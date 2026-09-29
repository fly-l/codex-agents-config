"""项目记忆候选文件的锁和有限元数据列表。"""

from __future__ import annotations

import argparse
import json
import os
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

if os.name == "nt":
    import msvcrt
else:
    import fcntl


DEFAULT_LIMIT = 5
DEFAULT_MAX_CHARS = 2400
MAX_LIMIT = 50
MAX_MAX_CHARS = 12000
MAX_CANDIDATE_BYTES = 256 * 1024


def _text(value: object, limit: int = 240) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _candidate_metadata(path: Path, payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "file": path.name,
        "host": _text(payload.get("host"), 32),
        "session_id": _text(payload.get("session_id"), 160),
        "turn_id": _text(payload.get("turn_id"), 160),
        "reason": _text(payload.get("reason"), 160),
        "updated_at": _text(payload.get("updated_at") or payload.get("created_at"), 64),
        "transcript_path": _text(payload.get("transcript_path"), 240),
        "transcript_exists": payload.get("transcript_exists"),
        "repository_root": _text(payload.get("repository_root"), 240),
    }


def _read_candidate(path: Path) -> dict[str, Any] | None:
    try:
        with path.open("rb") as stream:
            raw = stream.read(MAX_CANDIDATE_BYTES + 1)
        if len(raw) > MAX_CANDIDATE_BYTES:
            return None
        payload = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def pending_metadata(
    inbox: Path,
    *,
    limit: int = DEFAULT_LIMIT,
    offset: int = 0,
    max_chars: int = DEFAULT_MAX_CHARS,
) -> dict[str, Any]:
    """读取 pending 候选的有限元数据，不读取 transcript 正文。"""
    if limit < 1 or offset < 0 or max_chars < 256:
        raise ValueError("收件箱列表的 limit 必须为正数，offset 不能为负数，max_chars 至少为 256")
    if limit > MAX_LIMIT:
        raise ValueError(f"收件箱列表的 limit 不能超过 {MAX_LIMIT}")
    if max_chars > MAX_MAX_CHARS:
        raise ValueError(f"收件箱列表的 max_chars 不能超过 {MAX_MAX_CHARS}")
    json_budget = max_chars - 1
    candidates: list[tuple[str, Path, dict[str, Any]]] = []
    invalid_count = 0
    for path in inbox.glob("*.json"):
        payload = _read_candidate(path)
        if payload is None:
            invalid_count += 1
            continue
        if payload.get("status") != "pending":
            continue
        updated = str(payload.get("updated_at") or payload.get("created_at") or "")
        candidates.append((updated, path, payload))
    candidates.sort(key=lambda item: (item[0], item[1].name), reverse=True)

    items: list[dict[str, Any]] = []
    for _, path, payload in candidates[offset : offset + limit]:
        item = _candidate_metadata(path, payload)
        remaining = len(candidates) > offset + len(items) + 1
        trial = {
            "offset": offset,
            "pending": len(candidates),
            "invalid_count": invalid_count,
            "shown": len(items) + 1,
            "next_offset": offset + len(items) + 1 if remaining else None,
            "truncated": remaining,
            "items": [*items, item],
        }
        if len(json.dumps(trial, ensure_ascii=False, separators=(",", ":"))) > json_budget:
            break
        items.append(item)
    next_offset = offset + len(items) if offset + len(items) < len(candidates) else None
    result = {
        "offset": offset,
        "pending": len(candidates),
        "invalid_count": invalid_count,
        "shown": len(items),
        "next_offset": next_offset,
        "truncated": next_offset is not None,
        "items": items,
    }
    return result


def _inbox_path(vault_root: str, project: str) -> Path:
    project = project.strip()
    if not project or project in {".", ".."} or any(char in project for char in "/\\\0"):
        raise ValueError("项目名称不安全或为空")
    return Path(os.path.expandvars(vault_root)).expanduser() / project / "知识库" / "收件箱"


@contextmanager
def candidate_lock(target: Path) -> Iterator[None]:
    """锁定一个候选文件对应的固定锁文件，退出时释放内核锁。"""
    lock_path = target.with_suffix(".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+b") as handle:
        if os.name == "nt":
            handle.seek(0, os.SEEK_END)
            if handle.tell() == 0:
                handle.write(b"\0")
                handle.flush()
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
        else:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            if os.name == "nt":
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--vault-root",
        default=os.environ.get("PROJECT_MEMORY_VAULT"),
        help="Vault 根目录；默认读取 PROJECT_MEMORY_VAULT",
    )
    parser.add_argument("--project", required=True, help="项目名称")
    subparsers = parser.add_subparsers(dest="command", required=True)
    list_parser = subparsers.add_parser("list", help="列出待审核候选元数据")
    list_parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    list_parser.add_argument("--offset", type=int, default=0)
    list_parser.add_argument("--max-chars", type=int, default=DEFAULT_MAX_CHARS)
    args = parser.parse_args()
    if not args.vault_root:
        parser.error("缺少 --vault-root，且未设置 PROJECT_MEMORY_VAULT")
    if args.command == "list":
        try:
            result = pending_metadata(
                _inbox_path(args.vault_root, args.project),
                limit=args.limit,
                offset=args.offset,
                max_chars=args.max_chars,
            )
        except ValueError as exc:
            parser.error(str(exc))
        print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))


if __name__ == "__main__":
    main()
