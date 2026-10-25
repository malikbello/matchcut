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
CAPTION_S = 7.0  # a verified caption's time on screen (the Studio's CUE_SECONDS)
MIN_CAPTION_S = 2.0  # a caption that would be on screen for less never airs (unreadable, a flicker)
# captions a film may show besides its own language: Nigerian films read English lines too
CAPTION_LANGUAGES = {"en-NG": {"en-NG", "en"}, "pcm": {"pcm", "en-NG", "en"}}
MAX_FILM_S = 95.0
VOICE_GAP_S = 0.25
MAX_VOICE_SHIFT_S = 3.5  # a line that would land later than this after its moment is dropped
REPLAY_ANALYSIS_AT_S = 8.4  # into the package: the first replay angle has started
CALL_LINE_TAIL_S = 0.6  # the caller's words stay up this long after his voice stops
MIN_CALL_LINE_S = 1.0  # a call line cut shorter than this by a caption never airs

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
    clip: str = ""  # the reusable clip this segment belongs to (title, goal-<t>, chance-<t>, end...)

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
    # verified captions on screen: (film start, film end, moment id). The plan owns every overlay,
    # so each frame is a pure function of its spec and a film can be rendered in slices.
    captions: list[tuple[float, float, str]] = field(default_factory=list)
    # stretches of play: (film start, film end, match from, match to), where calls and lines land
    windows: list[tuple[float, float, float, float]] = field(default_factory=list)

    def caption_at(self, film_s: float) -> tuple[str, float] | None:
        """The caption on screen at film_s and how long it has been up."""
        return next(((m, film_s - a) for a, b, m in self.captions if a <= film_s < b), None)

    @property
    def duration(self) -> float:
        return sum(s.duration for s in self.segments)

    def clip_order(self) -> list[str]:
        """The reusable clips this cut is made of, in order (assembly joins exactly these)."""
        order: list[str] = []
        for s in self.segments:
            if s.clip and (not order or order[-1] != s.clip):
                order.append(s.clip)
        return order

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


def featured_focuses(feed: dict, cues: list[dict], focuses: list[dict[str, str]]) -> list[dict[str, str]]:
    """The focuses with a story in this match: either club always (a club's fans see the goals
    against too), and each player with at least one moment of their own. A player with none
    gets no film, rather than a title card and an end card."""
    return [f for f in focuses if "side" in f or pick_moments(feed, cues, f)]


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
    title = title_card(feed, focus, language, language_name)
    cut = Cut(feed["match_id"], language, aspect, title.title, f"{home['name']} v {away['name']}")
    cut.segments.append(title)
    _lay_out(cut, picks, TITLE_S, package_durations)
    cut.segments.append(end_card(feed, language))
    _voice_track(cut, picks, cut.windows, cues, calls, clip_durations)
    cut.captions = _captions(cut, cues)
    return cut


def moment_cut(
    feed: dict,
    cues: list[dict],
    calls: list[dict],
    key: str,
    *,
    language: str,
    aspect: str,
    package_durations: dict[int, float],
    clip_durations: dict[str, float],
) -> Cut:
    """One moment (or any stretch of play) as its own short film, for the live reel and for
    sharing: the clip with its soundtrack (calls, verified line, crowd), no cards."""
    if key.startswith("window-"):
        home, away = feed["teams"]["home"], feed["teams"]["away"]
        cut = Cut(feed["match_id"], language, aspect, key, f"{home['name']} v {away['name']}")
        cut.segments = window_segments(key)
        seg = cut.segments[0]
        cut.windows = [(0.0, seg.duration, seg.t0, seg.t0 + seg.duration * 1000)]
        cut.crowd_high = [(max(0.0, seg.duration - 4.0), seg.duration)]  # the crowd rises with the move
        _voice_track(cut, [], cut.windows, cues, calls, clip_durations)
        cut.captions = _captions(cut, cues)
        return cut
    kind, t = key.rsplit("-", 1)
    picks = [{"kind": kind, "t": int(t), "who": _scorer(feed, int(t)) if kind != "chance" else None}]
    home, away = feed["teams"]["home"], feed["teams"]["away"]
    cut = Cut(feed["match_id"], language, aspect, key, f"{home['name']} v {away['name']}")
    _lay_out(cut, picks, 0.0, package_durations)
    _voice_track(cut, picks, cut.windows, cues, calls, clip_durations)
    cut.captions = _captions(cut, cues)
    return cut


def _lay_out(cut: Cut, picks: list[dict], at: float, package_durations: dict[int, float]) -> None:
    """Append each picked moment's clip to the cut, with its crowd swells and roars."""
    for p in picks:
        segs = moment_segments(p["kind"], p["t"], package_durations)
        live = segs[0]
        cut.segments.extend(segs)
        if p["kind"] == "goal":
            cut.windows.append((at, at + live.duration, live.t0, p["t"] + GOAL_TAIL_S * 1000))
            cut.audio.append(AudioEvent(at + RUN_UP_S, "roar", "roar"))
            at += live.duration
            if len(segs) > 1:
                cut.crowd_high.append((at - 1.0, at + segs[1].duration))
                p["package_at"] = at
                at += segs[1].duration
        else:
            cut.windows.append((at, at + live.duration, live.t0, live.t0 + live.duration * 1000))
            if p["kind"] == "chance":
                cut.crowd_high.append((at + CHANCE_BEFORE_S - 2.0, at + CHANCE_BEFORE_S + 1.5))
            at += live.duration


def title_card(feed: dict, focus: dict[str, str], language: str, language_name: str = "") -> Segment:
    """The opening card: the fan's club or player, the fixture, the language. The backdrop is
    kick-off for every fan, so a title clip depends only on its words (rendered once each)."""
    home, away = feed["teams"]["home"], feed["teams"]["away"]
    words = CARD_WORDS.get(language, CARD_WORDS["en"])
    focus_name = focus.get("player") or feed["teams"][focus.get("side", "home")]["name"]
    side = focus.get("side")
    # the title names the fan's club or player; the line under it never repeats it
    versus = (
        f"v {feed['teams']['away' if side == 'home' else 'home']['name']}"
        if side
        else f"{home['name']} v {away['name']}"
    )
    return Segment(
        "card",
        TITLE_S,
        t0=0,
        title=focus_name,
        sub=f"{versus}\n{words['your_cut']}  ·  {language_name or language}",
        clip=f"title-{slug(focus_name)}",
    )


def end_card(feed: dict, language: str) -> Segment:
    """The closing card: full time, the score, every line verified."""
    home, away = feed["teams"]["home"], feed["teams"]["away"]
    words = CARD_WORDS.get(language, CARD_WORDS["en"])
    goals = feed.get("goals", [])
    score = (
        f"{home['code']} {sum(1 for g in goals if g['side'] == 'home')}-"
        f"{sum(1 for g in goals if g['side'] == 'away')} {away['code']}"
    )
    last_t = feed["t"][-1] if feed.get("t") else 0
    return Segment(
        "card", END_S, t0=last_t, title=f"{words['full_time']}\n{score}", sub=words["made"], clip="end"
    )


def slug(name: str) -> str:
    """A file-safe key for a club or player name (title clips are stored per focus)."""
    out = "".join(c.lower() if c.isalnum() else "-" for c in name)
    return "-".join(w for w in out.split("-") if w)


def moment_segments(kind: str, t: int, package_durations: dict[int, float]) -> list[Segment]:
    """The segments of one moment's reusable clip: a goal is its run-up then its package
    (celebration and replays); a conceded goal and a chance are a short stretch of play."""
    key = f"{kind}-{t}"
    if kind == "goal":
        segs = [Segment("live", RUN_UP_S + GOAL_TAIL_S, t0=t - RUN_UP_S * 1000, clip=key)]
        dur = package_durations.get(t, 0.0)
        if dur > 0:
            segs.append(Segment("package", dur, goal_t=t, clip=key))
        return segs
    before, after = (
        (CONCEDED_BEFORE_S, CONCEDED_AFTER_S) if kind == "conceded" else (CHANCE_BEFORE_S, CHANCE_AFTER_S)
    )
    return [Segment("live", before + after, t0=t - before * 1000, clip=key)]


def window_key(t0: int, t1: int) -> str:
    """A clip of any stretch of play (a fan's "Clip that", a dribble): its key names its span."""
    return f"window-{int(t0)}-{int(t1)}"


def window_segments(key: str) -> list[Segment]:
    _, t0, t1 = key.split("-")
    return [Segment("live", (int(t1) - int(t0)) / 1000, t0=int(t0), clip=key)]


def segments_for(key: str, package_durations: dict[int, float]) -> list[Segment]:
    """The segments of any reusable clip, a moment or a window."""
    if key.startswith("window-"):
        return window_segments(key)
    kind, t = key.rsplit("-", 1)
    return moment_segments(kind, int(t), package_durations)


def clip_plan(feed: dict, cues: list[dict], package_durations: dict[int, float]) -> dict[str, list[Segment]]:
    """Every reusable moment clip of a match: each goal as a goal and as a goal conceded, and
    each big chance or great save away from a goal. Any fan's cut is made of these (plus cards),
    so each is rendered once, whatever the number of fans."""
    plan: dict[str, list[Segment]] = {}
    goal_times = [g["t"] for g in feed.get("goals", [])]
    for t in goal_times:
        for kind in ("goal", "conceded"):
            plan[f"{kind}-{t}"] = moment_segments(kind, t, package_durations)
    for c in cues:
        if c.get("kind") in CHANCE_KINDS and not any(abs(c["t_ms"] - gt) < 15000 for gt in goal_times):
            plan[f"chance-{c['t_ms']}"] = moment_segments("chance", c["t_ms"], package_durations)
    return plan


def clip_frames(segments: list[Segment], fps: int) -> list[dict[str, Any]]:
    """Render specs for one reusable clip, captions off (captions are added per language)."""
    out: list[dict[str, Any]] = []
    for seg in segments:
        out.extend(seg.spec_at(i / fps) for i in range(round(seg.duration * fps)))
    for spec in out:
        spec["cue"], spec["cueAge"] = None, 0.0
    return out


def clip_captions(
    segments: list[Segment], cues: list[dict], language: str = ""
) -> list[tuple[float, float, str]]:
    """Caption windows inside one clip, in the clip's own seconds (the same rule as a whole cut)."""
    return _captions(Cut("", language, "", "", "", segments=list(segments)), cues)


def call_lines(cut: Cut, calls: list[dict]) -> list[tuple[float, float, str]]:
    """The caller's words on screen while he says them, for films watched muted (as most shared
    video is): each call's line airs where the soundtrack placed its voice, stays a moment after
    it, and gives way to the next call. A verified caption has the screen: a call voiced while one
    is up is heard, not shown, and a line ends when a caption arrives. (film start, film end, words)"""
    words = {c["audio"]: c["text"] for c in calls if c.get("audio") and c.get("text")}
    said = [
        (e.at, e.at + e.duration, words[e.file]) for e in cut.audio if e.role == "call" and e.file in words
    ]
    out = []
    for k, (a, b, text) in enumerate(said):
        if any(ca <= a < cb for ca, cb, _m in cut.captions):
            continue
        end = max(b + CALL_LINE_TAIL_S, a + MIN_CAPTION_S)
        if k + 1 < len(said):
            end = min(end, said[k + 1][0])
        end = min([end, cut.duration] + [ca for ca, _cb, _m in cut.captions if ca > a])
        if end - a >= MIN_CALL_LINE_S:
            out.append((round(a, 3), round(end, 3), text))
    return out


def frames(cut: Cut, fps: int) -> list[dict[str, Any]]:
    """The render spec for every output frame, in order, with the caption on screen."""
    out: list[dict[str, Any]] = []
    for seg in cut.segments:
        n = round(seg.duration * fps)
        out.extend(seg.spec_at(i / fps) for i in range(n))
    for i, spec in enumerate(out):
        on = cut.caption_at(i / fps)
        spec["cue"], spec["cueAge"] = (on[0], round(on[1], 4)) if on else (None, 0.0)
    return out


def _captions(cut: Cut, cues: list[dict]) -> list[tuple[float, float, str]]:
    """Where each moment's caption sits in the film, by the live Studio's rule: it appears when
    the clock passes the moment during play and stays CAPTION_S; a replay package starting in that
    time keeps it up to the package's end (the voiced analysis plays over the replay, so the words
    on screen match the words spoken). It clears when the film jumps to other play or a card.
    A film shows only lines in its own language, and a line that would be replaced or cut away
    within MIN_CAPTION_S never airs: the later, bigger moment (the goal) keeps the screen."""
    allowed = CAPTION_LANGUAGES.get(cut.language, {cut.language})
    starts: list[tuple[float, str]] = []
    clears: list[float] = []
    packages: list[tuple[float, float]] = []
    at = 0.0
    for seg in cut.segments:
        if seg.kind in ("live", "card"):
            clears.append(at)
        if seg.kind == "package":
            packages.append((at, at + seg.duration))
        if seg.kind == "live":
            t_end = seg.t0 + seg.duration * 1000
            starts += [
                (at + (c["t_ms"] - seg.t0) / 1000, c["moment_id"])
                for c in cues
                if seg.t0 <= c["t_ms"] <= t_end
                and (not cut.language or c.get("language", cut.language) in allowed)
            ]
        at += seg.duration
    clears.append(at)
    starts.sort()
    out = []
    for k, (start, moment) in enumerate(starts):
        nxt = starts[k + 1][0] if k + 1 < len(starts) else at
        clear = min(c for c in clears if c > start)
        end = start + CAPTION_S
        end = max([end] + [b for a, b in packages if start <= a < end])
        end = min(end, nxt, clear)
        if end - start >= MIN_CAPTION_S:
            out.append((start, end, moment))
    return out


def _voice_track(
    cut: Cut,
    picks: list[dict[str, Any]],
    windows: list[tuple[float, float, float, float]],
    cues: list[dict],
    calls: list[dict],
    clip_durations: dict[str, float],
) -> None:
    """Calls and verified lines where they happen in the film, never over one another. As a
    broadcast does it, the call owns the goal and the analysis owns the replay: a goal's verified
    line is voiced over the first replay angle, never stacked on the call."""
    wanted: list[tuple[float, str, str]] = []
    over_replay: dict[str, float] = {}
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
        if line:
            over_replay[line["audio"]] = p["package_at"] + REPLAY_ANALYSIS_AT_S
    for film_a, _film_b, m_from, m_to in windows:
        for c in calls:
            if c.get("audio") and m_from <= c["t_ms"] <= m_to:
                wanted.append((film_a + (c["t_ms"] - m_from) / 1000, c["audio"], "call"))
        for c in cues:
            ours = c.get("audio") and c.get("status") == "verified" and m_from <= c["t_ms"] <= m_to
            if ours and c["audio"] not in over_replay:
                wanted.append((film_a + (c["t_ms"] - m_from) / 1000 + 0.4, c["audio"], "line"))
    wanted += [(at, f, "line") for f, at in over_replay.items()]
    free_at = 0.0
    for t, f, role in sorted(wanted):
        d = clip_durations.get(f, 2.5)
        start = max(t, free_at)
        if start - t > MAX_VOICE_SHIFT_S or start + d > cut.duration:
            continue
        cut.audio.append(AudioEvent(round(start, 3), f, role, d))
        free_at = start + d + VOICE_GAP_S
    cut.audio.sort(key=lambda a: a.at)
