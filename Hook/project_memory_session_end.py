#!/usr/bin/env python3
"""在 SessionEnd 时登记待审核会话，不自动提升为权威记忆。"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import re
from pathlib import Path

from project_memory_common import atomic_json, read_event, resolve


def safe_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-._")[:80] or "session"


def main() -> None:
    if os.environ.get("CODEX_RENAME_CURRENT_TITLE_CHILD") == "1":
        return
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", choices=("codex", "claude"), default="codex")
    args = parser.parse_args()
    event = read_event()
    context = resolve(event, host=args.host)
    if not context or context["config"].get("自动收集", "是") != "是":
        return
    now = dt.datetime.now(dt.timezone.utc)
    session_id = str(event.get("session_id") or "session")
    transcript = str(event.get("transcript_path") or "")
    payload = {
        "schema_version": 1,
        "status": "pending",
        "created_at": now.isoformat(),
        "project": context["project"],
        "session_id": session_id,
        "reason": str(event.get("reason") or "other"),
        "cwd": str(context["cwd"]),
        "repository_root": str(context["root"]),
        "transcript_path": transcript,
        "transcript_exists": bool(transcript and Path(transcript).is_file()),
        "note": "候选记录；必须经 project-memory Skill 审核和验证后才能转为正式记忆。",
    }
    timestamp = now.strftime("%Y%m%dT%H%M%SZ")
    target = context["knowledge_root"] / "收件箱" / f"{timestamp}-{safe_name(session_id)}.json"
    atomic_json(target, payload)


if __name__ == "__main__":
    main()
