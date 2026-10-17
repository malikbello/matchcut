"""Moment detection: decide, in code, what is worth putting on screen.

Each moment carries the events that prove it and the numbers agents may cite.
Tactical shifts (a team switching to a high press) are found from the signal
that is reliably visible in event data: pressing actions in the opponent's
half. A shift is declared when the last 5 minutes contain at least double the
team's recent 5-minute average (previous 15 minutes) and at least 12 more
actions. Defensive-line height was evaluated and rejected as too sparse and
noisy per minute (see ADR-0008). Detections are scored against the simulator's hidden truth.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from matchcut_contracts import EventType, MatchEvent, Moment, MomentKind, Outcome, TruthRecord

from matchcut_analytics.geometry import expected_goals, to_attacking
from matchcut_analytics.state import MatchState

BIG_CHANCE_XG = 0.30
GREAT_SAVE_XG = 0.15
SPEED_PEAK_MPS = 9.45  # 34 km/h
MOMENTUM_SWING = 0.45
COOLDOWN_S = 300
TACTIC_COOLDOWN_S = 900
PRESS_RECENT_MIN = 5
PRESS_BASELINE_MIN = 15
PRESS_MIN_INCREASE = 12


def clock_of(e: MatchEvent) -> str:
    return e.clock


@dataclass
class MomentDetector:
    state: MatchState
    moments: list[Moment] = field(default_factory=list)
    _shots: dict[str, MatchEvent] = field(default_factory=dict)
    _last: dict[tuple[str, str | None], float] = field(default_factory=dict)
    _last_momentum_sign: int = 0
    _minute: int = -1
    _press_minutes: dict[str, dict[int, int]] = field(default_factory=dict)  # pressing actions per minute

    def __post_init__(self) -> None:
        for tid in self.state.teams:
            self._press_minutes[tid] = {}

    # ------------------------------------------------------------ helpers
    def _emit(
        self,
        e_t_ms: int,
        clock: str,
        kind: MomentKind,
        importance: float,
        team: str | None = None,
        player: str | None = None,
        evidence: list[str] | None = None,
        metrics: dict[str, float | int | str] | None = None,
    ) -> Moment:
        m = Moment(
            match_id=self.state.meta.match_id,
            moment_id=f"MO-{len(self.moments) + 1:05d}",
            t_ms=e_t_ms,
            clock=clock,
            kind=kind,
            team_id=team,
            player_id=player,
            importance=round(min(1.0, importance), 2),
            evidence_event_ids=evidence or [],
            metrics=metrics or {},
        )
        self.moments.append(m)
        return m

    def _cool(self, key: tuple[str, str | None], t_s: float, cooldown: float = COOLDOWN_S) -> bool:
        if t_s - self._last.get(key, -1e9) < cooldown:
            return False
        self._last[key] = t_s
        return True

    # ------------------------------------------------------------ events
    def on_event(self, e: MatchEvent) -> list[Moment]:
        before = len(self.moments)
        self.state.apply(e)
        t_s = e.t_ms / 1000
        if e.type == EventType.SHOT:
            self._shots[e.event_id] = e
        elif e.type == EventType.GOAL and e.related_event_id in self._shots:
            shot = self._shots[e.related_event_id]
            h, a = self.state.score
            late = 1.0 if t_s > 80 * 60 else 0.0
            margin = abs(h - a)
            importance = 0.75 + 0.15 * late + (0.1 if margin <= 1 else 0.0)
            self._emit(
                e.t_ms,
                e.clock,
                MomentKind.GOAL,
                importance,
                e.team_id,
                e.player_id,
                [shot.event_id, e.event_id],
                {"score": f"{h}-{a}", "xg": round(self._xg(shot), 2)},
            )
        elif e.type == EventType.SAVE and e.related_event_id in self._shots:
            shot = self._shots[e.related_event_id]
            xg = self._xg(shot)
            if xg >= GREAT_SAVE_XG:
                self._emit(
                    e.t_ms,
                    e.clock,
                    MomentKind.GREAT_SAVE,
                    0.45 + xg,
                    e.team_id,
                    e.player_id,
                    [shot.event_id, e.event_id],
                    {"xg_saved": round(xg, 2)},
                )
        elif e.type in (EventType.SHOT,):
            pass
        elif e.type == EventType.CARD:
            self._emit(
                e.t_ms,
                e.clock,
                MomentKind.CARD,
                0.6 if e.detail == "red" else 0.25,
                e.team_id,
                e.player_id,
                [e.event_id],
                {"card": e.detail or "yellow"},
            )
        elif e.type == EventType.SUBSTITUTION:
            self._emit(
                e.t_ms,
                e.clock,
                MomentKind.SUBSTITUTION,
                0.15,
                e.team_id,
                e.player_id,
                [e.event_id],
                {"on": e.recipient_id or ""},
            )
        if e.type == EventType.SHOT and e.outcome == Outcome.FAIL:
            xg = self._xg(e)
            if xg >= BIG_CHANCE_XG:
                self._emit(
                    e.t_ms,
                    e.clock,
                    MomentKind.BIG_CHANCE,
                    0.4 + xg,
                    e.team_id,
                    e.player_id,
                    [e.event_id],
                    {"xg": round(xg, 2)},
                )
        if (
            e.team_id
            and e.type in (EventType.TACKLE, EventType.INTERCEPTION, EventType.PRESSURE)
            and e.x is not None
        ):
            x, _ = to_attacking(e.x, e.y or 34, e.attacking_right)
            if x >= 52.5:
                mins = self._press_minutes[e.team_id]
                mins[int(t_s // 60)] = mins.get(int(t_s // 60), 0) + 1
        # momentum swing
        mom = self.state.momentum
        sign = 1 if mom > MOMENTUM_SWING else -1 if mom < -MOMENTUM_SWING else 0
        if sign and sign != self._last_momentum_sign and self._cool(("momentum", None), t_s):
            team = self.state.meta.home_club_id if sign > 0 else self.state.meta.away_club_id
            self._emit(
                e.t_ms,
                e.clock,
                MomentKind.MOMENTUM_SWING,
                0.35 + 0.3 * abs(mom),
                team,
                None,
                [e.event_id],
                {"momentum": round(mom, 2)},
            )
        if sign:
            self._last_momentum_sign = sign
        return self.moments[before:]

    def _xg(self, shot: MatchEvent) -> float:
        assert shot.x is not None
        x, y = to_attacking(shot.x, shot.y or 34, shot.attacking_right)
        return expected_goals(x, y, under_pressure=bool(shot.under_pressure))

    # ------------------------------------------------------------ tracking
    def on_tracking(
        self,
        t_ms: int,
        clock: str,
        player_ids: list[str | None],
        team_ids: list[str],
        xs: list[float],
        speeds: list[float],
        attacking_right: dict[str, bool],
        ball_x: float | None = None,
    ) -> list[Moment]:
        """Feed one 10 Hz frame. Line height is sampled; shift tests run once per match minute."""
        before = len(self.moments)
        self._ball_x = ball_x
        for pid, v in self.state.apply_tracking(t_ms, player_ids, team_ids, speeds):
            if v >= SPEED_PEAK_MPS and self._cool(("speed", pid), t_ms / 1000):
                self._emit(
                    t_ms,
                    clock,
                    MomentKind.SPEED_PEAK,
                    0.3,
                    self.state.players[pid].team_id,
                    pid,
                    [],
                    {"top_speed_kmh": round(v * 3.6, 1)},
                )
        minute = t_ms // 60000
        if minute != self._minute:
            self._minute = minute
            t_s = t_ms / 1000
            for tid in self.state.teams:
                if minute < PRESS_BASELINE_MIN + PRESS_RECENT_MIN:
                    continue
                mins = self._press_minutes[tid]
                recent = sum(mins.get(m, 0) for m in range(minute - PRESS_RECENT_MIN, minute))
                base_total = sum(
                    mins.get(m, 0)
                    for m in range(minute - PRESS_RECENT_MIN - PRESS_BASELINE_MIN, minute - PRESS_RECENT_MIN)
                )
                baseline = base_total / (PRESS_BASELINE_MIN / PRESS_RECENT_MIN)  # per 5-minute window
                if (
                    recent >= 2.0 * baseline
                    and recent - baseline >= PRESS_MIN_INCREASE
                    and self._cool(("tactic", tid), t_s, TACTIC_COOLDOWN_S)
                ):
                    self._emit(
                        t_ms,
                        clock,
                        MomentKind.TACTICAL_SHIFT,
                        0.6,
                        tid,
                        None,
                        [],
                        {
                            "signal": "pressing",
                            "high_press_actions_last_5_min": recent,
                            "average_per_5_min_before": round(baseline, 1),
                        },
                    )
        return self.moments[before:]


def score_tactical_detection(
    moments: list[Moment], truth: list[TruthRecord], window_s: int = 600
) -> dict[str, float]:
    """Precision and recall of tactical-shift moments against the hidden truth (team must match)."""
    shifts = [m for m in moments if m.kind == MomentKind.TACTICAL_SHIFT]
    changes = [t for t in truth if t.kind == "tactic_change"]
    hit_changes = {
        i
        for i, c in enumerate(changes)
        if any(m.team_id == c.team_id and 0 <= (m.t_ms - c.t_ms) / 1000 <= window_s for m in shifts)
    }
    true_pos = sum(
        1
        for m in shifts
        if any(m.team_id == c.team_id and 0 <= (m.t_ms - c.t_ms) / 1000 <= window_s for c in changes)
    )
    return {
        "detections": float(len(shifts)),
        "changes": float(len(changes)),
        "recall": len(hit_changes) / len(changes) if changes else 1.0,
        "precision": true_pos / len(shifts) if shifts else 1.0,
    }
