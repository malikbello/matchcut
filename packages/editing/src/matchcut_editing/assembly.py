"""Assembly: a fan's cut from pre-rendered pieces, in seconds.

The 3D render is the slow part (about 1.4 s a frame on CPU), so it happens once per moment, not
once per fan. Every piece is stored ready to join, encoded with exactly the same settings:

  moment clips   one per moment and format, rendered once (sliced across job replicas), then
                 captioned once per language by overlaying the Studio's own caption cards
  cards          the title card per focus and language, the end card per language

A fan's cut is then: join the pieces (no re-encode: identical settings, each starting on a
keyframe), mix the soundtrack in the fan's language, mux. Pure ffmpeg wiring; no browser.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from matchcut_editing.edl import Cut, build_cut
from matchcut_editing.inputs import LANGUAGE_NAMES, load
from matchcut_editing.mix import mix

# Every piece that is joined uses these, so the joins need no re-encode. Quality-led but capped
# for sharing: phones and social apps play it as it is, an 80 s film stays near 40 MB.
FPS = 25
VIDEO_ENCODE = [
    "-c:v", "libx264", "-preset", "medium", "-crf", "20",
    "-maxrate", "4500k", "-bufsize", "9000k", "-profile:v", "high",
    "-pix_fmt", "yuv420p", "-r", str(FPS), "-video_track_timescale", "12800",
]  # fmt: skip
CAPTION_IN_S, CAPTION_OUT_S = 0.16, 0.12  # the broadcast cut grammar: graphics cut in fast, leave faster


def piece_name(match: str, aspect: str, key: str, lang: str | None = None) -> str:
    """Where a piece lives in storage: moment clips and title cards per language."""
    return f"{match}/{aspect}/{key}.{lang}.mp4" if lang else f"{match}/{aspect}/{key}.mp4"


def caption_command(
    video: Path, overlays: list[tuple[Path, float, float]], out: Path, ffmpeg: str = "ffmpeg"
) -> list[str]:
    """Burn captions into a clip: each overlay is a full-frame transparent PNG of the Studio's
    caption card, shown from start to end seconds with the broadcast fade in and out."""
    cmd = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", str(video)]
    graph: list[str] = []
    base = "0:v"
    for i, (png, a, b) in enumerate(overlays, start=1):
        # the caption input ends with its window, so the clip keeps exactly its own frames
        cmd += ["-loop", "1", "-t", f"{b:.3f}", "-i", str(png)]
        out_at = max(a, b - CAPTION_OUT_S)
        graph.append(
            f"[{i}:v]format=rgba,fade=t=in:st={a:.3f}:d={CAPTION_IN_S}:alpha=1,"
            f"fade=t=out:st={out_at:.3f}:d={CAPTION_OUT_S}:alpha=1[c{i}]"
        )
        graph.append(f"[{base}][c{i}]overlay=0:0:eof_action=pass:enable='between(t,{a:.3f},{b:.3f})'[v{i}]")
        base = f"v{i}"
    if graph:
        cmd += ["-filter_complex", ";".join(graph), "-map", f"[{base}]"]
    else:
        cmd += ["-map", "0:v"]
    return [*cmd, "-an", *VIDEO_ENCODE, "-movflags", "+faststart", str(out)]


def card_command(
    png: Path, seconds: float, out: Path, ffmpeg: str = "ffmpeg", fade_in: bool = True
) -> list[str]:
    """A card clip from one rendered still: held for its duration, faded up from black."""
    vf = f"fps={FPS},format=yuv420p" + (",fade=t=in:st=0:d=0.3" if fade_in else "")
    return [
        ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-loop", "1", "-t", f"{seconds:.3f}",
        "-i", str(png), "-vf", vf, "-an", *VIDEO_ENCODE, "-movflags", "+faststart", str(out),
    ]  # fmt: skip


def join_command(pieces: list[Path], listing: Path, out: Path, ffmpeg: str = "ffmpeg") -> list[str]:
    """Join pieces encoded with VIDEO_ENCODE without re-encoding."""
    listing.write_text("".join(f"file '{p.resolve().as_posix()}'\n" for p in pieces), encoding="utf-8")
    return [
        ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0",
        "-i", str(listing), "-c", "copy", "-movflags", "+faststart", str(out),
    ]  # fmt: skip


def run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True)  # noqa: S603 - our own arguments


def mux_command(video: Path, audio: Path, out: Path, ffmpeg: str = "ffmpeg") -> list[str]:
    return [
        ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", str(video), "-i", str(audio),
        "-c:v", "copy", "-c:a", "copy", "-shortest", "-movflags", "+faststart", str(out),
    ]  # fmt: skip


def piece_files(cut: Cut) -> list[str]:
    """The stored pieces a cut joins, in order: its title card, its moment clips and the end
    card, all in the cut's language."""
    return [f"{key}.{cut.language}.mp4" for key in cut.clip_order()]


def fan_cut(data: Path, match: str, focus: dict[str, str], lang: str, aspect: str, manifest: dict) -> Cut:
    """Plan a fan's cut against the pieces' manifest (the replay packages the Studio measured)."""
    inp = load(data, match, lang)
    packages = {int(t): d for t, d in manifest["packages"].items()}
    return build_cut(
        inp.feed, inp.cues, inp.calls, focus=focus, language=lang, aspect=aspect,
        package_durations=packages, clip_durations=inp.durations,
        language_name=LANGUAGE_NAMES.get(lang, lang),
    )  # fmt: skip


def assemble_cut(
    cut: Cut, pieces: list[Path], media_root: Path, crowd_dir: Path, work: Path, ffmpeg: str = "ffmpeg"
) -> Path:
    """A fan's film from its pieces: a lossless join, the soundtrack mixed in their language,
    muxed. Seconds, not a render."""
    work.mkdir(parents=True, exist_ok=True)
    video = work / "video.mp4"
    run(join_command(pieces, work / "pieces.txt", video, ffmpeg))
    audio = mix(cut, media_root, crowd_dir, work / "audio.m4a", ffmpeg)
    film = work / "film.mp4"
    run(mux_command(video, audio, film, ffmpeg))
    return film
