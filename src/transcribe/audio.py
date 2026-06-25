"""音訊前處理：用系統 ffmpeg 把任意輸入轉成 16kHz 單聲道 WAV。

WhisperX/faster-whisper 內部雖也用 ffmpeg 載入，但先正規化成統一格式能避免
某些容器（m4a/視訊軌）帶來的取樣率或聲道問題，也方便 pyannote 取得一致輸入。
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from .errors import AudioError

TARGET_SAMPLE_RATE = 16_000


def ensure_ffmpeg() -> str:
    """確認系統有 ffmpeg，回傳其路徑，否則拋出友善錯誤。"""
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise AudioError(
            "ffmpeg not found on PATH",
            hint="找不到 ffmpeg。請先安裝（Windows 可用 winget install ffmpeg）並確認在 PATH 中。",
        )
    return ffmpeg


def prepare_audio(input_path: Path, work_dir: Path) -> Path:
    """把輸入音檔轉為 16kHz 單聲道 WAV，回傳輸出 WAV 路徑。

    Args:
        input_path: 原始音檔（mp3/m4a/wav/視訊等 ffmpeg 支援的格式）。
        work_dir: 暫存資料夾，轉出的 WAV 會放這裡。
    """
    if not input_path.exists():
        raise AudioError(
            f"input file not found: {input_path}",
            hint=f"找不到輸入檔：{input_path}",
        )

    ffmpeg = ensure_ffmpeg()
    work_dir.mkdir(parents=True, exist_ok=True)
    out_path = work_dir / f"{input_path.stem}.16k.wav"

    cmd = [
        ffmpeg,
        "-y",                      # 覆寫既有輸出
        "-i", str(input_path),
        "-ac", "1",                # 單聲道
        "-ar", str(TARGET_SAMPLE_RATE),
        "-vn",                     # 去除視訊軌
        "-loglevel", "error",
        str(out_path),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0 or not out_path.exists():
        raise AudioError(
            f"ffmpeg failed (code {proc.returncode})",
            hint=f"ffmpeg 轉檔失敗：{proc.stderr.strip() or '未知錯誤'}",
        )
    return out_path
