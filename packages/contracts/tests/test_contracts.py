import pytest
from matchcut_contracts import EventType, MatchEvent, Outcome
from matchcut_contracts.export import MODELS, main
from pydantic import ValidationError


def _event(**overrides):
    base = {
        "match_id": "kes-irv-7",
        "event_id": "EV-00001",
        "seq": 1,
        "period": 1,
        "t_ms": 0,
        "clock": "0:00",
        "type": EventType.PASS,
        "team_id": "kes",
        "player_id": "kes-08",
        "x": 52.5,
        "y": 34.0,
        "end_x": 60.0,
        "end_y": 30.0,
        "attacking_right": True,
        "outcome": Outcome.SUCCESS,
    }
    base.update(overrides)
    return MatchEvent(**base)


def test_valid_event_round_trips():
    ev = _event()
    assert MatchEvent.model_validate_json(ev.model_dump_json()) == ev


@pytest.mark.parametrize(
    "bad",
    [
        {"event_id": "E-1"},
        {"x": 106.0},
        {"y": -1.0},
        {"clock": "45"},
        {"end_x": 60.0, "end_y": None},
        {"unknown_field": 1},
    ],
)
def test_invalid_events_are_rejected(bad):
    with pytest.raises(ValidationError):
        _event(**bad)


def test_stoppage_clock_is_valid():
    assert _event(clock="45:00+2").clock == "45:00+2"


def test_contracts_are_immutable():
    ev = _event()
    with pytest.raises(ValidationError):
        ev.x = 1.0  # type: ignore[misc]


def test_schema_export_and_check(tmp_path):
    assert main([str(tmp_path)]) == 0
    assert len(list(tmp_path.glob("*.schema.json"))) == len(MODELS)
    assert main([str(tmp_path), "--check"]) == 0
    (tmp_path / "club.schema.json").write_text("{}", encoding="utf-8")
    assert main([str(tmp_path), "--check"]) == 1
