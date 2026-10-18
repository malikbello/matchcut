import itertools
import json
import shutil

import numpy as np
import pytest
from matchcut_renderer.camera import CameraState, Director
from matchcut_renderer.render import RenderSpec, render
from matchcut_sim import build_league, simulate_match


def test_projection_is_consistent():
    cam = CameraState((52.5, 34.0), 36.0, 1280, 720)
    centre, depth = cam.project(np.array([[52.5, 34.0, 0.0]]))
    assert depth[0] > 0
    assert centre[0][0] == pytest.approx(640, abs=0.5)
    assert centre[0][1] == pytest.approx(360, abs=0.5)
    # the near touchline is lower on screen than the far touchline
    (near, far), _ = cam.project(np.array([[52.5, 0.0, 0.0], [52.5, 68.0, 0.0]]))
    assert near[1] > far[1]
    # objects higher in the air appear higher on screen
    (ground, air), _ = cam.project(np.array([[52.5, 34.0, 0.0], [52.5, 34.0, 2.0]]))
    assert air[1] < ground[1]


def test_director_pans_smoothly_towards_play():
    d = Director(1280, 720, 25)
    xs = [d.update((90.0, 34.0), 30.0).target[0] for _ in range(100)]
    assert xs[-1] > xs[0]
    assert max(abs(b - a) for a, b in itertools.pairwise(xs)) < 2.0  # no jump cuts in the pan


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")
def test_render_writes_video_and_truth(tmp_path):
    league = build_league()
    m = simulate_match(league, "kes", "irv", seed=3, half_minutes=2)
    video = render(m, league, RenderSpec(30_000, 31_000, width=320, height=180), tmp_path)
    assert video.exists()
    assert video.stat().st_size > 1000
    rows = [json.loads(x) for x in (tmp_path / "truth.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 25  # one second at 25 fps
    first = rows[0]
    assert {"camera", "players", "ball"} <= set(first)
    assert len(first["players"]) >= 14
    for p in first["players"]:
        x0, y0, x1, y1 = p["box"]
        assert x1 >= x0
        assert y1 >= y0
