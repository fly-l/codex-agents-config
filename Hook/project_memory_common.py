#!/usr/bin/env python3
"""项目记忆 Hook 的共享配置解析。"""

from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any


SECTION = re.compile(r"(?ms)^##\s+知识体系\s*$\n(.*?)(?=^##\s+|\Z)")
FIELD = re.compile(r"^\s*-?\s*([^：:\n]+?)\s*[：:]\s*(.*?)\s*$")


def read_event() -> dict[str, Any]:
    try:
        return json.load(__import__("sys").stdin)
    except (json.JSONDecodeError, OSError):
        return {}


def find_git_root(cwd: Path) -> Path:
    current = cwd.resolve()
    for candidate in [current, *current.parents]:
        if (candidate / ".git").exists():
            return candidate
    return current


def instruction_files(root: Path, cwd: Path, host: str = "codex") -> list[Path]:
    try:
        relative = cwd.resolve().relative_to(root.resolve())
    except ValueError:
        relative = Path()
    directories = [root]
    cursor = root
    for part in relative.parts:
        cursor = cursor / part
        directories.append(cursor)
    result: list[Path] = []
    names = ("CLAUDE.md",) if host == "claude" else ("AGENTS.override.md", "AGENTS.md")
    for directory in directories:
        for name in names:
            path = directory / name
            if path.is_file():
                result.append(path)
                break
    return result


def parse_config(root: Path, cwd: Path, host: str = "codex") -> dict[str, str]:
    config: dict[str, str] = {}
    for path in instruction_files(root, cwd, host):
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            continue
        match = SECTION.search(text)
        if not match:
            continue
        for line in match.group(1).splitlines():
            field = FIELD.match(line)
            if field:
                config[field.group(1).strip()] = field.group(2).strip().strip("`")
    return config


def resolve(event: dict[str, Any], host: str = "codex") -> dict[str, Any] | None:
    if host not in {"codex", "claude"}:
        return None
    cwd = Path(str(event.get("cwd") or os.getcwd()))
    root = find_git_root(cwd)
    config = parse_config(root, cwd, host)
    if config.get("启用") != "是" or not config.get("项目名称"):
        return None
    vault = (
        os.environ.get("CLAUDE_MEMORY_VAULT")
        if host == "claude"
        else os.environ.get("CODEX_MEMORY_VAULT")
    ) or config.get("Vault根目录")
    if not vault:
        return None
    project = config["项目名称"]
    if project in {".", ".."} or any(char in project for char in "/\\\0"):
        return None
    vault_path = Path(os.path.expandvars(vault)).expanduser()
    return {
        "cwd": cwd,
        "root": root,
        "config": config,
        "project": project,
        "knowledge_root": vault_path / project / "知识库",
    }


def atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", newline="\n", dir=path.parent, delete=False
    ) as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
        temporary = Path(handle.name)
    os.replace(temporary, path)
