"""pipeline orchestration 測試：把 GPU 階段 (audio/transcribe/diarize) 全 mock 掉，
只驗證串接邏輯與檔案輸出，無需真正的 GPU 或 whisperx。"""

from __future__ import annotations

from pathlib import Path

import transcribe.audio as audio_mod
import transcribe.diarize as diarize_mod
import transcribe.transcribe as transcribe_mod
from transcribe.config import load_settings
from transcribe.pipeline import PipelineOptions, run_pipeline

FAKE_RESULT = {
    "language": "zh",
    "segments": [
        {"start": 0.0, "end": 2.0, "text": "第一句"},
        {"start": 2.0, "end": 4.0, "text": "第二句"},
    ],
}


def _patch_stages(monkeypatch, *, expect_diarize: bool):
    calls = {"diarize": 0}

    def fake_prepare(input_path: Path, work_dir: Path) -> Path:
        return work_dir / "fake.16k.wav"

    def fake_transcribe(audio_path, settings, align=True):
        # 回傳副本避免跨測試污染
        return {"language": "zh", "segments": [dict(s) for s in FAKE_RESULT["segments"]]}

    def fake_diarize(audio_path, result, settings, **kwargs):
        calls["diarize"] += 1
        for i, seg in enumerate(result["segments"]):
            seg["speaker"] = f"SPEAKER_0{i % 2}"
        return result

    monkeypatch.setattr(audio_mod, "prepare_audio", fake_prepare)
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
    for p in result.outputs:
        assert p.exists()
    assert "SPEAKER_00" in (tmp_path / "meeting.txt").read_text(encoding="utf-8")


def test_no_diarize_skips_diarization(monkeypatch, tmp_path):
    calls = _patch_stages(monkeypatch, expect_diarize=False)
    # 不給 hf_token，--no-diarize 時也不應報錯
    settings = load_settings(output_dir=tmp_path)
    options = PipelineOptions(diarize=False, formats=["txt"])

    audio_in = tmp_path / "solo.wav"
    audio_in.write_bytes(b"x")

    result = run_pipeline(audio_in, settings, options)

    assert calls["diarize"] == 0
    txt = (tmp_path / "solo.txt").read_text(encoding="utf-8")
    assert "UNKNOWN" in txt  # 無分辨 → 講者標 UNKNOWN


def test_progress_callback_invoked(monkeypatch, tmp_path):
    _patch_stages(monkeypatch, expect_diarize=True)
    settings = load_settings(output_dir=tmp_path, hf_token="dummy")
    messages: list[str] = []

    audio_in = tmp_path / "a.wav"
    audio_in.write_bytes(b"x")

    run_pipeline(audio_in, settings, PipelineOptions(formats=["txt"]), progress=messages.append)

    assert any("轉錄" in m for m in messages)
