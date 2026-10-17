"""The Harbour League universe: 26 fictional clubs (20 top flight, 6 second tier).

Club names, places and grounds are invented. Player names combine common given
names with generated surnames, so they read naturally across many cultures
without copying any real footballer. Players carry a permanent ID (``p00001``)
so careers survive transfers between clubs.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Literal

from matchcut_contracts import Club, Kit, Player, Position, TeamStyle

LEAGUE_NAME = "Harbour League"

FormationName = Literal["4-3-3", "4-2-3-1", "4-4-2", "3-4-3", "5-3-2"]
FORMATIONS: list[FormationName] = ["4-3-3", "4-2-3-1", "4-4-2", "3-4-3", "5-3-2"]

# fmt: off
# club_id, name, short, city, ground, founded, home primary, home secondary, number colour, away primary, base strength
CLUBS: list[tuple[str, str, str, str, str, int, str, str, str, str, float]] = [
    ("kes", "Kestrel Bay FC", "KES", "Kestrel Bay", "Saltmarsh Park", 1889, "#E8B422", "#101820", "#101820", "#1D2B53", 82),
    ("irv", "Ironvale Athletic", "IRV", "Ironvale", "Anvil Park", 1894, "#2F6FDE", "#FFFFFF", "#FFFFFF", "#F2F2F2", 79),
    ("hrw", "Harrowmere Rovers", "HRW", "Harrowmere", "Mere Lane", 1902, "#B5121B", "#FFFFFF", "#FFFFFF", "#1E1E1E", 80),
    ("cpt", "Copperton Town", "CPT", "Copperton", "The Kiln", 1885, "#C46A2B", "#1A1A1A", "#FFFFFF", "#EDE6DA", 72),
    ("ldm", "Lindenmoor FC", "LDM", "Lindenmoor", "Linden Park", 1910, "#2E8B57", "#FFFFFF", "#FFFFFF", "#F4D35E", 76),
    ("sbr", "Stonebridge Athletic", "SBR", "Stonebridge", "The Quarry", 1899, "#6E6E6E", "#E30613", "#FFFFFF", "#FFFFFF", 70),
    ("wcr", "Westcroft United", "WCR", "Westcroft", "Croft Road", 1907, "#5B2C83", "#F2C14E", "#F2C14E", "#FFFFFF", 78),
    ("asm", "Ashmoor Rangers", "ASM", "Ashmoor", "Moorside", 1921, "#0B3D91", "#7FC8F8", "#FFFFFF", "#7FC8F8", 71),
    ("ghv", "Glenhaven City", "GHV", "Glenhaven", "Haven Park", 1893, "#7FC8F8", "#0B2545", "#0B2545", "#0B2545", 81),
    ("thw", "Thornwick Athletic", "THW", "Thornwick", "The Thicket", 1912, "#1B4332", "#D8F3DC", "#FFFFFF", "#F7B801", 69),
    ("sol", "Solbury FC", "SOL", "Solbury", "Sun Street", 1931, "#F7B801", "#3D2C8D", "#3D2C8D", "#3D2C8D", 68),
    ("rkh", "Rookhaven Town", "RKH", "Rookhaven", "Rookery Lane", 1888, "#111111", "#FFFFFF", "#FFFFFF", "#E5E5E5", 74),
    ("flm", "Falmere FC", "FLM", "Falmere", "The Pavilion", 1919, "#00A6A6", "#0D1B2A", "#0D1B2A", "#F25C54", 73),
    ("gyw", "Greywater Harriers", "GYW", "Greywater", "Tideway", 1897, "#8D99AE", "#2B2D42", "#2B2D42", "#EF233C", 70),
    ("lth", "Lantern Hill FC", "LTH", "Lantern Hill", "Beacon Ground", 1926, "#FF7B00", "#FFFFFF", "#FFFFFF", "#1C1C1C", 72),
    ("hcn", "Highcairn FC", "HCN", "Highcairn", "Cairn Park", 1904, "#7A1F3D", "#7FC8F8", "#FFFFFF", "#FFFFFF", 75),
    ("svh", "Silverholt City", "SVH", "Silverholt", "Holt Lane", 1890, "#C0C5CE", "#14213D", "#14213D", "#14213D", 77),
    ("tdw", "Tidewell Rangers", "TDW", "Tidewell", "Harbour Road", 1913, "#1D3557", "#E63946", "#FFFFFF", "#E63946", 71),
    ("wxm", "Wexmoor Athletic", "WXM", "Wexmoor", "Moor Edge", 1908, "#9B2226", "#E9D8A6", "#E9D8A6", "#E9D8A6", 69),
    ("emx", "Ember Cross FC", "EMX", "Ember Cross", "The Forge", 1924, "#D62828", "#003049", "#FFFFFF", "#003049", 73),
    # second tier at the start of history
    ("pdb", "Pendlebrook FC", "PDB", "Pendlebrook", "Brook Meadow", 1906, "#3A86FF", "#FFBE0B", "#FFFFFF", "#FFBE0B", 67),
    ("okv", "Oakvale United", "OKV", "Oakvale", "Acorn Park", 1911, "#386641", "#F2E8CF", "#F2E8CF", "#F2E8CF", 68),
    ("crd", "Corrandale FC", "CRD", "Corrandale", "Dale Road", 1923, "#8338EC", "#FFFFFF", "#FFFFFF", "#FFFFFF", 66),
    ("mrf", "Mirefield Town", "MRF", "Mirefield", "Reed Park", 1898, "#FB5607", "#03045E", "#FFFFFF", "#03045E", 67),
    ("dnh", "Dunhollow FC", "DNH", "Dunhollow", "Hollow Lane", 1916, "#006D77", "#EDF6F9", "#EDF6F9", "#EDF6F9", 65),
    ("qlm", "Quillmoor Athletic", "QLM", "Quillmoor", "Quill Street", 1920, "#9D0208", "#FFBA08", "#FFBA08", "#FFBA08", 66),
]
# fmt: on
TOP_FLIGHT_START = [c[0] for c in CLUBS[:20]]

GIVEN = [
    "Tunde",
    "Chidi",
    "Emeka",
    "Kofi",
    "Kwame",
    "Sekou",
    "Ibrahim",
    "Musa",
    "Yaw",
    "Femi",
    "Dayo",
    "Ayo",
    "Mateo",
    "Diego",
    "Luis",
    "Rafael",
    "Joao",
    "Tiago",
    "Andres",
    "Pablo",
    "Iker",
    "Nico",
    "Liam",
    "Owen",
    "Callum",
    "Jack",
    "Harry",
    "Theo",
    "Rory",
    "Kieran",
    "Ellis",
    "Jude",
    "Lukas",
    "Jonas",
    "Felix",
    "Emil",
    "Mats",
    "Aksel",
    "Henrik",
    "Sander",
    "Omar",
    "Karim",
    "Yusuf",
    "Hamza",
    "Samir",
    "Tariq",
    "Adel",
    "Rayan",
    "Arjun",
    "Rohan",
    "Kabir",
    "Dev",
    "Kenji",
    "Haruto",
    "Min-jun",
    "Ji-ho",
    "Mateus",
    "Bruno",
    "Caio",
    "Davi",
    "Luca",
    "Marco",
    "Enzo",
    "Pietro",
    "Milan",
    "Luka",
    "Ivo",
    "Stefan",
]
SYL_A = [
    "Ok",
    "Ad",
    "Ob",
    "Ez",
    "Al",
    "Bar",
    "Cor",
    "Del",
    "Fen",
    "Gar",
    "Hal",
    "Ish",
    "Jar",
    "Kal",
    "Lor",
    "Mar",
    "Nor",
    "Ol",
    "Pel",
    "Quin",
    "Ros",
    "Sal",
    "Tor",
    "Ul",
    "Val",
    "Wen",
    "Yar",
    "Zan",
]
SYL_B = ["a", "e", "i", "o", "u", "ai", "ei", "ou", "ia", "ua"]
SYL_C = [
    "fon",
    "deke",
    "rin",
    "mare",
    "lund",
    "vik",
    "ez",
    "ani",
    "ola",
    "uwa",
    "sen",
    "ford",
    "wick",
    "hal",
    "ri",
    "dor",
    "nez",
    "kov",
    "ane",
    "ish",
    "eto",
    "imba",
    "ondo",
    "ard",
    "ley",
    "mont",
]

# 25-player squad plan
SQUAD_PLAN: dict[Position, int] = {
    Position.GK: 3,
    Position.CB: 4,
    Position.FB: 4,
    Position.DM: 2,
    Position.CM: 4,
    Position.AM: 2,
    Position.W: 3,
    Position.ST: 3,
}
SHIRT_POOL = [
    1,
    13,
    31,
    4,
    5,
    15,
    26,
    2,
    3,
    12,
    22,
    6,
    16,
    8,
    14,
    18,
    24,
    10,
    20,
    7,
    11,
    17,
    9,
    19,
    29,
    21,
    23,
    25,
    27,
    28,
    30,
    32,
    33,
    34,
    35,
    36,
    37,
    38,
    39,
    40,
    41,
    42,
    43,
    44,
    45,
]

# attribute profile per position, relative to the player's overall level
PROFILE: dict[Position, dict[str, int]] = {
    Position.GK: {
        "pace": -25,
        "passing": -12,
        "shooting": -40,
        "dribbling": -30,
        "defending": -10,
        "goalkeeping": +6,
    },
    Position.CB: {
        "pace": -6,
        "passing": -6,
        "shooting": -25,
        "dribbling": -15,
        "defending": +8,
        "goalkeeping": -60,
    },
    Position.FB: {
        "pace": +5,
        "passing": -2,
        "shooting": -18,
        "dribbling": -4,
        "defending": +2,
        "goalkeeping": -60,
    },
    Position.DM: {
        "pace": -4,
        "passing": +3,
        "shooting": -12,
        "dribbling": -6,
        "defending": +5,
        "goalkeeping": -60,
    },
    Position.CM: {
        "pace": -2,
        "passing": +6,
        "shooting": -6,
        "dribbling": +1,
        "defending": -2,
        "goalkeeping": -60,
    },
    Position.AM: {
        "pace": +2,
        "passing": +7,
        "shooting": +2,
        "dribbling": +6,
        "defending": -14,
        "goalkeeping": -60,
    },
    Position.W: {
        "pace": +9,
        "passing": +1,
        "shooting": 0,
        "dribbling": +7,
        "defending": -16,
        "goalkeeping": -60,
    },
    Position.ST: {
        "pace": +4,
        "passing": -4,
        "shooting": +9,
        "dribbling": +3,
        "defending": -22,
        "goalkeeping": -60,
    },
}


@dataclass(frozen=True)
class League:
    name: str
    season: str
    clubs: list[Club]
    players: list[Player]

    def club(self, club_id: str) -> Club:
        return next(c for c in self.clubs if c.club_id == club_id)

    def squad(self, club_id: str) -> list[Player]:
        return [p for p in self.players if p.club_id == club_id]

    def player(self, player_id: str) -> Player:
        return next(p for p in self.players if p.player_id == player_id)


def clamp(v: float, lo: int = 1, hi: int = 99) -> int:
    return max(lo, min(hi, round(v)))


def surname(rng: random.Random) -> str:
    return (rng.choice(SYL_A) + rng.choice(SYL_B) + rng.choice(SYL_C)).capitalize()


def overall(p: Player) -> float:
    """Single number for a player's quality, weighted by what matters in the position."""
    if p.position == Position.GK:
        return float(p.goalkeeping)
    w = {"pace": 1, "passing": 1.2, "shooting": 1, "dribbling": 1, "defending": 1}
    if p.position in (Position.CB, Position.DM):
        w.update(defending=2.2, shooting=0.3)
    elif p.position in (Position.ST, Position.W, Position.AM):
        w.update(shooting=1.8 if p.position == Position.ST else 1.2, defending=0.3, dribbling=1.5)
    return sum(getattr(p, k) * v for k, v in w.items()) / sum(w.values())


def make_ratings(rng: random.Random, pos: Position, level: float) -> dict[str, int]:
    out = {k: clamp(level + d + rng.gauss(0, 4)) for k, d in PROFILE[pos].items()}
    out["stamina"] = clamp(level + rng.gauss(2, 6))
    return out


def club_from_row(row: tuple, rng: random.Random, rating: int) -> Club:
    cid, name, short, city, ground, founded, prim, sec, num, away, _strength = row
    light = {
        "#FFFFFF",
        "#F2F2F2",
        "#E5E5E5",
        "#EDE6DA",
        "#F7B801",
        "#F4D35E",
        "#E9D8A6",
        "#7FC8F8",
        "#FFBE0B",
        "#F2E8CF",
        "#EDF6F9",
        "#FFBA08",
    }
    return Club(
        club_id=cid,
        name=name,
        short_name=short,
        city=city,
        ground=ground,
        founded=founded,
        home_kit=Kit(primary=prim, secondary=sec, number=num),
        away_kit=Kit(primary=away, secondary=prim, number="#101820" if away in light else "#FFFFFF"),
        style=TeamStyle(
            press_intensity=round(rng.uniform(0.25, 0.9), 2),
            directness=round(rng.uniform(0.15, 0.85), 2),
            width=round(rng.uniform(0.3, 0.9), 2),
            tempo=round(rng.uniform(0.3, 0.9), 2),
            defensive_line=round(rng.uniform(0.2, 0.85), 2),
            risk=round(rng.uniform(0.2, 0.8), 2),
        ),
        rating=rating,
        formation=rng.choice(FORMATIONS),
    )


def kit_distance(a: str, b: str) -> float:
    """Approximate perceptual colour distance (redmean) between two hex colours, 0..~765."""
    ra, ga, ba = (int(a[i : i + 2], 16) for i in (1, 3, 5))
    rb, gb, bb = (int(b[i : i + 2], 16) for i in (1, 3, 5))
    rmean = (ra + rb) / 2
    dr, dg, db = ra - rb, ga - gb, ba - bb
    return float(((2 + rmean / 256) * dr * dr + 4 * dg * dg + (2 + (255 - rmean) / 256) * db * db) ** 0.5)


def match_kits(home: Club, away: Club) -> tuple[Kit, Kit]:
    """Home kit always; the away team wears its away kit if the home kits clash."""
    if kit_distance(home.home_kit.primary, away.home_kit.primary) >= 180:
        return home.home_kit, away.home_kit
    return home.home_kit, away.away_kit


def build_league(seed: int = 2026) -> League:
    """The current (2026-27) top flight, after five evolved seasons of history."""
    from matchcut_sim.universe import build_universe  # noqa: PLC0415 - breaks the league <-> universe cycle

    return build_universe(seed).league
