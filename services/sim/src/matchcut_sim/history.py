"""Past seasons for League Memory: results and per-player match lines.

A fast team-strength model (Poisson goals with home advantage) rather than the
full engine, so two seasons (760 matches) generate in about a second. Players
are credited from the same squads the live engine uses, which keeps careers,
streaks and records consistent with what fans see live.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field

from matchcut_contracts import Position

from matchcut_sim.league import League

HOME_ADVANTAGE = 0.22
BASE_GOALS = 1.32


@dataclass(frozen=True)
class HistMatch:
    match_id: str
    season: str
    matchday: int
    home: str
    away: str
    home_goals: int
    away_goals: int


@dataclass(frozen=True)
class PlayerLine:
    match_id: str
    season: str
    matchday: int
    player_id: str
    club_id: str
    opponent_id: str
    home: bool
    started: bool
    minutes: int
    goals: int
    assists: int
    yellow: int
    red: int
    clean_sheet: bool


@dataclass
class History:
    seasons: list[str]
    matches: list[HistMatch] = field(default_factory=list)
    lines: list[PlayerLine] = field(default_factory=list)

    def table(self, season: str) -> list[dict[str, int | str]]:
        rows: dict[str, dict[str, int | str]] = {}
        for m in (m for m in self.matches if m.season == season):
            for cid, gf, ga in ((m.home, m.home_goals, m.away_goals), (m.away, m.away_goals, m.home_goals)):
                r = rows.setdefault(
                    cid, {"club_id": cid, "p": 0, "w": 0, "d": 0, "l": 0, "gf": 0, "ga": 0, "pts": 0}
                )
                r["p"] = int(r["p"]) + 1
                r["gf"] = int(r["gf"]) + gf
                r["ga"] = int(r["ga"]) + ga
                key, pts = ("w", 3) if gf > ga else ("d", 1) if gf == ga else ("l", 0)
                r[key] = int(r[key]) + 1
                r["pts"] = int(r["pts"]) + pts
        return sorted(
            rows.values(), key=lambda r: (-int(r["pts"]), -(int(r["gf"]) - int(r["ga"])), -int(r["gf"]))
        )


def round_robin(club_ids: list[str]) -> list[list[tuple[str, str]]]:
    """Double round robin (circle method): 38 matchdays for 20 clubs, home and away balanced."""
    ids = list(club_ids)
    n = len(ids)
    first: list[list[tuple[str, str]]] = []
    for rnd in range(n - 1):
        pairs = []
        for i in range(n // 2):
            a, b = ids[i], ids[n - 1 - i]
            pairs.append((a, b) if (rnd + i) % 2 == 0 else (b, a))
        first.append(pairs)
        ids = [ids[0], ids[-1], *ids[1:-1]]
    second = [[(b, a) for a, b in day] for day in first]
    return first + second


def _poisson(rng: random.Random, lam: float) -> int:
    limit, k, p = math.exp(-lam), 0, 1.0
    while True:
        p *= rng.random()
        if p <= limit:
            return k
        k += 1


def _weights(players, attr: str, by_pos: dict[Position, float]) -> list[float]:
    return [max(0.01, by_pos.get(p.position, 0.05) * (getattr(p, attr) / 70.0) ** 3) for p in players]


def simulate_history(league: League, seasons: list[str], seed: int = 7) -> History:
    rng = random.Random(seed)
    hist = History(seasons=seasons)
    strength = {c.club_id: (c.rating - 74) / 22.0 for c in league.clubs}
    for season in seasons:
        # strength drifts a little season to season
        drift = {cid: s + rng.gauss(0, 0.05) for cid, s in strength.items()}
        schedule = round_robin([c.club_id for c in league.clubs])
        rng.shuffle(schedule)
        for md, day in enumerate(schedule, start=1):
            for home, away in day:
                lam_h = BASE_GOALS * math.exp(drift[home] - drift[away] + HOME_ADVANTAGE)
                lam_a = BASE_GOALS * math.exp(drift[away] - drift[home])
                hg, ag = _poisson(rng, lam_h), _poisson(rng, lam_a)
                mid = f"{season}-{md:02d}-{home}-{away}"
                hist.matches.append(HistMatch(mid, season, md, home, away, hg, ag))
                for cid, opp, gf, ga, is_home in ((home, away, hg, ag, True), (away, home, ag, hg, False)):
                    hist.lines.extend(_player_lines(rng, league, mid, season, md, cid, opp, gf, ga, is_home))
    return hist


SCORER = {
    Position.ST: 1.0,
    Position.W: 0.6,
    Position.AM: 0.55,
    Position.CM: 0.22,
    Position.DM: 0.08,
    Position.FB: 0.07,
    Position.CB: 0.09,
}
CREATOR = {
    Position.AM: 1.0,
    Position.W: 0.85,
    Position.CM: 0.6,
    Position.ST: 0.45,
    Position.FB: 0.4,
    Position.DM: 0.25,
    Position.CB: 0.06,
}


def _player_lines(rng, league, mid, season, md, cid, opp, gf, ga, is_home) -> list[PlayerLine]:
    squad = league.squad(cid)
    gks = [p for p in squad if p.position == Position.GK]
    outfield = [p for p in squad if p.position != Position.GK]
    # a plausible XI: the best keeper (occasionally the second),
    # then 10 outfield players by rating with rotation noise
    keeper = gks[0] if rng.random() < 0.9 else gks[1]
    ranked = sorted(
        outfield, key=lambda p: -(p.passing + p.defending + p.shooting + p.pace) / 4 - rng.gauss(0, 4)
    )
    xi = [keeper, *ranked[:10]]
    bench = ranked[10:16]
    subs_on = rng.sample(bench, k=3)
    subs_off = rng.sample(xi[1:], k=3)
    minutes = {p.player_id: 90 for p in xi}
    for off, on in zip(subs_off, subs_on, strict=True):
        m = rng.randint(55, 85)
        minutes[off.player_id] = m
        minutes[on.player_id] = 90 - m
    on_pitch = list(xi) + subs_on
    goals = dict.fromkeys(minutes, 0)
    assists = dict.fromkeys(minutes, 0)
    sw = _weights(on_pitch, "shooting", SCORER)
    cw = _weights(on_pitch, "passing", CREATOR)
    for _ in range(gf):
        scorer = rng.choices(
            on_pitch, weights=[w * minutes[p.player_id] for p, w in zip(on_pitch, sw, strict=True)]
        )[0]
        goals[scorer.player_id] += 1
        if rng.random() < 0.72:
            pool = [p for p in on_pitch if p.player_id != scorer.player_id]
            wts = [cw[on_pitch.index(p)] * minutes[p.player_id] for p in pool]
            assists[rng.choices(pool, weights=wts)[0].player_id] += 1
    out = []
    for p in on_pitch:
        yellow = 1 if rng.random() < 0.09 * (1.4 if p.position in (Position.CB, Position.DM) else 1.0) else 0
        red = 1 if rng.random() < 0.004 else 0
        out.append(
            PlayerLine(
                mid,
                season,
                md,
                p.player_id,
                cid,
                opp,
                is_home,
                p in xi,
                minutes[p.player_id],
                goals[p.player_id],
                assists[p.player_id],
                yellow,
                red,
                ga == 0 and p.position in (Position.GK, Position.CB, Position.FB),
            )
        )
    return out
