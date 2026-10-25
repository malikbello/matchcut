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
import io
import json
import os
import re
import secrets
import shutil
import tempfile
import time
from collections import defaultdict
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path

import segno
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
    Film,
    LocalCuts,
)
from matchcut_api.factory import BusyError, DiskBlobs, Factory, LocalRunner, RationedError
from matchcut_api.reel import MAX_WINDOW_MS, BlobPieces, LocalPieces, Reel

MATCH_ID = re.compile(r"^[a-z]{3}-[a-z]{3}-\d{1,6}$")
LANG = re.compile(r"^[a-z]{2,3}(-[A-Z]{2})?$")  # BCP 47: en, en-NG, pcm, ar, yo
AUDIO_NAME = re.compile(r"^(CU|CA|CD)-\d{5}-[a-z]{2,3}(-[A-Z]{2})?\.mp3$")  # cue lines and play-by-play calls
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
    proxy_hops: int = 0  # reverse proxies in front of the app (1 behind the Container Apps ingress)
    factory_cooldown_s: int = 1800  # Recap Factory runs cost Azure credit: one per half hour
    factory_runs_per_day: int = 6

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
            proxy_hops=int(os.environ.get("MATCHCUT_PROXY_HOPS", "0")),
            factory_cooldown_s=int(os.environ.get("MATCHCUT_FACTORY_COOLDOWN_S", "1800")),
            factory_runs_per_day=int(os.environ.get("MATCHCUT_FACTORY_RUNS_PER_DAY", "6")),
        )


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def client_id(request: Request) -> str:
    """Who is calling, for rate limits. Behind a proxy every socket comes from the proxy, which
    appends the caller's address to X-Forwarded-For: the entry `proxy_hops` from the right is the
    caller, and entries further left are whatever the client sent (never trusted)."""
    hops = getattr(request.app.state, "proxy_hops", 0)
    if hops:
        chain = [h.strip() for h in request.headers.get("x-forwarded-for", "").split(",") if h.strip()]
        if len(chain) >= hops:
            return chain[-hops]
    return request.client.host if request.client else "unknown"


def public_base(request: Request) -> str:
    """The site's address for links that leave it (share cards, QR codes). The ingress ends TLS,
    so the app sees http; X-Forwarded-Proto names the scheme the visitor used. Only the scheme is
    taken from it: a spoofed header changes nothing but the links in the spoofer's own response."""
    base = str(request.base_url).rstrip("/")
    if request.headers.get("x-forwarded-proto", "").lower() == "https" and base.startswith("http://"):
        base = "https://" + base.removeprefix("http://")
    return base


def qr_svg(url: str) -> bytes:
    """A link as a QR code (segno): an SVG in the brand's ink on white, with a quiet zone."""
    out = io.BytesIO()
    segno.make(url, error="m").save(
        out, kind="svg", scale=8, border=2, dark="#07090d", light="#ffffff", xmldecl=False
    )
    return out.getvalue()


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


class ClipBody(BaseModel):
    start: int = Field(ge=0, le=20_000_000)  # match ms
    end: int = Field(ge=0, le=20_000_000)
    aspect: str = Field(default="9x16", max_length=5)


class FactoryBody(BaseModel):
    aspect: str = "9x16"


class ShareBody(BaseModel):
    match: str = Field(max_length=24)
    aspect: str = Field(default="9x16", max_length=5)
    key: str = Field(max_length=40)
    lang: str = Field(default="en", max_length=8)


REEL_ASPECT = re.compile(r"^(9x16|16x9)$")
REEL_KEY = re.compile(r"^(goal|conceded|chance)-\d{1,9}$|^window-\d{1,9}-\d{1,9}$")
MOMENT_FILE = re.compile(
    r"^(?P<key>(?:goal|conceded|chance)-\d{1,9}|window-\d{1,9}-\d{1,9})(?:\.(?P<lang>[a-zA-Z-]{2,6}))?\.(?P<ext>mp4|jpg)$"
)


def film_response(film: Film, request: Request, public: bool = False) -> StreamingResponse:
    """A film with byte ranges, so players can seek."""
    cache = "public, max-age=86400" if public else "private, max-age=3600"
    headers = {"Cache-Control": cache, "Accept-Ranges": "bytes"}
    span = byte_range(request.headers.get("range"), film.size)
    if span is None:
        headers["Content-Length"] = str(film.size)
        return StreamingResponse(film.read(0, film.size - 1), media_type="video/mp4", headers=headers)
    start, end = span
    headers["Content-Range"] = f"bytes {start}-{end}/{film.size}"
    headers["Content-Length"] = str(end - start + 1)
    return StreamingResponse(film.read(start, end), status_code=206, media_type="video/mp4", headers=headers)


def share_page(base: str, token: str, found: tuple[str, str, str, str]) -> str:
    """A shared clip's page: the film, plus Open Graph and Twitter tags so chats show a player."""
    _match, aspect, key, _lang = found
    kind = key.split("-")[0]
    title = {"goal": "Goal", "conceded": "Goal", "chance": "Big chance"}.get(kind, "Clip")
    video = f"{base}/s/{token}.mp4"
    poster = f"{base}/s/{token}.jpg"  # chats (WhatsApp, iMessage, Slack) preview the image, not the video
    w, h = (720, 1280) if aspect == "9x16" else (1280, 720)
    desc = "Every fan's cut. Synthetic match, every line verified."
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title} | Matchcut</title>
<meta property="og:type" content="video.other"><meta property="og:title" content="{title} | Matchcut">
<meta property="og:description" content="{desc}"><meta property="og:url" content="{base}/s/{token}">
<meta property="og:video" content="{video}"><meta property="og:video:secure_url" content="{video}">
<meta property="og:video:type" content="video/mp4"><meta property="og:video:width" content="{w}">
<meta property="og:video:height" content="{h}"><meta name="twitter:card" content="player">
<meta property="og:image" content="{poster}"><meta property="og:image:width" content="{w}">
<meta property="og:image:height" content="{h}"><meta name="twitter:image" content="{poster}">
<meta name="twitter:title" content="{title} | Matchcut"><meta name="twitter:player:stream" content="{video}">
<link rel="stylesheet" href="/share.css"></head>
<body><main class="share"><div class="mark">MATCH<span>C</span>UT</div>
<video src="/s/{token}.mp4" poster="/s/{token}.jpg" controls playsinline autoplay muted loop></video>
<p>{desc}</p></main></body></html>"""


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
    app.state.proxy_hops = s.proxy_hops

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

    def featured(match_id: str, focus: dict[str, str]) -> bool:
        """A focus with a story: a club, or a player with a moment of their own (else no film)."""
        from matchcut_editing.edl import featured_focuses  # noqa: PLC0415
        from matchcut_editing.inputs import best_cues, load_feed  # noqa: PLC0415

        feed = load_feed(s.feeds_dir / f"{match_id}.json.gz")
        return bool(featured_focuses(feed, best_cues(s.cues_dir / f"{match_id}.jsonl", "en"), [focus]))

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
        if body.player and not featured(body.match, {"player": body.player}):
            raise HTTPException(422, f"{body.player} has no moments in this match")
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
        return film_response(film, request)

    # ---------------------------------------------------------------- the fan's reel
    reel = Reel(
        pieces=(
            # the image's own folders are read-only for the app's user: the cache lives in temp
            BlobPieces(store.blobs, Path(tempfile.gettempdir()) / "matchcut-piece-cache")
            if isinstance(store, AzureCuts)
            else LocalPieces(s.pieces_dir)
        ),
        data=s.data_dir,
        crowd=crowd,
        secret=s.secret.encode(),
        ffmpeg=shutil.which("ffmpeg") or "ffmpeg",
    )

    def focus_of(side: str | None, player: str | None, match_id: str) -> dict[str, str]:
        if (side is None) == (player is None) or (side and side not in ("home", "away")):
            raise HTTPException(422, "choose a side or a player")
        if player and player not in players_of(match_id):
            raise HTTPException(422, "unknown player")
        return {"side": side} if side else {"player": player or ""}

    @app.get("/api/matches/{match_id}/reel", dependencies=[Depends(require_session)])
    def match_reel(
        match_id: str,
        side: str | None = None,
        player: str | None = None,
        lang: str = "en",
        aspect: str = "9x16",
        upto: int | None = None,
    ) -> dict:
        """The fan's moments up to the live clock, each ready to play and share when rendered."""
        if not MATCH_ID.match(match_id) or lang not in CUT_LANGUAGES or not REEL_ASPECT.match(aspect):
            raise HTTPException(422, "invalid request")
        focus = focus_of(side, player, match_id)
        moments = reel.moments(match_id, focus, lang, aspect, upto)
        for m in moments:
            if m["ready"]:
                reel.warm(match_id, aspect, m["key"], lang)  # mixed before the fan taps Play
        return {"moments": moments}

    @app.get("/media/moments/{match_id}/{aspect}/{name}", dependencies=[Depends(require_session)])
    def moment_media(match_id: str, aspect: str, name: str, request: Request) -> Response:
        """A moment's poster frame (key.jpg), or its short film with sound (key.lang.mp4)."""
        m = MOMENT_FILE.match(name)
        if not (MATCH_ID.match(match_id) and REEL_ASPECT.match(aspect) and m):
            raise HTTPException(404, "not found")
        key, lang, ext = m["key"], m["lang"], m["ext"]
        if ext == "jpg":
            poster = reel.pieces.path(match_id, aspect, f"{key}.jpg")
            if poster is None:
                raise HTTPException(404, "not found")
            return FileResponse(
                poster, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=3600"}
            )
        if lang not in CUT_LANGUAGES:
            raise HTTPException(404, "not found")
        film = reel.moment_film(match_id, aspect, key, lang)
        if film is None:
            raise HTTPException(404, "not rendered yet")
        return film_response(film, request)

    @app.post("/api/matches/{match_id}/clips", dependencies=[Depends(require_session)])
    def clip_that(match_id: str, body: ClipBody, request: Request) -> dict:
        """Clip that: any stretch of play (up to 30 s), rendered like a moment, for this fan."""
        if not MATCH_ID.match(match_id) or not REEL_ASPECT.match(body.aspect):
            raise HTTPException(422, "invalid request")
        if not 3_000 <= body.end - body.start <= MAX_WINDOW_MS or body.start < 0:
            raise HTTPException(422, "a clip is 3 to 30 seconds of play")
        key = f"window-{body.start}-{body.end}"
        if reel.pieces.exists(match_id, body.aspect, f"{key}.en.mp4"):
            return {"key": key, "ready": True}
        if not limiter.hit(per_hour, f"clips:{client_id(request)}"):
            raise HTTPException(429, "too many clips for now")
        request_clip = getattr(store, "request_clip", None)
        if request_clip is None:
            raise HTTPException(503, "clips are not switched on here")
        request_clip(match_id, body.aspect, key)
        return {"key": key, "ready": False}

    @app.post("/api/share", dependencies=[Depends(require_session)])
    def share(body: ShareBody) -> dict[str, str]:
        """A public link to exactly one clip, safe to post anywhere."""
        if not (MATCH_ID.match(body.match) and REEL_ASPECT.match(body.aspect) and REEL_KEY.match(body.key)):
            raise HTTPException(422, "invalid request")
        if body.lang not in CUT_LANGUAGES:
            raise HTTPException(422, "invalid request")
        return {"url": f"/s/{reel.share_token(body.match, body.aspect, body.key, body.lang)}"}

    @app.get("/s/{token}.mp4")
    def shared_film(token: str, request: Request) -> StreamingResponse:
        found = reel.read_token(token)
        film = reel.moment_film(*found) if found else None
        if film is None:
            raise HTTPException(404, "not found")
        return film_response(film, request, public=True)

    @app.get("/s/{token}.jpg")
    def shared_poster(token: str) -> FileResponse:
        """The shared clip's poster frame: the picture a chat shows in the link preview."""
        found = reel.read_token(token)
        poster = reel.pieces.path(found[0], found[1], f"{found[2]}.jpg") if found else None
        if poster is None:
            raise HTTPException(404, "not found")
        return FileResponse(
            poster, media_type="image/jpeg", headers={"Cache-Control": "public, max-age=86400"}
        )

    @app.get("/s/{token}/qr.svg")
    def shared_qr(token: str, request: Request) -> Response:
        """The shared link as a QR code: watching on a television or a laptop, the fan points a
        phone camera at it and the clip opens on the phone, where the apps they post from are."""
        if reel.read_token(token) is None:
            raise HTTPException(404, "not found")
        svg = qr_svg(f"{public_base(request)}/s/{token}")
        return Response(svg, media_type="image/svg+xml", headers={"Cache-Control": "public, max-age=86400"})

    @app.get("/s/{token}")
    def shared_page(token: str, request: Request) -> Response:
        """The page a shared link opens: the clip, and the tags that make chats show it."""
        found = reel.read_token(token)
        if found is None:
            raise HTTPException(404, "not found")
        return Response(share_page(public_base(request), token, found), media_type="text/html; charset=utf-8")

    # ---------------------------------------------------------------- the Recap Factory
    factory = (
        Factory(store.blobs, store.queue, s.factory_cooldown_s, s.factory_runs_per_day)
        if isinstance(store, AzureCuts)
        else Factory(DiskBlobs(s.data_dir), LocalRunner(DiskBlobs(s.data_dir), s.data_dir), 0, 1000)
    )

    def factory_plan(match_id: str) -> tuple[list[dict], dict[str, int]]:
        """Every film the match's fans can ask for, labelled for the screen, and the moment clips
        they are joined from (each rendered once, during the match)."""
        from matchcut_editing.edl import featured_focuses, pick_moments  # noqa: PLC0415
        from matchcut_editing.factory import plan  # noqa: PLC0415
        from matchcut_editing.inputs import VOICED, best_cues, focuses, load_feed  # noqa: PLC0415

        feed = load_feed(s.feeds_dir / f"{match_id}.json.gz")
        cues = best_cues(s.cues_dir / f"{match_id}.jsonl", "en")
        chosen = featured_focuses(feed, cues, focuses(feed))
        teams = feed["teams"]
        side_of = {teams[side]["id"]: side for side in ("home", "away")}
        side_by_name = {p["name"]: side for side in ("home", "away") for p in teams[side]["players"].values()}
        for c in feed.get("changes", []):  # substitutes join their side's list
            if c.get("id") in feed["players"]:
                side_by_name[feed["players"][c["id"]]["name"]] = side_of.get(feed["slots"][c["slot"]], "home")
        films = []
        for f in plan(chosen, [lang for lang in VOICED if lang in CUT_LANGUAGES]):
            side = f["focus"].get("side") or side_by_name.get(f["focus"]["player"], "home")
            label = f["focus"].get("player") or teams[side]["name"]
            films.append(
                {**f, "label": label, "team": teams[side]["code"], "kit": teams[side]["kit"]["primary"]}
            )
        moments = {f"{p['kind']}-{p['t']}" for c in chosen for p in pick_moments(feed, cues, c)}
        return films, {
            "moments": len(moments),
            "focuses": len(chosen),
            "players": len(feed.get("players", {})),
        }

    @app.get("/api/matches/{match_id}/factory", dependencies=[Depends(require_session)])
    def factory_state(match_id: str, aspect: str = "9x16") -> dict:
        """The latest Recap Factory run (films, replicas, timings, cost, QA), or the plan of one."""
        if not MATCH_ID.match(match_id) or not REEL_ASPECT.match(aspect) or not players_of(match_id):
            raise HTTPException(422, "invalid request")
        st = factory.state(match_id, aspect)
        if st is None:
            films, pieces = factory_plan(match_id)
            return {"run": None, "films": films, "pieces": pieces, "total": len(films), "next_run_in": 0}
        return st

    @app.post("/api/matches/{match_id}/factory", dependencies=[Depends(require_session)])
    def factory_run(match_id: str, body: FactoryBody) -> dict:
        """Make every fan's film now: one render job replica per film, side by side."""
        if not MATCH_ID.match(match_id) or not REEL_ASPECT.match(body.aspect) or not players_of(match_id):
            raise HTTPException(422, "invalid request")
        films, pieces = factory_plan(match_id)
        try:
            return factory.start(match_id, body.aspect, films, pieces)
        except BusyError:
            raise HTTPException(409, "a run is still making its films") from None
        except RationedError as r:
            if r.seconds is None:
                raise HTTPException(429, "no more runs today") from None
            wait = max(1, round(r.seconds))
            raise HTTPException(429, f"next run in {wait} s", headers={"Retry-After": str(wait)}) from None

    @app.get("/media/factory/{match_id}/{aspect}/{run}/{film}.mp4", dependencies=[Depends(require_session)])
    def factory_film(match_id: str, aspect: str, run: str, film: str, request: Request) -> StreamingResponse:
        from matchcut_editing.factory import FILM_ID, RUN_ID  # noqa: PLC0415

        ok = (
            MATCH_ID.match(match_id)
            and REEL_ASPECT.match(aspect)
            and RUN_ID.match(run)
            and FILM_ID.match(film)
        )
        made = factory.film(match_id, aspect, run, film) if ok else None
        if made is None:
            raise HTTPException(404, "not found")
        return film_response(made, request)

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
