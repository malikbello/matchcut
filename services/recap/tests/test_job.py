import json
import types

import pytest
from azure.core.exceptions import ResourceExistsError
from matchcut_recap import cli, job


class FakeBlobs:
    """Just enough of a ContainerClient: conditional create, listing, download, delete."""

    def __init__(self):
        self.data: dict[str, bytes] = {}

    def upload_blob(self, name, data, overwrite=False):
        if not overwrite and name in self.data:
            raise ResourceExistsError("exists")
        self.data[name] = data if isinstance(data, bytes) else data.read()

    def list_blobs(self, name_starts_with=""):
        return [types.SimpleNamespace(name=n) for n in sorted(self.data) if n.startswith(name_starts_with)]

    def download_blob(self, name):
        payload = self.data[name]
        return types.SimpleNamespace(readinto=lambda f: f.write(payload))

    def delete_blob(self, name):
        del self.data[name]


class FakeQueue:
    def __init__(self):
        self.sent: list[dict] = []

    def send_message(self, content):
        self.sent.append(json.loads(content))


def test_prewarm_queues_what_is_not_published_and_can_run_again():
    blobs, queue = FakeBlobs(), FakeQueue()
    blobs.upload_blob(job.piece_blob("m", "9x16", "goal-1.en.mp4"), b"published")
    blobs.upload_blob(job.piece_blob("m", "9x16", "end.fr.mp4"), b"published")
    queued = job.prewarm(blobs, queue, "m", "9x16", ["goal-1", "chance-2"], ["en", "fr"], chunks=2)
    assert queued == ["chance-2"]  # the goal is already published
    clips = [m for m in queue.sent if m["kind"] == "clip"]
    assert [(m["key"], m["chunk"], m["chunks"]) for m in clips] == [("chance-2", 0, 2), ("chance-2", 1, 2)]
    assert [m["lang"] for m in queue.sent if m["kind"] == "cards"] == ["en"]  # French cards are published
    assert "work/m/9x16/chance-2/requested" in blobs.data  # a fan asking meanwhile does not queue it again


@pytest.fixture
def fake_render(monkeypatch, tmp_path):
    monkeypatch.setattr(job, "SCRATCH", tmp_path)
    assembled = []
    cut = types.SimpleNamespace(as_dict=lambda: {"segments": []})

    def make_part(args):
        part = tmp_path / f"slice-{args.chunk}.mp4"
        part.write_bytes(f"part{args.chunk}".encode())
        return cut, part

    def assemble(args, c, parts):
        assembled.append([p.read_bytes() for p in parts])
        film = tmp_path / "film.mp4"
        film.write_bytes(b"".join(assembled[-1]))
        return film

    monkeypatch.setattr(cli, "make_part", make_part)
    monkeypatch.setattr(cli, "assemble", assemble)
    return assembled


def test_the_last_slice_assembles_the_film_once_in_order(fake_render):
    blobs = FakeBlobs()
    req = {"id": "c-0123456789ab", "match": "kes-wcr-7", "side": "home", "chunks": 3}
    for chunk in (2, 0, 1):  # slices finish in any order
        job.render_slice(blobs, {**req, "chunk": chunk})
    assert fake_render == [[b"part0", b"part1", b"part2"]]
    assert blobs.data["c-0123456789ab.mp4"] == b"part0part1part2"
    assert b'"done"' in blobs.data["c-0123456789ab.json"]
    assert not [n for n in blobs.data if n.startswith("c-0123456789ab/")]  # scratch markers cleaned up


def test_a_second_finisher_never_assembles_twice(fake_render):
    blobs = FakeBlobs()
    req = {"id": "c-0123456789ab", "match": "kes-wcr-7", "side": "home", "chunks": 2}
    blobs.upload_blob("c-0123456789ab/assemble", b"")  # another replica already claimed it
    for chunk in (0, 1):
        job.render_slice(blobs, {**req, "chunk": chunk})
    assert fake_render == []


def test_message_fields_become_render_arguments(tmp_path):
    args = job.make_args(
        {"id": "c-1", "match": "m", "player": "Quinouani", "chunk": 4, "chunks": 10}, tmp_path
    )
    assert (args.player, args.side, args.chunk, args.chunks, args.gpu_less) == (
        "Quinouani",
        None,
        4,
        10,
        True,
    )


class FakeClock:
    """Time moves only when the code under test sleeps (or a slice renders)."""

    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def sleep(self, s):
        self.now += s


def test_a_late_slice_is_backed_up_and_the_slow_original_changes_nothing(fake_render, monkeypatch):
    blobs = FakeBlobs()
    clock = FakeClock()
    renders = []
    original = cli.make_part

    def timed_make_part(args):
        renders.append(args.chunk)
        clock.now += 300  # every render takes 300 s on a healthy host
        return original(args)

    monkeypatch.setattr(cli, "make_part", timed_make_part)
    req = {"id": "c-0123456789ab", "match": "kes-wcr-7", "side": "home", "chunks": 5}
    blobs.upload_blob("c-0123456789ab/claim-04", b"")  # slice 4's host is slow: claimed, not done
    for chunk in (0, 1, 2, 3):
        clock.now = 0.0
        job.render_slice(blobs, {**req, "chunk": chunk}, clock=clock, sleep=clock.sleep)
    assert renders == [0, 1, 2, 3, 4]  # slice 3's replica watched slice 4, then rendered it
    assert fake_render == [[b"part0", b"part1", b"part2", b"part3", b"part4"]]
    film = blobs.data["c-0123456789ab.mp4"]
    # the slow original finally finishes: no upload, no second assembly, the film stands
    job.render_slice(blobs, {**req, "chunk": 4}, clock=clock, sleep=clock.sleep)
    assert blobs.data["c-0123456789ab.mp4"] == film
    assert len(fake_render) == 1
    assert not [n for n in blobs.data if n.startswith("c-0123456789ab/")]


def test_nobody_waits_while_most_slices_are_still_rendering(fake_render):
    blobs = FakeBlobs()
    clock = FakeClock()
    req = {"id": "c-0123456789ab", "match": "kes-wcr-7", "side": "home", "chunks": 10}
    job.render_slice(blobs, {**req, "chunk": 0}, clock=clock, sleep=clock.sleep)
    assert clock.now == 0.0  # returned at once: 9 of 10 slices missing is normal, not late
    assert not [n for n in blobs.data if "/watch-" in n]
