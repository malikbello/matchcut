"""Past seasons for League Memory: results and per-player match lines.

Scorelines use the Dixon-Coles model (Dixon & Coles, 1997): Poisson goals
with home advantage plus a low-score dependence correction (tau) that fixes
how often 0-0, 1-0, 0-1 and 1-1 occur. A season of 380 matches generates in a
fraction of a second, so five seasons of history are cheap. Players are
credited from that season's actual squads, keeping careers consistent across
transfers.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field

from matchcut_contracts import Player, Position

HOME_BASE = 1.42  # average home goals in an evenly matched game
AWAY_BASE = 1.16
HOME_EDGE = 0.06
RHO = -0.13  # Dixon-Coles low-score dependence
STRENGTH_SCALE = 15.0  # rating points per unit of log goal-rate difference


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
    seasons: list[str] = field(default_factory=list)
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


def _pois(k: int, lam: float) -> float:
    return math.exp(-lam) * lam**k / math.factorial(k)


def _tau(i: int, j: int, lh: float, la: float, rho: float) -> float:
    if i == 0 and j == 0:
        return 1 - lh * la * rho
    if i == 0 and j == 1:
        return 1 + lh * rho
    if i == 1 and j == 0:
        return 1 + la * rho
    if i == 1 and j == 1:
        return 1 - rho
    return 1.0


def dixon_coles_score(
    rng: random.Random, lh: float, la: float, rho: float = RHO, max_goals: int = 10
) -> tuple[int, int]:
    """Draw a scoreline from the Dixon-Coles corrected bivariate grid (renormalised)."""
    cells = [
        (i, j, _pois(i, lh) * _pois(j, la) * _tau(i, j, lh, la, rho))
        for i in range(max_goals + 1)
        for j in range(max_goals + 1)
    ]
    total = sum(w for _, _, w in cells)
    r = rng.random() * total
    acc = 0.0
    for i, j, w in cells:
        acc += w
        if r <= acc:
            return i, j
    return cells[-1][0], cells[-1][1]


def goal_rates(home_rating: float, away_rating: float) -> tuple[float, float]:
    d = (home_rating - away_rating) / STRENGTH_SCALE
    return HOME_BASE * math.exp(d / 2 + HOME_EDGE), AWAY_BASE * math.exp(-d / 2)


def simulate_season(
    rng: random.Random,
    season: str,
    ratings: dict[str, float],
    squads: dict[str, list[Player]],
) -> tuple[list[HistMatch], list[PlayerLine]]:
    matches: list[HistMatch] = []
    lines: list[PlayerLine] = []
    schedule = round_robin(sorted(ratings))
    rng.shuffle(schedule)
    for md, day in enumerate(schedule, start=1):
        for home, away in day:
            lh, la = goal_rates(ratings[home], ratings[away])
            hg, ag = dixon_coles_score(rng, lh, la)
            mid = f"{season}-{md:02d}-{home}-{away}"
            matches.append(HistMatch(mid, season, md, home, away, hg, ag))
            for cid, opp, gf, ga, is_home in ((home, away, hg, ag, True), (away, home, ag, hg, False)):
                lines.extend(_player_lines(rng, squads[cid], mid, season, md, cid, opp, gf, ga, is_home))
    return matches, lines


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


def _weight(p: Player, attr: str, by_pos: dict[Position, float]) -> float:
    return max(0.01, by_pos.get(p.position, 0.05) * (getattr(p, attr) / 70.0) ** 3)


def _player_lines(rng, squad, mid, season, md, cid, opp, gf, ga, is_home) -> list[PlayerLine]:
    gks = sorted((p for p in squad if p.position == Position.GK), key=lambda p: -p.goalkeeping)
    outfield = [p for p in squad if p.position != Position.GK]
    keeper = gks[0] if rng.random() < 0.9 or len(gks) < 2 else gks[1]
    # a plausible XI: the best keeper (occasionally the second),
    # then 10 outfield players by quality with rotation noise
    ranked = sorted(
        outfield, key=lambda p: -(p.passing + p.defending + p.shooting + p.pace) / 4 - rng.gauss(0, 4)
    )
    xi = [keeper, *ranked[:10]]
    bench = ranked[10:16]
    subs_on = rng.sample(bench, k=min(3, len(bench)))
    subs_off = rng.sample(xi[1:], k=len(subs_on))
    minutes = {p.player_id: 90 for p in xi}
    for off, on in zip(subs_off, subs_on, strict=True):
        m = rng.randint(55, 85)
        minutes[off.player_id] = m
        minutes[on.player_id] = 90 - m
    on_pitch = [*xi, *subs_on]
    goals = dict.fromkeys(minutes, 0)
    assists = dict.fromkeys(minutes, 0)
    for _ in range(gf):
        scorer = rng.choices(
            on_pitch, weights=[_weight(p, "shooting", SCORER) * minutes[p.player_id] for p in on_pitch]
        )[0]
        goals[scorer.player_id] += 1
        if rng.random() < 0.72:
            pool = [p for p in on_pitch if p.player_id != scorer.player_id]
            wts = [_weight(p, "passing", CREATOR) * minutes[p.player_id] for p in pool]
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
