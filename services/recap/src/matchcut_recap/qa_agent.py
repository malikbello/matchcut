"""The QA agent: it watches and listens to every finished film before a fan can.

Perception is Azure AI, keyless (Entra ID), on the project's AI Services resource:
- listening: Azure AI Speech fast transcription of the film's soundtrack, in the film's language;
- reading: the vision-capable model reads every word on screen at the middle of each caption
  window (it only transcribes; it is never asked whether the film is right);
- loudness: ffmpeg's EBU R128 meter.
The judgement is matchcut_editing.qa's, in code: every voiced line heard around its time, every
caption read in its window, the level right.
"""

from __future__ import annotations

import base64
import json
import os
import re
import subprocess
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import httpx
from matchcut_editing.edl import Cut
from matchcut_editing.qa import QAReport, expectations, judge

STT_PATH = "/speechtotext/transcriptions:transcribe?api-version=2024-11-15"
CHAT_API = "2025-04-01-preview"
# the recogniser's locale for each film language (Pidgin is heard with the Nigerian English model)
LOCALES = {
    "en": "en-GB",
    "en-NG": "en-NG",
    "pcm": "en-NG",
    "fr": "fr-FR",
    "es": "es-ES",
    "pt": "pt-PT",
    "ar": "ar-SA",
}
READER = (
    "You transcribe on-screen text for a quality check. Write every word visible in the image, "
    "exactly as written, top to bottom, one block per line. Do not describe the picture, do not "
    "translate, do not correct anything. If there is no text, write nothing."
)


def _run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, capture_output=True, text=True, check=False)  # noqa: S603 - our own arguments


def loudness(film: Path, ffmpeg: str = "ffmpeg") -> float | None:
    """Integrated loudness in LUFS (EBU R128)."""
    r = _run([ffmpeg, "-hide_banner", "-nostats", "-i", str(film), "-af", "ebur128", "-f", "null", "-"])
    found = re.findall(r"I:\s+(-?\d+(?:\.\d+)?) LUFS", r.stderr)
    return float(found[-1]) if found else None


@dataclass
class Perception:
    """Azure AI's senses for the QA agent."""

    endpoint: str
    token: Callable[[], str]
    model: str = "gpt-5-mini"
    ffmpeg: str = "ffmpeg"
    client: httpx.Client | None = None

    @classmethod
    def from_env(cls, ffmpeg: str = "ffmpeg") -> Perception:
        from azure.identity import DefaultAzureCredential  # noqa: PLC0415 - only when checking films

        cred = DefaultAzureCredential()
        held: dict[str, object] = {}

        def token() -> str:
            tok = held.get("t")
            if tok is None or tok.expires_on - 300 < time.time():  # type: ignore[attr-defined]
                tok = cred.get_token("https://cognitiveservices.azure.com/.default")
                held["t"] = tok
            return tok.token  # type: ignore[attr-defined]

        return cls(
            os.environ["AZURE_OPENAI_ENDPOINT"].rstrip("/"),
            token,
            os.environ.get("AZURE_OPENAI_MODEL", "gpt-5-mini"),
            ffmpeg,
        )

    @property
    def http(self) -> httpx.Client:
        if self.client is None:
            self.client = httpx.Client(timeout=120)
        return self.client

    def listen(self, film: Path, language: str) -> list[tuple[float, float, str]]:
        """What is said in the film, as (start s, end s, text) phrases."""
        with tempfile.TemporaryDirectory() as tmp:
            wav = Path(tmp) / "sound.wav"
            _run(
                [
                    self.ffmpeg,
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-y",
                    "-i",
                    str(film),
                    "-ac",
                    "1",
                    "-ar",
                    "16000",
                    str(wav),
                ]
            )
            definition = json.dumps({"locales": [LOCALES.get(language, "en-GB")]})
            r = self.http.post(
                self.endpoint + STT_PATH,
                headers={"Authorization": f"Bearer {self.token()}"},
                files={
                    "audio": ("sound.wav", wav.read_bytes(), "audio/wav"),
                    "definition": (None, definition),
                },
            )
        r.raise_for_status()
        return [
            (
                p["offsetMilliseconds"] / 1000,
                (p["offsetMilliseconds"] + p["durationMilliseconds"]) / 1000,
                p["text"],
            )
            for p in r.json().get("phrases", [])
        ]

    def read(self, film: Path, seconds: list[float]) -> dict[float, str]:
        """Every word on screen at each of these film seconds."""
        out: dict[float, str] = {}
        with tempfile.TemporaryDirectory() as tmp:
            for s in sorted(set(seconds)):
                jpg = Path(tmp) / f"{s:.2f}.jpg"
                _run(
                    [
                        self.ffmpeg,
                        "-hide_banner",
                        "-loglevel",
                        "error",
                        "-y",
                        "-ss",
                        f"{s}",
                        "-i",
                        str(film),
                        "-frames:v",
                        "1",
                        "-vf",
                        "scale=720:-2",
                        "-q:v",
                        "3",
                        str(jpg),
                    ]
                )
                if not jpg.is_file():
                    out[s] = ""
                    continue
                image = "data:image/jpeg;base64," + base64.b64encode(jpg.read_bytes()).decode()
                r = self.http.post(
                    f"{self.endpoint}/openai/deployments/{self.model}/chat/completions?api-version={CHAT_API}",
                    headers={"Authorization": f"Bearer {self.token()}"},
                    json={
                        "messages": [
                            {"role": "system", "content": READER},
                            {"role": "user", "content": [{"type": "image_url", "image_url": {"url": image}}]},
                        ],
                        "max_completion_tokens": 2000,
                        "reasoning_effort": "minimal",
                    },
                )
                r.raise_for_status()
                out[s] = r.json()["choices"][0]["message"].get("content") or ""
        return out


def qa_film(
    film: Path,
    cut: Cut,
    cues: list[dict],
    calls: list[dict],
    language: str,
    senses: Perception,
    names: list[str] | None = None,
) -> QAReport:
    """Listen to the film, read its captions, measure its level, and judge it against its plan."""
    names = names or []
    spoken, shown = expectations(cut, cues, calls)
    transcript = senses.listen(film, language) if spoken else []
    reads = senses.read(film, [s.middle for s in shown]) if shown else {}
    return judge(film.name, language, spoken, shown, transcript, reads, loudness(film, senses.ffmpeg), names)


def league_names(feed: dict) -> list[str]:
    """Every club and player name in a match's feed (the words a recogniser spells its own way)."""
    teams = [feed["teams"][side] for side in ("home", "away")]
    out = [t.get("name", "") for t in teams]
    out += [p.get("name", "") for t in teams for p in t.get("players", {}).values()]
    out += [p.get("name", "") for p in feed.get("players", {}).values()]
    return [n for n in out if n]
