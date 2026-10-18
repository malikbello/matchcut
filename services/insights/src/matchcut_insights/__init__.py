"""Matchcut live insights: code computes the facts, agents explain them, code verifies every line."""

from matchcut_insights.facts import MatchContext, build_facts, history_facts, tool_results_by_query
from matchcut_insights.pipeline import InsightsPipeline, MomentReport
from matchcut_insights.plain import plain_card
from matchcut_insights.verify import Verdict, verify_line, verify_translation

__all__ = [
    "InsightsPipeline",
    "MatchContext",
    "MomentReport",
    "Verdict",
    "build_facts",
    "history_facts",
    "plain_card",
    "tool_results_by_query",
    "verify_line",
    "verify_translation",
]
