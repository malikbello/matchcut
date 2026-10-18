import warnings

import cdf
import pytest
from matchcut_sim import build_league, simulate_match
from matchcut_sim.cdf import CDF_VERSION, cdf_position, export_cdf
from matchcut_sim.cli import main


@pytest.fixture(scope="module")
def exported(tmp_path_factory):
    league = build_league()
    ids = [c.club_id for c in league.clubs]
    m = simulate_match(league, ids[0], ids[1], seed=11, half_minutes=6)
    return m, export_cdf(m, league, tmp_path_factory.mktemp("cdf"), every=5)


@pytest.mark.parametrize(
    ("validator", "name", "kwargs"),
    [
        (cdf.MatchSchemaValidator, "match.json", {}),
        (cdf.MetaSchemaValidator, "meta.json", {}),
        (cdf.EventSchemaValidator, "event.jsonl", {"limit": 100_000}),
        (cdf.TrackingSchemaValidator, "tracking.jsonl", {"limit": 100_000}),
    ],
)
def test_export_passes_the_official_validator_strictly(exported, validator, name, kwargs):
    _, folder = exported
    with warnings.catch_warnings():
        warnings.simplefilter("error")  # unknown fields fail too
        validator().validate_schema(sample=str(folder / name), mode="strict", **kwargs)


def test_validator_and_export_agree_on_the_version():
    assert cdf.VERSION == CDF_VERSION


def test_positions_are_side_specific():
    league = build_league()
    positions = {cdf_position(p) for p in league.players}
    assert positions <= {"GK", "LB", "CB", "RB", "CDM", "CM", "CAM", "LW", "RW", "CF"}
    assert {"LB", "RB", "CF"} <= positions


def test_cli_exports(tmp_path, capsys):
    main(["cdf", "--home", "kes", "--away", "irv", "--seed", "3", "--every", "50", "--out", str(tmp_path)])
    assert "CDF" in capsys.readouterr().out
    assert any(tmp_path.rglob("tracking.jsonl"))
