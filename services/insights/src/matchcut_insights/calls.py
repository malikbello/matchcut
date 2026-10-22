"""Play-by-play calls: the commentator's live voice around shots, goals and saves.

Football commentary has two voices. The play-by-play caller reacts in the moment
("Quinouani is through... GOAL!"); the co-commentator adds analysis a few seconds
later. The verified insight lines are the analysis. These calls are the play-by-play:
built from the match events and the roster, so every name is correct by construction,
with seeded variety so repeated situations never sound canned.

  build  about 2 s before a shot, as the chance opens up
  goal   the moment the ball goes in
  save   the goalkeeper's stop
  miss   a shot off target
  block  a shot charged down

Each call is voiced with the moment's emotion (see voice.py and languages.py).
Yoruba, Hausa and Igbo are caption languages for now and get no calls.
"""

from __future__ import annotations

import random
from dataclasses import asdict, dataclass

from matchcut_contracts import EventType, MatchEvent

BUILD_LEAD_MS = 2000
MISS_DELAY_MS = 700

TEMPLATES: dict[str, dict[str, list[str]]] = {
    "en": {
        "build": [
            "{p}... has a sight of goal!",
            "Here's {p}...",
            "{p}, room to shoot...",
            "Chance here for {p}...",
        ],
        "goal": ["GOAL! {p}!", "{p}! What a finish!", "It's in! {p}!"],
        "save": ["Saved! {k} keeps it out!", "Great stop from {k}!", "{k} gets down well!"],
        "miss": ["Oh, so close from {p}!", "{p}... just wide!", "Over the bar from {p}!"],
        "block": ["Blocked!", "Charged down!", "Bodies on the line!"],
    },
    "en-NG": {
        "build": ["{p} is in on goal...", "{p}, can he do it...", "Look at {p} now..."],
        "goal": ["GOAL! {p}! What a strike!", "{p} has done it! GOAL!", "It's a goal! {p}!"],
        "save": ["What a save by {k}!", "{k} says no!", "Brilliant from {k}!"],
        "miss": ["Ah! {p}, so close!", "{p}... just wide!", "Haba! {p} should have scored!"],
        "block": ["Blocked!", "The defence stands firm!"],
    },
    "pcm": {
        "build": ["{p} don enter o...", "{p} fit shoot now...", "Watch {p}..."],
        "goal": ["GOAL! {p} don score am!", "E don enter! {p}!", "{p}! Na goal be that!"],
        "save": ["{k} don save am!", "{k} no gree!", "Wetin {k} do so! Save!"],
        "miss": ["Ah! {p} miss am, e near!", "{p}... e no enter!", "Chai! {p} for score that one!"],
        "block": ["Dem block am!", "Defence don stop am!"],
    },
    "fr": {
        "build": ["{p}... il a l'espace...", "Voilà {p}...", "{p} se présente..."],
        "goal": ["BUT ! {p} !", "{p} ! Quelle finition !", "C'est au fond ! {p} !"],
        "save": ["Arrêt de {k} !", "{k} sort le grand jeu !", "Superbe parade de {k} !"],
        "miss": ["Oh, à côté, {p} !", "{p}... c'était tout près !"],
        "block": ["Contré !", "La défense veille !"],
    },
    "es": {
        "build": ["{p}... tiene espacio...", "Ojo a {p}...", "{p} se planta..."],
        "goal": ["¡GOOOL! ¡{p}!", "¡{p}! ¡Qué definición!", "¡Adentro! ¡{p}!"],
        "save": ["¡Paradón de {k}!", "¡{k} lo evita!", "¡Qué atajada de {k}!"],
        "miss": ["¡Uy, por poco, {p}!", "{p}... ¡fuera por centímetros!"],
        "block": ["¡Bloqueado!", "¡La defensa lo tapa!"],
    },
    "pt": {
        "build": ["{p}... tem espaço...", "Atenção a {p}...", "{p} vai rematar..."],
        "goal": ["GOLO! {p}!", "{p}! Que finalização!", "Está lá dentro! {p}!"],
        "save": ["Grande defesa de {k}!", "{k} nega o golo!"],
        "miss": ["Ui, ao lado, {p}!", "{p}... por pouco!"],
        "block": ["Bloqueado!", "A defesa trava!"],
    },
    "ar": {
        "build": ["{p}... أمامه فرصة...", "انتبهوا إلى {p}...", "{p} ينفرد..."],
        "goal": ["هدف! {p}!", "{p}! يا له من إنهاء!", "في الشباك! {p}!"],
        "save": ["تصدٍّ رائع من {k}!", "{k} يتألق!"],
        "miss": ["يا لها من فرصة! {p}!", "{p}... بجوار القائم!"],
        "block": ["صدها الدفاع!", "تم إبعادها!"],
    },
}
LANGS = list(TEMPLATES)


@dataclass
class Call:
    call_id: str
    t_ms: int
    kind: str
    language: str
    text: str
    audio: str | None = None
    voice: str | None = None

    def as_dict(self) -> dict:
        return asdict(self)


def _outcomes(events: list[MatchEvent]) -> dict[str, tuple[str, MatchEvent | None]]:
    """For each shot: goal, save, block or miss, with the event that settled it."""
    settled: dict[str, tuple[str, MatchEvent | None]] = {}
    for e in events:
        if e.related_event_id is None:
            continue
        if e.type == EventType.GOAL:
            settled[e.related_event_id] = ("goal", e)
        elif e.type == EventType.SAVE:
            settled.setdefault(e.related_event_id, ("save", e))
        elif e.type == EventType.BLOCK:
            settled.setdefault(e.related_event_id, ("block", e))
    return settled


def build_calls(
    match_id: str, events: list[MatchEvent], names: dict[str, str], languages: list[str] | None = None
) -> list[Call]:
    """names: player ID -> name as shown on screen (known_as)."""
    langs = [lang for lang in (languages or LANGS) if lang in TEMPLATES]
    settled = _outcomes(events)
    plan: list[tuple[int, str, str | None, str | None]] = []  # (t, kind, player name, keeper name)
    for e in events:
        if e.type != EventType.SHOT or e.player_id is None:
            continue
        shooter = names.get(e.player_id)
        if not shooter:
            continue
        kind, by = settled.get(e.event_id, ("miss", None))
        keeper = names.get(by.player_id) if by is not None and by.player_id else None
        plan.append((max(0, e.t_ms - BUILD_LEAD_MS), "build", shooter, None))
        if kind == "goal" and by is not None:
            plan.append((by.t_ms, "goal", shooter, None))
        elif kind == "save" and by is not None and keeper:
            plan.append((by.t_ms, "save", shooter, keeper))
        elif kind == "block" and by is not None:
            plan.append((by.t_ms, "block", shooter, None))
        else:
            plan.append((e.t_ms + MISS_DELAY_MS, "miss", shooter, None))
    calls: list[Call] = []
    for n, (t, kind, p, k) in enumerate(sorted(plan, key=lambda x: x[0]), start=1):
        for lang in langs:
            options = TEMPLATES[lang][kind]
            rng = random.Random(f"{match_id}-{n}-{lang}")
            text = rng.choice(options).format(p=p or "", k=k or "")
            calls.append(Call(f"CA-{n:05d}-{lang}", t, kind, lang, text))
    return calls


# how each call kind should sound, in the mood vocabulary of languages.py
CALL_MOOD = {
    "build": "build",
    "goal": "goal",
    "save": "great_save",
    "miss": "big_chance",
    "block": "big_chance",
    "run": "build",
    "beat": "big_chance",
}

# ---------------------------------------------------------------- solo runs
# A dribble is not an event in the feed, so it is found in the tracking: one player keeps the
# ball (the nearest player, within 1.2 m) for over 3 s and 15 m while at least two opponents get
# within tackling range (2.5 m). The caller reacts as he sets off and as he beats the challenge.
RUN_TEMPLATES: dict[str, dict[str, list[str]]] = {
    "en": {
        "run": ["Here comes {p}!", "{p}, driving at them!", "{p} sets off!"],
        "beat": ["Past one... past two!", "He's skipped past the challenge!", "Still {p}!"],
    },
    "fr": {
        "run": ["Voilà {p} !", "{p} accélère !", "{p} s'en va !"],
        "beat": ["Il en passe un... puis deux !", "Il efface son adversaire !", "Toujours {p} !"],
    },
    "es": {
        "run": ["¡Ahí va {p}!", "¡{p} encara!", "¡Arranca {p}!"],
        "beat": ["¡Se va de uno... se va de dos!", "¡Deja atrás a su marcador!", "¡Sigue {p}!"],
    },
    "pt": {
        "run": ["Lá vai {p}!", "{p} parte para cima!", "{p} arranca!"],
        "beat": ["Passa um... passa dois!", "Deixa o adversário para trás!", "Continua {p}!"],
    },
    "ar": {
        "run": ["ها هو {p}!", "{p} يتقدم بالكرة!", "{p} ينطلق!"],
        "beat": ["تجاوز الأول... والثاني!", "يتخطى مدافعه!", "ما زال {p}!"],
    },
    "pcm": {
        "run": ["See {p} dey run with am!", "{p} don carry the ball dey go!", "Na {p} be this!"],
        "beat": ["E don pass one... e don pass two!", "{p} still dey go!", "E don waka pass am!"],
    },
}
RUN_TEMPLATES["en-NG"] = RUN_TEMPLATES["en"]
EMPTY = -9999
CONTROL_DM, CHALLENGE_DM = 12, 25  # decimetres: the feed's unit
MIN_RUN_MS, MIN_RUN_DM = 3000, 150


def _holders(feed: dict) -> list[tuple[int, int, int]]:
    """Stretches where one outfield player keeps the ball: (slot, first frame, last frame)."""
    t, b, p, slots = feed["t"], feed["b"], feed["p"], feed["slots"]
    keepers = set(feed.get("keepers", []))
    runs = []
    holder, start, dist = None, 0, 0.0
    for i in range(len(t) - 1):
        bx, by = b[i][0], b[i][1]
        dists = [
            (((p[i][2 * s] - bx) ** 2 + (p[i][2 * s + 1] - by) ** 2) ** 0.5, s)
            for s in range(len(slots))
            if p[i][2 * s] != EMPTY
        ]
        nd, near = min(dists) if dists else (1e9, None)
        owner = near if nd < CONTROL_DM else None
        if owner != holder:
            long_run = t[i] - t[start] > MIN_RUN_MS and dist > MIN_RUN_DM
            if holder is not None and holder not in keepers and long_run:
                runs.append((holder, start, i))
            holder, start, dist = owner, i, 0.0
        elif owner is not None:
            dist += ((b[i + 1][0] - bx) ** 2 + (b[i + 1][1] - by) ** 2) ** 0.5
    return runs


def _second_challenge(feed: dict, slot: int, a: int, z: int) -> int | None:
    """When a second opponent gets within tackling range of the runner (his challenge beaten)."""
    t, p, slots = feed["t"], feed["p"], feed["slots"]
    seen: set[int] = set()
    for i in range(a, z):
        cx, cy = p[i][2 * slot], p[i][2 * slot + 1]
        for o in range(len(slots)):
            if slots[o] == slots[slot] or p[i][2 * o] == EMPTY or o in seen:
                continue
            if ((p[i][2 * o] - cx) ** 2 + (p[i][2 * o + 1] - cy) ** 2) ** 0.5 < CHALLENGE_DM:
                seen.add(o)
                if len(seen) == 2:
                    return t[i]
    return None


def _name_at(feed: dict, slot: int, ms: int) -> str | None:
    """Who wears the slot's shirt at ms (substitutions change it)."""
    side = "home" if feed["slots"][slot] == feed["teams"]["home"]["id"] else "away"
    who = feed["teams"][side]["players"].get(str(slot), {}).get("name")
    for c in sorted(feed.get("changes", []), key=lambda c: c["t"]):
        if c["slot"] == slot and c["t"] <= ms and c.get("id") in feed.get("players", {}):
            who = feed["players"][c["id"]]["name"]
    return who


def solo_runs(feed: dict) -> list[tuple[int, int, str]]:
    """(start ms, the moment the challenge is beaten, runner's name) for each solo run past
    at least two opponents; goalkeepers carrying the ball in their hands are not runs."""
    out = []
    for slot, a, z in _holders(feed):
        beaten = _second_challenge(feed, slot, a, z)
        name = _name_at(feed, slot, feed["t"][a])
        if beaten is not None and name:
            out.append((feed["t"][a] + 300, beaten + 600, name))
    return out


def dribble_calls(match_id: str, feed: dict, languages: list[str] | None = None) -> list[Call]:
    """The caller's voice over solo runs: as the runner sets off, and as he beats the challenge.
    Their IDs (CD-...) are a series of their own, so the shot calls' voices are never renumbered."""
    langs = [lang for lang in (languages or LANGS) if lang in RUN_TEMPLATES]
    calls: list[Call] = []
    for n, (t0, beat, name) in enumerate(solo_runs(feed), start=1):
        for lang in langs:
            rng = random.Random(f"{match_id}-run-{n}-{lang}")
            calls.append(
                Call(
                    f"CD-{2 * n - 1:05d}-{lang}",
                    t0,
                    "run",
                    lang,
                    rng.choice(RUN_TEMPLATES[lang]["run"]).format(p=name),
                )
            )
            if beat is not None:
                text = rng.choice(RUN_TEMPLATES[lang]["beat"]).format(p=name)
                calls.append(Call(f"CD-{2 * n:05d}-{lang}", beat, "beat", lang, text))
    return calls
