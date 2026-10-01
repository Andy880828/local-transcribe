# 產品需求

> **要做什麼、什麼算完成。** 怎麼做在 ARCHITECTURE.md，做到哪在 PROGRESS.md。

## 定位

本地執行的影音轉錄 CLI：影片或錄音 → 有時間序、標註講者的逐字稿。
**第一使用者是 AI agent**（Claude Code 等），其次才是在終端機手動操作的人。不是雲端服務，也不是 GUI。

要能回答現況答不了的問題：

- 這支會議影片裡，誰在幾點說了什麼？（多講者 + 時間戳，可回聽原音片段）
- agent 不讀原始碼、不看 API 文件，能不能只靠 `schema` 與 SKILL 就正確下指令，並從錯誤中知道下一步？
- 一整個資料夾的錄音，哪些轉好了、哪些失敗、為什麼失敗？

## 使用者與規模

| 項目 | 定義 |
|---|---|
| 使用者 | 單人本機使用；由使用者本人或其 AI agent 操作 |
| 部署 | 本機（Windows 為主），NVIDIA GPU（開發機 RTX 4060 / 8GB） |
| 隱私 | 音訊不得上傳；轉錄與講者分辨 100% 本地。唯一對外連線是首次下載模型（Hugging Face） |
| 安全 | 逐字稿視為不受信任內容（防 prompt injection、終端機控制字元）。**不需要**帳號系統、多使用者權限、OS 鑰匙圈（`.env` 已足夠，使用者已決定不做） |

## 核心功能

- **轉錄**：影片／音檔 → txt / srt / vtt / md / json；支援多音軌選軌、多檔與資料夾批次、續跑。
- **中文輸出一律台灣繁體**：Whisper 會混出簡體段落，輸出前自動轉換（不改用詞），JSON 記錄實際套用的轉換。
- **多人聲辨識**：pyannote 講者分辨，可給確切人數或範圍；講者可改名（可逆）。
- **媒體工具**：看音軌（probe）、從影片抽音軌（extract）、依時間切片段（clip）。
- **逐字稿查詢**：關鍵字／正規表示式搜尋（附時間戳與前後文）、各講者發言統計。
- **Agent 介面**：`--json` 單一 envelope、穩定錯誤碼與 exit code、`schema` 自我描述、`--dry-run` 預檢、6 個專案 SKILL。
- **會議摘要**：由 agent 依 `meeting-summary` SKILL 讀稿撰寫；CLI 本身不呼叫任何 LLM。

## 非目標

| 不做 | 理由 |
|---|---|
| CLI 內建 LLM 摘要 | 多一把 API 金鑰與網路依賴；agent 本身就能讀稿寫摘要（使用者決定） |
| 人聲分離（demucs） | 依賴重、吃 VRAM；吵雜錄音建議外部用 UVR 前處理（使用者決定） |
| OS 鑰匙圈存憑證 / auth 指令 | 單人本機，`.env` + gitignore 足夠（使用者決定） |
| GUI / Web 服務 | 使用情境是終端機與 agent |
| 即時（串流）轉錄 | 目標是事後整理會議紀錄 |

## 成功標準

| 面向 | 可驗證的標準 |
|---|---|
| 影片轉逐字稿 | `uv run transcribe --json run <影片> --speakers N` 成功，JSON `source.kind == "video"`，segments 依時間排序且有多個講者標籤 |
| 輸出契約 | 任何指令加 `--json` 時 stdout 可被 `json.loads` 一次解析（含第三方套件輸出 log 時） |
| 錯誤可行動 | 每個失敗都有 `error.code`、`action`、中文 `hint`；exit code 與 `errors.py` 一致 |
| 繁體輸出 | 中文逐字稿不含簡體段落；JSON `text_conversion == "s2tw"`；原本就是繁體的字詞（吃、才、設備、數據、台郡）不被改動 |
| 批次 | 單檔失敗不中斷，exit 10，逐檔列狀態；`--skip-existing` 只重跑缺的 |
| SKILL 不漂移 | `tests/test_skills.py` 全綠：SKILL 中每條指令與旗標都存在、每個指令都有 SKILL 示範 |
