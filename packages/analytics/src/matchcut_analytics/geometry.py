"""Pitch geometry and expected goals, in the attacking frame (goal at x = 105, y = 34)."""

from __future__ import annotations

import math

LENGTH, WIDTH = 105.0, 68.0
GOAL_Y = WIDTH / 2
GOAL_HALF_WIDTH = 3.66
BOX_DEPTH = 16.5
BOX_HALF_WIDTH = 20.16


def to_attacking(x: float, y: float, attacking_right: bool | None) -> tuple[float, float]:
    """Convert a pitch-frame position into the acting team's attacking frame."""
    return (x, y) if attacking_right in (True, None) else (LENGTH - x, WIDTH - y)


def in_box(x: float, y: float) -> bool:
    return x >= LENGTH - BOX_DEPTH and abs(y - GOAL_Y) <= BOX_HALF_WIDTH


def in_final_third(x: float) -> bool:
    return x >= LENGTH * 2 / 3


def shot_angle(x: float, y: float) -> float:
    """Angle (radians) subtended by the goal mouth from (x, y)."""
    dx = max(LENGTH - x, 0.05)
    a = math.atan2(GOAL_Y + GOAL_HALF_WIDTH - y, dx)
    b = math.atan2(GOAL_Y - GOAL_HALF_WIDTH - y, dx)
    return abs(a - b)


def expected_goals(x: float, y: float, header: bool = False, under_pressure: bool = False) -> float:
    """Logistic xG from distance and goal-mouth angle, with header and pressure penalties.

    Calibrated to public open-play benchmarks: ~0.40 from 6 m central, ~0.15 from
    the penalty spot in open play, ~0.02-0.03 from 25 m central.
    """
    dist = math.hypot(LENGTH - x, GOAL_Y - y)
    z = -1.10 - 0.12 * dist + 1.30 * shot_angle(x, y)
    if header:
        z -= 0.9
    if under_pressure:
        z -= 0.3
    return 1.0 / (1.0 + math.exp(-z))
