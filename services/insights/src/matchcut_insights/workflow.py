"""The insights flow as a Microsoft Agent Framework workflow graph.

    moment ──► Analyst ─┐
           └─► Historian ┴─► Writer ──► Verifier ──► Localiser ──► output
                              ▲            │ (one revision with feedback)
                              └────────────┘
                                         └──► output (rejected: the plain card stays)

Executors are typed; the framework runs Analyst and Historian in parallel, joins
them, and routes the Verifier's decision along conditional edges. Running on the
framework also gives OpenTelemetry spans for every executor and model call.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Never

from agent_framework import Executor, Workflow, WorkflowBuilder, WorkflowContext, handler
from matchcut_contracts import Fact, Moment

from matchcut_insights.brain import AnalystNote, Brain, HistoryNote, Line, Translation
from matchcut_insights.facts import MatchContext, history_facts, tool_results_by_query
from matchcut_insights.verify import Verdict, verify_line, verify_translation

MAX_DRAFTS = 2


# ---------------------------------------------------------------- messages


@dataclass
class MomentJob:
    moment: Moment
    facts: list[Fact]


@dataclass
class Analysis:
    note: AnalystNote


@dataclass
class History:
    facts: list[Fact]
    rejected: list[str]


@dataclass
class Draft:
    job: MomentJob
    facts: list[Fact]
    note: AnalystNote
    line: Line
    attempt: int
    history_accepted: int = 0
    history_rejected: list[str] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)


@dataclass
class Revision:
    draft: Draft
    feedback: str


@dataclass
class Approved:
    draft: Draft
    verdict: Verdict


@dataclass
class Outcome:
    """What the workflow decided for one moment."""

    draft: Draft
    verdict: Verdict
    translations: list[tuple[Translation, Verdict]] = field(default_factory=list)

    @property
    def verified(self) -> bool:
        return self.verdict.passed


# ---------------------------------------------------------------- executors


class Dispatch(Executor):
    @handler
    async def start(self, job: MomentJob, ctx: WorkflowContext[MomentJob]) -> None:
        await ctx.send_message(job)


class AnalystStep(Executor):
    def __init__(self, brain: Brain):
        super().__init__(id="analyst")
        self.brain = brain

    @handler
    async def run(self, job: MomentJob, ctx: WorkflowContext[Analysis | History]) -> None:
        await ctx.send_message(Analysis(await self.brain.analyse(job.moment, job.facts)))


class HistorianStep(Executor):
    def __init__(self, brain: Brain, match: MatchContext):
        super().__init__(id="historian")
        self.brain, self.match = brain, match

    @handler
    async def run(self, job: MomentJob, ctx: WorkflowContext[Analysis | History]) -> None:
        note, raw = await self.brain.recall(job.moment, self.match)
        claims = ((c.label, c.value, c.query_id) for c in (note or HistoryNote(claims=[])).claims)
        grounded, rejected = history_facts(claims, tool_results_by_query(raw))
        await ctx.send_message(History(grounded, rejected))


class WriterStep(Executor):
    def __init__(self, brain: Brain):
        super().__init__(id="writer")
        self.brain = brain
        self.job: MomentJob | None = None

    def bind(self, job: MomentJob) -> None:
        self.job = job

    @handler
    async def first_draft(self, parts: list[Analysis | History], ctx: WorkflowContext[Draft]) -> None:
        assert self.job is not None
        note = next((p.note for p in parts if isinstance(p, Analysis)), AnalystNote(points=[]))
        history = next((p for p in parts if isinstance(p, History)), History([], []))
        facts = self.job.facts + history.facts
        line = await self.brain.write(self.job.moment, facts, note, None)
        await ctx.send_message(Draft(self.job, facts, note, line, 1, len(history.facts), history.rejected))

    @handler
    async def revise(self, rev: Revision, ctx: WorkflowContext[Draft]) -> None:
        d = rev.draft
        line = await self.brain.write(d.job.moment, d.facts, d.note, rev.feedback)
        await ctx.send_message(
            Draft(
                d.job,
                d.facts,
                d.note,
                line,
                d.attempt + 1,
                d.history_accepted,
                d.history_rejected,
                d.problems,
            )
        )


class VerifierStep(Executor):
    """Deterministic: no model judges another model here."""

    def __init__(self, match: MatchContext):
        super().__init__(id="verifier")
        self.names = match.names()

    @handler
    async def check(self, draft: Draft, ctx: WorkflowContext[Revision | Approved, Outcome]) -> None:
        line = draft.line
        verdict = verify_line(line.text, line.cited_fact_ids, draft.facts, self.names, line.number_refs())
        if verdict.passed:
            await ctx.send_message(Approved(draft, verdict))
            return
        draft.problems += verdict.problems
        if draft.attempt < MAX_DRAFTS:
            await ctx.send_message(Revision(draft, "; ".join(verdict.problems)))
        else:
            await ctx.yield_output(Outcome(draft, verdict))


class LocaliserStep(Executor):
    def __init__(self, brain: Brain, match: MatchContext, languages: list[str]):
        super().__init__(id="localiser")
        self.brain, self.languages, self.names = brain, languages, match.names()

    @handler
    async def localise(self, ok: Approved, ctx: WorkflowContext[Never, Outcome]) -> None:
        checked: list[tuple[Translation, Verdict]] = []
        if self.languages:
            for tr in await self.brain.translate(ok.draft.line.text, self.languages):
                checked.append((tr, verify_translation(ok.draft.line.text, tr.text, self.names)))
        await ctx.yield_output(Outcome(ok.draft, ok.verdict, checked))


# ---------------------------------------------------------------- graph


def build_workflow(brain: Brain, match: MatchContext, languages: list[str], job: MomentJob) -> Workflow:
    dispatch = Dispatch(id="dispatch")
    analyst, historian = AnalystStep(brain), HistorianStep(brain, match)
    writer, verifier = WriterStep(brain), VerifierStep(match)
    localiser = LocaliserStep(brain, match, languages)
    writer.bind(job)
    return (
        WorkflowBuilder(start_executor=dispatch, name="matchcut-insights", max_iterations=20)
        .add_fan_out_edges(dispatch, [analyst, historian])
        .add_fan_in_edges([analyst, historian], writer)
        .add_edge(writer, verifier)
        .add_edge(verifier, writer, condition=lambda m: isinstance(m, Revision))
        .add_edge(verifier, localiser, condition=lambda m: isinstance(m, Approved))
        .build()
    )
