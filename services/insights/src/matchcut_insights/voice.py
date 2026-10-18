"""Spoken commentary: verified lines voiced with Azure AI Speech, keyless (Entra ID).

Only verified lines are spoken. SSML handles what a football voice must get right:
scores read the way fans say them ("one nil", "uno a cero"), "xG" and "PPDA" said
as letters, and a slightly brisk broadcast pace. Audio is made once per cue and
cached as MP3 next to the match's other media.
"""

from __future__ import annotations

import os
import re
from collections.abc import Callable
from pathlib import Path
from xml.sax.saxutils import escape

import httpx

from matchcut_insights.languages import LANGUAGES

TTS_PATH = "/tts/cognitiveservices/v1"
OUTPUT_FORMAT = "audio-24khz-96kbitrate-mono-mp3"
SCORE = re.compile(r"\b(\d{1,2})-(\d{1,2})\b")
# how fans say a score, by language: (separator, word for zero or None)
SCORE_SPEECH = {
    "en": (" ", "nil"),
    "en-NG": (" ", "nil"),
    "pcm": (" ", "nil"),
    "es": (" a ", None),
    "fr": (" à ", None),
    "pt": (" a ", None),
    "ar": (" مقابل ", None),
}
SPELL = {"xG": "x G", "PPDA": "P P D A"}


def ssml(text: str, lang: str, voice: str) -> str:
    """Build SSML for one line: escape, then mark up scores and abbreviations."""
    sep, zero = SCORE_SPEECH.get(lang, (" ", None))

    def say_score(m: re.Match[str]) -> str:
        a, b = (zero if zero and n == "0" else n for n in m.groups())
        return f'<sub alias="{a}{sep}{b}">{m.group(0)}</sub>'

    body = SCORE.sub(say_score, escape(text))
    for written, spoken in SPELL.items():
        body = body.replace(written, f'<sub alias="{spoken}">{written}</sub>')
    locale = voice.split("-", 2)[0] + "-" + voice.split("-", 2)[1]
    return (
        f'<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" xml:lang="{locale}">'
        f'<voice name="{voice}"><prosody rate="+6%">{body}</prosody></voice></speak>'
    )


class AzureSpeech:
    """Calls the Speech REST endpoint of our Foundry (AI Services) resource with an Entra token."""

    def __init__(
        self, endpoint: str, resource_id: str, token: Callable[[], str], client: httpx.Client | None = None
    ):
        self.url = endpoint.rstrip("/") + TTS_PATH
        self.resource_id = resource_id
        self.token = token
        self.client = client or httpx.Client(timeout=30)

    @classmethod
    def from_env(cls) -> AzureSpeech:
        from azure.identity import DefaultAzureCredential  # noqa: PLC0415 - only when voicing

        credential = DefaultAzureCredential()
        return cls(
            os.environ["AZURE_OPENAI_ENDPOINT"],
            os.environ["AZURE_SPEECH_RESOURCE_ID"],
            lambda: credential.get_token("https://cognitiveservices.azure.com/.default").token,
        )

    def synthesize(self, text: str, lang: str) -> tuple[bytes, str] | None:
        """Return (mp3 bytes, voice id), or None when the language has no Azure voice."""
        spec = LANGUAGES.get(lang)
        if spec is None or not spec.voice or not spec.voice.startswith("azure:"):
            return None
        voice = spec.voice.split(":", 1)[1]
        r = self.client.post(
            self.url,
            content=ssml(text, lang, voice).encode("utf-8"),
            headers={
                "Authorization": f"Bearer aad#{self.resource_id}#{self.token()}",
                "Content-Type": "application/ssml+xml",
                "X-Microsoft-OutputFormat": OUTPUT_FORMAT,
                "User-Agent": "matchcut",
            },
        )
        r.raise_for_status()
        return r.content, spec.voice


def voice_cues(cues: list, speech: AzureSpeech, media_root: str | Path) -> int:
    """Voice each verified cue whose language has a voice; set audio and voice. Returns how many."""
    root = Path(media_root)
    done = 0
    for i, cue in enumerate(cues):
        if cue.status.value != "verified":
            continue
        rel = Path("audio") / cue.match_id / f"{cue.cue_id}.mp3"
        target = root / rel
        if target.is_file():
            spec = LANGUAGES.get(cue.language)
            cues[i] = cue.model_copy(update={"audio": rel.as_posix(), "voice": spec.voice if spec else None})
            done += 1
            continue
        result = speech.synthesize(cue.text, cue.language)
        if result is None:
            continue
        audio, voice = result
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(audio)
        cues[i] = cue.model_copy(update={"audio": rel.as_posix(), "voice": voice})
        done += 1
    return done
