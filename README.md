# local-transcribe

本地影音轉錄 + 多人聲辨識 CLI。輸入**影片或錄音**，輸出**有時間序、標註講者的逐字稿**（`.txt` / `.srt` / `.vtt` / `.md` / `.json`）。

- 轉錄與講者分辨 100% 在本地 GPU 執行，不上傳任何音訊。
- **為 AI agent 設計**：`--json` 輸出單一 JSON envelope、穩定錯誤碼與建議動作、`schema` 自我描述；
  `.claude/skills/` 內附 6 個 SKILL，Claude Code 可直接調用（轉錄、媒體工具、改名匯出、查詢、批次、會議摘要）。

## 環境需求

- NVIDIA GPU（建議 ≥ 6GB VRAM；開發於 RTX 4060 / 8GB）
- 系統已安裝 **ffmpeg**（含 ffprobe）且在 PATH 中（`winget install ffmpeg`）
- **uv**

## 安裝

```bash
cd local-transcribe
uv venv --python 3.11
.venv\Scripts\activate

# 先裝 CUDA 版 torch（否則會拉到 CPU 版，無法用 GPU）
uv pip install torch torchaudio --torch-backend=auto
uv pip install -e ".[dev]"
```

## 設定金鑰（講者分辨必需）

1. 複製 `.env.example` 為 `.env`，到 <https://huggingface.co/settings/tokens> 申請 read token 填入 `HF_TOKEN`
2. 以同一帳號接受兩個 gated 模型授權（否則 401）：
   - <https://huggingface.co/pyannote/speaker-diarization-3.1>
   - <https://huggingface.co/pyannote/segmentation-3.0>

只轉錄、不分辨講者時加 `--no-diarize`，不需要 token。其餘預設值（模型、語言、抗幻覺參數）見 `.env.example`。

## 使用

```bash
# 影片 → 多講者逐字稿（已知 3 人）
uv run transcribe run meeting.mp4 --speakers 3

# 多音軌影片：先看音軌，再選第 1 條
uv run transcribe media probe movie.mkv
uv run transcribe run movie.mkv --audio-track 1 --min-speakers 2 --max-speakers 5

# 整個資料夾批次，跳過已轉好的
uv run transcribe run ./recordings --skip-existing

# 只抽音軌 / 切片段回聽
uv run transcribe media extract meeting.mp4 -f mp3
uv run transcribe media clip meeting.mp4 --start 00:12:30 --end 00:13:10

# 逐字稿後處理
uv run transcribe transcript rename outputs/meeting/meeting.json --map SPEAKER_00=王小明
uv run transcribe transcript export outputs/meeting/meeting.json -f vtt,md
uv run transcribe transcript search outputs/meeting/meeting.json "交期" -C 1
uv run transcribe transcript stats outputs/meeting/meeting.json

# 給程式／AI 用：加 --json；查全部指令與錯誤碼
uv run transcribe --json schema
```

每個輸入檔一個資料夾：逐字稿寫到 `outputs/<檔名>/<檔名>.<格式>`，抽出的音軌、切出的片段、摘要也放同一資料夾。各指令完整旗標：`uv run transcribe <指令> --help`。

### `--json` 輸出

```json
{"ok": true,  "command": "run", "data": {"files": [...], "summary": {"ok": 1, "skipped": 0, "error": 0}}}
{"ok": false, "command": "run", "error": {"code": "GPU_OOM", "message": "...", "hint": "...",
  "action": "retry_with", "retry_args": ["--compute-type", "int8", "--batch-size", "4"]}}
```

stdout 只有這一個 JSON，進度在 stderr。`action` 告訴呼叫端下一步：`fix_input`、`fix_environment`、`retry_with`、`none`。
批次有任一檔失敗時 exit code 為 10（`PARTIAL_FAILURE`），成功的檔案仍會寫出。

## 疑難排解

| 症狀 | 處置 |
|---|---|
| `GPU_OOM` | `--compute-type int8 --batch-size 4`，或 `--device cpu` |
| `DIARIZATION_FAILED`（401 / gated） | 確認已接受上述兩個模型授權，且 token 屬同一帳號 |
| `TOOL_MISSING` | 安裝 ffmpeg 並加入 PATH |
| `CUDA_UNAVAILABLE` | 重裝 CUDA 版 torch（見安裝）；或 `--device cpu` |
| 下載模型時 `WinError 1314` | Windows 無法建立 symlink：開啟「開發人員模式」或在一般終端機執行 |
| 重複幻覺（同字連發） | `--repetition-penalty 1.3 --no-repeat-ngram-size 2`；吵雜錄音先用 UVR 去背景音 |
| 中文講者邊界漂移 | 加 `--no-align` 試試 |

## 開發

```bash
uv run pytest -q          # 離線測試，GPU 階段皆 mock
uvx ruff check src tests
```

開發者與 agent 請先讀 `AGENTS.md`，再從 `docs/PROGRESS.md` 開始。
