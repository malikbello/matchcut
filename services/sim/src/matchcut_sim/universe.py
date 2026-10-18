"""Five seasons of the Harbour League with a real off-season every summer.

Each summer, in this order:
1. Promotion and relegation: the bottom three go down; three second-tier clubs
   come up (stronger squads are more likely to win promotion).
2. Ageing: attributes move along position-specific curves. Development before
   the peak, a plateau, then decline. Peaks follow published ageing research:
   wingers and attacking midfielders peak earliest (~26), centre-backs later
   (~29), goalkeepers latest (~30). Pace peaks two years before overall quality.
3. Retirements: likely from 33, certain by 37 (goalkeepers two years later).
4. Transfers: stronger top-flight clubs buy the best younger players of weaker
   clubs; the buyer sends its weakest player in that position the other way.
5. Academy graduates (ages 17-19) fill any gaps in the 25-man squad plan.

The universe is deterministic for a seed and cached, so every service sees the
same league, careers and history.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from functools import lru_cache

from matchcut_contracts import Club, Foot, Player, Position

from matchcut_sim.history import History, simulate_season
from matchcut_sim.league import (
    CLUBS,
    GIVEN,
    LEAGUE_NAME,
    SHIRT_POOL,
    SQUAD_PLAN,
    TOP_FLIGHT_START,
    League,
    clamp,
    club_from_row,
    make_ratings,
    overall,
    surname,
)

FIRST_SEASON_START = 2021
SEASONS = 5
CURRENT_PLAYED = 8  # matchdays of the current season already played before the live match
PEAK_AGE = {
    Position.GK: 30,
    Position.CB: 29,
    Position.FB: 27,
    Position.DM: 28,
    Position.CM: 27,
    Position.AM: 26,
    Position.W: 26,
    Position.ST: 27,
}
ATTRS = ["pace", "passing", "shooting", "dribbling", "defending", "stamina", "goalkeeping"]


def season_label(start_year: int) -> str:
    return f"{start_year}-{(start_year + 1) % 100:02d}"


@dataclass(frozen=True)
class Transfer:
    season: str  # the season the player joins for
    player_id: str
    from_club: str
    to_club: str


@dataclass(frozen=True)
class CareerEvent:
    season: str
    player_id: str
    kind: str  # retired | academy_debut
    club_id: str


@dataclass
class Universe:
    league: League
    history: History
    top_flight: dict[str, list[str]] = field(default_factory=dict)  # season -> club ids
    promoted: dict[str, list[str]] = field(default_factory=dict)  # season -> clubs promoted into it
    relegated: dict[str, list[str]] = field(default_factory=dict)  # season -> clubs relegated after it
    transfers: list[Transfer] = field(default_factory=list)
    careers: list[CareerEvent] = field(default_factory=list)
    all_players: dict[str, Player] = field(
        default_factory=dict
    )  # every player who ever appeared, final state
    club_names: dict[str, str] = field(default_factory=dict)
    next_matchday: int = 1  # the live match is played on this matchday of the current season
    next_fixtures: list[tuple[str, str]] = field(default_factory=list)


class _Builder:
    def __init__(self, seed: int):
        self.rng = random.Random(seed)
        self.next_id = 1
        self.rows = {row[0]: row for row in CLUBS}
        self.styles = {cid: club_from_row(row, self.rng, 70) for cid, row in self.rows.items()}
        self.players: dict[str, Player] = {}
        self.squads: dict[str, list[str]] = {cid: [] for cid in self.rows}
        self.u = Universe(league=League(LEAGUE_NAME, "", [], []), history=History())
        self.u.club_names = {cid: row[1] for cid, row in self.rows.items()}
        for cid, row in self.rows.items():
            for pos, n in SQUAD_PLAN.items():
                for _ in range(n):
                    self._new_player(
                        cid,
                        pos,
                        level=row[10] + self.rng.gauss(0, 3.5),
                        year=FIRST_SEASON_START,
                        age=self.rng.randint(18, 33),
                    )

    # ------------------------------------------------------------ players
    def _free_shirt(self, cid: str) -> int:
        used = {self.players[p].shirt_number for p in self.squads[cid]}
        return next(n for n in SHIRT_POOL if n not in used)

    def _new_player(self, cid: str, pos: Position, level: float, year: int, age: int) -> Player:
        pid = f"p{self.next_id:05d}"
        self.next_id += 1
        names = {self.players[p].known_as for p in self.squads[cid]}
        sn = surname(self.rng)
        while sn in names:
            sn = surname(self.rng)
        p = Player(
            player_id=pid,
            club_id=cid,
            name=f"{self.rng.choice(GIVEN)} {sn}",
            known_as=sn,
            shirt_number=self._free_shirt(cid),
            position=pos,
            foot=Foot.LEFT if self.rng.random() < 0.24 else Foot.RIGHT,
            birth_year=year - age,
            **make_ratings(self.rng, pos, level),
        )
        self.players[pid] = p
        self.squads[cid].append(pid)
        return p

    def club_rating(self, cid: str) -> float:
        best = sorted((overall(self.players[p]) for p in self.squads[cid]), reverse=True)[:16]
        return sum(best) / len(best)

    # ------------------------------------------------------------ off-season
    def age(self, year: int) -> None:
        for pid, p in list(self.players.items()):
            if p.club_id == "retired":
                continue
            age = year - p.birth_year
            peak = PEAK_AGE[p.position]
            upd = {}
            for a in ATTRS:
                pk = peak - 2 if a == "pace" else peak
                if age <= pk - 4:
                    d = self.rng.gauss(2.8, 1.4)
                elif age <= pk - 1:
                    d = self.rng.gauss(1.3, 1.0)
                elif age <= pk + 1:
                    d = self.rng.gauss(0.0, 0.9)
                elif age <= pk + 4:
                    d = self.rng.gauss(-1.3, 1.0)
                else:
                    d = self.rng.gauss(-2.6, 1.2)
                if a == "pace" and age >= 30:
                    d -= 0.6
                upd[a] = clamp(getattr(p, a) + d)
            self.players[pid] = p.model_copy(update=upd)

    def retire(self, year: int, season: str) -> None:
        for cid, squad in self.squads.items():
            for pid in list(squad):
                p = self.players[pid]
                age = year - p.birth_year
                start = 35 if p.position == Position.GK else 33
                prob = 0.0 if age < start else min(1.0, 0.18 + 0.2 * (age - start))
                if self.rng.random() < prob:
                    squad.remove(pid)
                    self.players[pid] = p.model_copy(update={"club_id": "retired"})
                    self.u.careers.append(CareerEvent(season, pid, "retired", cid))

    def transfers(self, season: str, top: list[str]) -> None:
        ratings = {cid: self.club_rating(cid) for cid in self.squads}
        buyers = sorted(top, key=lambda c: -ratings[c])
        for _ in range(34):
            weights = [math.exp((ratings[c] - 70) / 4) for c in buyers]
            buyer = self.rng.choices(buyers, weights=weights)[0]
            seller = self.rng.choice(
                [c for c in self.squads if c != buyer and ratings[c] < ratings[buyer] + 2]
            )
            candidates = [
                p
                for p in (self.players[x] for x in self.squads[seller])
                if year_age(p, season) <= 29 and p.position != Position.GK
            ]
            if not candidates:
                continue
            star = max(candidates, key=overall)
            same = [self.players[x] for x in self.squads[buyer] if self.players[x].position == star.position]
            if not same:
                continue
            weakest = min(same, key=overall)
            if overall(star) <= overall(weakest) + 1:
                continue
            if star.known_as in {self.players[x].known_as for x in self.squads[buyer]}:
                continue  # avoid two players with the same name in one squad
            # swap clubs and shirt numbers
            s_num, w_num = star.shirt_number, weakest.shirt_number
            self.squads[seller].remove(star.player_id)
            self.squads[buyer].remove(weakest.player_id)
            self.players[star.player_id] = star.model_copy(update={"club_id": buyer, "shirt_number": w_num})
            self.players[weakest.player_id] = weakest.model_copy(
                update={"club_id": seller, "shirt_number": s_num}
            )
            self.squads[buyer].append(star.player_id)
            self.squads[seller].append(weakest.player_id)
            self.u.transfers.append(Transfer(season, star.player_id, seller, buyer))
            self.u.transfers.append(Transfer(season, weakest.player_id, buyer, seller))
            ratings[buyer], ratings[seller] = self.club_rating(buyer), self.club_rating(seller)

    def academy(self, year: int, season: str) -> None:
        for cid, squad in self.squads.items():
            counts = dict.fromkeys(SQUAD_PLAN, 0)
            for pid in squad:
                counts[self.players[pid].position] += 1
            base = self.rows[cid][10]
            for pos, need in SQUAD_PLAN.items():
                for _ in range(max(0, need - counts[pos])):
                    p = self._new_player(
                        cid,
                        pos,
                        level=base - 9 + self.rng.gauss(0, 4),
                        year=year,
                        age=self.rng.randint(17, 19),
                    )
                    self.u.careers.append(CareerEvent(season, p.player_id, "academy_debut", cid))

    # ------------------------------------------------------------ run
    def run(self) -> Universe:
        top = list(TOP_FLIGHT_START)
        second = [c for c in self.rows if c not in top]
        for i in range(SEASONS):
            year = FIRST_SEASON_START + i
            season = season_label(year)
            self.u.top_flight[season] = list(top)
            ratings = {c: self.club_rating(c) for c in top}
            squads = {c: [self.players[p] for p in self.squads[c]] for c in top}
            matches, lines = simulate_season(self.rng, season, ratings, squads)
            self.u.history.seasons.append(season)
            self.u.history.matches.extend(matches)
            self.u.history.lines.extend(lines)
            # summer
            table = self.u.history.table(season)
            down = [str(r["club_id"]) for r in table[-3:]]
            sec_r = {c: self.club_rating(c) + self.rng.gauss(0, 2.5) for c in second}
            up = sorted(second, key=lambda c: -sec_r[c])[:3]
            self.u.relegated[season] = down
            next_season = season_label(year + 1)
            self.u.promoted[next_season] = up
            top = [c for c in top if c not in down] + up
            second = [c for c in second if c not in up] + down
            self.age(year + 1)
            self.retire(year + 1, next_season)
            self.transfers(next_season, top)
            self.academy(year + 1, next_season)
        current = season_label(FIRST_SEASON_START + SEASONS)
        self.u.top_flight[current] = list(top)
        clubs = []
        for cid in top:
            base = self.styles[cid]
            clubs.append(base.model_copy(update={"rating": round(self.club_rating(cid))}))
        players = [self.players[p] for c in top for p in self.squads[c]]
        self.u.league = League(LEAGUE_NAME, current, clubs, players)
        # the current season so far: matchdays 1..CURRENT_PLAYED, then the live matchday
        ratings = {c: self.club_rating(c) for c in top}
        squads = {c: [self.players[p] for p in self.squads[c]] for c in top}
        matches, lines = simulate_season(self.rng, current, ratings, squads)
        played = {m.match_id for m in matches if m.matchday <= CURRENT_PLAYED}
        self.u.history.seasons.append(current)
        self.u.history.matches.extend(m for m in matches if m.match_id in played)
        self.u.history.lines.extend(ln for ln in lines if ln.match_id in played)
        self.u.next_matchday = CURRENT_PLAYED + 1
        self.u.next_fixtures = [(m.home, m.away) for m in matches if m.matchday == CURRENT_PLAYED + 1]
        self.u.all_players = dict(self.players)
        return self.u


def year_age(p: Player, season: str) -> int:
    return int(season[:4]) - p.birth_year


@lru_cache(maxsize=4)
def build_universe(seed: int = 2026) -> Universe:
    return _Builder(seed).run()


def current_clubs(u: Universe) -> list[Club]:
    return u.league.clubs
