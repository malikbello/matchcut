import random
from collections import Counter

from matchcut_sim.history import dixon_coles_score, goal_rates, round_robin
from matchcut_sim.league import CLUBS, build_league, kit_distance, match_kits
from matchcut_sim.universe import build_universe


def test_league_is_deterministic():
    assert build_league(11) == build_league(11)
    assert build_league(11).players != build_league(12).players


def test_current_league_shape():
    lg = build_league()
    assert lg.season == "2026-27"
    assert len(lg.clubs) == 20
    assert len(lg.players) == 500
    assert len({p.player_id for p in lg.players}) == 500
    for c in lg.clubs:
        squad = lg.squad(c.club_id)
        assert len(squad) == 25
        assert len({p.shirt_number for p in squad}) == 25
        assert sum(p.position.value == "GK" for p in squad) == 3
        assert len({p.known_as for p in squad}) == 25


def test_club_catalogue_is_unique():
    assert len(CLUBS) == 26
    for idx in (0, 1, 4):  # id, name, ground
        assert len({c[idx] for c in CLUBS}) == 26


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
        assert sorted(teams) == sorted(ids)
    fixtures = Counter(pair for day in days for pair in day)
    assert len(fixtures) == 380
    assert set(fixtures.values()) == {1}


def test_dixon_coles_matches_top_flight_scorelines():
    rng = random.Random(1)
    lh, la = goal_rates(75, 75)
    scores = [dixon_coles_score(rng, lh, la) for _ in range(20000)]
    goals = sum(h + a for h, a in scores) / len(scores)
    nil_nil = sum(1 for h, a in scores if h == a == 0) / len(scores)
    home_wins = sum(1 for h, a in scores if h > a) / len(scores)
    assert 2.4 <= goals <= 2.9
    assert 0.06 <= nil_nil <= 0.10
    assert 0.40 <= home_wins <= 0.50


def test_history_tables_and_player_lines_agree():
    u = build_universe(2026)
    hist = u.history
    past = hist.seasons[:5]
    for season in past:
        table = hist.table(season)
        assert len(table) == 20
        assert all(r["p"] == 38 for r in table)
    total_goals = sum(m.home_goals + m.away_goals for m in hist.matches)
    assert sum(ln.goals for ln in hist.lines) == total_goals  # every goal has a scorer
    assert 2.4 <= total_goals / len(hist.matches) <= 3.2
    for ln in hist.lines:
        assert 0 <= ln.minutes <= 90


def test_players_keep_their_id_across_transfers():
    u = build_universe(2026)
    t = next(t for t in u.transfers if t.player_id in u.all_players)
    clubs_played_for = {ln.club_id for ln in u.history.lines if ln.player_id == t.player_id}
    assert t.to_club in clubs_played_for or u.all_players[t.player_id].club_id in (t.to_club, "retired")
