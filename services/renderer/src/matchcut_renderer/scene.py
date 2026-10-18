"""Paint one broadcast frame: floodlit stadium, mown pitch, exact markings, goals and players.

All geometry is projected through ``CameraState`` so markings and players stay
consistent with the camera truth used to score the vision lane.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import skia

from matchcut_renderer.camera import CameraState

L, W = 105.0, 68.0
STRIPES = 18
GRASS_A = (0x1F, 0x6B, 0x3D)
GRASS_B = (0x24, 0x77, 0x44)
LINE = skia.Color4f(0.96, 0.97, 0.98, 0.92)
GK_KITS = ("#3BB273", "#8E44AD")  # neutral keeper colours, distinct from every outfield kit


def _hex(c: str, a: float = 1.0) -> skia.Color4f:
    return skia.Color4f(int(c[1:3], 16) / 255, int(c[3:5], 16) / 255, int(c[5:7], 16) / 255, a)


def _circle(cx: float, cy: float, r: float, n: int = 48) -> np.ndarray:
    a = np.linspace(0, 2 * math.pi, n)
    return np.stack([cx + r * np.cos(a), cy + r * np.sin(a), np.zeros(n)], axis=1)


def _arc(cx: float, cy: float, r: float, a0: float, a1: float, n: int = 24) -> np.ndarray:
    a = np.linspace(a0, a1, n)
    return np.stack([cx + r * np.cos(a), cy + r * np.sin(a), np.zeros(n)], axis=1)


def _poly(pts: list[tuple[float, float]]) -> np.ndarray:
    return np.array([[x, y, 0.0] for x, y in pts])


def pitch_lines() -> list[np.ndarray]:
    """Every marking as a 3D polyline (Laws of the Game dimensions)."""
    lines = [
        _poly([(0, 0), (L, 0), (L, W), (0, W), (0, 0)]),
        _poly([(L / 2, 0), (L / 2, W)]),
        _circle(L / 2, W / 2, 9.15),
    ]
    for gx, sgn in ((0.0, 1), (L, -1)):
        lines.append(
            _poly(
                [
                    (gx, W / 2 - 20.16),
                    (gx + sgn * 16.5, W / 2 - 20.16),
                    (gx + sgn * 16.5, W / 2 + 20.16),
                    (gx, W / 2 + 20.16),
                ]
            )
        )
        lines.append(
            _poly(
                [
                    (gx, W / 2 - 9.16),
                    (gx + sgn * 5.5, W / 2 - 9.16),
                    (gx + sgn * 5.5, W / 2 + 9.16),
                    (gx, W / 2 + 9.16),
                ]
            )
        )
        spot_x = gx + sgn * 11
        a = math.acos(5.5 / 9.15)
        lines.append(
            _arc(spot_x, W / 2, 9.15, -a, a)
            if sgn == 1
            else _arc(spot_x, W / 2, 9.15, math.pi - a, math.pi + a)
        )
    return lines


@dataclass
class TeamLook:
    kit: str
    trim: str
    number: str
    gk: str


class Painter:
    def __init__(self, width: int, height: int, home: TeamLook, away: TeamLook):
        self.w, self.h = width, height
        self.home, self.away = home, away
        self.lines = pitch_lines()
        self.font = skia.Font(skia.Typeface("Arial", skia.FontStyle.Bold()), 11)

    # ------------------------------------------------------------ background
    def _stadium(self, c: skia.Canvas) -> None:
        sky = skia.Paint(
            Shader=skia.GradientShader.MakeLinear(
                points=[skia.Point(0, 0), skia.Point(0, self.h * 0.55)],
                colors=[skia.Color(10, 14, 22), skia.Color(28, 34, 46)],
            )
        )
        c.drawRect(skia.Rect(0, 0, self.w, self.h), sky)
        # floodlight bloom along the far stand
        for fx in (0.12, 0.38, 0.62, 0.88):
            glow = skia.Paint(
                Shader=skia.GradientShader.MakeRadial(
                    center=skia.Point(self.w * fx, self.h * 0.04),
                    radius=self.w * 0.22,
                    colors=[skia.Color(255, 250, 235, 70), skia.Color(255, 250, 235, 0)],
                )
            )
            c.drawRect(skia.Rect(0, 0, self.w, self.h), glow)

    def _pitch(self, c: skia.Canvas, cam: CameraState) -> None:
        # surround (beyond the lines) slightly darker, then mown stripes across the pitch
        edge = np.array([[-6, -5, 0], [L + 6, -5, 0], [L + 6, W + 5, 0], [-6, W + 5, 0]], dtype=float)
        self._quad(c, cam, edge, skia.Color(22, 84, 48))
        for i in range(STRIPES):
            x0, x1 = L * i / STRIPES, L * (i + 1) / STRIPES
            q = np.array([[x0, 0, 0], [x1, 0, 0], [x1, W, 0], [x0, W, 0]], dtype=float)
            col = GRASS_A if i % 2 == 0 else GRASS_B
            self._quad(c, cam, q, skia.Color(*col))
        stroke = skia.Paint(
            Color4f=LINE, Style=skia.Paint.kStroke_Style, StrokeWidth=max(1.2, self.w / 900), AntiAlias=True
        )
        for line in self.lines:
            px, depth = cam.project(line)
            if (depth <= 0.5).all():
                continue
            path = skia.Path()
            path.moveTo(*px[0])
            for p in px[1:]:
                path.lineTo(*p)
            c.drawPath(path, stroke)
        self._goals(c, cam)

    def _goals(self, c: skia.Canvas, cam: CameraState) -> None:
        post = skia.Paint(
            Color4f=skia.Color4f(1, 1, 1, 0.95),
            Style=skia.Paint.kStroke_Style,
            StrokeWidth=max(1.6, self.w / 700),
            AntiAlias=True,
        )
        net = skia.Paint(
            Color4f=skia.Color4f(1, 1, 1, 0.18), Style=skia.Paint.kStroke_Style, StrokeWidth=1, AntiAlias=True
        )
        for gx, depth in ((0.0, -2.0), (L, 2.0)):
            y0, y1, h = W / 2 - 3.66, W / 2 + 3.66, 2.44
            frame = np.array([[gx, y0, 0], [gx, y0, h], [gx, y1, h], [gx, y1, 0]], dtype=float)
            back = np.array(
                [
                    [gx + depth, y0, 0],
                    [gx + depth, y0, h * 0.8],
                    [gx + depth, y1, h * 0.8],
                    [gx + depth, y1, 0],
                ],
                dtype=float,
            )
            pf, _ = cam.project(frame)
            pb, _ = cam.project(back)
            for a, b in ((pf, pb),):
                for k in range(4):
                    c.drawLine(*a[k], *b[k], net)
            c.drawLine(*pb[1], *pb[2], net)
            path = skia.Path()
            path.moveTo(*pf[0])
            for p in pf[1:]:
                path.lineTo(*p)
            c.drawPath(path, post)

    def _quad(self, c: skia.Canvas, cam: CameraState, q: np.ndarray, color: int) -> None:
        px, depth = cam.project(q)
        if (depth <= 0.5).any():
            return
        path = skia.Path()
        path.moveTo(*px[0])
        for p in px[1:]:
            path.lineTo(*p)
        path.close()
        c.drawPath(path, skia.Paint(Color=color, AntiAlias=True))

    # ------------------------------------------------------------ people
    def _player(
        self, c: skia.Canvas, cam: CameraState, x: float, y: float, look: TeamLook, number: int, keeper: bool
    ) -> tuple[float, float, float, float]:
        """Draw one player; returns the on-screen bounding box (x0, y0, x1, y1)."""
        pts, depth = cam.project(np.array([[x, y, 0.0], [x, y, 1.82]]))
        if depth[0] <= 0.5:
            return (0, 0, 0, 0)
        (fx, fy), (_hx, hy) = pts
        height = max(4.0, fy - hy)
        width = height * 0.36
        kit = _hex(look.gk if keeper else look.kit)
        trim = _hex(look.trim)
        # ground shadow (floodlights cast several soft shadows)
        sh = skia.Paint(
            Color4f=skia.Color4f(0, 0, 0, 0.32),
            AntiAlias=True,
            MaskFilter=skia.MaskFilter.MakeBlur(skia.kNormal_BlurStyle, max(0.6, height * 0.05)),
        )
        c.drawOval(skia.Rect(fx - width * 0.9, fy - height * 0.06, fx + width * 0.9, fy + height * 0.05), sh)
        legs = skia.Paint(Color4f=skia.Color4f(0.09, 0.1, 0.12, 1), AntiAlias=True)
        c.drawRoundRect(skia.Rect(fx - width * 0.32, fy - height * 0.42, fx - width * 0.04, fy), 2, 2, legs)
        c.drawRoundRect(skia.Rect(fx + width * 0.04, fy - height * 0.42, fx + width * 0.32, fy), 2, 2, legs)
        c.drawRoundRect(
            skia.Rect(fx - width * 0.42, fy - height * 0.52, fx + width * 0.42, fy - height * 0.36),
            2,
            2,
            skia.Paint(Color4f=trim, AntiAlias=True),
        )
        torso = skia.Rect(fx - width * 0.5, fy - height * 0.86, fx + width * 0.5, fy - height * 0.5)
        c.drawRoundRect(torso, width * 0.22, width * 0.22, skia.Paint(Color4f=kit, AntiAlias=True))
        # rim light from the floodlights
        rim = skia.Paint(
            Color4f=skia.Color4f(1, 1, 1, 0.22), Style=skia.Paint.kStroke_Style, StrokeWidth=1, AntiAlias=True
        )
        c.drawRoundRect(torso, width * 0.22, width * 0.22, rim)
        c.drawCircle(
            fx,
            fy - height * 0.93,
            height * 0.075,
            skia.Paint(Color4f=skia.Color4f(0.2, 0.16, 0.14, 1), AntiAlias=True),
        )
        if height > 26:
            self.font.setSize(max(7.0, height * 0.17))
            label = str(number)
            tw = self.font.measureText(label)
            c.drawString(
                label,
                fx - tw / 2,
                fy - height * 0.6,
                self.font,
                skia.Paint(Color4f=_hex(look.number), AntiAlias=True),
            )
        return (fx - width * 0.6, hy - height * 0.05, fx + width * 0.6, fy + height * 0.03)

    def _ball(self, c: skia.Canvas, cam: CameraState, bx: float, by: float, bz: float) -> tuple[float, ...]:
        pts, depth = cam.project(np.array([[bx, by, 0.0], [bx, by, bz + 0.11], [bx, by + 0.22, bz + 0.11]]))
        if depth[1] <= 0.5:
            return (0, 0, 0, 0)
        r = max(1.6, float(np.hypot(*(pts[2] - pts[1]))))
        sh = skia.Paint(Color4f=skia.Color4f(0, 0, 0, 0.35), AntiAlias=True)
        c.drawOval(skia.Rect(pts[0][0] - r, pts[0][1] - r * 0.45, pts[0][0] + r, pts[0][1] + r * 0.45), sh)
        c.drawCircle(*pts[1], r, skia.Paint(Color4f=skia.Color4f(0.98, 0.98, 0.98, 1), AntiAlias=True))
        return (pts[1][0] - r, pts[1][1] - r, pts[1][0] + r, pts[1][1] + r)

    # ------------------------------------------------------------ frame
    def paint(
        self,
        c: skia.Canvas,
        cam: CameraState,
        players: list[tuple[float, float, bool, int, bool]],
        ball: tuple[float, float, float],
    ) -> dict[str, list]:
        """players: (x, y, is_home, shirt_number, is_keeper). Returns screen boxes (for vision truth)."""
        self._stadium(c)
        self._pitch(c, cam)
        order = sorted(
            range(len(players)), key=lambda i: -players[i][1]
        )  # far side first (painter's algorithm)
        boxes: list[tuple[float, float, float, float]] = [(0.0, 0.0, 0.0, 0.0)] * len(players)
        for i in order:
            x, y, is_home, num, gk = players[i]
            boxes[i] = self._player(c, cam, x, y, self.home if is_home else self.away, num, gk)
        ball_box = self._ball(c, cam, *ball)
        return {"players": boxes, "ball": list(ball_box)}
