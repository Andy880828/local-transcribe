"""轉錄階段：用 WhisperX (faster-whisper 後端) 把 WAV 轉成逐字段落，
可選用 wav2vec2 做詞級對齊以提升時間戳精度。

whisperx / torch 都採延遲匯入（函式內 import），讓不需要 GPU 的單元測試
（formats、pipeline orchestration mock）能在沒裝這些重量級套件時照樣執行。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .config import Settings
from .errors import GPUOutOfMemoryError, ToolMissingError
from .gpu import ensure_cuda, free_gpu


def _is_oom(exc: Exception) -> bool:
    text = str(exc).lower()
    return "out of memory" in text or "cuda oom" in text or "cublas" in text


def build_asr_options(settings: Settings) -> dict[str, object]:
    """從設定組出 whisperx 的 asr_options（只含要覆寫的防幻覺旋鈕）。

    抽成純函式以便單元測試；whisperx 會把此 dict 疊加在自身預設之上。
    """
    return {
        "condition_on_previous_text": settings.condition_on_previous_text,
        "no_repeat_ngram_size": settings.no_repeat_ngram_size,
        "repetition_penalty": settings.repetition_penalty,
        "compression_ratio_threshold": settings.compression_ratio_threshold,
        "no_speech_threshold": settings.no_speech_threshold,
    }


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
        raise ToolMissingError(
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
            asr_options=build_asr_options(settings),
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
                retry_args=["--compute-type", "int8", "--batch-size", "4"],
            ) from exc
        raise


# 原文是這些字時，轉換後一律保留原字（OpenCC s2tw 會把它們換成另一個也正確的繁體字）。
# 實測：「台郡」被轉成「臺郡」——公司名稱被改掉。
_KEEP_ORIGINAL_CHARS = frozenset("台")


def to_traditional(result: dict[str, Any], mode: str) -> str | None:
    """把 zh* 逐字稿的簡體字轉成繁體（台灣用字），就地修改 ``result``，回傳實際套用的轉換名稱。

    Whisper 在 ``language=zh`` 時會隨機吐出簡體段落（同一支影片裡繁簡混雜）。

    為什麼選 OpenCC ``s2tw``（2026-10 以 15 支實際逐字稿量測）：
    - ``s2t``：會把正確的繁體字改成異體字（吃→喫、才→纔、為→爲）。
    - ``s2twp``：會改寫用詞（設備→裝置、數據→資料），等於改了講者說的話。
    - ``s2tw``：對已是繁體的文字近乎不動，唯一例外是 台→臺，由 ``_KEEP_ORIGINAL_CHARS`` 擋掉。

    不是中文、或 ``mode == "none"`` 時不動，回傳 ``None``。
    """
    if mode == "none" or not str(result.get("language") or "").startswith("zh"):
        return None
    try:
        import opencc
    except ImportError as exc:  # pragma: no cover - 僅在未安裝時觸發
        raise ToolMissingError(
            "opencc is not installed",
            hint="尚未安裝 opencc（簡轉繁用），請重新 uv pip install -e .；或加 --chinese-convert none 略過。",
        ) from exc

    converter = opencc.OpenCC(mode)

    def convert(text: str) -> str:
        converted = converter.convert(text)
        if len(converted) != len(text):  # s2tw 為逐字對應；長度不同時不做保留字還原
            return converted
        return "".join(o if o in _KEEP_ORIGINAL_CHARS else c for o, c in zip(text, converted))

    for seg in result.get("segments", []):
        if seg.get("text"):
            seg["text"] = convert(seg["text"])
        for word in seg.get("words", []) or []:
            if word.get("word"):
                word["word"] = convert(word["word"])
    return mode
