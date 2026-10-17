"""League Memory database: schema and loader.

Portable SQL (SQLite locally, Azure SQL in the cloud). Tables are append-only
history; the live match is never written here.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from matchcut_sim.universe import Universe

SCHEMA = """
CREATE TABLE clubs (club_id TEXT PRIMARY KEY, name TEXT NOT NULL, short_name TEXT, ground TEXT);
CREATE TABLE players (player_id TEXT PRIMARY KEY, name TEXT NOT NULL, known_as TEXT NOT NULL, position TEXT NOT NULL,
                      birth_year INTEGER NOT NULL, current_club TEXT NOT NULL);
CREATE TABLE season_clubs (season TEXT NOT NULL, club_id TEXT NOT NULL, tier INTEGER NOT NULL,
                           PRIMARY KEY (season, club_id));
CREATE TABLE matches (match_id TEXT PRIMARY KEY, season TEXT NOT NULL, season_order INTEGER NOT NULL,
                      matchday INTEGER NOT NULL, home TEXT NOT NULL, away TEXT NOT NULL,
                      home_goals INTEGER NOT NULL, away_goals INTEGER NOT NULL);
CREATE TABLE player_lines (match_id TEXT NOT NULL, player_id TEXT NOT NULL, club_id TEXT NOT NULL,
                           opponent_id TEXT NOT NULL, home INTEGER NOT NULL, started INTEGER NOT NULL,
                           minutes INTEGER NOT NULL, goals INTEGER NOT NULL, assists INTEGER NOT NULL,
                           yellow INTEGER NOT NULL, red INTEGER NOT NULL, clean_sheet INTEGER NOT NULL,
                           PRIMARY KEY (match_id, player_id));
CREATE TABLE transfers (season TEXT NOT NULL, player_id TEXT NOT NULL, from_club TEXT NOT NULL, to_club TEXT NOT NULL);
CREATE INDEX ix_lines_player ON player_lines (player_id);
CREATE INDEX ix_matches_order ON matches (season_order, matchday);
"""  # noqa: E501


def build_db(u: Universe, path: str | Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()
    con = sqlite3.connect(path)
    try:
        con.executescript(SCHEMA)
        con.executemany(
            "INSERT INTO clubs VALUES (?,?,?,?)",
            [(cid, name, cid.upper(), "") for cid, name in u.club_names.items()],
        )
        con.executemany(
            "INSERT INTO players VALUES (?,?,?,?,?,?)",
            [
                (p.player_id, p.name, p.known_as, p.position.value, p.birth_year, p.club_id)
                for p in u.all_players.values()
            ],
        )
        for season, clubs in u.top_flight.items():
            con.executemany("INSERT INTO season_clubs VALUES (?,?,1)", [(season, c) for c in clubs])
        order = {s: i for i, s in enumerate(u.history.seasons)}
        con.executemany(
            "INSERT INTO matches VALUES (?,?,?,?,?,?,?,?)",
            [
                (
                    m.match_id,
                    m.season,
                    order[m.season],
                    m.matchday,
                    m.home,
                    m.away,
                    m.home_goals,
                    m.away_goals,
                )
                for m in u.history.matches
            ],
        )
        con.executemany(
            "INSERT INTO player_lines VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            [
                (
                    ln.match_id,
                    ln.player_id,
                    ln.club_id,
                    ln.opponent_id,
                    int(ln.home),
                    int(ln.started),
                    ln.minutes,
                    ln.goals,
                    ln.assists,
                    ln.yellow,
                    ln.red,
                    int(ln.clean_sheet),
                )
                for ln in u.history.lines
            ],
        )
        con.executemany(
            "INSERT INTO transfers VALUES (?,?,?,?)",
            [(t.season, t.player_id, t.from_club, t.to_club) for t in u.transfers],
        )
        con.commit()
    finally:
        con.close()
    return path
