"""Red-team the Verifier: plant false claims in true lines and measure what it catches.

True lines are plain cards (correct by construction) and a few richer templates
built from the same fact sheet. Each attack makes one realistic error a writer
could make: a nudged number, a transposed score, a wrong player, a citation to a
fact that does not exist, an unsupported extra statistic, betting language, or an
em dash. Two numbers matter: the catch rate on false lines (higher is better) and
the false-rejection rate on true lines (lower is better).
"""

from __future__ import annotations

import random
import re
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from matchcut_contracts import Fact, Moment

from matchcut_insights.facts import MatchContext, build_facts
from matchcut_insights.plain import plain_card
from matchcut_insights.verify import NUMBER, bind_numbers, verify_line


@dataclass(frozen=True)
class Sample:
    text: str
    cited: list[str]
    facts: list[Fact]
    numbers: list[tuple[str, str]] | None = (
        None  # the writer's attribution, kept when an attack edits the text
    )

    def attributed(self) -> Sample:
        return Sample(self.text, self.cited, self.facts, bind_numbers(self.text, self.cited, self.facts))


Attack = Callable[[Sample, MatchContext, random.Random], Sample | None]


def _fact(facts: Sequence[Fact], start: str) -> Fact | None:
    return next((f for f in facts if f.label.startswith(start)), None)


def true_lines(moment: Moment, snapshot: dict, ctx: MatchContext) -> list[Sample]:
    facts = build_facts(moment, snapshot, ctx)
    text, used = plain_card(moment, facts)
    out = [Sample(text, used, facts).attributed()]
    minute, club = _fact(facts, "match minute"), _fact(facts, "club involved")
    if minute and club:
        shots = _fact(facts, f"{club.value} shots")
        if shots:
            out.append(
                Sample(
                    f"{club.value} have {shots.value} shots after {minute.value} minutes.",
                    [club.fact_id, shots.fact_id, minute.fact_id],
                    facts,
                ).attributed()
            )
    return out


# ---------------------------------------------------------------- attacks


def nudge_number(s: Sample, ctx: MatchContext, rng: random.Random) -> Sample | None:
    nums = list(NUMBER.finditer(s.text))
    if not nums:
        return None
    m = rng.choice(nums)
    value = float(m.group().replace(",", "."))
    wrong = value + rng.choice([-2, -1, 1, 2]) if value >= 1 else round(value + rng.choice([-0.1, 0.1]), 2)
    wrong_text = f"{wrong:g}" if wrong >= 0 else "3"
    return Sample(s.text[: m.start()] + wrong_text + s.text[m.end() :], s.cited, s.facts, s.numbers)


def flip_score(s: Sample, ctx: MatchContext, rng: random.Random) -> Sample | None:
    m = re.search(r"(\d+)-(\d+)", s.text)
    if not m or m.group(1) == m.group(2):
        return None
    return Sample(
        s.text[: m.start()] + f"{m.group(2)}-{m.group(1)}" + s.text[m.end() :], s.cited, s.facts, s.numbers
    )


def wrong_player(s: Sample, ctx: MatchContext, rng: random.Random) -> Sample | None:
    names = {f.value for f in s.facts if f.label == "player involved"}
    present = [n for n in names if isinstance(n, str) and n in s.text]
    if not present:
        return None
    others = sorted(p.known_as for p in ctx.players.values() if p.known_as not in names)
    return Sample(s.text.replace(present[0], rng.choice(others)), s.cited, s.facts, s.numbers)


def phantom_citation(s: Sample, ctx: MatchContext, rng: random.Random) -> Sample | None:
    return Sample(s.text, [*s.cited, "F-999"], s.facts, s.numbers)


def invented_stat(s: Sample, ctx: MatchContext, rng: random.Random) -> Sample | None:
    return Sample(f"{s.text} His {rng.randint(3, 19)}th of the season.", s.cited, s.facts, s.numbers)


def betting_language(s: Sample, ctx: MatchContext, rng: random.Random) -> Sample | None:
    return Sample(f"{s.text} The odds have shifted.", s.cited, s.facts, s.numbers)


def em_dash(s: Sample, ctx: MatchContext, rng: random.Random) -> Sample | None:
    return Sample(s.text.replace(" ", f" {chr(0x2014)} ", 1), s.cited, s.facts, s.numbers)


ATTACKS: dict[str, Attack] = {
    "nudged number": nudge_number,
    "transposed score": flip_score,
    "wrong player": wrong_player,
    "phantom citation": phantom_citation,
    "invented statistic": invented_stat,
    "betting language": betting_language,
    "em dash": em_dash,
}


@dataclass
class RedTeamResult:
    true_lines: int
    false_rejections: int
    attacks: Counter[str]
    caught: Counter[str]
    misses: list[str]

    @property
    def catch_rate(self) -> float:
        total = sum(self.attacks.values())
        return sum(self.caught.values()) / total if total else 1.0

    @property
    def false_rejection_rate(self) -> float:
        return self.false_rejections / self.true_lines if self.true_lines else 0.0


def red_team(moments: Sequence[tuple[Moment, dict]], ctx: MatchContext, seed: int = 7) -> RedTeamResult:
    rng = random.Random(seed)
    names = ctx.names()
    result = RedTeamResult(0, 0, Counter(), Counter(), [])
    for moment, snapshot in moments:
        for sample in true_lines(moment, snapshot, ctx):
            result.true_lines += 1
            if not verify_line(sample.text, sample.cited, sample.facts, names, sample.numbers).passed:
                result.false_rejections += 1
                result.misses.append(f"true line rejected: {sample.text}")
            for name, attack in ATTACKS.items():
                bad = attack(sample, ctx, rng)
                if bad is None or (bad.text == sample.text and bad.cited == sample.cited):
                    continue
                result.attacks[name] += 1
                if verify_line(bad.text, bad.cited, bad.facts, names, bad.numbers).passed:
                    result.misses.append(f"{name} not caught: {bad.text}")
                else:
                    result.caught[name] += 1
    return result


def report_markdown(result: RedTeamResult, matches: int) -> str:
    rows = [
        f"| {name} | {result.attacks[name]} | {result.caught[name]} | "
        f"{result.caught[name] / result.attacks[name]:.0%} |"
        for name in ATTACKS
        if result.attacks[name]
    ]
    misses = [f"- {m}" for m in result.misses[:15]] or ["- none"]
    return "\n".join(
        [
            "# Verifier red team",
            "",
            f"{matches} simulated matches. True lines come from the fact sheets; each attack plants one "
            "realistic error. Deterministic: the same seed gives the same report.",
            "",
            f"**Caught {result.catch_rate:.1%} of {sum(result.attacks.values())} false lines** · "
            f"**wrongly rejected {result.false_rejection_rate:.1%} of {result.true_lines} true lines**",
            "",
            "| Attack | Planted | Caught | Rate |",
            "|---|---|---|---|",
            *rows,
            "",
            "## Misses",
            "",
            *misses,
            "",
        ]
    )
