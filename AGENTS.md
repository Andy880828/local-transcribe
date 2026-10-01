# AGENTS.md — local-transcribe

> 跨專案的工程習慣與 AI 協作硬規則在 `~/.claude/AGENTS.md`
> （由 `~/.claude/CLAUDE.md` import，每個 session 自動載入）。
> **本檔只寫這個專案特有的約束**——CLI 契約、目錄、環境陷阱。

## ⚠️ 開始工作前必讀

文件只有 4 份，各自回答一個問題。**新 session 從 `docs/PROGRESS.md` 開始。**

| 文件 | 回答什麼 | 什麼時候讀 |
|---|---|---|
| **`docs/PROGRESS.md`** | **現在做到哪、下一步、卡在哪** | **每次開工** |
| `docs/PRD.md` | 要做什麼、什麼算完成 | 需求有疑問時 |
| `docs/ARCHITECTURE.md` | 系統怎麼實作、為什麼這樣選 | 動到結構時 |
| `docs/ROADMAP.md` | 接下來往哪走 | 規劃新工作時 |

**不要新增其他專案管理文件。** 資訊若放得進上述任何一份，就不要開新檔。
使用者面向的用法在 `README.md`；給 agent 的操作手冊在 `.claude/skills/*/SKILL.md`。

## 常用指令

```bash
uv run pytest -q                       # 全部離線測試（GPU 階段皆 mock；有 ffmpeg 時會跑真 ffmpeg 整合測試）
uvx ruff check src tests               # lint
uvx ruff format --check src tests      # 格式
uv run transcribe --json schema        # 機器可讀的全部指令／旗標／錯誤碼
uv pip install -e .                    # 改了 pyproject 的 entry point 或依賴後重裝
```

## CLI 契約（改 cli.py 前必看）

- `--json` 模式下 **stdout 只能有一個 JSON envelope**。進度用 `cli.progress()`（stderr）；
  任何新的輸出都走 `emit()` / `fail()`，不要直接 `print` 或 `typer.echo` 到 stdout。
- 錯誤碼、exit code、`action` **只定義在 `errors.py` 的例外類別屬性**。新增失敗情境＝新增例外類別，
  不要在 CLI 手寫 code 字串或數字。`action` 依「使用者現在該做什麼」分類，不是依內部原因。
- 輸出位置只由 `pipeline.meeting_dir()`／`output_base()` 決定（一場會議一個資料夾 `outputs/<stem>/`）。
  新增會產生檔案的指令時，預設路徑也要經過 `meeting_dir()`，不要自己拼 `output_dir / ...`。
- 輸出格式的允許值只有 `formats.RENDERERS`；影音副檔名只有 `media.MEDIA_EXTENSIONS`；
  抽音軌格式只有 `media.AUDIO_EXPORT_CODECS`。不要在別處再列一份。
- 逐字稿文字一律經 `formats.clean_text()`；回傳逐字稿文字的結果要 `emit(..., untrusted=True)`。
  人類模式輸出逐字稿用純 `typer.echo`，**不要用 rich**（`[SPEAKER_00]`、`[red]` 會被當 markup 吃掉）。
- 改了指令或旗標 → 同步改 `.claude/skills/*/SKILL.md`。`tests/test_skills.py` 會檢查 SKILL 裡每條
  `uv run transcribe --json ...` 的子指令與旗標存在，且每個 CLI 指令至少被一份 SKILL 示範。
- 取不到的值回 `null`，不湊 `0`（例：`media probe` 的 `duration`、`transcript stats` 的 `duration_source`）。

## 踩過的坑

- **whisperx 在 import 時建立 `logging.StreamHandler(sys.stdout)`**，INFO log 曾混進 JSON stdout。
  現由 `cli.main()` 在 `--json` 模式把 `sys.stdout` 指向 stderr、`entry()` 結束還原；
  回歸測試 `test_third_party_stdout_noise_does_not_break_envelope`。不要拿掉這段。
- **typer 0.27 內建自己的 click 副本（`typer._click`）**，與另外安裝的 `click` 是不同類別；
  `except click.UsageError` 攔不到。`cli.py` 只能從 `typer._click.exceptions` 匯入，
  pyproject 因此鎖 `typer>=0.27,<0.28`，升版要重跑 `tests/test_cli.py`。
- **Windows 上 HF Hub 下載模型可能報 `WinError 1314`（無法建立 symlink）**：在受限沙箱或未開
  開發人員模式時發生，不是程式錯誤。在一般終端機執行，或開啟 Windows 開發人員模式。
- **在 Windows 用 Python 解析 `--json` 輸出時，管線預設以 cp950 解碼**，中文會被拆出假的 `\` 而報
  `Invalid \escape`（已踩過兩次，誤以為 CLI 輸出壞掉）。CLI 輸出本身是合法 UTF-8：先存檔再
  `open(..., encoding="utf-8")` 讀，或設 `PYTHONIOENCODING=utf-8`。
- **torch 必須裝 CUDA 版**，否則 `CUDA_UNAVAILABLE`。安裝順序見 README。
- 講者分辨需要 `.env` 的 `HF_TOKEN`，且同帳號要接受 `pyannote/speaker-diarization-3.1` 與
  `pyannote/segmentation-3.0` 授權。`run` 會在轉錄前先檢查 token，避免跑完才失敗。
- 音軌編號 `track` 是「第幾條音軌」（ffmpeg `0:a:N`），不是 `stream_index`；有影像軌時兩者不同。
- 批次輸出檔名是 `<輸入檔 stem>.<格式>`，同 stem 的輸入會互相覆蓋，`run_batch` 直接拒絕。

## 目錄與資料

- `outputs/`（預設輸出）與 `samples/`（會議錄音樣本，可能含敏感內容）都在 `.gitignore`，**不要加回版控**。
- `docs/` 只放文件，不放音檔。
