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
             cuts/<id>/watch-03 (a finished replica watching a late slice),
             cuts/<id>/assemble (the assembler's claim)
"""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import secrets
import subprocess
import sys
import time
import urllib.request
from argparse import Namespace
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

QUEUE = "cuts"
CONTAINER = "cuts"
SCRATCH = Path("/tmp/cuts")  # noqa: S108 - the job's own scratch space
HEDGE = 1.3  # back up a slice once it runs this many times longer than the watcher's own slice
TAIL_SHARE = 5  # watch only when at most a fifth of the slices (and at least one) are missing


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


@dataclass
class Work:
    """A piece of sliced work: a film, or a moment clip. Replicas render slices in parallel;
    the one that completes the set finishes it (joins, captions, publishes) exactly once."""

    unit: str  # blob prefix for this work's markers and slices
    chunks: int
    published: Callable[[], bool]  # the finished output exists: late replicas must not touch it
    render_part: Callable[[int], Path]  # render slice i on this replica
    finish: Callable[[list[Path]], None]  # join the slices and publish


def _parts_missing(blobs: Any, unit: str, chunks: int) -> list[int]:
    have = {b.name for b in blobs.list_blobs(name_starts_with=f"{unit}/part-")}
    return [i for i in range(chunks) if f"{unit}/part-{i:02d}.mp4" not in have]


def _exists(blobs: Any, name: str) -> bool:
    return any(b.name == name for b in blobs.list_blobs(name_starts_with=name))


def _claim(blobs: Any, name: str) -> bool:
    """Create a marker blob only if it does not exist: an atomic claim across replicas."""
    from azure.core.exceptions import ResourceExistsError  # noqa: PLC0415

    try:
        blobs.upload_blob(name, b"", overwrite=False)
    except ResourceExistsError:
        return False
    return True


def run_sliced(
    blobs: Any,
    work: Work,
    chunk: int,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    """Render this replica's slice, back up a straggler when the work is nearly done, and
    finish the work if this replica completes it."""
    unit, chunks = work.unit, work.chunks
    if work.published():
        return  # a backup already finished it
    blobs.upload_blob(f"{unit}/claim-{chunk:02d}", b"", overwrite=True)
    started = clock()
    part = work.render_part(chunk)
    if work.published():
        return
    with part.open("rb") as f:
        blobs.upload_blob(f"{unit}/part-{chunk:02d}.mp4", f, overwrite=True)
    took = clock() - started
    # Backup tasks, as MapReduce runs them: once only the tail is left, one finished replica
    # watches each missing slice and renders it too if it runs HEDGE times longer than this one
    # did. A slow host or a lost replica then costs minutes, not the queue's hour.
    while missing := _parts_missing(blobs, unit, chunks):
        if len(missing) > max(1, chunks // TAIL_SHARE):
            return  # most slices are still in flight: nothing is late yet
        target = next((i for i in missing if _claim(blobs, f"{unit}/watch-{i:02d}")), None)
        if target is None:
            return  # every late slice already has a watcher
        deadline = started + HEDGE * took
        while clock() < deadline and target in _parts_missing(blobs, unit, chunks):
            sleep(10)
        if target in _parts_missing(blobs, unit, chunks):
            backup = work.render_part(target)
            if work.published():
                return
            with backup.open("rb") as f:
                blobs.upload_blob(f"{unit}/part-{target:02d}.mp4", f, overwrite=True)
    if work.published() or not _claim(blobs, f"{unit}/assemble"):
        return  # exactly one replica finishes, even when several complete together
    parts = []
    for i in range(chunks):
        local = SCRATCH / f"{unit.replace('/', '_')}-part-{i:02d}.mp4"
        with local.open("wb") as f:
            blobs.download_blob(f"{unit}/part-{i:02d}.mp4").readinto(f)
        parts.append(local)
    work.finish(parts)
    for name in [b.name for b in blobs.list_blobs(name_starts_with=f"{unit}/")]:
        blobs.delete_blob(name)


def render_slice(
    blobs: Any,
    req: dict[str, Any],
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    """A fan's whole film rendered frame by frame (the fallback when its pieces are not ready)."""
    from matchcut_recap.cli import assemble, make_part  # noqa: PLC0415

    cut_id = req["id"]
    planned: dict[str, Any] = {}

    def render_part(i: int) -> Path:
        cut, part = make_part(make_args({**req, "chunk": i}, SCRATCH))
        planned["cut"] = cut
        return part

    def finish(parts: list[Path]) -> None:
        cut = planned["cut"]
        film = assemble(make_args(req, SCRATCH), cut, parts)
        with film.open("rb") as f:
            blobs.upload_blob(f"{cut_id}.mp4", f, overwrite=True)
        plan = json.dumps(cut.as_dict(), ensure_ascii=False).encode()
        blobs.upload_blob(f"{cut_id}.edl.json", plan, overwrite=True)
        _status(blobs, cut_id, status="done", finished=time.time(), film=f"{cut_id}.mp4")

    work = Work(
        unit=cut_id,
        chunks=int(req.get("chunks", 1)),
        published=lambda: _exists(blobs, f"{cut_id}.mp4"),
        render_part=render_part,
        finish=finish,
    )
    run_sliced(blobs, work, int(req.get("chunk", 0)), clock, sleep)


CROWD = Path("apps/studio/assets/audio/crowd")  # the crowd stems the films are mixed with


def _senses() -> Any:
    """The QA agent's senses (Azure AI Speech and the vision model), when the job has an AI
    endpoint; on Azure it always has, through its managed identity."""
    from matchcut_recap.qa_agent import Perception  # noqa: PLC0415

    try:
        return Perception.from_env()
    except KeyError:
        return None


def piece_blob(match: str, aspect: str, name: str) -> str:
    return f"pieces/{match}/{aspect}/{name}"


def prewarm(
    blobs: Any, queue: Any, match: str, aspect: str, keys: list[str], langs: list[str], chunks: int = 4
) -> list[str]:
    """Queue every moment clip not yet published (sliced as a fan's request is) and the cards in
    every language not yet published, so reels and cuts are ready before the first fan asks.
    Run again at any time: what is published is skipped. Returns the clips queued."""
    queued = []
    for key in keys:
        if _exists(blobs, piece_blob(match, aspect, f"{key}.en.mp4")):
            continue
        blobs.upload_blob(f"work/{match}/{aspect}/{key}/requested", b"", overwrite=True)
        for chunk in range(chunks):
            msg = {
                "kind": "clip",
                "match": match,
                "aspect": aspect,
                "key": key,
                "chunk": chunk,
                "chunks": chunks,
            }
            queue.send_message(json.dumps(msg))
        queued.append(key)
    for lang in langs:
        if not _exists(blobs, piece_blob(match, aspect, f"end.{lang}.mp4")):
            queue.send_message(json.dumps({"kind": "cards", "match": match, "aspect": aspect, "lang": lang}))
    return queued


def render_clip(blobs: Any, req: dict[str, Any]) -> None:
    """A moment clip, rendered once for every fan: sliced like films, then captioned in every
    voiced language and published with its poster frame, and the match manifest updated."""
    from matchcut_editing.edl import clip_plan, segments_for  # noqa: PLC0415
    from matchcut_editing.inputs import VOICED, best_cues  # noqa: PLC0415

    from matchcut_recap.cli import write_manifest  # noqa: PLC0415
    from matchcut_recap.clips import finish_clip, finish_films, render_clip_part  # noqa: PLC0415
    from matchcut_recap.render import Studio  # noqa: PLC0415

    match, aspect, key = req["match"], req["aspect"], req["key"]
    a = make_args(req, SCRATCH)
    data = Path(a.data)
    code = os.environ["MATCHCUT_RENDER_CODE"]
    feed = json.loads(gzip.decompress((data / "feeds" / f"{match}.json.gz").read_bytes()))
    cues = best_cues(data / "insights" / f"{match}.jsonl", "en")

    def studio() -> Studio:
        return Studio(a.base, code, match, "en", aspect, gpu_less=True)

    def segments_with(st: Studio) -> list:
        """This clip's segments: a moment from the match's plan, or a window a fan clipped."""
        packages = {g["t"]: st.package_duration(g["t"]) for g in feed.get("goals", [])}
        plan = clip_plan(feed, cues, packages)
        manifest = write_manifest(SCRATCH, packages, plan, a.fps)
        blobs.upload_blob(piece_blob(match, aspect, "manifest.json"), manifest.read_bytes(), overwrite=True)
        return plan.get(key) or segments_for(key, packages)

    def render_part(i: int) -> Path:
        with studio() as st:
            segs = segments_with(st)
            return render_clip_part(
                st, segs, a.fps, i, int(req.get("chunks", 1)), SCRATCH / f"{key}-{i:02d}.mp4"
            )

    def finish(parts: list[Path]) -> None:
        with studio() as st:
            segs = segments_with(st)
            pieces = finish_clip(st, key, segs, parts, data, match, VOICED, SCRATCH)
        for lang, path in pieces.items():
            name = f"{key}.jpg" if lang == "poster" else f"{key}.{lang}.mp4"
            with path.open("rb") as f:
                blobs.upload_blob(piece_blob(match, aspect, name), f, overwrite=True)
        # each language's film, mixed and checked by the QA agent before any fan plays it
        for lang, (film, report) in finish_films(
            key, segs, data, match, VOICED, SCRATCH, CROWD, _senses()
        ).items():
            with film.open("rb") as f:
                blobs.upload_blob(piece_blob(match, aspect, film.name), f, overwrite=True)
            if report is not None:
                qa = json.dumps(report, ensure_ascii=False).encode()
                blobs.upload_blob(piece_blob(match, aspect, f"{key}.{lang}.qa.json"), qa, overwrite=True)

    work = Work(
        unit=f"work/{match}/{aspect}/{key}",
        chunks=int(req.get("chunks", 1)),
        published=lambda: _exists(blobs, piece_blob(match, aspect, f"{key}.en.mp4")),
        render_part=render_part,
        finish=finish,
    )
    run_sliced(blobs, work, int(req.get("chunk", 0)))


def render_card_set(blobs: Any, req: dict[str, Any]) -> None:
    """Title cards for every focus and the end card, in one language."""
    from matchcut_editing.inputs import focuses  # noqa: PLC0415

    from matchcut_recap.clips import render_cards  # noqa: PLC0415
    from matchcut_recap.render import Studio  # noqa: PLC0415

    match, aspect, lang = req["match"], req["aspect"], req["lang"]
    a = make_args(req, SCRATCH)
    data = Path(a.data)
    feed = json.loads(gzip.decompress((data / "feeds" / f"{match}.json.gz").read_bytes()))
    with Studio(a.base, os.environ["MATCHCUT_RENDER_CODE"], match, lang, aspect, gpu_less=True) as st:
        made = render_cards(st, data, match, focuses(feed), [lang], SCRATCH)
    for name, path in made.items():
        with path.open("rb") as f:
            blobs.upload_blob(piece_blob(match, aspect, f"{name}.mp4"), f, overwrite=True)


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
        kind = req.get("kind", "cut")
        {"cut": render_slice, "clip": render_clip, "cards": render_card_set}[kind](blobs, req)
        queue.delete_message(msg)
    except Exception as exc:
        if req.get("kind", "cut") == "cut":
            _status(blobs, req["id"], status="failed", error=f"{type(exc).__name__}: {exc}"[:300])
        queue.delete_message(msg)  # a broken request is reported, not retried forever
        raise
    finally:
        api.terminate()


if __name__ == "__main__":
    sys.exit(main())
