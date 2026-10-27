"""Audio description: what a blind or partially sighted fan cannot see, said in the gaps.

Stadium audio-descriptive commentary is how blind fans follow football in the ground. RNIB's
research with them names what helps: where the ball is and who has it, the kits so listeners know
who is who, how an attack builds, the score and the time, and "a lot less waffle". The describer
does that, in a calm voice of its own, between the caller's calls and the analyst's lines (the
editor never lets it talk over them, see matchcut_editing.edl):

  scene        the time and the score: every five minutes, and at the start of each moment clip
  attack       who has the ball (from the tracking), in which colours, and where
  play         the move: a pass into the final third, a one-two, the ball won, a set piece
  goal         who scored, with which foot or his head, from how far, and what he does next
               (the Studio's own celebration for him)
  replay       each replay angle as it starts

Every fact is computed here from the feed, and every phrase is written here in each language: no
model writes or translates a description, so there is nothing to verify after the fact.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import asdict, dataclass
from typing import Any

from matchcut_insights.calls import _name_at

# the Studio's goal package (apps/studio/src/show3d/package.js): celebration, wipe, the main
# camera at 0.75x from 6 s before the strike, wipe, behind the goal at 0.35x from 2.2 s before
CELEBRATION_S, WIPE_S = 7.0, 0.6
CELEBRATIONS = ["leap", "victory", "aeroplane"]  # players.js: celebrationStyle
# the moment clips' run-ups (matchcut_editing.edl): a scene line opens each
RUN_UP_S, CONCEDED_BEFORE_S = 8.0, 5.0
SCENE_EVERY_MIN = 5
PLAY_GAP_MS = 4000  # the describer stays quiet this long after a play line ("less waffle")
QUIET_BEFORE_SHOT_MS = 1500  # the caller owns the last moments before a shot
# the actions that say which side has the ball afterwards
OWNING = {
    "pass",
    "tackle",
    "interception",
    "shot",
    "throw_in",
    "free_kick",
    "corner",
    "goal_kick",
    "kick_off",
}
ONE_TWO_MS = 8000
L_DM, W_DM = 1050, 680

# describer voices: calm neural voices, distinct from each language's caller
VOICES = {
    "en": "en-GB-SoniaNeural",
    "en-NG": "en-NG-EzinneNeural",
    "pcm": "en-NG-AbeoNeural",
    "fr": "fr-FR-DeniseNeural",
    "es": "es-ES-ElviraNeural",
    "pt": "pt-PT-RaquelNeural",
    "ar": "ar-SA-ZariyahNeural",
}
LANGS = list(VOICES)

COLOURS = {  # name: (r, g, b)
    "yellow": (232, 190, 40),
    "orange": (240, 130, 30),
    "red": (200, 30, 40),
    "claret": (120, 25, 50),
    "purple": (95, 45, 130),
    "navy": (20, 35, 80),
    "blue": (30, 80, 200),
    "sky blue": (110, 190, 240),
    "green": (30, 130, 70),
    "white": (240, 240, 240),
    "black": (20, 20, 25),
    "grey": (130, 135, 140),
}
COLOUR_WORDS = {
    "en": {},
    "en-NG": {},
    "pcm": {},
    "fr": {
        "yellow": "jaune", "orange": "orange", "red": "rouge", "claret": "bordeaux", "purple": "violet",
        "navy": "bleu marine", "blue": "bleu", "sky blue": "bleu ciel", "green": "vert", "white": "blanc",
        "black": "noir", "grey": "gris",
    },
    "es": {
        "yellow": "amarillo", "orange": "naranja", "red": "rojo", "claret": "granate", "purple": "morado",
        "navy": "azul marino", "blue": "azul", "sky blue": "celeste", "green": "verde", "white": "blanco",
        "black": "negro", "grey": "gris",
    },
    "pt": {
        "yellow": "amarelo", "orange": "laranja", "red": "vermelho", "claret": "grená", "purple": "roxo",
        "navy": "azul-marinho", "blue": "azul", "sky blue": "azul-celeste", "green": "verde",
        "white": "branco", "black": "preto", "grey": "cinzento",
    },
    "ar": {
        "yellow": "الأصفر", "orange": "البرتقالي", "red": "الأحمر", "claret": "العنابي", "purple": "البنفسجي",
        "navy": "الكحلي", "blue": "الأزرق", "sky blue": "السماوي", "green": "الأخضر", "white": "الأبيض",
        "black": "الأسود", "grey": "الرمادي",
    },
}  # fmt: skip

ZONES = ("close", "box", "edge", "wide", "final", "middle", "own")
ZONE_WORDS = {
    "en": ("close to goal", "in the box", "on the edge of the box", "out wide", "in the final third",
           "in midfield", "in their own half"),
    "pcm": ("near goal well well", "inside the box", "for edge of the box", "for wing", "near their goal side",
            "for middle", "for their own side"),
    "fr": ("tout près du but", "dans la surface", "à l'entrée de la surface", "sur le côté", "dans le dernier tiers",
           "au milieu", "dans son camp"),
    "es": ("muy cerca de la portería", "en el área", "en la frontal del área", "por la banda", "en el último tercio",
           "en el centro del campo", "en su propio campo"),
    "pt": ("junto à baliza", "na área", "à entrada da área", "na ala", "no último terço", "no meio-campo",
           "no seu meio-campo"),
    "ar": ("قريبًا من المرمى", "داخل منطقة الجزاء", "على حدود منطقة الجزاء", "على الطرف", "في الثلث الأخير",
           "في وسط الملعب", "في نصف ملعبه"),
}  # fmt: skip
ZONE_WORDS["en-NG"] = ZONE_WORDS["en"]

FOOT = {
    "en": {"left_foot": "left foot", "right_foot": "right foot", "head": "a header"},
    "pcm": {"left_foot": "left leg", "right_foot": "right leg", "head": "with head"},
    "fr": {"left_foot": "du pied gauche", "right_foot": "du pied droit", "head": "de la tête"},
    "es": {"left_foot": "con la zurda", "right_foot": "con la derecha", "head": "de cabeza"},
    "pt": {"left_foot": "com o pé esquerdo", "right_foot": "com o pé direito", "head": "de cabeça"},
    "ar": {"left_foot": "بقدمه اليسرى", "right_foot": "بقدمه اليمنى", "head": "برأسه"},
}
FOOT["en-NG"] = FOOT["en"]

T: dict[str, dict[str, str]] = {
    "en": {
        "opener_goalless": "{m} minutes, goalless.",
        "opener_level": "{m} minutes, level at {h}-{a}.",
        "opener_lead": "{m} minutes, {team} lead {x}-{y}.",
        "scene": "{m} minutes played. {home} {h}, {away} {a}.",
        "attack": "{team}, in {colour}, have the ball {zone}.",
        "pass": "{p} plays it to {q}, {zone}.",
        "one_two": "{p} and {q} play a one-two, {zone}.",
        "back": "{p} plays it back to the keeper, {q}.",
        "won": "{p} wins the ball from {q}, {zone}.",
        "won_keeper": "{p} closes down the keeper, {q}, and takes the ball.",
        "intercept": "{p} cuts out the pass, {zone}.",
        "corner": "Corner to {team}.",
        "free_kick": "Free kick to {team}, {zone}.",
        "goal": "{p}, {foot}, from {d} metres. {celebration}",
        "leap": "He runs to the corner flag and leaps into the air.",
        "victory": "He runs to the corner flag, arms raised to the crowd.",
        "aeroplane": "Arms out like an aeroplane, off to the corner flag.",
        "replay": "Replay.",
        "replay_goal": "Again, from behind the goal, in slow motion.",
    },
    "pcm": {
        "opener_goalless": "{m} minutes, nobody don score.",
        "opener_level": "{m} minutes, e still level, {h}-{a}.",
        "opener_lead": "{m} minutes, {team} dey lead {x}-{y}.",
        "scene": "{m} minutes don pass. {home} {h}, {away} {a}.",
        "attack": "{team}, wey wear {colour}, get the ball {zone}.",
        "pass": "{p} pass am give {q}, {zone}.",
        "one_two": "{p} and {q} play one-two, {zone}.",
        "back": "{p} pass am back give the goalkeeper, {q}.",
        "won": "{p} collect the ball from {q}, {zone}.",
        "won_keeper": "{p} press the goalkeeper, {q}, collect the ball from am.",
        "intercept": "{p} block the pass, {zone}.",
        "corner": "Corner for {team}.",
        "free_kick": "Free kick for {team}, {zone}.",
        "goal": "{p}, {foot}, from {d} metres. {celebration}",
        "leap": "E run go the corner flag, jump for air.",
        "victory": "E run go the corner flag, raise him two hands.",
        "aeroplane": "E open him hand like aeroplane, run go the corner flag.",
        "replay": "Replay.",
        "replay_goal": "Again, from behind the goal, slow motion.",
    },
    "fr": {
        "opener_goalless": "{m1}e minute, pas encore de but.",
        "opener_level": "{m1}e minute, égalité {h}-{a}.",
        "opener_lead": "{m1}e minute, {team} mène {x}-{y}.",
        "scene": "{m} minutes de jeu. {home} {h}, {away} {a}.",
        "attack": "{team}, en {colour}, a le ballon {zone}.",
        "pass": "{p} trouve {q}, {zone}.",
        "one_two": "{p} et {q} combinent en une-deux, {zone}.",
        "back": "{p} remet en retrait à son gardien, {q}.",
        "won": "{p} récupère le ballon devant {q}, {zone}.",
        "won_keeper": "{p} presse le gardien, {q}, et lui chipe le ballon.",
        "intercept": "{p} intercepte, {zone}.",
        "corner": "Corner pour {team}.",
        "free_kick": "Coup franc pour {team}, {zone}.",
        "goal": "{p}, {foot}, à {d} mètres. {celebration}",
        "leap": "Il file au poteau de corner et saute en l'air.",
        "victory": "Il file au poteau de corner, les bras levés vers le public.",
        "aeroplane": "Les bras en avion, il file au poteau de corner.",
        "replay": "Le ralenti.",
        "replay_goal": "Encore, depuis derrière le but, au ralenti.",
    },
    "es": {
        "opener_goalless": "Minuto {m1}, sin goles.",
        "opener_level": "Minuto {m1}, empate a {h}.",
        "opener_lead": "Minuto {m1}, {team} gana {x}-{y}.",
        "scene": "Minuto {m1}. {home} {h}, {away} {a}.",
        "attack": "{team}, de {colour}, tiene el balón {zone}.",
        "pass": "{p} se la da a {q}, {zone}.",
        "one_two": "{p} y {q} hacen una pared, {zone}.",
        "back": "{p} cede hacia atrás a su portero, {q}.",
        "won": "{p} le roba el balón a {q}, {zone}.",
        "won_keeper": "{p} presiona al portero, {q}, y le roba el balón.",
        "intercept": "{p} intercepta el pase, {zone}.",
        "corner": "Córner para {team}.",
        "free_kick": "Falta a favor de {team}, {zone}.",
        "goal": "{p}, {foot}, desde {d} metros. {celebration}",
        "leap": "Corre hacia el banderín y salta.",
        "victory": "Corre hacia el banderín con los brazos en alto.",
        "aeroplane": "Con los brazos como un avión, corre hacia el banderín.",
        "replay": "La repetición.",
        "replay_goal": "Otra vez, desde detrás de la portería, a cámara lenta.",
    },
    "pt": {
        "opener_goalless": "Minuto {m1}, sem golos.",
        "opener_level": "Minuto {m1}, empate a {h}.",
        "opener_lead": "Minuto {m1}, {team} vence por {x}-{y}.",
        "scene": "Minuto {m1}. {home} {h}, {away} {a}.",
        "attack": "{team}, de {colour}, tem a bola {zone}.",
        "pass": "{p} passa para {q}, {zone}.",
        "one_two": "{p} e {q} tabelam, {zone}.",
        "back": "{p} atrasa para o guarda-redes, {q}.",
        "won": "{p} rouba a bola a {q}, {zone}.",
        "won_keeper": "{p} pressiona o guarda-redes, {q}, e rouba-lhe a bola.",
        "intercept": "{p} interceta o passe, {zone}.",
        "corner": "Canto para {team}.",
        "free_kick": "Livre para {team}, {zone}.",
        "goal": "{p}, {foot}, a {d} metros. {celebration}",
        "leap": "Corre para a bandeirola de canto e salta.",
        "victory": "Corre para a bandeirola de canto, de braços erguidos.",
        "aeroplane": "De braços abertos como um avião, corre para a bandeirola de canto.",
        "replay": "A repetição.",
        "replay_goal": "Outra vez, de trás da baliza, em câmara lenta.",
    },
    "ar": {
        "opener_goalless": "الدقيقة {m1}، لا أهداف بعد.",
        "opener_level": "الدقيقة {m1}، التعادل {h}-{a}.",
        "opener_lead": "الدقيقة {m1}، {team} يتقدم {x}-{y}.",
        "scene": "الدقيقة {m1}. {home} {h}، {away} {a}.",
        "attack": "الكرة مع {team} بالزي {colour}، {zone}.",
        "pass": "{p} يمرر إلى {q}، {zone}.",
        "one_two": "{p} و{q} يتبادلان الكرة، {zone}.",
        "back": "{p} يعيد الكرة إلى حارسه {q}.",
        "won": "{p} يستخلص الكرة من {q}، {zone}.",
        "won_keeper": "{p} يضغط على الحارس {q} ويخطف منه الكرة.",
        "intercept": "{p} يقطع التمريرة، {zone}.",
        "corner": "ركلة ركنية لـ{team}.",
        "free_kick": "ركلة حرة لـ{team}، {zone}.",
        "goal": "{p} {foot} من مسافة {d}. {celebration}",
        "leap": "يركض نحو راية الركنية ويقفز في الهواء.",
        "victory": "يركض نحو راية الركنية رافعًا ذراعيه.",
        "aeroplane": "يفتح ذراعيه كطائرة ويركض نحو راية الركنية.",
        "replay": "الإعادة.",
        "replay_goal": "مرة أخرى من خلف المرمى، بالحركة البطيئة.",
    },
}
T["en-NG"] = T["en"]


@dataclass
class Description:
    desc_id: str
    t_ms: int  # match time it describes (a package line: its goal's time)
    kind: str  # scene | attack | play | goal | celebration | replay
    language: str
    text: str
    clip: str | None = None  # only in this moment clip (a scene line opening it, a package line)
    priority: int = 3  # placed first where gaps are scarce: 1 the action, 2 replays, 3 the ball, 4 the clock
    at_s: float | None = None  # package lines: seconds into the goal package
    audio: str | None = None
    voice: str | None = None

    def as_dict(self) -> dict:
        return asdict(self)


def colour_name(hex_colour: str) -> str:
    """The plain name of a kit colour, as a listener would say it."""
    rgb = tuple(int(hex_colour.lstrip("#")[i : i + 2], 16) for i in (0, 2, 4))
    return min(COLOURS, key=lambda n: sum((a - b) ** 2 for a, b in zip(COLOURS[n], rgb, strict=True)))


def _metres_ar(d: int) -> str:
    """Arabic counts its noun: 3 to 10 take the plural, 11 and up the singular accusative."""
    if d == 1:
        return "متر واحد"
    if d == 2:
        return "مترين"
    return f"{d} {'أمتار' if 3 <= d <= 10 else 'مترًا'}"


@dataclass
class Match:
    """The facts the describer needs, read once from the feed."""

    feed: dict

    def __post_init__(self) -> None:
        f = self.feed
        self.p2 = next((f["t"][i] for i, per in enumerate(f["period"]) if per == 2), 10**12)
        teams = f["teams"]
        self.side_of_id = {teams[s]["id"]: s for s in ("home", "away")}
        # the home keeper's place early in the first half says which goal home defends
        k = f.get("keepers", [0])[0]
        early = [f["p"][i][2 * k] for i in range(0, min(len(f["t"]), 3000), 100) if f["p"][i][2 * k] >= 0]
        self.home_attacks_high_first = (sum(early) / max(len(early), 1)) < L_DM / 2
        self.goals = sorted(f.get("goals", []), key=lambda g: g["t"])

    def holder(self, ms: int) -> int | None:
        """The slot whose side has the ball at ms: the last completed action before it (a pass in
        flight belongs to the passer's side, a ball won to the winner's), or None if unclear. The
        nearest player is not enough: a pass travelling through a crowded box passes defenders."""
        last = None
        for e in self.feed.get("events", []):
            if e[0] > ms:
                break
            if e[1] in OWNING and (e[1] != "pass" or e[4] == "success") and e[2] is not None and e[2] >= 0:
                last = e
        return last[2] if last is not None and ms - last[0] < 10000 else None

    def side(self, slot: int) -> str:
        return self.side_of_id.get(self.feed["slots"][slot], "home")

    def team(self, side: str) -> str:
        return self.feed["teams"][side]["name"]

    def colour(self, side: str) -> str:
        return colour_name(self.feed["teams"][side]["kit"]["primary"])

    def clock_s(self, ms: int) -> float:
        """The broadcast clock in seconds (the Studio's rule: the second half restarts at 45:00)."""
        return (ms - self.p2) / 1000 + 2700 if ms >= self.p2 else ms / 1000

    def score(self, ms: int) -> tuple[int, int]:
        h = sum(1 for g in self.goals if g["t"] < ms and g["side"] == "home")
        return h, sum(1 for g in self.goals if g["t"] < ms and g["side"] == "away")

    def goal_x(self, side: str, ms: int) -> int:
        """The x of the goal this side attacks at ms."""
        high = self.home_attacks_high_first == (ms < self.p2)
        if side == "away":
            high = not high
        return L_DM if high else 0

    def zone(self, side: str, ms: int, x: int, y: int) -> int:
        """Where the ball is, from the attacking side's point of view (an index into ZONES)."""
        dist = abs(self.goal_x(side, ms) - x) / 10
        lateral = abs(y - W_DM / 2) / 10
        if dist <= 6 and lateral <= 10:
            return 0
        if dist <= 16.5 and lateral <= 20.2:
            return 1
        if dist <= 25 and lateral <= 20.2:
            return 2
        if lateral > 22 and dist < 40:
            return 3
        if dist < 35:
            return 4
        return 5 if dist < 70 else 6


def _say(lang: str, kind: str, **kw: object) -> str:
    return T[lang][kind].format(**kw)


def _scene(m: Match, lang: str, ms: int) -> str:
    s = m.clock_s(ms)
    h, a = m.score(ms)
    return _say(
        lang, "scene", m=int(s // 60), m1=int(s // 60) + 1, home=m.team("home"), away=m.team("away"), h=h, a=a
    )


def _opener(m: Match, lang: str, ms: int) -> str:
    """A moment clip's first words: the minute and the state of the game, briefly."""
    s = m.clock_s(ms)
    h, a = m.score(ms)
    minute = {"m": int(s // 60), "m1": int(s // 60) + 1}
    if h == a:
        return _say(lang, "opener_goalless" if h == 0 else "opener_level", h=h, a=a, **minute)
    team, x, y = (m.team("home"), h, a) if h > a else (m.team("away"), a, h)
    return _say(lang, "opener_lead", team=team, x=x, y=y, **minute)


def _colour(m: Match, side: str, lang: str) -> str:
    name = m.colour(side)
    return COLOUR_WORDS[lang].get(name, name)


def describe(
    match_id: str, feed: dict, moments: list[dict], langs: list[str] | None = None
) -> list[Description]:
    """Every description for a match: the live track (scenes and play) and, for each moment clip
    (`moments`: {"kind": "goal" | "conceded", "t": ms}), its opening scene and its package."""
    d = _Describer(feed, [lang for lang in (langs or LANGS) if lang in T])
    d.scenes()
    d.plays()
    for mo in moments:
        d.moment(mo["kind"], int(mo["t"]))
    return d.out


class _Describer:
    def __init__(self, feed: dict, langs: list[str]):
        self.feed, self.langs, self.m = feed, langs, Match(feed)
        self.events = feed.get("events", [])
        self.keepers = set(feed.get("keepers", []))
        self.shots = [e[0] for e in self.events if e[1] in ("shot", "goal")]
        self.out: list[Description] = []

    def add(self, n: str, ms: int, kind: str, say: Callable[[str], str], **extra: Any) -> None:
        for lang in self.langs:
            self.out.append(Description(f"AD-{n}-{lang}", ms, kind, lang, say(lang), **extra))

    def name(self, slot: int, ms: int) -> str:
        return _name_at(self.feed, slot, ms) or ""

    def scenes(self) -> None:
        """The score and the time every five minutes of the broadcast clock."""
        m, marks, last = self.m, [], -1
        for ms in range(0, self.feed["t"][-1], 1000):
            minute = int(m.clock_s(ms) // 60)
            if minute != last and minute > 0 and minute % SCENE_EVERY_MIN == 0:
                marks.append(ms)
            last = minute
        for i, ms in enumerate(marks, start=1):
            self.add(f"S{i:04d}", ms, "scene", lambda lang, ms=ms: _scene(m, lang, ms))

    def plays(self) -> None:
        """The ball changing hands, passes that take an attack forward, one-twos, set pieces."""
        quiet_until, n = -1, 0
        for i, e in enumerate(self.events):
            t, kind, slot = e[0], e[1], e[2]
            # the ball changing hands in a tackle is what a listener most needs: never held back
            won = kind == "tackle" and e[4] == "success"
            if (t < quiet_until and not won) or slot is None or slot < 0:
                continue
            if any(0 <= s - t < QUIET_BEFORE_SHOT_MS for s in self.shots):
                continue
            say = self.play(i, e)
            if say is not None:
                n += 1
                self.add(f"P{n:04d}", t, "play", say, priority=1)
                quiet_until = t + PLAY_GAP_MS

    def play(self, i: int, e: list) -> Callable[[str], str] | None:  # noqa: PLR0911 - one return per kind of event
        """How to say one event, or None if it is not worth a listener's attention."""
        m, t, kind, slot, outcome = self.m, e[0], e[1], e[2], e[4]
        side, target = m.side(slot), e[9] if e[9] is not None and e[9] >= 0 else None
        p = self.name(slot, t)
        q = self.name(target, t) if target is not None else ""
        if kind == "pass" and outcome == "success" and target is not None:
            zi = m.zone(side, t, e[7], e[8])
            prev = next(
                (x for x in reversed(self.events[:i]) if x[1] == "pass" and t - x[0] < ONE_TWO_MS), None
            )
            if target in self.keepers and m.side(target) == side:
                return lambda lang: _say(lang, "back", p=p, q=q)
            if prev and prev[2] == target and prev[9] == slot and zi <= 4:
                return lambda lang: _say(lang, "one_two", p=q, q=p, zone=ZONE_WORDS[lang][zi])
            if zi <= 4:
                return lambda lang: _say(lang, "pass", p=p, q=q, zone=ZONE_WORDS[lang][zi])
            return None
        zi = m.zone(side, t, e[5], e[6])
        if kind == "tackle" and outcome == "success" and target is not None:
            key = "won_keeper" if target in self.keepers else "won"
            return lambda lang: _say(lang, key, p=p, q=q, zone=ZONE_WORDS[lang][zi])
        if kind == "interception":
            return lambda lang: _say(lang, "intercept", p=p, zone=ZONE_WORDS[lang][zi])
        if kind == "corner":
            return lambda lang: _say(lang, "corner", team=m.team(side))
        if kind == "free_kick":
            return lambda lang: _say(lang, "free_kick", team=m.team(side), zone=ZONE_WORDS[lang][zi])
        return None

    def moment(self, kind: str, gt: int) -> None:
        """A moment clip's opening scene and who has the ball; a goal's package lines."""
        m, clip = self.m, f"{kind}-{gt}"
        start = gt - int((RUN_UP_S if kind == "goal" else CONCEDED_BEFORE_S) * 1000) + 300
        self.add(f"{clip}-scene", start, "scene", lambda lang: _opener(m, lang, start), clip=clip, priority=4)
        at = start + 2500
        holder = m.holder(at)
        if holder is not None:  # who really has it then: in the build-up it may be the other side
            owner = m.side(holder)
            bx, by = self.feed["b"][
                min(range(len(self.feed["t"])), key=lambda i: abs(self.feed["t"][i] - at))
            ][:2]
            zi = m.zone(owner, at, bx, by)
            self.add(
                f"{clip}-attack",
                at,
                "attack",
                lambda lang: _say(
                    lang,
                    "attack",
                    team=m.team(owner),
                    colour=_colour(m, owner, lang),
                    zone=ZONE_WORDS[lang][zi],
                ),
                clip=clip,
                priority=3,
            )
        if kind == "goal":
            self.package(clip, gt)

    def package(self, clip: str, gt: int) -> None:
        """The goal, the celebration and each replay angle, timed into the Studio's package."""
        m = self.m
        goal_ev = next((e for e in self.events if e[1] == "goal" and abs(e[0] - gt) < 1500), None)
        shot = next((e for e in reversed(self.events) if e[1] == "shot" and 0 <= gt - e[0] < 4000), None)
        scorer = goal_ev[2] if goal_ev else shot[2] if shot else -1
        if scorer < 0:
            return
        side, who = m.side(scorer), self.name(scorer, gt)
        before = sum(1 for e in self.events if e[1] == "goal" and e[2] == scorer and e[0] < gt - 1500)
        style = CELEBRATIONS[(sum(ord(c) for c in who) + before) % len(CELEBRATIONS)]
        if shot:
            d = max(1, round(math.hypot(m.goal_x(side, shot[0]) - shot[5], W_DM / 2 - shot[6]) / 10))
            foot = shot[3] if shot[3] in FOOT["en"] else "right_foot"

            def goal_line(lang: str) -> str:
                dist = _metres_ar(d) if lang == "ar" else d
                return _say(lang, "goal", p=who, foot=FOOT[lang][foot], d=dist, celebration=T[lang][style])

            self.add(f"{clip}-goal", gt, "goal", goal_line, clip=clip, at_s=0.4, priority=1)
        strike = shot[0] if shot else gt - 300
        replay1_at = CELEBRATION_S + WIPE_S
        replay2_at = replay1_at + ((gt + 700) - (strike - 6000)) / 1000 / 0.75 + WIPE_S
        self.add(
            f"{clip}-replay1",
            gt,
            "replay",
            lambda lang: T[lang]["replay"],
            clip=clip,
            at_s=round(replay1_at - 0.2, 2),  # as the wipe ends, before the analyst's line over the replay
        )
        self.add(
            f"{clip}-replay2",
            gt,
            "replay",
            lambda lang: T[lang]["replay_goal"],
            clip=clip,
            at_s=round(replay2_at + 0.2, 2),
        )
