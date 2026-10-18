"""Export a simulated match in the football Common Data Format (CDF v0.3.2).

CDF (Anzer et al., 2025) is the open, vendor-neutral schema for match sheet,
meta, event and tracking data. Exporting to it means any CDF-aware tool can read
Matchcut matches, and the official validator (``common-data-format-validator``)
checks our files in CI. Coordinates are metres with the origin at the centre
spot, as the format specifies. Synthetic matches get a synthetic kick-off date
derived from the season and matchday.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from matchcut_contracts import EventType, MatchEvent, Outcome, Player

from matchcut_sim.engine import MatchResult
from matchcut_sim.football import LENGTH, WIDTH
from matchcut_sim.league import League

CDF_VERSION = "0.3.2"
PERIOD = {1: "first_half", 2: "second_half"}
POSITION_GROUP = {
    "GK": "GK",
    "CB": "DF",
    "FB": "DF",
    "DM": "MF",
    "CM": "MF",
    "AM": "MF",
    "W": "FW",
    "ST": "FW",
}
# CDF positions are side-specific; ours are roles, so full-backs and wingers
# take the side of their stronger foot
CDF_POSITION = {"GK": "GK", "CB": "CB", "DM": "CDM", "CM": "CM", "AM": "CAM", "ST": "CF"}


def cdf_position(p: Player) -> str:
    role = p.position.value
    if role in CDF_POSITION:
        return CDF_POSITION[role]
    side = "L" if p.foot.value == "left" else "R"
    return f"{side}B" if role == "FB" else f"{side}W"


SKIP_EVENTS = {
    EventType.PERIOD_START,
    EventType.PERIOD_END,
    EventType.SUBSTITUTION,
    EventType.POSSESSION_CHANGE,
}


def kickoff(m: MatchResult) -> datetime:
    start_year = int(m.meta.season[:4])
    first_saturday = datetime(start_year, 8, 15, 14, 0, tzinfo=UTC)
    return first_saturday + timedelta(days=7 * (m.meta.matchday - 1))


def _ts(base: datetime, t_ms: int) -> str:
    return (base + timedelta(milliseconds=int(t_ms))).isoformat().replace("+00:00", "Z")


def _xy(x: float | None, y: float | None) -> tuple[float | None, float | None]:
    if x is None or y is None:
        return None, None
    return round(x - LENGTH / 2, 2), round(y - WIDTH / 2, 2)


def _player(p: Player, starter: bool, played: bool) -> dict[str, Any]:
    first, _, last = p.name.partition(" ")
    return {
        "id": p.player_id,
        "first_name": first,
        "last_name": last or p.known_as,
        "short_name": p.known_as,
        "team_id": p.club_id,
        "jersey_number": p.shirt_number,
        "is_starter": starter,
        "has_played": played,
        "position_group": POSITION_GROUP[p.position.value],
        "position": cdf_position(p),
        "foot": p.foot.value,
        "date_of_birth": f"{p.birth_year}-07-01",
    }


def _squad(m: MatchResult, league: League, home: bool) -> tuple[str, list[str], list[str]]:
    meta = m.meta
    return (
        (meta.home_club_id, meta.home_lineup, meta.home_bench)
        if home
        else (meta.away_club_id, meta.away_lineup, meta.away_bench)
    )


def match_sheet(m: MatchResult, league: League) -> dict[str, Any]:
    base = kickoff(m)
    subs_on = {e.recipient_id for e in m.events if e.type == EventType.SUBSTITUTION}
    teams = {}
    for side, home in (("home", True), ("away", False)):
        club_id, lineup, bench = _squad(m, league, home)
        club = league.club(club_id)
        players = [_player(league.player(p), True, True) for p in lineup]
        players += [_player(league.player(p), False, p in subs_on) for p in bench]
        teams[side] = {
            "id": club_id,
            "short_name": club.short_name,
            "formation": club.formation,
            "players": players,
        }
    goals, cards, subs = [], [], []
    score = [0, 0]
    for e in m.events:
        if e.type == EventType.GOAL and e.team_id:
            score[0 if e.team_id == m.meta.home_club_id else 1] += 1
            goals.append(
                {
                    "time": _ts(base, e.t_ms),
                    "period": PERIOD[e.period],
                    "team_id": e.team_id,
                    "player_id": e.player_id,
                    "assist_id": None,
                    "is_own_goal": False,
                    "is_penalty": False,
                    "score": {"home": score[0], "away": score[1]},
                }
            )
        elif e.type == EventType.CARD and e.team_id and e.player_id:
            cards.append(
                {
                    "team_id": e.team_id,
                    "time": _ts(base, e.t_ms),
                    "period": PERIOD[e.period],
                    "player_id": e.player_id,
                    "type": "red_card" if e.detail == "red" else "yellow_card",
                }
            )
        elif e.type == EventType.SUBSTITUTION and e.team_id and e.player_id and e.recipient_id:
            subs.append(
                {
                    "team_id": e.team_id,
                    "in_time": _ts(base, e.t_ms),
                    "in_player_id": e.recipient_id,
                    "out_time": _ts(base, e.t_ms),
                    "out_player_id": e.player_id,
                    "period": PERIOD[e.period],
                }
            )
    first = [
        sum(1 for g in goals if g["team_id"] == t and g["period"] == "first_half")
        for t in (m.meta.home_club_id, m.meta.away_club_id)
    ]
    h, a = m.score
    winner = m.meta.home_club_id if h > a else m.meta.away_club_id if a > h else None
    return {
        "match": {
            "id": m.meta.match_id,
            "status": {"is_neutral": False, "has_extratime": False, "has_shootout": False},
            "result": {
                "final": {"home": h, "away": a, "winning_team_id": winner},
                "first_half": {"home": first[0], "away": first[1]},
                "second_half": {"home": h, "away": a},
            },
        },
        "teams": teams,
        "officials": [{"id": f"{m.meta.match_id}-ref", "type": "main_referee"}],
        "events": {"goals": goals, "substitutions": subs, "cards": cards},
        "meta": {"vendor": "Matchcut (synthetic)"},
    }


def meta_data(m: MatchResult, league: League) -> dict[str, Any]:
    base = kickoff(m)
    p2_start = next((e.t_ms for e in m.events if e.period == 2), m.events[-1].t_ms)
    end = int(m.t_ms[-1])
    p2_frame = int((m.t_ms < p2_start).sum())
    home, away = m.meta.home_club_id, m.meta.away_club_id
    teams = {}
    for side, is_home in (("home", True), ("away", False)):
        club_id, lineup, bench = _squad(m, league, is_home)
        teams[side] = {
            "id": club_id,
            "name": league.club(club_id).name,
            "players": [
                {
                    "id": p,
                    "team_id": club_id,
                    "jersey_number": league.player(p).shirt_number,
                    "is_starter": p in lineup,
                }
                for p in lineup + bench
            ],
        }
    return {
        "competition": {"id": "harbour-league", "name": league.name, "format": "league_20", "type": "mens"},
        "season": {"id": m.meta.season, "name": m.meta.season.replace("-", "/")},
        "match": {
            "id": m.meta.match_id,
            "kickoff_time": _ts(base, 0),
            "periods": [
                {
                    "period": "first_half",
                    "play_direction": "left_right",
                    "start_time": _ts(base, 0),
                    "end_time": _ts(base, p2_start),
                    "frame_id_start": 0,
                    "frame_id_end": max(p2_frame - 1, 0),
                    "left_team_id": home,
                    "right_team_id": away,
                },
                {
                    "period": "second_half",
                    "play_direction": "right_left",
                    "start_time": _ts(base, p2_start),
                    "end_time": _ts(base, end),
                    "frame_id_start": p2_frame,
                    "frame_id_end": len(m.t_ms) - 1,
                    "left_team_id": away,
                    "right_team_id": home,
                },
            ],
            "whistles": [
                {"type": "first_half", "sub_type": "start", "time": _ts(base, 0)},
                {"type": "first_half", "sub_type": "end", "time": _ts(base, p2_start)},
                {"type": "second_half", "sub_type": "start", "time": _ts(base, p2_start)},
                {"type": "second_half", "sub_type": "end", "time": _ts(base, end)},
            ],
            "round": str(m.meta.matchday),
        },
        "teams": teams,
        "venue": {"id": m.meta.ground.lower().replace(" ", "-"), "name": m.meta.ground},
        "meta": {
            "video": None,
            "event": {"collection_timing": "live", "name": "Matchcut simulator", "version": "1"},
            "tracking": {
                "version": "1",
                "name": "Matchcut simulator",
                "fps": 10,
                "collection_timing": "live",
            },
            "landmarks": None,
            "ball": {"version": "1", "name": "Matchcut simulator", "fps": 10, "collection_timing": "live"},
            "meta": {"version": "1", "name": "Matchcut"},
            "cdf": {"version": CDF_VERSION},
        },
    }


def event_record(e: MatchEvent, base: datetime, foot: dict[str, str] | None = None) -> dict[str, Any]:
    """One CDF event. Passes and shots need a body part; passes use the player's stronger foot."""
    x, y = _xy(e.x, e.y)
    x_end, y_end = _xy(e.end_x, e.end_y)
    ok = e.outcome != Outcome.FAIL
    return {
        "match": {"id": e.match_id},
        "meta": {"is_synced": True},
        "event": {
            "id": e.event_id,
            "time": _ts(base, e.t_ms),
            "period": PERIOD[e.period],
            "type": e.type.value,
            "sub_type": e.detail,
            "is_successful": ok,
            "outcome_type": "successful" if ok else "unsuccessful",
            "player_id": e.player_id,
            "team_id": e.team_id,
            "receiver_id": e.recipient_id if e.type == EventType.PASS else None,
            "receiver_time": None,
            "receiver_team_id": e.team_id if e.type == EventType.PASS and e.recipient_id else None,
            "x": x,
            "y": y,
            "x_end": x_end,
            "y_end": y_end,
            "body_part": e.body_part.value
            if e.body_part
            else (
                f"{(foot or {}).get(e.player_id or '', 'right')}_foot"
                if e.type in (EventType.PASS, EventType.SHOT)
                else None
            ),
            "related_event_ids": [e.related_event_id] if e.related_event_id else None,
            "match_clock": e.clock,
        },
    }


def tracking_records(m: MatchResult, every: int = 1) -> Iterator[dict[str, Any]]:
    base = kickoff(m)
    home = m.meta.home_club_id
    for i in range(0, len(m.t_ms), every):
        sides: dict[str, list[dict[str, Any]]] = {"home": [], "away": []}
        for slot, team in enumerate(m.team_of_slot):
            r = int(m.roster[i, slot])
            if r < 0:
                continue
            x, y = _xy(float(m.pos[i, slot, 0]), float(m.pos[i, slot, 1]))
            sides["home" if team == home else "away"].append(
                {"id": m.player_ids[r], "x": x, "y": y, "vel": round(float(m.speed[i, slot]), 2)}
            )
        bx, by = _xy(float(m.ball[i, 0]), float(m.ball[i, 1]))
        yield {
            "frame_id": i,
            "timestamp": _ts(base, int(m.t_ms[i])),
            "period": PERIOD[int(m.period[i])],
            "match": {"id": m.meta.match_id},
            "teams": {
                "home": {"id": home, "players": sides["home"]},
                "away": {"id": m.meta.away_club_id, "players": sides["away"]},
            },
            "ball": {"x": bx, "y": by, "z": round(float(m.ball[i, 2]), 2)},
        }


def export_cdf(m: MatchResult, league: League, out_dir: str | Path, every: int = 1) -> Path:
    """Write match.json, meta.json, event.jsonl and tracking.jsonl; return the folder."""
    out = Path(out_dir) / m.meta.match_id
    out.mkdir(parents=True, exist_ok=True)
    base = kickoff(m)
    foot = {p.player_id: p.foot.value for p in league.players}
    (out / "match.json").write_text(json.dumps(match_sheet(m, league), indent=2), encoding="utf-8")
    (out / "meta.json").write_text(json.dumps(meta_data(m, league), indent=2), encoding="utf-8")
    with (out / "event.jsonl").open("w", encoding="utf-8", newline="\n") as f:
        for e in m.events:
            if e.type not in SKIP_EVENTS and e.x is not None and e.y is not None:
                f.write(json.dumps(event_record(e, base, foot)) + "\n")
    with (out / "tracking.jsonl").open("w", encoding="utf-8", newline="\n") as f:
        for rec in tracking_records(m, every):
            f.write(json.dumps(rec) + "\n")
    return out
