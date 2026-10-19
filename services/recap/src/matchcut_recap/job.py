"""The render job: one slice of one fan's cut per run, as an event-driven Azure Container Apps Job.

A cut is split into slices (chunks) so it renders in minutes, not an hour: the API puts one
message per slice on the `cuts` Storage Queue and KEDA starts one job replica per message, in
parallel. Each replica starts the Studio API inside its container (it serves the Studio and the
match data to the headless renderer), plans the whole cut (deterministic, so every replica gets
the same frames), renders its own slice and uploads it. The replica that uploads the last slice
wins an atomic claim (a conditional blob create), joins the slices, mixes the sound once and
publishes the film. Every Azure call uses the job's managed identity: no keys anywhere.

    message: {"id": "c-...", "match": "kes-wcr-7", "side": "home" | null, "player": null | "Name",
              "lang": "en", "aspect": "9x16", "chunk": 3, "chunks": 10}
    blobs:   cuts/<id>.json (status), cuts/<id>.mp4 (the film), cuts/<id>.edl.json (the plan),
             cuts/<id>/claim-03 (a slice started), cuts/<id>/part-03.mp4 (a slice rendered),
             cuts/<id>/assemble (the assembler's claim)
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import subprocess
import sys
import time
import urllib.request
from argparse import Namespace
from pathlib import Path
from typing import Any

QUEUE = "cuts"
CONTAINER = "cuts"
SCRATCH = Path("/tmp/cuts")  # noqa: S108 - the job's own scratch space


def _status(blobs: Any, cut_id: str, **fields: Any) -> None:
    blobs.upload_blob(f"{cut_id}.json", json.dumps({"id": cut_id, **fields}).encode(), overwrite=True)


def _start_api(code: str, port: int = 8080) -> subprocess.Popen:
    env = {
        **{k: v for k, v in os.environ.items() if k != "MATCHCUT_STORAGE_ACCOUNT"},  # serve, never queue
        "HOST": "127.0.0.1",
        "PORT": str(port),
        "MATCHCUT_ACCESS_CODE_SHA256": hashlib.sha256(code.encode()).hexdigest(),
        "MATCHCUT_INSECURE_COOKIE": "1",  # loopback only, inside the job container
    }
    api = subprocess.Popen(["matchcut-api"], env=env)  # noqa: S607 - installed console script
    for _ in range(120):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/healthz", timeout=1):
                return api
        except OSError:
            time.sleep(0.5)
    api.kill()
    raise RuntimeError("the Studio API did not start")


def make_args(req: dict[str, Any], out: Path) -> Namespace:
    return Namespace(
        match=req["match"],
        side=req.get("side"),
        player=req.get("player"),
        lang=req.get("lang", "en"),
        aspect=req.get("aspect", "9x16"),
        fps=int(os.environ.get("MATCHCUT_FPS", "25")),
        base="http://127.0.0.1:8080",
        data=os.environ.get("MATCHCUT_DATA", "/app/out"),
        crowd=os.environ.get("MATCHCUT_CROWD", "/app/apps/studio/assets/audio/crowd"),
        out=str(out),
        ffmpeg="ffmpeg",
        ffprobe="ffprobe",
        gpu_less=True,
        stills=None,
        quality=None,
        chunk=int(req.get("chunk", 0)),
        chunks=int(req.get("chunks", 1)),
    )


def render_slice(blobs: Any, req: dict[str, Any]) -> None:
    """Render this message's slice; if it was the last one, assemble and publish the film."""
    from azure.core.exceptions import ResourceExistsError  # noqa: PLC0415

    from matchcut_recap.cli import assemble, make_part  # noqa: PLC0415

    cut_id, chunk, chunks = req["id"], int(req.get("chunk", 0)), int(req.get("chunks", 1))
    args = make_args(req, SCRATCH)
    blobs.upload_blob(f"{cut_id}/claim-{chunk:02d}", b"", overwrite=True)
    cut, part = make_part(args)
    with part.open("rb") as f:
        blobs.upload_blob(f"{cut_id}/part-{chunk:02d}.mp4", f, overwrite=True)
    done = [b.name for b in blobs.list_blobs(name_starts_with=f"{cut_id}/part-")]
    if len(done) < chunks:
        return
    try:  # exactly one replica assembles, even when several finish together
        blobs.upload_blob(f"{cut_id}/assemble", b"", overwrite=False)
    except ResourceExistsError:
        return
    parts = []
    for i in range(chunks):
        local = SCRATCH / f"part-{i:02d}.mp4"
        with local.open("wb") as f:
            blobs.download_blob(f"{cut_id}/part-{i:02d}.mp4").readinto(f)
        parts.append(local)
    film = assemble(args, cut, parts)
    with film.open("rb") as f:
        blobs.upload_blob(f"{cut_id}.mp4", f, overwrite=True)
    plan = json.dumps(cut.as_dict(), ensure_ascii=False).encode()
    blobs.upload_blob(f"{cut_id}.edl.json", plan, overwrite=True)
    _status(blobs, cut_id, status="done", finished=time.time(), film=f"{cut_id}.mp4")
    for name in [b.name for b in blobs.list_blobs(name_starts_with=f"{cut_id}/")]:
        blobs.delete_blob(name)


def main() -> None:
    from azure.identity import DefaultAzureCredential  # noqa: PLC0415
    from azure.storage.blob import BlobServiceClient  # noqa: PLC0415
    from azure.storage.queue import QueueClient  # noqa: PLC0415

    account = os.environ["MATCHCUT_STORAGE_ACCOUNT"]
    cred = DefaultAzureCredential()
    queue = QueueClient(f"https://{account}.queue.core.windows.net", QUEUE, credential=cred)
    service = BlobServiceClient(f"https://{account}.blob.core.windows.net", credential=cred)
    blobs = service.get_container_client(CONTAINER)
    msg = next(iter(queue.receive_messages(max_messages=1, visibility_timeout=3600)), None)
    if msg is None:
        print("no work")
        return
    req = json.loads(msg.content)
    SCRATCH.mkdir(parents=True, exist_ok=True)
    code = secrets.token_urlsafe(24)
    api = _start_api(code)
    try:
        os.environ["MATCHCUT_RENDER_CODE"] = code
        render_slice(blobs, req)
        queue.delete_message(msg)
    except Exception as exc:
        _status(blobs, req["id"], status="failed", error=f"{type(exc).__name__}: {exc}"[:300])
        queue.delete_message(msg)  # a broken request is reported, not retried forever
        raise
    finally:
        api.terminate()


if __name__ == "__main__":
    sys.exit(main())
