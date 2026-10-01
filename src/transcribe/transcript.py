"""對「已存在的逐字稿 JSON」的操作：載入（含舊版相容）、講者改名、搜尋、統計。

和 formats.py 的分工：formats 只負責「result → 字串」的渲染；本檔負責讀回
磁碟上的逐字稿並加工。全部是純函式 + 檔案 I/O，不相依 whisperx/torch。

逐字稿版本：
- v0：初版輸出，只有 ``language`` / ``segments``（無 ``schema_version``）
- v1：加上 ``schema_version`` / ``source`` / ``speaker_names``
載入時一律補齊成 v1 結構，寫回時就是 v1。
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .errors import InputNotFoundError, InvalidArgumentError, InvalidTranscriptError
from .formats import (
    TRANSCRIPT_SCHEMA_VERSION,
    UNKNOWN_SPEAKER,
    clean_text,
    display_speaker,
    format_timestamp,
    to_json,
)

DEFAULT_SEARCH_LIMIT = 50


def load_transcript(path: Path) -> dict[str, Any]:
    """讀取逐字稿 JSON 並正規化成 v1 結構。"""
    if not path.is_file():
        raise InputNotFoundError(
            f"transcript not found: {path}",
            hint=f"找不到逐字稿：{path}。逐字稿 JSON 由 `transcribe run` 產生（預設在 outputs/）。",
        )
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise InvalidTranscriptError(f"cannot parse {path}: {exc}", hint="檔案不是有效的 UTF-8 JSON。") from exc
    if not isinstance(raw, dict) or not isinstance(raw.get("segments"), list):
        raise InvalidTranscriptError(
            f"{path} has no 'segments' list",
            hint="這不是 transcribe 產生的逐字稿 JSON（缺少 segments 陣列）。",
        )
    version = raw.get("schema_version", 0)
    if not isinstance(version, int) or version > TRANSCRIPT_SCHEMA_VERSION:
        raise InvalidTranscriptError(
            f"unsupported schema_version {version!r}",
            hint=f"此版本工具只支援 schema_version ≤ {TRANSCRIPT_SCHEMA_VERSION}，請更新工具。",
        )
    segments = []
    for seg in raw["segments"]:
        if not isinstance(seg, dict):
            raise InvalidTranscriptError(f"segment is not an object: {seg!r}", hint="segments 內每筆都必須是物件。")
        segments.append(
            {
                "speaker": seg.get("speaker") or UNKNOWN_SPEAKER,
                "start": float(seg.get("start") or 0.0),
                "end": float(seg.get("end") or seg.get("start") or 0.0),
                "text": clean_text(seg.get("text")),
            }
        )
    return {
        "schema_version": TRANSCRIPT_SCHEMA_VERSION,
        "language": raw.get("language"),
        "source": raw.get("source"),
        "text_conversion": raw.get("text_conversion"),
        "speaker_names": dict(raw.get("speaker_names") or {}),
        "segments": segments,
    }


def save_transcript(doc: dict[str, Any], path: Path) -> Path:
    path.write_text(to_json(doc), encoding="utf-8")
    return path


def speaker_labels(doc: dict[str, Any]) -> list[str]:
    """依首次出現順序列出原始講者標籤。"""
    return list(dict.fromkeys(seg["speaker"] for seg in doc["segments"]))


def parse_mapping(items: list[str]) -> dict[str, str]:
    """解析 ``SPEAKER_00=王小明`` 形式；值留空（``SPEAKER_00=``）代表移除改名。"""
    mapping: dict[str, str] = {}
    for item in items:
        if "=" not in item:
            raise InvalidArgumentError(
                f"invalid mapping: {item!r}", hint="--map 格式為 原始標籤=名稱，例如 SPEAKER_00=王小明。"
            )
        label, name = item.split("=", 1)
        mapping[label.strip()] = clean_text(name)
    return mapping


def rename_speakers(doc: dict[str, Any], mapping: dict[str, str]) -> dict[str, Any]:
    """更新 ``speaker_names`` 對照表（不改 segments 原始標籤，因此可逆）。"""
    labels = speaker_labels(doc)
    unknown = [label for label in mapping if label not in labels]
    if unknown:
        raise InvalidArgumentError(
            f"unknown speaker label(s): {', '.join(unknown)}",
            hint=f"--map 左邊必須是原始標籤，此逐字稿有：{', '.join(labels)}",
        )
    names = dict(doc["speaker_names"])
    for label, name in mapping.items():
        if name:
            names[label] = name
        else:
            names.pop(label, None)
    return {**doc, "speaker_names": names}


def _segment_view(doc: dict[str, Any], index: int) -> dict[str, Any]:
    seg = doc["segments"][index]
    return {
        "index": index,
        "label": seg["speaker"],
        "speaker": display_speaker(seg["speaker"], doc["speaker_names"]),
        "start": seg["start"],
        "end": seg["end"],
        "timestamp": format_timestamp(seg["start"]),
        "text": seg["text"],
    }


def search(
    doc: dict[str, Any],
    query: str,
    *,
    regex: bool = False,
    ignore_case: bool = True,
    speaker: str | None = None,
    context: int = 0,
    limit: int = DEFAULT_SEARCH_LIMIT,
) -> dict[str, Any]:
    """搜尋段落文字。``speaker`` 可用原始標籤或改名後名稱過濾。

    回傳 ``total`` 為全部命中數，``hits`` 最多 ``limit`` 筆，``truncated`` 標示是否截斷。
    """
    flags = re.IGNORECASE if ignore_case else 0
    try:
        pattern = re.compile(query if regex else re.escape(query), flags)
    except re.error as exc:
        raise InvalidArgumentError(
            f"invalid regex: {exc}", hint="--regex 模式下 query 必須是合法的正規表示式。"
        ) from exc
    if limit < 1:
        raise InvalidArgumentError(f"limit must be >= 1, got {limit}", hint="--limit 至少為 1。")

    segments = doc["segments"]
    matched = [
        i
        for i, seg in enumerate(segments)
        if pattern.search(seg["text"])
        and (speaker is None or speaker in (seg["speaker"], display_speaker(seg["speaker"], doc["speaker_names"])))
    ]
    hits = []
    for i in matched[:limit]:
        hit = _segment_view(doc, i)
        if context:
            hit["context_before"] = [_segment_view(doc, j) for j in range(max(0, i - context), i)]
            hit["context_after"] = [_segment_view(doc, j) for j in range(i + 1, min(len(segments), i + 1 + context))]
        hits.append(hit)
    return {
        "query": query,
        "total": len(matched),
        "returned": len(hits),
        "truncated": len(matched) > limit,
        "hits": hits,
    }


def stats(doc: dict[str, Any]) -> dict[str, Any]:
    """各講者發言統計。

    ``talk_time`` 是該講者段落時長加總（重疊說話不扣除）；``share`` 是占所有段落時長
    加總的比例。``duration`` 優先取 source 的媒體長度，沒有才用最後一段的結束時間，
    來源記在 ``duration_source``。
    """
    per: dict[str, dict[str, Any]] = {}
    for seg in doc["segments"]:
        if not seg["text"]:
            continue
        entry = per.setdefault(
            seg["speaker"],
            {
                "label": seg["speaker"],
                "speaker": display_speaker(seg["speaker"], doc["speaker_names"]),
                "segments": 0,
                "talk_time": 0.0,
                "first": seg["start"],
                "last": seg["end"],
            },
        )
        entry["segments"] += 1
        entry["talk_time"] += max(0.0, seg["end"] - seg["start"])
        entry["first"] = min(entry["first"], seg["start"])
        entry["last"] = max(entry["last"], seg["end"])

    total_talk = sum(e["talk_time"] for e in per.values())
    for e in per.values():
        e["talk_time"] = round(e["talk_time"], 3)
        e["share"] = round(e["talk_time"] / total_talk, 4) if total_talk else None

    source_duration = (doc.get("source") or {}).get("duration")
    if source_duration is not None:
        duration, duration_source = source_duration, "media"
    elif doc["segments"]:
        duration, duration_source = max(seg["end"] for seg in doc["segments"]), "last_segment_end"
    else:
        duration, duration_source = None, "unavailable"

    return {
        "language": doc.get("language"),
        "duration": duration,
        "duration_source": duration_source,
        "speaker_count": len(per),
        "total_talk_time": round(total_talk, 3),
        "speakers": sorted(per.values(), key=lambda e: e["talk_time"], reverse=True),
    }
