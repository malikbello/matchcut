"""Compact match feed for screens: who is playing, and where everyone is, 5 times a second.

The Studio's 2D data pitch (also the fallback tier of the 3D show camera) draws
from this. Positions are decimetres as integers to keep the file small; the API
serves the pre-compressed file as is. Layout:

    {"match_id", "hz", "slots": [team per slot], "players": {id: {num, name}},
     "teams": {home|away: {id, code, name, kit, players: {slot: {id, num, name}}}},
     "t": [ms...], "p": [[x, y, x, y, ... 22 slots ...]...], "b": [[x, y, z]...],
     "period": [1|2...], "changes": [{t, slot, id}], "goals": [{t, side}], "possession": [home % per minute]}

An empty slot (a player sent off) is written as -1, -1.
"""

from __future__ import annotations

import gzip
import json
from pathlib import Path
from typing import Any

from matchcut_contracts import EventType, Outcome

from matchcut_sim.engine import MatchResult
from matchcut_sim.league import League, match_kits

FEED_HZ = 5


def build_feed(m: MatchResult, league: League, hz: int = FEED_HZ) -> dict[str, Any]:
    home, away = league.club(m.meta.home_club_id), league.club(m.meta.away_club_id)
    kits = dict(zip((home.club_id, away.club_id), match_kits(home, away), strict=True))
    step = max(1, round(10 / hz))
    teams: dict[str, Any] = {}
    for side, club in (("home", home), ("away", away)):
        slots = {}
        for slot, team in enumerate(m.team_of_slot):
            if team != club.club_id:
                continue
            r = int(m.roster[0, slot])
            if r >= 0:
                p = league.player(m.player_ids[r])
                slots[str(slot)] = {"id": p.player_id, "num": p.shirt_number, "name": p.known_as}
        teams[side] = {
            "id": club.club_id,
            "code": club.short_name,
            "name": club.name,
            "kit": kits[club.club_id].model_dump(),
            "players": slots,
        }
    players = {
        p.player_id: {"num": p.shirt_number, "name": p.known_as}
        for p in league.players
        if p.player_id in set(m.player_ids)
    }
    idx = range(0, len(m.t_ms), step)
    # who occupies each slot changes with substitutions and red cards
    changes = []
    for i in range(1, len(m.t_ms)):
        for slot in range(len(m.team_of_slot)):
            before, now = int(m.roster[i - 1, slot]), int(m.roster[i, slot])
            if before != now:
                changes.append(
                    {"t": int(m.t_ms[i]), "slot": slot, "id": m.player_ids[now] if now >= 0 else None}
                )
    frames = []
    for i in idx:
        row: list[int] = []
        for slot in range(len(m.team_of_slot)):
            if int(m.roster[i, slot]) < 0:
                row += [-1, -1]
            else:
                row += [round(float(m.pos[i, slot, 0]) * 10), round(float(m.pos[i, slot, 1]) * 10)]
        frames.append(row)
    return {
        "match_id": m.meta.match_id,
        "hz": hz,
        "slots": m.team_of_slot,
        "players": players,
        "teams": teams,
        "t": [int(m.t_ms[i]) for i in idx],
        "period": [int(m.period[i]) for i in idx],
        "p": frames,
        "b": [[round(float(m.ball[i, k]) * 10) for k in range(3)] for i in idx],
        "changes": changes,
        "goals": [
            {"t": e.t_ms, "side": "home" if e.team_id == home.club_id else "away"}
            for e in m.events
            if e.type == EventType.GOAL
        ],
        "possession": possession_by_minute(m),
    }


def possession_by_minute(m: MatchResult) -> list[int]:
    """Home share of completed passes so far, per minute (the pass-share measure Opta uses), as a percent."""
    home = m.meta.home_club_id
    minutes = int(m.t_ms[-1] // 60000) + 1
    counts = [[0, 0] for _ in range(minutes)]
    for e in m.events:
        if e.type == EventType.PASS and e.outcome == Outcome.SUCCESS and e.team_id:
            counts[min(e.t_ms // 60000, minutes - 1)][0 if e.team_id == home else 1] += 1
    out, h, a = [], 0, 0
    for ch, ca in counts:
        h, a = h + ch, a + ca
        out.append(round(100 * h / (h + a)) if h + a else 50)
    return out


def write_feed(m: MatchResult, league: League, out_dir: str | Path, hz: int = FEED_HZ) -> Path:
    """Write ``<match_id>.json.gz``: compressed once here, served as a static file."""
    out = Path(out_dir) / f"{m.meta.match_id}.json.gz"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(
        gzip.compress(json.dumps(build_feed(m, league, hz), separators=(",", ":")).encode(), mtime=0)
    )
    return out
