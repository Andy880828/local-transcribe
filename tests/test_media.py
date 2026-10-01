"""media 模組測試：ffprobe 結果解析與時間解析（純函式），以及用真 ffmpeg 產生的
小影片做整合測試（多音軌影片、無音軌影片）。系統沒有 ffmpeg 時整合測試自動 skip。"""

from __future__ import annotations

import shutil
import subprocess

import pytest

from transcribe.errors import AudioError, InputNotFoundError, InvalidArgumentError, NoAudioStreamError
from transcribe.media import clip, extract_audio, parse_probe, parse_time, prepare_audio, probe, require_audio_track

HAS_FFMPEG = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))
needs_ffmpeg = pytest.mark.skipif(not HAS_FFMPEG, reason="系統沒有 ffmpeg/ffprobe")


@pytest.mark.parametrize(
    ("text", "expected"),
    [("90", 90.0), ("90.5", 90.5), ("01:30", 90.0), ("00:01:30.250", 90.25), (12, 12.0)],
)
def test_parse_time_valid(text, expected):
    assert parse_time(text) == expected


@pytest.mark.parametrize("text", ["", "1:2:3:4", "abc", "-5", "1m30s"])
def test_parse_time_invalid(text):
    with pytest.raises(InvalidArgumentError):
        parse_time(text)


def test_parse_probe_counts_audio_tracks_and_ignores_cover_art(tmp_path):
    raw = {
        "format": {"format_name": "mov,mp4", "duration": "12.5"},
        "streams": [
            {"index": 0, "codec_type": "video", "disposition": {"attached_pic": 1}},
            {
                "index": 1,
                "codec_type": "audio",
                "codec_name": "aac",
                "channels": 2,
                "sample_rate": "48000",
                "tags": {"language": "jpn"},
            },
            {"index": 2, "codec_type": "audio", "codec_name": "aac", "channels": 1, "sample_rate": "44100"},
        ],
    }
    info = parse_probe(raw, tmp_path / "song.m4a")
    assert info["kind"] == "audio" and info["has_video"] is False  # 封面圖不算影像
    assert info["duration"] == 12.5
    assert [(t["track"], t["stream_index"], t["language"]) for t in info["audio_tracks"]] == [
        (0, 1, "jpn"),
        (1, 2, None),
    ]


def test_parse_probe_missing_duration_is_none_not_zero(tmp_path):
    info = parse_probe({"format": {}, "streams": []}, tmp_path / "x")
    assert info["duration"] is None
    with pytest.raises(NoAudioStreamError):
        require_audio_track(info, 0)


def test_require_audio_track_out_of_range(tmp_path):
    info = parse_probe({"streams": [{"index": 0, "codec_type": "audio"}]}, tmp_path / "x")
    assert require_audio_track(info, 0)["track"] == 0
    with pytest.raises(NoAudioStreamError) as exc:
        require_audio_track(info, 1)
    assert "1 條音軌" in exc.value.hint


def _ffmpeg(*args: str) -> None:
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *args], check=True)


@pytest.fixture(scope="module")
def media_dir(tmp_path_factory):
    if not HAS_FFMPEG:
        pytest.skip("系統沒有 ffmpeg/ffprobe")
    d = tmp_path_factory.mktemp("media")
    # 2 秒、雙音軌（440Hz / 880Hz，第二軌標 eng）的影片
    _ffmpeg(
        "-f",
        "lavfi",
        "-i",
        "testsrc=size=64x64:rate=10:duration=2",
        "-f",
        "lavfi",
        "-i",
        "sine=frequency=440:duration=2",
        "-f",
        "lavfi",
        "-i",
        "sine=frequency=880:duration=2",
        "-map",
        "0",
        "-map",
        "1",
        "-map",
        "2",
        "-c:v",
        "mpeg4",
        "-c:a",
        "aac",
        "-metadata:s:a:1",
        "language=eng",
        str(d / "dual.mkv"),
    )
    # 只有影像、沒有音軌
    _ffmpeg("-f", "lavfi", "-i", "testsrc=size=64x64:rate=10:duration=1", "-c:v", "mpeg4", str(d / "mute.mp4"))
    (d / "garbage.mp4").write_bytes(b"not a video")
    return d


@needs_ffmpeg
def test_probe_real_multitrack_video(media_dir):
    info = probe(media_dir / "dual.mkv")
    assert info["kind"] == "video"
    assert len(info["audio_tracks"]) == 2
    assert info["audio_tracks"][1]["language"] == "eng"
    assert info["duration"] == pytest.approx(2.0, abs=0.2)


@needs_ffmpeg
def test_probe_real_errors(media_dir):
    assert probe(media_dir / "mute.mp4")["audio_tracks"] == []
    with pytest.raises(AudioError):
        probe(media_dir / "garbage.mp4")
    with pytest.raises(InputNotFoundError):
        probe(media_dir / "missing.mp4")


@needs_ffmpeg
def test_extract_second_track_and_prepare_audio(media_dir, tmp_path):
    out = extract_audio(media_dir / "dual.mkv", tmp_path / "t1.flac", track=1)
    info = probe(out)
    assert info["kind"] == "audio" and len(info["audio_tracks"]) == 1
    assert info["audio_tracks"][0]["codec"] == "flac"

    wav = prepare_audio(media_dir / "dual.mkv", tmp_path, track=1)
    track = probe(wav)["audio_tracks"][0]
    assert track["sample_rate"] == 16000 and track["channels"] == 1

    with pytest.raises(InvalidArgumentError):
        extract_audio(media_dir / "dual.mkv", tmp_path / "t.docx")


@needs_ffmpeg
def test_clip_real(media_dir, tmp_path):
    out = clip(media_dir / "dual.mkv", tmp_path / "part.mkv", 0.5, 1.5)
    assert probe(out)["duration"] == pytest.approx(1.0, abs=0.2)
    with pytest.raises(InvalidArgumentError):
        clip(media_dir / "dual.mkv", tmp_path / "bad.mkv", 1.5, 0.5)
