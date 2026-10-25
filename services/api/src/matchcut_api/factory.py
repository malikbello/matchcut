"""The Recap Factory's runs: start one, follow it, play its films (matchcut_editing.factory).

On Azure a run is blobs in the `cuts` container and one message per film on the `cuts` queue,
which starts one render job replica per film. Runs cost Azure credit, so they are rationed: one at
a time, a cooldown after each, and a cap per day, all claimed atomically in blob storage (two
judges pressing Run together start one run). In local development the same blobs live on disk
and the films are made in this process.
"""

from __future__ import annotations

import json
import secrets
import threading
import time
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from azure.core.exceptions import ResourceExistsError, ResourceNotFoundError
from matchcut_editing.factory import root, run_state

from matchcut_api.cuts import Film, file_film

RUN_TIMEOUT_S = 3600  # a run with films still waiting after this long lost its messages
STATE_TTL_S = 1.5  # every watcher polls; the blobs are read at most this often


class BusyError(Exception):
    """A run is still making its films."""


class RationedError(Exception):
    """No run now: `seconds` until the next one is allowed (None: none left today)."""

    def __init__(self, seconds: float | None):
        super().__init__(seconds)
        self.seconds = seconds


@dataclass
class Factory:
    blobs: Any  # the `cuts` container client (or DiskBlobs)
    queue: Any  # the `cuts` queue client (or LocalRunner)
    cooldown_s: int = 1800
    runs_per_day: int = 6
    clock: Callable[[], float] = time.time
    _cache: dict[str, tuple[float, dict[str, Any]]] = field(default_factory=dict, repr=False)

    def _get(self, name: str) -> dict[str, Any] | None:
        try:
            return json.loads(self.blobs.download_blob(name).readall())
        except (ResourceNotFoundError, ValueError):
            return None

    def _put(self, name: str, value: dict[str, Any], overwrite: bool = True) -> None:
        self.blobs.upload_blob(name, json.dumps(value, ensure_ascii=False).encode(), overwrite=overwrite)

    def latest(self, match: str, aspect: str) -> dict[str, Any] | None:
        head = self._get(root(match, aspect) + "latest.json")
        return self._get(f"{root(match, aspect)}{head['run']}/run.json") if head else None

    def state(self, match: str, aspect: str, fresh: bool = False) -> dict[str, Any] | None:
        """The latest run as the screen shows it, or None before the first run."""
        key = f"{match}/{aspect}"
        held = self._cache.get(key)
        if held and not fresh and 0 <= self.clock() - held[0] < STATE_TTL_S:
            return held[1]
        run = self.latest(match, aspect)
        out = None
        if run is not None:
            prefix = f"{root(match, aspect)}{run['run']}/"
            names = [
                b.name
                for b in self.blobs.list_blobs(name_starts_with=prefix)
                if b.name.endswith(".json") and not b.name.endswith((".qa.json", "/run.json"))
            ]
            with ThreadPoolExecutor(max_workers=8) as pool:
                found = dict(zip(names, pool.map(self._get, names), strict=True))
            films = {n[len(prefix) : -len(".json")]: v for n, v in found.items() if v}
            now = self.clock()
            out = run_state(run, films, now)
            if not out["finished"] and now - run["started"] > RUN_TIMEOUT_S:
                out["finished"] = True
            out["next_run_in"] = max(0, round(run["started"] + self.cooldown_s - now))
        if out is not None:
            self._cache[key] = (self.clock(), out)
        return out

    def _ration(self, match: str, aspect: str, now: float) -> None:
        """Claim this run's place: one per cooldown window and at most runs_per_day a day."""
        base = f"{root(match, aspect)}claims/"
        if self.cooldown_s > 0:
            window = int(now // self.cooldown_s)
            try:
                self.blobs.upload_blob(f"{base}window-{window}", b"", overwrite=False)
            except ResourceExistsError:
                raise RationedError((window + 1) * self.cooldown_s - now) from None
        day = time.strftime("%Y-%m-%d", time.gmtime(now))
        for n in range(self.runs_per_day):
            try:
                self.blobs.upload_blob(f"{base}{day}-{n}", b"", overwrite=False)
                return
            except ResourceExistsError:
                continue
        raise RationedError(None)

    def start(self, match: str, aspect: str, films: list[dict[str, Any]], pieces: dict[str, int]) -> dict:
        """Start a run: every film on the queue at once, so the job scales out to make them."""
        now = self.clock()
        last = self.state(match, aspect, fresh=True)
        if last is not None:
            if not last["finished"]:
                raise BusyError
            if last["next_run_in"] > 0:
                raise RationedError(last["next_run_in"])
        self._ration(match, aspect, now)
        run_id = f"f-{secrets.token_hex(6)}"
        base = root(match, aspect)
        record = {
            "run": run_id,
            "match": match,
            "aspect": aspect,
            "started": now,
            "films": films,
            "pieces": pieces,
        }
        self._put(f"{base}{run_id}/run.json", record)
        self._put(f"{base}latest.json", {"run": run_id})
        for f in films:
            msg = {"kind": "fan", "run": run_id, "film": f["id"], "match": match, "aspect": aspect}
            self.queue.send_message(json.dumps({**msg, "focus": f["focus"], "lang": f["lang"]}))
        return self.state(match, aspect, fresh=True) or {}

    def film(self, match: str, aspect: str, run: str, film: str) -> Film | None:
        name = f"{root(match, aspect)}{run}/{film}.mp4"
        if isinstance(self.blobs, DiskBlobs):
            path = self.blobs.root / name
            return file_film(path) if path.is_file() else None
        b = self.blobs.get_blob_client(name)
        if not b.exists():
            return None

        def read(start: int, end: int) -> Iterator[bytes]:
            return b.download_blob(offset=start, length=end - start + 1).chunks()

        return Film(b.get_blob_properties().size, read)


# ---------------------------------------------------------------- local development


class _Download:
    def __init__(self, path: Path):
        if not path.is_file():
            raise ResourceNotFoundError(str(path))
        self.path = path

    def readall(self) -> bytes:
        return self.path.read_bytes()

    def readinto(self, f: Any) -> int:
        data = self.path.read_bytes()
        f.write(data)
        return len(data)


@dataclass
class DiskBlobs:
    """The container calls the factory and the job make, on local disk (blob names are paths)."""

    root: Path
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def upload_blob(self, name: str, data: Any, overwrite: bool = False) -> None:
        path = self.root / name
        with self._lock:
            if path.exists() and not overwrite:
                raise ResourceExistsError(name)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data if isinstance(data, bytes) else data.read())

    def download_blob(self, name: str) -> _Download:
        return _Download(self.root / name)

    def list_blobs(self, name_starts_with: str = "") -> Iterator[SimpleNamespace]:
        folder = self.root / name_starts_with.rsplit("/", 1)[0] if "/" in name_starts_with else self.root
        if folder.is_dir():
            for p in sorted(folder.rglob("*")):
                name = p.relative_to(self.root).as_posix()
                if p.is_file() and name.startswith(name_starts_with):
                    yield SimpleNamespace(name=name)


@dataclass
class LocalRunner:
    """The queue, in local development: each film is made in this process, a few at a time."""

    blobs: DiskBlobs
    data: Path
    pool: ThreadPoolExecutor = field(default_factory=lambda: ThreadPoolExecutor(max_workers=3))

    def send_message(self, content: str) -> None:
        self.pool.submit(self._make, json.loads(content))

    def _make(self, req: dict[str, Any]) -> None:
        # the render job's own code, which the development workspace has installed
        from matchcut_recap.job import _senses, render_fan  # noqa: PLC0415

        try:
            render_fan(self.blobs, req, _senses(), self.data)
        except Exception as exc:
            name = f"{root(req['match'], req['aspect'])}{req['run']}/{req['film']}.json"
            body = {"status": "failed", "error": f"{type(exc).__name__}: {exc}"[:300]}
            self.blobs.upload_blob(name, json.dumps(body).encode(), overwrite=True)
