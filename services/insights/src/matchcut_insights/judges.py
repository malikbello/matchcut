"""Microsoft's model-graded evaluators (Azure AI Evaluation) on verified lines.

Our Verifier is deterministic and decides what airs. These evaluators add an
independent, industry-standard second opinion for the scorecard: groundedness
(is every claim supported by the facts given?) and relevance (does the line say
something that matters about this moment?). Scores run 1 to 5; the library's
default pass threshold is 3. Keyless: the judge model is our own Foundry
deployment, reached with Entra ID.
"""

from __future__ import annotations

import os
import statistics
from collections.abc import Sequence
from dataclasses import dataclass

from matchcut_contracts import Cue


@dataclass
class JudgeScores:
    lines: int
    groundedness_mean: float
    groundedness_pass: float
    relevance_mean: float
    relevance_pass: float


def _context(cue: Cue) -> str:
    return "\n".join(f"{f.fact_id}: {f.label} = {f.value}" for f in cue.facts)


def judge_lines(cues: Sequence[Cue]) -> JudgeScores:
    from azure.ai.evaluation import (  # noqa: PLC0415  # pyright: ignore[reportMissingImports] - optional "evals" extra
        AzureOpenAIModelConfiguration,
        GroundednessEvaluator,
        RelevanceEvaluator,
    )
    from azure.identity import DefaultAzureCredential  # noqa: PLC0415 - only needed with the extra

    config = AzureOpenAIModelConfiguration(
        azure_deployment=os.environ.get("AZURE_OPENAI_MODEL", "gpt-5-mini"),
        azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
        api_version=os.environ.get("AZURE_OPENAI_API_VERSION", "2025-04-01-preview"),
    )
    credential = DefaultAzureCredential()
    grounded = GroundednessEvaluator(config, credential=credential, is_reasoning_model=True)
    relevant = RelevanceEvaluator(config, credential=credential, is_reasoning_model=True)
    g_scores: list[float] = []
    r_scores: list[float] = []
    for cue in cues:
        query = f"Write one broadcast line for this {cue.kind.value.replace('_', ' ')} at {cue.clock}."
        g = grounded(query=query, context=_context(cue), response=cue.text)
        r = relevant(query=query, response=cue.text)
        g_scores.append(float(g["groundedness"]))
        r_scores.append(float(r["relevance"]))
    if not cues:
        return JudgeScores(0, 0.0, 0.0, 0.0, 0.0)
    return JudgeScores(
        lines=len(cues),
        groundedness_mean=statistics.fmean(g_scores),
        groundedness_pass=sum(s >= 3 for s in g_scores) / len(g_scores),
        relevance_mean=statistics.fmean(r_scores),
        relevance_pass=sum(s >= 3 for s in r_scores) / len(r_scores),
    )
