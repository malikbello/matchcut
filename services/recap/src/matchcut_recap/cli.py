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
import subprocess
import sys
from pathlib import Path

from matchcut_recap.edl import Cut, build_cut, frames
from matchcut_recap.mix import mix
from matchcut_recap.render import FILM_QUALITY, Studio, concat, mux

WARMUP_S = 2  # seconds of uncaptured frames before a slice or still, so motion settles

LANGUAGE_NAMES = {
    "en": "English",
    "en-NG": "Nigerian English",
    "pcm": "Naija",
    "yo": "Yorùbá",
    "ha": "Hausa",
    "ig": "Igbo",
    "ar": "العربية",
    "es": "Español",
    "fr": "Français",
    "pt": "Português",
}


def _cues(path: Path, lang: str) -> list[dict]:
    """The best cue per moment in this language (a verified line replaces the plain card)."""
    rows = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x]
    rank = {"verified": 2, "plain": 0, "rejected": -1}
    best: dict[str, dict] = {}
    for r in rows:
        if r["language"] != lang and not (r["language"] == "en" and r["status"] == "plain"):
            continue
        prev = best.get(r["moment_id"])
        score = rank[r["status"]] + (r["language"] == lang)
        if prev is None or score > rank[prev["status"]] + (prev["language"] == lang):
            best[r["moment_id"]] = r
    return sorted(best.values(), key=lambda r: r["t_ms"])


def _durations(files: set[str], media_root: Path, ffprobe: str) -> dict[str, float]:
    out = {}
    for f in files:
        r = subprocess.run(  # noqa: S603 - our own arguments
            [
                ffprobe,
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "csv=p=0",
                str(media_root / f),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        try:
            out[f] = float(r.stdout.strip())
        except ValueError:
            continue
    return out


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
    args = p.parse_args(argv)
    cmd_make(args)


if __name__ == "__main__":
    main()
