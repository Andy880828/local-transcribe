"""中文簡轉繁（transcribe.to_traditional）測試。

案例取自 2026-10 對 15 支實際逐字稿的量測：Whisper 在 language=zh 時會混出簡體段落；
而轉換器不能動到原本就是正確繁體的字詞（吃、才、為、設備、數據、台郡）。
"""

from __future__ import annotations

import pytest

from transcribe.config import load_settings
from transcribe.errors import InvalidArgumentError
from transcribe.transcribe import to_traditional


def _result(*texts: str, language: str = "zh") -> dict:
    return {"language": language, "segments": [{"text": t, "words": [{"word": t[:2]}]} for t in texts]}


def test_simplified_segments_become_traditional():
    r = _result("不过讲真的应该是就是有一次他就我比较刚来的时候", "生日快乐")
    assert to_traditional(r, "s2tw") == "s2tw"
    assert r["segments"][0]["text"] == "不過講真的應該是就是有一次他就我比較剛來的時候"
    assert r["segments"][1]["text"] == "生日快樂"
    assert r["segments"][0]["words"][0]["word"] == "不過"  # 逐字資料一起轉


@pytest.mark.parametrize(
    "text",
    [
        "我們去吃飯才開會",  # s2t 會改成 喫、纔
        "因為設備的數據要分析",  # s2twp 會改成 裝置、資料
        "我跟他說台郡李展博",  # s2tw 會把 台 改成 臺
        "對小白的第一印象",
    ],
)
def test_traditional_text_is_left_untouched(text):
    r = _result(text)
    to_traditional(r, "s2tw")
    assert r["segments"][0]["text"] == text


def test_mixed_segment_converts_only_simplified_part():
    r = _result("他有一次開會拗副總請客吧 不过讲真的")
    to_traditional(r, "s2tw")
    assert r["segments"][0]["text"] == "他有一次開會拗副總請客吧 不過講真的"


def test_skipped_for_none_mode_and_non_chinese():
    r = _result("生日快乐")
    assert to_traditional(r, "none") is None
    assert r["segments"][0]["text"] == "生日快乐"
    r = _result("hello 快乐", language="en")
    assert to_traditional(r, "s2tw") is None
    assert r["segments"][0]["text"] == "hello 快乐"


def test_invalid_setting_is_user_error_not_internal():
    with pytest.raises(InvalidArgumentError) as exc:
        load_settings(chinese_convert="s2t")
    assert "chinese_convert" in exc.value.hint
    assert load_settings().chinese_convert == "s2tw"
