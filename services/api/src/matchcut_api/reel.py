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
import re
import tempfile
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from matchcut_api.cuts import Film, file_film

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


@dataclass
class Reel:
    pieces: PieceStore
    data: Path  # feeds/, insights/, calls/, media/
    crowd: Path
    secret: bytes
    ffmpeg: str = "ffmpeg"

    def moments(
        self, match: str, focus: dict[str, str], lang: str, aspect: str, upto: int | None
    ) -> list[dict]:
        """The fan's moments so far: a goal for them, a goal against (their club), their chances."""
        from matchcut_editing.edl import pick_moments  # noqa: PLC0415
        from matchcut_editing.inputs import load  # noqa: PLC0415

        inp = load(self.data, match, lang)
        cue_at = {c["t_ms"]: c for c in inp.cues}
        out = []
        for p in pick_moments(inp.feed, inp.cues, focus):
            if upto is not None and p["t"] > upto:
                break
            key = f"{p['kind']}-{p['t']}"
            cue = next((c for t, c in cue_at.items() if abs(t - p["t"]) <= 1500), None)
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
                }
            )
        return out

    def moment_film(self, match: str, aspect: str, key: str, lang: str) -> Film | None:
        """A moment as a short film with its soundtrack; mixed on first play, then cached."""
        name = f"{key}.{lang}.share.mp4"
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
