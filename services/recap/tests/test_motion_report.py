from matchcut_recap.cli import motion_report


def carry(ahead, speed=4.0, acting=False):
    return {"carry": {"slot": 9, "speed": speed, "acting": acting, "ahead": ahead, "dist": abs(ahead)}}


def test_a_clean_cut_passes():
    samples = [carry(0.9) for _ in range(200)] + [{"strike": {"slot": 9, "dist": 0.05}} for _ in range(10)]
    r = motion_report(samples, 25)
    assert r["pass"]
    assert r["ball_behind_runner_frames"] == 0
    assert r["contact_gap_m"]["max"] == 0.05


def test_a_ball_behind_running_players_fails_the_gate():
    samples = [carry(0.9) for _ in range(100)] + [carry(-0.6) for _ in range(20)]
    r = motion_report(samples, 25)
    assert not r["pass"]
    assert r["ball_behind_runner_s"] == 0.8


def test_a_foot_missing_the_ball_at_contact_fails_the_gate():
    samples = [{"strike": {"slot": 4, "dist": 0.9}} for _ in range(10)]
    assert not motion_report(samples, 25)["pass"]


def test_standing_players_and_actions_are_not_judged_as_runs():
    samples = [carry(-0.5, speed=0.5), carry(-0.5, acting=True), None, {"ball": [0, 0.11, 0]}]
    r = motion_report(samples, 25)
    assert r["carry_frames"] == 0
    assert r["pass"]


def test_a_pass_still_arriving_from_behind_is_not_a_dribble_error():
    arriving = {
        "carry": {"slot": 9, "speed": 5.0, "acting": False, "ahead": -0.8, "dist": 0.8, "heldMs": 120}
    }
    r = motion_report([arriving] * 10, 25)
    assert r["carry_frames"] == 0
    assert r["pass"]
