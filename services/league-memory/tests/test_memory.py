import asyncio
import sqlite3
from collections import defaultdict

import pytest
from matchcut_memory import LeagueMemory, build_db, query_id, server
from matchcut_sim.universe import build_universe


@pytest.fixture(scope="module")
def universe():
    return build_universe(2026)


@pytest.fixture(scope="module")
def memory(universe, tmp_path_factory):
    path = build_db(universe, tmp_path_factory.mktemp("lm") / "memory.sqlite")
    lm = LeagueMemory(path)
    yield lm
    lm.close()


def _ordered_lines(universe, pid):
    order = {s: i for i, s in enumerate(universe.history.seasons)}
    md = {m.match_id: (order[m.season], m.matchday) for m in universe.history.matches}
    return sorted(
        (ln for ln in universe.history.lines if ln.player_id == pid), key=lambda ln: md[ln.match_id]
    )


def test_database_is_read_only(memory):
    with pytest.raises(sqlite3.OperationalError):
        memory.con.execute("DELETE FROM matches")


def test_query_ids_are_stable_and_distinct():
    assert query_id("x", {"a": 1}) == query_id("x", {"a": 1})
    assert query_id("x", {"a": 1}) != query_id("x", {"a": 2})


def test_career_totals_match_raw_history(memory, universe):
    totals = defaultdict(lambda: [0, 0])
    for ln in universe.history.lines:
        totals[ln.player_id][0] += 1
        totals[ln.player_id][1] += ln.goals
    for pid in list(totals)[:40]:
        prof = memory.player_profile(pid)
        assert prof["career"]["apps"] == totals[pid][0]
        assert prof["career"]["goals"] == totals[pid][1]


def test_goal_context_droughts_are_recomputed_correctly(memory, universe):
    checked = 0
    for pid in list({ln.player_id for ln in universe.history.lines})[:80]:
        lines = _ordered_lines(universe, pid)
        for is_home in (True, False):
            venue = [ln for ln in lines if ln.home == is_home]
            drought = 0
            for ln in reversed(venue):
                if ln.goals:
                    break
                drought += 1
            ctx = memory.goal_context(pid, is_home)
            facts = {f["fact"]: f for f in ctx["facts"]}
            key = f"first_{'home' if is_home else 'away'}_goal_in"
            has_goals = any(ln.goals for ln in lines)
            if has_goals and drought >= 5:
                assert facts[key]["apps"] == drought
                checked += 1
            else:
                assert key not in facts
    assert checked > 0


def test_a_second_goal_today_is_numbered_as_such_and_old_news_is_not_repeated(memory, universe):
    pid = next(ln.player_id for ln in universe.history.lines if ln.goals)
    first = memory.goal_context(pid, True)
    second = memory.goal_context(pid, True, goals_today=1)
    assert second["season_goal_number"] == first["season_goal_number"] + 1
    assert second["career_goal_number"] == first["career_goal_number"] + 1
    assert (first["match_goal_number"], second["match_goal_number"]) == (1, 2)
    once = {"first_league_goal", "goal_drought_ended", "first_home_goal_in", "first_goal_of_season"}
    assert not once & {f["fact"] for f in second["facts"]}  # a drought ends once, not twice in a day
    assert first["query_id"] != second["query_id"]  # a different question, a different answer


def test_head_to_head_is_consistent(memory, universe):
    h = memory.head_to_head("kes", "irv", last=100)
    meetings = [m for m in universe.history.matches if {m.home, m.away} == {"kes", "irv"}]
    assert h["meetings"] == len(meetings)
    assert h["a_wins"] + h["draws"] + h["b_wins"] == len(meetings)


def test_universe_evolves_like_a_real_league(universe):
    seasons = [s for s in universe.top_flight if s in universe.relegated]
    assert len(seasons) == 5
    for s in seasons:
        assert len(universe.relegated[s]) == 3
    assert len(universe.transfers) > 0
    assert any(c.kind == "retired" for c in universe.careers)
    assert any(c.kind == "academy_debut" for c in universe.careers)
    for club in universe.league.clubs:
        squad = universe.league.squad(club.club_id)
        assert len(squad) == 25
        assert len({p.shirt_number for p in squad}) == 25
    assert universe.next_matchday == 9
    assert len(universe.next_fixtures) == 10


def test_profile_form_milestones_and_scorers(memory, universe):
    top = memory.top_scorers(limit=5)
    assert len(top["rows"]) == 5
    assert top["rows"][0]["goals"] >= top["rows"][-1]["goals"]
    season = universe.history.seasons[0]
    assert memory.top_scorers(season=season, limit=3)["season"] == season
    pid = top["rows"][0]["player_id"]
    prof = memory.player_profile(pid)
    assert prof["career"]["goals"] == top["rows"][0]["goals"]
    assert sum(s["apps"] for s in prof["by_season"].values()) == prof["career"]["apps"]
    near = memory.milestones_near(pid, within=500)
    assert near["goals"] == prof["career"]["goals"]
    assert all(m["needed"] > 0 for m in near["near"])
    form = memory.club_form("kes", last=5)
    assert len(form["form"]) == 5
    assert set(form["form"]) <= {"W", "D", "L"}
    assert form["unbeaten_run"] == 0 or form["winless_run"] == 0 or form["form"][-1] == "D"
    with pytest.raises(KeyError):
        memory.player_profile("p99999")


def test_mcp_server_lists_and_calls_tools(memory, monkeypatch):
    monkeypatch.setattr(server, "_memory", memory)

    async def run():
        names = {t.name for t in await server.mcp.list_tools()}
        result = await server.mcp.call_tool("club_form", {"club_id": "irv", "last": 3})
        return names, result

    names, result = asyncio.run(run())
    assert names == {
        "player_profile",
        "goal_context",
        "milestones_near",
        "head_to_head",
        "club_form",
        "top_scorers",
    }
    assert "LM-" in str(result)
