"""Fan cuts: request a personal highlight film, follow it, watch it.

Two back ends behind one interface:
- Azure (MATCHCUT_STORAGE_ACCOUNT set): the request goes on the `cuts` Storage Queue, which
  starts the render job (Container Apps Job, KEDA queue trigger); status and film are read
  from the `cuts` blob container. Managed identity throughout: no keys.
- Local development: the renderer runs as a background process and writes to out/cuts.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import subprocess
import sys
import threading
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


class CutStore(Protocol):
    def submit(self, req: CutRequest) -> str: ...
    def status(self, cut_id: str) -> dict[str, Any] | None: ...
    def film(self, cut_id: str) -> Film | None: ...


def new_id() -> str:
    return f"c-{secrets.token_hex(6)}"


class AzureCuts:
    def __init__(self, account: str):
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
        self.blobs.upload_blob(
            f"{cut_id}.json", json.dumps({"id": cut_id, "status": "queued"}).encode(), overwrite=True
        )
        self.queue.send_message(json.dumps(req.message(cut_id)))
        return cut_id

    def status(self, cut_id: str) -> dict[str, Any] | None:
        b = self.blobs.get_blob_client(f"{cut_id}.json")
        if not b.exists():
            return None
        return json.loads(b.download_blob().readall())

    def film(self, cut_id: str) -> Film | None:
        b = self.blobs.get_blob_client(f"{cut_id}.mp4")
        if not b.exists():
            return None

        def read(start: int, end: int) -> Iterator[bytes]:
            return b.download_blob(offset=start, length=end - start + 1).chunks()

        return Film(b.get_blob_properties().size, read)


class LocalCuts:
    """Development: render in a background process with the same CLI the job uses."""

    def __init__(self, out_dir: Path, base: str, code: str):
        self.out = out_dir
        self.base, self.code = base, code
        self.jobs: dict[str, dict[str, Any]] = {}
        self.lock = threading.Lock()

    def submit(self, req: CutRequest) -> str:
        cut_id = new_id()
        with self.lock:
            self.jobs[cut_id] = {"id": cut_id, "status": "rendering"}
        threading.Thread(target=self._run, args=(cut_id, req), daemon=True).start()
        return cut_id

    def _run(self, cut_id: str, req: CutRequest) -> None:
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
