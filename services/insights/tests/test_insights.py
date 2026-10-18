import asyncio
import json
from collections.abc import Sequence

import pytest
from matchcut_contracts import Cue, CueStatus, Fact, Moment, MomentKind
from matchcut_insights import (
    InsightsPipeline,
    MatchContext,
    MomentReport,
    build_facts,
    cli,
    history_facts,
    plain_card,
    tool_results_by_query,
    verify_line,
    verify_translation,
)
from matchcut_insights.brain import (
    AnalystNote,
    HistoryClaim,
    HistoryNote,
    Line,
    NotePoint,
    NumberRef,
    Translation,
)
from matchcut_insights.redteam import ATTACKS, red_team, report_markdown
from matchcut_insights.telemetry import configure_telemetry
from matchcut_sim import build_league, simulate_match
from matchcut_sim.cli import replay_analytics


@pytest.fixture(scope="module")
def match():
    league = build_league()
    ids = [c.club_id for c in league.clubs]
    m = simulate_match(league, ids[0], ids[1], seed=11, half_minutes=12)
    found: list[tuple[Moment, dict]] = []
    replay_analytics(m, on_moment=lambda mo, snap: found.append((mo, snap)))
    ctx = MatchContext(
        home=league.club(ids[0]), away=league.club(ids[1]), players={p.player_id: p for p in league.players}
    )
    return ctx, found


def _goal(match) -> tuple[Moment, dict]:
    ctx, found = match
    goals = [x for x in found if x[0].kind == MomentKind.GOAL]
    if goals:
        return goals[0]
    mo, snap = found[0]
    player = next(iter(ctx.players))
    return mo.model_copy(
        update={
            "kind": MomentKind.GOAL,
            "player_id": player,
            "team_id": ctx.home.club_id,
            "metrics": {"score": "1-0", "xg": 0.31},
            "importance": 0.9,
        }
    ), snap


def _fact(facts: Sequence[Fact], label_start: str) -> Fact:
    return next(f for f in facts if f.label.startswith(label_start))


# ---------------------------------------------------------------- facts and plain cards


def test_moments_arrive_with_live_snapshots(match):
    _, found = match
    assert found, "a 24-minute match should produce moments"
    times = [snap["t_ms"] for _, snap in found]
    assert times == sorted(times)
    for mo, snap in found:
        assert snap["t_ms"] <= mo.t_ms + 100  # the snapshot is taken at detection, not at full time


def test_fact_sheet_is_numbered_and_carries_evidence(match):
    ctx, _ = match
    mo, snap = _goal(match)
    facts = build_facts(mo, snap, ctx)
    assert [f.fact_id for f in facts] == [f"F-{i:03d}" for i in range(1, len(facts) + 1)]
    assert all(mo.moment_id in f.evidence_ids for f in facts)
    assert _fact(facts, "match minute").value == int(mo.clock.split(":")[0]) + 1
    assert _fact(facts, "player involved").value == ctx.players[mo.player_id].known_as


def test_plain_cards_cover_every_moment_kind(match):
    ctx, found = match
    mo, snap = found[0]
    for kind in MomentKind:
        m2 = mo.model_copy(update={"kind": kind})
        facts = build_facts(m2, snap, ctx)
        text, used = plain_card(m2, facts)
        assert text
        assert set(used) <= {f.fact_id for f in facts}
        assert verify_line(text, used, facts, ctx.names()).checks["numbers_grounded"]


# ---------------------------------------------------------------- verifier

FACTS = [
    Fact(fact_id="F-001", label="match minute", value=67, source="analytics"),
    Fact(fact_id="F-002", label="player involved", value="Okafor", source="analytics"),
    Fact(fact_id="F-003", label="expected goals of the shot (0 to 1)", value=0.42, source="analytics"),
    Fact(fact_id="F-004", label="score, Kestrel first", value="2-1", source="analytics"),
]
NAMES = {"Okafor", "Brandt", "Kestrel Town"}


def test_grounded_line_passes():
    v = verify_line(
        "Okafor strikes in the 67th minute from a 0.42 chance: 2-1.",
        ["F-001", "F-002", "F-003", "F-004"],
        FACTS,
        NAMES,
    )
    assert v.passed, v.problems


@pytest.mark.parametrize(
    ("text", "cited", "failed"),
    [
        ("Okafor scores in the 68th minute.", ["F-001", "F-002"], "numbers_grounded"),
        ("Okafor scores in the 67th minute.", ["F-001"], "names_grounded"),
        ("Brandt scores in the 67th minute.", ["F-001", "F-002"], "names_grounded"),
        ("Okafor scores.", ["F-002", "F-099"], "cites_only_known_facts"),
        ("Okafor scores.", [], "cites_at_least_one_fact"),
        ("Okafor scores and the odds collapse.", ["F-002"], "clean_language"),
        ("Okafor " + "really " * 30 + "scores.", ["F-002"], "length_ok"),
        ("Okafor " + chr(0x2014) + " what a finish.", ["F-002"], "house_style"),
    ],
)
def test_verifier_catches_each_failure(text, cited, failed):
    v = verify_line(text, cited, FACTS, NAMES)
    assert not v.passed
    assert v.checks[failed] is False
    assert v.problems


def test_each_number_must_come_from_the_fact_it_is_attributed_to():
    facts = [
        Fact(fact_id="F-001", label="match minute", value=5, source="analytics"),
        Fact(fact_id="F-002", label="Ironvale shots", value=3, source="analytics"),
    ]
    good = [("3", "F-002"), ("5", "F-001")]
    assert verify_line(
        "Ironvale have 3 shots after 5 minutes.", ["F-001", "F-002"], facts, NAMES, good
    ).passed
    # 5 is a real fact (the minute) but not the shot count: caught
    nudged = verify_line("Ironvale have 5 shots after 5 minutes.", ["F-001", "F-002"], facts, NAMES, good)
    assert not nudged.checks["numbers_attributed"]
    swapped = verify_line("Ironvale have 5 shots after 3 minutes.", ["F-001", "F-002"], facts, NAMES, good)
    assert not swapped.checks["numbers_attributed"]
    wrong_owner = [("5", "F-002"), ("5", "F-001")]
    assert not verify_line(
        "Ironvale have 5 shots after 5 minutes.", ["F-001", "F-002"], facts, NAMES, wrong_owner
    ).passed


def test_a_score_can_be_attributed_as_one_value():
    facts = [Fact(fact_id="F-004", label="score, Kestrel first", value="2-1", source="analytics")]
    assert verify_line("It is 2-1.", ["F-004"], facts, NAMES, [("2-1", "F-004")]).passed
    flipped = verify_line("It is 1-2.", ["F-004"], facts, NAMES, [("2-1", "F-004")])
    assert not flipped.checks["numbers_attributed"]


def test_numbers_from_a_cited_label_are_allowed():
    facts = [Fact(fact_id="F-001", label="pressing actions, last 5 minutes", value=18, source="analytics")]
    assert verify_line("18 pressing actions in the last 5 minutes.", ["F-001"], facts, NAMES).passed


def test_translation_must_keep_numbers_and_names():
    src = "Okafor strikes in the 67th minute: 2-1."
    assert verify_translation(src, "Okafor marca en el minuto 67: 2-1.", NAMES).passed
    bad = verify_translation(src, "Okafor marca en el minuto 76: 2-1.", NAMES)
    assert not bad.checks["numbers_preserved"]
    assert not verify_translation(src, "Marca en el minuto 67: 2-1.", NAMES).checks["names_preserved"]


# ---------------------------------------------------------------- League Memory grounding

QID = "LM-0123456789"
ANSWER = json.dumps(
    {
        "query_id": QID,
        "career_goals_before": 49,
        "facts": [{"fact": "career_goal_milestone", "goals": 50}],
        "evidence": ["M-2024-01"],
    }
)


def test_history_claims_are_grounded_against_real_tool_answers():
    results = tool_results_by_query([ANSWER, "not json"])
    facts, rejected = history_facts(
        [
            ("career goals with this one", 50, QID),  # true: in the answer
            ("career goals before", 51, QID),  # fabricated value
            ("league titles", 3, "LM-ffffffffff"),  # query never made
        ],
        results,
    )
    assert [f.fact_id for f in facts] == [f"{QID}.1"]
    assert facts[0].source == "league_memory"
    assert "M-2024-01" in facts[0].evidence_ids
    assert len(rejected) == 2


# ---------------------------------------------------------------- pipeline with a scripted brain


class ScriptedBrain:
    def __init__(
        self,
        lines: list[Line],
        fail: bool = False,
        history: HistoryNote | None = None,
        raw: list[str] | None = None,
    ):
        self.lines, self.fail = list(lines), fail
        self.history, self.raw = history or HistoryNote(claims=[]), raw or []
        self.feedback: list[str | None] = []

    async def analyse(self, moment, facts):
        if self.fail:
            raise RuntimeError("model unavailable")
        return AnalystNote(points=[NotePoint(text="late and level", fact_ids=["F-001"])])

    async def recall(self, moment, ctx):
        return self.history, self.raw

    async def write(self, moment, facts, note, feedback):
        self.feedback.append(feedback)
        return self.lines.pop(0) if len(self.lines) > 1 else self.lines[0]

    async def translate(self, text, languages):
        return [Translation(language=lang, text=f"[{lang}] {text}") for lang in languages] + [
            Translation(language="de", text="unasked language")
        ]


def _run(brain, match, languages=("es", "fr")) -> tuple[list[Cue], MomentReport]:
    ctx, _ = match
    mo, snap = _goal(match)
    return asyncio.run(InsightsPipeline(brain, ctx, languages=languages).process(mo, snap))


def _good_line(match) -> Line:
    ctx, _ = match
    mo, snap = _goal(match)
    facts = build_facts(mo, snap, ctx)
    minute, player = _fact(facts, "match minute"), _fact(facts, "player involved")
    return Line(
        text=f"{player.value} delivers in minute {minute.value}.",
        cited_fact_ids=[minute.fact_id, player.fact_id],
        numbers=[NumberRef(text=str(minute.value), fact_id=minute.fact_id)],
    )


def test_verified_line_and_translations(match):
    cues, report = _run(ScriptedBrain([_good_line(match)]), match)
    assert cues[0].status == CueStatus.PLAIN
    verified = [c for c in cues if c.status == CueStatus.VERIFIED]
    assert [c.language for c in verified] == ["en", "es", "fr"]
    assert report.verified
    assert report.retries == 0
    assert report.translations_verified == 2
    assert report.translations_rejected == 1
    assert all(set(c.cited_fact_ids) == {f.fact_id for f in c.facts} for c in verified)


def test_verifier_feedback_fixes_a_bad_first_draft(match):
    bad = Line(text="A wonder goal in minute 999.", cited_fact_ids=["F-001"])
    brain = ScriptedBrain([bad, _good_line(match)])
    _cues, report = _run(brain, match)
    assert report.verified
    assert report.retries == 1
    assert brain.feedback[0] is None
    assert "999" in (brain.feedback[1] or "")


def test_persistent_failure_keeps_the_plain_card(match):
    bad = Line(text="A wonder goal in minute 999.", cited_fact_ids=["F-001"])
    cues, report = _run(ScriptedBrain([bad]), match)
    assert not report.verified
    assert report.retries == 1
    assert [c.status for c in cues] == [CueStatus.PLAIN, CueStatus.REJECTED]


def test_model_error_never_blocks_the_screen(match):
    cues, report = _run(ScriptedBrain([_good_line(match)], fail=True), match)
    assert [c.status for c in cues] == [CueStatus.PLAIN]
    assert report.error
    assert "model unavailable" in report.error


def test_low_importance_moments_skip_the_agents(match):
    ctx, found = match
    mo, snap = found[0]
    quiet = mo.model_copy(update={"importance": 0.1})
    cues, report = asyncio.run(InsightsPipeline(ScriptedBrain([_good_line(match)]), ctx).process(quiet, snap))
    assert not report.ai_attempted
    assert [c.status for c in cues] == [CueStatus.PLAIN]


def test_grounded_history_becomes_citable(match):
    ctx, _ = match
    mo, snap = _goal(match)
    player = ctx.players[mo.player_id].known_as
    history = HistoryNote(claims=[HistoryClaim(label="career goals with this one", value=50, query_id=QID)])
    line = Line(
        text=f"{player} brings up 50 career goals.",
        cited_fact_ids=[f"{QID}.1", "F-005"],
        numbers=[NumberRef(text="50", fact_id=f"{QID}.1")],
    )
    facts = build_facts(mo, snap, ctx)
    line.cited_fact_ids[1] = _fact(facts, "player involved").fact_id
    cues, report = _run(ScriptedBrain([line], history=history, raw=[ANSWER]), match, languages=())
    assert report.history_accepted == 1
    assert report.verified
    en = next(c for c in cues if c.status == CueStatus.VERIFIED)
    assert any(f.source == "league_memory" for f in en.facts)


# ---------------------------------------------------------------- CLI, end to end with the scripted brain


class _ScriptedSession(ScriptedBrain):
    def __init__(self, lines: list[Line]):
        super().__init__(lines)
        self.usage = [{"agent": "Writer", "input_token_count": 900, "output_token_count": 120}]

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return None


def test_cli_run_and_eval_write_outputs(match, monkeypatch, tmp_path, capsys):
    ctx, found = match
    monkeypatch.setattr(cli, "moments_with_snapshots", lambda home, away, seed: (ctx, found))
    monkeypatch.setattr(cli, "_brain", lambda args: _ScriptedSession([_good_line(match)]))

    out = tmp_path / "cues.jsonl"
    cli.main(
        [
            "run",
            "--home",
            ctx.home.club_id,
            "--away",
            ctx.away.club_id,
            "--out",
            str(out),
            "--max-moments",
            "3",
        ]
    )
    cues = [Cue.model_validate_json(line) for line in out.read_text(encoding="utf-8").splitlines()]
    assert cues
    assert {c.status for c in cues} <= {CueStatus.PLAIN, CueStatus.VERIFIED, CueStatus.REJECTED}

    report = tmp_path / "eval.md"
    cli.main(["eval", "--matches", "1", "--max-moments", "3", "--out", str(report)])
    text = report.read_text(encoding="utf-8")
    assert "Verified on the first draft" in text
    assert "Unverified numbers or names that reached the screen" in text
    assert "cues ->" in capsys.readouterr().out


def test_top_keeps_the_most_important_moments_in_time_order(match):
    _, found = match
    top = cli._top(found, 3)
    assert len(top) == min(3, len(found))
    assert [m.t_ms for m, _ in top] == sorted(m.t_ms for m, _ in top)
    assert cli._top(found, None) == found
    assert cli._pct([], 0.95) == 0.0
    assert cli._pct([1.0, 2.0, 3.0], 0.5) == 2.0


def test_telemetry_is_off_without_a_connection_string(monkeypatch):
    monkeypatch.delenv("APPLICATIONINSIGHTS_CONNECTION_STRING", raising=False)
    assert configure_telemetry("matchcut-test") is False


def test_red_team_catches_every_planted_error_and_passes_true_lines(match):
    ctx, found = match
    result = red_team(found, ctx)
    assert result.true_lines >= len(found)
    assert result.false_rejection_rate == 0.0, result.misses
    assert result.catch_rate == 1.0, result.misses
    assert set(result.attacks) <= set(ATTACKS)
    assert "Caught 100.0%" in report_markdown(result, 1)


def test_momentum_swings_keep_their_plain_card(match):
    ctx, found = match
    mo, snap = found[0]
    swing = mo.model_copy(update={"kind": MomentKind.MOMENTUM_SWING, "importance": 0.9})
    cues, report = asyncio.run(InsightsPipeline(ScriptedBrain([_good_line(match)]), ctx).process(swing, snap))
    assert not report.ai_attempted
    assert [c.status for c in cues] == [CueStatus.PLAIN]


def test_a_slow_translation_never_costs_the_verified_english_line(match):
    class SlowLocaliser(ScriptedBrain):
        async def translate(self, text, languages):
            await asyncio.sleep(5)
            return []

    ctx, _ = match
    mo, snap = _goal(match)
    pipe = InsightsPipeline(
        SlowLocaliser([_good_line(match)]), ctx, languages=("es",), translate_timeout_s=0.2
    )
    cues, report = asyncio.run(pipe.process(mo, snap))
    assert [(c.language, c.status) for c in cues] == [("en", CueStatus.PLAIN), ("en", CueStatus.VERIFIED)]
    assert report.verified
    assert "translations timed out" in (report.error or "")


def test_numbers_written_as_text_still_ground():
    facts, rejected = history_facts([("career goals before", "49", QID)], tool_results_by_query([ANSWER]))
    assert [f.value for f in facts] == ["49"]
    assert not rejected
    _, rejected = history_facts([("career goals before", "48", QID)], tool_results_by_query([ANSWER]))
    assert rejected
