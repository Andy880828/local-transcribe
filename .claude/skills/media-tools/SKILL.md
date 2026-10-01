---
name: media-tools
description: 影音檔工具：查看容器／長度／音軌（probe）、從影片抽出指定音軌成 wav/mp3/m4a/flac（extract）、依時間切出片段（clip）。Use when the user wants to 從影片分離音軌、抽音訊、看影片有幾條音軌、剪出某段對話回聽、extract audio from video, cut a clip by timestamp.
---

# 媒體工具（ffmpeg）

## 契約

- 一律 `uv run transcribe --json ...`；先看 `ok`，失敗依 `error.action`（`fix_input` 修參數、`fix_environment` 告訴使用者 hint）。
- 音軌編號 `track` 是「第幾條音軌」（0 起算），**不是** `stream_index`。probe 結果兩者都有，下指令用 `track`。
- 時間格式：秒數（`90`、`90.5`）或 `MM:SS`、`HH:MM:SS(.mmm)`。

## 查看媒體資訊

```bash
uv run transcribe --json media probe <檔案>
```

重點欄位：`kind`（video / audio）、`duration`（秒；取不到時是 `null`，不是 0）、`audio_tracks[].track / language / title / channels`。

## 從影片抽出音軌

```bash
uv run transcribe --json media extract <影片> --track 0 --format wav
uv run transcribe --json media extract <影片> --track 1 -o outputs/commentary.m4a
```

- 可用格式：`wav`、`flac`、`mp3`、`m4a`；給了 `-o` 就以其副檔名決定格式。
- 預設輸出到 `outputs/<檔名>.track<N>.<格式>`。
- 只是要轉逐字稿的話**不必先 extract**，`transcribe run` 會自己抽音軌（用 `--audio-track` 選軌）。

## 切出片段

```bash
uv run transcribe --json media clip <檔案> --start 00:12:30 --end 00:13:10
uv run transcribe --json media clip <檔案> -s 750 -e 790 -o outputs/clip.mp4 --dry-run
```

- 典型用途：使用者對逐字稿某句有疑問 → 用 transcript-query skill 找到時間戳 → 前後各留幾秒切出來給使用者回聽。
- 預設輸出 `outputs/<檔名>_<起>-<迄><原副檔名>`；起點超過媒體長度會回 `INVALID_ARGUMENT`。
