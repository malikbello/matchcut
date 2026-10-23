"""The fan's reel: their moments as the match happens, playable with sound, clippable, shareable.

While a fan watches, every moment that matters to them (their club's goals and chances, or their
player's) lands in their reel as a short film: the moment's clip, rendered once for every fan and
captioned in their language, with its soundtrack mixed on first play (seconds) and cached. "Clip
that" asks for any stretch of play, rendered like moments. A share link opens exactly one clip,
publicly: an unguessable token signed with the server's key, so a link can be posted anywhere
without opening the rest of the Studio.

Pieces live in a PieceStore: a local folder in development, the `cuts` blob container on Azure.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import re
import tempfile
import threading
import time
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from matchcut_api.cuts import Film, file_film

log = logging.getLogger(__name__)
QA_TTL_S = 60  # a moment's QA verdict is read again after this long

KEY = re.compile(r"^(goal|conceded|chance)-\d{1,9}$|^window-\d{1,9}-\d{1,9}$")
ASPECT = re.compile(r"^(9x16|16x9)$")
MAX_WINDOW_MS = 30_000


class PieceStore(Protocol):
    def exists(self, match: str, aspect: str, name: str) -> bool: ...
    def path(self, match: str, aspect: str, name: str) -> Path | None: ...
    def put(self, match: str, aspect: str, name: str, src: Path) -> None: ...
    def film(self, match: str, aspect: str, name: str) -> Film | None: ...
    def manifest(self, match: str, aspect: str) -> dict[str, Any] | None: ...


class LocalPieces:
    def __init__(self, root: Path):
        self.root = root

    def _p(self, match: str, aspect: str, name: str) -> Path:
        return self.root / match / aspect / name

    def exists(self, match: str, aspect: str, name: str) -> bool:
        return self._p(match, aspect, name).is_file()

    def path(self, match: str, aspect: str, name: str) -> Path | None:
        p = self._p(match, aspect, name)
        return p if p.is_file() else None

    def put(self, match: str, aspect: str, name: str, src: Path) -> None:
        dest = self._p(match, aspect, name)
        dest.parent.mkdir(parents=True, exist_ok=True)
        src.replace(dest)

    def film(self, match: str, aspect: str, name: str) -> Film | None:
        p = self.path(match, aspect, name)
        return file_film(p) if p else None

    def manifest(self, match: str, aspect: str) -> dict[str, Any] | None:
        p = self.path(match, aspect, "manifest.json")
        return json.loads(p.read_text(encoding="utf-8")) if p else None


class BlobPieces:
    """Pieces in the `cuts` container under pieces/; reads go through a small local cache."""

    def __init__(self, container: Any, cache: Path):
        self.blobs, self.cache = container, cache

    def _name(self, match: str, aspect: str, name: str) -> str:
        return f"pieces/{match}/{aspect}/{name}"

    def exists(self, match: str, aspect: str, name: str) -> bool:
        return bool(self.blobs.get_blob_client(self._name(match, aspect, name)).exists())

    def path(self, match: str, aspect: str, name: str) -> Path | None:
        local = self.cache / match / aspect / name
        if local.is_file():
            return local
        b = self.blobs.get_blob_client(self._name(match, aspect, name))
        if not b.exists():
            return None
        local.parent.mkdir(parents=True, exist_ok=True)
        with local.open("wb") as f:
            b.download_blob().readinto(f)
        return local

    def put(self, match: str, aspect: str, name: str, src: Path) -> None:
        with src.open("rb") as f:
            self.blobs.upload_blob(self._name(match, aspect, name), f, overwrite=True)
        local = self.cache / match / aspect / name
        local.parent.mkdir(parents=True, exist_ok=True)
        src.replace(local)

    def film(self, match: str, aspect: str, name: str) -> Film | None:
        b = self.blobs.get_blob_client(self._name(match, aspect, name))
        if not b.exists():
            return None

        def read(start: int, end: int) -> Iterator[bytes]:
            return b.download_blob(offset=start, length=end - start + 1).chunks()

        return Film(b.get_blob_properties().size, read)

    def manifest(self, match: str, aspect: str) -> dict[str, Any] | None:
        p = self.path(match, aspect, "manifest.json")
        return json.loads(p.read_text(encoding="utf-8")) if p else None


# the caption kinds that tell each kind of moment (a goal against is still told as a goal)
CAPTION_KINDS = {"goal": {"goal"}, "conceded": {"goal"}, "chance": {"big_chance", "great_save"}}


def moment_caption(cues: list[dict], kind: str, t: int) -> dict | None:
    """The caption a moment's card shows: of the captions within 1.5 s (a goal can share its
    second with a momentum line), the one about this kind of moment, verified first, nearest."""
    near = [c for c in cues if abs(c["t_ms"] - t) <= 1500]
    wanted = CAPTION_KINDS.get(kind, set())
    return min(
        near,
        key=lambda c: (c.get("kind") not in wanted, c.get("status") != "verified", abs(c["t_ms"] - t)),
        default=None,
    )


@dataclass
class Reel:
    pieces: PieceStore
    data: Path  # feeds/, insights/, calls/, media/
    crowd: Path
    secret: bytes
    ffmpeg: str = "ffmpeg"
    # one mix per film at a time (a tap during a warm-up waits for it), and warm-ups one by one
    _locks: dict[str, threading.Lock] = field(default_factory=dict, repr=False)
    _guard: threading.Lock = field(default_factory=threading.Lock, repr=False)
    _warming: set[str] = field(default_factory=set, repr=False)
    _qa: dict[str, tuple[float, dict[str, Any] | None]] = field(default_factory=dict, repr=False)
    _warmer: ThreadPoolExecutor = field(
        default_factory=lambda: ThreadPoolExecutor(max_workers=1, thread_name_prefix="reel-warm"), repr=False
    )

    def _lock(self, name: str) -> threading.Lock:
        with self._guard:
            return self._locks.setdefault(name, threading.Lock())

    def warm(self, match: str, aspect: str, key: str, lang: str) -> None:
        """Mix a ready moment's film in the background as soon as the reel lists it, so it plays
        the moment the fan taps it (mixing takes seconds; nobody should watch a spinner)."""
        name = f"{match}/{aspect}/{key}.{lang}"
        with self._guard:
            if name in self._warming:
                return
            self._warming.add(name)
        self._warmer.submit(self._warm, name, match, aspect, key, lang)

    def _warm(self, name: str, match: str, aspect: str, key: str, lang: str) -> None:
        try:
            self.moment_film(match, aspect, key, lang)
        except Exception:  # a failed warm-up is not an error: the fan's own tap mixes it again
            log.warning("could not mix %s ahead of play", name, exc_info=True)
            with self._guard:
                self._warming.discard(name)

    def moments(
        self, match: str, focus: dict[str, str], lang: str, aspect: str, upto: int | None
    ) -> list[dict]:
        """The fan's moments so far: a goal for them, a goal against (their club), their chances."""
        from matchcut_editing.edl import pick_moments  # noqa: PLC0415
        from matchcut_editing.inputs import best_cues, read_feed  # noqa: PLC0415

        # every fan's reel polls this: the feed and captions only (no voices are needed to list)
        feed = read_feed(self.data, match)
        cues = best_cues(self.data / "insights" / f"{match}.jsonl", lang)
        out = []
        for p in pick_moments(feed, cues, focus):
            if upto is not None and p["t"] > upto:
                break
            key = f"{p['kind']}-{p['t']}"
            cue = moment_caption(cues, p["kind"], p["t"])
            out.append(
                {
                    "key": key,
                    "kind": p["kind"],
                    "t": p["t"],
                    "who": p.get("who"),
                    "clock": cue["clock"] if cue else None,
                    "text": cue["text"] if cue else None,
                    "verified": bool(cue and cue.get("status") == "verified"),
                    "ready": self.pieces.exists(match, aspect, f"{key}.{lang}.mp4"),
                    "qa": self.qa(match, aspect, key, lang),
                }
            )
        return out

    def qa(self, match: str, aspect: str, key: str, lang: str) -> dict[str, Any] | None:
        """The QA agent's verdict on a moment's film in one language, in brief (None until it has
        checked it): lines heard, captions read, the level. Remembered for a minute."""
        name = f"{key}.{lang}.qa.json"
        held = self._qa.get(name)
        if held and time.monotonic() - held[0] < QA_TTL_S:
            return held[1]
        summary = None
        path = self.pieces.path(match, aspect, name)
        if path is not None:
            try:
                r = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                r = None
            if isinstance(r, dict):
                lines, caps = r.get("lines", []), r.get("captions", [])
                summary = {
                    "passed": bool(r.get("passed")),
                    "heard": f"{sum(1 for x in lines if x.get('heard'))}/{len(lines)}",
                    "read": f"{sum(1 for x in caps if x.get('read'))}/{len(caps)}",
                    "lufs": r.get("lufs"),
                    "words": not any(x.get("check") == "voiced" for x in lines),
                }
        self._qa[name] = (time.monotonic(), summary)
        return summary

    def moment_film(self, match: str, aspect: str, key: str, lang: str) -> Film | None:
        """A moment as a short film with its soundtrack; mixed once (ahead of play, or on first
        play), then cached."""
        name = f"{key}.{lang}.share.mp4"
        with self._lock(f"{match}/{aspect}/{name}"):
            film = self.pieces.film(match, aspect, name)
            if film:
                return film
            clip = self.pieces.path(match, aspect, f"{key}.{lang}.mp4")
            manifest = self.pieces.manifest(match, aspect)
            if clip is None or manifest is None:
                return None
            from matchcut_editing.assembly import assemble_cut  # noqa: PLC0415
            from matchcut_editing.edl import moment_cut  # noqa: PLC0415
            from matchcut_editing.inputs import load  # noqa: PLC0415

            inp = load(self.data, match, lang)
            packages = {int(t): d for t, d in manifest["packages"].items()}
            cut = moment_cut(
                inp.feed, inp.cues, inp.calls, key, language=lang, aspect=aspect,
                package_durations=packages, clip_durations=inp.durations,
            )  # fmt: skip
            with tempfile.TemporaryDirectory() as tmp:
                made = assemble_cut(cut, [clip], self.data / "media", self.crowd, Path(tmp), self.ffmpeg)
                self.pieces.put(match, aspect, name, made)
            return self.pieces.film(match, aspect, name)

    # ---------------------------------------------------------------- public share links
    def share_token(self, match: str, aspect: str, key: str, lang: str) -> str:
        body = base64.urlsafe_b64encode(json.dumps([match, aspect, key, lang]).encode()).rstrip(b"=")
        sig = hmac.new(self.secret, body, hashlib.sha256).digest()[:16]
        return f"{body.decode()}.{base64.urlsafe_b64encode(sig).rstrip(b'=').decode()}"

    def read_token(self, token: str) -> tuple[str, str, str, str] | None:
        try:
            body, sig = token.split(".")
            want = hmac.new(self.secret, body.encode(), hashlib.sha256).digest()[:16]
            got = base64.urlsafe_b64decode(sig + "=" * (-len(sig) % 4))
            if not hmac.compare_digest(want, got):
                return None
            match, aspect, key, lang = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
        except (ValueError, TypeError):
            return None
        if not (ASPECT.match(aspect) and KEY.match(key)):
            return None
        return match, aspect, key, lang
