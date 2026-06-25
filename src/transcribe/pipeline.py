"""串接完整流程：音檔 → 轉錄 → (對齊) → 講者分辨 → 輸出逐字稿。

各重量級階段間靠 gpu.free_gpu 釋放 VRAM，確保 8GB 卡也能依序跑完。
模組函式採延遲匯入，CLI 與測試可在不載入 GPU 套件時匯入本模組。
"""

from __future__ import annotations

import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .config import Settings


@dataclass
class PipelineOptions:
    """單次執行的選項（多由 CLI 旗標帶入）。"""

    align: bool = True
    diarize: bool = True
    num_speakers: int | None = None
    min_speakers: int | None = None
    max_speakers: int | None = None
    formats: list[str] = field(default_factory=lambda: ["txt", "srt", "json"])


@dataclass
class PipelineResult:
    """執行結果。"""

    result: dict[str, Any]
    outputs: list[Path]
    language: str | None


def run_pipeline(
    input_path: Path,
    settings: Settings,
    options: PipelineOptions,
    progress: Callable[[str], None] | None = None,
) -> PipelineResult:
    """執行完整轉錄流程並寫出檔案。

    Args:
        input_path: 原始音檔。
        settings: 設定。
        options: 執行選項。
        progress: 可選的進度回呼（接收一段中文訊息），CLI 用來顯示狀態。
    """
    # 延遲匯入：讓不需要 GPU 的測試能 import 本模組
    from .audio import prepare_audio
    from .diarize import diarize_transcript
    from .transcribe import transcribe_audio

    def report(msg: str) -> None:
        if progress:
            progress(msg)

    with tempfile.TemporaryDirectory(prefix="transcribe_") as tmp:
        work_dir = Path(tmp)

        report("正在前處理音訊 (ffmpeg 轉 16k 單聲道)…")
        wav_path = prepare_audio(input_path, work_dir)

        report(f"正在轉錄 (模型 {settings.whisper_model}, 對齊={'開' if options.align else '關'})…")
        result = transcribe_audio(wav_path, settings, align=options.align)

        if options.diarize:
            report("正在進行講者分辨 (pyannote)…")
            result = diarize_transcript(
                wav_path,
                result,
                settings,
                num_speakers=options.num_speakers,
                min_speakers=options.min_speakers,
                max_speakers=options.max_speakers,
            )

        report("正在寫出逐字稿…")
        from .formats import write_outputs

        base_path = settings.output_dir / input_path.stem
        outputs = write_outputs(result, base_path, options.formats)

    return PipelineResult(
        result=result,
        outputs=outputs,
        language=result.get("language"),
    )
