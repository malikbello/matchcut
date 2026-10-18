"""Fact sheets: every number an agent may say, computed by code and numbered for citation.

A moment's fact sheet holds who, when and the score, the moment's own metrics, and
the match stats for both sides at that instant. Agents never compute; they pick
facts by ID. League Memory answers become facts too, but only after grounding
(see ``history_facts``).
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from matchcut_contracts import Club, Fact, Moment, Player

METRIC_LABELS = {
    "xg": "expected goals of the shot (0 to 1)",
    "xg_saved": "expected goals of the shot that was saved (0 to 1)",
    "score": "score after the goal, home side first",
    "momentum": "momentum, -1 (away on top) to +1 (home on top)",
    "top_speed_kmh": "top speed in km/h",
    "card": "card colour",
    "on": "substitute coming on (player ID)",
    "signal": "how the tactical change was detected",
    "ppda_last_8_min": "opponent passes per defensive action, last 8 minutes (lower = more pressing)",
    "ppda_before": "opponent passes per defensive action, the 20 minutes before",
}


@dataclass(frozen=True)
class MatchContext:
    """Names the fact sheet can resolve: the two clubs and every player in the match."""

    home: Club
    away: Club
    players: Mapping[str, Player]

    def club(self, club_id: str | None) -> Club | None:
        return {self.home.club_id: self.home, self.away.club_id: self.away}.get(club_id or "")

    def names(self) -> set[str]:
        """Every proper name that could appear on screen for this match."""
        out = {self.home.name, self.away.name, self.home.short_name, self.away.short_name}
        for p in self.players.values():
            out.update({p.known_as, p.name})
        return out


def _minute(clock: str) -> int:
    return int(clock.split(":", 1)[0]) + 1  # 0:00-0:59 is the 1st minute, as broadcasters count


def build_facts(moment: Moment, snapshot: Mapping[str, Any], ctx: MatchContext) -> list[Fact]:
    evidence = [moment.moment_id, *moment.evidence_event_ids]
    facts: list[tuple[str, float | int | str]] = [("match minute", _minute(moment.clock))]
    facts.append((f"score, {ctx.home.name} first", snapshot["score"]))
    facts.append(("home club", ctx.home.name))
    facts.append(("away club", ctx.away.name))
    team = ctx.club(moment.team_id)
    if team is not None:
        facts.append(("club involved", team.name))
    if moment.player_id and moment.player_id in ctx.players:
        p = ctx.players[moment.player_id]
        facts.append(("player involved", p.known_as))
        facts.append(("player's shirt number", p.shirt_number))
    for key, value in moment.metrics.items():
        if key == "on" and isinstance(value, str) and value in ctx.players:
            facts.append(("substitute coming on", ctx.players[value].known_as))
        elif key != "score":  # the score is already a fact
            facts.append((METRIC_LABELS.get(key, key.replace("_", " ")), value))
    for club in (ctx.home, ctx.away):
        s = snapshot.get(club.club_id) or {}
        facts.append((f"{club.name} shots", s.get("shots", 0)))
        facts.append((f"{club.name} shots on target", s.get("on_target", 0)))
        facts.append((f"{club.name} expected goals so far", s.get("xg", 0.0)))
        if s.get("possession") is not None:
            facts.append((f"{club.name} possession, percent", round(100 * s["possession"])))
    return [
        Fact(fact_id=f"F-{i:03d}", label=label, value=value, source="analytics", evidence_ids=evidence)
        for i, (label, value) in enumerate(facts, start=1)
    ]


# ---------------------------------------------------------------- League Memory grounding


def _leaves(obj: Any) -> Iterable[Any]:
    if isinstance(obj, Mapping):
        for v in obj.values():
            yield from _leaves(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _leaves(v)
    else:
        yield obj


def tool_results_by_query(raw_results: Iterable[str]) -> dict[str, dict[str, Any]]:
    """Index the League Memory answers a run actually received, by their query ID."""
    out: dict[str, dict[str, Any]] = {}
    for raw in raw_results:
        try:
            data = json.loads(raw)
        except (TypeError, ValueError):
            continue
        if isinstance(data, dict) and isinstance(data.get("query_id"), str):
            out[data["query_id"]] = data
    return out


def history_facts(
    claims: Iterable[tuple[str, float | int | str, str]], results: Mapping[str, Mapping[str, Any]]
) -> tuple[list[Fact], list[str]]:
    """Turn Historian claims (label, value, query_id) into facts, keeping only grounded ones.

    A claim is grounded when its query ID was really returned by a League Memory
    tool in this run and its value appears verbatim in that answer.
    """
    accepted: list[Fact] = []
    rejected: list[str] = []
    per_query: dict[str, int] = {}
    for label, value, qid in claims:
        answer = results.get(qid)
        leaves = list(_leaves(answer)) if answer is not None else []
        if answer is None or not any(_same(value, leaf) for leaf in leaves):
            rejected.append(f"{qid}: {label} = {value!r}")
            continue
        per_query[qid] = per_query.get(qid, 0) + 1
        evidence = [qid, *[e for e in answer.get("evidence", []) if isinstance(e, str)]]
        accepted.append(
            Fact(
                fact_id=f"{qid}.{per_query[qid]}",
                label=label,
                value=value,
                source="league_memory",
                evidence_ids=evidence,
            )
        )
    return accepted, rejected


def _same(a: Any, b: Any) -> bool:
    if isinstance(a, bool) or isinstance(b, bool):
        return a is b
    if isinstance(a, int | float) and isinstance(b, int | float):
        return abs(float(a) - float(b)) < 1e-9
    return isinstance(a, str) and isinstance(b, str) and a.strip().lower() == b.strip().lower()
