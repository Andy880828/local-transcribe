"""build_asr_options 防幻覺參數組裝測試（純函式，無需 GPU/whisperx 模型）。"""

from __future__ import annotations

from transcribe.config import load_settings
from transcribe.transcribe import build_asr_options


def test_default_anti_hallucination_options():
    opts = build_asr_options(load_settings())
    # 預設即為抗幻覺設定
    assert opts["condition_on_previous_text"] is False
    assert opts["no_repeat_ngram_size"] == 3
    assert opts["repetition_penalty"] == 1.1
    assert opts["compression_ratio_threshold"] == 2.4
    assert opts["no_speech_threshold"] == 0.6


def test_cli_overrides_flow_through():
    settings = load_settings(
        condition_on_previous_text=True,
        repetition_penalty=1.3,
        no_repeat_ngram_size=0,
    )
    opts = build_asr_options(settings)
    assert opts["condition_on_previous_text"] is True
    assert opts["repetition_penalty"] == 1.3
    assert opts["no_repeat_ngram_size"] == 0


def test_only_expected_keys_present():
    # 只應含 whisperx 認得的覆寫 key，避免傳入未知參數
    opts = build_asr_options(load_settings())
    assert set(opts) == {
        "condition_on_previous_text",
        "no_repeat_ngram_size",
        "repetition_penalty",
        "compression_ratio_threshold",
        "no_speech_threshold",
    }
