"""SKILL 防漂移稽核：.claude/skills/*/SKILL.md 裡寫到的每一條 `uv run transcribe ...`
都必須對得上真正的 CLI 指令樹（子指令存在、旗標存在、帶 --json），而且每個 CLI 指令
至少被一份 SKILL 覆蓋。改了 CLI 卻忘了改 SKILL（或反過來）時這裡會紅。

只檢查「子指令與旗標是否存在」，不檢查參數值型別（SKILL 內常用 <檔案> 這類佔位字）。
"""

from __future__ import annotations

import re
import shlex
from pathlib import Path
from typing import Any

import pytest
import typer

from transcribe.cli import app

SKILLS_DIR = Path(__file__).resolve().parents[1] / ".claude" / "skills"
EXPECTED_MIN_SKILLS = 6
COMMAND_RE = re.compile(r"uv run transcribe[^`\n]*")


def _skill_files() -> list[Path]:
    return sorted(SKILLS_DIR.glob("*/SKILL.md"))


def _frontmatter(text: str) -> dict[str, str]:
    match = re.match(r"---\n(.*?)\n---\n", text, re.S)
    assert match, "缺少 YAML frontmatter"
    fields = {}
    for line in match.group(1).splitlines():
        key, _, value = line.partition(":")
        fields[key.strip()] = value.strip()
    return fields


def _leaf_commands(cmd: Any, path: tuple[str, ...] = ()) -> dict[tuple[str, ...], Any]:
    if hasattr(cmd, "commands"):
        out: dict[tuple[str, ...], Any] = {}
        for name, sub in cmd.commands.items():
            out.update(_leaf_commands(sub, (*path, name)))
        return out
    return {path: cmd}


ROOT = typer.main.get_command(app)
LEAVES = _leaf_commands(ROOT)


def check_command(line: str) -> tuple[tuple[str, ...], list[str]]:
    """回傳 (解析出的子指令路徑, 問題清單)。"""
    tokens = shlex.split(line)[3:]  # 去掉 uv run transcribe
    problems: list[str] = []
    if not tokens or tokens[0] != "--json":
        problems.append("缺少全域 --json（agent 必須拿 JSON envelope）")
    else:
        tokens = tokens[1:]

    if tokens == ["..."]:  # 契約段落的泛稱寫法「uv run transcribe --json ...」
        return (), problems

    cmd, path = ROOT, []
    while hasattr(cmd, "commands") and tokens and tokens[0] in cmd.commands:
        path.append(tokens[0])
        cmd = cmd.commands[tokens.pop(0)]
    if hasattr(cmd, "commands"):
        return tuple(path), [*problems, f"不是完整指令，可用子指令：{sorted(cmd.commands)}"]

    flags = {
        f for p in cmd.params for f in (*getattr(p, "opts", []), *getattr(p, "secondary_opts", [])) if f.startswith("-")
    }
    flags.add("--help")
    for tok in tokens:
        if tok.startswith("-") and not re.fullmatch(r"-\d+(\.\d+)?", tok):
            flag = tok.split("=", 1)[0]
            if flag not in flags:
                problems.append(f"`{' '.join(path)}` 沒有旗標 {flag}")
    return tuple(path), problems


def test_audit_scans_something():
    """空跑防護：路徑錯了或 glob 失效時不能「沒掃到東西＝通過」。"""
    files = _skill_files()
    assert len(files) >= EXPECTED_MIN_SKILLS, f"只找到 {len(files)} 份 SKILL：{files}"
    assert len(LEAVES) >= 9


@pytest.mark.parametrize("skill", _skill_files(), ids=lambda p: p.parent.name)
def test_skill_frontmatter(skill: Path):
    fields = _frontmatter(skill.read_text(encoding="utf-8"))
    assert fields.get("name") == skill.parent.name, "frontmatter name 必須與資料夾同名"
    assert len(fields.get("description", "")) >= 40, "description 太短，agent 無法判斷何時觸發"


@pytest.mark.parametrize("skill", _skill_files(), ids=lambda p: p.parent.name)
def test_skill_commands_match_cli(skill: Path):
    lines = COMMAND_RE.findall(skill.read_text(encoding="utf-8"))
    assert lines, "SKILL 至少要示範一條指令"
    problems = [f"{line!r}: {p}" for line in lines for p in check_command(line)[1]]
    assert not problems, "\n".join(problems)


def test_every_cli_command_covered_by_a_skill():
    covered = {
        check_command(line)[0]
        for skill in _skill_files()
        for line in COMMAND_RE.findall(skill.read_text(encoding="utf-8"))
    }
    missing = sorted(" ".join(p) for p in LEAVES if p not in covered)
    assert not missing, f"這些 CLI 指令沒有任何 SKILL 示範：{missing}"


# ---- 偵測規則自身的正反例 ----


def test_checker_accepts_valid_and_rejects_invalid():
    assert check_command("uv run transcribe --json run a.mp4 --speakers 3 -f txt,md") == (("run",), [])
    assert check_command("uv run transcribe --json transcript rename x.json --map A=B")[1] == []
    assert check_command("uv run transcribe --json ...") == ((), [])
    assert check_command("uv run transcribe ...")[1]  # 泛稱也必須帶 --json
    assert check_command("uv run transcribe run a.mp4")[1]  # 缺 --json
    assert check_command("uv run transcribe --json run a.mp4 --speaker 3")[1]  # 旗標拼錯
    assert check_command("uv run transcribe --json media")[1]  # 不完整
    assert check_command("uv run transcribe --json media probe x --track 1")[1]  # 旗標屬於別的子指令
