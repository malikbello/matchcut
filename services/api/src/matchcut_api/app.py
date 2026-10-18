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
import hashlib
import hmac
import json
import os
import re
import secrets
import time
from collections import defaultdict
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from limits import parse
from limits.storage import MemoryStorage
from limits.strategies import MovingWindowRateLimiter
from matchcut_contracts import Cue, CueStatus
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse
from starlette.middleware.sessions import SessionMiddleware

MATCH_ID = re.compile(r"^[a-z]{3}-[a-z]{3}-\d{1,6}$")
LANG = re.compile(r"^[a-z]{2,3}(-[A-Z]{2})?$")  # BCP 47: en, en-NG, pcm, ar, yo
AUDIO_NAME = re.compile(r"^CU-\d{5}-[a-z]{2,3}(-[A-Z]{2})?\.mp3$")
COOKIE = "mc_session"
SESSION_TTL_S = 12 * 3600
# 'wasm-unsafe-eval' lets the 3D show camera compile its meshopt WebAssembly decoder; it does not
# allow string evaluation of JavaScript
CSP = (
    "default-src 'self'; script-src 'self' 'wasm-unsafe-eval'; style-src 'self'; font-src 'self'; "
    "img-src 'self' data:; media-src 'self' blob:; "
    "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
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


class SessionRequest(BaseModel):
    code: str = Field(min_length=4, max_length=64)


# ---------------------------------------------------------------- app


def create_app(settings: Settings | None = None) -> FastAPI:
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
