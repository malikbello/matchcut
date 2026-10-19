"""Cut the Studio's crowd stems from CC0 stadium recordings (Freesound), loudness-normalised.

    python crowd_stems.py <ffmpeg> <recordings dir> <out dir>

Stems, as a game audio team layers a crowd:
  bed      steady crowd murmur, looped under everything
  chant    a stadium song: rises with attacking danger (the build-up)
  roar_*   goal reactions, one picked at random per goal
Loudness follows EBU R128 (integrated LUFS) so layers mix predictably.
Sources and licences: recordings/SOURCES.json, credited in assets/audio/crowd/CREDITS.txt.
"""

import subprocess
import sys
from pathlib import Path

ffmpeg, src, out = sys.argv[1], Path(sys.argv[2]), Path(sys.argv[3])
out.mkdir(parents=True, exist_ok=True)

# name: (recording id, start s, end s, target LUFS, fade in s, fade out s)
STEMS = {
    "bed_a": ("528799", 14, 50, -24, 1.5, 1.5),
    "bed_b": ("241630", 22, 56, -24, 1.5, 1.5),
    "chant": ("733614", 1, 17.5, -20, 1.0, 1.0),
    "roar_1": ("829455", 0.6, 13, -14, 0.05, 2.5),
    "roar_2": ("829455", 15.2, 33, -14, 0.05, 3.0),
    "roar_3": ("829455", 38.2, 57, -14, 0.05, 3.0),
    "roar_4": ("241630", 0.7, 14, -14, 0.05, 3.0),
    "roar_5": ("528799", 2.5, 16, -14, 0.3, 3.0),
}

for name, (rid, a, b, lufs, fi, fo) in STEMS.items():
    dur = b - a
    af = (
        f"atrim={a}:{b},asetpts=PTS-STARTPTS,"
        f"afade=t=in:st=0:d={fi},afade=t=out:st={dur - fo}:d={fo},"
        f"loudnorm=I={lufs}:TP=-1.5:LRA=11,aresample=44100"
    )
    target = out / f"{name}.mp3"
    subprocess.run(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(src / f"{rid}.mp3"),
            "-af",
            af,
            "-ac",
            "2",
            "-c:a",
            "libmp3lame",
            "-b:a",
            "128k",
            str(target),
        ],
        check=True,
    )
    print(f"{name:7s} {dur:5.1f}s -> {target.stat().st_size // 1024} KB")
