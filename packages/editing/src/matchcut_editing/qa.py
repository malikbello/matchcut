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
from functools import cache
from typing import Any

from num2words import num2words

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
# a line with fewer words than this once the names are set aside ("Atenção a Quinouani...") cannot
# be judged word by word: a recogniser that splits the name into words ("aqui não ani") swallows
# the one short word left. It is checked for being voiced where the plan puts it, and says so.
MIN_WORDS = 3
# a recogniser writes a number it hears in digits or in words ("Seventy-three minutes" opening a
# sentence, "one-nil", "ninth"): either way it was heard. Spelled with num2words in the film's
# language; a score's nought as football says it is not a number speller's word
SPELLED = {"en": "en", "en-NG": "en", "fr": "fr", "es": "es", "pt": "pt", "ar": "ar"}
NOUGHT = {"en": ("nil",), "en-NG": ("nil",)}
ORDINAL = re.compile(r"^(\d+)(st|nd|rd|th|e|er|eme|o|a)$")  # 9th, 53e, 8o (8.º once folded)


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

    @property
    def alone(self) -> tuple[float, float]:
        """The line's own stretch of the film, listened to again on its own when the whole film's
        transcript missed it (a short call straight after another voice, under the crowd)."""
        end = self.at + self.duration + LISTEN_BEFORE_S if self.duration else self.until
        return max(0.0, self.at - LISTEN_BEFORE_S), end


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
    are, an ordinal with its mark (8.º is one word, 8o, like 8th)."""
    text = re.sub(r"(\d)\.\s?(?=[ºª])", r"\1", text)
    folded = unicodedata.normalize("NFKD", text.casefold())
    plain = "".join(ch for ch in folded if not unicodedata.combining(ch))
    return [w for w in re.split(r"[^\w]+", plain) if w]


@cache
def spelled(number: str, language: str) -> tuple[tuple[str, ...], ...]:
    """A number token as a recogniser may write it in words in the film's language: 73 as
    'seventy-three', 9th as 'ninth', 53e as 'cinquante-troisième', a score's 0 as 'nil'."""
    lang = SPELLED.get(language)
    ordinal = ORDINAL.match(number)
    if lang is None or not (number.isdigit() or ordinal):
        return ()
    forms: list[str] = []
    try:
        if ordinal:
            forms.append(num2words(int(ordinal.group(1)), lang=lang, to="ordinal"))
        else:
            forms.append(num2words(int(number), lang=lang))
    except (NotImplementedError, OverflowError, ValueError):  # a form the language has no speller for
        pass
    if number == "0":
        forms += NOUGHT.get(language, ())
    return tuple(tuple(words(f)) for f in forms if words(f))


def _take(have: Counter[str], w: str) -> bool:
    """Take w, or a word heard nearly as written (NEAR), out of what was heard. A word with a
    number in it is found exactly or spelled out, never nearly ('9th' is not 'the')."""
    nearly = len(w) >= 3 and not any(ch.isdigit() for ch in w)
    near = (
        w
        if have[w] > 0
        else next(
            (h for h in have if have[h] > 0 and nearly and SequenceMatcher(None, w, h).ratio() >= NEAR),
            None,
        )
    )
    if near is None:
        return False
    have[near] -= 1
    return True


def _take_all(have: Counter[str], form: tuple[str, ...]) -> bool:
    """Take every word of a number said in words out of what was heard, or none of them. Exactly
    as spelled: nearly is not enough for a number ('fifteen' is not 'fifty')."""
    need = Counter(form)
    if any(have[w] < n for w, n in need.items()):
        return False
    have.subtract(need)
    return True


def recall(expected: str, got: str, names: Iterable[str] = (), language: str = "") -> float:
    """The share of the expected words found in what was heard or read (order-free, with repeats).
    names: words a recogniser cannot be held to (the league's invented names, which it spells its
    own way or in another script); they are set aside, and a line made only of names counts as
    found if anything was said there. A word found nearly as written counts (NEAR), and so does a
    number heard in words in the film's language."""
    every = words(expected)
    skip = {w for n in names for w in words(n)}
    want = [w for w in every if w not in skip]
    have = Counter(words(got))
    if not every:
        return 1.0
    if not want:
        return 1.0 if have else 0.0
    found = sum(1 for w in want if _take(have, w) or any(_take_all(have, f) for f in spelled(w, language)))
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
        r = recall(sp.text, near, names, language)
        skip = {w for n in names for w in words(n)}
        presence = language in PRESENCE_ONLY or len([w for w in words(sp.text) if w not in skip]) < MIN_WORDS
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
    report.passed = verdict(report)
    return report


def verdict(report: QAReport) -> bool:
    """Every line heard, every caption read, the level right."""
    loud = report.lufs is not None and abs(report.lufs - TARGET_LUFS) <= LUFS_TOLERANCE
    return all(x["heard"] for x in report.lines) and all(x["read"] for x in report.captions) and loud


def heard_again(
    report: QAReport,
    i: int,
    sp: Spoken,
    transcript: list[tuple[float, float, str]],
    names: Iterable[str] = (),
) -> None:
    """Judge line i again on what was heard when its own stretch of the film (Spoken.alone) was
    listened to on its own. The same words must be heard; the report keeps both hearings."""
    again = judge(report.film, report.language, [sp], [], transcript, {}, report.lufs, names).lines[0]
    if again["heard"]:
        report.lines[i] = {**again, "listened": "again", "first_heard_as": report.lines[i]["heard_as"]}
        report.passed = verdict(report)


def summary(report: dict[str, Any]) -> dict[str, Any]:
    """A QA report in brief, for a fan's screen: lines heard word for word, lines checked for
    voice only (Naija, and lines of a name and a word or two), captions read and the level."""
    lines, caps = report.get("lines", []), report.get("captions", [])
    worded = [x for x in lines if x.get("check") != "voiced"]
    voiced = [x for x in lines if x.get("check") == "voiced"]
    return {
        "passed": bool(report.get("passed")),
        "heard": f"{sum(1 for x in worded if x.get('heard'))}/{len(worded)}",
        "voiced": f"{sum(1 for x in voiced if x.get('heard'))}/{len(voiced)}" if voiced else None,
        "again": sum(1 for x in lines if x.get("listened") == "again"),  # heard on a second listen
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
