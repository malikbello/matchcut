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
