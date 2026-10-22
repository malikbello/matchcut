"""Fan cuts: request a personal highlight film, follow it, watch it.

The fast path, when the match's pieces exist (moment clips captioned in every language, title
and end cards, all rendered once by the job): the API plans the fan's cut, joins its pieces
without re-encoding and mixes the soundtrack in their language. Seconds, not a render.
The fallback, when a piece is missing: the whole film is rendered frame by frame, sliced across
the job's replicas.

Two back ends behind one interface:
- Azure (MATCHCUT_STORAGE_ACCOUNT set): pieces, status and films live in the `cuts` blob
  container; the fallback goes on the `cuts` Storage Queue, which starts the render job
  (Container Apps Job, KEDA queue trigger). Managed identity throughout: no keys.
- Local development: pieces in out/pieces; the fallback renderer runs as a background process.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

CUT_ID = re.compile(r"^c-[0-9a-f]{12}$")
ASPECTS = {"16x9", "9x16"}
# languages with voiced calls; Yoruba, Hausa and Igbo join when their voices do (ADR-0012)
CUT_LANGUAGES = {"en", "en-NG", "pcm", "fr", "es", "pt", "ar"}


@dataclass
class CutRequest:
    match: str
    lang: str
    aspect: str
    side: str | None = None
    player: str | None = None

    def message(self, cut_id: str) -> dict[str, Any]:
        return {
            "id": cut_id,
            "match": self.match,
            "side": self.side,
            "player": self.player,
            "lang": self.lang,
            "aspect": self.aspect,
        }


@dataclass
class Film:
    """A finished film: its size, and its bytes from `start` to `end` inclusive (HTTP ranges)."""

    size: int
    read: Callable[[int, int], Iterator[bytes]]


class CutAssembler(Protocol):
    def plan(self, req: CutRequest, manifest: dict[str, Any]) -> Any: ...
    def make(self, cut: Any, pieces: list[Path], work: Path) -> Path: ...


@dataclass
class Assembler:
    """Plans a fan's cut and makes it from stored pieces (matchcut_editing.assembly)."""

    data: Path  # feeds/, insights/, calls/, media/
    crowd: Path  # the crowd stems
    ffmpeg: str = "ffmpeg"

    def plan(self, req: CutRequest, manifest: dict[str, Any]) -> Any:
        from matchcut_editing.assembly import fan_cut  # noqa: PLC0415

        focus = {"player": req.player} if req.player else {"side": req.side or "home"}
        return fan_cut(self.data, req.match, focus, req.lang, req.aspect, manifest)

    def make(self, cut: Any, pieces: list[Path], work: Path) -> Path:
        from matchcut_editing.assembly import assemble_cut  # noqa: PLC0415

        return assemble_cut(cut, pieces, self.data / "media", self.crowd, work, self.ffmpeg)


def pieces_needed(cut: Any) -> list[str]:
    from matchcut_editing.assembly import piece_files  # noqa: PLC0415

    return piece_files(cut)


class CutStore(Protocol):
    def submit(self, req: CutRequest) -> str: ...
    def status(self, cut_id: str) -> dict[str, Any] | None: ...
    def film(self, cut_id: str) -> Film | None: ...


def progress(st: dict[str, Any], names: list[str]) -> dict[str, Any]:
    """A queued cut's live status from its slice markers: claims started, parts rendered."""
    started = sum(1 for n in names if "/claim-" in n)
    rendered = sum(1 for n in names if "/part-" in n)
    if not started:
        return st
    stage = "assembling" if any(n.endswith("/assemble") for n in names) else "rendering"
    return {**st, "status": stage, "rendered": rendered, "chunks": st.get("chunks", 1)}


def new_id() -> str:
    return f"c-{secrets.token_hex(6)}"


class AzureCuts:
    """One queue message per slice of the film; the render job's replicas take them in parallel."""

    def __init__(self, account: str, chunks: int = 10, assembler: CutAssembler | None = None):
        self.chunks = chunks
        self.assembler = assembler
        from azure.identity import DefaultAzureCredential  # noqa: PLC0415 - only in Azure
        from azure.storage.blob import BlobServiceClient  # noqa: PLC0415
        from azure.storage.queue import QueueClient  # noqa: PLC0415

        cred = DefaultAzureCredential()
        self.queue = QueueClient(f"https://{account}.queue.core.windows.net", "cuts", credential=cred)
        self.blobs = BlobServiceClient(
            f"https://{account}.blob.core.windows.net", credential=cred
        ).get_container_client("cuts")

    def submit(self, req: CutRequest) -> str:
        cut_id = new_id()
        self._status(cut_id, status="queued", chunks=self.chunks)
        threading.Thread(target=self._make, args=(cut_id, req), daemon=True).start()
        return cut_id

    def _status(self, cut_id: str, **fields: Any) -> None:
        self.blobs.upload_blob(
            f"{cut_id}.json", json.dumps({"id": cut_id, **fields}).encode(), overwrite=True
        )

    def _make(self, cut_id: str, req: CutRequest) -> None:
        """Assemble from the match's pieces if they are all there; otherwise render the film."""
        started = time.monotonic()
        prefix = f"pieces/{req.match}/{req.aspect}/"
        try:
            if self.assembler is None:
                raise LookupError("no assembler")
            manifest = json.loads(self.blobs.download_blob(f"{prefix}manifest.json").readall())
            cut = self.assembler.plan(req, manifest)
            needed = pieces_needed(cut)
            have = {b.name for b in self.blobs.list_blobs(name_starts_with=prefix)}
            if any(prefix + n not in have for n in needed):
                raise LookupError("pieces missing")
            self._status(cut_id, status="assembling")
            with tempfile.TemporaryDirectory() as tmp:
                work = Path(tmp)
                local = []
                for n in needed:
                    path = work / n
                    with path.open("wb") as f:
                        self.blobs.download_blob(prefix + n).readinto(f)
                    local.append(path)
                film = self.assembler.make(cut, local, work / "out")
                with film.open("rb") as f:
                    self.blobs.upload_blob(f"{cut_id}.mp4", f, overwrite=True)
            plan = json.dumps(cut.as_dict(), ensure_ascii=False).encode()
            self.blobs.upload_blob(f"{cut_id}.edl.json", plan, overwrite=True)
            took = round(time.monotonic() - started, 1)
            self._status(cut_id, status="done", film=f"{cut_id}.mp4", assembled=True, seconds=took)
        except Exception:
            self._status(cut_id, status="queued", chunks=self.chunks)
            for chunk in range(self.chunks):
                msg = {**req.message(cut_id), "chunk": chunk, "chunks": self.chunks}
                self.queue.send_message(json.dumps(msg))

    def request_clip(self, match: str, aspect: str, key: str, chunks: int = 4) -> None:
        """Render a clip (a moment or a window of play) for every fan: sliced on the job, once."""
        from azure.core.exceptions import ResourceExistsError  # noqa: PLC0415

        try:  # a double tap, or two fans clipping the same play, renders it once
            self.blobs.upload_blob(f"work/{match}/{aspect}/{key}/requested", b"", overwrite=False)
        except ResourceExistsError:
            return
        for chunk in range(chunks):
            msg = {
                "kind": "clip",
                "match": match,
                "aspect": aspect,
                "key": key,
                "chunk": chunk,
                "chunks": chunks,
            }
            self.queue.send_message(json.dumps(msg))

    def status(self, cut_id: str) -> dict[str, Any] | None:
        b = self.blobs.get_blob_client(f"{cut_id}.json")
        if not b.exists():
            return None
        st = json.loads(b.download_blob().readall())
        if st.get("status") == "queued":  # progress, from the slices' markers
            names = [x.name for x in self.blobs.list_blobs(name_starts_with=f"{cut_id}/")]
            return progress(st, names)
        return st

    def film(self, cut_id: str) -> Film | None:
        b = self.blobs.get_blob_client(f"{cut_id}.mp4")
        if not b.exists():
            return None

        def read(start: int, end: int) -> Iterator[bytes]:
            return b.download_blob(offset=start, length=end - start + 1).chunks()

        return Film(b.get_blob_properties().size, read)


class LocalCuts:
    """Development: render in a background process with the same CLI the job uses."""

    def __init__(
        self,
        out_dir: Path,
        base: str,
        code: str,
        pieces: Path | None = None,
        assembler: CutAssembler | None = None,
    ):
        self.out = out_dir
        self.base, self.code = base, code
        self.pieces, self.assembler = pieces, assembler
        self.clips: set[tuple[str, str, str]] = set()
        self.jobs: dict[str, dict[str, Any]] = {}
        self.lock = threading.Lock()

    def submit(self, req: CutRequest) -> str:
        cut_id = new_id()
        with self.lock:
            self.jobs[cut_id] = {"id": cut_id, "status": "rendering"}
        threading.Thread(target=self._run, args=(cut_id, req), daemon=True).start()
        return cut_id

    def request_clip(self, match: str, aspect: str, key: str) -> None:
        """Development: render the clip in a background process with the job's own command."""
        with self.lock:
            if (match, aspect, key) in self.clips:
                return
            self.clips.add((match, aspect, key))
        cmd = [
            sys.executable, "-m", "matchcut_recap.cli", "clip", "--match", match, "--aspect", aspect,
            "--keys", key, "--base", self.base, "--out", str(self.pieces or self.out / "pieces"),
        ]  # fmt: skip
        env = {**os.environ, "MATCHCUT_RENDER_CODE": self.code}
        threading.Thread(
            target=lambda: subprocess.run(cmd, env=env, capture_output=True, check=False),  # noqa: S603
            daemon=True,
        ).start()

    def _fast(self, cut_id: str, req: CutRequest) -> bool:
        """Assemble from out/pieces if every piece is there."""
        if self.pieces is None or self.assembler is None:
            return False
        folder = self.pieces / req.match / req.aspect
        manifest_path = folder / "manifest.json"
        if not manifest_path.is_file():
            return False
        started = time.monotonic()
        cut = self.assembler.plan(req, json.loads(manifest_path.read_text(encoding="utf-8")))
        local = [folder / n for n in pieces_needed(cut)]
        if not all(p.is_file() for p in local):
            return False
        with self.lock:
            self.jobs[cut_id] = {"id": cut_id, "status": "assembling"}
        film = self.assembler.make(cut, local, self.out / cut_id)
        with self.lock:
            self.jobs[cut_id] = {
                "id": cut_id, "status": "done", "film": film.name, "assembled": True,
                "seconds": round(time.monotonic() - started, 1),
            }  # fmt: skip
        return True

    def _run(self, cut_id: str, req: CutRequest) -> None:
        try:
            if self._fast(cut_id, req):
                return
        except Exception:  # noqa: S110 - a gap in the pieces means the film is rendered instead
            pass
        folder = self.out / cut_id
        cmd = [
            sys.executable,
            "-m",
            "matchcut_recap.cli",
            "make",
            "--match",
            req.match,
            "--lang",
            req.lang,
            "--aspect",
            req.aspect,
            "--base",
            self.base,
            "--out",
            str(folder),
        ]
        cmd += ["--player", req.player] if req.player else ["--side", req.side or "home"]
        r = subprocess.run(  # noqa: S603 - our own arguments (validated request fields)
            cmd,
            env={**os.environ, "MATCHCUT_RENDER_CODE": self.code},
            capture_output=True,
            text=True,
            check=False,
        )
        films = sorted(folder.glob("*.mp4"))
        with self.lock:
            if r.returncode == 0 and films:
                self.jobs[cut_id] = {"id": cut_id, "status": "done", "film": films[0].name}
            else:
                self.jobs[cut_id] = {"id": cut_id, "status": "failed", "error": (r.stderr or "")[-300:]}

    def status(self, cut_id: str) -> dict[str, Any] | None:
        with self.lock:
            return self.jobs.get(cut_id)

    def film(self, cut_id: str) -> Film | None:
        with self.lock:
            done = (self.jobs.get(cut_id) or {}).get("status") == "done"
        films = sorted((self.out / cut_id).glob("*.mp4")) if done else []
        return file_film(films[0]) if films else None


def file_film(path: Path) -> Film:
    def read(start: int, end: int) -> Iterator[bytes]:
        with path.open("rb") as f:
            f.seek(start)
            left = end - start + 1
            while left > 0 and (chunk := f.read(min(1 << 16, left))):
                left -= len(chunk)
                yield chunk

    return Film(path.stat().st_size, read)
