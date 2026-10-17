import json

from matchcut_sim.cli import main


def test_league_command_writes_universe(tmp_path):
    main(["league", "--out", str(tmp_path)])
    clubs = json.loads((tmp_path / "clubs.json").read_text(encoding="utf-8"))
    seasons = json.loads((tmp_path / "seasons.json").read_text(encoding="utf-8"))
    assert len(clubs) == 20
    assert len(seasons) == 6  # five past seasons plus the current one
    assert (tmp_path / "transfers.json").exists()


def test_analyse_command_replays_a_short_match(capsys):
    main(["analyse", "--half-minutes", "3", "--min-importance", "0"])
    out = capsys.readouterr().out
    assert "snapshot:" in out
    assert "tactical detection vs truth:" in out
