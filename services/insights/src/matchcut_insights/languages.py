"""Every language Matchcut speaks: how to write it, which way it reads, and who voices it.

Tags are BCP 47. Voices come from Azure AI Speech where it has one; Yoruba, Hausa
and Igbo use YarnGPT2 (Apache-2.0, self-hosted) once it passes a native listening
check, and are caption-only until then. Player and club names stay in Latin script
in every language, as broadcasters show squad names, so the Verifier can still
check them. Voices with emotion styles (Microsoft MAI-Voice-2.1) get a mood per
kind of moment: joy for a goal, surprise for a big chance or a great save.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Language:
    tag: str
    name: str  # in English, for prompts and menus
    native: str  # as fans write it
    style: str  # guidance for the Localiser
    rtl: bool = False
    voice: str | None = None  # "azure:<voice>" or "yarngpt:<speaker>"; None = captions only
    moods: Mapping[str, str] = field(default_factory=dict)  # moment kind -> voice style

    def mood(self, kind: str) -> str | None:
        return self.moods.get(kind)


LANGUAGES: dict[str, Language] = {
    lang.tag: lang
    for lang in (
        Language(
            "en",
            "English (British broadcast)",
            "English",
            "understated UK broadcast: judgement, then the number",
            voice="azure:en-GB-Harry:MAI-Voice-2.1",
            moods={"goal": "joyful", "big_chance": "surprised", "great_save": "surprised"},
        ),
        Language(
            "en-NG",
            "Nigerian English",
            "Nigerian English",
            "warm Nigerian broadcast English, as heard on Lagos radio; natural local idiom, never caricature",
            voice="azure:en-NG-AbeoNeural",
        ),
        Language(
            "pcm",
            "Nigerian Pidgin",
            "Naijá",
            "Nigerian Pidgin as Lagos sports media write it (for example 'Quinouani don score!'); lively",
            voice="azure:en-NG-EzinneNeural",
        ),
        Language("yo", "Yoruba", "Yorùbá", "standard Yoruba with full tone marks and under-dots (ẹ, ọ, ṣ)"),
        Language("ha", "Hausa", "Hausa", "standard Hausa in Boko script with hooked letters (ɓ, ɗ, ƙ)"),
        Language("ig", "Igbo", "Igbo", "standard Igbo with dotted vowels (ị, ọ, ụ) and ṅ"),
        Language(
            "ar",
            "Arabic",
            "العربية",
            "Modern Standard Arabic, formal broadcast register; Western digits (0-9)",
            rtl=True,
            voice="azure:ar-SA-HamedNeural",
        ),
        Language(
            "es",
            "Spanish",
            "Español",
            "rhythmic, celebratory Spanish broadcast",
            voice="azure:es-ES-AlvaroNeural",
        ),
        Language(
            "fr",
            "French",
            "Français",
            "lively French broadcast",
            voice="azure:fr-FR-Marc:MAI-Voice-2.1",
            moods={"goal": "shouting", "big_chance": "surprised", "great_save": "surprised"},
        ),
        Language("pt", "Portuguese", "Português", "Portuguese broadcast", voice="azure:pt-PT-DuarteNeural"),
    )
}


def canonical(tag: str) -> str | None:
    """Match a tag case-insensitively (a model may answer 'EN-ng' or 'PCM')."""
    t = tag.strip().replace("_", "-").lower()
    return next((k for k in LANGUAGES if k.lower() == t), None)
