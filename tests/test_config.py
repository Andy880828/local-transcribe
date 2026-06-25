"""config 模組測試：設定覆寫優先序與金鑰延遲驗證。"""

from __future__ import annotations

import pytest

from transcribe.config import load_settings
from transcribe.errors import MissingCredentialError


def test_defaults():
    s = load_settings()
    assert s.whisper_model == "large-v3"
    assert s.compute_type == "float16"
    assert s.batch_size == 8


def test_overrides_ignore_none():
    # None 覆寫應被忽略，沿用預設
    s = load_settings(whisper_model=None, batch_size=4)
    assert s.whisper_model == "large-v3"
    assert s.batch_size == 4


def test_require_hf_token_missing_raises_with_hint():
    s = load_settings(hf_token="")
    with pytest.raises(MissingCredentialError) as exc:
        s.require_hf_token()
    assert exc.value.hint is not None
    assert "HF_TOKEN" in exc.value.hint or "pyannote" in exc.value.hint


def test_require_hf_token_present_returns_trimmed():
    s = load_settings(hf_token="  hf_abc  ")
    assert s.require_hf_token() == "hf_abc"
