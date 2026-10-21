"""The renderer: drives the Studio's render mode in headless Chromium, frame by frame, into ffmpeg.

The Studio runs on a virtual clock in render mode, so frame N always shows the same picture
however long it takes to draw (exports are reproducible). Frames go to ffmpeg as JPEG over a
pipe and come out as H.264. On servers without a GPU, Chromium's ANGLE is pointed at Mesa's
llvmpipe (--use-angle=gl), which renders WebGL several times faster than SwiftShader.
"""

from __future__ import annotations

import subprocess
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from playwright.sync_api import Page, sync_playwright

SIZES = {"16x9": (1280, 720), "9x16": (720, 1280)}
# Films render at one fixed quality for the whole cut. Measured on CPU (Mesa llvmpipe, 720x1280):
# High 3.8 s a frame, of which ambient occlusion is 2.1 s; without it 1.8 s. At film size the
# shadow maps already ground the players, so films keep shadows, bloom and the full crowd.
FILM_QUALITY: dict[str, Any] = {"base": "high", "gtao": False}
GPU_LESS_ARGS = ["--use-gl=angle", "--use-angle=gl", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"]


class Studio:
    """A render-mode Studio page, signed in, with the match loaded."""

    def __init__(
        self,
        base: str,
        code: str,
        match: str,
        lang: str,
        aspect: str,
        gpu_less: bool = False,
        quality: str | dict[str, Any] = FILM_QUALITY,
    ):
        self.base, self.code, self.match, self.lang, self.aspect = base.rstrip("/"), code, match, lang, aspect
        self.gpu_less, self.quality = gpu_less, quality
        self._pw = None
        self.page: Page | None = None

    def __enter__(self) -> Studio:
        self._pw = sync_playwright().start()
        browser = self._pw.chromium.launch(args=GPU_LESS_ARGS if self.gpu_less else [])
        w, h = SIZES[self.aspect]
        ctx = browser.new_context(viewport={"width": w, "height": h}, device_scale_factor=1)
        r = ctx.request.post(f"{self.base}/api/session", data={"code": self.code})
        if not r.ok:
            raise RuntimeError(f"render sign-in failed: {r.status}")
        self.page = ctx.new_page()
        self.page.goto(f"{self.base}/?render=1")
        self.page.wait_for_function("() => window.__render")
        self.info = self.page.evaluate(
            "(a) => window.__render.init(a)",
            {"match": self.match, "lang": self.lang, "aspect": self.aspect, "quality": self.quality},
        )
        return self

    def __exit__(self, *exc: object) -> None:
        if self._pw:
            self._pw.stop()

    def step(self, spec: dict[str, Any], index: int, fps: int) -> None:
        """Advance the page to frame `index` without capturing it."""
        assert self.page
        self.page.evaluate("([s, i, f]) => window.__render.frame(s, i, f)", [spec, index, fps])

    def probe(self) -> dict[str, Any] | None:
        """Where the drawn ball sits against the striking bone and the controlling player."""
        assert self.page
        return self.page.evaluate("() => window.__render.probe()")

    def still(self, spec: dict[str, Any], index: int, fps: int, out: Path) -> Path:
        """One frame of the film as a PNG (QA, thumbnails)."""
        assert self.page
        self.step(spec, index, fps)
        self.page.screenshot(path=str(out), type="png")
        return out

    def package_duration(self, goal_t: int) -> float:
        assert self.page
        return float(self.page.evaluate("(t) => window.__render.packageDuration(t)", goal_t))

    def render(
        self,
        specs: list[dict[str, Any]],
        fps: int,
        out: Path,
        ffmpeg: str = "ffmpeg",
        progress: Callable[[int, int, float], None] | None = None,
        first: int = 0,
        warmup: list[dict[str, Any]] | None = None,
    ) -> Path:
        """Encode `specs` as frames `first`, `first + 1`, ... of the film. A slice of a film
        (one render-job chunk) first steps through `warmup`, the frames just before it,
        uncaptured, so animation blends and camera moves match a straight-through render."""
        assert self.page
        for j, spec in enumerate(warmup or []):
            self.step(spec, first - len(warmup or []) + j, fps)
        enc = subprocess.Popen(  # noqa: S603 - our own arguments
            [
                ffmpeg,
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-f",
                "image2pipe",
                "-c:v",
                "mjpeg",
                "-framerate",
                str(fps),
                "-i",
                "-",
                "-c:v",
                "libx264",
                # quality-led but capped for sharing: phones and social apps play it without
                # re-encoding, and an 80 s film stays near 40 MB
                "-preset",
                "slow",
                "-crf",
                "20",
                "-maxrate",
                "4500k",
                "-bufsize",
                "9000k",
                "-profile:v",
                "high",
                "-pix_fmt",
                "yuv420p",
                "-movflags",
                "+faststart",
                str(out),
            ],
            stdin=subprocess.PIPE,
        )
        assert enc.stdin
        t0 = time.perf_counter()
        for i, spec in enumerate(specs):
            self.step(spec, first + i, fps)
            enc.stdin.write(self.page.screenshot(type="jpeg", quality=92))
            if progress and (i % 30 == 0 or i == len(specs) - 1):
                progress(i + 1, len(specs), time.perf_counter() - t0)
        enc.stdin.close()
        if enc.wait() != 0:
            raise RuntimeError("video encode failed")
        return out


def concat(parts: list[Path], out: Path, ffmpeg: str = "ffmpeg") -> Path:
    """Join chunk videos losslessly: every chunk is its own H.264 stream with the same settings,
    starting on a keyframe, so the parts butt together with no re-encode."""
    listing = out.with_suffix(".parts.txt")
    lines = [f"file '{p.resolve().as_posix()}'" for p in parts]
    listing.write_text("".join(f"{line}\n" for line in lines), encoding="utf-8")
    subprocess.run(  # noqa: S603 - our own arguments
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(listing),
            "-c",
            "copy",
            "-movflags",
            "+faststart",
            str(out),
        ],
        check=True,
    )
    listing.unlink(missing_ok=True)
    return out


def mux(video: Path, audio: Path, out: Path, ffmpeg: str = "ffmpeg") -> Path:
    subprocess.run(  # noqa: S603 - our own arguments
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(video),
            "-i",
            str(audio),
            "-c:v",
            "copy",
            "-c:a",
            "copy",
            "-shortest",
            "-movflags",
            "+faststart",
            str(out),
        ],
        check=True,
    )
    return out
