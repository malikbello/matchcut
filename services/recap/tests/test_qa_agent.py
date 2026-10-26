import shutil
import subprocess

import httpx
import pytest
from matchcut_recap.qa_agent import RETRIES, Perception


def _senses(responses, waits):
    calls = iter(responses)

    def answer(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer t"
        item = next(calls)
        if isinstance(item, Exception):
            raise item
        return item

    client = httpx.Client(transport=httpx.MockTransport(answer))
    return Perception("https://ai.example", lambda: "t", client=client, sleep=waits.append)


def test_throttling_is_waited_out_as_the_service_asks():
    waits = []
    ok = httpx.Response(200, json={"phrases": []})
    senses = _senses([httpx.Response(429, headers={"Retry-After": "7"}), httpx.Response(503), ok], waits)
    assert senses._post("https://ai.example/x").status_code == 200
    assert 7 <= waits[0] < 8  # Retry-After, plus jitter
    assert 2 <= waits[1] < 3  # then doubling backoff


def test_a_dropped_connection_is_retried_and_a_real_error_is_not():
    waits = []
    senses = _senses([httpx.ConnectError("reset"), httpx.Response(400)], waits)
    with pytest.raises(httpx.HTTPStatusError):
        senses._post("https://ai.example/x")
    assert len(waits) == 1


def test_it_gives_up_after_its_retries():
    waits = []
    senses = _senses([httpx.Response(429)] * RETRIES, waits)
    with pytest.raises(httpx.HTTPStatusError):
        senses._post("https://ai.example/x")
    assert len(waits) == RETRIES - 1
    assert max(waits) < 31  # no wait over 30 s without Retry-After


def test_an_exhausted_recogniser_hands_over_to_the_next_for_the_same_language():
    seen = []

    def answer(request: httpx.Request) -> httpx.Response:
        body = request.content.decode("latin-1")
        seen.append("pt-PT" if "pt-PT" in body else "pt-BR")
        if "pt-PT" in body:
            return httpx.Response(429, json={"code": "TooManyRequests", "message": "Resource Exhausted"})
        return httpx.Response(200, json={"phrases": []})

    waits = []
    client = httpx.Client(transport=httpx.MockTransport(answer))
    senses = Perception("https://ai.example", lambda: "t", client=client, sleep=waits.append)

    def attempt(i):
        locale = ("pt-PT", "pt-BR")[i % 2]
        return {"files": {"definition": (None, f'{{"locales": ["{locale}"]}}')}}

    assert senses._post("https://ai.example/stt", vary=attempt).status_code == 200
    assert seen == ["pt-PT", "pt-BR"]


FFMPEG = shutil.which("ffmpeg")


@pytest.mark.skipif(FFMPEG is None, reason="ffmpeg not installed")
def test_a_window_is_listened_to_on_its_own_and_heard_in_film_seconds(tmp_path):
    assert FFMPEG is not None
    film = tmp_path / "film.wav"
    subprocess.run(  # noqa: S603 - our own arguments
        [FFMPEG, "-loglevel", "error", "-f", "lavfi", "-i", "sine=duration=6", str(film)], check=True
    )
    phrase = {"offsetMilliseconds": 200, "durationMilliseconds": 900, "text": "Here's Kinuwani."}
    senses = _senses([httpx.Response(200, json={"phrases": [phrase]})], [])
    senses.ffmpeg = FFMPEG
    usage: dict[str, float] = {}
    heard = senses.listen(film, "en", usage, window=(2.3, 4.7))
    assert heard == [(pytest.approx(2.5), pytest.approx(3.4), "Here's Kinuwani.")]
    assert usage["audio_s"] == pytest.approx(2.4, abs=0.05)  # only the window is sent (and billed)
