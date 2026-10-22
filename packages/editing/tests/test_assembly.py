import shutil
import subprocess
from pathlib import Path

import pytest
from matchcut_editing.assembly import (
    FPS,
    VIDEO_ENCODE,
    caption_command,
    card_command,
    join_command,
    piece_name,
    run,
)


def test_every_piece_is_encoded_the_same_way_so_joins_need_no_reencode():
    cap = caption_command(Path("clip.mp4"), [(Path("c.png"), 1.0, 8.0)], Path("out.mp4"))
    card = card_command(Path("card.png"), 3.0, Path("card.mp4"))
    for cmd in (cap, card):
        joined = " ".join(cmd)
        assert " ".join(VIDEO_ENCODE) in joined
        assert "-an" in cmd  # pieces carry no audio: the fan's soundtrack is mixed once
    assert f"-r {FPS}" in " ".join(VIDEO_ENCODE)


def test_captions_fade_in_and_out_inside_their_window():
    cmd = caption_command(
        Path("clip.mp4"), [(Path("a.png"), 2.0, 9.0), (Path("b.png"), 12.0, 14.5)], Path("o.mp4")
    )
    graph = cmd[cmd.index("-filter_complex") + 1]
    assert "fade=t=in:st=2.000:d=0.16" in graph
    assert "fade=t=out:st=8.880:d=0.12" in graph
    assert "enable='between(t,12.000,14.500)'" in graph
    assert cmd[cmd.index("-map") + 1] == "[v2]"  # the last overlay is the output


def test_a_clip_without_captions_is_still_encoded_for_joining():
    cmd = caption_command(Path("clip.mp4"), [], Path("o.mp4"))
    assert "-filter_complex" not in cmd
    assert cmd[cmd.index("-map") + 1] == "0:v"


def test_join_lists_pieces_in_order_and_copies(tmp_path):
    listing = tmp_path / "parts.txt"
    cmd = join_command([tmp_path / "title.mp4", tmp_path / "goal.mp4"], listing, tmp_path / "out.mp4")
    lines = listing.read_text(encoding="utf-8").splitlines()
    assert lines[0].endswith("title.mp4'")
    assert lines[1].endswith("goal.mp4'")
    assert cmd[cmd.index("-c") + 1] == "copy"


def test_pieces_are_named_by_match_format_key_and_language():
    assert piece_name("kes-wcr-7", "9x16", "goal-3274800", "fr") == "kes-wcr-7/9x16/goal-3274800.fr.mp4"
    assert piece_name("kes-wcr-7", "16x9", "end") == "kes-wcr-7/16x9/end.mp4"


def test_real_pieces_join_without_reencode_and_keep_every_frame(tmp_path):

    ffmpeg, ffprobe = shutil.which("ffmpeg"), shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        pytest.skip("ffmpeg not installed")
    q = ["-hide_banner", "-loglevel", "error", "-y"]
    src, png, card_png = tmp_path / "src.mp4", tmp_path / "cap.png", tmp_path / "card.png"
    run([ffmpeg, *q, "-f", "lavfi", "-i", f"testsrc2=size=180x320:rate={FPS}:duration=2", str(src)])
    run(
        [
            ffmpeg,
            *q,
            "-f",
            "lavfi",
            "-i",
            "color=c=red@0.6:size=180x320,format=rgba",
            "-frames:v",
            "1",
            str(png),
        ]
    )
    run([ffmpeg, *q, "-f", "lavfi", "-i", "color=c=navy:size=180x320", "-frames:v", "1", str(card_png)])
    clip, card, out = tmp_path / "clip.mp4", tmp_path / "card.mp4", tmp_path / "cut.mp4"
    run(caption_command(src, [(png, 0.4, 1.6)], clip, ffmpeg))
    run(card_command(card_png, 1.0, card, ffmpeg))
    run(join_command([card, clip], tmp_path / "parts.txt", out, ffmpeg))

    def frames(p):
        r = subprocess.run(  # noqa: S603 - test helper, our own arguments
            [ffprobe, "-v", "error", "-count_frames", "-select_streams", "v", "-show_entries",
             "stream=nb_read_frames", "-of", "csv=p=0", str(p)],
            capture_output=True, text=True, check=True,
        )  # fmt: skip
        return int(r.stdout.strip())

    assert frames(out) == frames(card) + frames(clip) == FPS * 3
