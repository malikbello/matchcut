from matchcut_editing.edl import AudioEvent, Cut, Segment
from matchcut_editing.qa import Shown, Spoken, expectations, judge, recall, words


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
