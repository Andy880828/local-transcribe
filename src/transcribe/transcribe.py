"""轉錄階段：用 WhisperX (faster-whisper 後端) 把 WAV 轉成逐字段落，
可選用 wav2vec2 做詞級對齊以提升時間戳精度。

whisperx / torch 都採延遲匯入（函式內 import），讓不需要 GPU 的單元測試
（formats、pipeline orchestration mock）能在沒裝這些重量級套件時照樣執行。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .config import Settings
from .errors import GPUOutOfMemoryError, TranscribeError
from .gpu import ensure_cuda, free_gpu


def _is_oom(exc: Exception) -> bool:
    text = str(exc).lower()
    return "out of memory" in text or "cuda oom" in text or "cublas" in text


def transcribe_audio(
    audio_path: Path,
    settings: Settings,
    align: bool = True,
) -> dict[str, Any]:
    """轉錄音檔，回傳 WhisperX result（含 segments）。

    Args:
        audio_path: 已正規化的 16k 單聲道 WAV。
        settings: 設定（模型、語言、精度、batch size、device）。
        align: 是否做 wav2vec2 詞級對齊（中文對齊品質普通，可關閉）。
    """
    try:
        import whisperx
    except ImportError as exc:  # pragma: no cover - 僅在未安裝時觸發
        raise TranscribeError(
            "whisperx is not installed",
            hint="尚未安裝 whisperx，請依 README 用 uv 安裝相依套件。",
        ) from exc

    ensure_cuda(settings.device)

    try:
        audio = whisperx.load_audio(str(audio_path))

        # --- 轉錄 ---
        model = whisperx.load_model(
            settings.whisper_model,
            device=settings.device,
            compute_type=settings.compute_type,
            language=settings.language or None,
        )
        result = model.transcribe(audio, batch_size=settings.batch_size)
        free_gpu(model)

        detected_language = result.get("language", settings.language)

        # --- 可選：詞級對齊 ---
        if align:
            align_model, metadata = whisperx.load_align_model(
                language_code=detected_language,
                device=settings.device,
            )
            result = whisperx.align(
                result["segments"],
                align_model,
                metadata,
                audio,
                settings.device,
                return_char_alignments=False,
            )
            free_gpu(align_model)

        result["language"] = detected_language
        return result
    except RuntimeError as exc:
        if _is_oom(exc):
            raise GPUOutOfMemoryError(
                str(exc),
                hint="GPU 記憶體不足。請改用 --compute-type int8 並調小 --batch-size（如 4），或 --device cpu。",
            ) from exc
        raise
