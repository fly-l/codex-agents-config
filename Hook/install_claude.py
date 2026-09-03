#!/usr/bin/env python3
"""将项目记忆 Hook 安全合并到 Claude Code settings.json。"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path


HANDLERS = {
    "SessionStart": {
        "filename": "project_memory_session_start.py",
        "matcher": "startup|resume|clear|compact|fork",
        "status": "检查项目记忆摘要",
    },
    "SessionEnd": {
        "filename": "project_memory_session_end.py",
        "matcher": "clear|resume|logout|prompt_input_exit|other",
        "status": "登记待审核项目记忆",
    },
}


def handler(script: Path, status: str) -> dict:
    return {
        "type": "command",
        "command": sys.executable,
        "args": [str(script), "--host", "claude"],
        "timeout": 3,
        "statusMessage": status,
    }


def group(script: Path, matcher: str, status: str) -> dict:
    return {
        "matcher": matcher,
        "hooks": [handler(script, status)],
    }


def load_settings(target: Path) -> dict:
    if not target.exists():
        return {}
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SystemExit(f"无法读取现有 Claude Code 设置：{exc}") from exc
    if not isinstance(payload, dict):
        raise SystemExit("现有 Claude Code 设置的顶层必须是 JSON 对象。")
    return payload


def merge_hooks(payload: dict, hook_dir: Path) -> dict:
    hooks = payload.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        raise SystemExit("现有 Claude Code 设置中的 hooks 必须是 JSON 对象。")

    for event, spec in HANDLERS.items():
        groups = hooks.setdefault(event, [])
        if not isinstance(groups, list):
            raise SystemExit(f"现有 Claude Code 设置中的 hooks.{event} 必须是数组。")
        filename = spec["filename"]
        groups[:] = [
            item
            for item in groups
            if filename not in json.dumps(item, ensure_ascii=False)
        ]
        groups.append(
            group(
                hook_dir / filename,
                spec["matcher"],
                spec["status"],
            )
        )
    return payload


def write_atomic(target: Path, rendered: str) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        shutil.copy2(target, target.with_suffix(target.suffix + ".bak"))
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", newline="\n", dir=target.parent, delete=False
    ) as handle:
        handle.write(rendered)
        handle.flush()
        os.fsync(handle.fileno())
        temporary = Path(handle.name)
    os.replace(temporary, target)


def main() -> None:
    claude_dir = Path(os.environ.get("CLAUDE_CONFIG_DIR", "~/.claude")).expanduser()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--target",
        default=str(claude_dir / "settings.json"),
        help="目标 settings.json；默认使用 CLAUDE_CONFIG_DIR/settings.json 或 ~/.claude/settings.json",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    target = Path(args.target).expanduser().resolve()
    payload = merge_hooks(load_settings(target), Path(__file__).resolve().parent)
    rendered = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    if args.dry_run:
        print(rendered, end="")
        return

    write_atomic(target, rendered)
    print(f"已安装到 {target}")
    print("请重启 Claude Code，并运行 /hooks 审核 SessionStart 与 SessionEnd。")


if __name__ == "__main__":
    main()
