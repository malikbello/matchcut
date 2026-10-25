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


def test_a_ball_that_snaps_between_frames_fails_and_cuts_are_forgiven():
    def at(i, x, kind="live", t=None):
        return {"ball": [x, 0.11, 0.0], "kind": kind, "t": i * 40 if t is None else t}

    smooth = [at(i, i * 0.5) for i in range(50)]  # 12.5 m/s: a firm pass
    assert motion_report(smooth, 25)["ball_jumps"] == 0
    snaps = [at(i, i * 0.5 + (3.0 if i in (10, 20, 30) else 0.0)) for i in range(50)]
    r = motion_report(snaps, 25)
    assert r["ball_jumps"] >= 3
    assert not r["pass"]
    cut = [at(0, 0.0), at(1, 40.0, t=900_000)]  # a cut to other play is not a jump
    assert motion_report(cut, 25)["ball_jumps"] == 0


def test_a_strike_that_does_not_face_its_target_fails_the_gate():
    def shot(off):
        return {
            "actors": [{"clip": "kick_soccerball", "at": 0.53, "contact": 0.533, "aims": True, "off": off}]
        }

    assert motion_report([shot(5) for _ in range(10)], 25)["pass"]
    r = motion_report([shot(120) for _ in range(10)], 25)  # a scorer kicking away from the goal
    assert not r["pass"]
    assert r["strike_facing_off_deg"]["max"] == 120


def test_players_drawn_through_each_other_fail_the_gate():
    def live(i, overlaps):
        return {
            "kind": "live",
            "t": i * 40,
            "ball": [0, 0.11, 0],
            "bodies": {"closest": 0.3, "overlaps": overlaps},
        }

    assert motion_report([live(i, 0) for i in range(200)], 25)["pass"]
    r = motion_report([live(i, 0) for i in range(180)] + [live(i, 1) for i in range(180, 200)], 25)
    assert not r["pass"]
    assert r["bodies_overlap_frames"] == 20
