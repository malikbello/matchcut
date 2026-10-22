"""The pieces every fan's cut is joined from, each rendered once.

Moment clips (a goal with its celebration and replays, a goal conceded, a big chance) are drawn
by the Studio in render mode, captions off, sliced across job replicas like films. A finished
clip is then captioned once per voiced language: the Studio renders each verified caption card,
and each of the caller's lines (shared films are mostly watched muted), alone on a transparent
page and ffmpeg lays it over the clip with the broadcast fades. Cards are
stills held for their duration. Every piece is encoded with the same settings, so a fan's cut is
a lossless join plus a soundtrack mix (matchcut_editing.assembly), done in seconds.
"""

from __future__ import annotations

import gzip
import json
from pathlib import Path

from matchcut_editing.assembly import caption_command, card_command, run
from matchcut_editing.edl import (
    CHANCE_BEFORE_S,
    CONCEDED_BEFORE_S,
    RUN_UP_S,
    Segment,
    call_lines,
    clip_captions,
    clip_frames,
    end_card,
    moment_cut,
    title_card,
)
from matchcut_editing.inputs import LANGUAGE_NAMES, load

from matchcut_recap.render import Studio, concat

WARMUP_S = 2
POSTER_AT = {"goal": RUN_UP_S - 0.25, "conceded": CONCEDED_BEFORE_S - 0.25, "chance": CHANCE_BEFORE_S - 0.25}


def chunk_range(total: int, chunk: int, chunks: int) -> range:
    return range(total * chunk // chunks, total * (chunk + 1) // chunks)


def render_clip_part(
    studio: Studio, segments: list[Segment], fps: int, chunk: int, chunks: int, out: Path
) -> Path:
    """One slice of a moment clip, captions off, after two seconds of uncaptured warm-up."""
    specs = clip_frames(segments, fps)
    span = chunk_range(len(specs), chunk, chunks)
    warm = range(max(0, span.start - WARMUP_S * fps), span.start)
    return studio.render(
        specs[span.start : span.stop],
        fps,
        out,
        progress=lambda i, n, s: print(f"  frame {span.start + i}/{len(specs)}  {s:.0f} s", flush=True),
        first=span.start,
        warmup=[specs[i] for i in warm],
        crf=14,  # near-lossless: the clip is encoded once more when captioned per language
    )


def caption_clip(
    studio: Studio,
    key: str,
    segments: list[Segment],
    joined: Path,
    data: Path,
    match: str,
    langs: list[str],
    work: Path,
    ffmpeg: str = "ffmpeg",
) -> dict[str, Path]:
    """Caption a clean clip once per language: the verified caption cards, and the caller's
    words where the soundtrack voices them (the same plan the clip's soundtrack is mixed from)."""
    packages = {s.goal_t: s.duration for s in segments if s.kind == "package" and s.goal_t is not None}
    out: dict[str, Path] = {}
    for lang in langs:
        inp = load(data, match, lang)
        overlays = []
        for a, b, moment in clip_captions(segments, inp.cues, lang):
            png = work / f"{key}.{lang}.{moment}.png"
            if studio.caption(lang, moment, png):
                overlays.append((png, a, b))
        said = moment_cut(
            inp.feed, inp.cues, inp.calls, key, language=lang, aspect=studio.aspect,
            package_durations=packages, clip_durations=inp.durations,
        )  # fmt: skip
        for n, (a, b, words) in enumerate(call_lines(said, inp.calls)):
            png = work / f"{key}.{lang}.call{n:02d}.png"
            if studio.line(lang, words, png):
                overlays.append((png, a, b))
        piece = work / f"{key}.{lang}.mp4"
        run(caption_command(joined, overlays, piece, ffmpeg))
        out[lang] = piece
    return out


def finish_clip(
    studio: Studio,
    key: str,
    segments: list[Segment],
    parts: list[Path],
    data: Path,
    match: str,
    langs: list[str],
    work: Path,
    ffmpeg: str = "ffmpeg",
) -> dict[str, Path]:
    """Join a clip's slices, then caption it once per language; also a poster frame."""
    joined = concat(parts, work / f"{key}.clean.mp4", ffmpeg)
    out = caption_clip(studio, key, segments, joined, data, match, langs, work, ffmpeg)
    poster = work / f"{key}.jpg"
    at = POSTER_AT.get(key.split("-", maxsplit=1)[0], 1.5)  # the moment itself: the strike, the save
    run(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-ss",
            f"{at}",
            "-i",
            str(joined),
            "-frames:v",
            "1",
            str(poster),
        ]
    )
    out["poster"] = poster
    return out


def render_cards(
    studio: Studio,
    data: Path,
    match: str,
    focus_list: list[dict[str, str]],
    langs: list[str],
    work: Path,
    ffmpeg: str = "ffmpeg",
) -> dict[str, Path]:
    """Title cards for every focus and language, end cards for every language."""
    feed = json.loads(gzip.decompress((data / "feeds" / f"{match}.json.gz").read_bytes()))
    out: dict[str, Path] = {}
    for lang in langs:
        cards = [title_card(feed, f, lang, LANGUAGE_NAMES.get(lang, lang)) for f in focus_list]
        cards.append(end_card(feed, lang))
        for seg in cards:
            still = studio.card(seg.title, seg.sub, seg.t0, work / f"{seg.clip}.{lang}.png")
            piece = work / f"{seg.clip}.{lang}.mp4"
            run(card_command(still, seg.duration, piece, ffmpeg, fade_in=seg.clip != "end"))
            out[f"{seg.clip}.{lang}"] = piece
    return out
