import itertools
from pathlib import Path

from matchcut_editing.edl import (
    END_S,
    MAX_FILM_S,
    RUN_UP_S,
    TITLE_S,
    AudioEvent,
    Cut,
    Segment,
    build_cut,
    call_lines,
    clip_captions,
    clip_frames,
    clip_plan,
    frames,
    moment_cut,
    pick_moments,
    segments_for,
    slug,
    window_key,
)
from matchcut_editing.mix import mix_command

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
        "moment_id": f"MO-{t}",
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


def test_every_frame_names_its_caption_so_slices_render_alone():
    cut = build_cut(
        FEED, CUES, CALLS, focus={"side": "home"}, language="en", aspect="9x16",
        package_durations=PACKAGES, clip_durations={},
    )  # fmt: skip
    specs = frames(cut, 25)
    assert all("cue" in s and "cueAge" in s for s in specs)
    shown = [s for s in specs if s["cue"]]
    assert shown, "goals in the cut must carry their verified captions"
    assert all(s["kind"] != "card" for s in shown)  # cards stand alone
    # a goal's caption holds through its replay package (the analysis is voiced over it)
    first_pkg = next(i for i, s in enumerate(specs) if s["kind"] == "package")
    assert specs[first_pkg]["cue"]
    assert specs[first_pkg + 25 * 5]["cue"] == specs[first_pkg]["cue"]
    # ages grow by one frame at a time while a caption stays up
    for a, b in itertools.pairwise(specs):
        if a["cue"] and a["cue"] == b["cue"]:
            assert abs(b["cueAge"] - a["cueAge"] - 1 / 25) < 1e-3


# ---------------------------------------------------------------- reusable clips


def _cut(focus):
    return build_cut(
        FEED, CUES, CALLS, focus=focus, language="en", aspect="9x16",
        package_durations=PACKAGES, clip_durations={},
    )  # fmt: skip


def test_every_cut_is_exactly_its_clips_joined():
    plan = clip_plan(FEED, CUES, PACKAGES)
    for focus in ({"side": "home"}, {"side": "away"}, {"player": "Quinouani"}, {"player": "Obeiuwa"}):
        cut = _cut(focus)
        order = cut.clip_order()
        assert order[0].startswith("title-")
        assert order[-1] == "end"
        moments = [s for s in cut.segments if s.kind != "card"]
        from_plan = [seg for key in order[1:-1] for seg in plan[key]]
        assert moments == from_plan  # same segments, same timings: the cut is the clips joined


def test_frame_counts_add_up_so_joined_clips_match_the_plan():
    plan = clip_plan(FEED, CUES, PACKAGES)
    cut = _cut({"side": "home"})
    card_frames = sum(round(s.duration * 25) for s in cut.segments if s.kind == "card")
    clip_total = sum(len(clip_frames(plan[k], 25)) for k in cut.clip_order()[1:-1])
    assert card_frames + clip_total == len(frames(cut, 25))
    assert all(spec["cue"] is None for k in cut.clip_order()[1:-1] for spec in clip_frames(plan[k], 25))


def test_clip_captions_are_the_cut_captions_in_clip_time():
    plan = clip_plan(FEED, CUES, PACKAGES)
    cut = _cut({"side": "home"})
    at, shifted = TITLE_S, []
    for key in cut.clip_order()[1:-1]:
        shifted += [(a + at, b + at, m) for a, b, m in clip_captions(plan[key], CUES)]
        at += sum(s.duration for s in plan[key])
    assert [(round(a, 3), round(b, 3), m) for a, b, m in shifted] == [
        (round(a, 3), round(b, 3), m) for a, b, m in cut.captions
    ]


def test_every_goal_has_a_goal_and_a_conceded_clip_and_titles_are_keyed_by_focus():
    plan = clip_plan(FEED, CUES, PACKAGES)
    for g in FEED["goals"]:
        assert f"goal-{g['t']}" in plan
        assert f"conceded-{g['t']}" in plan
    assert _cut({"player": "Quinouani"}).clip_order()[0] == "title-quinouani"
    assert slug("Kestrel Bay FC") == "kestrel-bay-fc"


def test_a_single_moment_plays_as_its_own_film_from_the_same_clip():
    plan = clip_plan(FEED, CUES, PACKAGES)
    one = moment_cut(
        FEED, CUES, CALLS, "goal-1000000", language="en", aspect="9x16",
        package_durations=PACKAGES, clip_durations={},
    )  # fmt: skip
    assert one.segments == plan["goal-1000000"]  # the stored clip, nothing else: no cards
    assert one.clip_order() == ["goal-1000000"]
    assert any(e.role == "roar" for e in one.audio)  # the crowd erupts on the goal
    assert one.captions  # the verified line is on screen


def test_a_caption_that_would_flicker_never_airs_and_films_speak_one_language():
    live = [Segment("live", 10.0, t0=0, clip="goal-8000")]
    cues = [
        {"t_ms": 7800, "moment_id": "MO-1", "language": "en"},  # momentum, 0.2 s before the goal
        {"t_ms": 8000, "moment_id": "MO-2", "language": "fr"},
        {"t_ms": 8000, "moment_id": "MO-2", "language": "en"},
    ]
    fr = clip_captions(live, cues, "fr")
    assert [m for *_, m in fr] == ["MO-2"]  # the English momentum line never shows in a French film
    en = clip_captions(live, cues, "en")
    assert [m for *_, m in en] == ["MO-2"]  # and in English it would flash for 0.2 s: dropped
    assert [m for *_, m in clip_captions(live, cues, "pcm")] == ["MO-2"]  # Naija films read English lines


def test_the_call_owns_the_goal_and_the_analysis_owns_the_replay():
    cut = _cut({"side": "home"})
    goal_line = "audio/m/CU-00001-en.mp3"
    placed = [e for e in cut.audio if e.file == goal_line]
    assert len(placed) == 1
    package_at = next(
        sum(s.duration for s in cut.segments[:i]) for i, s in enumerate(cut.segments) if s.kind == "package"
    )
    assert placed[0].at >= package_at  # voiced over the replay, not on top of the goal call


def test_any_stretch_of_play_is_a_clip_with_its_own_sound():
    key = window_key(990_000, 1_001_500)
    assert key == "window-990000-1001500"
    segs = segments_for(key, PACKAGES)
    assert len(segs) == 1
    assert segs[0].duration == 11.5
    one = moment_cut(
        FEED, CUES, CALLS, key, language="en", aspect="9x16", package_durations=PACKAGES, clip_durations={}
    )
    assert one.clip_order() == [key]
    assert any(e.role == "call" for e in one.audio)  # the calls inside the window are voiced


def test_the_callers_words_are_on_screen_while_he_says_them():
    calls = [
        {"t_ms": 991_000, "audio": "audio/m/CD-00001-en.mp3", "text": "Quinouani sets off!"},
        {"t_ms": 992_000, "audio": "audio/m/CD-00002-en.mp3", "text": "Past one... past two!"},
        {"t_ms": 999_000, "audio": "audio/m/CA-00002-en.mp3", "text": "GOAL!"},
    ]
    durations = {
        "audio/m/CD-00001-en.mp3": 1.4,
        "audio/m/CD-00002-en.mp3": 1.6,
        "audio/m/CA-00002-en.mp3": 1.0,
    }
    one = moment_cut(
        FEED, CUES, calls, window_key(990_000, 1_001_500), language="en", aspect="9x16",
        package_durations=PACKAGES, clip_durations=durations,
    )  # fmt: skip
    lines = call_lines(one, calls)
    voiced = [e for e in one.audio if e.role == "call"]
    assert [a for a, _b, _t in lines] == [e.at for e in voiced]  # words and voice start together
    assert [t for *_, t in lines] == ["Quinouani sets off!", "Past one... past two!", "GOAL!"]
    first, second, last = lines
    assert first[1] <= second[0]  # the second call pushes the first line off, never on top of it
    assert second[1] >= second[0] + 1.6  # the line outlasts the voice
    assert last[1] - last[0] >= 2.0  # a short call is still readable
    assert all(b <= one.duration for _a, b, _t in lines)


def test_a_verified_caption_has_the_screen_over_a_call_line():
    cut = Cut("m", "en", "9x16", "", "", segments=[Segment("live", 12.0, t0=0)])
    cut.captions = [(6.0, 12.0, "MO-1")]
    cut.audio = [AudioEvent(4.5, "a.mp3", "call", 1.2), AudioEvent(7.0, "b.mp3", "call", 1.0)]
    calls = [{"audio": "a.mp3", "text": "Here comes Quinouani!"}, {"audio": "b.mp3", "text": "It's in!"}]
    # the first line gives way when the caption arrives; the second is heard over it, not shown
    assert call_lines(cut, calls) == [(4.5, 6.0, "Here comes Quinouani!")]


def test_the_master_is_measured_then_set_with_the_measurement():
    from matchcut_editing.mix import loudness_report  # noqa: PLC0415

    cut = build_cut(FEED, CUES, CALLS, focus={"side": "home"}, language="en", aspect="9x16",
                    package_durations=PACKAGES, clip_durations={})  # fmt: skip
    first = mix_command(cut, Path("media"), Path("crowd"), Path("out.m4a"), measure=True)
    assert first[-3:] == ["-f", "null", "-"]
    assert "print_format=json" in first[first.index("-filter_complex") + 1]
    log = """noise
[Parsed_loudnorm_0 @ 0x1]
{
 "input_i" : "-18.20",
 "input_tp" : "-4.10",
 "input_lra" : "3.40",
 "input_thresh" : "-28.50",
 "target_offset" : "0.20"
}
"""
    measured = loudness_report(log)
    assert measured == {
        "input_i": -18.2,
        "input_tp": -4.1,
        "input_lra": 3.4,
        "input_thresh": -28.5,
        "target_offset": 0.2,
    }
    second = mix_command(cut, Path("media"), Path("crowd"), Path("out.m4a"), measured=measured)
    graph = second[second.index("-filter_complex") + 1]
    assert "measured_I=-18.2:measured_TP=-4.1" in graph
    assert graph.count("linear=true") == 1
    assert second[-1] == "out.m4a"
    assert loudness_report(log.replace("-18.20", "-inf")) is None  # silence: one pass instead
    assert loudness_report("no report") is None


def test_no_voice_or_call_line_runs_over_a_cut():
    """A conceded clip is 6.5 s: the goal call near its end does not fit, so it is left out of the
    clip; a fan's film joining that clip to the next must leave it out too (it once voiced it over
    the next moment's pictures, with no line on screen, and the QA agent flagged every away film)."""
    from matchcut_editing.edl import AudioEvent, Cut, Segment, _voice_track, call_lines, clip_end  # noqa: PLC0415

    cut = Cut("kes-wcr-7", "en", "9x16", "x", "KES v WCR")
    cut.segments = [
        Segment("live", 3.5, t0=0, clip="conceded-1"),
        Segment("live", 3.0, t0=3500, clip="conceded-1"),
        Segment("live", 6.5, t0=20000, clip="conceded-2"),
    ]
    assert clip_end(cut, 1.0) == 6.5
    assert clip_end(cut, 6.5) == 13.0
    calls = [
        {"audio": "early.mp3", "t_ms": 1000, "text": "Here's Quinouani..."},
        {"audio": "late.mp3", "t_ms": 5000, "text": "Quinouani! What a finish!"},
    ]
    _voice_track(cut, [], [(0.0, 6.5, 0, 6500)], [], calls, {"early.mp3": 1.9, "late.mp3": 1.9})
    assert [e.file for e in cut.audio] == ["early.mp3"]  # 5.0 + 1.9 s would cross the cut at 6.5 s
    cut.audio.append(AudioEvent(5.9, "edge.mp3", "call", 0.5))
    lines = call_lines(cut, [*calls, {"audio": "edge.mp3", "text": "In!"}])
    assert all(end <= 6.5 for a, end, _t in lines if a < 6.5)


def test_the_describer_speaks_only_in_the_gaps_and_inside_its_clip():
    from matchcut_editing.edl import AudioEvent, Cut, Segment, _describe_track  # noqa: PLC0415

    cut = Cut("kes-wcr-7", "en", "9x16", "x", "KES v WCR")
    cut.segments = [
        Segment("live", 8.6, t0=0, clip="goal-8000"),
        Segment("live", 6.5, t0=20000, clip="conceded-25000"),
    ]
    cut.audio = [AudioEvent(6.0, "call.mp3", "call", 0.8)]  # the caller, 6.0 to 6.8 s
    windows = [(0.0, 8.6, 0.0, 8600.0), (8.6, 15.1, 20000.0, 26500.0)]
    descriptions = [
        {"t_ms": 300, "audio": "scene.mp3", "clip": "goal-8000"},  # opens the goal clip
        {"t_ms": 5900, "audio": "play.mp3"},  # would run into the call: waits for it
        {"t_ms": 20300, "audio": "other-scene.mp3", "clip": "goal-8000"},  # not this clip's line
        {"t_ms": 25500, "audio": "late.mp3"},  # would run over the end of the clip
    ]
    durations = {"scene.mp3": 2.5, "play.mp3": 0.6, "other-scene.mp3": 2.0, "late.mp3": 2.0}
    _describe_track(cut, [], windows, descriptions, durations)
    placed = {e.file: e.at for e in cut.audio if e.role == "describe"}
    assert placed == {"scene.mp3": 0.3, "play.mp3": 6.95}  # after the call (6.8 s) and a breath
