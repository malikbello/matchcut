"""Plain cards: template lines that air the instant a moment is detected.

They are built only from the fact sheet, so they are correct by construction and
need no model. The verified AI line replaces the plain card when it is ready.
"""

from __future__ import annotations

from collections.abc import Sequence

from matchcut_contracts import Fact, Moment, MomentKind

from matchcut_insights.facts import CHANCE_IN_10, CHANCE_ONE_IN


def _get(facts: Sequence[Fact], label: str) -> Fact | None:
    return next((f for f in facts if f.label == label), None)


def _chance(facts: Sequence[Fact]) -> tuple[str, Fact] | None:
    """Chance quality in fans' words, from the code-computed chance fact."""
    for f in facts:
        if f.label.startswith(CHANCE_IN_10):
            return f"a chance scored {f.value} times in 10", f
        if f.label.startswith(CHANCE_ONE_IN):
            return f"a chance scored once in every {f.value} attempts", f
    return None


def plain_card(moment: Moment, facts: Sequence[Fact]) -> tuple[str, list[str]]:
    """Return the card text and the fact IDs it uses."""
    minute = _get(facts, "match minute")
    club = _get(facts, "club involved")
    player = _get(facts, "player involved")
    score = next((f for f in facts if f.label.startswith("score, ")), None)
    used = [f for f in (minute, club, player) if f is not None]
    who = player.value if player else club.value if club else "Play"
    m = f"{minute.value}'" if minute else ""
    k = moment.kind
    metric = None
    if k == MomentKind.GOAL:
        text = f"{m} GOAL - {who}. {score.value if score else ''}".strip()
        if score:
            used.append(score)
    elif k == MomentKind.BIG_CHANCE:
        chance = _chance(facts)
        metric = chance[1] if chance else None
        text = f"{m} Big chance for {who}" + (f": {chance[0]}" if chance else "")
    elif k == MomentKind.GREAT_SAVE:
        chance = _chance(facts)
        metric = chance[1] if chance else None
        text = f"{m} Big save by {who}" + (f", denying {chance[0]}" if chance else "")
    elif k == MomentKind.SPEED_PEAK:
        metric = _get(facts, "top speed in km/h")
        text = f"{m} {who} hits {metric.value} km/h" if metric else f"{m} {who} at full speed"
    elif k == MomentKind.CARD:
        metric = _get(facts, "card colour")
        colour = str(metric.value).capitalize() if metric else "Yellow"
        text = f"{m} {colour} card - {who}"
    elif k == MomentKind.SUBSTITUTION:
        metric = _get(facts, "substitute coming on")
        text = f"{m} Substitution: {metric.value} on for {who}" if metric else f"{m} Substitution - {who}"
    elif k == MomentKind.TACTICAL_SHIFT:
        text = f"{m} {who} pressing harder"  # what was measured, not a claim about the coach's intent
    elif k == MomentKind.MOMENTUM_SWING:
        text = f"{m} Momentum swings to {who}"
    else:
        text = f"{m} {who}"
    if metric is not None:
        used.append(metric)
    return text.strip(), [f.fact_id for f in used]
