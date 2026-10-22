"""The fan's journey, driven end to end on a phone-sized screen, captured as screenshots.

    matchcut-recap journey --base http://127.0.0.1:8765 --out out/journey

Sign in, follow Kestrel Bay, watch the match reach a goal, see it land in the reel, play it,
share it (the public link a friend opens without the access code), and clip a stretch of play.
It is both the demonstration of how a fan uses Matchcut and an end-to-end test: every step
asserts what a fan would see. The fan's session is also recorded (journey.webm).
"""

from __future__ import annotations

import argparse
import os
import time
from pathlib import Path

from playwright.sync_api import Page, ViewportSize, expect, sync_playwright

PHONE: ViewportSize = {"width": 390, "height": 844}


def shot(page: Page, out: Path, name: str) -> None:
    page.screenshot(path=str(out / f"{name}.png"))
    print(f"  {name}", flush=True)


def run(base: str, code: str, out: Path, seek_ms: int = 3_290_000) -> None:
    out.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        ctx = browser.new_context(
            viewport=PHONE, device_scale_factor=2, is_mobile=True, has_touch=True,
            record_video_dir=str(out), record_video_size=PHONE,
        )  # fmt: skip
        page = ctx.new_page()
        page.goto(base)
        page.fill("#code", code)
        page.click("#gate-form button[type=submit]")
        expect(page.locator("#studio")).to_be_visible(timeout=60_000)
        shot(page, out, "01-live-match")

        # follow Kestrel Bay, in English, on the phone format (the defaults), and jump the
        # replayed match to just after Quinouani's goal (53rd minute)
        page.evaluate("(t) => window.__studio?.seek ? window.__studio.seek(t) : null", seek_ms)
        page.locator("#cut").scroll_into_view_if_needed()
        expect(page.locator("#reel-list .reel-item.goal").first).to_be_visible(timeout=60_000)
        shot(page, out, "02-goal-lands-in-the-reel")

        page.locator("#reel-list .reel-item.goal button", has_text="Play").first.click()
        expect(page.locator("#moment-player")).to_be_visible()
        page.wait_for_timeout(2500)
        shot(page, out, "03-playing-the-goal")

        page.click("#moment-share")
        expect(page.locator("#moment-note")).to_contain_text("/s/", timeout=60_000)
        link = page.locator("#moment-note").inner_text().split("Link copied: ")[-1].strip()
        shot(page, out, "04-share-link")
        page.click("#moment-close")

        friend = browser.new_context(viewport=PHONE, device_scale_factor=2, is_mobile=True).new_page()
        friend.goto(link)
        expect(friend.locator("video")).to_be_visible()
        friend.wait_for_timeout(2500)
        shot(friend, out, "05-a-friend-opens-the-link")

        page.click("#clip-that")
        expect(page.locator("#reel-list .reel-item.clip").first).to_be_visible(timeout=30_000)
        shot(page, out, "06-clip-that")
        video = page.video
        ctx.close()  # the recording is written when its context closes
        if video:
            Path(video.path()).replace(out / "journey.webm")
            print("  journey.webm", flush=True)
        browser.close()


def main() -> None:
    p = argparse.ArgumentParser(prog="matchcut-journey")
    p.add_argument("--base", default="http://127.0.0.1:8765")
    p.add_argument("--out", default="out/journey")
    p.add_argument(
        "--seek", type=int, default=3_290_000, help="match ms to jump to (default: after the first goal)"
    )
    a = p.parse_args()
    started = time.monotonic()
    run(a.base, os.environ["MATCHCUT_ACCESS_CODE"], Path(a.out), a.seek)
    print(f"journey ok in {time.monotonic() - started:.0f} s")


if __name__ == "__main__":
    main()
