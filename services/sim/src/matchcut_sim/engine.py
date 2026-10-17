"""Agent-based match engine with 10 Hz tracking.

Each tick (0.1 s) every player moves toward a tactical target derived from the
team's formation, style and the ball; the ball carrier decides between passing,
carrying and shooting using the same football models analysts use (zone value,
expected goals, pressure). Events are emitted *from* the simulated play, so the
event feed and the tracking data always agree. A hidden truth log records the
tactical changes and true shot probabilities for scoring downstream services.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Literal

import numpy as np
from matchcut_contracts import (
    BodyPart,
    EventType,
    MatchEvent,
    MatchMeta,
    Outcome,
    Player,
    Position,
    TruthRecord,
)

from matchcut_sim.football import (
    FORMATIONS,
    LENGTH,
    WIDTH,
    expected_goals,
    point_segment_distance,
    zone_value,
)
from matchcut_sim.league import League

DT = 0.1
HZ = 10
ROLE_FIT: dict[str, list[Position]] = {
    "GK": [Position.GK],
    "CB": [Position.CB, Position.DM, Position.FB],
    "FB": [Position.FB, Position.CB, Position.W],
    "DM": [Position.DM, Position.CM, Position.CB],
    "CM": [Position.CM, Position.DM, Position.AM],
    "AM": [Position.AM, Position.CM, Position.W],
    "W": [Position.W, Position.AM, Position.ST, Position.FB],
    "ST": [Position.ST, Position.W, Position.AM],
}


@dataclass
class MatchResult:
    meta: MatchMeta
    events: list[MatchEvent]
    truth: list[TruthRecord]
    t_ms: np.ndarray  # (T,) int64
    period: np.ndarray  # (T,) int8
    pos: np.ndarray  # (T, 22, 2) float32, pitch frame metres
    speed: np.ndarray  # (T, 22) float32, m/s
    ball: np.ndarray  # (T, 3) float32
    roster: np.ndarray  # (T, 22) int16 index into player_ids, -1 = slot empty (sent off)
    player_ids: list[str]
    score: tuple[int, int]
    team_of_slot: list[str] = field(default_factory=list)


@dataclass
class _Flight:
    kind: str  # pass | shot | out | cross
    sx: float
    sy: float
    ex: float
    ey: float
    t0: float
    dur: float
    peak: float
    team: int
    success: bool
    target_slot: int | None
    event_id: str
    shot_xg: float = 0.0
    shooter_slot: int | None = None
    result: str = ""  # goal | save | catch | off | block


def _pick_xi(squad: list[Player], formation: str) -> tuple[list[Player], list[Player]]:
    """Fill each formation role with the best-fitting available player."""
    pool = sorted(squad, key=lambda p: -(p.passing + p.defending + p.shooting + p.pace + p.dribbling))
    xi: list[Player] = []
    for role, _, _ in FORMATIONS[formation]:
        chosen = None
        for pos in ROLE_FIT[role]:
            chosen = next((p for p in pool if p.position == pos and p not in xi), None)
            if chosen:
                break
        xi.append(chosen or next(p for p in pool if p not in xi and p.position != Position.GK))
    bench = [p for p in pool if p not in xi]
    gk_bench = [p for p in bench if p.position == Position.GK][:1]
    bench = gk_bench + [p for p in bench if p.position != Position.GK][:6]
    return xi, bench


class _Engine:
    def __init__(
        self, league: League, home_id: str, away_id: str, seed: int, matchday: int, half_minutes: float = 45.0
    ):
        self.r = random.Random(seed)
        self.league = league
        self.match_id = f"{home_id}-{away_id}-{seed}"
        self.clubs = [league.club(home_id), league.club(away_id)]
        self.style = [dict(c.style.model_dump()) for c in self.clubs]
        self.formation = [c.formation for c in self.clubs]
        lineups = [_pick_xi(league.squad(c.club_id), c.formation) for c in self.clubs]
        self.bench: list[list[Player]] = [list(lineups[0][1]), list(lineups[1][1])]
        self.player_ids: list[str] = []
        self.pid_index: dict[str, int] = {}
        for p in [*lineups[0][0], *lineups[1][0], *lineups[0][1], *lineups[1][1]]:
            self.pid_index[p.player_id] = len(self.player_ids)
            self.player_ids.append(p.player_id)
        self.slot_player: list[Player] = [*lineups[0][0], *lineups[1][0]]
        self.slot_role = [r for f in self.formation for r, _, _ in FORMATIONS[f]]
        self.anchor = np.array([(d, w) for f in self.formation for _, d, w in FORMATIONS[f]], dtype=float)
        self.team = np.array([0] * 11 + [1] * 11)
        self.active = np.ones(22, dtype=bool)
        self.phase_offset = np.array([self.r.uniform(0, 2 * math.pi) for _ in range(22)])
        self._load_attrs()
        self.meta = MatchMeta(
            match_id=self.match_id,
            competition=league.name,
            season=league.season,
            matchday=matchday,
            home_club_id=home_id,
            away_club_id=away_id,
            ground=self.clubs[0].ground,
            seed=seed,
            home_formation=self.formation[0],
            away_formation=self.formation[1],
            home_lineup=[p.player_id for p in lineups[0][0]],
            away_lineup=[p.player_id for p in lineups[1][0]],
            home_bench=[p.player_id for p in lineups[0][1]],
            away_bench=[p.player_id for p in lineups[1][1]],
        )
        # time
        stoppage1, stoppage2 = self.r.randint(1, 4), self.r.randint(3, 6)
        self.p1_len = (half_minutes + stoppage1 * half_minutes / 45) * 60.0
        self.p2_len = (half_minutes + stoppage2 * half_minutes / 45) * 60.0
        self.t = 0.0
        self.period: Literal[1, 2] = 1
        # state
        self.pos = np.zeros((22, 2))
        self.vel = np.zeros((22, 2))
        self.ball = np.array([LENGTH / 2, WIDTH / 2, 0.0])
        self.carrier: int | None = None
        self.poss = 0
        self.flight: _Flight | None = None
        self.dead: dict | None = None
        self.next_decision = 0.0
        self.carry_dest: tuple[float, float] | None = None
        self.carry_start: tuple[float, float, float] | None = None
        self.pressured_by: set[int] = set()
        self.tackle_cooldown = 0.0
        self.pending_set_piece: str | None = None
        self.score = [0, 0]
        self.yellows: dict[str, int] = {}
        self.subs_done = [0, 0]
        self.sub_times = [sorted(self.r.uniform(55, 86) * 60 for _ in range(3)) for _ in range(2)]
        self.events: list[MatchEvent] = []
        self.truth: list[TruthRecord] = []
        self.seq = 0
        self.tactic_change = (self.r.randint(0, 1), self.r.uniform(55, 70) * 60, False)
        # recording
        self.rec_t: list[int] = []
        self.rec_period: list[int] = []
        self.rec_pos: list[np.ndarray] = []
        self.rec_speed: list[np.ndarray] = []
        self.rec_ball: list[np.ndarray] = []
        self.rec_roster: list[np.ndarray] = []
        self.roster = np.array([self.pid_index[p.player_id] for p in self.slot_player], dtype=np.int16)

    # ------------------------------------------------------------ helpers
    def _load_attrs(self) -> None:
        sp = self.slot_player
        self.pace = np.array([p.pace for p in sp], dtype=float)
        self.passing = np.array([p.passing for p in sp], dtype=float)
        self.shooting = np.array([p.shooting for p in sp], dtype=float)
        self.dribbling = np.array([p.dribbling for p in sp], dtype=float)
        self.defending = np.array([p.defending for p in sp], dtype=float)
        self.stamina = np.array([p.stamina for p in sp], dtype=float)
        self.max_speed = 6.9 + 2.7 * (self.pace / 99.0)

    def attacks_right(self, team: int) -> bool:
        return (team == 0) == (self.period == 1)

    def to_att(self, team: int, x, y):
        return (x, y) if self.attacks_right(team) else (LENGTH - x, WIDTH - y)

    def from_att(self, team: int, x, y):
        return self.to_att(team, x, y)  # the mirror is its own inverse

    def clock(self) -> str:
        if self.period == 1:
            m, s = divmod(int(self.t), 60)
            return f"{m}:{s:02d}" if m < 45 else f"45:00+{m - 44}"
        el = 45 * 60 + (self.t - self.p1_len)
        m, s = divmod(int(el), 60)
        return f"{m}:{s:02d}" if m < 90 else f"90:00+{m - 89}"

    def pid(self, slot: int | None) -> str | None:
        return None if slot is None else self.slot_player[slot].player_id

    def club_id(self, team: int) -> str:
        return self.clubs[team].club_id

    def emit(
        self,
        etype: EventType,
        team: int | None = None,
        slot: int | None = None,
        xy: tuple[float, float] | None = None,
        end: tuple[float, float] | None = None,
        **kw,
    ) -> str:
        self.seq += 1
        eid = f"EV-{self.seq:05d}"
        cx = lambda v: float(min(max(v, 0.0), LENGTH))  # noqa: E731
        cy = lambda v: float(min(max(v, 0.0), WIDTH))  # noqa: E731
        self.events.append(
            MatchEvent(
                match_id=self.match_id,
                event_id=eid,
                seq=self.seq,
                period=self.period,
                t_ms=int(self.t * 1000),
                clock=self.clock(),
                type=etype,
                team_id=None if team is None else self.club_id(team),
                player_id=self.pid(slot),
                x=None if xy is None else round(cx(xy[0]), 2),
                y=None if xy is None else round(cy(xy[1]), 2),
                end_x=None if end is None else round(cx(end[0]), 2),
                end_y=None if end is None else round(cy(end[1]), 2),
                attacking_right=None if team is None else self.attacks_right(team),
                **kw,
            )
        )
        return eid

    def opponents(self, team: int) -> np.ndarray:
        return np.where((self.team != team) & self.active)[0]

    def mates(self, team: int, exclude: int | None = None) -> np.ndarray:
        m = (self.team == team) & self.active
        if exclude is not None:
            m[exclude] = False
        return np.where(m)[0]

    # ------------------------------------------------------------ setup / restarts
    def kickoff_positions(self) -> None:
        for s in range(22):
            team = int(self.team[s])
            d, w = self.anchor[s]
            ax = 4.0 if self.slot_role[s] == "GK" else 12 + d * 36
            ay = 4 + w * (WIDTH - 8)
            self.pos[s] = self.from_att(team, ax, ay)
        self.vel[:] = 0

    def start_period(self, period: Literal[1, 2]) -> None:
        self.period = period
        kicking = 0 if period == 1 else 1
        self.kickoff_positions()
        self.emit(EventType.PERIOD_START)
        self.set_dead("kick_off", kicking, (LENGTH / 2, WIDTH / 2), wait=0.5)

    def set_dead(self, kind: str, team: int, xy: tuple[float, float], wait: float) -> None:
        self.flight = None
        self.carrier = None
        self.poss = team
        self.ball[:] = (xy[0], xy[1], 0.0)
        mates = self.mates(team)
        if kind == "goal_kick":
            taker = next((s for s in mates if self.slot_role[s] == "GK"), int(mates[0]))
        elif kind == "kick_off":
            dist = np.hypot(*(self.pos[mates] - np.array(xy)).T)
            taker = int(mates[np.argsort(dist)[0]])
            self.pos[taker] = xy
        else:
            dist = np.hypot(*(self.pos[mates] - np.array(xy)).T)
            outfield = [int(m) for m in mates[np.argsort(dist)] if self.slot_role[m] != "GK"]
            taker = outfield[0]
        self.dead = {"kind": kind, "team": team, "xy": xy, "until": self.t + wait, "taker": taker}

    def resume(self) -> None:
        d = self.dead
        assert d is not None
        kind, team, xy, taker = d["kind"], d["team"], d["xy"], d["taker"]
        self.pos[taker] = xy
        etype = {
            "kick_off": EventType.KICK_OFF,
            "throw_in": EventType.THROW_IN,
            "corner": EventType.CORNER,
            "goal_kick": EventType.GOAL_KICK,
            "free_kick": EventType.FREE_KICK,
        }[kind]
        self.emit(etype, team, taker, xy)
        self.dead = None
        self.give_ball(taker, decide_in=0.2)
        self.pending_set_piece = kind

    def give_ball(self, slot: int, decide_in: float | None = None) -> None:
        team = int(self.team[slot])
        if team != self.poss:
            self.poss = team
        self.carrier = slot
        self.flight = None
        self.pressured_by = set()
        self.carry_dest = None
        self.carry_start = (self.t, float(self.pos[slot][0]), float(self.pos[slot][1]))
        tempo = self.style[team]["tempo"]
        self.next_decision = self.t + (
            decide_in if decide_in is not None else max(0.7, self.r.gauss(2.8 - 0.9 * tempo, 0.5))
        )

    def change_possession(self, new_slot: int, cause_event: str) -> None:
        self.give_ball(new_slot)
        self.emit(
            EventType.POSSESSION_CHANGE,
            int(self.team[new_slot]),
            new_slot,
            (float(self.pos[new_slot][0]), float(self.pos[new_slot][1])),
            related_event_id=cause_event,
        )

    # ------------------------------------------------------------ tactics
    def targets(self) -> tuple[np.ndarray, np.ndarray]:
        """Target positions and urgency (0 = jog, 1 = sprint) for all slots."""
        tgt = np.zeros((22, 2))
        urg = np.zeros(22)
        for team in (0, 1):
            st = self.style[team]
            bx, by = self.to_att(team, float(self.ball[0]), float(self.ball[1]))
            if team == self.poss:
                back = np.clip(bx - 40 + 12 * st["defensive_line"], 10, 58)
                depth = 34 + 14 * st["directness"]
                width_m = 44 + 20 * st["width"]
                cy = 34 + (by - 34) * 0.25
            elif bx < 42:  # low block: protect the box, compact and narrow
                back = float(np.clip(bx - 20, 4.5, 16))
                depth = 17.0
                width_m = 30.0
                cy = 34 + (by - 34) * 0.35
            else:
                back = np.clip(bx - 30 + 16 * st["defensive_line"], 6, 52)
                depth = 28 - 7 * st["press_intensity"]
                width_m = 36 + 10 * (1 - st["press_intensity"])
                cy = 34 + (by - 34) * 0.55
            offside_x = LENGTH
            if team == self.poss:
                # attackers stay onside: level with the second-last defender (or the ball, if further forward)
                opp = self.opponents(team)
                ox_att, _ = self.to_att(team, self.pos[opp][:, 0], self.pos[opp][:, 1])
                second_last = float(np.sort(ox_att)[-2]) if len(opp) >= 2 else LENGTH
                offside_x = max(second_last, bx, 52.5) - 0.6
            for s in np.where(self.team == team)[0]:
                d, w = self.anchor[s]
                wander = 1.4 * math.sin(self.t * 0.35 + self.phase_offset[s])
                if self.slot_role[s] == "GK":
                    ax = float(np.clip(back - (22 if team == self.poss else 14), 2.5, 24))
                    ay = 34 + (by - 34) * 0.18
                else:
                    ax = float(np.clip(min(back + d * depth + wander, offside_x), 3, LENGTH - 3))
                    ay = float(np.clip(cy + (w - 0.5) * width_m + wander * 0.6, 2, WIDTH - 2))
                tgt[s] = self.from_att(team, ax, ay)
        # defending pressure: nearest defenders hunt the ball
        if self.carrier is not None and self.dead is None:
            dteam = 1 - self.poss
            press = self.style[dteam]["press_intensity"]
            defs = self.opponents(self.poss)
            defs = defs[[self.slot_role[s] != "GK" for s in defs]]
            dist = np.hypot(*(self.pos[defs] - self.pos[self.carrier]).T)
            order = defs[np.argsort(dist)]
            bx_def, _ = self.to_att(dteam, float(self.ball[0]), float(self.ball[1]))
            n_press = (
                1 + (1 if press > 0.55 else 0) + (1 if press > 0.75 and bx_def > 52.5 else 0)
            )  # high press hunts in their half
            for k, s in enumerate(order[:n_press]):
                if np.hypot(*(self.pos[s] - self.pos[self.carrier])) < 22 + 10 * press:
                    lead = self.vel[self.carrier] * (0.5 + 0.3 * k)
                    tgt[s] = self.pos[self.carrier] + lead
                    urg[s] = 0.7 + 0.3 * press
        if self.carrier is not None and self.carry_dest is not None:
            tgt[self.carrier] = self.carry_dest
            urg[self.carrier] = 0.75
        if self.flight is not None and self.flight.target_slot is not None:
            tgt[self.flight.target_slot] = (self.flight.ex, self.flight.ey)
            urg[self.flight.target_slot] = 1.0
        if self.dead is not None:
            tgt[self.dead["taker"]] = self.dead["xy"]
            urg[self.dead["taker"]] = 0.6
        return tgt, urg

    def move(self, tgt: np.ndarray, urg: np.ndarray) -> None:
        frac = self.t / (self.p1_len + self.p2_len)
        fatigue = 1 - 0.10 * frac * (1.4 - self.stamina / 100)
        delta = tgt - self.pos
        dist = np.hypot(delta[:, 0], delta[:, 1])
        cruise = np.where(urg > 0, self.max_speed * (0.55 + 0.45 * urg), np.minimum(4.6, 0.75 * dist + 0.4))
        want = np.minimum(cruise * fatigue, dist / DT)
        unit = np.divide(delta, dist[:, None], out=np.zeros_like(delta), where=dist[:, None] > 1e-6)
        desired = unit * want[:, None]
        dv = desired - self.vel
        dvn = np.hypot(dv[:, 0], dv[:, 1])
        cap = 4.2 * DT
        scale = np.where(dvn > cap, cap / np.maximum(dvn, 1e-9), 1.0)
        self.vel += dv * scale[:, None]
        self.vel[~self.active] = 0
        self.pos += self.vel * DT
        self.pos[:, 0] = np.clip(self.pos[:, 0], -2, LENGTH + 2)
        self.pos[:, 1] = np.clip(self.pos[:, 1], -2, WIDTH + 2)

    # ------------------------------------------------------------ decisions
    def decide(self) -> None:
        c = self.carrier
        assert c is not None
        team = self.poss
        st = self.style[team]
        x, y = self.to_att(team, float(self.pos[c][0]), float(self.pos[c][1]))
        opp = self.opponents(team)
        ox, oy = self.to_att(team, self.pos[opp][:, 0], self.pos[opp][:, 1])
        near = float(np.min(np.hypot(ox - x, oy - y))) if len(opp) else 99.0
        set_piece = self.pending_set_piece
        self.pending_set_piece = None
        # shooting
        if x > 76 and set_piece not in ("throw_in", "goal_kick", "kick_off", "corner"):
            xg = expected_goals(x, y, under_pressure=near < 2.5)
            # elite players shoot from range: about 4 in 10 shots come from outside the box
            outside = x < 105 - 16.5 or abs(y - 34) > 20.16
            base = 0.075 if outside else 0.03  # top-flight teams take ~4 in 10 shots from distance
            p_shoot = min(0.5, max(0.0, base + (xg - 0.02) * 1.0)) * (0.7 + 0.6 * self.shooting[c] / 99)
            if self.r.random() < p_shoot:
                self.shoot(c, x, y, xg, near < 2.5)
                return
        # candidate passes
        mates = self.mates(team, exclude=c)
        mx, my = self.to_att(team, self.pos[mates][:, 0], self.pos[mates][:, 1])
        best: tuple[float, int, float] | None = None
        here_val = float(zone_value(x, y))
        for i, m in enumerate(mates):
            d = math.hypot(mx[i] - x, my[i] - y)
            if d < 4 or d > (62 if st["directness"] > 0.6 else 48):
                continue
            if self.slot_role[m] == "GK" and x > 40:
                continue
            lane = (
                float(np.min(point_segment_distance(ox, oy, x, y, float(mx[i]), float(my[i]))))
                if len(opp)
                else 9
            )
            recv = float(np.min(np.hypot(ox - mx[i], oy - my[i]))) if len(opp) else 9
            fwd = max(0.0, (mx[i] - x) / 20)
            z = (
                3.0
                - 0.055 * d
                + 0.030 * (self.passing[c] - 70)
                - 2.4 * math.exp(-lane / 1.3)
                - 1.0 * math.exp(-recv / 2.6)
                - 0.30 * fwd
            )
            p = 1 / (1 + math.exp(-z))
            gain = float(zone_value(mx[i], my[i])) - here_val
            score = p * (0.10 + gain * (1.6 + 2.4 * st["risk"])) - (1 - p) * (0.12 + here_val * 0.4)
            score += self.r.gauss(0, 0.018)
            if best is None or score > best[0]:
                best = (score, int(m), p)
        # carry option
        ahead = (ox > x) & (ox < x + 9) & (np.abs(oy - y) < 5)
        space = 9.0 if not ahead.any() else float(np.min(ox[ahead] - x))
        carry_score = -1.0
        if set_piece is None and space > (8.5 if x > 78 else 4.5) and x < 88:
            carry_score = 0.03 + 0.03 * self.dribbling[c] / 99 + 0.004 * space + self.r.gauss(0, 0.015)
        if best is not None and best[0] >= carry_score:
            self.pass_to(c, best[1], best[2], set_piece)
        elif carry_score > -1:
            dx = self.r.uniform(6, 13)
            dy = (34 - y) * 0.15 + self.r.gauss(0, 3)
            self.carry_dest = self.from_att(team, min(x + dx, 88.0), float(np.clip(y + dy, 3, WIDTH - 3)))
            self.next_decision = self.t + self.r.uniform(0.9, 1.8)
        elif best is not None:
            self.pass_to(c, best[1], best[2], set_piece)
        else:
            self.next_decision = self.t + 0.5

    def pass_to(self, c: int, m: int, p: float, set_piece: str | None) -> None:
        team = self.poss
        sx, sy = float(self.pos[c][0]), float(self.pos[c][1])
        d = float(np.hypot(*(self.pos[m] - self.pos[c])))
        speed = float(np.clip(8 + 0.42 * d, 11, 27))
        dur = d / speed
        ex, ey = (self.pos[m] + self.vel[m] * dur * 0.55).tolist()
        ex, ey = float(np.clip(ex, 0.5, LENGTH - 0.5)), float(np.clip(ey, 0.5, WIDTH - 0.5))
        success = self.r.random() < p
        under = bool(min(np.hypot(*(self.pos[self.opponents(team)] - self.pos[c]).T)) < 2.5)
        self.close_carry(c)
        target_slot: int | None = m
        kind = "pass"
        if not success:
            if self.r.random() < 0.74:
                opp = self.opponents(team)
                opp = opp[[self.slot_role[o] != "GK" for o in opp]]
                lane = point_segment_distance(self.pos[opp][:, 0], self.pos[opp][:, 1], sx, sy, ex, ey)
                cut = int(opp[int(np.argmin(lane))])
                # interception point: projection of the interceptor onto the pass line, a little short of it
                ab = np.array([ex - sx, ey - sy])
                tproj = float(
                    np.clip(np.dot(self.pos[cut] - (sx, sy), ab) / max(np.dot(ab, ab), 1e-6), 0.15, 0.95)
                )
                ex, ey = sx + ab[0] * tproj, sy + ab[1] * tproj
                target_slot = cut
            else:
                kind = "out"
                ax, ay = self.to_att(team, ex, ey)
                ay = -1.0 if ay < 34 else WIDTH + 1.0
                ax = min(ax + self.r.uniform(2, 10), LENGTH + 1)
                ex, ey = self.from_att(team, ax, ay)
                target_slot = None
        peak = 0.0 if d < 28 else min(9.0, 0.12 * d)
        eid = self.emit(
            EventType.PASS,
            team,
            c,
            (sx, sy),
            (ex, ey),
            outcome=Outcome.SUCCESS if success else Outcome.FAIL,
            recipient_id=self.pid(m),
            under_pressure=under,
            ball_speed_kmh=round(speed * 3.6, 1),
            detail=set_piece,
        )
        self.carrier = None
        self.flight = _Flight(
            kind, sx, sy, ex, ey, self.t, max(dur, 0.25), peak, team, success, target_slot, eid
        )

    def shoot(self, c: int, x: float, y: float, xg: float, under: bool) -> None:
        team = self.poss
        sx, sy = float(self.pos[c][0]), float(self.pos[c][1])
        gy = 34 + self.r.uniform(-3.4, 3.4)
        tx, ty = self.from_att(team, LENGTH, gy)
        # The true scoring probability is the xG of the chance, adjusted for the finisher.
        # The goal is decided first; only misses are then shared between blocks, saves and
        # off-target, so goals track xG in every zone of the pitch (as xG is defined).
        p_goal = min(
            0.95, xg * (1.0 + 0.008 * (self.shooting[c] - 62))
        )  # centred on the league-average finisher
        is_goal = self.r.random() < p_goal
        opp = self.opponents(team)
        lane = point_segment_distance(self.pos[opp][:, 0], self.pos[opp][:, 1], sx, sy, tx, ty)
        blockers = [
            int(o)
            for o, d_ in zip(opp, lane, strict=True)
            if d_ < 1.4 and self.slot_role[o] != "GK" and np.hypot(*(self.pos[o] - (sx, sy))) < 12
        ]
        speed = self.r.uniform(19, 31)
        self.close_carry(c)
        self.truth.append(
            TruthRecord(
                match_id=self.match_id,
                t_ms=int(self.t * 1000),
                kind="shot_probability",
                team_id=self.club_id(team),
                player_id=self.pid(c),
                detail={"p_goal": round(p_goal, 4), "model_xg": round(xg, 4)},
            )
        )
        foot = BodyPart.LEFT_FOOT if self.slot_player[c].foot.value == "left" else BodyPart.RIGHT_FOOT
        if not is_goal and blockers and self.r.random() < 0.55:
            b = blockers[0]
            bx_, by_ = float(self.pos[b][0]), float(self.pos[b][1])
            eid = self.emit(
                EventType.SHOT,
                team,
                c,
                (sx, sy),
                (bx_, by_),
                outcome=Outcome.FAIL,
                under_pressure=under,
                ball_speed_kmh=round(speed * 3.6, 1),
                body_part=foot,
            )
            self.carrier = None
            self.flight = _Flight(
                "shot", sx, sy, bx_, by_, self.t, 0.25, 0.0, team, False, b, eid, xg, c, "block"
            )
            return
        result = "goal" if is_goal else ("save" if self.r.random() < 0.42 else "off")
        if result == "off":
            ty = ty + (self.r.choice([-1, 1]) * self.r.uniform(4.2, 9))
        dur = math.hypot(tx - sx, ty - sy) / speed
        gk = next((s for s in self.opponents(team) if self.slot_role[s] == "GK"), None)
        eid = self.emit(
            EventType.SHOT,
            team,
            c,
            (sx, sy),
            (tx, float(np.clip(ty, 0, WIDTH))),
            outcome=Outcome.SUCCESS if result == "goal" else Outcome.FAIL,
            under_pressure=under,
            ball_speed_kmh=round(speed * 3.6, 1),
            body_part=foot,
        )
        self.carrier = None
        self.flight = _Flight(
            "shot",
            sx,
            sy,
            tx,
            float(np.clip(ty, -2, WIDTH + 2)),
            self.t,
            max(dur, 0.2),
            self.r.uniform(0.2, 2.2),
            team,
            result == "goal",
            gk if result == "save" else None,
            eid,
            xg,
            c,
            result,
        )

    def close_carry(self, c: int) -> None:
        if self.carry_start is None:
            return
        _t0, x0, y0 = self.carry_start
        x1, y1 = float(self.pos[c][0]), float(self.pos[c][1])
        if math.hypot(x1 - x0, y1 - y0) >= 5:
            self.emit(EventType.CARRY, int(self.team[c]), c, (x0, y0), (x1, y1))
        self.carry_start = None

    # ------------------------------------------------------------ resolution
    def land(self) -> None:
        f = self.flight
        assert f is not None
        team = f.team
        if f.kind == "out":
            ax, ay = self.to_att(team, f.ex, f.ey)
            if ax >= LENGTH:
                self.set_dead(
                    "goal_kick", 1 - team, self.from_att(1 - team, 5.5, 34 + self.r.choice([-9, 9])), 18
                )
            else:
                self.set_dead(
                    "throw_in",
                    1 - team,
                    (float(np.clip(f.ex, 1, LENGTH - 1)), 0.0 if f.ey < 34 else WIDTH),
                    13,
                )
            return
        if f.kind == "pass":
            assert f.target_slot is not None
            if f.success:
                self.give_ball(f.target_slot)
            else:
                eid = self.emit(
                    EventType.INTERCEPTION,
                    1 - team,
                    f.target_slot,
                    (f.ex, f.ey),
                    outcome=Outcome.SUCCESS,
                    related_event_id=f.event_id,
                )
                self.change_possession(f.target_slot, eid)
            return
        # shots
        if f.result == "goal":
            self.score[team] += 1
            self.emit(
                EventType.GOAL,
                team,
                f.shooter_slot,
                (f.sx, f.sy),
                related_event_id=f.event_id,
                detail=f"{self.score[0]}-{self.score[1]}",
            )
            self.kickoff_positions()
            self.set_dead("kick_off", 1 - team, (LENGTH / 2, WIDTH / 2), wait=55)
        elif f.result == "block":
            assert f.target_slot is not None
            eid = self.emit(
                EventType.BLOCK, 1 - team, f.target_slot, (f.ex, f.ey), related_event_id=f.event_id
            )
            if self.r.random() < 0.55:
                self.change_possession(f.target_slot, eid)
            else:
                _, ay = self.to_att(team, f.ex, f.ey)
                self.set_dead(
                    "corner", team, self.from_att(team, LENGTH - 0.5, 0.5 if ay < 34 else WIDTH - 0.5), 22
                )
        elif f.result == "save":
            gk = f.target_slot
            assert gk is not None
            eid = self.emit(
                EventType.SAVE,
                1 - team,
                gk,
                (f.ex, float(np.clip(f.ey, 0, WIDTH))),
                related_event_id=f.event_id,
            )
            if self.r.random() < 0.55:
                self.change_possession(gk, eid)
            else:
                self.set_dead(
                    "corner", team, self.from_att(team, LENGTH - 0.5, self.r.choice([0.5, WIDTH - 0.5])), 22
                )
        else:
            self.set_dead(
                "goal_kick", 1 - team, self.from_att(1 - team, 5.5, 34 + self.r.choice([-9, 9])), 18
            )

    def duel(self) -> None:
        c = self.carrier
        if c is None or self.dead is not None:
            return
        opp = self.opponents(self.poss)
        dist = np.hypot(*(self.pos[opp] - self.pos[c]).T)
        for o_raw, d in zip(opp, dist, strict=True):
            o = int(o_raw)
            if (
                d < 2.6
                and o not in self.pressured_by
                and len(self.pressured_by) < 2
                and self.slot_role[o] != "GK"
            ):
                self.pressured_by.add(o)
                self.emit(
                    EventType.PRESSURE, 1 - self.poss, o, (float(self.pos[o][0]), float(self.pos[o][1]))
                )
        if self.t < self.tackle_cooldown:
            return
        k = int(np.argmin(dist))
        o, d = int(opp[k]), float(dist[k])
        if d > 1.35 or self.slot_role[o] == "GK":
            return
        press = self.style[1 - self.poss]["press_intensity"]
        cx_att, _ = self.to_att(self.poss, float(self.pos[c][0]), float(self.pos[c][1]))
        hazard = 0.05 * (0.6 + press) * (1.3 if cx_att > 75 else 1.0)
        if self.r.random() > hazard:
            return
        self.tackle_cooldown = self.t + 1.2
        xy = (float(self.pos[c][0]), float(self.pos[c][1]))
        r = self.r.random()
        p_win = 0.48 + 0.004 * (self.defending[o] - self.dribbling[c])
        if r < 0.13:
            self.foul(o, c, xy)
        elif r < 0.13 + p_win * 0.87:
            self.close_carry(c)
            eid = self.emit(
                EventType.TACKLE, 1 - self.poss, o, xy, outcome=Outcome.SUCCESS, recipient_id=self.pid(c)
            )
            self.change_possession(o, eid)
        else:
            self.emit(EventType.TACKLE, 1 - self.poss, o, xy, outcome=Outcome.FAIL, recipient_id=self.pid(c))
            self.next_decision = min(self.next_decision, self.t + 0.3)

    def foul(self, offender: int, victim: int, xy: tuple[float, float]) -> None:
        team = int(self.team[offender])
        self.close_carry(victim)
        self.emit(EventType.FOUL, team, offender, xy, recipient_id=self.pid(victim))
        if self.r.random() < 0.17:
            pid = self.slot_player[offender].player_id
            self.yellows[pid] = self.yellows.get(pid, 0) + 1
            second = self.yellows[pid] >= 2
            self.emit(EventType.CARD, team, offender, xy, detail="red" if second else "yellow")
            if second:
                self.send_off(offender)
        self.set_dead("free_kick", 1 - team, xy, 22)

    def send_off(self, slot: int) -> None:
        self.active[slot] = False
        self.pos[slot] = (LENGTH / 2, -3.0)
        self.roster[slot] = -1

    def maybe_substitute(self) -> None:
        if self.period != 2:
            return
        for team in (0, 1):
            if (
                self.subs_done[team] >= 3
                or self.t - self.p1_len + 45 * 60 < self.sub_times[team][self.subs_done[team]]
            ):
                continue
            if self.carrier is not None and int(self.team[self.carrier]) == team and self.dead is None:
                continue
            mates = [s for s in self.mates(team) if self.slot_role[s] != "GK" and s != self.carrier]
            if not mates or not self.bench[team]:
                continue
            off = min(mates, key=lambda s: self.stamina[s] + self.r.uniform(0, 15))
            role_fit = ROLE_FIT[self.slot_role[off]]
            on = next((p for pos in role_fit for p in self.bench[team] if p.position == pos), None)
            if on is None:
                on = next((p for p in self.bench[team] if p.position != Position.GK), None)
            if on is None:
                continue
            self.bench[team].remove(on)
            self.emit(EventType.SUBSTITUTION, team, off, None, recipient_id=on.player_id, detail="sub")
            self.slot_player[off] = on
            self.roster[off] = self.pid_index[on.player_id]
            self.pos[off] = (LENGTH / 2, -0.5 if team == 0 else WIDTH + 0.5)
            self._load_attrs()
            self.subs_done[team] += 1

    def maybe_change_tactics(self) -> None:
        team, when, done = self.tactic_change
        if done or self.period != 2 or (self.t - self.p1_len + 45 * 60) < when:
            return
        st = self.style[team]
        st["press_intensity"] = min(1.0, st["press_intensity"] + 0.35)
        st["defensive_line"] = min(1.0, st["defensive_line"] + 0.35)
        st["tempo"] = min(1.0, st["tempo"] + 0.15)
        self.truth.append(
            TruthRecord(
                match_id=self.match_id,
                t_ms=int(self.t * 1000),
                kind="tactic_change",
                team_id=self.club_id(team),
                detail={
                    "change": "high_press",
                    "press_intensity": round(st["press_intensity"], 2),
                    "defensive_line": round(st["defensive_line"], 2),
                },
            )
        )
        self.tactic_change = (team, when, True)

    # ------------------------------------------------------------ main loop
    def step_ball(self) -> None:
        f = self.flight
        if f is not None:
            u = min(1.0, (self.t - f.t0) / f.dur)
            self.ball[0] = f.sx + (f.ex - f.sx) * u
            self.ball[1] = f.sy + (f.ey - f.sy) * u
            self.ball[2] = 4 * f.peak * u * (1 - u)
            if u >= 1.0:
                self.land()
        elif self.carrier is not None:
            c = self.carrier
            v = self.vel[c]
            n = float(np.hypot(*v))
            off = v / n * 0.55 if n > 0.3 else np.zeros(2)
            self.ball[:2] = self.pos[c] + off
            self.ball[2] = 0.0

    def record(self) -> None:
        self.rec_t.append(round(self.t * 1000))
        self.rec_period.append(self.period)
        self.rec_pos.append(self.pos.astype(np.float32).copy())
        self.rec_speed.append(np.hypot(self.vel[:, 0], self.vel[:, 1]).astype(np.float32))
        self.rec_ball.append(self.ball.astype(np.float32).copy())
        self.rec_roster.append(self.roster.copy())

    def run_period(self, period: Literal[1, 2], end_t: float) -> None:
        self.start_period(period)
        while self.t < end_t or self.flight is not None:
            if self.dead is not None and self.t >= self.dead["until"]:
                self.resume()
            if self.carrier is not None and self.dead is None and self.flight is None:
                if self.t >= self.next_decision:
                    self.decide()
                else:
                    self.duel()
            self.maybe_substitute()
            self.maybe_change_tactics()
            tgt, urg = self.targets()
            self.move(tgt, urg)
            self.step_ball()
            self.record()
            self.t = round(self.t + DT, 3)
            if self.t > end_t + 20:  # safety: never run on forever
                break
        if self.carrier is not None:
            self.close_carry(self.carrier)
        self.emit(EventType.PERIOD_END)

    def run(self) -> MatchResult:
        self.run_period(1, self.p1_len)
        self.p1_len = self.t
        self.run_period(2, self.p1_len + self.p2_len)
        return MatchResult(
            meta=self.meta,
            events=self.events,
            truth=self.truth,
            t_ms=np.array(self.rec_t, dtype=np.int64),
            period=np.array(self.rec_period, dtype=np.int8),
            pos=np.stack(self.rec_pos),
            speed=np.stack(self.rec_speed),
            ball=np.stack(self.rec_ball),
            roster=np.stack(self.rec_roster),
            player_ids=self.player_ids,
            score=(self.score[0], self.score[1]),
            team_of_slot=[self.club_id(int(t)) for t in self.team],
        )


def simulate_match(
    league: League, home_id: str, away_id: str, seed: int, matchday: int = 1, half_minutes: float = 45.0
) -> MatchResult:
    """Play one match. Same inputs, same match, every time.

    ``half_minutes`` shortens both halves for fast tests; production always uses 45.
    """
    return _Engine(league, home_id, away_id, seed, matchday, half_minutes).run()
