# 架構

> 系統**怎麼實作**。要做什麼看 PRD.md，做到哪看 PROGRESS.md。
> 開發時的硬性約束與踩過的坑在 AGENTS.md——那是「不能做什麼」，本檔是「長什麼樣」。

## 技術棧

| 環節 | 選擇 |
|---|---|
| 轉錄 | WhisperX（faster-whisper / CTranslate2，預設 `large-v3`） |
| 詞級對齊 | wav2vec2（`--no-align` 可關） |
| 講者分辨 | pyannote `speaker-diarization-3.1`（gated，需 HF token） |
| 媒體處理 | 系統 ffmpeg / ffprobe（subprocess，無 Python 綁定） |
| CLI | Typer（鎖 0.27.x） |
| 設定 | pydantic-settings（`.env` → 環境變數 → CLI 旗標） |
| 套件管理 | uv；lint／format 用 ruff |

## 資料流

```
影片/音檔 ──ffprobe──▶ 音軌資訊 (kind/duration/audio_tracks)
    │                      │ 無音軌 → NO_AUDIO_STREAM（不進 GPU）
    ▼
ffmpeg 抽第 N 條音軌 → 16kHz mono WAV（暫存資料夾）
    ▼
WhisperX 轉錄 → (wav2vec2 對齊) → pyannote 分辨 → 指派講者 → OpenCC s2tw 簡轉繁（zh 才做）
    │  每階段後 free_gpu()，8GB VRAM 才能依序跑完
    ▼
write_outputs → outputs/<stem>/<stem>.{txt,srt,vtt,md,json}（一場會議一個資料夾）
    ▼
transcript.* 讀回 JSON：rename / export / search / stats
```

只有轉錄與分辨需要 GPU；probe、extract、clip、transcript 系列都不載入 torch，可在無 GPU 環境執行。

## 分層

```
cli.py         參數解析、envelope 輸出、錯誤 → exit code       （唯一處理 stdout/stderr 的地方）
  ↓
pipeline.py    單檔流程與批次編排                               （延遲匯入 GPU 模組）
  ↓
media.py / transcribe.py / diarize.py / gpu.py                 （外部工具與模型）
formats.py / transcript.py                                      （純函式＋檔案 I/O，可完整單元測試）
errors.py / config.py                                           （被所有層引用，不引用別人）
```

規則：

1. 下層不輸出到 stdout、不 `sys.exit`——只回傳值或丟 `TranscribeError` 子類別。這樣 CLI 才能保證 envelope 契約。
2. whisperx / torch 只在函式內延遲匯入——讓 CLI 啟動與大部分測試不需要 GPU 套件。
3. `formats.py` 與 `transcript.py` 不相依 whisperx/torch——它們是測試覆蓋的主力。

## 主要目錄

| 目錄 | 內容 |
|---|---|
| `src/transcribe/` | 套件本體 |
| `tests/` | pytest；`test_cli.py` 契約、`test_media.py` 含真 ffmpeg 整合、`test_skills.py` SKILL 稽核 |
| `.claude/skills/` | 6 個專案 SKILL（agent 操作手冊，指令示範受測試保護） |
| `.claude/hooks/` | docs-sync Stop hook |
| `outputs/<stem>/` | 每場會議一個資料夾：逐字稿、抽出音軌、片段、`<stem>_summary.md`；不進版控 |
| `samples/` | 原始錄音／影片樣本；不進版控 |

## 逐字稿 JSON（schema_version 1）

- `segments[]`：`speaker`（**永遠是原始標籤**，如 `SPEAKER_00`）、`start` / `end`（秒，float）、`text`（已淨化）。
- `speaker_names`：原始標籤 → 顯示名稱。改名只動這裡，所以可逆；渲染時才套用。
- `text_conversion`：實際套用的簡轉繁（`s2tw` 或 `null`＝沒轉）。
- `source`：`kind`（video/audio）、`duration`（秒或 null）、`audio_track`、`audio_track_count`。
- 無 `schema_version` 的舊檔視為 v0，`transcript.load_transcript` 讀入時補齊。版本號大於工具支援時拒絕。

## 模組

| 模組 | 職責 | 最該記住的一件事 |
|---|---|---|
| `cli.py` | 指令、envelope、schema 內省 | `--json` 時 sys.stdout 被暫時指向 stderr；envelope 只經 `_write_json` |
| `errors.py` | 例外與 code/exit_code/action | 新失敗情境＝新類別；`schema` 自動列出 |
| `pipeline.py` | 單檔流程、批次、輸入展開 | 缺 HF token 在轉錄**前**就失敗 |
| `media.py` | ffprobe/ffmpeg | `track` ≠ `stream_index`；封面圖不算影像軌 |
| `formats.py` | 渲染、`clean_text`、`RENDERERS` | 未知格式報錯，不略過 |
| `transcript.py` | 讀回 JSON、改名、搜尋、統計 | `talk_time` 不扣重疊說話；`duration_source` 說明長度來源 |
| `transcribe.py` | WhisperX 轉錄＋對齊 | 抗幻覺參數預設開啟（`build_asr_options`） |
| `diarize.py` | pyannote 分辨 | 依建構子簽名相容不同 whisperx 版本 |

## 重要技術決策

| 決策 | 選擇 | 理由（被否決的方案錯在哪） |
|---|---|---|
| Agent 介面 | `--json` 單一 envelope + `schema` 內省 | 純文字輸出要 agent 自己猜格式；手寫 schema 文件會與程式漂移 |
| 錯誤分類軸 | `action`（fix_input / fix_environment / retry_with / none） | 依內部原因分類時，agent 仍不知道該重試、改參數還是停下來問人 |
| 批次 | `run` 接受多檔與資料夾，不另開 `batch` 指令 | 另開指令要重複宣告 15 個轉錄旗標，必然漂移 |
| 改名 | 寫 `speaker_names` 對照表 | 直接改 segments 標籤不可逆，且再次改名時會把錯名字當原始標籤 |
| 媒體工具 | subprocess 呼叫 ffmpeg | Python 綁定（如 PyAV）多一個依賴且錯誤訊息被包掉；ffmpeg stderr 原文直接放進 error.message |
| 簡轉繁 | OpenCC `s2tw`，保留原文的「台」 | 以 15 支實際逐字稿量測：`s2t` 把正確繁體改成異體字（吃→喫、才→纔），`s2twp` 改寫用詞（設備→裝置、數據→資料）；不轉則同一支影片繁簡混雜 |
| SKILL 正確性 | 測試解析 SKILL 指令並對 CLI 樹驗證 | 只靠文件約定，改旗標時一定會漏改 SKILL |

## 貫穿全系統的原則

**查不到 ≠ 0、不默默降級。** 媒體長度取不到回 `null`；未知輸出格式報錯而不是略過（舊版曾靜默略過）；
搜尋被 `--limit` 截斷時回 `truncated: true` 與 `total`；批次失敗逐檔列出。違反的代價：agent 會把「沒做到」當成「做完了」回報給使用者。
