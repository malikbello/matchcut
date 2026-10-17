"""Deterministic football analytics on Matchcut contracts.

Depends only on ``matchcut_contracts``: the same code runs on synthetic data and
on a licensed real-world feed.
"""

from matchcut_analytics.geometry import expected_goals, in_box, to_attacking
from matchcut_analytics.moments import MomentDetector, score_tactical_detection
from matchcut_analytics.state import MatchState
from matchcut_analytics.xt import XTModel, train

__all__ = [
    "MatchState",
    "MomentDetector",
    "XTModel",
    "expected_goals",
    "in_box",
    "score_tactical_detection",
    "to_attacking",
    "train",
]
