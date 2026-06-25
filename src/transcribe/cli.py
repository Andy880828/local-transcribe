"""CLI 進入點 (Typer)。

提供單一 ``run`` 指令：輸入音檔 → 輸出已標註講者的逐字稿 (txt/srt/json)。
摘要不在本工具範圍內——產出的逐字稿可自行貼到 Claude Code 或網站彙整。
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer
from rich.console import Console

from .config import load_settings
from .errors import TranscribeError
from .pipeline import PipelineOptions, run_pipeline

app = typer.Typer(
    add_completion=False,
    help="本地語音轉錄 + 講者分辨，輸出已標註講者的逐字稿。",
)
console = Console()
err_console = Console(stderr=True)


@app.callback()
def main() -> None:
    """本地語音轉錄 + 講者分辨，輸出已標註講者的逐字稿。

    （此 callback 的存在會讓 Typer 維持「子指令」模式，
    因此呼叫方式為 ``transcribe run <音檔>``。）
    """


@app.command()
def run(
    audio: Path = typer.Argument(..., help="輸入音檔 (mp3/m4a/wav/視訊等)"),
    language: Optional[str] = typer.Option(None, "--language", "-l", help="語言代碼，如 zh；留空自動偵測"),
    model: Optional[str] = typer.Option(None, "--model", "-m", help="Whisper 模型，如 large-v3"),
    speakers: Optional[int] = typer.Option(None, "--speakers", help="已知確切講者人數"),
    min_speakers: Optional[int] = typer.Option(None, "--min-speakers", help="講者人數下限"),
    max_speakers: Optional[int] = typer.Option(None, "--max-speakers", help="講者人數上限"),
    align: bool = typer.Option(True, "--align/--no-align", help="是否做詞級對齊 (中文品質普通，可關)"),
    diarize: bool = typer.Option(True, "--diarize/--no-diarize", help="是否做講者分辨"),
    diarize_model: Optional[str] = typer.Option(None, "--diarize-model", help="pyannote 分辨模型，預設 speaker-diarization-3.1"),
    condition_on_previous_text: Optional[bool] = typer.Option(
        None,
        "--condition-on-previous-text/--no-condition-on-previous-text",
        help="以前文為解碼條件。預設關閉（抗重複幻覺）；連貫性需求高時可開",
    ),
    repetition_penalty: Optional[float] = typer.Option(None, "--repetition-penalty", help="重複懲罰，預設 1.1（越大越抗重複）"),
    no_repeat_ngram_size: Optional[int] = typer.Option(None, "--no-repeat-ngram-size", help="禁止重複的 n-gram 大小，預設 3（0=停用）"),
    compute_type: Optional[str] = typer.Option(None, "--compute-type", help="float16 / int8 / float32"),
    batch_size: Optional[int] = typer.Option(None, "--batch-size", help="批次大小，VRAM 不足時調小"),
    device: Optional[str] = typer.Option(None, "--device", help="cuda / cpu"),
    output_dir: Optional[Path] = typer.Option(None, "--output-dir", "-o", help="輸出資料夾"),
    formats: str = typer.Option("txt,srt,json", "--format", "-f", help="輸出格式，逗號分隔"),
) -> None:
    """轉錄並標註講者，輸出逐字稿。"""
    try:
        settings = load_settings(
            language=language,
            whisper_model=model,
            compute_type=compute_type,
            batch_size=batch_size,
            device=device,
            output_dir=output_dir,
            diarize_model=diarize_model,
            condition_on_previous_text=condition_on_previous_text,
            repetition_penalty=repetition_penalty,
            no_repeat_ngram_size=no_repeat_ngram_size,
        )
        options = PipelineOptions(
            align=align,
            diarize=diarize,
            num_speakers=speakers,
            min_speakers=min_speakers,
            max_speakers=max_speakers,
            formats=[f.strip() for f in formats.split(",") if f.strip()],
        )

        result = run_pipeline(
            audio,
            settings,
            options,
            progress=lambda msg: console.print(f"[cyan]›[/cyan] {msg}"),
        )

        console.print("[green]✓ 完成。[/green]")
        if result.language:
            console.print(f"  偵測語言：{result.language}")
        for path in result.outputs:
            console.print(f"  輸出：{path}")
    except TranscribeError as exc:
        err_console.print(f"[red]✗ {exc}[/red]")
        if exc.hint:
            err_console.print(f"[yellow]→ {exc.hint}[/yellow]")
        raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
