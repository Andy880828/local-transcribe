"""講者分辨階段：用 pyannote (透過 WhisperX 的 DiarizationPipeline) 找出
誰在何時說話，再把講者標籤指派到每個段落/字詞。

WhisperX 不同版本的匯入路徑不同（3.3 起搬到 whisperx.diarize），這裡做
相容處理。pyannote 是 gated 模型，需 HF token 且須接受授權條款。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .config import Settings
from .errors import DiarizationError
from .gpu import free_gpu


def _load_diarize_components():
    """跨 whisperx 版本取得 (DiarizationPipeline, assign_word_speakers)。"""
    try:
        from whisperx.diarize import DiarizationPipeline, assign_word_speakers

        return DiarizationPipeline, assign_word_speakers
    except ImportError:
        pass
    try:
        from whisperx import DiarizationPipeline, assign_word_speakers  # 舊版

        return DiarizationPipeline, assign_word_speakers
    except ImportError as exc:  # pragma: no cover
        raise DiarizationError(
            "cannot import DiarizationPipeline from whisperx",
            hint="whisperx 版本不相容或未安裝，請依 README 重新安裝相依。",
        ) from exc


def _build_init_kwargs(pipeline_cls: type, hf_token: str, model_name: str) -> dict[str, str]:
    """依建構子實際簽名組出相容的 kwargs（跨 whisperx 版本）。

    - 授權參數：新版 ``token`` / 舊版 ``use_auth_token``
    - 模型名稱：新版才有 ``model_name``（用來指定非預設的分辨模型）
    """
    import inspect

    params = inspect.signature(pipeline_cls.__init__).parameters
    kwargs: dict[str, str] = {}
    if "token" in params:
        kwargs["token"] = hf_token
    elif "use_auth_token" in params:
        kwargs["use_auth_token"] = hf_token
    if "model_name" in params and model_name:
        kwargs["model_name"] = model_name
    return kwargs


def _looks_like_gated_error(exc: Exception) -> bool:
    text = str(exc).lower()
    return "401" in text or "unauthorized" in text or "gated" in text or "access" in text


def diarize_transcript(
    audio_path: Path,
    result: dict[str, Any],
    settings: Settings,
    num_speakers: int | None = None,
    min_speakers: int | None = None,
    max_speakers: int | None = None,
) -> dict[str, Any]:
    """對已轉錄的 result 做講者分辨，回傳帶 ``speaker`` 標籤的 result。

    Args:
        audio_path: 已正規化的 16k WAV。
        result: transcribe_audio 的輸出。
        num_speakers: 已知確切人數（優先）。
        min_speakers / max_speakers: 人數範圍（未知人數時用）。
    """
    hf_token = settings.require_hf_token()
    DiarizationPipeline, assign_word_speakers = _load_diarize_components()

    try:
        pipeline = DiarizationPipeline(
            device=settings.device,
            **_build_init_kwargs(DiarizationPipeline, hf_token, settings.diarize_model),
        )
        diarize_segments = pipeline(
            str(audio_path),
            num_speakers=num_speakers,
            min_speakers=min_speakers,
            max_speakers=max_speakers,
        )
        # 新版 __call__ 在 return_embeddings=True 時回傳 (df, embeddings)；
        # 我們沒開該選項，但保險起見取第一個元素。
        if isinstance(diarize_segments, tuple):
            diarize_segments = diarize_segments[0]
        result = assign_word_speakers(diarize_segments, result)
        free_gpu(pipeline)
        return result
    except DiarizationError:
        raise
    except Exception as exc:
        if _looks_like_gated_error(exc):
            raise DiarizationError(
                str(exc),
                hint=(
                    f"無法下載分辨模型 '{settings.diarize_model}'，通常是尚未接受該 repo 的授權。"
                    f"請以同一個 HF 帳號登入並接受：https://huggingface.co/{settings.diarize_model} "
                    "以及 https://huggingface.co/pyannote/segmentation-3.0。"
                    "（或用 --diarize-model 指定你已接受授權的其他模型。）"
                ),
            ) from exc
        raise DiarizationError(
            str(exc),
            hint="講者分辨失敗，請檢查 HF token 是否有效、網路是否可連 huggingface.co。",
        ) from exc
