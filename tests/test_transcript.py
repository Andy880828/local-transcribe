"""transcript 模組測試：舊版相容載入、可逆改名、搜尋、統計（純函式，無需 GPU）。"""

from __future__ import annotations

import json

import pytest

from transcribe.errors import InputNotFoundError, InvalidArgumentError, InvalidTranscriptError
from transcribe.transcript import (
    load_transcript,
    parse_mapping,
    rename_speakers,
    save_transcript,
    search,
    stats,
)

V0 = {
    "language": "zh",
    "segments": [
        {"speaker": "SPEAKER_00", "start": 0.0, "end": 10.0, "text": "我們先看稼動率"},
        {"speaker": "SPEAKER_01", "start": 10.0, "end": 14.0, "text": "好"},
        {"speaker": "SPEAKER_00", "start": 14.0, "end": 20.0, "text": "稼動率要每日計算\x1b[31m"},
        {"start": 20.0, "end": 21.0, "text": "（無講者）"},
    ],
}


@pytest.fixture
def v0_file(tmp_path):
    path = tmp_path / "m.json"
    path.write_text(json.dumps(V0, ensure_ascii=False), encoding="utf-8")
    return path


def test_load_v0_upgrades_and_cleans(v0_file):
    doc = load_transcript(v0_file)
    assert doc["schema_version"] == 1
    assert doc["speaker_names"] == {}
    assert doc["segments"][2]["text"] == "稼動率要每日計算"  # ANSI 已移除
    assert doc["segments"][3]["speaker"] == "UNKNOWN"


def test_load_errors(tmp_path):
    with pytest.raises(InputNotFoundError):
        load_transcript(tmp_path / "none.json")
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    with pytest.raises(InvalidTranscriptError):
        load_transcript(bad)
    wrong = tmp_path / "wrong.json"
    wrong.write_text('{"items": []}', encoding="utf-8")
    with pytest.raises(InvalidTranscriptError):
        load_transcript(wrong)
    future = tmp_path / "future.json"
    future.write_text('{"schema_version": 99, "segments": []}', encoding="utf-8")
    with pytest.raises(InvalidTranscriptError):
        load_transcript(future)


def test_rename_is_reversible_and_keeps_raw_labels(v0_file):
    doc = rename_speakers(load_transcript(v0_file), parse_mapping(["SPEAKER_00=王小明"]))
    save_transcript(doc, v0_file)
    reloaded = load_transcript(v0_file)
    assert reloaded["speaker_names"] == {"SPEAKER_00": "王小明"}
    assert reloaded["segments"][0]["speaker"] == "SPEAKER_00"  # 原始標籤未改

    undone = rename_speakers(reloaded, parse_mapping(["SPEAKER_00="]))
    assert undone["speaker_names"] == {}


def test_rename_rejects_unknown_label_and_bad_syntax(v0_file):
    doc = load_transcript(v0_file)
    with pytest.raises(InvalidArgumentError) as exc:
        rename_speakers(doc, {"SPEAKER_09": "X"})
    assert "SPEAKER_00" in exc.value.hint  # 提示列出可用標籤
    with pytest.raises(InvalidArgumentError):
        parse_mapping(["SPEAKER_00"])


def test_search_keyword_context_and_speaker_filter(v0_file):
    doc = rename_speakers(load_transcript(v0_file), {"SPEAKER_00": "王小明"})
    res = search(doc, "稼動率", context=1)
    assert res["total"] == 2 and not res["truncated"]
    first = res["hits"][0]
    assert first["speaker"] == "王小明" and first["label"] == "SPEAKER_00"
    assert first["timestamp"] == "00:00:00"
    assert first["context_before"] == [] and first["context_after"][0]["text"] == "好"

    assert search(doc, "稼動率", speaker="王小明")["total"] == 2
    assert search(doc, "稼動率", speaker="SPEAKER_01")["total"] == 0


def test_search_regex_limit_and_invalid(v0_file):
    doc = load_transcript(v0_file)
    res = search(doc, r"稼動率(要.*計算)?", regex=True, limit=1)
    assert res["total"] == 2 and res["returned"] == 1 and res["truncated"]
    with pytest.raises(InvalidArgumentError):
        search(doc, "(", regex=True)


def test_stats_talk_time_share_and_duration_source(v0_file):
    s = stats(load_transcript(v0_file))
    assert s["speaker_count"] == 3
    top = s["speakers"][0]
    assert top["label"] == "SPEAKER_00" and top["talk_time"] == 16.0 and top["segments"] == 2
    assert top["first"] == 0.0 and top["last"] == 20.0
    assert sum(sp["talk_time"] for sp in s["speakers"]) == s["total_talk_time"] == 21.0
    assert s["duration"] == 21.0 and s["duration_source"] == "last_segment_end"


def test_stats_prefers_media_duration_and_handles_empty():
    doc = {"segments": [], "speaker_names": {}, "source": None}
    s = stats(doc)
    assert s["duration"] is None and s["duration_source"] == "unavailable" and s["speakers"] == []
    doc = {"segments": [], "speaker_names": {}, "source": {"duration": 99.5}}
    assert stats(doc)["duration_source"] == "media"
