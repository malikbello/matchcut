"""Core data contracts (schema version 1).

Coordinate frame (all positions, metres):
    Pitch is 105 m x 68 m. Origin (0, 0) is the corner to the left of the camera
    at the home team's first-half goal line. x runs along the touchline (0..105),
    y runs across the pitch (0..68). The home team attacks +x in the first half
    and -x in the second half. ``MatchEvent.attacking_right`` records direction
    so consumers never have to infer it.

Time:
    ``t_ms`` is milliseconds since kick-off on one continuous timeline (stoppage
    time included). It is the key that synchronises events, tracking, video
    timecode and on-screen cues. ``clock`` is the broadcast clock string.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

SCHEMA_VERSION = "1.0.0"
PITCH_LENGTH_M = 105.0
PITCH_WIDTH_M = 68.0


class _Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)


# ---------------------------------------------------------------- league


class Position(StrEnum):
    GK = "GK"
    CB = "CB"
    FB = "FB"
    DM = "DM"
    CM = "CM"
    AM = "AM"
    W = "W"
    ST = "ST"


class Foot(StrEnum):
    LEFT = "left"
    RIGHT = "right"


class Kit(_Contract):
    primary: str = Field(pattern=r"^#[0-9A-F]{6}$", description="Shirt colour")
    secondary: str = Field(pattern=r"^#[0-9A-F]{6}$", description="Trim and shorts")
    number: str = Field(pattern=r"^#[0-9A-F]{6}$", description="Shirt number colour")


class TeamStyle(_Contract):
    """Tactical identity in 0..1. Drives the match engine and is part of the hidden truth."""

    press_intensity: float = Field(ge=0, le=1)
    directness: float = Field(ge=0, le=1)
    width: float = Field(ge=0, le=1)
    tempo: float = Field(ge=0, le=1)
    defensive_line: float = Field(ge=0, le=1, description="0 = deep block, 1 = high line")
    risk: float = Field(ge=0, le=1, description="Appetite for forward, low-percentage passes")


class Club(_Contract):
    club_id: str = Field(pattern=r"^[a-z]{3}$")
    name: str
    short_name: str = Field(pattern=r"^[A-Z]{3}$")
    city: str
    ground: str
    founded: int = Field(ge=1860, le=2020)
    home_kit: Kit
    away_kit: Kit
    style: TeamStyle
    rating: int = Field(ge=40, le=95, description="Overall squad strength")
    formation: Literal["4-3-3", "4-2-3-1", "4-4-2", "3-4-3", "5-3-2"]


class Player(_Contract):
    player_id: str = Field(pattern=r"^[a-z]{3}-\d{2}$", description="<club_id>-<shirt number>")
    club_id: str
    name: str
    known_as: str = Field(description="Name used on screen, usually the surname")
    shirt_number: int = Field(ge=1, le=99)
    position: Position
    foot: Foot
    birth_year: int = Field(ge=1980, le=2010)
    pace: int = Field(ge=1, le=99)
    passing: int = Field(ge=1, le=99)
    shooting: int = Field(ge=1, le=99)
    dribbling: int = Field(ge=1, le=99)
    defending: int = Field(ge=1, le=99)
    stamina: int = Field(ge=1, le=99)
    goalkeeping: int = Field(ge=1, le=99)


# ---------------------------------------------------------------- match


class MatchMeta(_Contract):
    schema_version: str = SCHEMA_VERSION
    match_id: str
    competition: str
    season: str
    matchday: int = Field(ge=1, le=38)
    home_club_id: str
    away_club_id: str
    ground: str
    seed: int
    home_formation: str
    away_formation: str
    home_lineup: list[str] = Field(min_length=11, max_length=11)
    away_lineup: list[str] = Field(min_length=11, max_length=11)
    home_bench: list[str]
    away_bench: list[str]
    synthetic: Literal[True] = True


class EventType(StrEnum):
    KICK_OFF = "kick_off"
    PASS = "pass"  # noqa: S105 - event type, not a credential
    CARRY = "carry"
    SHOT = "shot"
    SAVE = "save"
    GOAL = "goal"
    BLOCK = "block"
    TACKLE = "tackle"
    INTERCEPTION = "interception"
    CLEARANCE = "clearance"
    PRESSURE = "pressure"
    BALL_RECOVERY = "ball_recovery"
    POSSESSION_CHANGE = "possession_change"
    FOUL = "foul"
    CARD = "card"
    THROW_IN = "throw_in"
    CORNER = "corner"
    GOAL_KICK = "goal_kick"
    FREE_KICK = "free_kick"
    SUBSTITUTION = "substitution"
    PERIOD_START = "period_start"
    PERIOD_END = "period_end"


class Outcome(StrEnum):
    SUCCESS = "success"
    FAIL = "fail"


class BodyPart(StrEnum):
    LEFT_FOOT = "left_foot"
    RIGHT_FOOT = "right_foot"
    HEAD = "head"


class MatchEvent(_Contract):
    schema_version: str = SCHEMA_VERSION
    match_id: str
    event_id: str = Field(pattern=r"^EV-\d{5}$")
    seq: int = Field(ge=1)
    period: Literal[1, 2]
    t_ms: int = Field(ge=0, description="Milliseconds since kick-off on one continuous timeline")
    clock: str = Field(pattern=r"^\d{1,3}:\d{2}(\+\d{1,2})?$", description="Broadcast clock, e.g. 45:00+2")
    type: EventType
    team_id: str | None = None
    player_id: str | None = None
    x: float | None = Field(default=None, ge=0, le=105)
    y: float | None = Field(default=None, ge=0, le=68)
    end_x: float | None = Field(default=None, ge=0, le=105)
    end_y: float | None = Field(default=None, ge=0, le=68)
    attacking_right: bool | None = Field(default=None, description="True when team_id attacks +x")
    outcome: Outcome | None = None
    recipient_id: str | None = Field(default=None, description="Pass target or player fouled")
    under_pressure: bool | None = None
    ball_speed_kmh: float | None = Field(default=None, ge=0, le=160)
    body_part: BodyPart | None = None
    detail: str | None = Field(
        default=None,
        description="Small qualifier: yellow/red for cards, on/off for substitution, set-piece type",
    )
    related_event_id: str | None = None

    @model_validator(mode="after")
    def _end_needs_start(self) -> MatchEvent:
        if (self.end_x is None) != (self.end_y is None):
            raise ValueError("end_x and end_y must both be set or both be empty")
        if self.end_x is not None and self.x is None:
            raise ValueError("an end position needs a start position")
        return self


class PlayerPosition(_Contract):
    player_id: str
    team_id: str
    x: float = Field(ge=-5, le=110)
    y: float = Field(ge=-5, le=73)
    speed_mps: float = Field(ge=0, le=12.5)


class BallPosition(_Contract):
    x: float = Field(ge=-5, le=110)
    y: float = Field(ge=-5, le=73)
    z: float = Field(ge=0, le=40)


class TrackingFrame(_Contract):
    schema_version: str = SCHEMA_VERSION
    match_id: str
    t_ms: int = Field(ge=0)
    period: Literal[1, 2]
    ball: BallPosition
    players: list[PlayerPosition] = Field(min_length=14, max_length=22)


class TruthRecord(_Contract):
    """What really happened tactically. Hidden from every downstream service; used only to score them."""

    schema_version: str = SCHEMA_VERSION
    match_id: str
    t_ms: int = Field(ge=0)
    kind: Literal["tactic_change", "storyline", "fatigue", "shot_probability"]
    team_id: str | None = None
    player_id: str | None = None
    detail: dict[str, float | int | str | bool]
