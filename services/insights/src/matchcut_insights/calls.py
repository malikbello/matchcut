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
}
