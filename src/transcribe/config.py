"""設定載入與驗證。

使用 pydantic-settings 從 .env / 環境變數讀取設定，於系統邊界完成驗證
（coding-style：始終在系統邊界驗證、密鑰不進原始碼）。

HF token 採「延遲驗證」：載入時允許為空，真正需要講者分辨時才呼叫
``require_hf_token``，這樣「只轉錄不分辨」(--no-diarize) 不會被缺失金鑰擋住。
"""

from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from .errors import MissingCredentialError


class Settings(BaseSettings):
    """執行期設定。欄位可由 .env、環境變數或 CLI 旗標覆寫。"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
        populate_by_name=True,  # 允許用欄位名稱（非 alias）建構，供 CLI 旗標覆寫
    )

    # 密鑰（載入時可空，使用前才驗證）
    hf_token: str = Field(default="", alias="HF_TOKEN")

    # 講者分辨模型（新版 whisperx 預設為 community-1，但需另接受授權；
    # 預設指回多數人已接受的 3.1 以降低摩擦，可用 DIARIZE_MODEL 覆寫）
    diarize_model: str = Field(
        default="pyannote/speaker-diarization-3.1", alias="DIARIZE_MODEL"
    )

    # 轉錄設定
    whisper_model: str = Field(default="large-v3", alias="WHISPER_MODEL")
    language: str = Field(default="zh", alias="LANGUAGE")
    compute_type: str = Field(default="float16", alias="COMPUTE_TYPE")
    batch_size: int = Field(default=8, alias="BATCH_SIZE")
    device: str = Field(default="cuda", alias="DEVICE")

    # 輸出
    output_dir: Path = Field(default=Path("outputs"), alias="OUTPUT_DIR")

    def require_hf_token(self) -> str:
        """取得 HF token，缺失則拋出帶設定指引的錯誤。"""
        if not self.hf_token.strip():
            raise MissingCredentialError(
                "HF_TOKEN is not set",
                hint=(
                    "講者分辨需要 Hugging Face token。請在 .env 設定 HF_TOKEN，"
                    "並接受 pyannote/speaker-diarization-3.1 與 "
                    "pyannote/segmentation-3.0 的授權條款。"
                    "（若不需分辨，可加 --no-diarize 略過。）"
                ),
            )
        return self.hf_token.strip()


def load_settings(**overrides: object) -> Settings:
    """載入設定，允許以 CLI 旗標覆寫（None 值會被忽略，沿用預設）。"""
    clean = {k: v for k, v in overrides.items() if v is not None}
    return Settings(**clean)
