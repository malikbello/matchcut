from matchcut_contracts import EventType, MatchEvent
from matchcut_insights.calls import BUILD_LEAD_MS, TEMPLATES, build_calls, dribble_calls, solo_runs
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


def _run_feed(runner_is_keeper: bool = False) -> dict:
    """Slot 0 carries the ball 22 m in 5.5 s; slot 1 closes him down at 1 s, slot 2 at 2.8 s; then
    the ball is played away. Positions are in decimetres, as in the tracking feed."""
    t = list(range(0, 6100, 100))
    b, p = [], []
    for i in range(len(t)):
        rx = 300 + 4 * min(i, 55)
        bx = rx + 5 if i <= 55 else 900
        b.append([bx, 340, 0])
        d1 = (rx + 15, 355) if 10 <= i <= 20 else (100, 100)
        d2 = (rx + 13, 325) if 28 <= i <= 35 else (100, 600)
        p.append([rx, 340, *d1, *d2, 1000, 340])
    return {
        "t": t, "b": b, "p": p, "slots": ["kes", "wcr", "wcr", "wcr"],
        "keepers": [0] if runner_is_keeper else [3],
        "teams": {
            "home": {"id": "kes", "players": {"0": {"name": "Kaluamont"}}},
            "away": {"id": "wcr", "players": {}},
        },
        "changes": [], "players": {},
    }  # fmt: skip


def test_a_solo_run_past_two_challenges_gets_a_call_as_he_sets_off_and_as_he_beats_them():
    feed = _run_feed()
    assert solo_runs(feed) == [(300, 3400, "Kaluamont")]  # the second challenge at 2.8 s, beaten just after
    calls = dribble_calls("kes-wcr-7", feed, ["en", "fr"])
    assert [(c.call_id, c.t_ms, c.kind) for c in calls if c.language == "en"] == [
        ("CD-00001-en", 300, "run"),
        ("CD-00002-en", 3400, "beat"),
    ]
    assert any("Kaluamont" in c.text for c in calls if c.kind == "run")
    assert [c.text for c in calls] == [
        c.text for c in dribble_calls("kes-wcr-7", feed, ["en", "fr"])
    ]  # seeded


def test_a_keeper_carrying_the_ball_is_not_a_solo_run():
    assert solo_runs(_run_feed(runner_is_keeper=True)) == []


def test_build_up_calls_rise_and_quicken():
    s = ssml("Here's Quinouani...", "en", "en-GB-Harry:MAI-Voice-2.1", None, lift=True)
    assert 'pitch="+6%"' in s
    assert 'rate="+12%"' in s
