"""matchcut-recap: make a fan's cut of a match.

    matchcut-recap make --match kes-wcr-7 --side home --lang en --aspect 9x16
    matchcut-recap make --match kes-wcr-7 --player Quinouani --lang fr --aspect 16x9

Needs a running Matchcut API (it serves the Studio, the feed, the cues, the calls and the
voice files) and its access code in MATCHCUT_RENDER_CODE.
"""

from __future__ import annotations

import argparse
import gzip
import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any

from matchcut_editing.edl import Cut, build_cut, frames
from matchcut_editing.inputs import LANGUAGE_NAMES
from matchcut_editing.inputs import best_cues as _cues
from matchcut_editing.inputs import voice_durations as _durations
from matchcut_editing.mix import mix

from matchcut_recap.render import FILM_QUALITY, Studio, concat, mux

WARMUP_S = 2  # seconds of uncaptured frames before a slice or still, so motion settles


def chunk_range(total: int, chunk: int, chunks: int) -> range:
    """Frames of chunk `chunk` (0-based) when a film of `total` frames is split `chunks` ways."""
    return range(total * chunk // chunks, total * (chunk + 1) // chunks)


def make_part(a: argparse.Namespace) -> tuple[Cut, Path]:
    """Plan the cut and render this machine's slice of it (the whole film when chunks is 1).

    The plan is deterministic (same feed, cues, calls and Studio), so every render-job replica
    computes the same frame list and renders only its own slice."""
    root = Path(a.data)
    feed = json.loads(gzip.decompress((root / "feeds" / f"{a.match}.json.gz").read_bytes()))
    cues = _cues(root / "insights" / f"{a.match}.jsonl", a.lang)
    calls_path = root / "calls" / f"{a.match}.json"
    calls = (
        [c for c in json.loads(calls_path.read_text(encoding="utf-8")) if c["language"] == a.lang]
        if calls_path.is_file()
        else []
    )
    files = {c["audio"] for c in cues + calls if c.get("audio")}
    durations = _durations(files, root / "media", a.ffprobe)
    focus = {"player": a.player} if a.player else {"side": a.side}
    stem = _stem(a)
    code = os.environ.get("MATCHCUT_RENDER_CODE", "")
    quality = json.loads(a.quality) if (a.quality or "").startswith("{") else (a.quality or FILM_QUALITY)
    with Studio(a.base, code, a.match, a.lang, a.aspect, gpu_less=a.gpu_less, quality=quality) as studio:
        packages = {g["t"]: studio.package_duration(g["t"]) for g in feed.get("goals", [])}
        cut = build_cut(
            feed,
            cues,
            calls,
            focus=focus,
            language=a.lang,
            aspect=a.aspect,
            package_durations=packages,
            clip_durations=durations,
            language_name=str(LANGUAGE_NAMES.get(a.lang) or a.lang),
        )
        stem.with_suffix(".edl.json").write_text(
            json.dumps(cut.as_dict(), ensure_ascii=False, indent=1), encoding="utf-8"
        )
        print(f"cut: {len(cut.segments)} segments, {cut.duration:.1f} s, {len(cut.audio)} sounds")
        specs = frames(cut, a.fps)
        if a.stills:
            # QA and thumbnails: chosen moments as PNGs. Two seconds of frames run first, so
            # animation blends and camera moves settle exactly as they do in the film.
            wanted = sorted({min(int(float(x) * a.fps), len(specs) - 1) for x in a.stills.split(",")})
            for w in wanted:
                for i in range(max(0, w - WARMUP_S * a.fps), w):
                    studio.step(specs[i], i, a.fps)
                studio.still(specs[w], w, a.fps, stem.parent / f"{stem.name}-{w / a.fps:05.1f}s.png")
            print(f"stills -> {stem.parent}")
            return cut, stem.parent
        span = chunk_range(len(specs), a.chunk, a.chunks)
        warm = range(max(0, span.start - WARMUP_S * a.fps), span.start)
        part = stem.parent / f"{stem.name}.part{a.chunk:02d}.mp4"
        studio.render(
            specs[span.start : span.stop],
            a.fps,
            part,
            a.ffmpeg,
            progress=lambda i, n, s: print(f"  frame {span.start + i}/{len(specs)}  {s:.0f} s", flush=True),
            first=span.start,
            warmup=[specs[i] for i in warm],
        )
    return cut, part


STRIKE_FACING_DEG = 30  # a strike more than this far off its target reads as wrong


def motion_report(samples: list[dict[str, Any]], fps: int) -> dict[str, Any]:
    """Score how the drawn ball meets the players over a cut (the realism gate).

    contact: at every frame where an action's striking bone holds the ball, the gap between
    bone and ball (a foot that misses the ball by a metre reads at once on television).
    carry: while a player runs with the ball (held at least 0.4 s, so a pass still arriving
    from behind a runner is not counted), where the ball sits along his heading; a ball behind
    a running player is the error fans notice first.
    """
    gaps = sorted(s["strike"]["dist"] for s in samples if s and s.get("strike"))
    runs = [
        (i, s["carry"])
        for i, s in enumerate(samples)
        if s
        and s.get("carry")
        and s["carry"]["speed"] > 1.4
        and not s["carry"]["acting"]
        and s["carry"].get("heldMs", 1e9) >= 400  # an established dribble, not a ball still arriving
    ]
    ahead = sorted(c["ahead"] for _, c in runs)
    behind = [i for i, c in runs if c["ahead"] < -0.1]

    def q(xs: list[float], f: float) -> float | None:
        return round(xs[min(len(xs) - 1, int(f * len(xs)))], 3) if xs else None

    report = {
        "frames": len(samples),
        "contact_frames": len(gaps),
        "contact_gap_m": {"median": q(gaps, 0.5), "p95": q(gaps, 0.95), "max": gaps[-1] if gaps else None},
        "carry_frames": len(runs),
        "carry_ahead_m": {"p5": q(ahead, 0.05), "median": q(ahead, 0.5), "p95": q(ahead, 0.95)},
        "ball_behind_runner_frames": len(behind),
        "ball_behind_runner_s": round(len(behind) / fps, 2),
        "ball_behind_at_s": [round(i / fps, 2) for i in behind[:20]],
    }
    # ball jumps: during continuous play the drawn ball never moves faster than a ball can (a snap
    # to a foot, a teleport between two tracked positions); 1.4 m a frame at 25 fps is 35 m/s.
    # The second after a shot is exempt: a struck shot legitimately flies that fast.
    jumps = []
    for i in range(1, len(samples)):
        a_, b_ = samples[i - 1], samples[i]
        if not (a_ and b_ and a_.get("kind") == b_.get("kind") == "live") or b_.get("shot"):
            continue
        if abs((b_["t"] or 0) - (a_["t"] or 0) - 1000 / fps) > 1:
            continue  # a cut to other play
        step = sum((x - y) ** 2 for x, y in zip(a_["ball"], b_["ball"], strict=True)) ** 0.5
        if step > 1.4 * 25 / fps:
            jumps.append(round(i / fps, 2))
    report["ball_jumps"] = len(jumps)
    report["ball_jump_at_s"] = jumps[:20]
    # strikes: at the contact frame a shooter (or passer) faces where the ball goes; a scorer
    # kicking without facing the goal reads at once
    offs = sorted(
        a["off"]
        for s in samples
        if s
        for a in s.get("actors", [])
        if a.get("aims") and "off" in a and abs(a["at"] - a["contact"]) <= 1 / fps
    )
    report["strike_facing_off_deg"] = {
        "median": q(offs, 0.5),
        "p95": q(offs, 0.95),
        "max": offs[-1] if offs else None,
    }
    # bodies: during play no two players are drawn through one another
    live = [s for s in samples if s and s.get("kind") == "live"]
    overlaps = sum(1 for s in live if (s.get("bodies") or {}).get("overlaps"))
    report["bodies_overlap_frames"] = overlaps
    report["pass"] = bool(
        (not gaps or (q(gaps, 0.95) or 0) <= 0.2)
        and len(behind) <= max(1, len(runs) // 100)
        and len(jumps) <= 2
        and (not offs or (q(offs, 0.95) or 0) <= STRIKE_FACING_DEG)
        and overlaps <= max(1, len(live) // 100)
    )
    return report


def cmd_realism(a: argparse.Namespace) -> dict[str, Any]:
    """Step through a cut without capturing pixels and measure ball and player contact."""
    root = Path(a.data)
    feed = json.loads(gzip.decompress((root / "feeds" / f"{a.match}.json.gz").read_bytes()))
    cues = _cues(root / "insights" / f"{a.match}.jsonl", a.lang)
    focus = {"player": a.player} if a.player else {"side": a.side}
    code = os.environ.get("MATCHCUT_RENDER_CODE", "")
    with Studio(a.base, code, a.match, a.lang, a.aspect, gpu_less=a.gpu_less, quality=FILM_QUALITY) as studio:
        packages = {g["t"]: studio.package_duration(g["t"]) for g in feed.get("goals", [])}
        cut = build_cut(
            feed, cues, [], focus=focus, language=a.lang, aspect=a.aspect,
            package_durations=packages, clip_durations={},
        )  # fmt: skip
        specs = frames(cut, a.fps)
        assert studio.page
        studio.page.evaluate("() => window.__render.paint(false)")  # measure motion, draw nothing
        samples = []
        shots = [e[0] for e in feed.get("events", []) if e[1] == "shot"]
        for i, spec in enumerate(specs):
            studio.step(spec, i, a.fps)
            probe = studio.probe() if spec["kind"] != "card" else None
            t = spec.get("t")
            shot = t is not None and any(0 <= t - s_ <= 1200 for s_ in shots)  # a struck shot flies fast
            samples.append({**probe, "t": t, "kind": spec["kind"], "shot": shot} if probe else None)
    report = motion_report(samples, a.fps)
    print(json.dumps(report, indent=1))
    return report


def assemble(a: argparse.Namespace, cut: Cut, parts: list[Path]) -> Path:
    """Join the rendered slices, mix the sound once and mux the film."""
    stem = _stem(a)
    video = concat(parts, stem.with_suffix(".video.mp4"), a.ffmpeg)
    audio = mix(cut, Path(a.data) / "media", Path(a.crowd), stem.with_suffix(".audio.m4a"), a.ffmpeg)
    final = mux(video, audio, stem.with_suffix(".mp4"), a.ffmpeg)
    for tmp in (video, audio, *parts):
        tmp.unlink(missing_ok=True)
    print(f"film -> {final}")
    return final


def _stem(a: argparse.Namespace) -> Path:
    out_dir = Path(a.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    who = (a.player or a.side).lower().replace(" ", "-")
    return out_dir / f"{a.match}-{who}-{a.lang}-{a.aspect}"


def cmd_make(a: argparse.Namespace) -> Path:
    """One machine: render every frame, then assemble (a chunk alone with --chunks > 1)."""
    cut, part = make_part(a)
    if a.stills or a.chunks > 1:
        return part
    return assemble(a, cut, [part])


def _pieces_dir(a: argparse.Namespace) -> Path:
    d = Path(a.out) / a.match / a.aspect
    d.mkdir(parents=True, exist_ok=True)
    return d


def write_manifest(folder: Path, packages: dict[int, float], plan: dict[str, list], fps: int) -> Path:
    """What the API needs to assemble cuts from the pieces: each goal's replay package length (the
    Studio measures it) and every clip's duration."""
    manifest = {
        "fps": fps,
        "packages": {str(t): d for t, d in packages.items()},
        "clips": {k: round(sum(s.duration for s in segs), 3) for k, segs in plan.items()},
    }
    path = folder / "manifest.json"
    path.write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    return path


def cmd_clip(a: argparse.Namespace) -> list[Path]:
    """Render moment clips (all slices on this machine) and caption them in every language."""
    from matchcut_editing.edl import clip_plan, segments_for  # noqa: PLC0415
    from matchcut_editing.inputs import VOICED  # noqa: PLC0415

    from matchcut_recap.clips import finish_clip, render_clip_part  # noqa: PLC0415

    data, folder = Path(a.data), _pieces_dir(a)
    langs = a.langs.split(",") if a.langs else VOICED
    feed = json.loads(gzip.decompress((data / "feeds" / f"{a.match}.json.gz").read_bytes()))
    cues = _cues(data / "insights" / f"{a.match}.jsonl", "en")
    code = os.environ.get("MATCHCUT_RENDER_CODE", "")
    made: list[Path] = []
    with Studio(a.base, code, a.match, "en", a.aspect, gpu_less=a.gpu_less) as studio:
        packages = {g["t"]: studio.package_duration(g["t"]) for g in feed.get("goals", [])}
        plan = clip_plan(feed, cues, packages)
        write_manifest(folder, packages, plan, a.fps)
        keys = a.keys.split(",") if a.keys else list(plan)
        for key in keys:
            segs = plan.get(key) or segments_for(key, packages)  # a moment, or a window of play
            part = render_clip_part(studio, segs, a.fps, 0, 1, folder / f"{key}.part00.mp4")
            pieces = finish_clip(studio, key, segs, [part], data, a.match, langs, folder, a.ffmpeg)
            made += list(pieces.values())
            print(f"clip {key}: {', '.join(sorted(pieces))}", flush=True)
    return made


def cmd_captions(a: argparse.Namespace) -> list[Path]:
    """Caption rendered clips again from their clean renders (new lines, new languages): the
    Studio draws only the overlays, never a frame of play."""
    from matchcut_editing.edl import segments_for  # noqa: PLC0415
    from matchcut_editing.inputs import VOICED  # noqa: PLC0415

    from matchcut_recap.clips import caption_clip  # noqa: PLC0415

    data, folder = Path(a.data), _pieces_dir(a)
    langs = a.langs.split(",") if a.langs else VOICED
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    packages = {int(t): d for t, d in manifest["packages"].items()}
    clean = sorted(p.name.removesuffix(".clean.mp4") for p in folder.glob("*.clean.mp4"))
    keys = a.keys.split(",") if a.keys else clean
    code = os.environ.get("MATCHCUT_RENDER_CODE", "")
    made: list[Path] = []
    with Studio(a.base, code, a.match, "en", a.aspect, gpu_less=a.gpu_less) as studio:
        for key in keys:
            joined = folder / f"{key}.clean.mp4"
            segs = segments_for(key, packages)
            pieces = caption_clip(studio, key, segs, joined, data, a.match, langs, folder, a.ffmpeg)
            made += list(pieces.values())
            print(f"captions {key}: {', '.join(sorted(pieces))}", flush=True)
    return made


def cmd_prewarm(a: argparse.Namespace) -> list[str]:
    """Azure: queue every moment clip and card set of a match on the render job (signed in as
    the deployer: Azure CLI or any DefaultAzureCredential source)."""
    from azure.identity import DefaultAzureCredential  # noqa: PLC0415
    from azure.storage.blob import BlobServiceClient  # noqa: PLC0415
    from azure.storage.queue import QueueClient  # noqa: PLC0415
    from matchcut_editing.edl import clip_plan  # noqa: PLC0415
    from matchcut_editing.inputs import VOICED, read_feed  # noqa: PLC0415

    from matchcut_recap.job import CONTAINER, QUEUE, prewarm  # noqa: PLC0415

    data = Path(a.data)
    feed = read_feed(data, a.match)
    cues = _cues(data / "insights" / f"{a.match}.jsonl", "en")
    keys = list(clip_plan(feed, cues, {g["t"]: 0.0 for g in feed.get("goals", [])}))  # keys only
    cred = DefaultAzureCredential()
    blobs = BlobServiceClient(f"https://{a.account}.blob.core.windows.net", credential=cred)
    queue = QueueClient(f"https://{a.account}.queue.core.windows.net", QUEUE, credential=cred)
    langs = a.langs.split(",") if a.langs else VOICED
    queued = prewarm(blobs.get_container_client(CONTAINER), queue, a.match, a.aspect, keys, langs, a.chunks)
    print(f"{len(keys)} clips in the plan, {len(queued)} queued: {', '.join(queued) or 'none'}")
    return queued


def cmd_cards(a: argparse.Namespace) -> list[Path]:
    """Render the title cards (every focus, every language) and the end cards."""
    from matchcut_editing.inputs import VOICED, focuses  # noqa: PLC0415

    from matchcut_recap.clips import render_cards  # noqa: PLC0415

    data, folder = Path(a.data), _pieces_dir(a)
    langs = a.langs.split(",") if a.langs else VOICED
    feed = json.loads(gzip.decompress((data / "feeds" / f"{a.match}.json.gz").read_bytes()))
    code = os.environ.get("MATCHCUT_RENDER_CODE", "")
    with Studio(a.base, code, a.match, "en", a.aspect, gpu_less=a.gpu_less) as studio:
        made = render_cards(studio, data, a.match, focuses(feed), langs, folder, a.ffmpeg)
    print(f"cards: {len(made)}")
    return list(made.values())


def main(argv: list[str] | None = None) -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # pyright: ignore[reportAttributeAccessIssue]
    p = argparse.ArgumentParser(prog="matchcut-recap")
    sub = p.add_subparsers(dest="cmd", required=True)
    m = sub.add_parser("make", help="make a fan's cut")
    m.add_argument("--match", required=True)
    who = m.add_mutually_exclusive_group(required=True)
    who.add_argument("--side", choices=["home", "away"])
    who.add_argument("--player")
    m.add_argument("--lang", default="en")
    m.add_argument("--aspect", choices=["16x9", "9x16"], default="16x9")
    m.add_argument("--fps", type=int, default=30)
    m.add_argument("--base", default="http://127.0.0.1:8765")
    m.add_argument("--data", default="out")
    m.add_argument("--crowd", default="apps/studio/assets/audio/crowd")
    m.add_argument("--out", default="out/cuts")
    m.add_argument("--ffmpeg", default=shutil.which("ffmpeg") or "ffmpeg")
    m.add_argument("--ffprobe", default=shutil.which("ffprobe") or "ffprobe")
    m.add_argument(
        "--gpu-less", action="store_true", help="servers without a GPU: render WebGL on Mesa llvmpipe"
    )
    m.add_argument(
        "--quality", help='a Studio tier (high) or JSON overrides, e.g. {"base": "high", "gtao": true}'
    )
    m.add_argument(
        "--stills", help="seconds of the film to save as PNGs instead of rendering it, e.g. 1.5,14,22"
    )
    m.add_argument("--chunk", type=int, default=0, help="this machine's slice of the film (0-based)")
    m.add_argument("--chunks", type=int, default=1, help="slices the film is split into across machines")
    r = sub.add_parser("realism", help="measure how the drawn ball meets the players over a cut")
    r.add_argument("--match", required=True)
    rwho = r.add_mutually_exclusive_group(required=True)
    rwho.add_argument("--side", choices=["home", "away"])
    rwho.add_argument("--player")
    r.add_argument("--lang", default="en")
    r.add_argument("--aspect", choices=["16x9", "9x16"], default="9x16")
    r.add_argument("--fps", type=int, default=25)
    r.add_argument("--base", default="http://127.0.0.1:8765")
    r.add_argument("--data", default="out")
    r.add_argument("--gpu-less", action="store_true")
    for name, helptext in (
        ("clip", "render moment clips and caption them per language"),
        ("captions", "caption rendered clips again from their clean renders"),
        ("cards", "render title and end cards"),
    ):
        c = sub.add_parser(name, help=helptext)
        c.add_argument("--match", required=True)
        c.add_argument("--aspect", choices=["16x9", "9x16"], default="9x16")
        c.add_argument("--fps", type=int, default=25)
        c.add_argument("--langs", help="comma-separated; default: every voiced language")
        c.add_argument("--keys", help="clip keys (goal-<t>, chance-<t>...); default: all")
        c.add_argument("--base", default="http://127.0.0.1:8765")
        c.add_argument("--data", default="out")
        c.add_argument("--out", default="out/pieces")
        c.add_argument("--ffmpeg", default=shutil.which("ffmpeg") or "ffmpeg")
        c.add_argument("--gpu-less", action="store_true")
    w = sub.add_parser("prewarm", help="Azure: queue every moment clip and card set on the render job")
    w.add_argument("--match", required=True)
    w.add_argument("--account", required=True, help="the storage account with the cuts queue")
    w.add_argument("--aspect", choices=["16x9", "9x16"], default="9x16")
    w.add_argument("--langs", help="comma-separated; default: every voiced language")
    w.add_argument("--chunks", type=int, default=4, help="slices per clip (job replicas in parallel)")
    w.add_argument("--data", default="out")
    args = p.parse_args(argv)
    if args.cmd == "prewarm":
        cmd_prewarm(args)
        return
    if args.cmd == "clip":
        cmd_clip(args)
        return
    if args.cmd == "captions":
        cmd_captions(args)
        return
    if args.cmd == "cards":
        cmd_cards(args)
        return
    if args.cmd == "realism":
        sys.exit(0 if cmd_realism(args)["pass"] else 1)
    cmd_make(args)


if __name__ == "__main__":
    main()
