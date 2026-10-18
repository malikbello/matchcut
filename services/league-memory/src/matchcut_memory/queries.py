"""League Memory queries: the only questions the Historian agent may ask.

Every function is read-only and parameterised (no SQL is ever built from model
text). Every answer carries a ``query_id`` (stable for the same question) and
``evidence`` (the match IDs behind it) so the verifier can re-run and check it.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any

GOAL_MILESTONES = [10, 25, 50, 75, 100, 125, 150, 200]
APP_MILESTONES = [50, 100, 150, 200, 250, 300]


def query_id(name: str, params: dict[str, Any]) -> str:
    raw = name + json.dumps(params, sort_keys=True)
    return "LM-" + hashlib.sha1(raw.encode()).hexdigest()[:10]  # noqa: S324 - identifier, not security


class LeagueMemory:
    def __init__(self, path: str | Path):
        uri = f"file:{Path(path).as_posix()}?mode=ro"
        self.con = sqlite3.connect(uri, uri=True, check_same_thread=False)  # read-only connection
        self.con.row_factory = sqlite3.Row

    def close(self) -> None:
        self.con.close()

    # ------------------------------------------------------------ helpers
    def _lines(self, player_id: str) -> list[sqlite3.Row]:
        return self.con.execute(
            """SELECT l.*, m.season, m.matchday, m.season_order FROM player_lines l
               JOIN matches m ON m.match_id = l.match_id
               WHERE l.player_id = ? ORDER BY m.season_order, m.matchday""",
            (player_id,),
        ).fetchall()

    def _player(self, player_id: str) -> sqlite3.Row:
        row = self.con.execute("SELECT * FROM players WHERE player_id = ?", (player_id,)).fetchone()
        if row is None:
            raise KeyError(f"unknown player {player_id}")
        return row

    def _club_name(self, club_id: str) -> str:
        row = self.con.execute("SELECT name FROM clubs WHERE club_id = ?", (club_id,)).fetchone()
        return row["name"] if row else club_id

    # ------------------------------------------------------------ tools
    def player_profile(self, player_id: str) -> dict[str, Any]:
        p = self._player(player_id)
        lines = self._lines(player_id)
        seasons: dict[str, dict[str, int]] = {}
        for ln in lines:
            s = seasons.setdefault(ln["season"], {"apps": 0, "goals": 0, "assists": 0, "minutes": 0})
            s["apps"] += 1
            s["goals"] += ln["goals"]
            s["assists"] += ln["assists"]
            s["minutes"] += ln["minutes"]
        transfers = self.con.execute(
            "SELECT season, from_club, to_club FROM transfers WHERE player_id = ? ORDER BY season",
            (player_id,),
        ).fetchall()
        return {
            "query_id": query_id("player_profile", {"player_id": player_id}),
            "player_id": player_id,
            "name": p["name"],
            "known_as": p["known_as"],
            "position": p["position"],
            "birth_year": p["birth_year"],
            "current_club": p["current_club"],
            "career": {
                "apps": len(lines),
                "goals": sum(x["goals"] for x in lines),
                "assists": sum(x["assists"] for x in lines),
                "minutes": sum(x["minutes"] for x in lines),
            },
            "by_season": seasons,
            "transfers": [dict(t) for t in transfers],
            "evidence": [ln["match_id"] for ln in lines[-5:]],
        }

    def goal_context(self, player_id: str, is_home: bool) -> dict[str, Any]:
        """Facts that become true if this player scores now (in the live match).

        All counts are league appearances before the live match.
        """
        lines = self._lines(player_id)
        p = self._player(player_id)
        current_season = lines[-1]["season"] if lines else None
        career_goals = sum(x["goals"] for x in lines)
        season_goals = sum(x["goals"] for x in lines if x["season"] == current_season)

        def since_last(rows: list[sqlite3.Row]) -> tuple[int, str | None]:
            n = 0
            for r in reversed(rows):
                if r["goals"] > 0:
                    return n, r["match_id"]
                n += 1
            return n, None

        all_drought, last_any = since_last(lines)
        venue_rows = [x for x in lines if bool(x["home"]) == is_home]
        venue_drought, last_venue = since_last(venue_rows)
        facts: list[dict[str, Any]] = []
        if career_goals == 0:
            facts.append({"fact": "first_league_goal", "apps_before": len(lines)})
        elif all_drought >= 5:
            facts.append(
                {"fact": "goal_drought_ended", "apps_without_goal": all_drought, "last_goal_match": last_any}
            )
        if career_goals > 0 and venue_drought >= 5:
            facts.append(
                {
                    "fact": f"first_{'home' if is_home else 'away'}_goal_in",
                    "apps": venue_drought,
                    "last_goal_match": last_venue,
                }
            )
        new_total = career_goals + 1
        if new_total in GOAL_MILESTONES:
            facts.append({"fact": "career_goal_milestone", "goals": new_total})
        if season_goals == 0 and lines:
            facts.append({"fact": "first_goal_of_season", "season": current_season})
        return {
            "query_id": query_id("goal_context", {"player_id": player_id, "is_home": is_home}),
            "player_id": player_id,
            "known_as": p["known_as"],
            "career_goals_before": career_goals,
            "season_goals_before": season_goals,
            "facts": facts,
            "evidence": [m for m in (last_any, last_venue) if m],
        }

    def milestones_near(self, player_id: str, within: int = 3) -> dict[str, Any]:
        lines = self._lines(player_id)
        goals, apps = sum(x["goals"] for x in lines), len(lines)
        near = []
        for target in GOAL_MILESTONES:
            if 0 < target - goals <= within:
                near.append({"kind": "goals", "target": target, "needed": target - goals})
        for target in APP_MILESTONES:
            if 0 < target - apps <= within:
                near.append({"kind": "appearances", "target": target, "needed": target - apps})
        return {
            "query_id": query_id("milestones_near", {"player_id": player_id, "within": within}),
            "player_id": player_id,
            "goals": goals,
            "apps": apps,
            "near": near,
            "evidence": [],
        }

    def head_to_head(self, club_a: str, club_b: str, last: int = 10) -> dict[str, Any]:
        rows = self.con.execute(
            """SELECT * FROM matches WHERE (home = ? AND away = ?) OR (home = ? AND away = ?)
               ORDER BY season_order DESC, matchday DESC LIMIT ?""",
            (club_a, club_b, club_b, club_a, last),
        ).fetchall()
        w = d = lost = 0
        for r in rows:
            ga, gb = (
                (r["home_goals"], r["away_goals"])
                if r["home"] == club_a
                else (r["away_goals"], r["home_goals"])
            )
            w, d, lost = (w + 1, d, lost) if ga > gb else (w, d + 1, lost) if ga == gb else (w, d, lost + 1)
        return {
            "query_id": query_id("head_to_head", {"a": club_a, "b": club_b, "last": last}),
            "club_a": club_a,
            "club_b": club_b,
            "meetings": len(rows),
            "a_wins": w,
            "draws": d,
            "b_wins": lost,
            "last_meeting": dict(rows[0]) if rows else None,
            "evidence": [r["match_id"] for r in rows],
        }

    def club_form(self, club_id: str, last: int = 5) -> dict[str, Any]:
        rows = self.con.execute(
            """SELECT * FROM matches WHERE home = ? OR away = ? ORDER BY season_order DESC, matchday DESC""",
            (club_id, club_id),
        ).fetchall()
        results = []
        for r in rows:
            gf, ga = (
                (r["home_goals"], r["away_goals"])
                if r["home"] == club_id
                else (r["away_goals"], r["home_goals"])
            )
            results.append("W" if gf > ga else "D" if gf == ga else "L")
        unbeaten = 0
        for res in results:
            if res == "L":
                break
            unbeaten += 1
        winless = 0
        for res in results:
            if res == "W":
                break
            winless += 1
        return {
            "query_id": query_id("club_form", {"club_id": club_id, "last": last}),
            "club_id": club_id,
            "name": self._club_name(club_id),
            "form": "".join(results[:last][::-1]),
            "unbeaten_run": unbeaten,
            "winless_run": winless,
            "evidence": [r["match_id"] for r in rows[:last]],
        }

    def top_scorers(self, season: str | None = None, limit: int = 10) -> dict[str, Any]:
        sql = """SELECT l.player_id, p.name, SUM(l.goals) AS goals, COUNT(*) AS apps
                 FROM player_lines l JOIN players p ON p.player_id = l.player_id
                 JOIN matches m ON m.match_id = l.match_id
                 WHERE (? IS NULL OR m.season = ?)
                 GROUP BY l.player_id, p.name ORDER BY goals DESC, apps ASC LIMIT ?"""
        rows = self.con.execute(sql, (season, season, limit)).fetchall()
        return {
            "query_id": query_id("top_scorers", {"season": season, "limit": limit}),
            "season": season or "all",
            "rows": [dict(r) for r in rows],
            "evidence": [],
        }
