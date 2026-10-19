"""The render job: one fan's cut per run, as an event-driven Azure Container Apps Job.

KEDA starts the job when a request lands on the `cuts` Storage Queue. The job takes one
message, starts the Studio API inside the container (it serves the Studio and the match
data to the headless renderer), makes the film, uploads it to Blob Storage and records the
status next to it. Every Azure call uses the job's managed identity: no keys anywhere.

    message: {"id": "c-...", "match": "kes-wcr-7", "side": "home" | null, "player": null | "Name",
              "lang": "en", "aspect": "9x16"}
    blobs:   cuts/<id>.json (status), cuts/<id>.mp4 (the film), cuts/<id>.edl.json (the plan)
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

QUEUE = "cuts"
CONTAINER = "cuts"


def _status(blobs, cut_id: str, **fields) -> None:
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


def main() -> None:
    from azure.identity import DefaultAzureCredential  # noqa: PLC0415
    from azure.storage.blob import BlobServiceClient  # noqa: PLC0415
    from azure.storage.queue import QueueClient  # noqa: PLC0415

    from matchcut_recap.cli import cmd_make  # noqa: PLC0415

    account = os.environ["MATCHCUT_STORAGE_ACCOUNT"]
    cred = DefaultAzureCredential()
    queue = QueueClient(f"https://{account}.queue.core.windows.net", QUEUE, credential=cred)
    blobs = BlobServiceClient(
        f"https://{account}.blob.core.windows.net", credential=cred
    ).get_container_client(CONTAINER)
    msg = next(iter(queue.receive_messages(max_messages=1, visibility_timeout=3600)), None)
    if msg is None:
        print("no work")
        return
    req = json.loads(msg.content)
    cut_id = req["id"]
    _status(blobs, cut_id, status="rendering", started=time.time())
    code = secrets.token_urlsafe(24)
    api = _start_api(code)
    out = Path("/tmp/cuts")  # noqa: S108 - the job's own scratch space
    try:
        os.environ["MATCHCUT_RENDER_CODE"] = code
        args = Namespace(
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
        )
        film = cmd_make(args)
        with film.open("rb") as f:
            blobs.upload_blob(f"{cut_id}.mp4", f, overwrite=True)
        edl = film.with_suffix(".edl.json")
        if edl.is_file():
            blobs.upload_blob(f"{cut_id}.edl.json", edl.read_bytes(), overwrite=True)
        _status(blobs, cut_id, status="done", finished=time.time(), film=f"{cut_id}.mp4")
        queue.delete_message(msg)
    except Exception as exc:
        _status(blobs, cut_id, status="failed", error=f"{type(exc).__name__}: {exc}"[:300])
        queue.delete_message(msg)  # a broken request is reported, not retried forever
        raise
    finally:
        api.terminate()


if __name__ == "__main__":
    sys.exit(main())
