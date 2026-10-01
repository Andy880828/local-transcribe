# 現況

> **新 session 從這裡開始。**
> 要做什麼 → PRD.md｜怎麼做 → ARCHITECTURE.md｜接下來 → ROADMAP.md

**最後更新：2026-10-01**

## §0 接手速覽

- **交接狀態**：agent-native CLI 重構完成並已實測（影片 → 多講者逐字稿、媒體工具、逐字稿後處理、批次、6 個 SKILL）。沒有進行中的工作。
- **驗證基準**：`uv run pytest -q` → **86 passed**（重構前 18）；`uvx ruff check src tests` → **0**；`uvx ruff format --check` → 全部已格式化。
- **下一步**：
  1. 用真實會議影片跑一次 `meeting-summary` SKILL 全流程，確認 SKILL 指引足夠。
  2. 視需求從 ROADMAP「可能的方向」挑下一項。
- **動手前只要讀**：改 CLI → AGENTS.md「CLI 契約」與「踩過的坑」；改 SKILL → `tests/test_skills.py` 開頭說明。

## 進度

| 項目 | 狀態 | 備註 |
|---|---|---|
| agent-native CLI 重構 | ✅ 完成並驗證 | 見下方驗證紀錄 |
| 6 個專案 SKILL | ✅ 完成並驗證 | 稽核測試以探針確認會紅在正確位置 |

## 驗證紀錄（2026-10-01）

- 真 GPU：`samples/0727_IE.m4a` 前 3 分鐘合成帶影像軌的 mp4 → `run --speakers 3`：exit 0，stdout 單一 JSON，`source.kind=video`，3 位講者，segments 依時間排序。
- 真 GPU 批次：資料夾含正常影片、無音軌影片、壞檔、.txt → exit 10，1 ok / 2 error（`NO_AUDIO_STREAM`、`MEDIA_ERROR`），.txt 被略過；`--skip-existing` 重跑 → 1 skipped。
- 真實產物上跑 stats / search / rename / export vtt,md / media clip / media extract mp3：輸出內容逐一檢查。
- 錯誤路徑實測：無音軌（exit 3）、音軌超出範圍（exit 3）、`HF_TOKEN=` 空（exit 4，轉錄前即失敗）、未知格式（exit 2）、缺參數／未知旗標（exit 2，仍為 envelope）。
- 舊版逐字稿 `outputs/0727_IE.json`（v0）可直接 `transcript stats`。

## 已知未覆蓋

| 沒驗什麼 | 為什麼 | 替代覆蓋 | 不能證明什麼 |
|---|---|---|---|
| 講者分辨正確率 | 沒有標註真值 | 實測分出 3 位講者 | 不能證明「誰說的」標得對 |
| `--device cpu` 長檔 | 太慢，非主要情境 | `CUDA_UNAVAILABLE` 錯誤路徑有測 | 不能證明 CPU 模式效能可用 |
| `GPU_OOM` 真實觸發 | 8GB 卡跑 3 分鐘片段不會 OOM | mock 測 envelope 與 `retry_args` | 不能證明真 OOM 字串都被 `_is_oom` 辨識 |
| 多音軌真影片轉錄 | 無真實多音軌樣本 | ffmpeg 合成雙音軌影片測 probe/extract/prepare_audio | 不能證明真實多語影片的音軌語言標籤可靠 |

## 阻塞中

無。

## 接手前必知

- 在受限沙箱中執行真 GPU 轉錄會因 HF Hub 建 symlink 失敗（WinError 1314）；需在一般終端機執行。
- 使用者已決定不做：OS 鑰匙圈／auth、doctor、demucs、CLI 內建摘要。不要重新提案，除非 ROADMAP 的重評條件成立。
- IDE 的 Pyright 若顯示 `.media` / `.transcript` 無法匯入，是 IDE 沒用 `.venv` 直譯器，不是程式問題。

## 快速上手

```bash
uv run pytest -q
uv run transcribe --json schema
uv run transcribe --json media probe samples/0727_IE.m4a
uv run transcribe --json run <影片> --speakers 3 --dry-run
```

## 更新本檔的規則

完成一段有意義的工作後更新（docs-sync hook 會在每輪有程式變更時提醒）。
只記錄：做到哪、正在做什麼、卡在哪、下一步、下一個 session 必須知道的 context。
每次更新都要改「最後更新」日期與 §0。**不要寫成工作日誌。**
