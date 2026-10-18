"""Football models used by the engine's decision-making.

Expected goals and shot geometry come from ``matchcut_analytics`` (one source of truth).

All functions work in the *attacking frame*: the team in question attacks +x,
its target goal is centred at (105, 34).
"""

from __future__ import annotations

import numpy as np
from matchcut_analytics.geometry import expected_goals, shot_angle

LENGTH, WIDTH = 105.0, 68.0
GOAL_Y = WIDTH / 2
GOAL_HALF_WIDTH = 3.66

# Formation anchors in the attacking frame: (depth 0..1 within the team block, width 0..1).
FORMATIONS: dict[str, list[tuple[str, float, float]]] = {
    "4-3-3": [
        ("GK", 0.0, 0.5),
        ("FB", 0.30, 0.10),
        ("CB", 0.18, 0.36),
        ("CB", 0.18, 0.64),
        ("FB", 0.30, 0.90),
        ("DM", 0.40, 0.50),
        ("CM", 0.55, 0.30),
        ("CM", 0.55, 0.70),
        ("W", 0.82, 0.10),
        ("ST", 0.90, 0.50),
        ("W", 0.82, 0.90),
    ],
    "4-2-3-1": [
        ("GK", 0.0, 0.5),
        ("FB", 0.30, 0.10),
        ("CB", 0.18, 0.36),
        ("CB", 0.18, 0.64),
        ("FB", 0.30, 0.90),
        ("DM", 0.42, 0.38),
        ("DM", 0.42, 0.62),
        ("W", 0.72, 0.12),
        ("AM", 0.70, 0.50),
        ("W", 0.72, 0.88),
        ("ST", 0.92, 0.50),
    ],
    "4-4-2": [
        ("GK", 0.0, 0.5),
        ("FB", 0.28, 0.10),
        ("CB", 0.18, 0.36),
        ("CB", 0.18, 0.64),
        ("FB", 0.28, 0.90),
        ("W", 0.58, 0.10),
        ("CM", 0.50, 0.38),
        ("CM", 0.50, 0.62),
        ("W", 0.58, 0.90),
        ("ST", 0.88, 0.40),
        ("ST", 0.88, 0.60),
    ],
    "3-4-3": [
        ("GK", 0.0, 0.5),
        ("CB", 0.18, 0.25),
        ("CB", 0.16, 0.50),
        ("CB", 0.18, 0.75),
        ("FB", 0.48, 0.07),
        ("CM", 0.46, 0.38),
        ("CM", 0.46, 0.62),
        ("FB", 0.48, 0.93),
        ("W", 0.82, 0.18),
        ("ST", 0.92, 0.50),
        ("W", 0.82, 0.82),
    ],
    "5-3-2": [
        ("GK", 0.0, 0.5),
        ("FB", 0.32, 0.06),
        ("CB", 0.17, 0.28),
        ("CB", 0.15, 0.50),
        ("CB", 0.17, 0.72),
        ("FB", 0.32, 0.94),
        ("CM", 0.50, 0.30),
        ("DM", 0.45, 0.50),
        ("CM", 0.50, 0.70),
        ("ST", 0.88, 0.40),
        ("ST", 0.88, 0.60),
    ],
}


def zone_value(x: np.ndarray | float, y: np.ndarray | float) -> np.ndarray | float:
    """Possession value of a location (probability-like, 0..~0.35).

    A smooth surface in the spirit of expected threat (Singh, 2019): value rises
    sharply in central zones near goal. Derived here from a closed-form model,
    not copied from any published grid.
    """
    d_goal = np.hypot(LENGTH - np.asarray(x, dtype=float), (np.asarray(y, dtype=float) - GOAL_Y) * 1.35)
    return 0.004 + 0.33 * np.exp(-((d_goal / 17.0) ** 1.35))


def point_segment_distance(
    px: np.ndarray, py: np.ndarray, ax: float, ay: float, bx: float, by: float
) -> np.ndarray:
    """Distance from points to the segment AB (vectorised)."""
    abx, aby = bx - ax, by - ay
    denom = abx * abx + aby * aby
    if denom < 1e-9:
        return np.hypot(px - ax, py - ay)
    t = np.clip(((px - ax) * abx + (py - ay) * aby) / denom, 0.0, 1.0)
    return np.hypot(px - (ax + t * abx), py - (ay + t * aby))


__all__ = ["FORMATIONS", "expected_goals", "point_segment_distance", "shot_angle", "zone_value"]
