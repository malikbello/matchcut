import numpy as np
import pytest
from matchcut_contracts import EventType, Outcome
from matchcut_sim.engine import simulate_match
from matchcut_sim.league import build_league
from matchcut_sim.realism import match_stats, report_markdown, summarise


@pytest.fixture(scope="module")
def league():
    return build_league()


@pytest.fixture(scope="module")
def match(league):
    # two 10-minute halves keep the suite fast; the engine code path is identical
    return simulate_match(league, "kes", "irv", seed=7, half_minutes=10)


def test_same_seed_same_match(league, match):
    again = simulate_match(league, "kes", "irv", seed=7, half_minutes=10)
    assert [e.model_dump() for e in again.events] == [e.model_dump() for e in match.events]
    assert np.array_equal(again.pos, match.pos)


def test_different_seed_different_match(league, match):
    other = simulate_match(league, "kes", "irv", seed=8, half_minutes=10)
    assert [e.event_id for e in other.events] != []
    assert other.events != match.events


def test_tracking_is_10hz_and_continuous(match):
    steps = np.diff(match.t_ms)
    assert np.all(steps == 100)
    assert match.pos.shape[1:] == (22, 2)
    assert set(np.unique(match.period)) == {1, 2}
    assert match.speed.max() < 10.5  # nobody runs faster than ~37.8 km/h


def test_events_are_ordered_and_in_play(match):
    seqs = [e.seq for e in match.events]
    assert seqs == list(range(1, len(seqs) + 1))
    times = [e.t_ms for e in match.events]
    assert times == sorted(times)
    kinds = {e.type for e in match.events}
    for needed in (EventType.PERIOD_START, EventType.KICK_OFF, EventType.PASS, EventType.PERIOD_END):
        assert needed in kinds


def test_events_agree_with_tracking(match):
    """A pass starts where the passer actually is in the tracking data."""
    idx_by_t = {int(t): i for i, t in enumerate(match.t_ms)}
    checked = 0
    for e in match.events:
        if e.type != EventType.PASS or e.player_id is None or e.x is None:
            continue
        i = idx_by_t.get(e.t_ms)
        if i is None:
            continue
        slot_ids = [match.player_ids[r] if r >= 0 else None for r in match.roster[i]]
        slot = slot_ids.index(e.player_id)
        px, py = match.pos[i, slot]
        assert abs(px - e.x) < 1.0
        assert abs(py - e.y) < 1.0
        checked += 1
    assert checked > 50


def test_goals_match_the_score(match):
    goals = [e for e in match.events if e.type == EventType.GOAL]
    assert len(goals) == sum(match.score)
    for g in goals:
        assert g.related_event_id is not None
        shot = next(e for e in match.events if e.event_id == g.related_event_id)
        assert shot.type == EventType.SHOT
        assert shot.outcome == Outcome.SUCCESS


def test_truth_records_every_shot(match):
    shots = [e for e in match.events if e.type == EventType.SHOT]
    probs = [t for t in match.truth if t.kind == "shot_probability"]
    assert len(probs) == len(shots)


def test_realism_summary_and_report(match):
    s = match_stats(match)
    assert s.passes > 0
    assert 0 < s.passes_completed <= s.passes
    summary = summarise([s])
    md = report_markdown(summary, 1)
    assert "Realism report" in md
    assert "| passes per match |" in md
