"""The insights pipeline for one moment.

1. Code builds the fact sheet and a plain card airs at once.
2. The Agent Framework workflow (see ``workflow.py``) runs Analyst and Historian
   in parallel (Historian claims grounded against the League Memory answers
   actually received), then the Writer and the deterministic Verifier, with one
   revision on feedback, then the Localiser with re-checked translations.
Any model error or timeout leaves the plain card on air: the screen never waits on AI.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from matchcut_contracts import Cue, CueStatus, Fact, Moment, MomentKind

from matchcut_insights.brain import Brain
from matchcut_insights.facts import MatchContext, build_facts
from matchcut_insights.plain import plain_card
from matchcut_insights.workflow import MomentJob, Outcome, build_workflow

AI_MIN_IMPORTANCE = 0.4  # lower-weight moments keep their plain card (cost and screen time)
# an abstract index reads better as a plain card ("Momentum swings to ...") than as prose
PLAIN_ONLY = frozenset({MomentKind.MOMENTUM_SWING})
MOMENT_TIMEOUT_S = 30.0


@dataclass
class MomentReport:
    """What happened to one moment, for evaluation."""

    moment_id: str
    kind: str
    ai_attempted: bool = False
    verified: bool = False
    retries: int = 0
    problems: list[str] = field(default_factory=list)
    history_accepted: int = 0
    history_rejected: list[str] = field(default_factory=list)
    translations_verified: int = 0
    translations_rejected: int = 0
    latency_ms: int | None = None
    error: str | None = None


@dataclass
class InsightsPipeline:
    brain: Brain
    ctx: MatchContext
    languages: Sequence[str] = ("es", "fr", "pt")
    min_importance: float = AI_MIN_IMPORTANCE
    timeout_s: float = MOMENT_TIMEOUT_S

    def _cue(
        self,
        moment: Moment,
        lang: str,
        status: CueStatus,
        text: str,
        cited: list[str],
        facts: list[Fact],
        checks: Mapping[str, bool] | None = None,
        latency_ms: int | None = None,
    ) -> Cue:
        return Cue(
            match_id=moment.match_id,
            cue_id=f"CU-{moment.moment_id[3:]}-{lang}",
            moment_id=moment.moment_id,
            kind=moment.kind,
            t_ms=moment.t_ms,
            clock=moment.clock,
            language=lang,
            status=status,
            text=text,
            cited_fact_ids=cited,
            facts=facts,
            checks=dict(checks or {}),
            latency_ms=latency_ms,
        )

    async def process(self, moment: Moment, snapshot: Mapping[str, Any]) -> tuple[list[Cue], MomentReport]:
        start = time.perf_counter()
        report = MomentReport(moment.moment_id, moment.kind.value)
        facts = build_facts(moment, snapshot, self.ctx)
        text, used = plain_card(moment, facts)
        cues = [self._cue(moment, "en", CueStatus.PLAIN, text, used, facts)]
        if moment.importance < self.min_importance or moment.kind in PLAIN_ONLY:
            return cues, report
        report.ai_attempted = True
        try:
            cues += await asyncio.wait_for(self._ai(moment, facts, report, start), self.timeout_s)
        except TimeoutError:
            report.error = f"timed out after {self.timeout_s:.0f} s"
        except Exception as exc:  # a model failure must never take the screen down
            report.error = f"{type(exc).__name__}: {exc}"[:300]
        return cues, report

    async def _ai(self, moment: Moment, facts: list[Fact], report: MomentReport, start: float) -> list[Cue]:
        job = MomentJob(moment, facts)
        workflow = build_workflow(self.brain, self.ctx, list(self.languages), job)
        result = await workflow.run(job)
        outcome = next(o for o in result.get_outputs() if isinstance(o, Outcome))
        draft, verdict = outcome.draft, outcome.verdict
        report.history_accepted, report.history_rejected = draft.history_accepted, draft.history_rejected
        report.problems = list(draft.problems)
        report.retries = draft.attempt - 1
        latency = int((time.perf_counter() - start) * 1000)
        report.latency_ms = latency
        line = draft.line
        if not outcome.verified:
            return [
                self._cue(
                    moment,
                    "en",
                    CueStatus.REJECTED,
                    line.text[:280],
                    line.cited_fact_ids,
                    draft.facts,
                    verdict.checks,
                    latency,
                )
            ]
        report.verified = True
        cited = [f for f in draft.facts if f.fact_id in set(line.cited_fact_ids)]
        out = [
            self._cue(
                moment,
                "en",
                CueStatus.VERIFIED,
                line.text,
                line.cited_fact_ids,
                cited,
                verdict.checks,
                latency,
            )
        ]
        for tr, tv in outcome.translations:
            lang = tr.language.lower()[:2]
            if lang not in self.languages or not tv.passed:
                report.translations_rejected += 1
                continue
            report.translations_verified += 1
            out.append(
                self._cue(
                    moment,
                    lang,
                    CueStatus.VERIFIED,
                    tr.text[:280],
                    line.cited_fact_ids,
                    cited,
                    tv.checks,
                    int((time.perf_counter() - start) * 1000),
                )
            )
        return out
