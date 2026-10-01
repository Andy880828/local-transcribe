"""串接完整流程：媒體檔（影片／音檔）→ 抽音軌 → 轉錄 → (對齊) → 講者分辨 → 輸出逐字稿。

各重量級階段間靠 gpu.free_gpu 釋放 VRAM，確保 8GB 卡也能依序跑完。
模組函式採延遲匯入，CLI 與測試可在不載入 GPU 套件時匯入本模組。

批次（多檔／資料夾）：``run_batch`` 逐檔呼叫 ``run_pipeline``，單檔失敗不中斷，
每檔的結果（ok / skipped / error）都會列出，不默默吞掉。
已知限制：模型每個檔案都重新載入一次（換取 VRAM 釋放的單純性），大量短檔時較慢。
"""

from __future__ import annotations

import tempfile
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .config import Settings
from .errors import InputNotFoundError, InvalidArgumentError, TranscribeError
from .formats import DEFAULT_FORMATS

Progress = Callable[[str], None]


@dataclass
class PipelineOptions:
    """單次執行的選項（多由 CLI 旗標帶入）。"""

    align: bool = True
    diarize: bool = True
    num_speakers: int | None = None
    min_speakers: int | None = None
    max_speakers: int | None = None
    audio_track: int = 0
    formats: list[str] = field(default_factory=lambda: list(DEFAULT_FORMATS))


@dataclass
class PipelineResult:
    """單檔執行結果。"""

    result: dict[str, Any]
    outputs: list[Path]
    language: str | None
    source: dict[str, Any]
    speakers: list[str]


def expand_inputs(inputs: list[Path]) -> list[Path]:
    """把檔案與資料夾展開成待處理清單（資料夾只取第一層、依副檔名過濾、排序）。

    明確指定的檔案不檢查副檔名（交給 ffprobe 判斷）；不存在的路徑直接報錯。
    """
    from .media import MEDIA_EXTENSIONS

    files: list[Path] = []
    for path in inputs:
        if path.is_dir():
            found = sorted(p for p in path.iterdir() if p.is_file() and p.suffix.lower() in MEDIA_EXTENSIONS)
            if not found:
                raise InputNotFoundError(
                    f"no media files in directory: {path}",
                    hint=f"資料夾 {path} 內沒有可處理的影音檔（支援：{', '.join(sorted(MEDIA_EXTENSIONS))}）。",
                )
            files.extend(found)
        elif path.is_file():
            files.append(path)
        else:
            raise InputNotFoundError(f"input not found: {path}", hint=f"找不到輸入：{path}")
    return list(dict.fromkeys(files))


def meeting_dir(input_path: Path, settings: Settings) -> Path:
    """一個輸入檔（一場會議）的專屬輸出資料夾：``<output_dir>/<stem>/``。

    輸出位置的唯一決定點：逐字稿、抽出的音軌、切出的片段、agent 寫的摘要都放這裡，
    讓同一場會議的產物聚在一起。
    """
    return settings.output_dir / input_path.stem


def output_base(input_path: Path, settings: Settings) -> Path:
    """逐字稿檔的共同前綴：``<output_dir>/<stem>/<stem>``（後面接 ``.txt`` 等副檔名）。"""
    return meeting_dir(input_path, settings) / input_path.stem


def existing_transcript(input_path: Path, settings: Settings) -> Path | None:
    """``--skip-existing`` 的判斷依據（唯一決定點，正式執行與 dry-run 共用）：已有逐字稿 JSON 就回傳其路徑。"""
    path = output_base(input_path, settings).with_name(f"{input_path.stem}.json")
    return path if path.exists() else None


def run_pipeline(
    input_path: Path,
    settings: Settings,
    options: PipelineOptions,
    progress: Progress | None = None,
) -> PipelineResult:
    """執行單檔完整轉錄流程並寫出檔案。"""
    # 延遲匯入：讓不需要 GPU 的測試能 import 本模組
    from . import diarize, media, transcribe
    from .formats import write_outputs

    def report(msg: str) -> None:
        if progress:
            progress(f"[{input_path.name}] {msg}")

    # 先擋掉一定會失敗的情況，避免跑完十分鐘轉錄才發現缺金鑰
    if options.diarize:
        settings.require_hf_token()

    info = media.probe(input_path)
    track = media.require_audio_track(info, options.audio_track)
    source = {
        "path": str(input_path),
        "kind": info["kind"],
        "duration": info["duration"],
        "audio_track": options.audio_track,
        "audio_track_count": len(info["audio_tracks"]),
        "audio_language_tag": track.get("language"),
    }

    with tempfile.TemporaryDirectory(prefix="transcribe_") as tmp:
        report(f"正在抽取音軌 #{options.audio_track} 並轉 16k 單聲道 ({info['kind']})…")
        wav_path = media.prepare_audio(input_path, Path(tmp), track=options.audio_track)

        report(f"正在轉錄 (模型 {settings.whisper_model}, 對齊={'開' if options.align else '關'})…")
        result = transcribe.transcribe_audio(wav_path, settings, align=options.align)

        if options.diarize:
            report("正在進行講者分辨 (pyannote)…")
            result = diarize.diarize_transcript(
                wav_path,
                result,
                settings,
                num_speakers=options.num_speakers,
                min_speakers=options.min_speakers,
                max_speakers=options.max_speakers,
            )

    result["source"] = source
    report("正在寫出逐字稿…")
    outputs = write_outputs(result, output_base(input_path, settings), options.formats)
    speakers = list(dict.fromkeys(seg.get("speaker") or "UNKNOWN" for seg in result.get("segments", [])))
    return PipelineResult(
        result=result,
        outputs=outputs,
        language=result.get("language"),
        source=source,
        speakers=speakers,
    )


def ok_record(input_path: Path, res: PipelineResult) -> dict[str, Any]:
    """單檔成功的狀態紀錄（CLI 單檔與批次共用同一形狀）。"""
    return {
        "input": str(input_path),
        "status": "ok",
        "language": res.language,
        "source": res.source,
        "speakers": res.speakers,
        "segment_count": len(res.result.get("segments", [])),
        "outputs": [str(p) for p in res.outputs],
    }


def run_batch(
    files: list[Path],
    settings: Settings,
    options: PipelineOptions,
    *,
    skip_existing: bool = False,
    progress: Progress | None = None,
) -> list[dict[str, Any]]:
    """逐檔執行，回傳每檔的狀態紀錄（ok / skipped / error），不因單檔失敗中斷。

    ``skip_existing``：``<output_dir>/<stem>/<stem>.json`` 已存在就跳過。
    同名（stem 相同）的不同檔案會互相覆蓋輸出，因此直接報錯而非默默覆蓋。
    """
    if options.diarize:
        settings.require_hf_token()  # 全批共用的前置條件，缺了就整批不跑

    stems: dict[str, Path] = {}
    for f in files:
        if f.stem in stems:
            raise InvalidArgumentError(
                f"output name collision: {stems[f.stem]} and {f} both map to '{f.stem}'",
                hint="兩個輸入檔去掉副檔名後同名，輸出會互相覆蓋；請分開執行並指定不同 --output-dir。",
            )
        stems[f.stem] = f

    records: list[dict[str, Any]] = []
    for i, f in enumerate(files, start=1):
        if progress and len(files) > 1:
            progress(f"({i}/{len(files)}) {f.name}")
        existing = existing_transcript(f, settings) if skip_existing else None
        if existing:
            records.append({"input": str(f), "status": "skipped", "reason": "output_exists", "json": str(existing)})
            continue
        try:
            res = run_pipeline(f, settings, options, progress)
        except TranscribeError as exc:
            records.append({"input": str(f), "status": "error", "error": exc.to_dict()})
            continue
        except Exception as exc:  # 非預期錯誤：完整 stack 寫到 stderr，批次繼續
            traceback.print_exc()
            wrapped = TranscribeError(
                f"{type(exc).__name__}: {exc}",
                hint="非預期錯誤，完整 traceback 已輸出到 stderr。",
            )
            records.append({"input": str(f), "status": "error", "error": wrapped.to_dict()})
            continue
        records.append(ok_record(f, res))
    return records
