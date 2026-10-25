from matchcut_editing.edl import featured_focuses
from matchcut_editing.factory import FILM_ID, PRICES, STALE_S, cost, film_id, plan, run_state


def test_films_are_named_safely_and_planned_clubs_first():
    assert film_id({"side": "home"}, "en") == "home.en"
    assert film_id({"player": "Quinouani"}, "en-NG") == "p-quinouani.en-NG"
    films = plan([{"side": "home"}, {"player": "Ãdé O'Neil"}], ["en", "ar"])
    assert [f["id"] for f in films] == ["home.en", "home.ar", "p-ade-o-neil.en", "p-ade-o-neil.ar"]
    assert all(FILM_ID.match(f["id"]) for f in films)


def test_a_film_costs_its_replica_time_and_what_the_qa_agent_used():
    c = cost(60, 4, 8, {"audio_s": 3600, "tokens_in": 1_000_000, "tokens_out": 1_000_000})
    assert c["compute"] == round(60 * (4 * PRICES["vcpu_s"] + 8 * PRICES["gib_s"]), 6) == 0.00720
    assert c["qa"] == PRICES["speech_h"] + 0.25 + 2.0
    assert c["total"] == round(c["compute"] + c["qa"], 6)


def _done(started, finished, passed=True):
    return {
        "status": "done",
        "started": started,
        "finished": finished,
        "seconds": finished - started,
        "cost": {"compute": 0.01, "qa": 0.02, "total": 0.03},
        "qa": {"passed": passed},
    }


def test_a_run_reads_back_as_the_screen_shows_it():
    run = {
        "run": "f-000000000001",
        "started": 100.0,
        "films": plan([{"side": "home"}], ["en", "fr", "ar", "es"]),
    }
    films = {
        "home.en": _done(102, 160),
        "home.fr": _done(103, 170, passed=False),
        "home.ar": {"status": "making", "started": 104},
    }
    st = run_state(run, films, now=180)
    counts = {"waiting": 1, "making": 1, "checked": 1, "flagged": 1, "unchecked": 0, "failed": 0}
    assert st["counts"] == counts
    assert not st["finished"]
    assert st["first_film_s"] == 60
    assert st["all_films_s"] is None
    assert st["peak_replicas"] == 3
    assert st["qa_passed"] == "1/2"
    assert st["cost_per_film"] == {"compute": 0.01, "qa": 0.02, "total": 0.03}
    assert st["timeline"][-1] == [70.0, 2, 1]  # two made, one still at work
    assert [f["status"] for f in st["films"]] == ["checked", "flagged", "making", "waiting"]


def test_a_film_that_lost_its_replica_fails_and_the_run_ends():
    run = {"run": "f-000000000002", "started": 0.0, "films": plan([{"side": "away"}], ["en"])}
    st = run_state(run, {"away.en": {"status": "making", "started": 1}}, now=STALE_S + 2)
    assert st["counts"]["failed"] == 1
    assert st["finished"]
    assert st["cost_per_film"] is None


def test_only_players_with_a_moment_of_their_own_get_a_film():
    feed = {
        "slots": ["kes", "wcr"],
        "teams": {
            "home": {"id": "kes", "players": {"0": {"name": "Quinouani"}}},
            "away": {"id": "wcr", "players": {"1": {"name": "Toredor"}}},
        },
        "goals": [{"t": 60_000, "side": "home"}],
        "events": [[60_000, "goal", 0]],
    }
    focuses = [{"side": "home"}, {"side": "away"}, {"player": "Quinouani"}, {"player": "Toredor"}]
    assert featured_focuses(feed, [], focuses) == focuses[:3]


def test_a_film_the_qa_agent_could_not_hear_is_not_checked_rather_than_flagged():
    run = {"run": "f-000000000003", "started": 0.0, "films": plan([{"side": "home"}], ["en", "pt"])}
    unheard = {**_done(1, 30, passed=False), "qa": {"passed": False, "issues": [{"kind": "not checked"}]}}
    st = run_state(run, {"home.en": _done(1, 30), "home.pt": unheard}, now=40)
    assert [f["status"] for f in st["films"]] == ["checked", "unchecked"]
    assert st["counts"]["unchecked"] == 1
    assert st["qa_passed"] == "1/1"  # judged films only
    assert st["finished"]
