from matchcut_contracts import Fact, Moment, MomentKind
from matchcut_insights.facts import CHANCE_IN_10, CHANCE_ONE_IN, chance_facts
from matchcut_insights.plain import plain_card


def test_chance_quality_is_said_as_fans_say_it():
    assert chance_facts(0.93) == [(CHANCE_IN_10, 9)]
    assert chance_facts(0.15) == [(CHANCE_IN_10, 2)]
    assert chance_facts(0.05) == [(CHANCE_ONE_IN, 20)]
    assert chance_facts(0.004)[0][1] == 100  # very long range never divides by zero


def _moment(kind: MomentKind) -> Moment:
    return Moment(
        match_id="kes-wcr-7",
        moment_id="MO-00003",
        kind=kind,
        t_ms=1000,
        clock="52:34",
        importance=0.8,
        team_id=None,
        player_id=None,
        metrics={},
        evidence_event_ids=[],
    )


def test_plain_cards_never_show_xg():
    facts = [
        Fact(fact_id="F-001", label="match minute", value=53, source="analytics"),
        Fact(fact_id="F-002", label="player involved", value="Quinouani", source="analytics"),
        Fact(fact_id="F-003", label="expected goals of the shot (0 to 1)", value=0.93, source="analytics"),
        Fact(fact_id="F-004", label=CHANCE_IN_10, value=9, source="analytics"),
    ]
    text, used = plain_card(_moment(MomentKind.BIG_CHANCE), facts)
    assert "xG" not in text
    assert "9 times in 10" in text
    assert "F-004" in used
