from collections import Counter

from matchcut_sim.history import round_robin, simulate_history
from matchcut_sim.league import CLUBS, build_league, kit_distance, match_kits


def test_league_is_deterministic():
    assert build_league(11) == build_league(11)
    assert build_league(11).players != build_league(12).players


def test_league_shape():
    lg = build_league()
    assert len(lg.clubs) == 20
    assert len(lg.players) == 500
    assert len({p.player_id for p in lg.players}) == 500
    for c in lg.clubs:
        squad = lg.squad(c.club_id)
        assert len(squad) == 25
        assert len({p.shirt_number for p in squad}) == 25
        assert sum(p.position.value == "GK" for p in squad) == 3
        assert len({p.known_as for p in squad}) == 25


def test_club_names_ids_and_grounds_are_unique():
    assert len({c[0] for c in CLUBS}) == len({c[1] for c in CLUBS}) == len({c[4] for c in CLUBS}) == 20


def test_kits_never_clash_on_the_pitch():
    lg = build_league()
    for home in lg.clubs:
        for away in lg.clubs:
            if home is away:
                continue
            hk, ak = match_kits(home, away)
            assert kit_distance(hk.primary, ak.primary) >= 120, (home.club_id, away.club_id)


def test_round_robin_is_a_valid_double_round_robin():
    ids = [f"c{i:02d}" for i in range(20)]
    days = round_robin(ids)
    assert len(days) == 38
    for day in days:
        teams = [t for pair in day for t in pair]
        assert sorted(teams) == sorted(ids)  # everyone plays exactly once per matchday
    fixtures = Counter(pair for day in days for pair in day)
    assert len(fixtures) == 380
    assert set(fixtures.values()) == {1}


def test_history_tables_and_player_lines_agree():
    lg = build_league()
    hist = simulate_history(lg, ["2024-25"], seed=3)
    assert len(hist.matches) == 380
    table = hist.table("2024-25")
    assert len(table) == 20
    assert all(r["p"] == 38 for r in table)
    total_goals = sum(m.home_goals + m.away_goals for m in hist.matches)
    assert sum(int(r["gf"]) for r in table) == total_goals
    assert sum(ln.goals for ln in hist.lines) == total_goals  # every goal has a scorer
    assert 2.2 <= total_goals / 380 <= 3.4  # top-flight scoring rate
    for ln in hist.lines:
        assert 0 <= ln.minutes <= 90
