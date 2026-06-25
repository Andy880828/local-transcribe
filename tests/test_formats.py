"""formats 模組的純函式測試（無需 GPU / whisperx）。"""

from __future__ import annotations

import json

from transcribe.formats import (
    format_timestamp,
    merge_by_speaker,
    to_json,
    to_srt,
    to_txt,
)


def _segments():
    return [
        {"speaker": "SPEAKER_00", "start": 0.0, "end": 2.5, "text": "你好"},
        {"speaker": "SPEAKER_00", "start": 2.5, "end": 5.0, "text": "今天開會"},
        {"speaker": "SPEAKER_01", "start": 5.0, "end": 8.0, "text": "好的，沒問題"},
        {"speaker": "SPEAKER_00", "start": 8.0, "end": 9.0, "text": "  "},  # 空白段落應跳過
    ]


def test_format_timestamp_plain():
    assert format_timestamp(0) == "00:00:00"
    assert format_timestamp(3661.5) == "01:01:01"


def test_format_timestamp_srt_uses_comma_millis():
    assert format_timestamp(1.234, srt=True) == "00:00:01,234"


def test_format_timestamp_negative_clamped():
    assert format_timestamp(-5) == "00:00:00"


def test_merge_consecutive_same_speaker():
    blocks = merge_by_speaker(_segments())
    # SPEAKER_00 的兩段相鄰應合併；空白段落跳過 → 共 2 個區塊
    assert len(blocks) == 2
    assert blocks[0]["speaker"] == "SPEAKER_00"
    assert blocks[0]["text"] == "你好 今天開會"
    assert blocks[0]["end"] == 5.0
    assert blocks[1]["speaker"] == "SPEAKER_01"


def test_merge_missing_speaker_defaults_unknown():
    blocks = merge_by_speaker([{"start": 0, "end": 1, "text": "誰說的"}])
    assert blocks[0]["speaker"] == "UNKNOWN"


def test_to_txt_contains_speaker_and_timestamp():
    txt = to_txt(_segments())
    assert "[SPEAKER_00] 00:00:00 - 00:00:05" in txt
    assert "你好 今天開會" in txt
    assert "[SPEAKER_01]" in txt


def test_to_srt_numbering_and_arrow():
    srt = to_srt(_segments())
    assert "1\n00:00:00,000 --> 00:00:02,500\n[SPEAKER_00] 你好" in srt
    # 空白段落被跳過，編號應連續不含它
    assert "[SPEAKER_01] 好的，沒問題" in srt


def test_to_json_roundtrip():
    payload = json.loads(to_json({"language": "zh", "segments": _segments()}))
    assert payload["language"] == "zh"
    # 空白段落仍會被保留在 json（原始資料），但 text 去除空白
    assert payload["segments"][0]["speaker"] == "SPEAKER_00"
    assert payload["segments"][0]["text"] == "你好"
