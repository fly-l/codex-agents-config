#!/usr/bin/env python3
"""在 Stop 时登记待审核会话，不自动提升为权威记忆。"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

SCRIPT_ROOT = Path(__file__).resolve().parents[1]
MEMORY_SCRIPTS = SCRIPT_ROOT / "Skills" / "project-memory" / "scripts"
sys.path.insert(0, str(MEMORY_SCRIPTS))

from memory_inbox import candidate_lock
from project_memory_common import (
    atomic_json,
    read_stdin_utf8,
    resolve,
    write_stderr_utf8,
    write_stdout_utf8,
)


CHILD_ENV = "CODEX_RENAME_CURRENT_TITLE_CHILD"


def safe_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-._")[:80] or "session"


def explicit_session_id(event: dict[str, Any]) -> str | None:
    for key in ("session_id", "thread_id", "sessionId", "threadId"):
        value = event.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def explicit_turn_id(event: dict[str, Any]) -> str | None:
    for key in ("turn_id", "turnId"):
        value = event.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def explicit_updated_at(event: dict[str, Any]) -> str | None:
    for key in ("updated_at", "updatedAt"):
        value = event.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def transcript_markers(
    path_value: str,
) -> tuple[bool, int | None, float | None, int | None]:
    if not path_value:
        return False, None, None, None
    path = Path(path_value)
    try:
        stat = path.stat()
    except (OSError, ValueError):
        return False, None, None, None
    if not path.is_file():
        return False, None, None, None
    return True, stat.st_size, stat.st_mtime, stat.st_mtime_ns


def candidate_path(root: Path, host: str, session_id: str) -> Path:
    identity = f"{host}\0{session_id}".encode("utf-8")
    digest = hashlib.sha256(identity).hexdigest()
    return root / "收件箱" / f"{safe_name(session_id)}-{digest}.json"


def read_candidate(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def candidate_version(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "turn_id": payload.get("turn_id"),
        "event_updated_at": payload.get("event_updated_at"),
        "transcript_size": payload.get("transcript_size"),
        "transcript_mtime_ns": payload.get("transcript_mtime_ns"),
    }


def emit_empty() -> None:
    write_stdout_utf8("{}\n")


def main() -> None:
    if os.environ.get(CHILD_ENV) == "1":
        emit_empty()
        return

    try:
        event = json.loads(read_stdin_utf8())
    except (json.JSONDecodeError, OSError, UnicodeError) as exc:
        write_stderr_utf8(f"Stop Hook 输入不是有效 JSON：{exc}\n")
        emit_empty()
        return
    if not isinstance(event, dict):
        write_stderr_utf8("Stop Hook 输入必须是 JSON 对象。\n")
        emit_empty()
        return
    if event.get("stop_hook_active") is True:
        emit_empty()
        return

    session_id = explicit_session_id(event)
    if not session_id:
        emit_empty()
        return

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", choices=("codex", "claude", "pi"), default="codex")
    args = parser.parse_args()
    context = resolve(event, host=args.host)
    if not context or context["config"].get("自动收集", "是") != "是":
        emit_empty()
        return

    target = candidate_path(context["knowledge_root"], args.host, session_id)
    with candidate_lock(target):
        previous = read_candidate(target) if target.exists() else None
        transcript = str(event.get("transcript_path") or "")
        exists, size, mtime, mtime_ns = transcript_markers(transcript)
        current_version = {
            "turn_id": explicit_turn_id(event),
            "event_updated_at": explicit_updated_at(event),
            "transcript_size": size,
            "transcript_mtime_ns": mtime_ns,
        }
        if previous is not None and candidate_version(previous) == current_version:
            emit_empty()
            return

        now = dt.datetime.now(dt.timezone.utc)
        payload = dict(previous or {})
        payload.update(
            {
                "schema_version": 1,
                "status": "pending",
                "updated_at": now.isoformat(),
                "project": context["project"],
                "host": args.host,
                "session_id": session_id,
                "turn_id": current_version["turn_id"],
                "event_updated_at": current_version["event_updated_at"],
                "reason": str(event.get("reason") or "other"),
                "cwd": str(context["cwd"]),
                "repository_root": str(context["root"]),
                "transcript_path": transcript,
                "transcript_exists": exists,
                "transcript_size": size,
                "transcript_mtime": mtime,
                "transcript_mtime_ns": mtime_ns,
                "version": current_version,
                "note": "候选记录；必须经 project-memory Skill 审核和验证后才能转为正式记忆。",
            }
        )
        payload.setdefault("created_at", now.isoformat())
        payload.pop("processed_at", None)
        atomic_json(target, payload)
    emit_empty()


if __name__ == "__main__":
    main()
