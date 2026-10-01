"""輸出格式化：把 WhisperX(+diarization) 的 result 轉成
已標註講者的逐字稿（.txt / .srt / .vtt / .md / .json）。

本檔刻意只用純函式、不相依 whisperx/torch，方便完整單元測試。

兩個唯一決定點：
- ``clean_text``：逐字稿文字的淨化（去 ANSI escape、控制字元、雙向覆寫字元）。
  逐字稿是「錄音裡任何人說的話」，屬不受信任內容；所有渲染器與 JSON 載入都經過它，
  避免終端機被控制序列污染，也避免看不見的字元混進 agent 的 context。
- ``RENDERERS``：允許的輸出格式清單，CLI 驗證、schema、SKILL 文件都以它為準。
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Callable

from .errors import InvalidArgumentError

UNKNOWN_SPEAKER = "UNKNOWN"
TRANSCRIPT_SCHEMA_VERSION = 1

_ANSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]|\x1b[@-_]")
# C0/C1 控制字元（含換行，段落內換行一律攤平成空白）與雙向文字覆寫字元
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f-\x9f‪-‮⁦-⁩]")


def clean_text(text: str | None) -> str:
    """淨化逐字稿文字：去 ANSI escape 與控制字元、收斂空白。"""
    if not text:
        return ""
    text = _ANSI_RE.sub("", text)
    text = _CONTROL_RE.sub(" ", text)
    return re.sub(r"[ \t]{2,}", " ", text).strip()


def format_timestamp(seconds: float, *, srt: bool = False, vtt: bool = False) -> str:
    """秒數轉時間字串。srt=True → HH:MM:SS,mmm；vtt=True → HH:MM:SS.mmm；否則 HH:MM:SS。"""
    if seconds < 0:
        seconds = 0.0
    millis = int(round(seconds * 1000))
    hours, millis = divmod(millis, 3_600_000)
    minutes, millis = divmod(millis, 60_000)
    secs, millis = divmod(millis, 1000)
    base = f"{hours:02d}:{minutes:02d}:{secs:02d}"
    if srt:
        return f"{base},{millis:03d}"
    if vtt:
        return f"{base}.{millis:03d}"
    return base


def display_speaker(label: str | None, names: dict[str, str] | None = None) -> str:
    """原始講者標籤 → 顯示名稱（有 rename 對照就用對照）。"""
    label = label or UNKNOWN_SPEAKER
    return (names or {}).get(label, label)


def _iter_segments(segments: list[dict[str, Any]], names: dict[str, str] | None):
    """逐段產出 (顯示講者, start, end, 淨化後文字)，空白段落略過。"""
    for seg in segments:
        text = clean_text(seg.get("text"))
        if not text:
            continue
        start = float(seg.get("start", 0.0) or 0.0)
        end = float(seg.get("end", start) or start)
        yield display_speaker(seg.get("speaker"), names), start, end, text


def merge_by_speaker(segments: list[dict[str, Any]], names: dict[str, str] | None = None) -> list[dict[str, Any]]:
    """把連續且同一講者的段落合併成區塊，回傳 ``[{speaker, start, end, text}, ...]``。"""
    blocks: list[dict[str, Any]] = []
    for speaker, start, end, text in _iter_segments(segments, names):
        if blocks and blocks[-1]["speaker"] == speaker:
            blocks[-1]["text"] = f"{blocks[-1]['text']} {text}".strip()
            blocks[-1]["end"] = end
        else:
            blocks.append({"speaker": speaker, "start": start, "end": end, "text": text})
    return blocks


def to_txt(segments: list[dict[str, Any]], names: dict[str, str] | None = None) -> str:
    """產生人類可讀的講者逐字稿。"""
    lines: list[str] = []
    for b in merge_by_speaker(segments, names):
        lines.append(f"[{b['speaker']}] {format_timestamp(b['start'])} - {format_timestamp(b['end'])}")
        lines.append(b["text"])
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def to_md(segments: list[dict[str, Any]], names: dict[str, str] | None = None) -> str:
    """產生 Markdown 逐字稿（講者合併區塊，方便貼進文件或給 agent 閱讀）。"""
    parts = [
        f"**{b['speaker']}** `{format_timestamp(b['start'])} - {format_timestamp(b['end'])}`\n\n{b['text']}\n"
        for b in merge_by_speaker(segments, names)
    ]
    return "\n".join(parts)


def to_srt(segments: list[dict[str, Any]], names: dict[str, str] | None = None) -> str:
    """產生 SRT 字幕，每段前綴講者標籤（不合併，保留原始時間軸）。"""
    entries = [
        f"{i}\n{format_timestamp(start, srt=True)} --> {format_timestamp(end, srt=True)}\n[{speaker}] {text}\n"
        for i, (speaker, start, end, text) in enumerate(_iter_segments(segments, names), start=1)
    ]
    return "\n".join(entries)


def to_vtt(segments: list[dict[str, Any]], names: dict[str, str] | None = None) -> str:
    """產生 WebVTT 字幕，用 ``<v 講者>`` voice tag 標註講者。"""
    cues = [
        f"{format_timestamp(start, vtt=True)} --> {format_timestamp(end, vtt=True)}\n<v {speaker}>{text}\n"
        for speaker, start, end, text in _iter_segments(segments, names)
    ]
    return "WEBVTT\n\n" + "\n".join(cues)


def to_json(result: dict[str, Any]) -> str:
    """輸出逐字稿 JSON（schema_version 1）。

    ``segments[].speaker`` 永遠是原始標籤；改名只寫進 ``speaker_names``，因此可逆。
    """
    payload = {
        "schema_version": TRANSCRIPT_SCHEMA_VERSION,
        "language": result.get("language"),
        "source": result.get("source"),
        "speaker_names": result.get("speaker_names") or {},
        "segments": [
            {
                "speaker": seg.get("speaker", UNKNOWN_SPEAKER) or UNKNOWN_SPEAKER,
                "start": seg.get("start"),
                "end": seg.get("end"),
                "text": clean_text(seg.get("text")),
            }
            for seg in result.get("segments", [])
        ],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _segment_renderer(fn: Callable[..., str]) -> Callable[[dict[str, Any]], str]:
    return lambda result: fn(result.get("segments", []), result.get("speaker_names"))


RENDERERS: dict[str, Callable[[dict[str, Any]], str]] = {
    "txt": _segment_renderer(to_txt),
    "srt": _segment_renderer(to_srt),
    "vtt": _segment_renderer(to_vtt),
    "md": _segment_renderer(to_md),
    "json": to_json,
}
DEFAULT_FORMATS = ("txt", "srt", "json")


def parse_formats(value: str | list[str]) -> list[str]:
    """解析並驗證 ``txt,srt`` 形式的格式清單；未知格式直接報錯，不默默略過。"""
    items = value.split(",") if isinstance(value, str) else value
    formats = list(dict.fromkeys(f.strip().lower() for f in items if f.strip()))
    unknown = [f for f in formats if f not in RENDERERS]
    if unknown or not formats:
        raise InvalidArgumentError(
            f"unknown format(s): {', '.join(unknown) or '(empty)'}",
            hint=f"可用格式：{','.join(RENDERERS)}",
        )
    return formats


def write_outputs(result: dict[str, Any], base_path: Path, formats: list[str]) -> list[Path]:
    """把指定格式寫到 ``base_path.<ext>``，回傳實際寫出的檔案路徑清單。"""
    formats = parse_formats(formats)
    base_path.parent.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for fmt in formats:
        out = base_path.with_name(f"{base_path.name}.{fmt}")
        out.write_text(RENDERERS[fmt](result), encoding="utf-8")
        written.append(out)
    return written
