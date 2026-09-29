#!/usr/bin/env python3
"""项目记忆 Hook 的共享配置解析。"""

from __future__ import annotations

import json
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Any


HOSTS = ("codex", "claude", "pi")

FIELD = re.compile(r"^\s*-?\s*([^：:\n]+?)\s*[：:]\s*(.*?)\s*$")
KNOWLEDGE_HEADING = re.compile(r"^ {0,3}##\s+知识体系\s*$")
LEVEL_TWO_HEADING = re.compile(r"^ {0,3}##\s+")
FENCE = re.compile(r"^ {0,3}(?P<marker>`{3,}|~{3,})(?P<tail>.*)$")


def read_stdin_utf8() -> str:
    """读取 Hook 的原始标准输入并按 UTF-8 解码，绕过 Windows 默认代码页。"""
    stream = sys.stdin
    buffer = getattr(stream, "buffer", None)
    value = buffer.read() if buffer is not None else stream.read()
    return value.decode("utf-8") if isinstance(value, bytes) else value


def write_stdout_utf8(value: str) -> None:
    """按 UTF-8 写出 Hook 响应，绕过 Windows 默认代码页。"""
    stream = sys.stdout
    buffer = getattr(stream, "buffer", None)
    if buffer is not None:
        buffer.write(value.encode("utf-8"))
        buffer.flush()
        return
    stream.write(value)
    stream.flush()


def write_stderr_utf8(value: str) -> None:
    """按 UTF-8 写出 Hook 错误响应，绕过 Windows 默认代码页。"""
    stream = sys.stderr
    buffer = getattr(stream, "buffer", None)
    if buffer is not None:
        buffer.write(value.encode("utf-8"))
        buffer.flush()
        return
    stream.write(value)
    stream.flush()


def read_event() -> dict[str, Any]:
    try:
        value = json.loads(read_stdin_utf8())
    except (json.JSONDecodeError, OSError, UnicodeError):
        return {}
    return value if isinstance(value, dict) else {}


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
    if host == "claude":
        names = ("CLAUDE.md",)
    elif host == "pi":
        names = ("AGENTS.override.md", "AGENTS.md", "CLAUDE.md")
    else:
        names = ("AGENTS.override.md", "AGENTS.md")
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
        section: list[str] | None = None
        active_fence: tuple[str, int] | None = None
        for line in text.splitlines():
            fence = FENCE.match(line)
            if active_fence is not None:
                if (
                    fence is not None
                    and fence.group("marker")[0] == active_fence[0]
                    and len(fence.group("marker")) >= active_fence[1]
                    and not fence.group("tail").strip()
                ):
                    active_fence = None
                continue
            if fence is not None:
                marker = fence.group("marker")
                active_fence = (marker[0], len(marker))
                continue
            if section is None:
                if KNOWLEDGE_HEADING.fullmatch(line):
                    section = []
                continue
            if LEVEL_TWO_HEADING.match(line):
                break
            section.append(line)
        if section is None:
            continue
        for line in section:
            field = FIELD.match(line)
            if field:
                config[field.group(1).strip()] = field.group(2).strip().strip("`")
    return config


def resolve(event: dict[str, Any], host: str = "codex") -> dict[str, Any] | None:
    if host not in HOSTS:
        return None
    cwd = Path(str(event.get("cwd") or os.getcwd()))
    root = find_git_root(cwd)
    config = parse_config(root, cwd, host)
    if config.get("启用") != "是" or not config.get("项目名称"):
        return None
    vault = os.environ.get("PROJECT_MEMORY_VAULT") or config.get("Vault根目录")
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
