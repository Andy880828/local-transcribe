"""媒體處理：所有 ffmpeg / ffprobe 相關職責集中於此。

- ``probe``          用 ffprobe 列出容器、長度、影像軌與所有音軌
- ``prepare_audio``  把影片／音檔的指定音軌轉成 16kHz 單聲道 WAV（轉錄前處理）
- ``extract_audio``  從影片抽出指定音軌成 wav/m4a/mp3/flac
- ``clip``           依時間切出片段（回聽某段對話用）

WhisperX/faster-whisper 內部雖也用 ffmpeg 載入，但先正規化成統一格式能避免
某些容器（m4a/視訊軌/多音軌）帶來的取樣率或聲道問題，也方便 pyannote 取得一致輸入。

音軌編號 ``track`` 一律是「第幾條音軌」(0 起算，對應 ffmpeg 的 ``0:a:N``)，
不是容器內的 stream index；兩者在有影像軌時不同，probe 結果兩個都會列出。
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

from .errors import (
    AudioError,
    InputNotFoundError,
    InvalidArgumentError,
    NoAudioStreamError,
    ToolMissingError,
)

TARGET_SAMPLE_RATE = 16_000

# 資料夾展開時視為可處理的媒體副檔名（單一來源；指定單一檔案時不受此限）
AUDIO_EXTENSIONS = frozenset({".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg", ".opus", ".wma"})
VIDEO_EXTENSIONS = frozenset({".mp4", ".mkv", ".mov", ".avi", ".webm", ".m4v", ".wmv", ".flv", ".ts"})
MEDIA_EXTENSIONS = AUDIO_EXTENSIONS | VIDEO_EXTENSIONS

# extract 可輸出的音訊格式 → ffmpeg 編碼參數（允許值的單一來源）
AUDIO_EXPORT_CODECS: dict[str, list[str]] = {
    "wav": ["-c:a", "pcm_s16le"],
    "flac": ["-c:a", "flac"],
    "mp3": ["-c:a", "libmp3lame", "-q:a", "2"],
    "m4a": ["-c:a", "aac", "-b:a", "192k"],
}

# 封面圖（mp3/m4a 內嵌專輯圖）在 ffprobe 也是 video stream，需排除
_ATTACHED_PIC = "attached_pic"


def ensure_tool(name: str) -> str:
    """確認系統有指定外部工具（ffmpeg / ffprobe），回傳其路徑。"""
    path = shutil.which(name)
    if not path:
        raise ToolMissingError(
            f"{name} not found on PATH",
            hint=f"找不到 {name}。請先安裝 ffmpeg（Windows: winget install ffmpeg）並確認在 PATH 中。",
        )
    return path


def ensure_ffmpeg() -> str:
    return ensure_tool("ffmpeg")


def require_file(path: Path) -> Path:
    if not path.is_file():
        raise InputNotFoundError(
            f"input file not found: {path}",
            hint=f"找不到輸入檔：{path}（請確認路徑與副檔名）",
        )
    return path


def parse_time(value: str | float | int) -> float:
    """把 ``90`` / ``90.5`` / ``01:30`` / ``00:01:30.250`` 轉成秒數。"""
    if isinstance(value, (int, float)):
        seconds = float(value)
    else:
        text = value.strip()
        if not re.fullmatch(r"\d+(\.\d+)?|(\d+:){1,2}\d+(\.\d+)?", text):
            raise InvalidArgumentError(
                f"invalid time: {value!r}",
                hint="時間格式應為秒數（90 / 90.5）或 MM:SS / HH:MM:SS(.mmm)。",
            )
        seconds = 0.0
        for part in text.split(":"):
            seconds = seconds * 60 + float(part)
    if seconds < 0:
        raise InvalidArgumentError(f"negative time: {value!r}", hint="時間不可為負。")
    return seconds


def _to_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_probe(raw: dict[str, Any], path: Path) -> dict[str, Any]:
    """把 ffprobe 的 JSON 輸出整理成精簡結構（純函式，方便測試）。

    ``duration`` 取不到時為 ``None``（不湊 0）。
    """
    streams = raw.get("streams", [])
    fmt = raw.get("format", {})
    audio_tracks: list[dict[str, Any]] = []
    has_video = False
    for stream in streams:
        kind = stream.get("codec_type")
        if kind == "video" and not stream.get("disposition", {}).get(_ATTACHED_PIC):
            has_video = True
        elif kind == "audio":
            tags = stream.get("tags", {}) or {}
            audio_tracks.append(
                {
                    "track": len(audio_tracks),
                    "stream_index": stream.get("index"),
                    "codec": stream.get("codec_name"),
                    "channels": stream.get("channels"),
                    "sample_rate": int(stream["sample_rate"]) if stream.get("sample_rate") else None,
                    "language": tags.get("language"),
                    "title": tags.get("title"),
                    "duration": _to_float(stream.get("duration")),
                }
            )
    return {
        "path": str(path),
        "container": fmt.get("format_name"),
        "duration": _to_float(fmt.get("duration")),
        "kind": "video" if has_video else "audio",
        "has_video": has_video,
        "audio_tracks": audio_tracks,
    }


def probe(path: Path) -> dict[str, Any]:
    """用 ffprobe 讀取媒體資訊。"""
    require_file(path)
    ffprobe = ensure_tool("ffprobe")
    proc = subprocess.run(
        [ffprobe, "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if proc.returncode != 0:
        raise AudioError(
            f"ffprobe failed (code {proc.returncode}): {proc.stderr.strip()}",
            hint=f"無法讀取媒體檔 {path.name}，可能已損毀或不是影音檔。",
        )
    return parse_probe(json.loads(proc.stdout or "{}"), path)


def require_audio_track(info: dict[str, Any], track: int) -> dict[str, Any]:
    """確認 probe 結果中有第 ``track`` 條音軌，回傳該音軌資訊。"""
    tracks = info["audio_tracks"]
    if not tracks:
        raise NoAudioStreamError(
            f"no audio stream in {info['path']}",
            hint="此檔案沒有任何音軌，無法轉錄。",
        )
    if not 0 <= track < len(tracks):
        raise NoAudioStreamError(
            f"audio track {track} out of range (has {len(tracks)})",
            hint=f"此檔案只有 {len(tracks)} 條音軌（編號 0~{len(tracks) - 1}），請改用 --audio-track 指定。",
        )
    return tracks[track]


def _run_ffmpeg(args: list[str], out_path: Path) -> Path:
    cmd = [ensure_ffmpeg(), "-y", "-loglevel", "error", *args, str(out_path)]
    out_path.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if proc.returncode != 0 or not out_path.exists():
        raise AudioError(
            f"ffmpeg failed (code {proc.returncode}): {proc.stderr.strip() or 'unknown error'}",
            hint="ffmpeg 處理失敗，請確認輸入檔可正常播放、輸出路徑可寫入。",
        )
    return out_path


def prepare_audio(input_path: Path, work_dir: Path, track: int = 0) -> Path:
    """把輸入檔的第 ``track`` 條音軌轉為 16kHz 單聲道 WAV，回傳 WAV 路徑。"""
    require_file(input_path)
    out_path = work_dir / f"{input_path.stem}.16k.wav"
    return _run_ffmpeg(
        [
            "-i",
            str(input_path),
            "-map",
            f"0:a:{track}",
            "-ac",
            "1",
            "-ar",
            str(TARGET_SAMPLE_RATE),
            "-vn",
        ],
        out_path,
    )


def extract_audio(input_path: Path, out_path: Path, track: int = 0) -> Path:
    """抽出第 ``track`` 條音軌，輸出格式由 ``out_path`` 副檔名決定。"""
    fmt = out_path.suffix.lstrip(".").lower()
    if fmt not in AUDIO_EXPORT_CODECS:
        raise InvalidArgumentError(
            f"unsupported audio format: {fmt}",
            hint=f"可用格式：{', '.join(AUDIO_EXPORT_CODECS)}",
        )
    require_file(input_path)
    return _run_ffmpeg(
        ["-i", str(input_path), "-map", f"0:a:{track}", "-vn", *AUDIO_EXPORT_CODECS[fmt]],
        out_path,
    )


def clip(input_path: Path, out_path: Path, start: float, end: float) -> Path:
    """切出 [start, end) 秒的片段（重新編碼以確保切點精準）。"""
    if end <= start:
        raise InvalidArgumentError(
            f"end ({end}) must be greater than start ({start})",
            hint="--end 必須晚於 --start。",
        )
    require_file(input_path)
    return _run_ffmpeg(
        ["-ss", f"{start:.3f}", "-i", str(input_path), "-t", f"{end - start:.3f}"],
        out_path,
    )
