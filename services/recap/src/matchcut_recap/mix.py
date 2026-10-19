"""The mixer: the film's soundtrack with ffmpeg, the way a broadcast mix is built.

crowd   two bed loops under everything; the stadium song rises in the film's high windows
        (goal packages, big chances); a real goal roar on every goal
voice   the play-by-play calls and verified lines, each at its planned time
ducking the crowd is side-chain compressed by the voice, so commentary always reads
master  loudness-normalised to -16 LUFS (the common target for streaming and social video)
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from matchcut_recap.edl import Cut

ROARS = ["roar_1", "roar_2", "roar_3", "roar_4", "roar_5"]


def _between(windows: list[tuple[float, float]]) -> str:
    return "+".join(f"between(t,{a:.2f},{b:.2f})" for a, b in windows) or "0"


def mix_command(cut: Cut, media_root: Path, crowd_dir: Path, out: Path, ffmpeg: str = "ffmpeg") -> list[str]:
    """Build the ffmpeg command (pure, so it is tested without running ffmpeg)."""
    d = cut.duration
    args = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y"]
    args += ["-stream_loop", "-1", "-i", str(crowd_dir / "bed_a.mp3")]
    args += ["-stream_loop", "-1", "-i", str(crowd_dir / "bed_b.mp3")]
    args += ["-stream_loop", "-1", "-i", str(crowd_dir / "chant.mp3")]
    filters = [
        f"[0:a]atrim=0:{d:.2f},volume=0.5[b0]",
        f"[1:a]atrim=0:{d:.2f},volume=0.4[b1]",
        f"[2:a]atrim=0:{d:.2f},volume='0.85*({_between(cut.crowd_high)})':eval=frame[ch]",
    ]
    crowd = ["[b0]", "[b1]", "[ch]"]
    voices: list[str] = []
    n = 3
    roar_i = 0
    for ev in cut.audio:
        ms = int(ev.at * 1000)
        if ev.role == "roar":
            path = crowd_dir / f"{ROARS[roar_i % len(ROARS)]}.mp3"
            roar_i += 1
            label = f"r{n}"
            filters.append(f"[{n}:a]adelay={ms}|{ms},volume=1.1[{label}]")
            crowd.append(f"[{label}]")
        else:
            path = media_root / ev.file
            label = f"v{n}"
            filters.append(
                f"[{n}:a]aresample=48000,aformat=channel_layouts=stereo,adelay={ms}|{ms},volume=1.7[{label}]"
            )
            voices.append(f"[{label}]")
        args += ["-i", str(path)]
        n += 1
    filters.append(
        f"{''.join(crowd)}amix=inputs={len(crowd)}:normalize=0:duration=longest,atrim=0:{d:.2f}[crowd]"
    )
    if voices:
        filters.append(
            f"{''.join(voices)}amix=inputs={len(voices)}:normalize=0:duration=longest,apad,atrim=0:{d:.2f}[vo]"
        )
        filters.append("[vo]asplit=2[vo_key][vo_mix]")
        filters.append(
            "[crowd][vo_key]sidechaincompress=threshold=0.04:ratio=6:attack=15:release=450[ducked]"
        )
        filters.append("[ducked][vo_mix]amix=inputs=2:normalize=0:duration=first[mix]")
    else:
        filters.append("[crowd]anull[mix]")
    filters.append("[mix]loudnorm=I=-16:TP=-1.5:LRA=11,aresample=48000[out]")
    args += [
        "-filter_complex",
        ";".join(filters),
        "-map",
        "[out]",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-t",
        f"{d:.2f}",
        str(out),
    ]
    return args


def mix(cut: Cut, media_root: Path, crowd_dir: Path, out: Path, ffmpeg: str = "ffmpeg") -> Path:
    subprocess.run(mix_command(cut, media_root, crowd_dir, out, ffmpeg), check=True)  # noqa: S603 - our own arguments
    return out
