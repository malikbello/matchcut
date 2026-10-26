from matchcut_insights.describe import LANGS, Match, _metres_ar, colour_name, describe

HOME, AWAY = "kes", "wcr"


def _feed(events, goals=()):
    """A tiny match: home keeper (slot 0) defends x=0 in the first half; slots 1-2 home, 3-4 away."""
    n = 40
    t = [i * 1000 for i in range(n)]
    period = [1] * 20 + [2] * 20
    pos = [[25, 340, 500, 300, 520, 360, 600, 340, 1000, 340] for _ in range(n)]
    return {
        "t": t,
        "period": period,
        "p": pos,
        "b": [[525, 340, 0]] * n,
        "slots": [HOME, HOME, HOME, AWAY, AWAY],
        "keepers": [0, 4],
        "teams": {
            "home": {
                "id": HOME,
                "name": "Kestrel Bay FC",
                "kit": {"primary": "#E8B422"},
                "players": {"0": {"name": "Keeper"}, "1": {"name": "Quinouani"}, "2": {"name": "Pelador"}},
            },
            "away": {
                "id": AWAY,
                "name": "Westcroft United",
                "kit": {"primary": "#5B2C83"},
                "players": {"3": {"name": "Toriez"}, "4": {"name": "Okueto"}},
            },
        },
        "players": {},
        "changes": [],
        "goals": list(goals),
        "events": events,
    }


def test_kits_are_named_as_a_listener_would_say_them():
    assert colour_name("#E8B422") == "yellow"
    assert colour_name("#5B2C83") == "purple"
    assert colour_name("#FFFFFF") == "white"


def test_arabic_counts_metres_with_the_right_noun():
    assert _metres_ar(3) == "3 أمتار"
    assert _metres_ar(12) == "12 مترًا"


def test_the_clock_restarts_at_45_and_the_sides_swap_at_half_time():
    m = Match(_feed([]))
    assert m.clock_s(25_000) == 2700 + 5  # 5 s into the second half
    assert m.goal_x("home", 5_000) == 1050  # home keeper near x=0 early: home attack x=1050
    assert m.goal_x("home", 25_000) == 0
    assert m.goal_x("away", 5_000) == 0


def test_possession_follows_the_last_completed_action_not_the_nearest_player():
    events = [
        [2000, "pass", 1, "", "success", 500, 300, 600, 340, 2],
        [6000, "tackle", 3, "", "success", 600, 340, -1, -1, 2],
    ]
    m = Match(_feed(events))
    in_flight, won = m.holder(4000), m.holder(7000)
    assert in_flight is not None
    assert won is not None
    assert m.side(in_flight) == "home"  # the pass is in flight: still the passer's side
    assert m.side(won) == "away"  # the ball was won


def test_a_move_reads_as_a_listener_needs_it():
    events = [
        [3000, "pass", 3, "", "success", 300, 340, 40, 340, 4],  # back to the keeper
        [8000, "tackle", 1, "", "success", 40, 340, -1, -1, 4],  # robbing him
        [9500, "shot", 1, "left_foot", "success", 30, 330, 0, 340, -1],
        [9700, "goal", 1, "", "", 30, 330, -1, -1, -1],
    ]
    feed = _feed(events, goals=[{"t": 9700, "side": "home"}])
    feed["p"] = [
        [1000, 340, 500, 300, 520, 360, 600, 340, 40, 340] for _ in range(40)
    ]  # home keeper at x=1000
    descs = describe("x", feed, [{"kind": "goal", "t": 9700}], ["en"])
    said = {d.kind: d.text for d in descs if d.clip}
    plays = [d.text for d in descs if d.kind == "play"]
    assert plays == [
        "Toriez plays it back to the keeper, Okueto.",
        "Quinouani closes down the keeper, Okueto, and takes the ball.",
    ]  # the tackle is said even inside the quiet gap after the back pass
    assert said["goal"].startswith("Quinouani, left foot, from 3 metres. ")  # then his celebration
    assert said["scene"] == "0 minutes, goalless."
    replays = sorted((d.at_s or 0.0, d.text) for d in descs if d.kind == "replay")
    assert replays[0] == (7.4, "Replay.")
    assert replays[1][0] > 7.4 + 9  # the second angle starts after the first replay


def test_every_language_says_every_line():
    events = [
        [3000, "pass", 1, "", "success", 900, 340, 980, 330, 2],
        [12000, "pass", 2, "", "success", 980, 330, 990, 360, 1],
    ]
    feed = _feed(events, goals=[{"t": 15000, "side": "home"}])
    descs = describe("x", feed, [{"kind": "goal", "t": 15000}, {"kind": "conceded", "t": 15000}])
    by_lang = {
        lang: sorted(d.desc_id[: -len(lang) - 1] for d in descs if d.language == lang) for lang in LANGS
    }
    assert len({tuple(v) for v in by_lang.values()}) == 1  # the same lines in every language
    assert all(d.text and "{" not in d.text for d in descs)


def test_voicing_is_priced_with_its_markup_and_held_above_a_dollar(tmp_path):
    import pytest  # noqa: PLC0415
    from matchcut_insights.describe import Description  # noqa: PLC0415
    from matchcut_insights.voice import billable_chars, voice_descriptions  # noqa: PLC0415

    plain = billable_chars("Replay.", "en", "en-GB-SoniaNeural")
    marked = billable_chars("Replay.", "en", "en-GB-SoniaNeural", rate="+30%", tight=True)
    assert plain >= len("Replay.")
    assert marked > 10 * len("Replay.")  # the pace and silence markup is billed too

    class NoSpeech:
        def synthesize_with(self, *a):
            raise AssertionError("must not be called")

    lines = [Description(f"AD-P{i:04d}-en", i, "play", "en", "x" * 200) for i in range(400)]
    with pytest.raises(SystemExit):
        voice_descriptions(lines, "m", NoSpeech(), tmp_path, confirm=lambda cost, n: cost <= 1.0)  # type: ignore[arg-type]
