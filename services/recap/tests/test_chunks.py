import pytest
from matchcut_recap.cli import chunk_range


@pytest.mark.parametrize(("total", "chunks"), [(2018, 10), (2422, 8), (7, 3), (5, 1), (3, 5)])
def test_slices_cover_every_frame_exactly_once_in_order(total, chunks):
    frames = [f for c in range(chunks) for f in chunk_range(total, c, chunks)]
    assert frames == list(range(total))


def test_slices_are_balanced():
    sizes = [len(chunk_range(2018, c, 10)) for c in range(10)]
    assert max(sizes) - min(sizes) <= 1
