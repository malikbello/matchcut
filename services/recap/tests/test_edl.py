import itertools
from pathlib import Path

from matchcut_recap.edl import END_S, MAX_FILM_S, RUN_UP_S, TITLE_S, build_cut, frames, pick_moments
from matchcut_recap.mix import mix_command

FEED = {
    "match_id": "kes-wcr-7",
    "slots": ["KES"] * 11 + ["WCR"] * 11,
    "players": {"p9": {"num": 9, "name": "Quinouani"}, "p20": {"num": 20, "name": "Obeiuwa"}},
    "teams": {
        "home": {
            "id": "KES",
            "code": "KES",
            "name": "Kestrel Bay FC",
            "players": {"9": {"num": 9, "name": "Quinouani"}},
        },
        "away": {
            "id": "WCR",
            "code": "WCR",
            "name": "Westcroft United",
            "players": {"20": {"num": 20, "name": "Obeiuwa"}},
        },
    },
    "t": [0, 5_400_000],
    "goals": [
        {"t": 1_000_000, "side": "home"},
        {"t": 2_000_000, "side": "away"},
        {"t": 3_000_000, "side": "home"},
    ],
    "events": [
        [1_000_000, "goal", 9, "", "", 0, 0, -1, -1, -1],
        [2_000_000, "goal", 20, "", "", 0, 0, -1, -1, -1],
        [3_000_000, "goal", 9, "", "", 0, 0, -1, -1, -1],
    ],
    "changes": [],
}


def _cue(t: int, kind: str, club: str, player: str, audio: str | None = None) -> dict:
    return {
        "t_ms": t,
        "kind": kind,
        "status": "verified",
        "audio": audio,
        "facts": [{"label": "club involved", "value": club}, {"label": "player involved", "value": player}],
    }


CUES = [
    _cue(1_000_500, "goal", "Kestrel Bay FC", "Quinouani", "audio/m/CU-00001-en.mp3"),
    _cue(1_500_000, "big_chance", "Kestrel Bay FC", "Quinouani", "audio/m/CU-00002-en.mp3"),
    _cue(2_500_000, "great_save", "Westcroft United", "Obeiuwa"),
]
CALLS = [
    {"t_ms": 998_000, "kind": "build", "audio": "audio/m/CA-00001-en.mp3"},
    {"t_ms": 1_000_000, "kind": "goal", "audio": "audio/m/CA-00002-en.mp3"},
]
PACKAGES = {1_000_000: 27.0, 2_000_000: 27.0, 3_000_000: 27.0}


def test_a_fan_gets_his_goals_with_packages_and_conceded_goals_briefly():
    picks = pick_moments(FEED, CUES, {"side": "home"})
    assert [p["kind"] for p in picks] == ["goal", "chance", "conceded", "goal"]
    assert picks[0]["who"] == "Quinouani"


def test_a_player_cut_follows_only_that_player():
    picks = pick_moments(FEED, CUES, {"player": "Obeiuwa"})
    assert [p["kind"] for p in picks] == ["goal", "chance"]


def test_the_cut_is_a_film_with_title_and_end_cards_within_budget():
    cut = build_cut(
        FEED,
        CUES,
        CALLS,
        focus={"side": "home"},
        language="en",
        aspect="9x16",
        package_durations=PACKAGES,
        clip_durations={},
    )
    kinds = [s.kind for s in cut.segments]
    assert kinds[0] == "card"
    assert kinds[-1] == "card"
    assert kinds.count("package") == 2  # our two goals, not the one conceded
    assert cut.duration <= MAX_FILM_S
    assert "2-1" in cut.segments[-1].title
    assert cut.segments[0].duration == TITLE_S
    assert cut.segments[-1].duration == END_S


def test_voice_lines_land_where_they_happen_and_never_overlap():
    durations = {
        "audio/m/CA-00001-en.mp3": 1.8,
        "audio/m/CA-00002-en.mp3": 1.2,
        "audio/m/CU-00001-en.mp3": 4.0,
    }
    cut = build_cut(
        FEED,
        CUES,
        CALLS,
        focus={"side": "home"},
        language="en",
        aspect="16x9",
        package_durations=PACKAGES,
        clip_durations=durations,
    )
    voices = [a for a in cut.audio if a.role != "roar"]
    build = next(a for a in voices if a.file.endswith("CA-00001-en.mp3"))
    assert abs(build.at - (TITLE_S + RUN_UP_S - 2.0)) < 0.01  # two seconds before the goal in the run-up
    for a, b in itertools.pairwise(voices):
        assert b.at >= a.at + a.duration  # one voice at a time
    roars = [a for a in cut.audio if a.role == "roar"]
    assert len(roars) == 2
    assert abs(roars[0].at - (TITLE_S + RUN_UP_S)) < 0.01


def test_every_frame_has_a_render_spec():
    cut = build_cut(
        FEED,
        CUES,
        CALLS,
        focus={"side": "home"},
        language="en",
        aspect="9x16",
        package_durations=PACKAGES,
        clip_durations={},
    )
    specs = frames(cut, 30)
    assert len(specs) == sum(round(s.duration * 30) for s in cut.segments)
    assert specs[0]["kind"] == "card"
    assert any(s["kind"] == "package" for s in specs)
    live = [s for s in specs if s["kind"] == "live"]
    assert all(b["t"] >= a["t"] for a, b in itertools.pairwise(live) if b["t"] - a["t"] < 1000)


def test_the_mix_ducks_the_crowd_under_the_voice_and_normalises_loudness():
    cut = build_cut(
        FEED,
        CUES,
        CALLS,
        focus={"side": "home"},
        language="en",
        aspect="9x16",
        package_durations=PACKAGES,
        clip_durations={"audio/m/CA-00002-en.mp3": 1.2},
    )
    cmd = mix_command(cut, Path("media"), Path("crowd"), Path("out.m4a"))
    graph = cmd[cmd.index("-filter_complex") + 1]
    assert "sidechaincompress" in graph
    assert "loudnorm=I=-16" in graph
    assert graph.count("adelay") == len(cut.audio)


def test_cards_lead_with_the_fan_and_speak_their_language():
    kwargs = {"aspect": "9x16", "package_durations": PACKAGES, "clip_durations": {}}
    fr = build_cut(FEED, CUES, CALLS, focus={"player": "Quinouani"}, language="fr", **kwargs)
    assert fr.segments[0].title == "Quinouani"
    assert "Votre résumé" in fr.segments[0].sub
    assert fr.segments[-1].title.startswith("Fin du match")
    pcm = build_cut(FEED, CUES, CALLS, focus={"side": "away"}, language="pcm", **kwargs)
    assert pcm.segments[0].title == "Westcroft United"
    assert pcm.segments[0].sub.startswith("v Kestrel Bay FC")
    assert pcm.segments[-1].title.startswith("Full time")  # Nigerian captions use the English cards


def test_the_mix_states_its_output_format_for_older_ffmpeg():
    cut = build_cut(
        FEED, CUES, CALLS, focus={"side": "home"}, language="en", aspect="9x16",
        package_durations=PACKAGES, clip_durations={},
    )  # fmt: skip
    graph = mix_command(cut, Path("media"), Path("crowd"), Path("out.m4a"))
    out = next(x for x in graph if "[out]" in x and "loudnorm" in x)
    assert "aformat=sample_fmts=fltp:channel_layouts=stereo[out]" in out  # ffmpeg 5.1 (Debian 12) needs it
