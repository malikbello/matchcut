"""Media QA: a finished film must say and show exactly what was verified.

The Verifier checks every line before it is voiced; this checks the film after it is made. The
plan the film was cut from says what should be heard (each call and verified line, at its time)
and what should be read on screen (each caption card and commentary line, in its window).
Perception is Azure AI's (speech to text for the soundtrack, a vision model reading frames);
the judgement is this code's: no model judges another model's work.

    heard   enough of a voiced line's words are in the transcript around its time
    read    enough of a caption's words are in the text read off the frame in its window
    loud    the soundtrack sits at the loudness social platforms normalise to

A film fails QA if any line is not heard, any caption is not read, or the level is off.
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter
from dataclasses import asdict, dataclass, field
from typing import Any

from matchcut_editing.edl import Cut, call_lines

HEARD = 0.6  # of a line's words in the transcript (names a recogniser spells its own way are allowed)
READ = 0.8  # of a caption's words in the text read off the frame
TARGET_LUFS, LUFS_TOLERANCE = -16.0, 2.0
LISTEN_BEFORE_S, LISTEN_AFTER_S = 0.5, 6.0  # where a voiced line's words may land in the transcript


@dataclass
class Spoken:
    at: float  # film seconds the voice starts
    text: str
    role: str  # call | line


@dataclass
class Shown:
    start: float
    end: float
    text: str
    kind: str  # caption | call

    @property
    def middle(self) -> float:
        return round((self.start + self.end) / 2, 2)


def expectations(cut: Cut, cues: list[dict], calls: list[dict]) -> tuple[list[Spoken], list[Shown]]:
    """What the film must say and show, from the plan it was cut from."""
    said = {c["audio"]: c["text"] for c in [*calls, *cues] if c.get("audio") and c.get("text")}
    spoken = [Spoken(round(e.at, 2), said[e.file], e.role) for e in cut.audio if e.file in said]
    captions = {c["moment_id"]: c["text"] for c in cues if c.get("text")}
    shown = [Shown(a, b, captions[m], "caption") for a, b, m in cut.captions if m in captions]
    shown += [Shown(a, b, text, "call") for a, b, text in call_lines(cut, calls)]
    return spoken, sorted(shown, key=lambda s: s.start)


def words(text: str) -> list[str]:
    """Comparable words in any script: case, accents and punctuation set aside; digits kept as they
    are (8th and 8 both give 8, so a recogniser's 'eighth' is the one thing that can miss)."""
    folded = unicodedata.normalize("NFKD", text.casefold())
    plain = "".join(ch for ch in folded if not unicodedata.combining(ch))
    return [w for w in re.split(r"[^\w]+", plain) if w]


def recall(expected: str, got: str) -> float:
    """The share of the expected words found in what was heard or read (order-free, with repeats)."""
    want = Counter(words(expected))
    if not want:
        return 1.0
    have = Counter(words(got))
    return sum(min(n, have[w]) for w, n in want.items()) / sum(want.values())


@dataclass
class QAReport:
    film: str
    language: str
    lines: list[dict[str, Any]] = field(default_factory=list)
    captions: list[dict[str, Any]] = field(default_factory=list)
    lufs: float | None = None
    passed: bool = False

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def judge(
    film: str,
    language: str,
    spoken: list[Spoken],
    shown: list[Shown],
    transcript: list[tuple[float, float, str]],
    reads: dict[float, str],
    lufs: float | None,
) -> QAReport:
    """The verdict: every voiced line heard around its time, every caption read in its window, the
    level right. transcript: (start s, end s, text) phrases; reads: frame second -> text read."""
    report = QAReport(film, language, lufs=lufs)
    for sp in spoken:
        near = " ".join(
            t for a, b, t in transcript if b >= sp.at - LISTEN_BEFORE_S and a <= sp.at + LISTEN_AFTER_S
        )
        r = recall(sp.text, near)
        report.lines.append(
            {"at": sp.at, "role": sp.role, "text": sp.text, "recall": round(r, 2), "heard": r >= HEARD}
        )
    for sh in shown:
        r = recall(sh.text, reads.get(sh.middle, ""))
        report.captions.append(
            {"at": sh.middle, "kind": sh.kind, "text": sh.text, "recall": round(r, 2), "read": r >= READ}
        )
    loud = lufs is not None and abs(lufs - TARGET_LUFS) <= LUFS_TOLERANCE
    report.passed = all(x["heard"] for x in report.lines) and all(x["read"] for x in report.captions) and loud
    return report
