#!/usr/bin/env python3
"""将仓库中的项目记忆与对话标题 Hook 合并到 Codex hooks.json。"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


HANDLERS = {
    "SessionStart": (
        ("project_memory_session_start.py", "检查项目记忆摘要", "startup|resume|clear|compact"),
    ),
    "Stop": (
        ("conversation_title_session_end.py", "检查并整理当前对话标题", ".*"),
        ("project_memory_session_end.py", "登记待审核项目记忆", None),
    ),
}

LEGACY_EVENTS = ("SessionEnd",)
EXECUTION_FIELDS = frozenset({"command", "commandWindows", "args"})


def command_for(script: Path) -> tuple[str, str]:
    unix = f"{shlex.quote(sys.executable)} {shlex.quote(str(script))}"
    windows = subprocess.list2cmdline([sys.executable, str(script)])
    return unix, windows


def group(event: str, script: Path, status: str, matcher: str | None) -> dict:
    command, command_windows = command_for(script)
    handler = {
        "type": "command",
        "command": command,
        "commandWindows": command_windows,
        "timeout": 3,
        "statusMessage": status,
    }
    if event == "SessionStart":
        handler["additionalContextLimit"] = 1500
    result = {"hooks": [handler]}
    if matcher is not None:
        result["matcher"] = matcher
    return result


def _execution_values(value: object):
    if isinstance(value, (str, int, float)):
        yield str(value)
    elif isinstance(value, list):
        for item in value:
            yield from _execution_values(item)


def is_managed_handler(hook: object, managed_filenames: set[str]) -> bool:
    if not isinstance(hook, dict):
        return False
    for field in EXECUTION_FIELDS:
        for value in _execution_values(hook.get(field)):
            if any(filename in value for filename in managed_filenames):
                return True
    return False


def remove_managed_handlers(groups: list, managed_filenames: set[str]) -> list:
    result = []
    for item in groups:
        if not isinstance(item, dict) or not isinstance(item.get("hooks"), list):
            result.append(item)
            continue
        remaining = [
            hook
            for hook in item["hooks"]
            if not is_managed_handler(hook, managed_filenames)
        ]
        if remaining:
            if len(remaining) != len(item["hooks"]):
                item = {**item, "hooks": remaining}
            result.append(item)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--target",
        default=str(Path(os.environ.get("CODEX_HOME", "~/.codex")).expanduser() / "hooks.json"),
        help="目标 hooks.json；默认使用 CODEX_HOME/hooks.json",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    target = Path(args.target).expanduser().resolve()
    hook_dir = Path(__file__).resolve().parent
    if target.exists():
        try:
            payload = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise SystemExit(f"无法读取现有 Hook 配置：{exc}")
    else:
        payload = {"description": "Codex lifecycle hooks", "hooks": {}}

    hooks = payload.setdefault("hooks", {})
    managed_filenames = {
        spec[0] for specs in HANDLERS.values() for spec in specs
    }
    for event, specs in HANDLERS.items():
        groups = hooks.setdefault(event, [])
        groups[:] = remove_managed_handlers(groups, managed_filenames)
        for filename, status, matcher in specs:
            groups.append(group(event, hook_dir / filename, status, matcher))

    for event in LEGACY_EVENTS:
        if event in hooks and isinstance(hooks[event], list):
            hooks[event][:] = remove_managed_handlers(
                hooks[event], managed_filenames
            )

    rendered = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    if args.dry_run:
        print(rendered, end="")
        return

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
    print(f"已安装到 {target}")
    print("请在 Codex 中运行 /hooks，审核并信任新增 Hook。")


if __name__ == "__main__":
    main()
