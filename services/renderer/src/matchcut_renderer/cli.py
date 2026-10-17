"""Render a clip of a simulated match.

matchcut-render --home kes --away irv --seed 7 --start 60 --seconds 20 --out renders/clip
matchcut-render --around-goal 1 --seconds 16 --out renders/goal1   (centres the clip on the first goal)
"""

from __future__ import annotations

import argparse
import time

from matchcut_contracts import EventType
from matchcut_sim.engine import simulate_match
from matchcut_sim.league import build_league

from matchcut_renderer.render import RenderSpec, render


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="matchcut-render")
    ap.add_argument("--home", default="kes")
    ap.add_argument("--away", default="irv")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--half-minutes", type=float, default=45.0)
    ap.add_argument("--start", type=float, default=60.0, help="clip start, seconds since kick-off")
    ap.add_argument("--seconds", type=float, default=20.0)
    ap.add_argument("--around-goal", type=int, default=0, help="centre the clip on the Nth goal (1-based)")
    ap.add_argument("--width", type=int, default=1280)
    ap.add_argument("--height", type=int, default=720)
    ap.add_argument("--out", default="renders/clip")
    args = ap.parse_args(argv)
    league = build_league()
    t_sim = time.perf_counter()
    m = simulate_match(league, args.home, args.away, args.seed, half_minutes=args.half_minutes)
    print(f"simulated in {time.perf_counter() - t_sim:.1f}s")
    start_ms = int(args.start * 1000)
    if args.around_goal:
        goals = [e for e in m.events if e.type == EventType.GOAL]
        if len(goals) < args.around_goal:
            raise SystemExit(f"match has only {len(goals)} goals")
        start_ms = max(0, goals[args.around_goal - 1].t_ms - int(args.seconds * 600))
    spec = RenderSpec(start_ms, start_ms + int(args.seconds * 1000), args.width, args.height)
    t0 = time.perf_counter()
    video = render(m, league, spec, args.out)
    took = time.perf_counter() - t0
    print(
        f"{m.meta.match_id} {m.score[0]}-{m.score[1]}: rendered {args.seconds:.0f}s "
        f"at {args.width}x{args.height} "
        f"in {took:.1f}s ({args.seconds * 25 / took:.0f} fps) -> {video}"
    )


if __name__ == "__main__":
    main()
