"""pipeline orchestration 測試：把 GPU 與 ffmpeg 階段 (media/transcribe/diarize) 全 mock 掉，
只驗證串接邏輯與檔案輸出，無需真正的 GPU 或 whisperx。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import transcribe.diarize as diarize_mod
import transcribe.media as media_mod
import transcribe.transcribe as transcribe_mod
from transcribe.config import load_settings
from transcribe.errors import InputNotFoundError, InvalidArgumentError, MissingCredentialError, NoAudioStreamError
from transcribe.pipeline import PipelineOptions, expand_inputs, run_batch, run_pipeline

FAKE_RESULT = {
    "language": "zh",
    "segments": [
        {"start": 0.0, "end": 2.0, "text": "第一句"},
        {"start": 2.0, "end": 4.0, "text": "第二句"},
    ],
}


def _patch_stages(monkeypatch, *, expect_diarize: bool):
    calls = {"diarize": 0}

    def fake_prepare(input_path: Path, work_dir: Path, track: int = 0) -> Path:
        return work_dir / "fake.16k.wav"

    def fake_probe(path: Path) -> dict:
        if path.read_bytes() == b"no-audio":
            return {"path": str(path), "kind": "video", "duration": 4.0, "has_video": True, "audio_tracks": []}
        return {
            "path": str(path),
            "kind": "video" if path.suffix == ".mp4" else "audio",
            "duration": 4.0,
            "has_video": path.suffix == ".mp4",
            "audio_tracks": [{"track": 0, "language": "zho"}],
        }

    def fake_transcribe(audio_path, settings, align=True):
        # 回傳副本避免跨測試污染
        return {"language": "zh", "segments": [dict(s) for s in FAKE_RESULT["segments"]]}

    def fake_diarize(audio_path, result, settings, **kwargs):
        calls["diarize"] += 1
        for i, seg in enumerate(result["segments"]):
            seg["speaker"] = f"SPEAKER_0{i % 2}"
        return result

    monkeypatch.setattr(media_mod, "prepare_audio", fake_prepare)
    monkeypatch.setattr(media_mod, "probe", fake_probe)
    monkeypatch.setattr(transcribe_mod, "transcribe_audio", fake_transcribe)
    monkeypatch.setattr(diarize_mod, "diarize_transcript", fake_diarize)
    return calls


def test_full_pipeline_writes_outputs(monkeypatch, tmp_path):
    calls = _patch_stages(monkeypatch, expect_diarize=True)
    settings = load_settings(output_dir=tmp_path, hf_token="dummy")
    options = PipelineOptions(formats=["txt", "json"])

    audio_in = tmp_path / "meeting.m4a"
    audio_in.write_bytes(b"not-real-audio")

    result = run_pipeline(audio_in, settings, options)

    assert calls["diarize"] == 1
    assert result.language == "zh"
    names = {p.name for p in result.outputs}
    assert names == {"meeting.txt", "meeting.json"}
    # 一場會議一個資料夾：<output_dir>/<stem>/<stem>.<格式>
    assert {p.parent for p in result.outputs} == {tmp_path / "meeting"}
    for p in result.outputs:
        assert p.exists()
    assert "SPEAKER_00" in (tmp_path / "meeting" / "meeting.txt").read_text(encoding="utf-8")


def test_no_diarize_skips_diarization(monkeypatch, tmp_path):
    calls = _patch_stages(monkeypatch, expect_diarize=False)
    # 不給 hf_token，--no-diarize 時也不應報錯
    settings = load_settings(output_dir=tmp_path)
    options = PipelineOptions(diarize=False, formats=["txt"])

    audio_in = tmp_path / "solo.wav"
    audio_in.write_bytes(b"x")

    run_pipeline(audio_in, settings, options)

    assert calls["diarize"] == 0
    txt = (tmp_path / "solo" / "solo.txt").read_text(encoding="utf-8")
    assert "UNKNOWN" in txt  # 無分辨 → 講者標 UNKNOWN


def test_progress_callback_invoked(monkeypatch, tmp_path):
    _patch_stages(monkeypatch, expect_diarize=True)
    settings = load_settings(output_dir=tmp_path, hf_token="dummy")
    messages: list[str] = []

    audio_in = tmp_path / "a.wav"
    audio_in.write_bytes(b"x")

    run_pipeline(audio_in, settings, PipelineOptions(formats=["txt"]), progress=messages.append)

    assert any("轉錄" in m for m in messages)


def test_video_source_recorded_in_json(monkeypatch, tmp_path):
    _patch_stages(monkeypatch, expect_diarize=True)
    settings = load_settings(output_dir=tmp_path / "out", hf_token="dummy")
    video = tmp_path / "talk.mp4"
    video.write_bytes(b"x")

    res = run_pipeline(video, settings, PipelineOptions(formats=["json"]))

    assert res.source["kind"] == "video"
    assert res.speakers == ["SPEAKER_00", "SPEAKER_01"]
    doc = json.loads((tmp_path / "out" / "talk" / "talk.json").read_text(encoding="utf-8"))
    assert doc["schema_version"] == 1
    assert doc["source"]["kind"] == "video"
    assert doc["source"]["audio_track"] == 0


def test_missing_token_fails_before_transcription(monkeypatch, tmp_path):
    calls = {"transcribe": 0}
    monkeypatch.setattr(transcribe_mod, "transcribe_audio", lambda *a, **k: calls.__setitem__("transcribe", 1))
    settings = load_settings(output_dir=tmp_path, hf_token="")
    audio_in = tmp_path / "a.wav"
    audio_in.write_bytes(b"x")

    with pytest.raises(MissingCredentialError):
        run_pipeline(audio_in, settings, PipelineOptions())
    assert calls["transcribe"] == 0  # 沒有浪費時間先轉錄


def test_no_audio_stream_raises(monkeypatch, tmp_path):
    _patch_stages(monkeypatch, expect_diarize=False)
    video = tmp_path / "silent.mp4"
    video.write_bytes(b"no-audio")
    with pytest.raises(NoAudioStreamError):
        run_pipeline(video, load_settings(output_dir=tmp_path), PipelineOptions(diarize=False))


def test_expand_inputs_directory_filters_and_sorts(tmp_path):
    for name in ["b.mp4", "a.m4a", "notes.txt", "c.MKV"]:
        (tmp_path / name).write_bytes(b"x")
    files = expand_inputs([tmp_path])
    assert [f.name for f in files] == ["a.m4a", "b.mp4", "c.MKV"]


def test_expand_inputs_errors(tmp_path):
    with pytest.raises(InputNotFoundError):
        expand_inputs([tmp_path / "missing.mp4"])
    with pytest.raises(InputNotFoundError):
        expand_inputs([tmp_path])  # 空資料夾


def test_batch_continues_after_failure_and_skips_existing(monkeypatch, tmp_path):
    _patch_stages(monkeypatch, expect_diarize=False)
    out = tmp_path / "out"
    (out / "done").mkdir(parents=True)
    (out / "done" / "done.json").write_text("{}", encoding="utf-8")
    good, bad, done = tmp_path / "good.wav", tmp_path / "bad.mp4", tmp_path / "done.wav"
    good.write_bytes(b"x")
    bad.write_bytes(b"no-audio")
    done.write_bytes(b"x")

    records = run_batch(
        [bad, good, done],
        load_settings(output_dir=out),
        PipelineOptions(diarize=False, formats=["json"]),
        skip_existing=True,
    )

    status = {Path(r["input"]).name: r["status"] for r in records}
    assert status == {"bad.mp4": "error", "good.wav": "ok", "done.wav": "skipped"}
    assert records[0]["error"]["code"] == "NO_AUDIO_STREAM"


def test_batch_rejects_stem_collision(tmp_path):
    a, b = tmp_path / "x.mp4", tmp_path / "x.wav"
    with pytest.raises(InvalidArgumentError):
        run_batch([a, b], load_settings(output_dir=tmp_path), PipelineOptions(diarize=False))
