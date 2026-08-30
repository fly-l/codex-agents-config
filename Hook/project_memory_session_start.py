#!/usr/bin/env python3
"""按项目配置向 SessionStart 注入有上限的当前状态摘要。"""

from __future__ import annotations

import json
import os

from project_memory_common import read_event, resolve


def main() -> None:
    event = read_event()
    context = resolve(event)
    if not context or context["config"].get("自动加载", "否") != "是":
        return
    path = context["knowledge_root"] / "当前状态.md"
    try:
        limit = max(500, min(int(os.environ.get("CODEX_MEMORY_CONTEXT_CHARS", "2400")), 6000))
        content = path.read_text(encoding="utf-8")[:limit]
    except (OSError, UnicodeError, ValueError):
        return
    payload = {
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": (
                "以下是项目当前状态导航摘要，可能已经过期；涉及实现或决策时必须以当前代码、测试和正式记录复核。\n\n"
                + content
            ),
        }
    }
    print(json.dumps(payload, ensure_ascii=False))


if __name__ == "__main__":
    main()
