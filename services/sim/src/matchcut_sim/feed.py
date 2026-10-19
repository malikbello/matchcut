"""Compact match feed for screens: who is playing, where everyone is 10 times a second, and what they do.

The Studio's 2D data pitch (also the fallback tier of the 3D show camera) draws
from this. Positions are decimetres as integers to keep the file small; the API
serves the pre-compressed file as is. Layout:

    {"match_id", "hz", "slots": [team per slot], "players": {id: {num, name}},
     "teams": {home|away: {id, code, name, kit, players: {slot: {id, num, name}}}},
     "t": [ms...], "p": [[x, y, x, y, ... 22 slots ...]...], "b": [[x, y, z]...],
     "period": [1|2...], "changes": [{t, slot, id}], "goals": [{t, side}], "possession": [home % per minute],
     "keepers": [slot...], "events": [[t, type, slot, body_part, outcome, x, y, end_x, end_y, to_slot]...],
     "cuts": [t...]}

An empty slot (a player sent off) is written as EMPTY, EMPTY (-9999): real positions can be negative,
since players step behind the goal line or off the touchline.
"""

from __future__ import annotations

import gzip
import json
from itertools import pairwise
from pathlib import Path
from typing import Any

from matchcut_contracts import EventType, Outcome

from matchcut_sim.engine import MatchResult
from matchcut_sim.league import League, match_kits

FEED_HZ = 10  # the engine's native rate: the 3D players need every step
EMPTY = -9999  # an empty slot; never a real position (decimetres)


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
                row += [EMPTY, EMPTY]
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
        "keepers": keeper_slots(m, league),
        "events": action_events(m),
        "cuts": restart_cuts(m, idx),
    }


# On-ball actions the 3D show camera animates. Each row is compact and positional:
#   [t_ms, type, slot, body_part, outcome, x, y, end_x, end_y, recipient_slot]
# x/y in decimetres; -1 where a value is missing. The event time is the moment of contact,
# so an animation's contact frame is aligned to it.
ANIMATED = {
    EventType.PASS,
    EventType.SHOT,
    EventType.SAVE,
    EventType.GOAL,
    EventType.TACKLE,
    EventType.INTERCEPTION,
    EventType.CLEARANCE,
    EventType.BLOCK,
    EventType.BALL_RECOVERY,
    EventType.THROW_IN,
    EventType.CORNER,
    EventType.GOAL_KICK,
    EventType.FREE_KICK,
    EventType.KICK_OFF,
    EventType.FOUL,
    EventType.CARD,
}


def _slot_at(m: MatchResult, player_id: str | None, t_ms: int) -> int:
    """Which feed slot a player occupies at a moment (slots change with substitutions)."""
    if player_id is None or player_id not in m.player_ids:
        return -1
    r = m.player_ids.index(player_id)
    i = min(int(t_ms // 100), len(m.t_ms) - 1)
    hits = [s for s in range(m.roster.shape[1]) if int(m.roster[i, s]) == r]
    return hits[0] if hits else -1


def _dm(v: float | None) -> int:
    return -1 if v is None else round(v * 10)


def action_events(m: MatchResult) -> list[list[Any]]:
    return [
        [
            e.t_ms,
            e.type.value,
            _slot_at(m, e.player_id, e.t_ms),
            e.body_part.value if e.body_part else "",
            e.outcome.value if e.outcome else "",
            _dm(e.x),
            _dm(e.y),
            _dm(e.end_x),
            _dm(e.end_y),
            _slot_at(m, e.recipient_id, e.t_ms),
        ]
        for e in m.events
        if e.type in ANIMATED
    ]


def keeper_slots(m: MatchResult, league: League) -> list[int]:
    """Slots that start in goal (the 3D scene dresses them in the keeper kit)."""
    return [
        slot
        for slot in range(len(m.team_of_slot))
        if int(m.roster[0, slot]) >= 0
        and league.player(m.player_ids[int(m.roster[0, slot])]).position.value == "GK"
    ]


def restart_cuts(m: MatchResult, idx: range, jump_m: float = 4.0) -> list[int]:
    """Times where several players are repositioned at once (restarts after goals, half time).

    A real broadcast cuts away at these moments; the 3D scene cuts too, instead of
    animating players sliding across the pitch.
    """
    frames = list(idx)
    cuts = []
    for a, b in pairwise(frames):
        moved = sum(
            1
            for slot in range(len(m.team_of_slot))
            if int(m.roster[a, slot]) >= 0
            and int(m.roster[b, slot]) >= 0
            and float(((m.pos[b, slot] - m.pos[a, slot]) ** 2).sum()) ** 0.5 > jump_m
        )
        if moved >= 3:
            cuts.append(int(m.t_ms[b]))
    return cuts


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
