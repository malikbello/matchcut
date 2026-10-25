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
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from difflib import SequenceMatcher
from typing import Any

from matchcut_editing.edl import Cut, call_lines

HEARD = 0.6  # of a line's words in the transcript (names a recogniser spells its own way are allowed)
READ = 0.8  # of a caption's words in the text read off the frame
TARGET_LUFS, LUFS_TOLERANCE = -16.0, 2.0
# where a voiced line's words may land in the transcript: from just before it starts to a little
# after it ends (a long line runs past any fixed window, and its tail would read as unheard)
LISTEN_BEFORE_S, LISTEN_AFTER_S = 0.5, 1.5
LISTEN_MIN_S = 6.0  # the window when a line's length is not known
NEAR = 0.66  # a word heard nearly as written counts ("bat" for "but", "don't" for "don")
# languages no recogniser hears word for word yet (Azure has no Pidgin model): their lines are
# checked for being voiced where the plan puts them, not word by word, and the report says so
PRESENCE_ONLY = {"pcm"}


@dataclass
class Spoken:
    at: float  # film seconds the voice starts
    text: str
    role: str  # call | line
    duration: float = 0.0  # seconds of voice, when known

    @property
    def until(self) -> float:
        """The latest film second its words may be heard."""
        return self.at + max(LISTEN_MIN_S, self.duration + LISTEN_AFTER_S)


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
    spoken = [
        Spoken(round(e.at, 2), said[e.file], e.role, round(e.duration, 2))
        for e in cut.audio
        if e.file in said
    ]
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


def recall(expected: str, got: str, names: Iterable[str] = ()) -> float:
    """The share of the expected words found in what was heard or read (order-free, with repeats).
    names: words a recogniser cannot be held to (the league's invented names, which it spells its
    own way or in another script); they are set aside, and a line made only of names counts as
    found if anything was said there. A word found nearly as written counts (NEAR)."""
    every = words(expected)
    skip = {w for n in names for w in words(n)}
    want = [w for w in every if w not in skip]
    have = Counter(words(got))
    if not every:
        return 1.0
    if not want:
        return 1.0 if have else 0.0
    found = 0
    for w in want:
        near = (
            w
            if have[w] > 0
            else next(
                (
                    h
                    for h in have
                    if have[h] > 0 and len(w) >= 3 and SequenceMatcher(None, w, h).ratio() >= NEAR
                ),
                None,
            )
        )
        if near is not None:
            have[near] -= 1
            found += 1
    return found / len(want)


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
    names: Iterable[str] = (),
) -> QAReport:
    """The verdict: every voiced line heard around its time, every caption read in its window, the
    level right. transcript: (start s, end s, text) phrases; reads: frame second -> text read;
    names: the league's names, set aside when listening (on screen they must read exactly)."""
    names = list(names)
    report = QAReport(film, language, lufs=lufs)
    for sp in spoken:
        near = " ".join(t for a, b, t in transcript if b >= sp.at - LISTEN_BEFORE_S and a <= sp.until)
        r = recall(sp.text, near, names)
        presence = language in PRESENCE_ONLY
        report.lines.append(
            {
                "at": sp.at,
                "role": sp.role,
                "text": sp.text,
                "recall": round(r, 2),
                "heard": bool(words(near)) if presence else r >= HEARD,
                "check": "voiced" if presence else "words",
                "heard_as": near[:300],  # what the recogniser heard there: a failure explains itself
            }
        )
    for sh in shown:
        got = reads.get(sh.middle, "")
        r = recall(sh.text, got)
        report.captions.append(
            {
                "at": sh.middle,
                "kind": sh.kind,
                "text": sh.text,
                "recall": round(r, 2),
                "read": r >= READ,
                "read_as": got[:300],
            }
        )
    loud = lufs is not None and abs(lufs - TARGET_LUFS) <= LUFS_TOLERANCE
    report.passed = all(x["heard"] for x in report.lines) and all(x["read"] for x in report.captions) and loud
    return report


def summary(report: dict[str, Any]) -> dict[str, Any]:
    """A QA report in brief, for a fan's screen: lines heard, captions read, the level, and
    whether the lines were checked word by word (or, with no recogniser, for voice only)."""
    lines, caps = report.get("lines", []), report.get("captions", [])
    return {
        "passed": bool(report.get("passed")),
        "heard": f"{sum(1 for x in lines if x.get('heard'))}/{len(lines)}",
        "read": f"{sum(1 for x in caps if x.get('read'))}/{len(caps)}",
        "lufs": report.get("lufs"),
        "words": not any(x.get("check") == "voiced" for x in lines),
        "issues": issues(report),
    }


def issues(report: dict[str, Any], most: int = 3) -> list[dict[str, Any]]:
    """What made a film fail, first things first: each line not heard, each caption not read
    (with its film second and its words), and a level off target."""
    out: list[dict[str, Any]] = [
        {"kind": "not heard", "at": x.get("at"), "text": x.get("text", "")}
        for x in report.get("lines", [])
        if not x.get("heard")
    ]
    out += [
        {"kind": "not read", "at": x.get("at"), "text": x.get("text", "")}
        for x in report.get("captions", [])
        if not x.get("read")
    ]
    lufs = report.get("lufs")
    if lufs is not None and abs(lufs - TARGET_LUFS) > LUFS_TOLERANCE:
        out.append({"kind": "level", "at": None, "text": f"{lufs} LUFS, not {TARGET_LUFS:g}"})
    if report.get("error"):
        out.append({"kind": "not checked", "at": None, "text": str(report["error"])[:160]})
    return sorted(out, key=lambda i: (i["at"] is None, i["at"] or 0))[:most]
