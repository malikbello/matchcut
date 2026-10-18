"""Matchcut data contracts.

Every service exchanges these models. JSON Schema files are generated from them
(`python -m matchcut_contracts.export`) and CI fails if the committed schemas drift.
"""

from matchcut_contracts.models import (
    SCHEMA_VERSION,
    BodyPart,
    Club,
    EventType,
    Foot,
    Kit,
    MatchEvent,
    MatchMeta,
    Moment,
    MomentKind,
    Outcome,
    Player,
    Position,
    TeamStyle,
    TrackingFrame,
    TruthRecord,
)

__all__ = [
    "SCHEMA_VERSION",
    "BodyPart",
    "Club",
    "EventType",
    "Foot",
    "Kit",
    "MatchEvent",
    "MatchMeta",
    "Moment",
    "MomentKind",
    "Outcome",
    "Player",
    "Position",
    "TeamStyle",
    "TrackingFrame",
    "TruthRecord",
]
