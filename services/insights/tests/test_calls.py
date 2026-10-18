from matchcut_contracts import EventType, MatchEvent
from matchcut_insights.calls import BUILD_LEAD_MS, TEMPLATES, build_calls
from matchcut_insights.voice import ssml


def _ev(n: int, t: int, typ: EventType, player: str, related: str | None = None) -> MatchEvent:
    return MatchEvent(
        match_id="kes-wcr-7",
        event_id=f"EV-{n:05d}",
        seq=n,
        period=1,
        t_ms=t,
        clock="10:00",
        type=typ,
        player_id=player,
        related_event_id=related,
    )


NAMES = {"p1": "Quinouani", "k2": "Okafor"}


def test_a_goal_gets_a_build_up_then_the_call_in_every_voiced_language():
    events = [_ev(1, 60_000, EventType.SHOT, "p1"), _ev(2, 60_300, EventType.GOAL, "p1", "EV-00001")]
    calls = build_calls("kes-wcr-7", events, NAMES)
    langs = set(TEMPLATES)
    assert {c.language for c in calls} == langs
    en = [c for c in calls if c.language == "en"]
    assert [(c.kind, c.t_ms) for c in en] == [("build", 60_000 - BUILD_LEAD_MS), ("goal", 60_300)]
    assert all("Quinouani" in c.text for c in en)


def test_saves_name_the_keeper_and_misses_follow_the_shot():
    events = [
        _ev(1, 10_000, EventType.SHOT, "p1"),
        _ev(2, 10_400, EventType.SAVE, "k2", "EV-00001"),
        _ev(3, 90_000, EventType.SHOT, "p1"),
    ]
    en = list(build_calls("kes-wcr-7", events, NAMES, ["en"]))
    kinds = [c.kind for c in en]
    assert kinds == ["build", "save", "build", "miss"]
    assert "Okafor" in en[1].text
    assert en[3].t_ms > 90_000


def test_calls_are_stable_and_never_use_em_dashes():
    events = [_ev(1, 60_000, EventType.SHOT, "p1"), _ev(2, 60_300, EventType.GOAL, "p1", "EV-00001")]
    a = build_calls("kes-wcr-7", events, NAMES)
    b = build_calls("kes-wcr-7", events, NAMES)
    assert [c.text for c in a] == [c.text for c in b]  # seeded: the same match always sounds the same
    for lang in TEMPLATES.values():
        for options in lang.values():
            assert all(chr(0x2014) not in o for o in options)


def test_build_up_calls_rise_and_quicken():
    s = ssml("Here's Quinouani...", "en", "en-GB-Harry:MAI-Voice-2.1", None, lift=True)
    assert 'pitch="+6%"' in s
    assert 'rate="+12%"' in s
