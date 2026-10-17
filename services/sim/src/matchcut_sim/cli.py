"""Command line: generate the league, history, matches and the realism report.

matchcut-sim league   --out data/league
matchcut-sim match    --home kes --away irv --seed 7 --out data/matches
matchcut-sim realism  --matches 12 --out reports/realism.md
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import numpy as np

from matchcut_sim.engine import MatchResult, simulate_match
from matchcut_sim.history import simulate_history
from matchcut_sim.league import build_league
from matchcut_sim.realism import in_range, match_stats, report_markdown, summarise

PAST_SEASONS = ["2024-25", "2025-26"]


def write_match(m: MatchResult, out: Path) -> Path:
    d = out / m.meta.match_id
    d.mkdir(parents=True, exist_ok=True)
    (d / "meta.json").write_text(m.meta.model_dump_json(indent=2), encoding="utf-8")
    with (d / "events.jsonl").open("w", encoding="utf-8", newline="\n") as f:
        for e in m.events:
            f.write(e.model_dump_json(exclude_none=True) + "\n")
    with (d / "truth.jsonl").open("w", encoding="utf-8", newline="\n") as f:
        for t in m.truth:
            f.write(t.model_dump_json() + "\n")
    np.savez_compressed(
        d / "tracking.npz",
        t_ms=m.t_ms,
        period=m.period,
        pos=m.pos,
        speed=m.speed,
        ball=m.ball,
        roster=m.roster,
        player_ids=np.array(m.player_ids),
        team_of_slot=np.array(m.team_of_slot),
    )
    return d


def cmd_league(args: argparse.Namespace) -> None:
    league = build_league(args.seed)
    hist = simulate_history(league, PAST_SEASONS, seed=args.seed + 1)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "clubs.json").write_text(
        json.dumps([c.model_dump() for c in league.clubs], indent=2), encoding="utf-8"
    )
    (out / "players.json").write_text(
        json.dumps([p.model_dump() for p in league.players], indent=2), encoding="utf-8"
    )
    (out / "history_matches.json").write_text(
        json.dumps([m.__dict__ for m in hist.matches]), encoding="utf-8"
    )
    (out / "history_player_lines.json").write_text(
        json.dumps([ln.__dict__ for ln in hist.lines]), encoding="utf-8"
    )
    print(
        f"{len(league.clubs)} clubs, {len(league.players)} players, {len(hist.matches)} past matches -> {out}"
    )


def cmd_match(args: argparse.Namespace) -> None:
    league = build_league(args.league_seed)
    t0 = time.perf_counter()
    m = simulate_match(league, args.home, args.away, args.seed, args.matchday)
    d = write_match(m, Path(args.out))
    s = match_stats(m)
    print(
        f"{m.meta.match_id}: {m.score[0]}-{m.score[1]} | {len(m.events)} events | {len(m.t_ms)} frames | "
        f"{s.shots} shots, xG {s.xg_total}, "
        f"{s.passes} passes ({s.passes_completed / max(s.passes, 1):.0%}) | "
        f"{time.perf_counter() - t0:.1f}s -> {d}"
    )


def cmd_realism(args: argparse.Namespace) -> None:
    league = build_league(args.league_seed)
    ids = [c.club_id for c in league.clubs]
    stats = []
    for i in range(args.matches):
        home, away = ids[(2 * i) % 20], ids[(2 * i + 7) % 20]
        stats.append(match_stats(simulate_match(league, home, away, seed=100 + i)))
    summary = summarise(stats)
    md = report_markdown(summary, len(stats))
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(md, encoding="utf-8", newline="\n")
    print(md)
    ok = in_range(summary)
    print(f"{sum(ok.values())}/{len(ok)} metrics in range")


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="matchcut-sim")
    sub = p.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("league")
    a.add_argument("--seed", type=int, default=2026)
    a.add_argument("--out", default="data/league")
    a.set_defaults(fn=cmd_league)
    b = sub.add_parser("match")
    b.add_argument("--home", default="kes")
    b.add_argument("--away", default="irv")
    b.add_argument("--seed", type=int, default=7)
    b.add_argument("--matchday", type=int, default=9)
    b.add_argument("--league-seed", type=int, default=2026)
    b.add_argument("--out", default="data/matches")
    b.set_defaults(fn=cmd_match)
    c = sub.add_parser("realism")
    c.add_argument("--matches", type=int, default=12)
    c.add_argument("--league-seed", type=int, default=2026)
    c.add_argument("--out", default="reports/realism.md")
    c.set_defaults(fn=cmd_realism)
    args = p.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
