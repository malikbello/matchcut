"""Expected threat (xT), after Karun Singh (2019), "Introducing Expected Threat".

The pitch (attacking frame) is split into a 16 x 12 grid. From event data we
learn, per cell:
    s  = P(shoot | ball in cell)        m = P(move | ball in cell) = 1 - s
    g  = P(goal | shot from cell)       T = P(move ends in cell j | move from i, successful)
and solve  xT = s * g + m * (T @ xT)  by value iteration. The value of a pass or
carry is xT(end) - xT(start). Failed moves contribute to m but not to T, so
risky zones are naturally discounted. Goal probabilities are shrunk towards
the analytic xG model where a cell has few shots, which keeps sparse cells sane.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from matchcut_contracts import EventType, MatchEvent, Outcome

from matchcut_analytics.geometry import LENGTH, WIDTH, expected_goals, to_attacking

NX, NY = 16, 12
SHRINK = 8.0  # pseudo-shots of xG prior per cell
CELL_PRIOR_WEIGHT = 10.0  # pseudo-actions of analytic prior per cell
DEFAULT_GRID = Path(__file__).with_name("xt_grid.json")


def cell(x: float, y: float) -> int:
    i = min(NX - 1, max(0, int(x / LENGTH * NX)))
    j = min(NY - 1, max(0, int(y / WIDTH * NY)))
    return i * NY + j


def cell_centre(c: int) -> tuple[float, float]:
    i, j = divmod(c, NY)
    return (i + 0.5) * LENGTH / NX, (j + 0.5) * WIDTH / NY


@dataclass
class XTModel:
    grid: np.ndarray  # (NX * NY,)
    trained_on_events: int = 0

    def value(self, x: float, y: float) -> float:
        return float(self.grid[cell(x, y)])

    def added(self, sx: float, sy: float, ex: float, ey: float) -> float:
        return self.value(ex, ey) - self.value(sx, sy)

    def to_json(self) -> str:
        return json.dumps(
            {
                "nx": NX,
                "ny": NY,
                "trained_on_events": self.trained_on_events,
                "grid": [round(float(v), 6) for v in self.grid],
            },
            indent=1,
        )

    @classmethod
    def from_json(cls, text: str) -> XTModel:
        d = json.loads(text)
        if (d["nx"], d["ny"]) != (NX, NY):
            raise ValueError("xT grid shape mismatch")
        return cls(np.array(d["grid"], dtype=float), d.get("trained_on_events", 0))

    @classmethod
    def load_default(cls) -> XTModel:
        if DEFAULT_GRID.exists():
            return cls.from_json(DEFAULT_GRID.read_text(encoding="utf-8"))
        return cls(prior_grid())


def prior_grid() -> np.ndarray:
    """Analytic fallback: the probability of scoring with a shot from each cell."""
    return np.array([expected_goals(*cell_centre(c)) * 0.35 for c in range(NX * NY)])


def train(events: Iterable[MatchEvent], iterations: int = 40) -> XTModel:
    n = NX * NY
    shots = np.zeros(n)
    goals = np.zeros(n)
    moves = np.zeros(n)
    trans = np.zeros((n, n))
    scored: set[str] = set()
    evs = list(events)
    for e in evs:
        if e.type == EventType.GOAL and e.related_event_id:
            scored.add(e.related_event_id)
    used = 0
    for e in evs:
        if e.x is None or e.y is None:
            continue
        sx, sy = to_attacking(e.x, e.y, e.attacking_right)
        c = cell(sx, sy)
        if e.type == EventType.SHOT:
            shots[c] += 1
            goals[c] += e.event_id in scored
            used += 1
        elif e.type in (EventType.PASS, EventType.CARRY) and e.end_x is not None and e.end_y is not None:
            moves[c] += 1
            used += 1
            if e.type == EventType.CARRY or e.outcome == Outcome.SUCCESS:
                ex, ey = to_attacking(e.end_x, e.end_y, e.attacking_right)
                trans[c, cell(ex, ey)] += 1
    total = shots + moves
    with np.errstate(invalid="ignore", divide="ignore"):
        s = np.where(total > 0, shots / total, 0.0)
        m = 1.0 - s
        prior = np.array([expected_goals(*cell_centre(c)) for c in range(n)])
        g = (goals + SHRINK * prior) / (shots + SHRINK)
        row = np.where(moves > 0, moves, 1.0)[:, None]
        t = trans / row
    xt = np.zeros(n)
    for _ in range(iterations):
        xt = s * g + m * (t @ xt)
    # sparse cells (few observed actions) are blended towards the analytic prior in proportion
    # to how little data they have, so rarely visited zones never read as worthless
    xt = (total * xt + CELL_PRIOR_WEIGHT * prior_grid()) / (total + CELL_PRIOR_WEIGHT)
    return XTModel(xt, used)
