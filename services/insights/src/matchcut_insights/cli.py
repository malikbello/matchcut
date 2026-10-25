"""matchcut-insights: run the live insights agents over a simulated match, or evaluate them.

    matchcut-insights run --home kes --away wcr --seed 7 --memory-db data/league/memory.sqlite
    matchcut-insights eval --matches 2 --memory-db data/league/memory.sqlite

Needs AZURE_OPENAI_ENDPOINT (and optionally AZURE_OPENAI_MODEL) and an Entra sign-in
that DefaultAzureCredential can use. No keys.
"""

from __future__ import annotations

import argparse
import asyncio
import gzip
import io
import json
import statistics
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from matchcut_contracts import Cue, CueStatus, Moment, MomentKind
from matchcut_memory import LeagueMemory
from matchcut_sim import build_league, simulate_match
from matchcut_sim.cli import replay_analytics

from matchcut_insights.brain import AgentBrain, Brain
from matchcut_insights.calls import build_calls, dribble_calls
from matchcut_insights.facts import MatchContext
from matchcut_insights.pipeline import InsightsPipeline, MomentReport
from matchcut_insights.redteam import red_team, report_markdown
from matchcut_insights.telemetry import configure_telemetry
from matchcut_insights.voice import AzureSpeech, voice_calls, voice_cues

# list price per 1M tokens for gpt-5-mini Global Standard, USD (input, output); for the cost estimate
PRICE_PER_M = (0.25, 2.00)


def moments_with_snapshots(
    home: str, away: str, seed: int
) -> tuple[MatchContext, list[tuple[Moment, dict[str, Any]]]]:
    league = build_league()
    m = simulate_match(league, home, away, seed=seed)
    found: list[tuple[Moment, dict[str, Any]]] = []
    replay_analytics(m, on_moment=lambda mo, snap: found.append((mo, snap)))
    scored: dict[str, int] = {}  # a scorer's earlier goals today: his second is numbered as such
    for i, (mo, snap) in enumerate(found):
        if mo.kind == MomentKind.GOAL and mo.player_id:
            found[i] = (mo, {**snap, "scorer_goals_before": scored.get(mo.player_id, 0)})
            scored[mo.player_id] = scored.get(mo.player_id, 0) + 1
    ids = set(m.meta.home_lineup + m.meta.away_lineup + m.meta.home_bench + m.meta.away_bench)
    ctx = MatchContext(
        home=league.club(home),
        away=league.club(away),
        players={p.player_id: p for p in league.players if p.player_id in ids},
    )
    return ctx, found


async def run_match(
    brain: Brain,
    ctx: MatchContext,
    moments: Sequence[tuple[Moment, dict[str, Any]]],
    languages: Sequence[str],
    concurrency: int = 4,
    memory: Any | None = None,
) -> tuple[list[Cue], list[MomentReport]]:
    pipe = InsightsPipeline(brain, ctx, languages=languages, memory=memory)
    gate = asyncio.Semaphore(concurrency)

    async def one(mo: Moment, snap: dict[str, Any]) -> tuple[list[Cue], MomentReport]:
        async with gate:
            return await pipe.process(mo, snap)

    results = await asyncio.gather(*(one(mo, snap) for mo, snap in moments))
    cues = [c for cs, _ in results for c in cs]
    return cues, [r for _, r in results]


def _brain(args: argparse.Namespace) -> AgentBrain:
    return AgentBrain.from_env(memory_db=args.memory_db)


def _memory(args: argparse.Namespace) -> LeagueMemory | None:
    """League Memory read in-process, for the history every goal gets in code."""
    return LeagueMemory(args.memory_db) if args.memory_db and Path(args.memory_db).is_file() else None


def _top(moments: list[tuple[Moment, dict[str, Any]]], n: int | None) -> list[tuple[Moment, dict[str, Any]]]:
    if not n:
        return moments
    keep = sorted(moments, key=lambda x: -x[0].importance)[:n]
    return sorted(keep, key=lambda x: x[0].t_ms)


async def cmd_run(args: argparse.Namespace) -> None:
    ctx, moments = moments_with_snapshots(args.home, args.away, args.seed)
    moments = _top(moments, args.max_moments)
    only = set(args.moments.split(",")) if args.moments else None
    if only:  # rewrite just these moments; every other line stays as it is
        moments = [m for m in moments if m[0].moment_id in only]
    async with _brain(args) as brain:
        cues, reports = await run_match(
            brain, ctx, moments, args.languages.split(",") if args.languages else [], memory=_memory(args)
        )
    if args.voice:
        voiced = voice_cues(cues, AzureSpeech.from_env(), args.media)
        print(f"voiced {voiced} verified lines -> {args.media}/audio")
    match_id = ctx.home.club_id.lower() + "-" + ctx.away.club_id.lower() + f"-{args.seed}"
    out = Path(args.out or f"out/insights/{moments[0][0].match_id if moments else match_id}.jsonl")
    out.parent.mkdir(parents=True, exist_ok=True)
    rows = [c.model_dump_json() for c in cues]
    if only and out.is_file():  # merge: the rewritten moments replace theirs, in time order
        kept = [
            ln
            for ln in out.read_text(encoding="utf-8").splitlines()
            if ln and json.loads(ln)["moment_id"] not in only
        ]
        rows = sorted(kept + rows, key=lambda ln: (json.loads(ln)["t_ms"], json.loads(ln)["moment_id"]))
    out.write_text("".join(r + "\n" for r in rows), encoding="utf-8")
    for c in cues:
        if c.status != CueStatus.PLAIN or args.verbose:
            print(f"{c.clock:>6} {c.language} {c.status.value:<8} {c.text}")
    for r in reports:
        if r.error or r.problems or r.history_rejected:
            print("  note:", r.moment_id, r.error or "", r.problems, r.history_rejected)
    print(f"{len(cues)} cues -> {out}")


def _pct(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, round(q * (len(ordered) - 1)))]


async def cmd_eval(args: argparse.Namespace) -> None:
    league = build_league()
    ids = [c.club_id for c in league.clubs]
    reports: list[MomentReport] = []
    usage: list[dict[str, Any]] = []
    samples: list[Cue] = []
    all_verified: list[Cue] = []
    async with _brain(args) as brain:
        for i in range(args.matches):
            ctx, moments = moments_with_snapshots(ids[(5 * i) % 20], ids[(5 * i + 7) % 20], 500 + i)
            cues, reps = await run_match(
                brain, ctx, _top(moments, args.max_moments), args.languages.split(","), memory=_memory(args)
            )
            reports += reps
            en = [c for c in cues if c.status == CueStatus.VERIFIED and c.language == "en"]
            samples += en[:4]
            all_verified += en
            print(
                f"match {i + 1}/{args.matches}: "
                f"{sum(r.verified for r in reps)}/{sum(r.ai_attempted for r in reps)} verified",
                flush=True,
            )
        usage = brain.usage
    ai = [r for r in reports if r.ai_attempted]
    verified = [r for r in ai if r.verified]
    first_try = [r for r in verified if r.retries == 0]
    lat = [float(r.latency_ms) for r in verified if r.latency_ms is not None]
    tok_in = sum(u.get("input_token_count", 0) for u in usage)
    tok_out = sum(u.get("output_token_count", 0) for u in usage)
    cost = tok_in / 1e6 * PRICE_PER_M[0] + tok_out / 1e6 * PRICE_PER_M[1]
    n = max(len(ai), 1)
    hist_ok = sum(r.history_accepted for r in ai)
    hist_bad = sum(len(r.history_rejected) for r in ai)
    tr_ok = sum(r.translations_verified for r in ai)
    tr_bad = sum(r.translations_rejected for r in ai)
    rows = [
        ("Moments sent to the agents", f"{len(ai)}"),
        ("Verified on the first draft", f"{len(first_try) / n:.0%}"),
        ("Verified after one retry with Verifier feedback", f"{len(verified) / n:.0%}"),
        ("Kept the plain card (failed checks, error or timeout)", f"{(len(ai) - len(verified)) / n:.0%}"),
        (
            "Unverified numbers or names that reached the screen",
            "0 (by construction: only verified lines air)",
        ),
        ("History claims grounded / rejected", f"{hist_ok} / {hist_bad}"),
        ("Translations verified / rejected", f"{tr_ok} / {tr_bad}"),
        (
            "Latency to verified line, median / p95",
            f"{statistics.median(lat) / 1000 if lat else 0:.1f} s / {_pct(lat, 0.95) / 1000:.1f} s",
        ),
        ("Tokens per moment (in / out)", f"{tok_in // n} / {tok_out // n}"),
        ("Estimated model cost per moment", f"${cost / n:.5f}"),
    ]
    if args.judges:
        from matchcut_insights.judges import judge_lines  # noqa: PLC0415 - optional 'evals' extra

        j = judge_lines(all_verified)
        rows += [
            (
                "Azure AI Evaluation groundedness (1 to 5), mean / pass rate",
                f"{j.groundedness_mean:.2f} / {j.groundedness_pass:.0%} of {j.lines}",
            ),
            (
                "Azure AI Evaluation relevance (1 to 5), mean / pass rate",
                f"{j.relevance_mean:.2f} / {j.relevance_pass:.0%} of {j.lines}",
            ),
        ]
    problems: dict[str, int] = {}
    for r in ai:
        for p in r.problems:
            key = p.split(":")[0]
            problems[key] = problems.get(key, 0) + 1
    md = [
        "# Insights agents: evaluation",
        "",
        f"{args.matches} simulated matches, the {args.max_moments} most important moments of each, "
        f"languages: en + {args.languages}. Model: Foundry `gpt-5-mini`, Microsoft Agent Framework.",
        "",
        "| Measure | Result |",
        "|---|---|",
        *[f"| {a} | {b} |" for a, b in rows],
        "",
        "## What the Verifier caught (first drafts)",
        "",
        *([f"- {k}: {v}" for k, v in sorted(problems.items(), key=lambda kv: -kv[1])] or ["- nothing"]),
        "",
        "## Sample verified lines",
        "",
        *[f"- `{c.clock}` {c.text} (cites {', '.join(c.cited_fact_ids)})" for c in samples[:8]],
        "",
    ]
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(md), encoding="utf-8")
    print("\n".join(md))
    print(f"-> {out}")


def cmd_redteam(args: argparse.Namespace) -> None:
    league = build_league()
    ids = [c.club_id for c in league.clubs]
    total = None
    for i in range(args.matches):
        ctx, moments = moments_with_snapshots(ids[(5 * i) % 20], ids[(5 * i + 7) % 20], 500 + i)
        r = red_team(moments, ctx, seed=i)
        if total is None:
            total = r
        else:
            total.true_lines += r.true_lines
            total.false_rejections += r.false_rejections
            total.attacks += r.attacks
            total.caught += r.caught
            total.misses += r.misses
    assert total is not None
    md = report_markdown(total, args.matches)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(md, encoding="utf-8")
    print(md)


def cmd_calls(args: argparse.Namespace) -> None:
    league = build_league()
    m = simulate_match(league, args.home, args.away, seed=args.seed)
    names = {p.player_id: p.known_as for p in league.players if p.player_id in set(m.player_ids)}
    calls = build_calls(m.meta.match_id, m.events, names)
    feed_path = Path(args.feeds) / f"{m.meta.match_id}.json.gz"
    if feed_path.is_file():  # solo runs come from the tracking feed
        calls += dribble_calls(m.meta.match_id, json.loads(gzip.decompress(feed_path.read_bytes())))
    if args.voice:
        voiced = voice_calls(calls, m.meta.match_id, AzureSpeech.from_env(), args.media)
        print(f"voiced {voiced} calls -> {args.media}/audio/{m.meta.match_id}")
    out = Path(args.out_dir) / f"{m.meta.match_id}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps([c.as_dict() for c in calls], ensure_ascii=False, indent=0), encoding="utf-8")
    print(f"{len(calls)} calls in {len({c.language for c in calls})} languages -> {out}")


def cmd_describe(args: argparse.Namespace) -> None:
    """Write (and voice) a match's audio description: the live track and each moment clip's."""
    from matchcut_insights.describe import describe  # noqa: PLC0415
    from matchcut_insights.voice import voice_descriptions  # noqa: PLC0415

    feed = json.loads(gzip.decompress((Path(args.feeds) / f"{args.match}.json.gz").read_bytes()))
    moments = [{"kind": k, "t": g["t"]} for g in feed.get("goals", []) for k in ("goal", "conceded")]
    descs = describe(args.match, feed, moments)
    if args.voice:
        voiced = voice_descriptions(descs, args.match, AzureSpeech.from_env(), args.media)
        print(f"voiced {voiced} descriptions -> {args.media}/audio/{args.match}")
    out = Path(args.out_dir) / f"{args.match}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps([d.as_dict() for d in descs], ensure_ascii=False, indent=0), encoding="utf-8")
    print(f"{len(descs)} descriptions in {len({d.language for d in descs})} languages -> {out}")


def cmd_voice(args: argparse.Namespace) -> None:
    """Voice a match's verified lines again wherever the words changed since they were voiced
    (no line is rewritten): every voice file says what its caption says."""
    path = Path(args.cues or f"out/insights/{args.match}.jsonl")
    cues = [Cue.model_validate_json(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]
    voiced = voice_cues(cues, AzureSpeech.from_env(), args.media)
    path.write_text("".join(c.model_dump_json() + "\n" for c in cues), encoding="utf-8")
    print(f"{voiced} verified lines voiced and current -> {args.media}/audio/{args.match}")


def main(argv: list[str] | None = None) -> None:
    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser(prog="matchcut-insights")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="run the agents over one simulated match")
    r.add_argument("--home", required=True)
    r.add_argument("--away", required=True)
    r.add_argument("--seed", type=int, default=7)
    r.add_argument("--memory-db", default="data/league/memory.sqlite")
    r.add_argument("--languages", default="en-NG,pcm,yo,ha,ig,ar,es,fr,pt")
    r.add_argument("--voice", action="store_true", help="voice verified lines with Azure AI Speech")
    r.add_argument("--media", default="out/media")
    r.add_argument("--max-moments", type=int, default=12)
    r.add_argument("--moments", help="rewrite only these moment IDs (MO-00004,...) and merge them in")
    r.add_argument("--out")
    r.add_argument("--verbose", action="store_true")
    e = sub.add_parser("eval", help="score the agents over several matches")
    e.add_argument("--matches", type=int, default=2)
    e.add_argument("--max-moments", type=int, default=10)
    e.add_argument("--memory-db", default="data/league/memory.sqlite")
    e.add_argument("--languages", default="es,fr")
    e.add_argument("--out", default="reports/insights-eval.md")
    e.add_argument("--judges", action="store_true", help="add Azure AI Evaluation groundedness and relevance")
    t = sub.add_parser("redteam", help="plant false claims and measure what the Verifier catches (offline)")
    t.add_argument("--matches", type=int, default=4)
    t.add_argument("--out", default="reports/verifier-redteam.md")
    c = sub.add_parser("calls", help="write the play-by-play calls for one match (no model needed)")
    c.add_argument("--home", required=True)
    c.add_argument("--away", required=True)
    c.add_argument("--seed", type=int, default=7)
    c.add_argument("--voice", action="store_true", help="voice the calls with Azure AI Speech")
    c.add_argument("--media", default="out/media")
    c.add_argument("--out-dir", default="out/calls")
    c.add_argument("--feeds", default="out/feeds", help="tracking feeds, for the calls over solo runs")
    d = sub.add_parser("describe", help="write a match's audio description (no model needed)")
    d.add_argument("--match", required=True)
    d.add_argument("--voice", action="store_true", help="voice it with Azure AI Speech")
    d.add_argument("--feeds", default="out/feeds")
    d.add_argument("--media", default="out/media")
    d.add_argument("--out-dir", default="out/describe")
    v = sub.add_parser("voice", help="voice a match's lines again wherever the words changed")
    v.add_argument("--match", required=True)
    v.add_argument("--cues", help="the match's lines (default out/insights/<match>.jsonl)")
    v.add_argument("--media", default="out/media")
    args = p.parse_args(argv)
    if args.cmd == "voice":
        cmd_voice(args)
        return
    if args.cmd == "describe":
        cmd_describe(args)
        return
    if args.cmd == "redteam":
        cmd_redteam(args)
        return
    if args.cmd == "calls":
        cmd_calls(args)
        return
    configure_telemetry("matchcut-insights")
    asyncio.run(cmd_run(args) if args.cmd == "run" else cmd_eval(args))


if __name__ == "__main__":
    main()
