from matchcut_editing.edl import AudioEvent, Cut, Segment
from matchcut_editing.qa import Shown, Spoken, expectations, judge, recall, summary, words


def test_words_fold_case_accents_and_punctuation_in_any_script():
    assert words("Quinouani’s 8th, À LA 74e minute!") == ["quinouani", "s", "8th", "a", "la", "74e", "minute"]
    assert words("هدف Quinouani رقم 9") == ["هدف", "quinouani", "رقم", "9"]


def test_recall_is_the_share_of_expected_words_found():
    assert recall("Quinouani scores his 9th", "and quinouani scores, his 9th!") == 1.0
    assert recall("Quinouani scores his 9th", "kino wani scores his 9th") == 0.75  # a name spelt its own way
    assert recall("", "anything") == 1.0


def _cut() -> tuple[Cut, list[dict], list[dict]]:
    cut = Cut("m", "en", "9x16", "", "", segments=[Segment("live", 12.0, t0=0)])
    cut.audio = [AudioEvent(2.0, "a/CA-1.mp3", "call", 1.5), AudioEvent(7.0, "a/CU-1.mp3", "line", 3.0)]
    cut.captions = [(6.5, 12.0, "MO-1")]
    calls = [{"audio": "a/CA-1.mp3", "text": "Here comes Quinouani!"}]
    cues = [{"moment_id": "MO-1", "audio": "a/CU-1.mp3", "text": "His 9th of the season."}]
    return cut, cues, calls


def test_the_plan_says_what_the_film_must_say_and_show():
    spoken, shown = expectations(*_cut())
    assert [(s.at, s.role, s.text) for s in spoken] == [
        (2.0, "call", "Here comes Quinouani!"),
        (7.0, "line", "His 9th of the season."),
    ]
    assert [(s.kind, s.text) for s in shown] == [
        ("call", "Here comes Quinouani!"),
        ("caption", "His 9th of the season."),
    ]


def test_a_film_that_says_and_shows_its_lines_passes_and_one_that_does_not_fails():
    spoken = [Spoken(2.0, "Here comes Quinouani!", "call")]
    shown = [Shown(6.0, 10.0, "His 9th of the season.", "caption")]
    heard = [(2.1, 3.4, "Here comes Quinouani")]
    good = judge(
        "f", "en", spoken, shown, heard, {8.0: "9 TRIES PER GOAL His 9th of the season. VERIFIED"}, -16.2
    )
    assert good.passed
    silent = judge("f", "en", spoken, shown, [], {8.0: "His 9th of the season."}, -16.2)
    assert not silent.passed
    assert not silent.lines[0]["heard"]
    unread = judge("f", "en", spoken, shown, heard, {8.0: ""}, -16.2)
    assert not unread.passed
    assert not unread.captions[0]["read"]
    quiet = judge("f", "en", spoken, shown, heard, {8.0: "His 9th of the season."}, -27.0)
    assert not quiet.passed  # far below the level platforms play at
    late = judge(
        "f", "en", spoken, shown, [(20.0, 21.0, "Here comes Quinouani")], {8.0: "His 9th of the season."}, -16
    )
    assert not late.lines[0]["heard"]  # heard, but not where the plan puts it


def test_invented_names_and_near_misses_do_not_fail_a_line_that_was_said():
    names = ["Kaluamont", "Quinouani"]
    assert recall("Kaluamont accélère !", "Caluamon accélère.", names) == 1.0  # the name set aside
    assert recall("BUT ! Quinouani !", "Bat Kinwani", names) == 1.0  # "bat" for "but", shouted
    assert recall("هدف! Quinouani!", "هدف كونواوني", names) == 1.0  # the name in another script
    assert recall("Quinouani!", "Kinwani", names) == 1.0  # only a name: something was said there
    assert recall("Quinouani!", "", names) == 0.0  # and nothing was
    assert recall("See Kaluamont dey run with am!", "He don't pass one", names) < 0.6  # another line


def test_a_language_without_a_recogniser_is_checked_for_being_voiced_and_says_so():
    spoken = [Spoken(2.9, "See Kaluamont dey run with am!", "call")]
    voiced = judge("f", "pcm", spoken, [], [(3.2, 4.4, "Si Calyaman Deiran with Ham")], {}, -16.0)
    assert voiced.passed
    assert voiced.lines[0]["check"] == "voiced"
    silent = judge("f", "pcm", spoken, [], [], {}, -16.0)
    assert not silent.passed  # nothing was said where the plan puts the call


def test_a_long_line_is_heard_to_its_end():
    """A ten-second line spills past a fixed listening window: its tail must still count."""
    line = (
        "his ninth of the season his second tonight came in the 74th minute "
        "a chance that goes in once in every nine"
    )
    spoken = [Spoken(56.0, line, "line", 9.8)]
    transcript = [
        (56.2, 62.0, "his ninth of the season, his second tonight, came in the 74th minute."),
        (62.6, 65.9, "A chance that goes in once in every nine."),
    ]
    report = judge("f.mp4", "en", spoken, [], transcript, {}, -16.0)
    assert report.lines[0]["heard"]
    assert report.lines[0]["recall"] == 1.0
    assert Spoken(1.0, "x", "call").until == 7.0  # length unknown: the fixed window


def test_a_summary_says_what_failed_in_film_order():
    report = {
        "passed": False,
        "lufs": -21.0,
        "lines": [{"at": 30.0, "text": "late line", "heard": False}, {"at": 5.0, "heard": True}],
        "captions": [{"at": 12.0, "text": "a stale caption", "read": False}],
    }
    brief = summary(report)
    assert brief["heard"] == "1/2"
    assert brief["read"] == "0/1"
    assert [(i["kind"], i["at"]) for i in brief["issues"]] == [
        ("not read", 12.0),
        ("not heard", 30.0),
        ("level", None),
    ]
    assert summary({"passed": True, "lufs": -16.0})["issues"] == []


def test_a_line_of_a_name_and_one_word_is_checked_for_voice_not_words():
    """'Atenção a Quinouani' heard as 'Atenção aqui não ani': the split name ate the 'a'."""
    spoken = [Spoken(2.4, "Atenção a Quinouani...", "call"), Spoken(8.0, "Quinouani is in on goal", "call")]
    transcript = [(2.5, 3.6, "Atenção aqui não ani."), (8.1, 9.2, "Quinuani Izinango.")]
    report = judge("f.mp4", "pt", spoken, [], transcript, {}, -16.0, ["Quinouani"])
    short, long = report.lines
    assert short["check"] == "voiced"
    assert short["heard"]
    assert long["check"] == "words"  # four words to hear: judged word by word, and not heard
    assert not long["heard"]
