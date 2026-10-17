import pytest
from matchcut_analytics import (
    MatchState,
    MomentDetector,
    XTModel,
    expected_goals,
    score_tactical_detection,
    train,
)
from matchcut_analytics.xt import NX, NY, cell, prior_grid
from matchcut_contracts import EventType, MatchEvent, MatchMeta, Moment, MomentKind, Outcome, TruthRecord

HOME, AWAY = "kes", "irv"


def meta() -> MatchMeta:
    xi = [f"p{i:05d}" for i in range(1, 12)]
    xi2 = [f"p{i:05d}" for i in range(12, 23)]
    return MatchMeta(
        match_id="m1",
        competition="Harbour League",
        season="2026-27",
        matchday=9,
        home_club_id=HOME,
        away_club_id=AWAY,
        ground="Saltmarsh Park",
        seed=1,
        home_formation="4-3-3",
        away_formation="4-4-2",
        home_lineup=xi,
        away_lineup=xi2,
        home_bench=[],
        away_bench=[],
    )


_seq = iter(range(1, 100000))


def ev(t: str, team: str = HOME, player: str = "p00009", **kw) -> MatchEvent:
    n = next(_seq)
    base = {
        "match_id": "m1",
        "event_id": f"EV-{n:05d}",
        "seq": n,
        "period": 1,
        "t_ms": kw.pop("t_ms", n * 1000),
        "clock": "1:00",
        "type": t,
        "team_id": team,
        "player_id": player,
        "attacking_right": team == HOME,
    }
    base.update(kw)
    return MatchEvent(**base)


def test_xg_is_higher_closer_and_central():
    assert expected_goals(99, 34) > expected_goals(88, 34) > expected_goals(80, 34)
    assert expected_goals(99, 34) > expected_goals(99, 10)
    assert expected_goals(99, 34, header=True) < expected_goals(99, 34)
    assert 0.3 < expected_goals(99, 34) < 0.6


def test_xt_training_values_threat_near_goal():
    events = []
    for k in range(400):
        deep_ok = Outcome.FAIL if k % 5 == 0 else Outcome.SUCCESS
        events.append(ev(EventType.PASS, x=30, y=34, end_x=60, end_y=34, outcome=deep_ok))
        # forward passes from midfield fail a third of the time: risk must discount the zone
        ok = Outcome.FAIL if k % 3 == 0 else Outcome.SUCCESS
        events.append(ev(EventType.PASS, x=60, y=34, end_x=92, end_y=34, outcome=ok))
        s = ev(EventType.SHOT, x=95, y=34, outcome=Outcome.SUCCESS if k % 4 == 0 else Outcome.FAIL)
        events.append(s)
        if k % 4 == 0:
            events.append(ev(EventType.GOAL, related_event_id=s.event_id))
    model = train(events)
    assert model.grid.shape == (NX * NY,)
    assert model.value(95, 34) > model.value(60, 34) > model.value(30, 34)
    assert model.added(30, 34, 92, 34) > 0
    assert XTModel.from_json(model.to_json()).value(95, 34) == pytest.approx(model.value(95, 34), abs=1e-6)


def test_xt_cells_cover_the_pitch():
    assert cell(0, 0) == 0
    assert cell(105, 68) == NX * NY - 1
    assert len(prior_grid()) == NX * NY


def test_state_counts_passes_shots_goals_and_possession():
    st = MatchState(meta(), XTModel(prior_grid()))
    st.apply(ev(EventType.PASS, x=40, y=30, end_x=55, end_y=30, outcome=Outcome.SUCCESS))
    st.apply(ev(EventType.PASS, x=55, y=30, end_x=80, end_y=40, outcome=Outcome.FAIL))
    st.apply(
        ev(
            EventType.PASS,
            team=AWAY,
            player="p00015",
            x=30,
            y=30,
            end_x=40,
            end_y=30,
            outcome=Outcome.SUCCESS,
        )
    )
    shot = ev(EventType.SHOT, x=97, y=34, outcome=Outcome.SUCCESS)
    st.apply(shot)
    st.apply(ev(EventType.GOAL, related_event_id=shot.event_id))
    snap = st.snapshot()
    assert snap["score"] == "1-0"
    home = snap[HOME]
    assert home["shots"] == 1
    assert home["goals"] == 1
    assert home["pass_completion"] == 0.5
    assert st.possession(HOME) == pytest.approx(2 / 3)
    assert st.players["p00009"].goals == 1
    assert st.momentum > 0  # home created all the threat


def test_ppda_counts_opponent_passes_and_our_actions_in_their_zone():
    st = MatchState(meta(), XTModel(prior_grid()))
    for _ in range(9):  # away attack towards x = 0, so their own defensive 60% is pitch x >= 42
        st.apply(
            ev(
                EventType.PASS,
                team=AWAY,
                player="p00015",
                x=80,
                y=34,
                end_x=75,
                end_y=34,
                outcome=Outcome.SUCCESS,
            )
        )
    # home tackles high up (x >= 42 in home's attacking frame = inside away's own 60%)
    st.apply(ev(EventType.TACKLE, x=70, y=34, outcome=Outcome.SUCCESS))
    st.apply(ev(EventType.INTERCEPTION, x=60, y=34, outcome=Outcome.SUCCESS))
    st.apply(ev(EventType.TACKLE, x=20, y=34, outcome=Outcome.SUCCESS))  # deep: not counted
    assert st.teams[HOME].ppda == pytest.approx(4.5)


def test_detector_emits_goal_and_big_chance_with_evidence():
    det = MomentDetector(MatchState(meta(), XTModel(prior_grid())))
    miss = ev(EventType.SHOT, x=100, y=34, outcome=Outcome.FAIL)
    out = det.on_event(miss)
    assert any(m.kind == MomentKind.BIG_CHANCE for m in out)
    shot = ev(EventType.SHOT, x=99, y=34, outcome=Outcome.SUCCESS)
    det.on_event(shot)
    goal = ev(EventType.GOAL, related_event_id=shot.event_id)
    moments = det.on_event(goal)
    g = next(m for m in moments if m.kind == MomentKind.GOAL)
    assert g.evidence_event_ids == [shot.event_id, goal.event_id]
    assert g.metrics["score"] == "1-0"


def test_tactical_detection_scoring():
    def mom(t: int, team: str) -> Moment:
        return Moment(
            match_id="m1",
            moment_id=f"MO-{t:05d}",
            t_ms=t * 1000,
            clock="0:00",
            kind=MomentKind.TACTICAL_SHIFT,
            team_id=team,
            importance=0.5,
        )

    truth = [TruthRecord(match_id="m1", t_ms=3600_000, kind="tactic_change", team_id=HOME, detail={})]
    score = score_tactical_detection([mom(3700, HOME), mom(100, AWAY)], truth)
    assert score["recall"] == 1.0
    assert score["precision"] == 0.5
    assert score_tactical_detection([], truth)["recall"] == 0.0
