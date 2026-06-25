"""集中定義所有自訂例外，讓 CLI 能對不同錯誤給出友善訊息。

設計原則（遵循 coding-style：錯誤需顯式處理、訊息對使用者友善）：
每個例外都帶一段可直接顯示給使用者的中文 ``hint``，CLI 層只負責呈現。
"""

from __future__ import annotations


class TranscribeError(Exception):
    """本工具所有錯誤的基底類別。"""

    def __init__(self, message: str, hint: str | None = None) -> None:
        super().__init__(message)
        self.hint = hint


class MissingCredentialError(TranscribeError):
    """缺少必要的金鑰（HF_TOKEN 或 ANTHROPIC_API_KEY）。"""


class AudioError(TranscribeError):
    """音檔不存在、格式不支援或 ffmpeg 轉檔失敗。"""


class GPUOutOfMemoryError(TranscribeError):
    """GPU 記憶體不足（CUDA OOM）。"""


class DiarizationError(TranscribeError):
    """講者分辨失敗，常見原因是 pyannote gated 模型授權未接受。"""
