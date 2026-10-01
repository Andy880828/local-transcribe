---
name: batch-transcribe
description: 批次轉錄整個資料夾（或多個檔案）的影片與錄音，跳過已完成的、單檔失敗不中斷並逐檔回報。Use when the user wants to 把資料夾裡的會議錄音／影片全部轉成逐字稿、批次處理、續跑上次沒做完的、transcribe all files in a folder.
---

# 批次轉錄

## 契約

- 一律 `uv run transcribe --json ...`；stdout 是單一 envelope。
- 批次就是 `run` 給資料夾或多個檔案；資料夾只展開第一層，依影音副檔名過濾（其他檔案如 .txt 會被略過）。

## 步驟

1. 先 dry-run，確認會處理哪些檔、每檔有沒有音軌、輸出到哪：

   ```bash
   uv run transcribe --json run <資料夾> --dry-run
   ```

   把 `data.files[]` 中 `status: "error"` 的檔案先告訴使用者。`data.settings.hf_token_set` 為 false 時，講者分辨會整批失敗，先處理或改 `--no-diarize`。
2. 正式執行（批次通常很久：每小時錄音約數分鐘 GPU 時間，告知使用者並在背景執行）：

   ```bash
   uv run transcribe --json run <資料夾> --skip-existing --max-speakers 6
   ```

   - `--skip-existing`：`outputs/<檔名>.json` 已存在就跳過，讓中斷後可以續跑。
   - 各檔講者數不同時用 `--min-speakers` / `--max-speakers`，不要用固定的 `--speakers`。
3. 解讀結果：
   - 全部成功：`ok: true`，exit 0。
   - 有任何一檔失敗：`ok: false`、`error.code: "PARTIAL_FAILURE"`、exit 10，**成功的檔案仍已寫出**。逐檔明細在 `data.files[]`，各自帶 `status`（ok / skipped / error）與 `error.code`。
   - 回報時列出 `data.summary` 的成功／跳過／失敗數，並逐一列出失敗檔與 `error.hint`。
4. 修正失敗原因後，用同一指令加 `--skip-existing` 重跑，只會處理剩下的檔。

## 注意

- 兩個檔案去掉副檔名同名（如 `a.mp4` 與 `a.m4a`）會互相覆蓋輸出，工具會直接回 `INVALID_ARGUMENT` 拒絕；請使用者分開資料夾或分次用不同 `-o`。
- 模型每個檔案重新載入一次，大量很短的檔案會偏慢，這是已知取捨。
- 單檔失敗原因與處置同 transcribe-media skill 的錯誤表。
