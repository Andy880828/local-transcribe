"""集中定義所有自訂例外，以及錯誤碼／exit code／建議動作的唯一決定點。

設計原則：
- 每個例外帶一段可直接顯示給使用者的中文 ``hint``，CLI 層只負責呈現。
- ``code`` / ``exit_code`` / ``action`` 是類別屬性，CLI 的 JSON envelope 與
  exit code 都只從這裡取，不在別處手寫。
- ``action`` 的分類軸是「使用者（或 agent）現在該做什麼」，不是內部發生什麼：
  ``fix_input``       修正輸入（路徑、參數、檔案內容）
  ``fix_environment`` 修環境（安裝 ffmpeg、設定 HF_TOKEN、接受模型授權、裝 CUDA 版 torch）
  ``retry_with``      換參數重跑即可，建議旗標放在 ``retry_args``
  ``none``            不需處理（例如部分成功的批次，失敗項已逐筆列出）
"""

from __future__ import annotations

ACTIONS = ("fix_input", "fix_environment", "retry_with", "none")


class TranscribeError(Exception):
    """本工具所有錯誤的基底類別。"""

    code = "INTERNAL_ERROR"
    exit_code = 1
    action = "fix_environment"

    def __init__(
        self,
        message: str,
        hint: str | None = None,
        retry_args: list[str] | None = None,
    ) -> None:
        super().__init__(message)
        self.hint = hint
        self.retry_args = retry_args

    def to_dict(self) -> dict[str, object]:
        """轉成 JSON envelope 的 ``error`` 欄位。"""
        payload: dict[str, object] = {
            "code": self.code,
            "message": str(self),
            "hint": self.hint,
            "action": self.action,
        }
        if self.retry_args:
            payload["retry_args"] = self.retry_args
        return payload


class InvalidArgumentError(TranscribeError):
    """旗標或參數值不合法（例如未知的輸出格式、時間字串格式錯誤）。"""

    code = "INVALID_ARGUMENT"
    exit_code = 2
    action = "fix_input"


class InputNotFoundError(TranscribeError):
    """輸入檔或資料夾不存在，或資料夾內沒有可處理的媒體檔。"""

    code = "INPUT_NOT_FOUND"
    exit_code = 3
    action = "fix_input"


class AudioError(TranscribeError):
    """媒體檔格式不支援或 ffmpeg / ffprobe 處理失敗。"""

    code = "MEDIA_ERROR"
    exit_code = 3
    action = "fix_input"


class NoAudioStreamError(AudioError):
    """媒體檔沒有音軌，或指定的音軌編號不存在。"""

    code = "NO_AUDIO_STREAM"


class InvalidTranscriptError(TranscribeError):
    """逐字稿 JSON 無法解析或結構不符。"""

    code = "INVALID_TRANSCRIPT"
    exit_code = 3
    action = "fix_input"


class ToolMissingError(TranscribeError):
    """系統缺少外部工具（ffmpeg / ffprobe / whisperx / torch）。"""

    code = "TOOL_MISSING"
    exit_code = 4
    action = "fix_environment"


class MissingCredentialError(TranscribeError):
    """缺少必要的金鑰（HF_TOKEN）。"""

    code = "MISSING_CREDENTIAL"
    exit_code = 4
    action = "fix_environment"


class CudaUnavailableError(TranscribeError):
    """指定 cuda 但 torch 偵測不到 CUDA。"""

    code = "CUDA_UNAVAILABLE"
    exit_code = 5
    action = "fix_environment"


class GPUOutOfMemoryError(TranscribeError):
    """GPU 記憶體不足（CUDA OOM）。"""

    code = "GPU_OOM"
    exit_code = 5
    action = "retry_with"


class DiarizationError(TranscribeError):
    """講者分辨失敗，常見原因是 pyannote gated 模型授權未接受。"""

    code = "DIARIZATION_FAILED"
    exit_code = 6
    action = "fix_environment"


class PartialFailureError(TranscribeError):
    """批次處理中部分檔案失敗；成功與失敗的明細另由 CLI 放在 data 中。"""

    code = "PARTIAL_FAILURE"
    exit_code = 10
    action = "none"
