"""The agents: Analyst, Historian, Writer and Localiser on Microsoft Agent Framework.

Each agent returns typed output (Pydantic models as structured outputs). The
Historian reaches League Memory through MCP and every answer it receives is
captured, so its claims can be grounded against what the tools really said.
The pipeline depends only on the ``Brain`` protocol, so tests run a scripted
brain with no network or credentials.
"""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Sequence
from typing import Any, Protocol, Self

from agent_framework import Agent, MCPStdioTool
from agent_framework.openai import OpenAIChatCompletionClient
from azure.identity import DefaultAzureCredential
from matchcut_contracts import Fact, Moment
from pydantic import BaseModel, Field

from matchcut_insights.facts import MatchContext
from matchcut_insights.languages import LANGUAGES

# ---------------------------------------------------------------- typed outputs


class NotePoint(BaseModel):
    text: str = Field(description="One short analytical observation")
    fact_ids: list[str] = Field(description="Fact IDs this observation rests on")


class AnalystNote(BaseModel):
    points: list[NotePoint] = Field(max_length=2)


class HistoryClaim(BaseModel):
    label: str = Field(description="What the value means, in plain words")
    value: str | int | float = Field(description="Copied exactly from the League Memory answer")
    query_id: str = Field(description="The query_id of the League Memory answer it came from")


class HistoryNote(BaseModel):
    claims: list[HistoryClaim] = Field(max_length=3)


class NumberRef(BaseModel):
    text: str = Field(description="A number exactly as written in the line, e.g. '0.92' or '51'")
    fact_id: str = Field(description="The fact that states this number")


class Line(BaseModel):
    text: str = Field(description="One broadcast line")
    cited_fact_ids: list[str] = Field(description="Every fact ID the line uses")
    numbers: list[NumberRef] = Field(
        default_factory=list, description="Every number in the line, in order of appearance, with its fact"
    )

    def number_refs(self) -> list[tuple[str, str]]:
        return [(n.text, n.fact_id) for n in self.numbers]


class Translation(BaseModel):
    language: str = Field(description="The language tag exactly as requested, e.g. 'en-NG', 'pcm', 'yo'")
    text: str


class Translations(BaseModel):
    items: list[Translation]


class Brain(Protocol):
    async def analyse(self, moment: Moment, facts: Sequence[Fact]) -> AnalystNote: ...

    async def recall(self, moment: Moment, ctx: MatchContext) -> tuple[HistoryNote, list[str]]: ...

    async def write(
        self, moment: Moment, facts: Sequence[Fact], note: AnalystNote, feedback: str | None
    ) -> Line: ...

    async def translate(self, text: str, languages: Sequence[str]) -> list[Translation]: ...


# ---------------------------------------------------------------- instructions

ANALYST = """You are the Analyst in a live football broadcast team. You get one moment and its
fact sheet. Say at most two short things about why the moment matters (game state,
pressure, chance quality, tactics). Use only the facts given and cite their IDs.
Never compute or estimate a new number."""

HISTORIAN = """You are the Historian. You have League Memory tools over five seasons of league
history. For the moment given, call the one or two tools most likely to add history
that matters now (a milestone, a drought ended, a run of form, a rivalry record).
Then return at most three claims. Each value must be ONE number or short text copied
exactly from a single field of the answer (never a list or an object), with the
query_id of that answer. If nothing is notable, return no claims."""

WRITER = """You are the Writer, the voice of the on-screen graphics. Write ONE line, 25 words or
fewer, British English, vivid but factual. Rules that are checked by code:
- every number you write must appear, exactly as given, in a fact you cite;
- every name you write must appear in a fact you cite;
- keep the unit a fact's label gives (percent, km/h);
- fans hear this line, so never write "xG", "expected goals" or a decimal for chance
  quality: say it as fans do, using the chance fact ("a chance that goes in 9 times in 10",
  "the sort scored once in every 20 attempts"), with the digits exactly as given;
- cite the ID of every fact you use, and only IDs from the fact sheet;
- list every number you write, in order, with the ID of the fact that states it
  (a score like 2-1 is one entry);
- no betting language and no league or brand names;
- no em dashes: use a colon, comma or full stop.
Lead with what fans cannot see on the screen: when the sheet has a league history fact
(marked [league history]) that is news (which goal of his season or career this is, a
milestone, a drought ended, a first, a run of form), build the line around it, adding chance
quality or another match fact only if it still fits; a bare count (how many times two clubs
have met, appearances so far) is not news on its own. Otherwise
prefer one striking fact a fan would care about (chance quality, top speed, a run of form)
over many, and over abstract indices such as momentum. Use a shirt number only when it
adds something. If feedback from the Verifier is given, fix exactly those problems."""

LOCALISER = """You are the Localiser. Write the broadcast line in each requested language for
on-screen graphics and spoken commentary, natural to football fans who speak it. Follow
the style given for each language. Rules checked by code:
- keep every number exactly as written, in Western digits (0-9), in every language;
- keep every player and club name exactly as written, in Latin script, in every language;
- do not add or remove information;
- never use em dashes.
Return each item with the exact language tag you were given."""


def _facts_block(facts: Sequence[Fact]) -> str:
    """The fact sheet as the agents read it; grounded League Memory facts are marked."""
    mark = {"league_memory": " [league history]"}
    return "\n".join(f"{f.fact_id}: {f.label} = {f.value}{mark.get(f.source, '')}" for f in facts)


def _moment_block(moment: Moment) -> str:
    return f"Moment {moment.moment_id}: {moment.kind.value} at {moment.clock}"


# ---------------------------------------------------------------- Agent Framework brain


class AgentBrain:
    """Production brain: Foundry-hosted model, keyless (Entra ID), League Memory over MCP."""

    def __init__(self, client: Any, memory_tool: Any | None = None, reasoning_effort: str = "low"):
        self._memory_tool = memory_tool
        self._options: dict[str, Any] = {"reasoning_effort": reasoning_effort}
        self.analyst = Agent(client, ANALYST, name="Analyst")
        self.historian = Agent(
            client, HISTORIAN, name="Historian", tools=[memory_tool] if memory_tool else None
        )
        self.writer = Agent(client, WRITER, name="Writer")
        self.localiser = Agent(client, LOCALISER, name="Localiser")
        self.usage: list[dict[str, Any]] = []

    @classmethod
    def from_env(cls, memory_db: str | None = None) -> AgentBrain:
        """Build from AZURE_OPENAI_ENDPOINT / AZURE_OPENAI_MODEL with DefaultAzureCredential."""
        client = OpenAIChatCompletionClient(
            model=os.environ.get("AZURE_OPENAI_MODEL", "gpt-5-mini"),
            azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
            credential=DefaultAzureCredential(),
        )
        tool = None
        if memory_db:
            tool = MCPStdioTool(
                name="league_memory",
                command=sys.executable,  # same interpreter: no PATH lookup, works in any container
                args=["-m", "matchcut_memory.server", "--db", memory_db],
                description="League Memory: read-only history of the league",
                approval_mode="never_require",
            )
        return cls(client, tool)

    async def __aenter__(self) -> Self:
        if self._memory_tool is not None:
            await self._memory_tool.__aenter__()
        return self

    async def __aexit__(self, *exc: object) -> None:
        if self._memory_tool is not None:
            await self._memory_tool.__aexit__(*exc)

    async def _run(self, agent: Any, prompt: str, schema: type[BaseModel]) -> Any:
        response = await agent.run(prompt, options={"response_format": schema, **self._options})
        if response.usage_details:
            self.usage.append({"agent": agent.name, **dict(response.usage_details)})
        return response

    async def analyse(self, moment: Moment, facts: Sequence[Fact]) -> AnalystNote:
        r = await self._run(
            self.analyst, f"{_moment_block(moment)}\nFacts:\n{_facts_block(facts)}", AnalystNote
        )
        return r.value

    async def recall(self, moment: Moment, ctx: MatchContext) -> tuple[HistoryNote, list[str]]:
        if self._memory_tool is None:
            return HistoryNote(claims=[]), []
        player = ctx.players.get(moment.player_id or "")
        is_home = moment.team_id == ctx.home.club_id
        home, away = ctx.home, ctx.away
        prompt = (
            f"{_moment_block(moment)}\n"
            f"Home club ID: {home.club_id} ({home.name}); away club ID: {away.club_id} ({away.name}).\n"
        )
        if player:
            venue = "at home" if is_home else "away"
            prompt += f"Player: {player.known_as}, ID {player.player_id}, playing {venue}.\n"
        r = await self._run(self.historian, prompt, HistoryNote)
        raw = [
            c.result if isinstance(c.result, str) else json.dumps(c.result)
            for m in r.messages
            for c in m.contents
            if c.type == "function_result" and c.result is not None
        ]
        return r.value, raw

    async def write(
        self, moment: Moment, facts: Sequence[Fact], note: AnalystNote, feedback: str | None
    ) -> Line:
        analysis = "\n".join(f"- {p.text} [{', '.join(p.fact_ids)}]" for p in note.points)
        prompt = (
            f"{_moment_block(moment)}\nFacts:\n{_facts_block(facts)}\nAnalyst notes:\n{analysis or '- none'}"
        )
        if feedback:
            prompt += f"\nVerifier feedback on your previous line: {feedback}"
        r = await self._run(self.writer, prompt, Line)
        return r.value

    async def translate(self, text: str, languages: Sequence[str]) -> list[Translation]:
        wanted = "\n".join(
            f"- {tag}: {LANGUAGES[tag].name}. Style: {LANGUAGES[tag].style}"
            for tag in languages
            if tag in LANGUAGES
        )
        r = await self._run(self.localiser, f"Languages:\n{wanted}\nLine: {text}", Translations)
        return r.value.items
