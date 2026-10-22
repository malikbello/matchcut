"""What a cut is made from, read the same way by the render job and the API.

A match's data folder holds feeds/<match>.json.gz (positions and events), insights/<match>.jsonl
(the verified cues in every language), calls/<match>.json (play-by-play calls) and media/
(the voiced lines and calls).
"""

from __future__ import annotations

import gzip
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

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
# languages with voiced calls today; Yoruba, Hausa and Igbo join when their voices do (ADR-0012)
VOICED = ["en", "en-NG", "pcm", "fr", "es", "pt", "ar"]


def best_cues(path: Path, lang: str) -> list[dict]:
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


def voice_durations(files: set[str], media_root: Path, ffprobe: str = "ffprobe") -> dict[str, float]:
    """Seconds of each voiced file, measured (the soundtrack never overlaps two lines)."""
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


@dataclass
class MatchInputs:
    feed: dict
    cues: list[dict]
    calls: list[dict]
    durations: dict[str, float]


def load(data: Path, match: str, lang: str, ffprobe: str = "ffprobe") -> MatchInputs:
    """Feed, best cues and calls in one language, and the length of every voice file they use."""
    feed = json.loads(gzip.decompress((data / "feeds" / f"{match}.json.gz").read_bytes()))
    cues = best_cues(data / "insights" / f"{match}.jsonl", lang)
    calls_path = data / "calls" / f"{match}.json"
    calls = (
        [c for c in json.loads(calls_path.read_text(encoding="utf-8")) if c["language"] == lang]
        if calls_path.is_file()
        else []
    )
    files = {c["audio"] for c in cues + calls if c.get("audio")}
    return MatchInputs(feed, cues, calls, voice_durations(files, data / "media", ffprobe))


def focuses(feed: dict) -> list[dict[str, str]]:
    """Every focus a fan can choose: either club, or any player who appears in the match."""
    names = sorted({p["name"] for p in feed.get("players", {}).values()})
    return [{"side": "home"}, {"side": "away"}, *({"player": n} for n in names)]
