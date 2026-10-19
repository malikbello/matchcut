import pytest
from matchcut_contracts import EventType
from matchcut_sim import build_league, simulate_match
from matchcut_sim.feed import ANIMATED, build_feed


@pytest.fixture(scope="module")
def match_and_feed():
    league = build_league()
    ids = [c.club_id for c in league.clubs]
    m = simulate_match(league, ids[0], ids[1], seed=11, half_minutes=6)
    return m, league, build_feed(m, league)


def test_feed_carries_positions_at_the_engine_rate(match_and_feed):
    m, _, feed = match_and_feed
    assert feed["hz"] == 10
    assert len(feed["t"]) == len(m.t_ms)
    assert len(feed["p"][0]) == 2 * len(feed["slots"])


def test_every_on_ball_action_is_in_the_event_stream_with_its_player(match_and_feed):
    m, _, feed = match_and_feed
    expected = [e for e in m.events if e.type in ANIMATED]
    assert len(feed["events"]) == len(expected)
    for row, e in zip(feed["events"], expected, strict=True):
        assert row[0] == e.t_ms
        assert row[1] == e.type.value
        if e.player_id:
            slot = row[2]
            assert slot >= 0, f"{e.type} by {e.player_id} not mapped to a slot"
            r = int(m.roster[min(e.t_ms // 100, len(m.t_ms) - 1), slot])
            assert m.player_ids[r] == e.player_id


def test_shots_carry_the_body_part_the_animation_needs(match_and_feed):
    _, _, feed = match_and_feed
    shots = [r for r in feed["events"] if r[1] == EventType.SHOT.value]
    assert shots, "a 12-minute match should have shots"
    assert all(r[3] in {"left_foot", "right_foot", "head"} for r in shots)


def test_one_keeper_per_side_and_restarts_are_marked(match_and_feed):
    m, _, feed = match_and_feed
    sides = {m.team_of_slot[s] for s in feed["keepers"]}
    assert len(feed["keepers"]) == 2
    assert len(sides) == 2
    # the second half starts with everyone repositioned: the scene must cut, not slide
    second = next(t for t, p in zip(feed["t"], feed["period"], strict=True) if p == 2)
    assert any(abs(c - second) <= 1000 for c in feed["cuts"])


def test_empty_slots_are_marked_and_real_positions_never_look_empty(match_and_feed):
    m, _, feed = match_and_feed
    from matchcut_sim.feed import EMPTY  # noqa: PLC0415

    for i, row in enumerate(feed["p"]):
        for slot in range(len(feed["slots"])):
            on_pitch = int(m.roster[i, slot]) >= 0
            x, y = row[2 * slot], row[2 * slot + 1]
            if on_pitch:
                assert x > EMPTY
                assert y > EMPTY  # behind the goal line is negative, and still a real position
            else:
                assert (x, y) == (EMPTY, EMPTY)
