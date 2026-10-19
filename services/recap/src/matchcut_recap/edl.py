"""The Editor: plans a fan's cut as an edit decision list (EDL).

Given a match (its feed and verified cues), a focus (a club or a player), a language and an
aspect ratio, the Editor picks the moments that matter to that fan and lays them out as a
film, the way a highlights editor works:

  title card    the fixture, the fan's focus and the language
  goals         an eight-second run-up, then the goal package (celebration and replays)
  chances       big chances and great saves involving the focus, run-up and aftermath
  conceded      goals against, shorter and without the package (the story stays honest)
  end card      the final score

The soundtrack is planned with it: the play-by-play calls and the verified lines in the fan's
language, each placed where it happens and never over another line, a goal's analysis line
over its replay, and a crowd roar for every goal. Every word comes from a verified cue or a
call built from the events, so the film never says anything the match did not do.
This module is pure (no I/O), so the plan is tested on its own.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

RUN_UP_S = 8.0
GOAL_TAIL_S = 0.6  # the live run-up stops just after the ball crosses the line
CONCEDED_BEFORE_S, CONCEDED_AFTER_S = 5.0, 1.5
CHANCE_BEFORE_S, CHANCE_AFTER_S = 6.0, 2.5
TITLE_S, END_S = 3.0, 4.0
MAX_FILM_S = 95.0
VOICE_GAP_S = 0.25
MAX_VOICE_SHIFT_S = 3.5  # a line that would land later than this after its moment is dropped
REPLAY_ANALYSIS_AT_S = 8.4  # into the package: the first replay angle has started

CHANCE_KINDS = {"big_chance", "great_save"}


# Card wording in each language a cut is voiced in. Nigerian English and Pidgin use the
# English cards (how Nigerian broadcasts caption them).
CARD_WORDS: dict[str, dict[str, str]] = {
    "en": {
        "your_cut": "Your cut",
        "full_time": "Full time",
        "made": "Made with Matchcut  ·  every line verified",
    },
    "fr": {
        "your_cut": "Votre résumé",
        "full_time": "Fin du match",
        "made": "Réalisé avec Matchcut  ·  chaque phrase vérifiée",
    },
    "es": {
        "your_cut": "Tu resumen",
        "full_time": "Final del partido",
        "made": "Hecho con Matchcut  ·  cada frase verificada",
    },
    "pt": {
        "your_cut": "O seu resumo",
        "full_time": "Fim de jogo",
        "made": "Feito com Matchcut  ·  cada frase verificada",
    },
    "ar": {"your_cut": "ملخّصك", "full_time": "نهاية المباراة", "made": "صُنع مع Matchcut  ·  كل جملة موثّقة"},
}


@dataclass
class Segment:
    kind: str  # card | live | package
    duration: float
    t0: float = 0.0  # match ms at the start (live, card backdrop)
    goal_t: int | None = None  # package
    title: str = ""
    sub: str = ""

    def spec_at(self, local_s: float) -> dict[str, Any]:
        """What the Studio's render mode should show local_s seconds into this segment."""
        if self.kind == "package":
            return {"kind": "package", "goalT": self.goal_t, "pt": local_s}
        if self.kind == "card":
            return {"kind": "card", "t": self.t0, "title": self.title, "sub": self.sub}
        return {"kind": "live", "t": self.t0 + local_s * 1000}


@dataclass
class AudioEvent:
    at: float  # seconds into the film
    file: str  # path relative to the media root, or a crowd stem name
    role: str  # call | line | roar
    duration: float = 0.0


@dataclass
class Cut:
    match_id: str
    language: str
    aspect: str
    focus: str
    title: str
    segments: list[Segment] = field(default_factory=list)
    audio: list[AudioEvent] = field(default_factory=list)
    crowd_high: list[tuple[float, float]] = field(default_factory=list)  # film windows the crowd is up

    @property
    def duration(self) -> float:
        return sum(s.duration for s in self.segments)

    def as_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["duration"] = self.duration
        return d


def _fact(cue: dict, label: str) -> Any:
    return next((f["value"] for f in cue.get("facts", []) if f["label"].startswith(label)), None)


def _team_of_cue(cue: dict, feed: dict) -> str | None:
    club = _fact(cue, "club involved")
    for side in ("home", "away"):
        if club and club == feed["teams"][side]["name"]:
            return side
    return None


def _scorer(feed: dict, goal_t: int) -> str | None:
    for e in feed.get("events", []):
        if e[1] == "goal" and abs(e[0] - goal_t) < 1500 and e[2] >= 0:
            side = "home" if feed["slots"][e[2]] == feed["teams"]["home"]["id"] else "away"
            who = feed["teams"][side]["players"].get(str(e[2]))
            for ch in feed.get("changes", []):
                if ch["slot"] == e[2] and ch["t"] <= goal_t and ch.get("id"):
                    who = feed["players"].get(ch["id"], who)
            return who["name"] if who else None
    return None


def pick_moments(feed: dict, cues: list[dict], focus: dict[str, str]) -> list[dict[str, Any]]:
    """The moments for this fan, in match order. focus: {"side": "home"} or {"player": "Quinouani"}."""
    side = focus.get("side")
    player = focus.get("player")
    picks: list[dict[str, Any]] = []
    for g in feed.get("goals", []):
        scorer = _scorer(feed, g["t"])
        ours = (side and g["side"] == side) or (player and scorer == player)
        if ours:
            picks.append({"kind": "goal", "t": g["t"], "who": scorer})
        elif side:  # conceded: shown briefly, so the story is honest
            picks.append({"kind": "conceded", "t": g["t"], "who": scorer})
    goal_times = [g["t"] for g in feed.get("goals", [])]
    for c in cues:
        if c.get("kind") not in CHANCE_KINDS:
            continue
        if any(abs(c["t_ms"] - gt) < 15000 for gt in goal_times):
            continue  # part of a goal already in the cut
        involved = (side and _team_of_cue(c, feed) == side) or (
            player and _fact(c, "player involved") == player
        )
        if involved:
            picks.append({"kind": "chance", "t": c["t_ms"], "who": _fact(c, "player involved")})
    picks.sort(key=lambda p: p["t"])
    return picks


def _fit(picks: list[dict], package: dict[int, float]) -> list[dict]:
    """Keep every goal; drop the earliest chances until the film fits."""

    def length(ps: list[dict]) -> float:
        total = TITLE_S + END_S
        for p in ps:
            if p["kind"] == "goal":
                total += RUN_UP_S + GOAL_TAIL_S + package.get(p["t"], 0.0)
            elif p["kind"] == "conceded":
                total += CONCEDED_BEFORE_S + CONCEDED_AFTER_S
            else:
                total += CHANCE_BEFORE_S + CHANCE_AFTER_S
        return total

    kept = list(picks)
    while length(kept) > MAX_FILM_S and any(p["kind"] == "chance" for p in kept):
        kept.remove(next(p for p in kept if p["kind"] == "chance"))
    while length(kept) > MAX_FILM_S and any(p["kind"] == "conceded" for p in kept):
        kept.remove(next(p for p in kept if p["kind"] == "conceded"))
    return kept


def build_cut(
    feed: dict,
    cues: list[dict],
    calls: list[dict],
    *,
    focus: dict[str, str],
    language: str,
    aspect: str,
    package_durations: dict[int, float],
    clip_durations: dict[str, float],
    language_name: str = "",
) -> Cut:
    home, away = feed["teams"]["home"], feed["teams"]["away"]
    picks = _fit(pick_moments(feed, cues, focus), package_durations)
    focus_name = focus.get("player") or feed["teams"][focus.get("side", "home")]["name"]
    title = f"{home['name']} v {away['name']}"
    words = CARD_WORDS.get(language, CARD_WORDS["en"])
    # the title names the fan's club or player; the line under it never repeats it
    side = focus.get("side")
    versus = f"v {feed['teams']['away' if side == 'home' else 'home']['name']}" if side else title
    cut = Cut(feed["match_id"], language, aspect, focus_name, title)
    first_t = picks[0]["t"] - RUN_UP_S * 1000 if picks else 0
    cut.segments.append(
        Segment(
            "card",
            TITLE_S,
            t0=max(0, first_t),
            title=focus_name,
            sub=f"{versus}  ·  {words['your_cut']}  ·  {language_name or language}",
        )
    )
    windows: list[tuple[float, float, float, float]] = []  # film start, film end, match from, match to
    at = TITLE_S
    for p in picks:
        if p["kind"] == "goal":
            start_ms = p["t"] - RUN_UP_S * 1000
            seg = Segment("live", RUN_UP_S + GOAL_TAIL_S, t0=start_ms)
            cut.segments.append(seg)
            windows.append((at, at + seg.duration, start_ms, p["t"] + GOAL_TAIL_S * 1000))
            cut.audio.append(AudioEvent(at + RUN_UP_S, "roar", "roar"))
            at += seg.duration
            dur = package_durations.get(p["t"], 0.0)
            if dur > 0:
                cut.segments.append(Segment("package", dur, goal_t=p["t"]))
                cut.crowd_high.append((at - 1.0, at + dur))
                p["package_at"] = at
                at += dur
        else:
            before, after = (
                (CONCEDED_BEFORE_S, CONCEDED_AFTER_S)
                if p["kind"] == "conceded"
                else (CHANCE_BEFORE_S, CHANCE_AFTER_S)
            )
            start_ms = p["t"] - before * 1000
            seg = Segment("live", before + after, t0=start_ms)
            cut.segments.append(seg)
            windows.append((at, at + seg.duration, start_ms, start_ms + seg.duration * 1000))
            if p["kind"] == "chance":
                cut.crowd_high.append((at + before - 2.0, at + before + 1.5))
            at += seg.duration
    score = (
        f"{home['code']} {sum(1 for g in feed.get('goals', []) if g['side'] == 'home')}-"
        f"{sum(1 for g in feed.get('goals', []) if g['side'] == 'away')} {away['code']}"
    )
    last_t = feed["t"][-1] if feed.get("t") else 0
    cut.segments.append(
        Segment(
            "card",
            END_S,
            t0=last_t,
            title=f"{words['full_time']}  {score}",
            sub=words["made"],
        )
    )

    _voice_track(cut, picks, windows, cues, calls, clip_durations)
    return cut


def frames(cut: Cut, fps: int) -> list[dict[str, Any]]:
    """The render spec for every output frame, in order."""
    out: list[dict[str, Any]] = []
    for seg in cut.segments:
        n = round(seg.duration * fps)
        out.extend(seg.spec_at(i / fps) for i in range(n))
    return out


def _voice_track(
    cut: Cut,
    picks: list[dict[str, Any]],
    windows: list[tuple[float, float, float, float]],
    cues: list[dict],
    calls: list[dict],
    clip_durations: dict[str, float],
) -> None:
    """Calls and verified lines where they happen in the film, never over one another."""
    wanted: list[tuple[float, str, str]] = []
    for film_a, _film_b, m_from, m_to in windows:
        for c in calls:
            if c.get("audio") and m_from <= c["t_ms"] <= m_to:
                wanted.append((film_a + (c["t_ms"] - m_from) / 1000, c["audio"], "call"))
        for c in cues:
            if c.get("audio") and c.get("status") == "verified" and m_from <= c["t_ms"] <= m_to:
                wanted.append((film_a + (c["t_ms"] - m_from) / 1000 + 0.4, c["audio"], "line"))
    played_lines = {f for _, f, role in wanted if role == "line"}
    for p in picks:
        if p["kind"] != "goal" or "package_at" not in p:
            continue
        line = next(
            (
                c
                for c in cues
                if c.get("audio")
                and c.get("status") == "verified"
                and c.get("kind") == "goal"
                and abs(c["t_ms"] - p["t"]) < 20000
            ),
            None,
        )
        if line and line["audio"] not in played_lines:
            wanted.append(
                (p["package_at"] + REPLAY_ANALYSIS_AT_S, line["audio"], "line")
            )  # analysis over the replay
    free_at = 0.0
    for t, f, role in sorted(wanted):
        d = clip_durations.get(f, 2.5)
        start = max(t, free_at)
        if start - t > MAX_VOICE_SHIFT_S or start + d > cut.duration:
            continue
        cut.audio.append(AudioEvent(round(start, 3), f, role, d))
        free_at = start + d + VOICE_GAP_S
    cut.audio.sort(key=lambda a: a.at)
