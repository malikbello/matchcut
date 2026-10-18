"""The Verifier: deterministic checks every AI line must pass before it airs.

No model judges another model here. A line passes only if each number in it
matches a fact it cites, each proper name in it belongs to a cited fact, it cites
only facts that exist, and it stays short and clean. A failed line never airs;
the plain card stays on screen.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

from matchcut_contracts import Fact

MAX_WORDS = 30
MAX_CHARS = 200
NUMBER = re.compile(r"\d+(?:[.,]\d+)?")
# house style: no em dashes on screen (a colon, comma or full stop reads better)
EM_DASH = chr(0x2014)
# betting language, certainty claims and real-world marks never appear on screen
BANNED = re.compile(r"\b(bet|bets|betting|odds|wager|guaranteed|premier league|epl)\b", re.IGNORECASE)


@dataclass
class Verdict:
    checks: dict[str, bool]
    problems: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(self.checks.values())


def _number_forms(value: float | int | str) -> set[str]:
    if isinstance(value, str):
        return {n.replace(",", ".") for n in NUMBER.findall(value)}
    forms = {f"{value:g}", str(value)}
    if isinstance(value, float):
        forms |= {f"{value:.1f}", f"{value:.2f}"}
        if value.is_integer():
            forms.add(str(int(value)))
    return forms


def numbers_in(text: str) -> list[str]:
    return [n.replace(",", ".") for n in NUMBER.findall(text)]


def _names_in(text: str, names: Iterable[str]) -> set[str]:
    return {n for n in names if n and re.search(rf"(?<!\w){re.escape(n)}(?!\w)", text)}


def bind_numbers(text: str, cited: Sequence[str], facts: Sequence[Fact]) -> list[tuple[str, str]]:
    """Attribute each number in a code-built line to the first cited fact that states it."""
    by_id = {f.fact_id: f for f in facts}
    cited_facts = [by_id[c] for c in cited if c in by_id]
    out = []
    for n in numbers_in(text):
        owner = next((f for f in cited_facts if n in _number_forms(f.value) | _number_forms(f.label)), None)
        out.append((n, owner.fact_id if owner else ""))
    return out


def verify_line(
    text: str,
    cited: Sequence[str],
    facts: Sequence[Fact],
    known_names: Iterable[str],
    numbers: Sequence[tuple[str, str]] | None = None,
) -> Verdict:
    """Check one line. ``numbers`` lists every number as written, in order, with the fact it comes
    from (attributed generation); code-built lines may omit it and are bound automatically."""
    by_id = {f.fact_id: f for f in facts}
    cited_facts = [by_id[c] for c in cited if c in by_id]
    problems: list[str] = []

    unknown = [c for c in cited if c not in by_id]
    if unknown:
        problems.append(f"cites facts that do not exist: {', '.join(unknown)}")

    # numbers may come from a cited fact's value or its code-written label (e.g. 'last 5 minutes')
    allowed: set[str] = set()
    for f in cited_facts:
        allowed |= _number_forms(f.value) | _number_forms(f.label)
    loose = [n for n in numbers_in(text) if n not in allowed]
    if loose:
        problems.append(f"numbers not backed by a cited fact: {', '.join(loose)}")

    refs = list(numbers) if numbers is not None else bind_numbers(text, cited, facts)
    written = numbers_in(text)
    # an attributed value may hold several numbers (a score "2-1"); each must come from its fact
    expanded = [(part, fid) for n, fid in refs for part in (numbers_in(n) or [n])]
    mismatched = [
        f"{n} -> {fid or '?'}"
        for n, fid in expanded
        if fid not in by_id
        or fid not in cited
        or n not in _number_forms(by_id[fid].value) | _number_forms(by_id[fid].label)
    ]
    attributed = [n for n, _ in expanded] == written and not mismatched
    if not attributed:
        problems.append(
            "each number must be listed in order with the cited fact that states it"
            + (f" (wrong: {', '.join(mismatched)})" if mismatched else f" (text has {written})")
        )

    cited_strings = " | ".join(str(f.value) for f in cited_facts if isinstance(f.value, str))
    stray = sorted(n for n in _names_in(text, known_names) if n not in cited_strings)
    if stray:
        problems.append(f"names not backed by a cited fact: {', '.join(stray)}")

    words = len(text.split())
    if words > MAX_WORDS or len(text) > MAX_CHARS:
        problems.append(f"too long: {words} words, {len(text)} characters")
    banned = BANNED.findall(text)
    if banned:
        problems.append(f"banned terms: {', '.join(sorted({b.lower() for b in banned}))}")
    if EM_DASH in text:
        problems.append("house style: replace each em dash with a colon, comma or full stop")

    checks = {
        "cites_at_least_one_fact": bool(cited_facts),
        "cites_only_known_facts": not unknown,
        "numbers_grounded": not loose,
        "numbers_attributed": attributed,
        "names_grounded": not stray,
        "length_ok": words <= MAX_WORDS and len(text) <= MAX_CHARS,
        "clean_language": not banned,
        "house_style": EM_DASH not in text,
    }
    if not cited_facts:
        problems.append("cites no facts")
    return Verdict(checks, problems)


def verify_translation(source: str, translated: str, known_names: Iterable[str]) -> Verdict:
    """A translation must carry exactly the source's numbers and proper names."""
    names = list(known_names)
    same_numbers = Counter(numbers_in(source)) == Counter(numbers_in(translated))
    missing = sorted(_names_in(source, names) - _names_in(translated, names))
    banned = BANNED.findall(translated)
    problems = []
    if not same_numbers:
        problems.append(f"numbers changed: {numbers_in(source)} -> {numbers_in(translated)}")
    if missing:
        problems.append(f"names lost: {', '.join(missing)}")
    if banned:
        problems.append("banned terms")
    if EM_DASH in translated:
        problems.append("house style: em dash")
    checks = {
        "numbers_preserved": same_numbers,
        "names_preserved": not missing,
        "length_ok": len(translated) <= MAX_CHARS + 60,
        "clean_language": not banned,
        "house_style": EM_DASH not in translated,
    }
    return Verdict(checks, problems)
