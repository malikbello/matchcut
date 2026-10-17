"""Realism report: compare simulated matches with top-flight norms (synthetic-data fidelity).

Targets are typical ranges for elite men's leagues (per match, both teams unless
stated). They are ranges, not exact values, because leagues and seasons differ.
Sources: Premier League shot data since 2003/04 (conversion ~10-12%; ~4% outside
the box, ~13% inside; ~43% of shots from outside the box), Stats Perform shot
clarity research (blocked shots), and published physical-performance studies.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from matchcut_contracts import EventType, Outcome

from matchcut_sim.engine import MatchResult
from matchcut_sim.football import expected_goals

PERCENT_KEYS = (
    "pass_completion",
    "shot_conversion",
    "outside_box_share",
    "conversion_inside",
    "conversion_outside",
    "blocked_share",
)

TARGETS: dict[str, tuple[float, float, str]] = {
    "goals": (2.2, 3.4, "goals per match"),
    "shots": (20, 30, "shots per match"),
    "shot_conversion": (0.08, 0.14, "goals per shot"),
    "outside_box_share": (0.35, 0.48, "share of shots from outside the box"),
    "conversion_inside": (0.10, 0.17, "goals per shot inside the box"),
    "conversion_outside": (0.02, 0.06, "goals per shot outside the box"),
    "blocked_share": (0.18, 0.30, "share of shots blocked"),
    "xg_total": (2.0, 3.6, "expected goals per match"),
    "passes": (750, 1150, "passes per match"),
    "pass_completion": (0.76, 0.88, "share of passes completed"),
    "fouls": (16, 28, "fouls per match"),
    "yellows": (2, 6, "yellow cards per match"),
    "distance_km": (9.0, 12.0, "km per outfield player per 90"),
    "top_speed_kmh": (31, 37, "fastest sprint in the match, km/h"),
}


@dataclass
class MatchStats:
    goals: int
    shots: int
    shots_inside: int
    goals_inside: int
    shots_outside: int
    goals_outside: int
    blocked: int
    xg_total: float
    passes: int
    passes_completed: int
    fouls: int
    yellows: int
    distance_km: float
    top_speed_kmh: float
    possession_home: float


def in_box(x: float, y: float) -> bool:
    """Penalty area in the attacking frame (goal at x = 105)."""
    return x >= 105 - 16.5 and 13.84 <= y <= 54.16


def match_stats(m: MatchResult) -> MatchStats:
    ev = m.events
    shots = [e for e in ev if e.type == EventType.SHOT]
    passes = [e for e in ev if e.type == EventType.PASS]
    scored = {e.related_event_id for e in ev if e.type == EventType.GOAL}
    blocked = {e.related_event_id for e in ev if e.type == EventType.BLOCK}
    xg = 0.0
    si = gi = so = go = 0
    for s in shots:
        assert s.x is not None
        assert s.y is not None
        x, y = (s.x, s.y) if s.attacking_right else (105 - s.x, 68 - s.y)
        xg += expected_goals(x, y, under_pressure=bool(s.under_pressure))
        goal = int(s.event_id in scored)
        if in_box(x, y):
            si, gi = si + 1, gi + goal
        else:
            so, go = so + 1, go + goal
    # distance: integrate speed over time per slot, normalised to 90 minutes on the pitch
    dt = 0.1
    dist_slot = (m.speed * dt).sum(axis=0)
    on_pitch = (m.roster >= 0).sum(axis=0) * dt / 60
    keepers = {0, 11}
    per90 = [dist_slot[s] / max(on_pitch[s], 1) * 90 / 1000 for s in range(22) if s not in keepers]
    home_passes = sum(1 for p in passes if p.team_id == m.meta.home_club_id)
    return MatchStats(
        goals=m.score[0] + m.score[1],
        shots=len(shots),
        shots_inside=si,
        goals_inside=gi,
        shots_outside=so,
        goals_outside=go,
        blocked=sum(1 for s in shots if s.event_id in blocked),
        xg_total=round(xg, 2),
        passes=len(passes),
        passes_completed=sum(1 for p in passes if p.outcome == Outcome.SUCCESS),
        fouls=sum(1 for e in ev if e.type == EventType.FOUL),
        yellows=sum(1 for e in ev if e.type == EventType.CARD and e.detail == "yellow"),
        distance_km=round(float(np.mean(per90)), 2),
        top_speed_kmh=round(float(m.speed.max()) * 3.6, 1),
        possession_home=round(home_passes / max(len(passes), 1), 3),
    )


def summarise(stats: list[MatchStats]) -> dict[str, float]:
    n = len(stats)
    shots = sum(s.shots for s in stats)
    passes = sum(s.passes for s in stats)
    return {
        "goals": sum(s.goals for s in stats) / n,
        "shots": shots / n,
        "shot_conversion": sum(s.goals for s in stats) / max(shots, 1),
        "outside_box_share": sum(s.shots_outside for s in stats) / max(shots, 1),
        "conversion_inside": sum(s.goals_inside for s in stats) / max(sum(s.shots_inside for s in stats), 1),
        "conversion_outside": sum(s.goals_outside for s in stats)
        / max(sum(s.shots_outside for s in stats), 1),
        "blocked_share": sum(s.blocked for s in stats) / max(shots, 1),
        "xg_total": sum(s.xg_total for s in stats) / n,
        "passes": passes / n,
        "pass_completion": sum(s.passes_completed for s in stats) / max(passes, 1),
        "fouls": sum(s.fouls for s in stats) / n,
        "yellows": sum(s.yellows for s in stats) / n,
        "distance_km": sum(s.distance_km for s in stats) / n,
        "top_speed_kmh": sum(s.top_speed_kmh for s in stats) / n,
    }


def report_markdown(summary: dict[str, float], n_matches: int) -> str:
    lines = [
        "# Realism report",
        "",
        f"Simulated matches: **{n_matches}** (Harbour League, fixed seeds). Generated by "
        "`matchcut-sim realism`. Targets are typical elite top-flight ranges (synthetic-data fidelity).",
        "",
        "| Metric | Simulated | Target range | In range |",
        "|---|---|---|---|",
    ]
    for key, (lo, hi, label) in TARGETS.items():
        v = summary[key]
        pct = key in PERCENT_KEYS
        fmt = f"{v:.1%}" if pct else f"{v:.2f}"
        rng = f"{lo:.0%}–{hi:.0%}" if pct else f"{lo:g}–{hi:g}"
        lines.append(f"| {label} | {fmt} | {rng} | {'✅' if lo <= v <= hi else '❌'} |")
    return "\n".join(lines) + "\n"


def in_range(summary: dict[str, float]) -> dict[str, bool]:
    return {k: lo <= summary[k] <= hi for k, (lo, hi, _) in TARGETS.items()}
