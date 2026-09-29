#!/usr/bin/env python3
"""将项目记忆 Hook 安装为 pi 扩展（$PI_CODING_AGENT_DIR/extensions）。"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path


TEMPLATE = Path(__file__).resolve().parent / "pi" / "project_memory_hook.ts"
EXTENSION_NAME = "project-memory-hook.ts"
PLACEHOLDERS = {
    '"__PYTHON__"': "PYTHON",
    '"__SESSION_START__"': "SESSION_START",
    '"__SESSION_END__"': "SESSION_END",
}


def render(hook_dir: Path) -> str:
    """把模板中的占位符替换为本机绝对路径（正斜杠，兼容 Windows）。"""
    template = TEMPLATE.read_text(encoding="utf-8")
    values = {
        "PYTHON": Path(sys.executable).resolve().as_posix(),
        "SESSION_START": (hook_dir / "project_memory_session_start.py").as_posix(),
        "SESSION_END": (hook_dir / "project_memory_session_end.py").as_posix(),
    }
    for placeholder, key in PLACEHOLDERS.items():
        template = template.replace(
            placeholder, json.dumps(values[key], ensure_ascii=False)
        )
    return template


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
    pi_dir = Path(os.environ.get("PI_CODING_AGENT_DIR", "~/.pi/agent")).expanduser()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--target",
        default=str(pi_dir / "extensions" / EXTENSION_NAME),
        help="目标扩展文件；默认使用 PI_CODING_AGENT_DIR/extensions/project-memory-hook.ts",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    target = Path(args.target).expanduser().resolve()
    rendered = render(Path(__file__).resolve().parent)
    if args.dry_run:
        print(rendered, end="")
        return

    write_atomic(target, rendered)
    print(f"已安装到 {target}")
    print("请重启 pi，或在会话中运行 /reload 加载扩展。")


if __name__ == "__main__":
    main()
