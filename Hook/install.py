#!/usr/bin/env python3
"""将仓库中的项目记忆 Hook 合并到 Codex hooks.json。"""

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
    "SessionStart": "project_memory_session_start.py",
    "SessionEnd": "project_memory_session_end.py",
}


def command_for(script: Path) -> tuple[str, str]:
    unix = f"{shlex.quote(sys.executable)} {shlex.quote(str(script))}"
    windows = subprocess.list2cmdline([sys.executable, str(script)])
    return unix, windows


def group(event: str, script: Path) -> dict:
    command, command_windows = command_for(script)
    handler = {
        "type": "command",
        "command": command,
        "commandWindows": command_windows,
        "timeout": 3,
        "statusMessage": "检查项目记忆摘要" if event == "SessionStart" else "登记待审核项目记忆",
    }
    if event == "SessionStart":
        handler["additionalContextLimit"] = 1200
        matcher = "startup|resume|clear|compact"
    else:
        matcher = "other"
    return {"matcher": matcher, "hooks": [handler]}


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
    for event, filename in HANDLERS.items():
        groups = hooks.setdefault(event, [])
        groups[:] = [
            item
            for item in groups
            if filename not in json.dumps(item, ensure_ascii=False)
        ]
        groups.append(group(event, hook_dir / filename))

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
