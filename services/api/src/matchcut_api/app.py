"""Matchcut API: access sessions, cue streams over SSE, and the Studio screen.

- ``POST /api/session`` exchanges a judge/fan access code for a signed, HttpOnly,
  SameSite=Strict session cookie (EventSource cannot send headers, and codes must
  never sit in URLs or logs).
- ``GET /api/matches`` lists matches with cues.
- ``GET /api/matches/{id}/cues`` returns all cues for one language (for seeking).
- ``GET /api/matches/{id}/stream`` replays cues as Server-Sent Events on match time.
  The live lane feeds the same stream from Event Hubs.
Every response carries strict security headers; each client is rate limited.
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
from collections import defaultdict, deque
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from matchcut_contracts import Cue, CueStatus
from pydantic import BaseModel, Field

MATCH_ID = re.compile(r"^[a-z]{3}-[a-z]{3}-\d{1,6}$")
LANG = re.compile(r"^[a-z]{2}$")
COOKIE = "mc_session"
SESSION_TTL_S = 12 * 3600
CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self' https://fonts.googleapis.com; "
    "font-src https://fonts.gstatic.com; img-src 'self' data:; media-src 'self' blob:; "
    "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
)


@dataclass
class Settings:
    cues_dir: Path
    media_dir: Path
    studio_dir: Path | None
    code_hashes: frozenset[str]
    secret: bytes
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
            studio_dir=Path(studio) if studio and Path(studio).is_dir() else None,
            code_hashes=frozenset(h.strip().lower() for h in codes.split(",") if h.strip()),
            secret=os.environ.get("MATCHCUT_SESSION_SECRET", "").encode() or secrets.token_bytes(32),
            secure_cookie=os.environ.get("MATCHCUT_INSECURE_COOKIE") != "1",
        )


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


# ---------------------------------------------------------------- sessions


def sign_session(secret: bytes, now: float | None = None) -> str:
    expires = int((now or time.time()) + SESSION_TTL_S)
    nonce = secrets.token_hex(8)
    body = f"{expires}.{nonce}"
    mac = hmac.new(secret, body.encode(), hashlib.sha256).hexdigest()
    return f"{body}.{mac}"


def session_valid(secret: bytes, token: str | None, now: float | None = None) -> bool:
    if not token or token.count(".") != 2:
        return False
    expires, nonce, mac = token.split(".")
    good = hmac.new(secret, f"{expires}.{nonce}".encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(mac, good) and expires.isdigit() and int(expires) > (now or time.time())


# ---------------------------------------------------------------- rate limits


@dataclass
class Limiter:
    per_minute: int
    max_streams: int
    hits: dict[str, deque[float]] = field(default_factory=lambda: defaultdict(deque))
    streams: dict[str, int] = field(default_factory=lambda: defaultdict(int))

    def allow(self, client: str, now: float | None = None) -> bool:
        t = now or time.monotonic()
        q = self.hits[client]
        while q and t - q[0] > 60:
            q.popleft()
        if len(q) >= self.per_minute:
            return False
        q.append(t)
        return True


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
    limiter = Limiter(s.requests_per_minute, s.streams_per_client)
    app = FastAPI(title="Matchcut API", version="0.1.0", docs_url=None, redoc_url=None, openapi_url=None)

    @app.middleware("http")
    async def guard(request: Request, call_next):  # type: ignore[no-untyped-def]
        if request.url.path.startswith("/api/") and not limiter.allow(client_id(request)):
            return JSONResponse({"detail": "rate limit"}, status_code=429, headers={"Retry-After": "60"})
        response: Response = await call_next(request)
        response.headers["Content-Security-Policy"] = CSP
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return response

    def require_session(request: Request) -> None:
        if not session_valid(s.secret, request.cookies.get(COOKIE)):
            raise HTTPException(401, "access code required")

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/api/session")
    def open_session(body: SessionRequest, response: Response) -> dict[str, bool]:
        if not s.code_hashes or not any(hmac.compare_digest(sha256(body.code), h) for h in s.code_hashes):
            raise HTTPException(401, "invalid access code")
        response.set_cookie(
            COOKIE,
            sign_session(s.secret),
            max_age=SESSION_TTL_S,
            httponly=True,
            secure=s.secure_cookie,
            samesite="strict",
            path="/",
        )
        return {"ok": True}

    @app.get("/api/matches", dependencies=[Depends(require_session)])
    def matches() -> list[dict[str, str]]:
        if not s.cues_dir.is_dir():
            return []
        out = []
        for p in sorted(s.cues_dir.glob("*.jsonl")):
            if MATCH_ID.match(p.stem):
                media = s.media_dir / p.stem / "clip.mp4"
                out.append(
                    {"match_id": p.stem, "video": f"/media/{p.stem}/clip.mp4" if media.is_file() else ""}
                )
        return out

    @app.get("/api/matches/{match_id}/cues", dependencies=[Depends(require_session)])
    def cues(match_id: str, lang: str = "en") -> list[dict]:
        return [json.loads(c.model_dump_json()) for c in load_cues(s, match_id, lang)]

    @app.get("/api/matches/{match_id}/stream", dependencies=[Depends(require_session)])
    async def stream(request: Request, match_id: str, lang: str = "en", from_ms: int = 0, speed: float = 1.0):
        all_cues = [c for c in load_cues(s, match_id, lang) if c.t_ms >= from_ms]
        speed = min(max(speed, 0.25), 60.0)
        who = client_id(request)
        if limiter.streams[who] >= limiter.max_streams:
            raise HTTPException(429, "too many open streams")
        limiter.streams[who] += 1

        async def events() -> AsyncIterator[str]:
            try:
                yield "retry: 3000\n\n"
                start, last_beat = time.monotonic(), time.monotonic()
                for c in all_cues:
                    due = start + (c.t_ms - from_ms) / 1000 / speed
                    while (wait := due - time.monotonic()) > 0:
                        if await request.is_disconnected():
                            return
                        await asyncio.sleep(min(wait, 1.0))
                        if time.monotonic() - last_beat > 15:
                            last_beat = time.monotonic()
                            yield ": keep-alive\n\n"
                    yield f"id: {c.cue_id}\nevent: cue\ndata: {c.model_dump_json()}\n\n"
                yield "event: end\ndata: {}\n\n"
            finally:
                limiter.streams[who] -= 1

        return StreamingResponse(
            events(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
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
