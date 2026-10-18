"""Command line: generate the league, history, matches and the realism report.

matchcut-sim league   --out data/league
matchcut-sim match    --home kes --away irv --seed 7 --out data/matches
matchcut-sim realism  --matches 12 --out reports/realism.md
"""

from __future__ import annotations

import argparse
import io
import json
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np
from matchcut_analytics import MatchState, MomentDetector, XTModel, score_tactical_detection, train
from matchcut_contracts import Moment

from matchcut_sim.engine import MatchResult, simulate_match
from matchcut_sim.league import build_league
from matchcut_sim.realism import in_range, match_stats, report_markdown, summarise
from matchcut_sim.universe import build_universe


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
    u = build_universe(args.seed)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    def dump(name: str, rows: list) -> None:
        (out / name).write_text(json.dumps(rows, indent=1), encoding="utf-8")

    dump("clubs.json", [c.model_dump() for c in u.league.clubs])
    dump("players.json", [p.model_dump() for p in u.all_players.values()])
    dump("history_matches.json", [m.__dict__ for m in u.history.matches])
    dump("history_player_lines.json", [ln.__dict__ for ln in u.history.lines])
    dump("transfers.json", [t.__dict__ for t in u.transfers])
    dump("careers.json", [c.__dict__ for c in u.careers])
    dump(
        "seasons.json",
        [
            {
                "season": s,
                "top_flight": u.top_flight[s],
                "promoted": u.promoted.get(s, []),
                "relegated": u.relegated.get(s, []),
            }
            for s in u.top_flight
        ],
    )
    print(
        f"{u.league.season}: {len(u.league.clubs)} clubs, {len(u.league.players)} players | history: "
        f"{len(u.history.seasons)} seasons, {len(u.history.matches)} matches, "
        f"{len(u.transfers) // 2} transfers, "
        f"{sum(c.kind == 'retired' for c in u.careers)} retirements -> {out}"
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


def replay_analytics(m: MatchResult, on_moment: Callable[[Moment, dict[str, Any]], None] | None = None):
    """Feed a simulated match through the live analytics in timeline order, as the cloud lane will.

    ``on_moment`` receives each moment as it is detected, with the match snapshot at that instant.
    """
    det = MomentDetector(MatchState(m.meta, XTModel.load_default()))

    def emit(new: list[Moment]) -> None:
        if on_moment is not None:
            for mo in new:
                on_moment(mo, det.state.snapshot())

    events = iter(m.events)
    nxt = next(events, None)
    for i, t in enumerate(m.t_ms):
        while nxt is not None and nxt.t_ms <= t:
            emit(det.on_event(nxt))
            nxt = next(events, None)
        ids = [m.player_ids[r] if r >= 0 else None for r in m.roster[i]]
        period = int(m.period[i])
        home_right = period == 1
        att = {m.meta.home_club_id: home_right, m.meta.away_club_id: not home_right}
        clock = f"{int(t // 60000)}:{int(t // 1000) % 60:02d}"
        new = det.on_tracking(
            int(t),
            clock,
            ids,
            m.team_of_slot,
            m.pos[i, :, 0].tolist(),
            m.speed[i].tolist(),
            att,
            ball_x=float(m.ball[i, 0]),
        )
        emit(new)
    while nxt is not None:
        emit(det.on_event(nxt))
        nxt = next(events, None)
    return det


def cmd_train_xt(args: argparse.Namespace) -> None:
    league = build_league(args.league_seed)
    ids = [c.club_id for c in league.clubs]
    events = []
    for i in range(args.matches):
        m = simulate_match(
            league, ids[i % 20], ids[(i * 7 + 3) % 20], seed=5000 + i, half_minutes=args.half_minutes
        )
        events.extend(m.events)
    model = train(events)
    out = Path(args.out)
    out.write_text(model.to_json(), encoding="utf-8")
    print(f"xT trained on {model.trained_on_events} actions from {args.matches} matches -> {out}")


def cmd_analyse(args: argparse.Namespace) -> None:
    league = build_league(args.league_seed)
    m = simulate_match(league, args.home, args.away, args.seed, half_minutes=args.half_minutes)
    det = replay_analytics(m)
    for mo in det.moments:
        if mo.importance >= args.min_importance:
            print(
                f"{mo.clock:>8}  {mo.kind.value:<15} {mo.team_id or '':<4} {mo.player_id or '':<7} "
                f"{mo.importance:.2f}  {mo.metrics}"
            )
    print("snapshot:", det.state.snapshot())
    print("tactical detection vs truth:", score_tactical_detection(det.moments, m.truth))


def cmd_eval_tactics(args: argparse.Namespace) -> None:
    league = build_league(args.league_seed)
    ids = [c.club_id for c in league.clubs]
    tp = fp = found = changes = 0
    rows = []
    for i in range(args.matches):
        m = simulate_match(league, ids[(3 * i) % 20], ids[(3 * i + 5) % 20], seed=300 + i)
        det = replay_analytics(m)
        sc = score_tactical_detection(det.moments, m.truth)
        n_det = int(sc["detections"])
        tp_i = round(sc["precision"] * n_det) if n_det else 0
        tp, fp = tp + tp_i, fp + n_det - tp_i
        changes += int(sc["changes"])
        found += round(sc["recall"] * sc["changes"])
        rows.append(f"| {m.meta.match_id} | {int(sc['changes'])} | {n_det} | {tp_i} |")
        print(rows[-1], flush=True)
    precision = tp / max(tp + fp, 1)
    recall = found / max(changes, 1)
    md = "\n".join(
        [
            "# Tactical-shift detection vs hidden truth",
            "",
            f"{args.matches} full matches; each contains one hidden tactical change "
            "(a switch to a high press).",
            "A detection counts if it names the right team within 10 minutes after the change.",
            "Detector settings were tuned on 16 separate matches (seeds 400-415); these 8 are held out.",
            "",
            f"**Precision {precision:.0%} · Recall {recall:.0%}**",
            "",
            "| Match | True changes | Detections | Correct |",
            "|---|---|---|---|",
            *rows,
            "",
        ]
    )
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(md, encoding="utf-8")
    print(f"precision {precision:.2f} recall {recall:.2f} -> {out}")


def cmd_feed(args: argparse.Namespace) -> None:
    from matchcut_sim.feed import write_feed  # noqa: PLC0415 - keeps the default CLI start fast

    league = build_league(args.league_seed)
    m = simulate_match(league, args.home, args.away, args.seed)
    print(f"feed -> {write_feed(m, league, args.out)}")


def cmd_cdf(args: argparse.Namespace) -> None:
    from matchcut_sim.cdf import export_cdf  # noqa: PLC0415 - keeps the default CLI start fast

    league = build_league(args.league_seed)
    m = simulate_match(league, args.home, args.away, args.seed)
    out = export_cdf(m, league, args.out, every=args.every)
    print(f"CDF {out} (match.json, meta.json, event.jsonl, tracking.jsonl)")


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
    d = sub.add_parser("train-xt", help="train the expected-threat grid from simulated matches")
    d.add_argument("--matches", type=int, default=40)
    d.add_argument("--half-minutes", type=float, default=15.0)
    d.add_argument("--league-seed", type=int, default=2026)
    d.add_argument("--out", default="packages/analytics/src/matchcut_analytics/xt_grid.json")
    d.set_defaults(fn=cmd_train_xt)
    e = sub.add_parser("analyse", help="replay a match through live analytics and list moments")
    e.add_argument("--home", default="kes")
    e.add_argument("--away", default="irv")
    e.add_argument("--seed", type=int, default=7)
    e.add_argument("--half-minutes", type=float, default=45.0)
    e.add_argument("--min-importance", type=float, default=0.3)
    e.add_argument("--league-seed", type=int, default=2026)
    e.set_defaults(fn=cmd_analyse)
    g = sub.add_parser("eval-tactics", help="score tactical-shift detection against hidden truth")
    g.add_argument("--matches", type=int, default=8)
    g.add_argument("--league-seed", type=int, default=2026)
    g.add_argument("--out", default="reports/tactical-detection.md")
    g.set_defaults(fn=cmd_eval_tactics)
    h = sub.add_parser("cdf", help="export one match in the Common Data Format (CDF v0.3.2)")
    h.add_argument("--home", default="kes")
    h.add_argument("--away", default="irv")
    h.add_argument("--seed", type=int, default=7)
    h.add_argument("--every", type=int, default=1, help="write every Nth 10 Hz tracking frame")
    h.add_argument("--league-seed", type=int, default=2026)
    h.add_argument("--out", default="out/cdf")
    h.set_defaults(fn=cmd_cdf)
    f = sub.add_parser("feed", help="write the 10 Hz screen feed (positions, events, restarts) for one match")
    f.add_argument("--home", default="kes")
    f.add_argument("--away", default="irv")
    f.add_argument("--seed", type=int, default=7)
    f.add_argument("--league-seed", type=int, default=2026)
    f.add_argument("--out", default="out/feeds")
    f.set_defaults(fn=cmd_feed)
    args = p.parse_args(argv)
    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(encoding="utf-8")  # Windows consoles default to cp1252
    args.fn(args)


if __name__ == "__main__":
    main()
