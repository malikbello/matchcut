import gzip
import json
import time

import pytest
from fastapi.testclient import TestClient
from matchcut_api import Settings, create_app
from matchcut_api.app import MOMENT_FILE, qr_svg, sha256
from matchcut_api.cuts import CutRequest, Film, LocalCuts, progress
from matchcut_api.factory import DiskBlobs, Factory
from matchcut_api.reel import LocalPieces, Reel, described_variant, moment_caption
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
    feeds = tmp_path / "feeds"
    feeds.mkdir()
    (feeds / f"{MATCH}.json.gz").write_bytes(gzip.compress(b'{"match_id": "kes-wcr-7", "t": [0]}'))
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
        feeds_dir=feeds,
        studio_dir=None,
        code_hashes=frozenset({sha256(CODE)}),
        secret="x" * 32,
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


def test_tampered_or_expired_sessions_are_refused(settings, monkeypatch):
    c = TestClient(create_app(settings))
    _login(c)
    assert c.get("/api/matches").status_code == 200
    cookie = c.cookies.get("mc_session")
    assert cookie
    c.cookies.set("mc_session", cookie[:-2] + ("aa" if not cookie.endswith("aa") else "bb"))
    assert c.get("/api/matches").status_code == 401  # signature no longer matches
    _login(c)
    monkeypatch.setattr("matchcut_api.app.time.time", lambda: 10**12)  # far past the 12-hour expiry
    assert c.get("/api/matches").status_code == 401


def test_verified_lines_replace_plain_cards_and_rejected_never_air(client):
    _login(client)
    assert client.get("/api/matches").json() == [
        {"match_id": MATCH, "video": "", "feed": f"/api/matches/{MATCH}/feed"}
    ]
    assert client.get(f"/api/matches/{MATCH}/feed").json()["t"] == [0]  # served gzip, decoded by the client
    assert client.get("/api/matches/abc-def-9/feed").status_code == 404
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


def test_behind_the_ingress_each_caller_has_their_own_rate_limit(settings):
    settings.requests_per_minute = 2
    settings.proxy_hops = 1  # every socket comes from the ingress, which appends the caller
    c = TestClient(create_app(settings))

    def get(chain: str) -> int:
        return c.get("/api/matches", headers={"X-Forwarded-For": chain}).status_code

    assert [get("203.0.113.5") for _ in range(3)] == [401, 401, 429]
    assert get("198.51.100.7") == 401  # another fan is not blocked by the first
    assert get("198.51.100.99, 203.0.113.5") == 429  # an address forged on the left changes nothing


def test_spoken_lines_are_served_only_by_strict_name(settings):
    audio = settings.media_dir / "audio" / MATCH
    audio.mkdir(parents=True)
    (audio / "CU-00001-en-NG.mp3").write_bytes(b"ID3")
    c = TestClient(create_app(settings))
    assert c.get(f"/media/audio/{MATCH}/CU-00001-en-NG.mp3").status_code == 401  # session first
    _login(c)
    r = c.get(f"/media/audio/{MATCH}/CU-00001-en-NG.mp3")
    assert r.status_code == 200
    assert r.headers["content-type"] == "audio/mpeg"
    for bad in ("..%2F..%2Fsecret.mp3", "CU-00001-en-NG.wav", "notes.txt"):
        assert c.get(f"/media/audio/{MATCH}/{bad}").status_code == 404


def test_studio_files_revalidate(settings, tmp_path):
    studio = tmp_path / "studio"
    studio.mkdir()
    (studio / "index.html").write_text("<!doctype html><title>Studio</title>", encoding="utf-8")
    settings.studio_dir = studio
    r = TestClient(create_app(settings)).get("/")
    assert r.status_code == 200
    assert r.headers["cache-control"] == "no-cache"


# ---------------------------------------------------------------- fan cuts


class FakeCuts:
    def __init__(self):
        self.requests = []

    def submit(self, req):
        self.requests.append(req)
        return "c-0123456789ab"

    def status(self, cut_id):
        return {"id": cut_id, "status": "done"} if cut_id == "c-0123456789ab" else None

    def film(self, cut_id):
        data = b"mp4-bytes"
        return Film(len(data), lambda a, b: iter([data[a : b + 1]])) if cut_id == "c-0123456789ab" else None


@pytest.fixture
def cuts_client(settings):
    (settings.feeds_dir / f"{MATCH}.json.gz").write_bytes(gzip.compress(json.dumps(FEED).encode()))
    store = FakeCuts()
    return TestClient(create_app(settings, cuts=store)), store


def test_cuts_need_a_session(cuts_client):
    client, _ = cuts_client
    assert client.post("/api/cuts", json={"match": MATCH, "side": "home"}).status_code == 401
    assert client.get("/api/cuts/c-0123456789ab").status_code == 401
    assert client.get("/media/cuts/c-0123456789ab.mp4").status_code == 401


def test_a_cut_is_queued_followed_and_watched(cuts_client):
    client, store = cuts_client
    _login(client)
    r = client.post("/api/cuts", json={"match": MATCH, "player": "Quinouani", "lang": "fr", "aspect": "16x9"})
    assert r.json() == {"id": "c-0123456789ab", "status": "queued"}
    assert store.requests[0].player == "Quinouani"
    assert store.requests[0].lang == "fr"
    assert client.get("/api/cuts/c-0123456789ab").json()["status"] == "done"
    film = client.get("/media/cuts/c-0123456789ab.mp4")
    assert film.content == b"mp4-bytes"
    assert film.headers["content-type"] == "video/mp4"


@pytest.mark.parametrize(
    "body",
    [
        {"match": MATCH},  # neither a side nor a player
        {"match": MATCH, "side": "home", "player": "Quinouani"},  # both
        {"match": MATCH, "side": "both"},
        {"match": MATCH, "player": "Nobody"},
        {"match": MATCH, "side": "home", "aspect": "4x3"},
        {"match": MATCH, "side": "home", "lang": "../x"},
        {"match": MATCH, "side": "home", "lang": "yo"},  # captions only until the voice is ready
        {"match": "../../etc", "side": "home"},
    ],
)
def test_bad_cut_requests_are_refused(cuts_client, body):
    client, store = cuts_client
    _login(client)
    assert client.post("/api/cuts", json=body).status_code == 422
    assert store.requests == []


def test_cut_ids_are_checked_before_any_lookup(cuts_client):
    client, _ = cuts_client
    _login(client)
    for bad in ("c-unknown", "..%2Fsecret", "c-0123456789aZ"):
        assert client.get(f"/api/cuts/{bad}").status_code == 404
    assert client.get("/api/cuts/c-ffffffffffff").status_code == 404


def test_cuts_are_rate_limited(settings):
    settings.cuts_per_hour = 2
    store = FakeCuts()
    client = TestClient(create_app(settings, cuts=store))
    _login(client)
    codes = [client.post("/api/cuts", json={"match": MATCH, "side": "home"}).status_code for _ in range(3)]
    assert codes == [200, 200, 429]


def test_cuts_are_unavailable_without_a_back_end(client):
    _login(client)
    assert client.post("/api/cuts", json={"match": MATCH, "side": "home"}).status_code == 503


def test_films_answer_byte_ranges_so_players_can_seek(cuts_client):
    client, _ = cuts_client
    _login(client)
    url = "/media/cuts/c-0123456789ab.mp4"
    assert client.get(url).headers["accept-ranges"] == "bytes"
    part = client.get(url, headers={"Range": "bytes=4-6"})
    assert part.status_code == 206
    assert part.content == b"byt"
    assert part.headers["content-range"] == "bytes 4-6/9"
    assert client.get(url, headers={"Range": "bytes=-3"}).content == b"tes"
    assert client.get(url, headers={"Range": "bytes=50-"}).status_code == 416


def test_a_queued_cut_reports_progress_from_its_slices():
    st = {"id": "c-0123456789ab", "status": "queued", "chunks": 10}
    assert progress(st, []) == st
    names = ["c-0123456789ab/claim-00", "c-0123456789ab/claim-01", "c-0123456789ab/part-00.mp4"]
    assert progress(st, names) | {} == {**st, "status": "rendering", "rendered": 1}
    assert progress(st, [*names, "c-0123456789ab/assemble"])["status"] == "assembling"


# ---------------------------------------------------------------- assembling cuts from pieces


class _PieceCut:
    language = "en"

    def clip_order(self):
        return ["title-kestrel-bay-fc", "goal-3274800", "end"]

    def as_dict(self):
        return {"segments": []}


class _FakeAssembler:
    def __init__(self):
        self.joined = None

    def plan(self, req, manifest):
        return _PieceCut()

    def make(self, cut, pieces, work):
        self.joined = [p.name for p in pieces]
        work.mkdir(parents=True, exist_ok=True)
        film = work / "film.mp4"
        film.write_bytes(b"film")
        return film


def _pieces(tmp_path, names):
    folder = tmp_path / "pieces" / MATCH / "9x16"
    folder.mkdir(parents=True)
    (folder / "manifest.json").write_text('{"fps": 25, "packages": {}, "clips": {}}', encoding="utf-8")
    for n in names:
        (folder / n).write_bytes(b"piece")
    return tmp_path / "pieces"


def test_a_cut_is_assembled_from_its_pieces_in_order(tmp_path):
    names = ["title-kestrel-bay-fc.en.mp4", "goal-3274800.en.mp4", "end.en.mp4"]
    asm = _FakeAssembler()
    store = LocalCuts(tmp_path / "cuts", "http://127.0.0.1:1", "x", _pieces(tmp_path, names), asm)
    req = CutRequest(MATCH, "en", "9x16", side="home")
    assert store._fast("c-0123456789ab", req)
    assert asm.joined == names
    st = store.status("c-0123456789ab")
    film = store.film("c-0123456789ab")
    assert st is not None
    assert film is not None
    assert st["status"] == "done"
    assert st["assembled"] is True
    assert film.size == 4


def test_a_missing_piece_means_the_film_is_rendered_instead(tmp_path):
    pieces = _pieces(tmp_path, ["title-kestrel-bay-fc.en.mp4", "end.en.mp4"])  # the goal clip is not ready
    store = LocalCuts(tmp_path / "cuts", "http://127.0.0.1:1", "x", pieces, _FakeAssembler())
    assert not store._fast("c-0123456789ab", CutRequest(MATCH, "en", "9x16", side="home"))


# ---------------------------------------------------------------- the reel: play, clip, share


def _reel_client(settings, tmp_path, store=None):
    settings.pieces_dir = tmp_path / "pieces"
    folder = settings.pieces_dir / MATCH / "9x16"
    folder.mkdir(parents=True)
    (folder / "goal-3274800.en.share.mp4").write_bytes(b"0123456789")  # a moment film, mixed earlier
    (folder / "goal-3274800.jpg").write_bytes(b"\xff\xd8poster")
    return TestClient(create_app(settings, cuts=store))


def test_share_links_open_exactly_one_clip_and_refuse_tampering(settings, tmp_path):
    client = _reel_client(settings, tmp_path)
    _login(client)
    r = client.post(
        "/api/share", json={"match": MATCH, "aspect": "9x16", "key": "goal-3274800", "lang": "en"}
    )
    url = r.json()["url"]
    public = TestClient(client.app)  # a friend with no session
    page = public.get(url)
    assert page.status_code == 200
    assert 'property="og:video"' in page.text
    assert public.get(f"{url}.mp4").content == b"0123456789"
    body, sig = url.removeprefix("/s/").split(".")
    assert public.get(f"/s/{body}.{sig[::-1]}").status_code == 404
    assert public.get("/s/not-a-token").status_code == 404


def test_shared_links_preview_in_chats_and_hand_over_to_a_phone_by_qr(settings, tmp_path):
    client = _reel_client(settings, tmp_path)
    _login(client)
    body = {"match": MATCH, "aspect": "9x16", "key": "goal-3274800", "lang": "en"}
    url = client.post("/api/share", json=body).json()["url"]
    public = TestClient(client.app)
    https = {"X-Forwarded-Proto": "https"}  # the ingress ends TLS
    page = public.get(url, headers=https)
    assert f'property="og:image" content="https://testserver{url}.jpg"' in page.text  # chats show the poster
    assert public.get(f"{url}.jpg").content.startswith(b"\xff\xd8")
    qr = public.get(f"{url}/qr.svg", headers=https)
    assert qr.headers["content-type"].startswith("image/svg+xml")
    assert qr.content == qr_svg(f"https://testserver{url}")  # the code holds exactly the public link
    assert qr.content != qr_svg(f"http://testserver{url}")
    forged = url[:-1] + ("A" if url[-1] != "A" else "B")
    assert public.get(f"{forged}/qr.svg").status_code == 404
    assert public.get(f"{forged}.jpg").status_code == 404


def test_a_goal_card_tells_the_goal_not_the_momentum_line_beside_it():
    cues = [
        {"t_ms": 3_274_800, "kind": "momentum", "status": "plain", "text": "Momentum swings"},
        {"t_ms": 3_274_800, "kind": "goal", "status": "verified", "text": "Quinouani scores"},
        {"t_ms": 3_400_000, "kind": "goal", "status": "verified", "text": "too late"},
    ]
    goal, conceded = moment_caption(cues, "goal", 3_274_800), moment_caption(cues, "conceded", 3_274_800)
    assert goal is not None
    assert goal["text"] == "Quinouani scores"  # the same second as a momentum line: the goal wins
    assert conceded is not None
    assert conceded["text"] == "Quinouani scores"
    assert moment_caption(cues, "chance", 1_000) is None


def test_ready_moments_are_mixed_ahead_of_play_once(tmp_path):
    mixed: list[tuple[str, str, str, str]] = []

    class CountingReel(Reel):
        def moment_film(self, match: str, aspect: str, key: str, lang: str) -> Film | None:
            mixed.append((match, aspect, key, lang))
            time.sleep(0.05)  # mixing takes a while: the reel polls again meanwhile
            return None

    reel = CountingReel(LocalPieces(tmp_path), tmp_path, tmp_path, b"key")
    for _ in range(3):
        reel.warm(MATCH, "9x16", "goal-3274800", "en")
    reel._warmer.shutdown(wait=True)
    assert mixed == [(MATCH, "9x16", "goal-3274800", "en")]


def test_moment_media_checks_names_and_serves_posters_and_films(settings, tmp_path):
    client = _reel_client(settings, tmp_path)
    _login(client)
    base = f"/media/moments/{MATCH}/9x16"
    assert client.get(f"{base}/goal-3274800.jpg").content.startswith(b"\xff\xd8")
    part = client.get(f"{base}/goal-3274800.en.mp4", headers={"Range": "bytes=2-4"})
    assert part.status_code == 206
    assert part.content == b"234"
    for bad in ("..%2Fsecret.mp4", "goal-1.en.mp4.exe", "anything.mp4", "goal-3274800.xx.mp4"):
        assert client.get(f"{base}/{bad}").status_code == 404


def test_clip_that_is_validated_and_needs_a_renderer(settings, tmp_path):
    client = _reel_client(settings, tmp_path)
    _login(client)
    url = f"/api/matches/{MATCH}/clips"
    assert client.post(url, json={"start": 1000, "end": 60000}).status_code == 422  # longer than 30 s
    assert client.post(url, json={"start": 1000, "end": 2000}).status_code == 422  # shorter than 3 s
    assert client.post(url, json={"start": 1000, "end": 16000}).status_code == 503  # no renderer here


def test_clip_that_asks_the_renderer_once_per_stretch_of_play(settings, tmp_path):
    asked = []

    class Renders(FakeCuts):
        def request_clip(self, match, aspect, key):
            asked.append((match, aspect, key))

    client = _reel_client(settings, tmp_path, Renders())
    _login(client)
    r = client.post(f"/api/matches/{MATCH}/clips", json={"start": 1000, "end": 16000})
    assert r.json() == {"key": "window-1000-16000", "ready": False}
    assert asked == [(MATCH, "9x16", "window-1000-16000")]


def test_a_moment_carries_the_qa_agents_verdict(tmp_path):
    folder = tmp_path / MATCH / "9x16"
    folder.mkdir(parents=True)
    report = {
        "passed": True,
        "lufs": -15.9,
        "lines": [{"heard": True}, {"heard": True}],
        "captions": [{"read": True}],
    }
    (folder / "goal-1.en.qa.json").write_text(json.dumps(report), encoding="utf-8")
    reel = Reel(LocalPieces(tmp_path), tmp_path, tmp_path, b"key")
    assert reel.qa(MATCH, "9x16", "goal-1", "en") == {
        "passed": True,
        "heard": "2/2",
        "voiced": None,
        "again": 0,
        "read": "1/1",
        "lufs": -15.9,
        "words": True,
        "issues": [],
    }
    assert reel.qa(MATCH, "9x16", "goal-1", "fr") is None  # not checked yet


FEED = {
    "match_id": MATCH,
    "t": [0],
    "slots": ["kes", "wcr"],
    "players": {"p1": {"num": 9, "name": "Quinouani"}, "p2": {"num": 4, "name": "Toredor"}},
    "teams": {
        "home": {"id": "kes", "code": "KES", "name": "Kestrel Bay FC", "kit": {"primary": "#E8B422"},
                 "players": {"0": {"id": "p1", "num": 9, "name": "Quinouani"}}},
        "away": {"id": "wcr", "code": "WCR", "name": "Westcroft United", "kit": {"primary": "#6CC8FF"},
                 "players": {"1": {"id": "p2", "num": 4, "name": "Toredor"}}},
    },
    "goals": [{"t": 60_000, "side": "home"}],
    "events": [[60_000, "goal", 0]],
    "changes": [],
}  # fmt: skip


class FakeQueue:
    def __init__(self):
        self.messages = []

    def send_message(self, content):
        self.messages.append(json.loads(content))


@pytest.fixture
def factory_client(settings, tmp_path, monkeypatch):
    (settings.feeds_dir / f"{MATCH}.json.gz").write_bytes(gzip.compress(json.dumps(FEED).encode()))
    queue = FakeQueue()
    clock = [1_000_000.0]
    made = Factory(
        DiskBlobs(tmp_path / "blobs"), queue, cooldown_s=600, runs_per_day=2, clock=lambda: clock[0]
    )
    monkeypatch.setattr("matchcut_api.app.Factory", lambda *a, **k: made)
    settings.data_dir = tmp_path
    client = TestClient(create_app(settings))
    _login(client)
    return client, queue, made, clock


def test_the_factory_plans_every_fans_film_then_runs_them_all_at_once(factory_client):
    client, queue, made, clock = factory_client
    url = f"/api/matches/{MATCH}/factory"
    plan = client.get(url).json()
    assert plan["run"] is None
    assert plan["total"] == 3 * 7
    assert {f["label"] for f in plan["films"]} == {"Kestrel Bay FC", "Westcroft United", "Quinouani"}
    assert plan["pieces"] == {"moments": 2, "focuses": 3, "players": 2}  # a goal, and the same goal conceded
    started = client.post(url, json={"aspect": "9x16"}).json()
    assert started["run"].startswith("f-")
    assert started["counts"]["waiting"] == 21
    assert len(queue.messages) == 21
    assert {m["kind"] for m in queue.messages} == {"fan"}
    assert client.post(url, json={"aspect": "9x16"}).status_code == 409  # still making its films
    # every film made: the run ends, and the next is rationed by the cooldown, then by the day's cap
    prefix = f"factory/{MATCH}/9x16/{started['run']}/"
    for m in queue.messages:
        body = {"status": "done", "started": clock[0] + 5, "finished": clock[0] + 60,
                "cost": {"compute": 0.008, "qa": 0.024, "total": 0.032}, "qa": {"passed": True}}  # fmt: skip
        made.blobs.upload_blob(prefix + m["film"] + ".json", json.dumps(body).encode(), overwrite=True)
    clock[0] += 120
    st = client.get(url).json()
    assert st["finished"]
    assert st["qa_passed"] == "21/21"
    assert st["first_film_s"] == 60
    refused = client.post(url, json={"aspect": "9x16"})
    assert refused.status_code == 429
    assert int(refused.headers["retry-after"]) == 480
    clock[0] += 600
    assert client.post(url, json={"aspect": "9x16"}).status_code == 200
    assert client.get(url).json()["run"] != started["run"]


def test_factory_films_are_served_by_strict_name_only(factory_client):
    client, _, made, _ = factory_client
    name = f"factory/{MATCH}/9x16/f-0123456789ab/home.en.mp4"
    made.blobs.upload_blob(name, b"\x00" * 100)
    base = f"/media/factory/{MATCH}/9x16"
    r = client.get(f"{base}/f-0123456789ab/home.en.mp4", headers={"Range": "bytes=0-9"})
    assert r.status_code == 206
    assert len(r.content) == 10
    for bad in (
        "f-0123456789ab/..%2Fhome.en.mp4",
        "x-0123456789ab/home.en.mp4",
        "f-0123456789ab/home.xx.en.mp4",
    ):
        assert client.get(f"{base}/{bad}").status_code == 404


def test_a_cut_for_a_player_with_no_moments_is_refused(settings):
    (settings.feeds_dir / f"{MATCH}.json.gz").write_bytes(gzip.compress(json.dumps(FEED).encode()))
    store = FakeCuts()
    client = TestClient(create_app(settings, cuts=store))
    _login(client)
    body = {"match": MATCH, "lang": "en", "aspect": "9x16"}
    r = client.post("/api/cuts", json={**body, "player": "Toredor"})
    assert r.status_code == 422
    assert "no moments" in r.json()["detail"]
    assert client.post("/api/cuts", json={**body, "player": "Quinouani"}).status_code == 200
    assert [req.player for req in store.requests] == ["Quinouani"]


def test_described_films_are_the_same_moments_with_the_describer(tmp_path, settings):
    m = MOMENT_FILE.match("goal-1.en-NG.ad.mp4")
    assert m is not None
    assert m["key"] == "goal-1"
    assert m["lang"] == "en-NG.ad"
    assert described_variant("en-NG.ad") == ("en-NG", True)
    assert described_variant("pcm") == ("pcm", False)
    assert MOMENT_FILE.match("goal-1.en.xx.mp4") is None
    # the reel lists the described film's own QA verdict
    folder = tmp_path / "pieces" / MATCH / "9x16"
    folder.mkdir(parents=True)
    (folder / "goal-1.en.ad.qa.json").write_text(
        json.dumps({"passed": True, "lines": [{"heard": True}]}), encoding="utf-8"
    )
    reel = Reel(LocalPieces(tmp_path / "pieces"), tmp_path, tmp_path, b"key")
    described = reel.qa(MATCH, "9x16", "goal-1", "en.ad")
    assert described is not None
    assert described["passed"] is True
    assert reel.qa(MATCH, "9x16", "goal-1", "en") is None
    # a share link can carry the described film
    token = reel.share_token(MATCH, "9x16", "goal-1", "en.ad")
    assert reel.read_token(token) == (MATCH, "9x16", "goal-1", "en.ad")


def test_a_cut_can_be_asked_for_with_audio_description(settings):
    (settings.feeds_dir / f"{MATCH}.json.gz").write_bytes(gzip.compress(json.dumps(FEED).encode()))
    store = FakeCuts()
    client = TestClient(create_app(settings, cuts=store))
    _login(client)
    body = {"match": MATCH, "lang": "fr", "aspect": "9x16", "side": "home", "described": True}
    assert client.post("/api/cuts", json=body).status_code == 200
    assert store.requests[0].described is True
    assert store.requests[0].message("c-0123456789ab")["described"] is True
