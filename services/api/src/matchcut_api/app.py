"""Matchcut API: access sessions, cue streams over SSE, and the Studio screen.

- ``POST /api/session`` exchanges an access code for a signed, HttpOnly,
  SameSite=Strict session cookie (Starlette ``SessionMiddleware``). EventSource
  cannot send headers, and codes must never sit in URLs or logs.
- ``GET /api/matches`` lists matches with cues.
- ``GET /api/matches/{id}/cues`` returns all cues for one language (for seeking).
- ``GET /api/matches/{id}/stream`` replays cues as Server-Sent Events on match time
  (``sse-starlette``: keep-alive pings, disconnect handling). The live lane feeds
  the same stream from Event Hubs.
Every response carries strict security headers. Clients are rate limited with the
``limits`` library (moving window; in-memory now, Redis when scaled out).
"""

from __future__ import annotations

import asyncio
import gzip
import hashlib
import hmac
import json
import os
import re
import secrets
import shutil
import time
from collections import defaultdict
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from limits import parse
from limits.storage import MemoryStorage
from limits.strategies import MovingWindowRateLimiter
from matchcut_contracts import Cue, CueStatus
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse
from starlette.middleware.sessions import SessionMiddleware

from matchcut_api.cuts import (
    ASPECTS,
    CUT_ID,
    CUT_LANGUAGES,
    Assembler,
    AzureCuts,
    CutRequest,
    CutStore,
    LocalCuts,
)

MATCH_ID = re.compile(r"^[a-z]{3}-[a-z]{3}-\d{1,6}$")
LANG = re.compile(r"^[a-z]{2,3}(-[A-Z]{2})?$")  # BCP 47: en, en-NG, pcm, ar, yo
AUDIO_NAME = re.compile(r"^(CU|CA)-\d{5}-[a-z]{2,3}(-[A-Z]{2})?\.mp3$")  # cue lines and play-by-play calls
COOKIE = "mc_session"
SESSION_TTL_S = 12 * 3600
# 'wasm-unsafe-eval' lets the 3D show camera compile its meshopt WebAssembly decoder (it does not
# allow string evaluation of JavaScript); blob: lets the model loader decode the textures embedded in
# the character file (blob URLs can only be created by this page)
CSP = (
    "default-src 'self'; script-src 'self' 'wasm-unsafe-eval'; style-src 'self'; font-src 'self'; "
    "img-src 'self' data: blob:; media-src 'self' blob:; "
    "connect-src 'self' blob:; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
)


@dataclass
class Settings:
    cues_dir: Path
    media_dir: Path
    feeds_dir: Path
    studio_dir: Path | None
    code_hashes: frozenset[str]
    secret: str
    requests_per_minute: int = 120
    streams_per_client: int = 3
    secure_cookie: bool = True
    calls_dir: Path = Path("out/calls")
    storage_account: str | None = None  # Azure: fan cuts via the queue-triggered render job
    render_code: str | None = None  # local development: the code the background renderer signs in with
    cuts_dir: Path = Path("out/cuts")
    data_dir: Path = Path("out")  # feeds/, insights/, calls/, media/ (assembling cuts from pieces)
    pieces_dir: Path = Path("out/pieces")  # local development: the job's pieces
    port: int = 8080
    cuts_per_hour: int = 6
    cut_chunks: int = 10  # slices rendered in parallel per cut on Azure

    @classmethod
    def from_env(cls) -> Settings:
        codes = os.environ.get("MATCHCUT_ACCESS_CODE_SHA256", "")
        studio = os.environ.get("MATCHCUT_STUDIO_DIR", "apps/studio")
        return cls(
            cues_dir=Path(os.environ.get("MATCHCUT_CUES_DIR", "out/insights")),
            media_dir=Path(os.environ.get("MATCHCUT_MEDIA_DIR", "out/media")),
            feeds_dir=Path(os.environ.get("MATCHCUT_FEEDS_DIR", "out/feeds")),
            studio_dir=Path(studio) if studio and Path(studio).is_dir() else None,
            code_hashes=frozenset(h.strip().lower() for h in codes.split(",") if h.strip()),
            secret=os.environ.get("MATCHCUT_SESSION_SECRET") or secrets.token_urlsafe(32),
            secure_cookie=os.environ.get("MATCHCUT_INSECURE_COOKIE") != "1",
            calls_dir=Path(os.environ.get("MATCHCUT_CALLS_DIR", "out/calls")),
            storage_account=os.environ.get("MATCHCUT_STORAGE_ACCOUNT") or None,
            render_code=os.environ.get("MATCHCUT_RENDER_CODE") or None,
            cuts_dir=Path(os.environ.get("MATCHCUT_CUTS_DIR", "out/cuts")),
            data_dir=Path(os.environ.get("MATCHCUT_DATA", "out")),
            pieces_dir=Path(os.environ.get("MATCHCUT_PIECES_DIR", "out/pieces")),
            port=int(os.environ.get("PORT", "8080")),
            cut_chunks=int(os.environ.get("MATCHCUT_CUT_CHUNKS", "10")),
        )


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def client_id(request: Request) -> str:
    return request.client.host if request.client else "unknown"


# ---------------------------------------------------------------- data access


def load_cues(settings: Settings, match_id: str, lang: str) -> list[Cue]:
    if not MATCH_ID.match(match_id) or not LANG.match(lang):
        raise HTTPException(404, "match not found")
    path = settings.cues_dir / f"{match_id}.jsonl"
    if not path.is_file():
        raise HTTPException(404, "match not found")
    cues = [Cue.model_validate_json(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
    # the latest state per moment wins: a verified line replaces the plain card for that language
    best: dict[str, Cue] = {}
    for c in cues:
        if c.language == lang or (c.language == "en" and c.status == CueStatus.PLAIN):
            prev = best.get(c.moment_id)
            if prev is None or _rank(c, lang) > _rank(prev, lang):
                best[c.moment_id] = c
    return sorted(best.values(), key=lambda c: c.t_ms)


def _rank(c: Cue, lang: str) -> int:
    return {CueStatus.PLAIN: 0, CueStatus.REJECTED: -1, CueStatus.VERIFIED: 2}[c.status] + (
        c.language == lang
    )


class CutBody(BaseModel):
    match: str = Field(max_length=24)
    lang: str = Field(default="en", max_length=8)
    aspect: str = Field(default="9x16", max_length=5)
    side: str | None = Field(default=None, max_length=4)
    player: str | None = Field(default=None, max_length=60)


class SessionRequest(BaseModel):
    code: str = Field(min_length=4, max_length=64)


# ---------------------------------------------------------------- app


RANGE = re.compile(r"^bytes=(\d*)-(\d*)$")


def byte_range(header: str | None, size: int) -> tuple[int, int] | None:
    """One `bytes=a-b` range, clamped to the file; None means the whole file. 416 if unsatisfiable."""
    m = RANGE.match(header.strip()) if header else None
    if not m or not (m[1] or m[2]):
        return None
    if m[1]:
        start, end = int(m[1]), min(int(m[2]) if m[2] else size - 1, size - 1)
    else:  # the last N bytes
        start, end = max(size - int(m[2]), 0), size - 1
    if start > end or start >= size:
        raise HTTPException(416, "range not satisfiable", headers={"Content-Range": f"bytes */{size}"})
    return start, end


def create_app(settings: Settings | None = None, cuts: CutStore | None = None) -> FastAPI:
    s = settings or Settings.from_env()
    limiter = MovingWindowRateLimiter(MemoryStorage())
    per_client = parse(f"{s.requests_per_minute}/minute")
    open_streams: dict[str, int] = defaultdict(int)
    app = FastAPI(title="Matchcut API", version="0.2.0", docs_url=None, redoc_url=None, openapi_url=None)

    @app.middleware("http")
    async def guard(request: Request, call_next):  # type: ignore[no-untyped-def]
        if request.url.path.startswith("/api/") and not limiter.hit(per_client, client_id(request)):
            return JSONResponse({"detail": "rate limit"}, status_code=429, headers={"Retry-After": "60"})
        response: Response = await call_next(request)
        response.headers["Content-Security-Policy"] = CSP
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        path = request.url.path
        if not path.startswith(("/api/", "/media/")) and "Cache-Control" not in response.headers:
            response.headers["Cache-Control"] = (
                "no-cache"  # Studio files revalidate, so a release is seen at once
            )
        return response

    # added after the guard so it runs first and the session is ready for the routes
    app.add_middleware(
        SessionMiddleware,
        secret_key=s.secret,
        session_cookie=COOKIE,
        max_age=SESSION_TTL_S,
        same_site="strict",
        https_only=s.secure_cookie,
    )

    def require_session(request: Request) -> None:
        if not request.session.get("granted") or request.session.get("exp", 0) < time.time():
            raise HTTPException(401, "access code required")

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/api/session")
    def open_session(body: SessionRequest, request: Request) -> dict[str, bool]:
        if not s.code_hashes or not any(hmac.compare_digest(sha256(body.code), h) for h in s.code_hashes):
            raise HTTPException(401, "invalid access code")
        request.session.clear()
        request.session.update({"granted": True, "exp": int(time.time()) + SESSION_TTL_S})
        return {"ok": True}

    @app.get("/api/matches", dependencies=[Depends(require_session)])
    def matches() -> list[dict[str, str]]:
        if not s.cues_dir.is_dir():
            return []
        out = []
        for p in sorted(s.cues_dir.glob("*.jsonl")):
            if MATCH_ID.match(p.stem):
                media = s.media_dir / p.stem / "clip.mp4"
                has_feed = (s.feeds_dir / f"{p.stem}.json.gz").is_file()
                out.append(
                    {
                        "match_id": p.stem,
                        "video": f"/media/{p.stem}/clip.mp4" if media.is_file() else "",
                        "feed": f"/api/matches/{p.stem}/feed" if has_feed else "",
                    }
                )
        return out

    @app.get("/api/matches/{match_id}/feed", dependencies=[Depends(require_session)])
    def feed(match_id: str) -> Response:
        """The 5 Hz positions feed, served pre-compressed."""
        path = s.feeds_dir / f"{match_id}.json.gz"
        if not MATCH_ID.match(match_id) or not path.is_file():
            raise HTTPException(404, "not found")
        return Response(
            path.read_bytes(),
            media_type="application/json",
            headers={"Content-Encoding": "gzip", "Cache-Control": "private, no-cache"},
        )

    @app.get("/api/matches/{match_id}/cues", dependencies=[Depends(require_session)])
    def cues(match_id: str, lang: str = "en") -> list[dict]:
        return [json.loads(c.model_dump_json()) for c in load_cues(s, match_id, lang)]

    @app.get("/api/matches/{match_id}/calls", dependencies=[Depends(require_session)])
    def calls(match_id: str, lang: str = "en") -> list[dict]:
        """Play-by-play calls (build-up, goal, save, miss) for one language, in match order."""
        path = s.calls_dir / f"{match_id}.json"
        if not MATCH_ID.match(match_id) or not LANG.match(lang) or not path.is_file():
            return []
        rows = json.loads(path.read_text(encoding="utf-8"))
        return [r for r in rows if r.get("language") == lang]

    @app.get("/api/matches/{match_id}/stream", dependencies=[Depends(require_session)])
    async def stream(request: Request, match_id: str, lang: str = "en", from_ms: int = 0, speed: float = 1.0):
        all_cues = [c for c in load_cues(s, match_id, lang) if c.t_ms >= from_ms]
        speed = min(max(speed, 0.25), 60.0)
        who = client_id(request)
        if open_streams[who] >= s.streams_per_client:
            raise HTTPException(429, "too many open streams")
        open_streams[who] += 1

        async def events() -> AsyncIterator[dict[str, str]]:
            try:
                start = time.monotonic()
                for c in all_cues:
                    wait = start + (c.t_ms - from_ms) / 1000 / speed - time.monotonic()
                    if wait > 0:
                        await asyncio.sleep(wait)
                    yield {"event": "cue", "id": c.cue_id, "data": c.model_dump_json()}
                yield {"event": "end", "data": "{}"}
            finally:
                open_streams[who] -= 1

        return EventSourceResponse(events(), ping=15, headers={"Cache-Control": "no-store"})

    @app.get("/media/audio/{match_id}/{name}", dependencies=[Depends(require_session)])
    def audio(match_id: str, name: str) -> FileResponse:
        """A spoken, verified line (written by the insights voice step)."""
        path = s.media_dir / "audio" / match_id / name
        if not MATCH_ID.match(match_id) or not AUDIO_NAME.match(name) or not path.is_file():
            raise HTTPException(404, "not found")
        return FileResponse(
            path, media_type="audio/mpeg", headers={"Cache-Control": "private, max-age=86400"}
        )

    # ---------------------------------------------------------------- fan cuts
    crowd = (s.studio_dir or Path("apps/studio")) / "assets" / "audio" / "crowd"
    assembler = Assembler(s.data_dir, crowd, shutil.which("ffmpeg") or "ffmpeg")
    store = cuts
    if store is None and s.storage_account:
        store = AzureCuts(s.storage_account, s.cut_chunks, assembler)
    elif store is None and s.render_code:
        store = LocalCuts(s.cuts_dir, f"http://127.0.0.1:{s.port}", s.render_code, s.pieces_dir, assembler)
    per_hour = parse(f"{s.cuts_per_hour}/hour")

    def players_of(match_id: str) -> set[str]:
        path = s.feeds_dir / f"{match_id}.json.gz"
        if not path.is_file():
            return set()
        feed = json.loads(gzip.decompress(path.read_bytes()))
        return {p["name"] for p in feed.get("players", {}).values()}

    @app.post("/api/cuts", dependencies=[Depends(require_session)])
    def make_cut(body: CutBody, request: Request) -> dict[str, str]:
        """Ask for a personal highlight film: a club (side) or a player, a language, an aspect."""
        if store is None:
            raise HTTPException(503, "fan cuts are not configured here")
        if not MATCH_ID.match(body.match) or body.lang not in CUT_LANGUAGES or body.aspect not in ASPECTS:
            raise HTTPException(422, "invalid request")
        if (body.side is None) == (body.player is None) or (body.side and body.side not in ("home", "away")):
            raise HTTPException(422, "choose a side or a player")
        if body.player and body.player not in players_of(body.match):
            raise HTTPException(422, "unknown player")
        if not limiter.hit(per_hour, f"cuts:{client_id(request)}"):
            raise HTTPException(429, "too many cuts for now")
        cut_id = store.submit(CutRequest(body.match, body.lang, body.aspect, body.side, body.player))
        return {"id": cut_id, "status": "queued"}

    @app.get("/api/cuts/{cut_id}", dependencies=[Depends(require_session)])
    def cut_status(cut_id: str) -> dict:
        st = store.status(cut_id) if store and CUT_ID.match(cut_id) else None
        if st is None:
            raise HTTPException(404, "not found")
        return st

    @app.get("/media/cuts/{cut_id}.mp4", dependencies=[Depends(require_session)])
    def cut_film(cut_id: str, request: Request) -> StreamingResponse:
        """The finished film, with byte ranges so players can seek."""
        film = store.film(cut_id) if store and CUT_ID.match(cut_id) else None
        if film is None:
            raise HTTPException(404, "not found")
        headers = {"Cache-Control": "private, max-age=3600", "Accept-Ranges": "bytes"}
        span = byte_range(request.headers.get("range"), film.size)
        if span is None:
            headers["Content-Length"] = str(film.size)
            return StreamingResponse(film.read(0, film.size - 1), media_type="video/mp4", headers=headers)
        start, end = span
        headers["Content-Range"] = f"bytes {start}-{end}/{film.size}"
        headers["Content-Length"] = str(end - start + 1)
        return StreamingResponse(
            film.read(start, end), status_code=206, media_type="video/mp4", headers=headers
        )

    @app.get("/media/{match_id}/clip.mp4", dependencies=[Depends(require_session)])
    def media(match_id: str) -> FileResponse:
        path = s.media_dir / match_id / "clip.mp4"
        if not MATCH_ID.match(match_id) or not path.is_file():
            raise HTTPException(404, "not found")
        return FileResponse(path, media_type="video/mp4")

    if s.studio_dir is not None:
        app.mount("/", StaticFiles(directory=s.studio_dir, html=True), name="studio")
    return app


def main() -> None:
    import uvicorn  # noqa: PLC0415 - server dependency only needed when serving

    uvicorn.run(
        create_app(), host=os.environ.get("HOST", "127.0.0.1"), port=int(os.environ.get("PORT", "8080"))
    )
