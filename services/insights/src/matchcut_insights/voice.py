"""Spoken commentary: verified lines voiced with Azure AI Speech, keyless (Entra ID).

Only verified lines are spoken. SSML handles what a football voice must get right:
scores read the way fans say them ("one nil", "uno a cero"), "xG" and "PPDA" said
as letters. Expressive voices (MAI-Voice-2.1) speak with the moment's mood (joy
for a goal, surprise for a big chance); classic voices get a slightly brisk
broadcast pace instead. Audio is made once per cue and voice, and cached as MP3
next to the match's other media, with a manifest of which voice made each file.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
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


def ssml(
    text: str,
    lang: str,
    voice: str,
    style: str | None = None,
    lift: bool = False,
    rate: str | None = None,
    tight: bool = False,
) -> str:
    """Build SSML for one line: escape, mark up scores and abbreviations, then set the delivery.
    rate: a pace of its own (the describer's); tight: no silence before or after the words, so a
    line fits the gap it is placed in."""
    sep, zero = SCORE_SPEECH.get(lang, (" ", None))

    def say_score(m: re.Match[str]) -> str:
        a, b = (zero if zero and n == "0" else n for n in m.groups())
        return f'<sub alias="{a}{sep}{b}">{m.group(0)}</sub>'

    body = SCORE.sub(say_score, escape(text))
    for written, spoken in SPELL.items():
        body = body.replace(written, f'<sub alias="{spoken}">{written}</sub>')
    locale = voice.split("-", 2)[0] + "-" + voice.split("-", 2)[1]
    if rate:
        body = f'<prosody rate="{rate}">{body}</prosody>'
    elif lift:  # a build-up call: the voice rises and quickens as the chance opens up
        body = f'<prosody rate="+12%" pitch="+6%">{body}</prosody>'
    elif (
        not style and ":" not in voice
    ):  # classic neural voice: lift the pace; expressive voices set their own
        body = f'<prosody rate="+6%">{body}</prosody>'
    if style:
        body = f'<mstts:express-as style="{style}">{body}</mstts:express-as>'
    if tight:
        body = (
            '<mstts:silence type="Leading-exact" value="0ms"/>'
            '<mstts:silence type="Tailing-exact" value="0ms"/>' + body
        )
    return (
        f'<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" '
        f'xmlns:mstts="http://www.w3.org/2001/mstts" xml:lang="{locale}">'
        f'<voice name="{voice}">{body}</voice></speak>'
    )


def cached_token(credential: object, scope: str, margin_s: int = 300) -> Callable[[], str]:
    """One Entra token shared by every worker, refreshed five minutes before it expires.

    Parallel voicing would otherwise ask the credential (for a developer, the Azure CLI) for a
    token on every request at once, which the CLI cannot serve.
    """
    lock = threading.Lock()
    held: dict[str, object] = {}

    def get() -> str:
        with lock:
            tok = held.get("t")
            if tok is None or tok.expires_on - margin_s < time.time():  # type: ignore[attr-defined]
                tok = credential.get_token(scope)  # type: ignore[attr-defined]
                held["t"] = tok
            return tok.token  # type: ignore[attr-defined]

    return get


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

        return cls(
            os.environ["AZURE_OPENAI_ENDPOINT"],
            os.environ["AZURE_SPEECH_RESOURCE_ID"],
            cached_token(DefaultAzureCredential(), "https://cognitiveservices.azure.com/.default"),
        )

    def synthesize(
        self, text: str, lang: str, kind: str = "", live: bool = False
    ) -> tuple[bytes, str] | None:
        """Return (mp3 bytes, voice id), or None when the language has no Azure voice.

        live: use the low-latency Flash model of an expressive voice (play-by-play calls).
        """
        key = voice_key(lang, kind, live=live)
        if key is None or not key.startswith("azure:"):
            return None
        voice, _, style = key.split(":", 1)[1].partition("#")
        r = self.client.post(
            self.url,
            content=ssml(text, lang, voice, style or None, lift=kind == "build").encode("utf-8"),
            headers={
                "Authorization": f"Bearer aad#{self.resource_id}#{self.token()}",
                "Content-Type": "application/ssml+xml",
                "X-Microsoft-OutputFormat": OUTPUT_FORMAT,
                "User-Agent": "matchcut",
            },
        )
        r.raise_for_status()
        return r.content, key

    def synthesize_with(self, text: str, lang: str, voice: str) -> bytes:
        """One line in a named neural voice, read plainly (the describer: calm, never styled)."""
        for attempt in range(6):  # a burst of lines can be throttled: wait and try again
            r = self.client.post(
                self.url,
                content=ssml(text, lang, voice, rate=DESCRIBER_RATE, tight=True).encode("utf-8"),
                headers={
                    "Authorization": f"Bearer aad#{self.resource_id}#{self.token()}",
                    "Content-Type": "application/ssml+xml",
                    "X-Microsoft-OutputFormat": OUTPUT_FORMAT,
                    "User-Agent": "matchcut",
                },
            )
            if r.status_code != 429 or attempt == 5:
                r.raise_for_status()
                return r.content
            time.sleep(min(30, 2**attempt))
        raise AssertionError("unreachable")


def voice_descriptions(
    descs: list, match_id: str, speech: AzureSpeech, media_root: str | Path, workers: int = 8
) -> int:
    """Voice audio-description lines (see describe.py) with each language's describer voice, in
    parallel, cached like the calls: only new or reworded lines are synthesised."""
    from concurrent.futures import ThreadPoolExecutor  # noqa: PLC0415

    from matchcut_insights.describe import VOICES  # noqa: PLC0415 - avoids an import cycle

    folder = Path(media_root) / "audio" / match_id
    manifest = _read_manifest(folder)
    todo = []
    for d in descs:
        voice = VOICES.get(d.language)
        if voice is None:
            continue
        key = f"azure:{voice}+describer{DESCRIBER_RATE}"  # the delivery is part of what a file says
        rel = Path("audio") / match_id / f"{d.desc_id}.mp3"
        d.audio, d.voice = rel.as_posix(), key
        if not ((Path(media_root) / rel).is_file() and manifest.get(d.desc_id) == cache_key(key, d.text)):
            todo.append((d, voice, key))

    def work(item: tuple) -> tuple:
        d, voice, key = item
        return d, key, speech.synthesize_with(d.text, d.language, voice)

    folder.mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for d, key, audio in pool.map(work, todo):
            (Path(media_root) / d.audio).write_bytes(audio)
            manifest[d.desc_id] = cache_key(key, d.text)
    (folder / MANIFEST).write_text(json.dumps(manifest, indent=1, sort_keys=True), encoding="utf-8")
    return sum(1 for d in descs if d.audio)


def voice_key(lang: str, kind: str = "", live: bool = False) -> str | None:
    """The voice and mood for a line, e.g. 'azure:en-GB-Harry:MAI-Voice-2.1#joyful'."""
    spec = LANGUAGES.get(lang)
    if spec is None or not spec.voice:
        return None
    voice = spec.voice
    if live and voice.endswith(":MAI-Voice-2.1"):
        voice += "-Flash"  # the same voice on the low-latency model, for live calls
    mood = spec.mood(kind)
    return f"{voice}#{mood}" if mood else voice


DESCRIBER_RATE = "+30%"  # describers speak briskly: a line has to fit between the calls
MANIFEST = "voices.json"  # cue ID -> voice and words, so only a changed voice or line is voiced again


def cache_key(voice: str, text: str) -> str:
    """What a voice file says, as the manifest records it: the voice and a digest of the words. A
    line rewritten under the same cue ID is voiced again (keyed on the voice alone, a rewritten
    line kept its old audio under its new caption)."""
    return f"{voice}|{hashlib.sha256(text.encode('utf-8')).hexdigest()[:12]}"


def voice_cues(cues: list, speech: AzureSpeech, media_root: str | Path) -> int:
    """Voice each verified cue whose language has a voice; set audio and voice. Returns how many."""
    root = Path(media_root)
    manifests: dict[Path, dict[str, str]] = {}
    done = 0
    for i, cue in enumerate(cues):
        if cue.status.value != "verified":
            continue
        key = voice_key(cue.language, cue.kind.value)
        if key is None:
            continue
        rel = Path("audio") / cue.match_id / f"{cue.cue_id}.mp3"
        target = root / rel
        manifest = manifests.setdefault(target.parent, _read_manifest(target.parent))
        if not (target.is_file() and manifest.get(cue.cue_id) == cache_key(key, cue.text)):
            result = speech.synthesize(cue.text, cue.language, cue.kind.value)
            if result is None:
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(result[0])
            manifest[cue.cue_id] = cache_key(key, cue.text)
        cues[i] = cue.model_copy(update={"audio": rel.as_posix(), "voice": key})
        done += 1
    for folder, manifest in manifests.items():
        if manifest:
            folder.mkdir(parents=True, exist_ok=True)
            (folder / MANIFEST).write_text(json.dumps(manifest, indent=1, sort_keys=True), encoding="utf-8")
    return done


def _read_manifest(folder: Path) -> dict[str, str]:
    try:
        data = json.loads((folder / MANIFEST).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {k: v for k, v in data.items() if isinstance(k, str) and isinstance(v, str)}


def voice_calls(
    calls: list, match_id: str, speech: AzureSpeech, media_root: str | Path, workers: int = 8
) -> int:
    """Voice play-by-play calls (see calls.py) on the live (Flash) voices, in parallel.

    Cached by call ID and voice like the cues: only new or changed calls are synthesised.
    """
    from concurrent.futures import ThreadPoolExecutor  # noqa: PLC0415

    from matchcut_insights.calls import CALL_MOOD  # noqa: PLC0415 - avoids an import cycle

    folder = Path(media_root) / "audio" / match_id
    manifest = _read_manifest(folder)
    todo = []
    for call in calls:
        mood = CALL_MOOD.get(call.kind, "")
        key = voice_key(call.language, mood, live=True)
        if key is None:
            continue
        key = f"{key}+lift" if call.kind in ("build", "run") else key
        rel = Path("audio") / match_id / f"{call.call_id}.mp3"
        call.audio, call.voice = rel.as_posix(), key
        if not (
            (Path(media_root) / rel).is_file() and manifest.get(call.call_id) == cache_key(key, call.text)
        ):
            todo.append((call, mood, key))

    def work(item: tuple) -> tuple:
        call, mood, key = item
        return call, key, speech.synthesize(call.text, call.language, mood, live=True)

    folder.mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for call, key, result in pool.map(work, todo):
            if result is None:
                call.audio = call.voice = None
                continue
            (Path(media_root) / call.audio).write_bytes(result[0])
            manifest[call.call_id] = cache_key(key, call.text)
    (folder / MANIFEST).write_text(json.dumps(manifest, indent=1, sort_keys=True), encoding="utf-8")
    return sum(1 for c in calls if c.audio)
