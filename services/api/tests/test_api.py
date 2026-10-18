import time

import pytest
from fastapi.testclient import TestClient
from matchcut_api import Settings, create_app, session_valid, sign_session
from matchcut_api.app import sha256
from matchcut_contracts import Cue, CueStatus, MomentKind

CODE = "kickoff-2026"
MATCH = "kes-wcr-7"


def _cue(moment: int, lang: str, status: CueStatus, text: str, t_ms: int) -> Cue:
    return Cue(
        match_id=MATCH,
        cue_id=f"CU-{moment:05d}-{lang}",
        moment_id=f"MO-{moment:05d}",
        kind=MomentKind.GOAL,
        t_ms=t_ms,
        clock=f"{t_ms // 60000}:00",
        language=lang,
        status=status,
        text=text,
    )


@pytest.fixture
def settings(tmp_path):
    cues = tmp_path / "cues"
    cues.mkdir()
    lines = [
        _cue(1, "en", CueStatus.PLAIN, "51' GOAL - Quinouani. 1-0", 3_000),
        _cue(1, "en", CueStatus.VERIFIED, "Quinouani finishes a 0.92 chance: 1-0.", 3_000),
        _cue(1, "es", CueStatus.VERIFIED, "Quinouani define una ocasión de 0.92: 1-0.", 3_000),
        _cue(2, "en", CueStatus.PLAIN, "60' Big save by Ade", 6_000),
        _cue(2, "en", CueStatus.REJECTED, "An unverifiable line", 6_000),
    ]
    (cues / f"{MATCH}.jsonl").write_text("".join(c.model_dump_json() + "\n" for c in lines), encoding="utf-8")
    return Settings(
        cues_dir=cues,
        media_dir=tmp_path / "media",
        studio_dir=None,
        code_hashes=frozenset({sha256(CODE)}),
        secret=b"x" * 32,
        requests_per_minute=50,
        secure_cookie=False,
    )


@pytest.fixture
def client(settings):
    return TestClient(create_app(settings))


def _login(client: TestClient) -> None:
    r = client.post("/api/session", json={"code": CODE})
    assert r.status_code == 200


def test_health_and_security_headers(client):
    r = client.get("/healthz")
    assert r.json() == {"status": "ok"}
    assert "frame-ancestors 'none'" in r.headers["content-security-policy"]
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["referrer-policy"] == "no-referrer"


def test_everything_needs_a_session(client):
    for path in ("/api/matches", f"/api/matches/{MATCH}/cues", f"/api/matches/{MATCH}/stream"):
        assert client.get(path).status_code == 401


def test_wrong_code_is_refused_and_cookie_is_hardened(client):
    assert client.post("/api/session", json={"code": "wrong-code"}).status_code == 401
    r = client.post("/api/session", json={"code": CODE})
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie
    assert "samesite=strict" in cookie


def test_sessions_are_signed_and_expire():
    secret = b"s" * 32
    token = sign_session(secret, now=1000.0)
    assert session_valid(secret, token, now=1001.0)
    assert not session_valid(secret, token, now=1000.0 + 13 * 3600)  # expired
    assert not session_valid(b"t" * 32, token, now=1001.0)  # wrong key
    assert not session_valid(secret, token[:-1] + ("0" if token[-1] != "0" else "1"), now=1001.0)  # tampered
    assert not session_valid(secret, None)


def test_verified_lines_replace_plain_cards_and_rejected_never_air(client):
    _login(client)
    assert client.get("/api/matches").json() == [{"match_id": MATCH, "video": ""}]
    en = client.get(f"/api/matches/{MATCH}/cues").json()
    assert [c["status"] for c in en] == ["verified", "plain"]
    assert "unverifiable" not in str(en)
    es = client.get(f"/api/matches/{MATCH}/cues", params={"lang": "es"}).json()
    assert es[0]["language"] == "es"
    assert es[1]["status"] == "plain"  # no Spanish line yet: the English plain card holds the slot


@pytest.mark.parametrize("bad", ["../secrets", "KES-wcr-7", "kes-wcr-7.jsonl", "a" * 40])
def test_match_ids_are_validated(client, bad):
    _login(client)
    assert client.get(f"/api/matches/{bad}/cues").status_code == 404
    assert client.get(f"/api/matches/{MATCH}/cues", params={"lang": "../x"}).status_code == 404


def test_stream_delivers_cues_as_server_sent_events(client):
    _login(client)
    t0 = time.monotonic()
    with client.stream("GET", f"/api/matches/{MATCH}/stream", params={"speed": 60}) as r:
        assert r.headers["content-type"].startswith("text/event-stream")
        body = "".join(r.iter_text())
    assert body.count("event: cue") == 2
    assert "id: CU-00001-en" in body
    assert "event: end" in body
    assert time.monotonic() - t0 < 5


def test_rate_limit(settings):
    settings.requests_per_minute = 3
    c = TestClient(create_app(settings))
    codes = [c.get("/api/matches").status_code for _ in range(5)]
    assert codes[:3] == [401, 401, 401]
    assert codes[3:] == [429, 429]
