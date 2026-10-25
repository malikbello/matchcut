"""The insights pipeline for one moment.

1. Code builds the fact sheet and a plain card airs at once.
2. Decision stage, the Agent Framework workflow (``workflow.py``): Analyst and
   Historian in parallel (Historian claims grounded against the League Memory
   answers actually received), then the Writer and the deterministic Verifier,
   with one revision on feedback. The verified English line is kept at once.
3. Localisation stage: languages in parallel batches, each translation
   re-checked for numbers, names and house style.
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
from matchcut_insights.facts import MatchContext, build_facts, goal_history_facts
from matchcut_insights.languages import canonical
from matchcut_insights.plain import plain_card
from matchcut_insights.verify import verify_translation
from matchcut_insights.workflow import MomentJob, Outcome, build_workflow

AI_MIN_IMPORTANCE = 0.4  # lower-weight moments keep their plain card (cost and screen time)
# an abstract index reads better as a plain card ("Momentum swings to ...") than as prose
PLAIN_ONLY = frozenset({MomentKind.MOMENTUM_SWING})
MOMENT_TIMEOUT_S = 30.0  # stage 1: the verified English line
TRANSLATE_TIMEOUT_S = 45.0  # stage 2: all languages, after the English line
TRANSLATE_BATCH = 3  # languages per Localiser call, run in parallel


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
    translate_timeout_s: float = TRANSLATE_TIMEOUT_S
    memory: Any | None = None  # League Memory (matchcut_memory.LeagueMemory): goal history in code

    def _goal_history(self, moment: Moment, snapshot: Mapping[str, Any]) -> list[Fact]:
        """For a goal: which goal of the scorer's season and career it is, asked of League Memory
        in code (his earlier goals in this match come with the snapshot)."""
        if self.memory is None or moment.kind != MomentKind.GOAL or not moment.player_id:
            return []
        try:
            answer = self.memory.goal_context(
                moment.player_id,
                moment.team_id == self.ctx.home.club_id,
                int(snapshot.get("scorer_goals_before", 0)),
            )
        except Exception:  # a player League Memory does not know has no history to tell
            return []
        return goal_history_facts(answer)

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
        facts = facts + self._goal_history(moment, snapshot)  # the plain card stays match facts only
        try:
            english = await asyncio.wait_for(self._decide(moment, facts, report, start), self.timeout_s)
        except TimeoutError:
            report.error = f"timed out after {self.timeout_s:.0f} s"
            return cues, report
        except Exception as exc:  # a model failure must never take the screen down
            report.error = f"{type(exc).__name__}: {exc}"[:300]
            return cues, report
        cues.append(english)
        if english.status == CueStatus.VERIFIED and self.languages:
            try:  # translations follow the English line; a slow language never costs it
                cues += await asyncio.wait_for(
                    self._localise(moment, english, report, start), self.translate_timeout_s
                )
            except TimeoutError:
                report.error = f"translations timed out after {self.translate_timeout_s:.0f} s"
            except Exception as exc:
                report.error = f"translations: {type(exc).__name__}: {exc}"[:300]
        return cues, report

    async def _decide(self, moment: Moment, facts: list[Fact], report: MomentReport, start: float) -> Cue:
        """Stage 1, the Agent Framework workflow: Analyst and Historian, Writer, Verifier."""
        job = MomentJob(moment, facts)
        result = await build_workflow(self.brain, self.ctx, job).run(job)
        outcome = next(o for o in result.get_outputs() if isinstance(o, Outcome))
        draft, verdict, line = outcome.draft, outcome.verdict, outcome.draft.line
        report.history_accepted, report.history_rejected = draft.history_accepted, draft.history_rejected
        report.problems = list(draft.problems)
        report.retries = draft.attempt - 1
        report.latency_ms = latency = int((time.perf_counter() - start) * 1000)
        if not outcome.verified:
            return self._cue(
                moment,
                "en",
                CueStatus.REJECTED,
                line.text[:280],
                line.cited_fact_ids,
                draft.facts,
                verdict.checks,
                latency,
            )
        report.verified = True
        cited = [f for f in draft.facts if f.fact_id in set(line.cited_fact_ids)]
        return self._cue(
            moment, "en", CueStatus.VERIFIED, line.text, line.cited_fact_ids, cited, verdict.checks, latency
        )

    async def _localise(self, moment: Moment, english: Cue, report: MomentReport, start: float) -> list[Cue]:
        """Stage 2: languages in parallel batches; each translation must keep the numbers and names
        and be written in its language. A language the Verifier turns down gets one more try, on
        its own (a fan should not lose the line in their language to one bad draft)."""
        names = self.ctx.names()
        wanted = list(self.languages)
        out: list[Cue] = []
        done: set[str] = set()
        for size in (TRANSLATE_BATCH, 1):
            missing = [lang for lang in wanted if lang not in done]
            batches = [missing[i : i + size] for i in range(0, len(missing), size)]
            results = await asyncio.gather(
                *(self.brain.translate(english.text, b) for b in batches), return_exceptions=True
            )
            for batch, items in zip(batches, results, strict=True):
                if isinstance(items, BaseException):
                    continue
                for tr in items:
                    lang = canonical(tr.language)
                    verdict = verify_translation(english.text, tr.text, names, lang or "")
                    if lang is None or lang not in batch or lang in done or not verdict.passed:
                        continue
                    done.add(lang)
                    report.translations_verified += 1
                    out.append(
                        self._cue(
                            moment,
                            lang,
                            CueStatus.VERIFIED,
                            tr.text[:280],
                            english.cited_fact_ids,
                            english.facts,
                            verdict.checks,
                            int((time.perf_counter() - start) * 1000),
                        )
                    )
        report.translations_rejected += len([lang for lang in wanted if lang not in done])
        return out
