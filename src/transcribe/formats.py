"""輸出格式化：把 WhisperX(+diarization) 的 result 轉成
已標註講者的逐字稿（.txt / .srt / .json）。

本檔刻意只用純函式、不相依 whisperx/torch，方便完整單元測試。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

UNKNOWN_SPEAKER = "UNKNOWN"


def format_timestamp(seconds: float, *, srt: bool = False) -> str:
    """秒數轉時間字串。srt=True 用逗號毫秒 (HH:MM:SS,mmm)，否則 HH:MM:SS。"""
    if seconds < 0:
        seconds = 0.0
    millis = int(round(seconds * 1000))
    hours, millis = divmod(millis, 3_600_000)
    minutes, millis = divmod(millis, 60_000)
    secs, millis = divmod(millis, 1000)
    if srt:
        return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def merge_by_speaker(segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """把連續且同一講者的段落合併成區塊，回傳
    ``[{speaker, start, end, text}, ...]``。"""
    blocks: list[dict[str, Any]] = []
    for seg in segments:
        speaker = seg.get("speaker", UNKNOWN_SPEAKER) or UNKNOWN_SPEAKER
        text = (seg.get("text") or "").strip()
        if not text:
            continue
        start = float(seg.get("start", 0.0) or 0.0)
        end = float(seg.get("end", start) or start)

        if blocks and blocks[-1]["speaker"] == speaker:
            blocks[-1]["text"] = f"{blocks[-1]['text']} {text}".strip()
            blocks[-1]["end"] = end
        else:
            blocks.append({"speaker": speaker, "start": start, "end": end, "text": text})
    return blocks


def to_txt(segments: list[dict[str, Any]]) -> str:
    """產生人類可讀的講者逐字稿。"""
    blocks = merge_by_speaker(segments)
    lines: list[str] = []
    for b in blocks:
        ts = f"{format_timestamp(b['start'])} - {format_timestamp(b['end'])}"
        lines.append(f"[{b['speaker']}] {ts}")
        lines.append(b["text"])
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def to_srt(segments: list[dict[str, Any]]) -> str:
    """產生 SRT 字幕，每段前綴講者標籤（不合併，保留原始時間軸）。"""
    entries: list[str] = []
    index = 1
    for seg in segments:
        text = (seg.get("text") or "").strip()
        if not text:
            continue
        speaker = seg.get("speaker", UNKNOWN_SPEAKER) or UNKNOWN_SPEAKER
        start = format_timestamp(float(seg.get("start", 0.0) or 0.0), srt=True)
        end = format_timestamp(float(seg.get("end", 0.0) or 0.0), srt=True)
        entries.append(f"{index}\n{start} --> {end}\n[{speaker}] {text}\n")
        index += 1
    return "\n".join(entries)


def to_json(result: dict[str, Any]) -> str:
    """輸出精簡 JSON（保留 segments 與 language，便於後續程式化處理）。"""
    payload = {
        "language": result.get("language"),
        "segments": [
            {
                "speaker": seg.get("speaker", UNKNOWN_SPEAKER),
                "start": seg.get("start"),
                "end": seg.get("end"),
                "text": (seg.get("text") or "").strip(),
            }
            for seg in result.get("segments", [])
        ],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def write_outputs(
    result: dict[str, Any],
    base_path: Path,
    formats: list[str],
) -> list[Path]:
    """把指定格式寫到 ``base_path.<ext>``，回傳實際寫出的檔案路徑清單。"""
    segments = result.get("segments", [])
    writers = {
        "txt": lambda: to_txt(segments),
        "srt": lambda: to_srt(segments),
        "json": lambda: to_json(result),
    }
    base_path.parent.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for fmt in formats:
        if fmt not in writers:
            continue
        out = base_path.with_suffix(f".{fmt}")
        out.write_text(writers[fmt](), encoding="utf-8")
        written.append(out)
    return written
