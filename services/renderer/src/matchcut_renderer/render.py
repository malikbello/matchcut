"""Render a window of a match to MP4 (H.264), with per-frame camera truth and screen boxes.

Tracking is 10 Hz; video is 25 fps, so positions are linearly interpolated.
Frames are piped straight into ffmpeg as raw RGBA, so nothing large is written
to disk except the final video. ``truth.jsonl`` holds, for every frame, the
camera parameters and every player's and the ball's on-screen box: perfect
labels for training and scoring the vision lane.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import skia
from matchcut_sim.engine import MatchResult
from matchcut_sim.league import League, match_kits

from matchcut_renderer.camera import Director
from matchcut_renderer.scene import GK_KITS, Painter, TeamLook


@dataclass(frozen=True)
class RenderSpec:
    start_ms: int
    end_ms: int
    width: int = 1280
    height: int = 720
    fps: int = 25
    crf: int = 20


def _ffmpeg() -> str:
    exe = shutil.which("ffmpeg")
    if not exe:
        raise RuntimeError("ffmpeg is required on PATH to encode video")
    return exe


def render(m: MatchResult, league: League, spec: RenderSpec, out_dir: str | Path) -> Path:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    home_c, away_c = league.club(m.meta.home_club_id), league.club(m.meta.away_club_id)
    hk, ak = match_kits(home_c, away_c)
    painter = Painter(
        spec.width,
        spec.height,
        TeamLook(hk.primary, hk.secondary, hk.number, GK_KITS[0]),
        TeamLook(ak.primary, ak.secondary, ak.number, GK_KITS[1]),
    )
    director = Director(spec.width, spec.height, spec.fps)
    shirt = {p.player_id: p.shirt_number for p in league.players}
    keepers = {p.player_id for p in league.players if p.position.value == "GK"}
    video = out / "clip.mp4"
    cmd = [
        _ffmpeg(),
        "-v",
        "error",
        "-y",
        "-f",
        "rawvideo",
        "-pix_fmt",
        "rgba",
        "-s",
        f"{spec.width}x{spec.height}",
        "-r",
        str(spec.fps),
        "-i",
        "-",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        str(spec.crf),
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        str(video),
    ]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)  # noqa: S603 - fixed argument list, no shell
    assert proc.stdin is not None
    # explicit RGBA byte order: the platform default is BGRA on Windows, which would swap kit colours
    info = skia.ImageInfo.Make(spec.width, spec.height, skia.kRGBA_8888_ColorType, skia.kPremul_AlphaType)
    surface = skia.Surface.MakeRaster(info)
    t_ms = m.t_ms
    truth_f = (out / "truth.jsonl").open("w", encoding="utf-8")
    try:
        n_frames = int((spec.end_ms - spec.start_ms) / 1000 * spec.fps)
        # warm the director up on the first second so the opening frame is already framed
        for t in np.linspace(spec.start_ms - 1000, spec.start_ms, spec.fps):
            i = int(np.clip(np.searchsorted(t_ms, t), 0, len(t_ms) - 1))
            director.update((float(m.ball[i, 0]), float(m.ball[i, 1])), 30.0)
        for k in range(n_frames):
            t = spec.start_ms + k * 1000 / spec.fps
            i1 = int(np.clip(np.searchsorted(t_ms, t), 1, len(t_ms) - 1))
            i0 = i1 - 1
            a = float(np.clip((t - t_ms[i0]) / max(1, t_ms[i1] - t_ms[i0]), 0, 1))
            pos = m.pos[i0] * (1 - a) + m.pos[i1] * a
            ball = m.ball[i0] * (1 - a) + m.ball[i1] * a
            roster = m.roster[i1]
            on = [s for s in range(22) if roster[s] >= 0]
            xs = pos[on, 0]
            spread = float(np.percentile(xs, 90) - np.percentile(xs, 10)) if on else 30.0
            cam = director.update((float(ball[0]), float(ball[1])), spread)
            players = []
            ids = []
            for s in on:
                pid = m.player_ids[roster[s]]
                ids.append(pid)
                players.append(
                    (
                        float(pos[s, 0]),
                        float(pos[s, 1]),
                        m.team_of_slot[s] == m.meta.home_club_id,
                        shirt.get(pid, 0),
                        pid in keepers,
                    )
                )
            canvas = surface.getCanvas()
            boxes = painter.paint(canvas, cam, players, (float(ball[0]), float(ball[1]), float(ball[2])))
            proc.stdin.write(surface.makeImageSnapshot().tobytes())
            truth_f.write(
                json.dumps(
                    {
                        "frame": k,
                        "t_ms": round(t),
                        "camera": cam.to_dict(),
                        "players": [
                            {
                                "player_id": pid,
                                "team_id": m.team_of_slot[s],
                                "x": round(float(pos[s, 0]), 2),
                                "y": round(float(pos[s, 1]), 2),
                                "box": [round(v, 1) for v in box],
                            }
                            for pid, s, box in zip(ids, on, boxes["players"], strict=True)
                        ],
                        "ball": {
                            "x": round(float(ball[0]), 2),
                            "y": round(float(ball[1]), 2),
                            "z": round(float(ball[2]), 2),
                            "box": [round(v, 1) for v in boxes["ball"]],
                        },
                    }
                )
                + "\n"
            )
    finally:
        truth_f.close()
        proc.stdin.close()
        proc.wait()
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg failed with exit code {proc.returncode}")
    return video
