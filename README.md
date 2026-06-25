# local-transcribe

本地語音轉錄 + 講者分辨 CLI 工具。輸入音檔，輸出**已標註講者的逐字稿**（`.txt` / `.srt` / `.json`）。

轉錄與講者分辨 100% 在本地 GPU 執行，不上傳任何音訊。產出的逐字稿可自行貼到 Claude Code 或網站彙整摘要——本工具不含摘要功能。

## 技術組成

| 環節 | 方案 |
|------|------|
| 轉錄 | [WhisperX](https://github.com/m-bain/whisperX)（faster-whisper / CTranslate2 後端，預設 `large-v3`）|
| 詞級對齊 | wav2vec2（可用 `--no-align` 關閉）|
| 講者分辨 | pyannote `speaker-diarization-3.1`（gated 模型，需 HF token）|
| 前處理 | 系統 ffmpeg（轉 16kHz 單聲道）|
| CLI | Typer |

## 環境需求

- NVIDIA GPU（建議 ≥ 6GB VRAM；本專案在 RTX 4060 / 8GB 上開發）
- 系統已安裝 **ffmpeg** 且在 PATH 中
- **uv**（Python 套件 / 環境管理器）

## 安裝（使用 uv）

```bash
cd local-transcribe

# 1) 建立 Python 3.11 虛擬環境（uv 會自動下載對應 Python）
uv venv --python 3.11
# Windows 啟用：
.venv\Scripts\activate

# 2) 先裝 CUDA 12.1 版 torch（RTX 40 系列適用，自帶 cuDNN）
uv pip install torch==2.4.1 torchaudio==2.4.1 --index-url https://download.pytorch.org/whl/cu121

# 3) 裝本專案與其餘相依（whisperx 會帶入 faster-whisper / pyannote）
uv pip install -e .
```

> ⚠️ **安裝順序很重要**：一定要先裝 cu121 版 torch，否則 pip 會拉到 CPU 版，無法用 GPU。

## 設定金鑰（講者分辨必需）

1. 複製 `.env.example` 為 `.env`
2. 到 <https://huggingface.co/settings/tokens> 申請一組 read token，填入 `HF_TOKEN`
3. **以同一帳號登入並接受兩個 gated 模型的授權**（否則下載會 401）：
   - <https://huggingface.co/pyannote/speaker-diarization-3.1>
   - <https://huggingface.co/pyannote/segmentation-3.0>

> 若你只要轉錄、不需分辨講者，可加 `--no-diarize`，這樣不需要 HF token。

## 使用

```bash
# 中文會議，已知 3 位講者，輸出 txt/srt/json
transcribe run meeting.m4a --language zh --speakers 3

# 只轉錄、不分辨講者（不需 HF token）
transcribe run note.m4a --no-diarize

# VRAM 不足時降載
transcribe run meeting.m4a --compute-type int8 --batch-size 4

# 人數未知，給範圍
transcribe run panel.wav --min-speakers 2 --max-speakers 5

# 自訂輸出資料夾與格式
transcribe run a.mp3 -o ./outputs -f txt,srt
```

結果預設寫到 `outputs/<檔名>.txt`、`.srt`、`.json`。

### 主要旗標

| 旗標 | 說明 |
|------|------|
| `--language, -l` | 語言代碼（`zh`）；留空自動偵測 |
| `--model, -m` | Whisper 模型（`large-v3`）|
| `--speakers` | 已知確切講者人數 |
| `--min-speakers` / `--max-speakers` | 講者人數範圍 |
| `--align / --no-align` | 詞級對齊（中文品質普通，可關）|
| `--diarize / --no-diarize` | 講者分辨開關 |
| `--compute-type` | `float16`（預設）/ `int8` / `float32` |
| `--batch-size` | 批次大小，VRAM 不足時調小 |
| `--device` | `cuda` / `cpu` |
| `--output-dir, -o` | 輸出資料夾 |
| `--format, -f` | 輸出格式，逗號分隔（`txt,srt,json`）|

## 輸出範例（.txt）

```
[SPEAKER_00] 00:00:00 - 00:00:05
你好，今天我們來討論下一季的規劃。

[SPEAKER_01] 00:00:05 - 00:00:12
好的，我先報告一下目前的進度。
```

## 開發 / 測試

```bash
uv pip install -e ".[dev]"
pytest            # 離線單元測試，不需 GPU 或金鑰
```

測試刻意把 GPU 階段（audio/transcribe/diarize）全部 mock，可在無 GPU 環境跑。

## 疑難排解

| 症狀 | 處置 |
|------|------|
| CUDA out of memory | `--compute-type int8 --batch-size 4`，或 `--device cpu` |
| pyannote 下載 401 / gated | 確認已接受上述兩個模型授權，且 token 屬同一帳號 |
| 找不到 ffmpeg | 安裝 ffmpeg 並加入 PATH（`winget install ffmpeg`）|
| 中文講者邊界漂移 | 加 `--no-align` 試試 |
| cuDNN DLL 錯誤 | 確認用 cu121 版 torch（自帶 cuDNN）；必要時改 `--device cpu` |
```
