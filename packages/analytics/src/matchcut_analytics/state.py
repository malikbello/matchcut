"""Live match state: every number an agent or a graphic may show, computed by code.

Definitions follow common analytics practice:
- possession share: share of pass attempts (the usual broadcast method);
- PPDA (passes allowed per defensive action): opponent passes in *their own*
  defensive 60% of the pitch divided by our tackles, interceptions and fouls in
  that same zone. Lower = more intense pressing;
- field tilt: our share of all passes played in the final third;
- xT added: sum of expected-threat gained by successful passes and carries;
- momentum: exponentially weighted (half-life 2 min) difference in threat
  created (xT added + xG), squashed to -1..1, positive = home on top;
- control vs chaos: 0 = settled possession, 1 = end-to-end chaos; from the
  rolling 10-minute turnover rate and pass completion.
- sprints: runs at or above 25.2 km/h (7 m/s) lasting at least one second.
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field
from typing import Any

from matchcut_contracts import EventType, MatchEvent, MatchMeta, Outcome

from matchcut_analytics.geometry import expected_goals, in_final_third, to_attacking
from matchcut_analytics.xt import XTModel

SPRINT_MPS = 7.0
MOMENTUM_HALF_LIFE_S = 120.0
PPDA_ZONE_X = 63.0  # a team's own defensive 60% in its attacking frame


@dataclass
class PlayerStats:
    player_id: str
    team_id: str
    passes: int = 0
    passes_completed: int = 0
    shots: int = 0
    xg: float = 0.0
    goals: int = 0
    xt_added: float = 0.0
    tackles_won: int = 0
    interceptions: int = 0
    pressures: int = 0
    distance_m: float = 0.0
    sprints: int = 0
    top_speed_mps: float = 0.0
    _sprint_run: float = 0.0


@dataclass
class TeamStats:
    team_id: str
    goals: int = 0
    shots: int = 0
    shots_on_target: int = 0
    xg: float = 0.0
    passes: int = 0
    passes_completed: int = 0
    final_third_passes: int = 0
    xt_added: float = 0.0
    opp_passes_in_zone: int = 0  # opponent passes in their own defensive 60% (our pressing zone)
    def_actions_in_zone: int = 0
    fouls: int = 0
    yellows: int = 0
    reds: int = 0
    corners: int = 0

    @property
    def ppda(self) -> float | None:
        return None if self.def_actions_in_zone == 0 else self.opp_passes_in_zone / self.def_actions_in_zone


@dataclass
class MatchState:
    meta: MatchMeta
    xt: XTModel
    t_ms: int = 0
    teams: dict[str, TeamStats] = field(default_factory=dict)
    players: dict[str, PlayerStats] = field(default_factory=dict)
    momentum_raw: float = 0.0
    _last_t: float = 0.0
    _recent: deque = field(default_factory=deque)  # (t_s, kind) for the 10-minute window
    _scored: set[str] = field(default_factory=set)

    def __post_init__(self) -> None:
        for tid in (self.meta.home_club_id, self.meta.away_club_id):
            self.teams[tid] = TeamStats(tid)

    # ------------------------------------------------------------ helpers
    def other(self, team_id: str) -> str:
        return self.meta.away_club_id if team_id == self.meta.home_club_id else self.meta.home_club_id

    def player(self, pid: str, tid: str) -> PlayerStats:
        if pid not in self.players:
            self.players[pid] = PlayerStats(pid, tid)
        return self.players[pid]

    def _decay_to(self, t_s: float) -> None:
        dt = max(0.0, t_s - self._last_t)
        self.momentum_raw *= 0.5 ** (dt / MOMENTUM_HALF_LIFE_S)
        self._last_t = t_s
        while self._recent and self._recent[0][0] < t_s - 600:
            self._recent.popleft()

    def _threat(self, team_id: str, amount: float) -> None:
        self.momentum_raw += amount if team_id == self.meta.home_club_id else -amount

    # ------------------------------------------------------------ public
    @property
    def score(self) -> tuple[int, int]:
        return self.teams[self.meta.home_club_id].goals, self.teams[self.meta.away_club_id].goals

    @property
    def momentum(self) -> float:
        """-1..1, positive when the home side is on top."""
        return math.tanh(self.momentum_raw / 0.35)

    @property
    def chaos(self) -> float:
        """0 settled .. 1 chaotic, from the last 10 minutes."""
        if not self._recent:
            return 0.0
        span_min = max(1.0, min(10.0, (self._last_t - self._recent[0][0]) / 60))
        turnovers = sum(1 for _, k in self._recent if k == "turnover") / span_min
        passes = [k for _, k in self._recent if k in ("pass_ok", "pass_fail")]
        completion = (passes.count("pass_ok") / len(passes)) if passes else 0.8
        return max(0.0, min(1.0, 0.5 * (turnovers - 3.0) / 4.0 + 0.5 * (0.88 - completion) / 0.2 + 0.25))

    def possession(self, team_id: str) -> float:
        total = sum(t.passes for t in self.teams.values())
        return 0.5 if total == 0 else self.teams[team_id].passes / total

    def field_tilt(self, team_id: str) -> float:
        total = sum(t.final_third_passes for t in self.teams.values())
        return 0.5 if total == 0 else self.teams[team_id].final_third_passes / total

    def apply(self, e: MatchEvent) -> None:
        self.t_ms = e.t_ms
        self._decay_to(e.t_ms / 1000)
        tid = e.team_id
        if tid is None or tid not in self.teams:
            return
        team = self.teams[tid]
        opp = self.teams[self.other(tid)]
        p = self.player(e.player_id, tid) if e.player_id else None
        if e.x is not None and e.y is not None:
            x, y = to_attacking(e.x, e.y, e.attacking_right)
        else:
            x = y = None
        if e.type == EventType.PASS:
            team.passes += 1
            ok = e.outcome == Outcome.SUCCESS
            team.passes_completed += ok
            if p:
                p.passes += 1
                p.passes_completed += ok
            self._recent.append((e.t_ms / 1000, "pass_ok" if ok else "pass_fail"))
            if x is not None and in_final_third(x):
                team.final_third_passes += 1
            if x is not None and x <= PPDA_ZONE_X:
                opp.opp_passes_in_zone += 1
            if ok and x is not None and e.end_x is not None and e.end_y is not None:
                ex, ey = to_attacking(e.end_x, e.end_y, e.attacking_right)
                gain = self.xt.added(x, y, ex, ey)  # type: ignore[arg-type]
                team.xt_added += gain
                if p:
                    p.xt_added += gain
                self._threat(tid, max(gain, 0.0))
        elif e.type == EventType.CARRY and x is not None and e.end_x is not None and e.end_y is not None:
            ex, ey = to_attacking(e.end_x, e.end_y, e.attacking_right)
            gain = self.xt.added(x, y, ex, ey)  # type: ignore[arg-type]
            team.xt_added += gain
            if p:
                p.xt_added += gain
            self._threat(tid, max(gain, 0.0))
        elif e.type == EventType.SHOT and x is not None:
            xg = expected_goals(x, y, under_pressure=bool(e.under_pressure))  # type: ignore[arg-type]
            team.shots += 1
            team.xg += xg
            if p:
                p.shots += 1
                p.xg += xg
            self._threat(tid, xg)
        elif e.type == EventType.SAVE:
            opp.shots_on_target += 1
        elif e.type == EventType.GOAL:
            team.goals += 1
            team.shots_on_target += 1
            if p:
                p.goals += 1
        elif e.type in (EventType.TACKLE, EventType.INTERCEPTION, EventType.FOUL):
            if e.type == EventType.FOUL:
                team.fouls += 1
            if e.type == EventType.TACKLE and e.outcome == Outcome.SUCCESS and p:
                p.tackles_won += 1
            if e.type == EventType.INTERCEPTION and p:
                p.interceptions += 1
            # our action at x (our frame) sits in the opponent's own 60% when x >= 105 - 63
            if x is not None and x >= 105 - PPDA_ZONE_X:
                team.def_actions_in_zone += 1
        elif e.type == EventType.PRESSURE and p:
            p.pressures += 1
        elif e.type == EventType.POSSESSION_CHANGE:
            self._recent.append((e.t_ms / 1000, "turnover"))
        elif e.type == EventType.CARD:
            if e.detail == "red":
                team.reds += 1
            else:
                team.yellows += 1
        elif e.type == EventType.CORNER:
            team.corners += 1

    def apply_tracking(
        self,
        t_ms: int,
        player_ids: list[str | None],
        team_ids: list[str],
        speeds_mps: list[float],
        dt_s: float = 0.1,
    ) -> list[tuple[str, float]]:
        """Update physical stats from one tracking frame. Returns new match top speeds (player, m/s)."""
        peaks = []
        for pid, tid, v in zip(player_ids, team_ids, speeds_mps, strict=True):
            if pid is None:
                continue
            ps = self.player(pid, tid)
            ps.distance_m += v * dt_s
            if v >= SPRINT_MPS:
                ps._sprint_run += dt_s
                if abs(ps._sprint_run - 1.0) < dt_s / 2:
                    ps.sprints += 1
            else:
                ps._sprint_run = 0.0
            if v > ps.top_speed_mps + 0.05:
                ps.top_speed_mps = v
                peaks.append((pid, v))
        self.t_ms = max(self.t_ms, t_ms)
        return peaks

    def snapshot(self) -> dict[str, Any]:
        """Flat, rounded numbers for agents and graphics (cite as given)."""
        home, away = self.meta.home_club_id, self.meta.away_club_id
        out: dict[str, Any] = {
            "t_ms": self.t_ms,
            "score": f"{self.score[0]}-{self.score[1]}",
            "momentum": round(self.momentum, 2),
            "chaos": round(self.chaos, 2),
        }
        for tid in (home, away):
            t = self.teams[tid]
            out[tid] = {
                "goals": t.goals,
                "shots": t.shots,
                "on_target": t.shots_on_target,
                "xg": round(t.xg, 2),
                "possession": round(self.possession(tid), 3),
                "pass_completion": round(t.passes_completed / t.passes, 3) if t.passes else None,
                "field_tilt": round(self.field_tilt(tid), 3),
                "xt_added": round(t.xt_added, 3),
                "ppda": None if t.ppda is None else round(t.ppda, 1),
                "corners": t.corners,
                "fouls": t.fouls,
                "yellows": t.yellows,
                "reds": t.reds,
            }
        return out
