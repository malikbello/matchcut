"""Broadcast main camera: a pinhole projection from a high central gantry.

The camera sits behind the near touchline at the halfway line, ~22 m up, as
the main camera does at most stadiums. A director model follows the ball with
critically damped smoothing, leads play slightly, and widens the shot when the
ball is far from the camera or play is stretched. Every frame's camera
parameters are recorded so the vision lane can be scored against exact truth.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

CAM_POS = np.array([52.5, -36.0, 22.0])  # behind the near touchline (y < 0), halfway line, gantry height
UP = np.array([0.0, 0.0, 1.0])


@dataclass(frozen=True)
class CameraState:
    target: tuple[float, float]  # look-at point on the pitch (metres)
    fov_deg: float  # horizontal field of view
    width: int
    height: int
    _rot: np.ndarray = field(init=False, repr=False, compare=False)  # rows: forward, right, up

    def __post_init__(self) -> None:
        # the orientation is fixed for a frame: compute it once, not per projected shape
        look = np.array([self.target[0], self.target[1], 0.0])
        f = look - CAM_POS
        f = f / np.linalg.norm(f)
        r = np.array([f[1] * UP[2] - f[2] * UP[1], f[2] * UP[0] - f[0] * UP[2], f[0] * UP[1] - f[1] * UP[0]])
        r = r / np.linalg.norm(r)
        u = np.array([r[1] * f[2] - r[2] * f[1], r[2] * f[0] - r[0] * f[2], r[0] * f[1] - r[1] * f[0]])
        object.__setattr__(self, "_rot", np.stack([f, r, u]))
        object.__setattr__(self, "_focal", (self.width / 2) / math.tan(math.radians(self.fov_deg) / 2))

    @property
    def focal(self) -> float:
        return self._focal  # type: ignore[attr-defined]

    def basis(self) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        return self._rot[0], self._rot[1], self._rot[2]

    def project(self, pts: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Project (N, 3) world points to (N, 2) pixels; also returns depth (N,)."""
        f, r, u = self._rot
        d = pts - CAM_POS
        zc = d @ f
        xc = d @ r
        yc = d @ u
        zc_safe = np.where(zc > 0.1, zc, 0.1)
        px = self.width / 2 + self.focal * xc / zc_safe
        py = self.height / 2 - self.focal * yc / zc_safe
        return np.stack([px, py], axis=-1), zc

    def to_dict(self) -> dict[str, float]:
        return {
            "target_x": round(self.target[0], 3),
            "target_y": round(self.target[1], 3),
            "fov_deg": round(self.fov_deg, 3),
            "cam_x": float(CAM_POS[0]),
            "cam_y": float(CAM_POS[1]),
            "cam_z": float(CAM_POS[2]),
        }


class Director:
    """Smoothly follows play like a camera operator."""

    def __init__(self, width: int, height: int, fps: float):
        self.w, self.h = width, height
        self.dt = 1.0 / fps
        self.tx, self.ty = 52.5, 34.0
        self.vx = self.vy = 0.0
        self.fov = 34.0

    def update(self, ball_xy: tuple[float, float], spread_m: float) -> CameraState:
        bx, by = ball_xy
        # aim slightly ahead of the ball and a little towards the far side to keep play framed
        aim_x = float(np.clip(bx, 18.0, 87.0))
        aim_y = float(np.clip(by * 0.55 + 34 * 0.45, 20.0, 50.0))
        # critically damped spring (omega ~ 1.6 rad/s) gives broadcast-like pans
        omega = 1.6
        for axis in ("x", "y"):
            pos = self.tx if axis == "x" else self.ty
            vel = self.vx if axis == "x" else self.vy
            aim = aim_x if axis == "x" else aim_y
            acc = omega * omega * (aim - pos) - 2 * omega * vel
            vel += acc * self.dt
            pos += vel * self.dt
            if axis == "x":
                self.tx, self.vx = pos, vel
            else:
                self.ty, self.vy = pos, vel
        # zoom: wider when the ball is far from the camera or play is stretched
        want = 28.0 + 0.16 * by + 0.18 * max(0.0, spread_m - 25)
        want = float(np.clip(want, 26.0, 44.0))
        self.fov += (want - self.fov) * 0.04
        return CameraState((self.tx, self.ty), self.fov, self.w, self.h)
