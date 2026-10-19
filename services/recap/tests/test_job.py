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
