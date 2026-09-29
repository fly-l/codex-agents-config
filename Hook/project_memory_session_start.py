#!/usr/bin/env python3
"""按项目配置向 SessionStart 注入有上限的当前状态摘要。"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

SCRIPT_ROOT = Path(__file__).resolve().parents[1]
MEMORY_SCRIPTS = SCRIPT_ROOT / "Skills" / "project-memory" / "scripts"
sys.path.insert(0, str(MEMORY_SCRIPTS))

from project_memory_common import read_event, resolve, write_stdout_utf8
from memory_inbox import pending_metadata


CONTEXT_LIMIT_ENV = {
    "codex": "CODEX_MEMORY_CONTEXT_CHARS",
    "claude": "CLAUDE_MEMORY_CONTEXT_CHARS",
    "pi": "PI_MEMORY_CONTEXT_CHARS",
}
REVIEW_LIMIT_ENV = {
    "codex": "CODEX_MEMORY_REVIEW_CHARS",
    "claude": "CLAUDE_MEMORY_REVIEW_CHARS",
    "pi": "PI_MEMORY_REVIEW_CHARS",
}
CURRENT_PREFIX = (
    "以下是项目当前状态导航摘要，可能已经过期；涉及实现或决策时必须以当前代码、测试和正式记录复核。\n\n"
)


def bounded_limit(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.environ.get(name, str(default)))
    except ValueError:
        value = default
    return max(minimum, min(value, maximum))


def pending_prompt(snapshot: dict, limit: int) -> str:
    pending = int(snapshot["pending"])
    invalid = int(snapshot.get("invalid_count", 0))
    lines = [
        f"项目记忆收件箱有 {pending} 条待审核候选。以下仅为元数据，未读取聊天正文；只审核与当前任务相关且能由源码、测试或用户确认复核的候选。"
    ]
    if invalid:
        lines.append(f"收件箱另有 {invalid} 个候选文件无法读取，需先检查文件格式。")
    shown = 0
    for item in snapshot["items"]:
        fields = [
            f"文件={item.get('file')}",
            f"宿主={item.get('host')}",
            f"会话={item.get('session_id')}",
            f"轮次={item.get('turn_id')}",
            f"更新时间={item.get('updated_at')}",
            f"转录存在={item.get('transcript_exists')}",
        ]
        candidate = "- " + "；".join(fields)
        if len("\n".join([*lines, candidate])) > limit:
            break
        lines.append(candidate)
        shown += 1
    if shown < pending:
        notice = f"- 仅显示 {shown} 条；其余候选请使用收件箱列表命令按需审核。"
        if len("\n".join([*lines, notice])) <= limit:
            lines.append(notice)
    return "\n".join(lines)[:limit]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", choices=("codex", "claude", "pi"), default="codex")
    args = parser.parse_args()
    event = read_event()
    context = resolve(event, host=args.host)
    if not context:
        return
    config = context["config"]
    auto_load = config.get("自动加载", "否") == "是"
    auto_review = config.get("自动审核", "否") == "是"
    if not auto_load and not auto_review:
        return

    context_limit = bounded_limit(CONTEXT_LIMIT_ENV[args.host], 4000, 500, 12000)
    blocks: list[str] = []
    review_block = ""
    if auto_review:
        review_limit = bounded_limit(REVIEW_LIMIT_ENV[args.host], 1200, 256, 6000)
        review_limit = min(review_limit, context_limit)
        try:
            snapshot = pending_metadata(
                context["knowledge_root"] / "收件箱",
                limit=5,
                max_chars=review_limit,
            )
        except OSError:
            snapshot = {"pending": 0, "invalid_count": 0, "shown": 0, "truncated": False, "items": []}
        if snapshot["pending"] or snapshot.get("invalid_count"):
            if auto_load:
                review_limit = min(review_limit, max(256, context_limit // 2))
            review_block = pending_prompt(snapshot, review_limit)

    if auto_load:
        path = context["knowledge_root"] / "当前状态.md"
        try:
            content_limit = max(0, context_limit - len(CURRENT_PREFIX))
            if review_block:
                content_limit = max(
                    0,
                    context_limit - len(CURRENT_PREFIX) - len(review_block) - 2,
                )
            content = path.read_text(encoding="utf-8")[:content_limit]
            current = CURRENT_PREFIX + content
            blocks.append(current)
        except (OSError, UnicodeError):
            pass
    if review_block:
        blocks.append(review_block)
    if not blocks:
        return
    payload = {
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": "\n\n".join(blocks)[:context_limit],
        }
    }
    write_stdout_utf8(json.dumps(payload, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
