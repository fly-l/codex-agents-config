#!/usr/bin/env python3
"""项目记忆的确定性、原子化存储工具。"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Any


KIND_DIRS = {
    "decision": "决策",
    "bug": "Bug",
    "api": "API",
    "architecture": "架构",
    "convention": "约定",
    "environment": "环境",
}
VALID_STATUSES = {
    "proposed",
    "accepted",
    "active",
    "fixed",
    "deprecated",
    "superseded",
}
SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


def fail(message: str, code: int = 2) -> None:
    print(json.dumps({"ok": False, "error": message}, ensure_ascii=False), file=sys.stderr)
    raise SystemExit(code)


def scalar(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def normalize(value: str) -> str:
    return " ".join(value.replace("\r\n", "\n").replace("\r", "\n").split()).casefold()


def fingerprint(kind: str, title: str, body: str, modules: list[str]) -> str:
    payload = json.dumps(
        {
            "type": kind,
            "title": normalize(title),
            "body": normalize(body),
            "module": sorted(normalize(item) for item in modules),
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def validate_component(value: str, label: str) -> str:
    value = value.strip()
    if not value or value in {".", ".."} or any(char in value for char in "/\\\0"):
        fail(f"{label} 不安全或为空")
    return value


def validate_id(value: str) -> str:
    if not SAFE_ID.fullmatch(value):
        fail("ID 只能包含字母、数字、点、下划线和连字符，且最长 128 字符")
    return value


def knowledge_root(vault_root: str, project: str) -> Path:
    project = validate_component(project, "项目名称")
    root = Path(os.path.expandvars(vault_root)).expanduser()
    if not str(root).strip():
        fail("Vault 根目录为空")
    return root / project / "知识库"


def atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", newline="\n", dir=path.parent, delete=False
    ) as handle:
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())
        temporary = Path(handle.name)
    os.replace(temporary, path)


def parse_scalar(value: str) -> Any:
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value.strip().strip('"').strip("'")


def read_frontmatter(path: Path) -> dict[str, Any]:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return {}
    if not text.startswith("---\n"):
        return {}
    end = text.find("\n---\n", 4)
    if end < 0:
        return {}
    result: dict[str, Any] = {}
    for line in text[4:end].splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        result[key.strip()] = parse_scalar(value.strip())
    return result


def ensure_initialized(root: Path, project: str) -> list[str]:
    created: list[str] = []
    for directory in [*KIND_DIRS.values(), "收件箱"]:
        target = root / directory
        if not target.exists():
            target.mkdir(parents=True, exist_ok=True)
            created.append(str(target))

    current = root / "当前状态.md"
    if not current.exists():
        atomic_write(
            current,
            "---\n"
            f"project: {scalar(project)}\n"
            "status: active\n"
            f"updated: {dt.date.today().isoformat()}\n"
            "---\n\n"
            f"# {project} 当前状态\n\n"
            "> 仅保存仍然有效的短摘要；详细历史请链接到原子记录。\n",
        )
        created.append(str(current))

    index = root / "索引.md"
    if not index.exists():
        atomic_write(index, render_index(project, []))
        created.append(str(index))
    return created


def collect_records(root: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for directory in KIND_DIRS.values():
        folder = root / directory
        if not folder.exists():
            continue
        for path in sorted(folder.glob("*.md")):
            metadata = read_frontmatter(path)
            if not metadata.get("id"):
                continue
            metadata["path"] = path.relative_to(root).with_suffix("").as_posix()
            records.append(metadata)
    return records


def render_index(project: str, records: list[dict[str, Any]]) -> str:
    lines = [
        "---",
        f"project: {scalar(project)}",
        f"updated: {dt.date.today().isoformat()}",
        "---",
        "",
        f"# {project} 知识索引",
        "",
        "> 由 memory_store.py 生成；不要手工追加反向链接。",
        "",
        "| ID | 类型 | 状态 | 标题 | 最近验证 |",
        "|---|---|---|---|---|",
    ]
    for item in sorted(records, key=lambda row: str(row.get("updated", "")), reverse=True):
        record_id = str(item.get("id", ""))
        path = str(item.get("path", ""))
        title = str(item.get("title", "")).replace("|", "\\|")
        lines.append(
            f"| [[{path}|{record_id}]] | {item.get('type', '')} | "
            f"{item.get('status', '')} | {title} | {item.get('verified_at', '')} |"
        )
    return "\n".join(lines) + "\n"


def rebuild_index(root: Path, project: str) -> None:
    atomic_write(root / "索引.md", render_index(project, collect_records(root)))


def command_init(args: argparse.Namespace) -> None:
    root = knowledge_root(args.vault_root, args.project)
    created = ensure_initialized(root, args.project)
    print(json.dumps({"ok": True, "root": str(root), "created": created}, ensure_ascii=False))


def read_body(args: argparse.Namespace) -> str:
    if args.body is not None:
        return args.body.strip()
    if args.body_file:
        try:
            return Path(args.body_file).read_text(encoding="utf-8").strip()
        except (OSError, UnicodeError) as exc:
            fail(f"无法读取正文文件：{exc}")
    fail("必须提供 --body 或 --body-file")
    return ""


def command_upsert(args: argparse.Namespace) -> None:
    record_id = validate_id(args.id)
    if args.status not in VALID_STATUSES:
        fail(f"不支持的状态：{args.status}")
    root = knowledge_root(args.vault_root, args.project)
    ensure_initialized(root, args.project)
    body = read_body(args)
    modules = [item.strip() for item in args.module if item.strip()]
    supersedes = [validate_id(item) for item in args.supersedes]
    digest = fingerprint(args.kind, args.title, body, modules)
    target = root / KIND_DIRS[args.kind] / f"{record_id}.md"

    existing = read_frontmatter(target) if target.exists() else {}
    if args.expected_fingerprint and existing.get("fingerprint") != args.expected_fingerprint:
        fail("现有记录指纹与 --expected-fingerprint 不一致，拒绝覆盖", 3)

    for item in collect_records(root):
        if item.get("fingerprint") == digest and item.get("id") != record_id:
            print(
                json.dumps(
                    {"ok": True, "action": "duplicate", "existing_id": item.get("id")},
                    ensure_ascii=False,
                )
            )
            return

    today = dt.date.today().isoformat()
    created = str(existing.get("created") or today)
    metadata = [
        "---",
        f"id: {scalar(record_id)}",
        f"type: {scalar(args.kind)}",
        f"status: {scalar(args.status)}",
        f"title: {scalar(args.title.strip())}",
        f"project: {scalar(args.project)}",
        f"module: {json.dumps(modules, ensure_ascii=False)}",
        f"source: {scalar(args.source.strip())}",
        f"created: {created}",
        f"updated: {today}",
        f"verified_at: {args.verified_at or today}",
        f"supersedes: {json.dumps(supersedes, ensure_ascii=False)}",
        f"fingerprint: {scalar(digest)}",
        "---",
        "",
        f"# {record_id}: {args.title.strip()}",
        "",
        "## 内容",
        "",
        body,
        "",
    ]
    atomic_write(target, "\n".join(metadata))
    rebuild_index(root, args.project)
    print(
        json.dumps(
            {
                "ok": True,
                "action": "updated" if existing else "created",
                "path": str(target),
                "fingerprint": digest,
            },
            ensure_ascii=False,
        )
    )


def command_set_current(args: argparse.Namespace) -> None:
    root = knowledge_root(args.vault_root, args.project)
    ensure_initialized(root, args.project)
    try:
        body = Path(args.body_file).read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError) as exc:
        fail(f"无法读取当前状态摘要：{exc}")
    if len(body.splitlines()) > 80:
        fail("当前状态摘要超过 80 行")
    content = (
        "---\n"
        f"project: {scalar(args.project)}\n"
        "status: active\n"
        f"updated: {dt.date.today().isoformat()}\n"
        "---\n\n"
        f"# {args.project} 当前状态\n\n{body}\n"
    )
    target = root / "当前状态.md"
    atomic_write(target, content)
    print(json.dumps({"ok": True, "path": str(target)}, ensure_ascii=False))


def command_mark_inbox(args: argparse.Namespace) -> None:
    root = knowledge_root(args.vault_root, args.project)
    inbox = (root / "收件箱").resolve()
    target = (inbox / args.file).resolve()
    if target.parent != inbox or target.suffix != ".json":
        fail("收件箱文件名不安全")
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        fail(f"无法读取收件箱记录：{exc}")
    payload["status"] = args.status
    payload["processed_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
    atomic_write(target, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"ok": True, "path": str(target), "status": args.status}, ensure_ascii=False))


def command_validate(args: argparse.Namespace) -> None:
    root = knowledge_root(args.vault_root, args.project)
    records = collect_records(root)
    errors: list[str] = []
    ids: dict[str, str] = {}
    fingerprints: dict[str, list[dict[str, Any]]] = {}
    for item in records:
        record_id = str(item.get("id", ""))
        path = str(item.get("path", ""))
        digest = str(item.get("fingerprint", ""))
        if record_id in ids:
            errors.append(f"重复 ID：{record_id} ({ids[record_id]}, {path})")
        ids[record_id] = path
        if digest:
            fingerprints.setdefault(digest, []).append(item)
        if item.get("status") not in VALID_STATUSES:
            errors.append(f"无效状态：{record_id} -> {item.get('status')}")
    for items in fingerprints.values():
        live_ids = [
            str(item.get("id", ""))
            for item in items
            if item.get("status") not in {"deprecated", "superseded"}
        ]
        if len(live_ids) > 1:
            errors.append(f"有效记录重复指纹：{', '.join(live_ids)}")
    for item in records:
        if item.get("status") != "superseded":
            continue
        replacement = str(item.get("superseded_by") or "")
        if replacement and replacement not in ids:
            errors.append(f"替代目标不存在：{item.get('id')} -> {replacement}")
    result = {"ok": not errors, "records": len(records), "errors": errors}
    print(json.dumps(result, ensure_ascii=False))
    if errors:
        raise SystemExit(1)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--vault-root",
        default=os.environ.get("CODEX_MEMORY_VAULT"),
        help="Obsidian Vault 根目录；默认读取 CODEX_MEMORY_VAULT",
    )
    parser.add_argument("--project", required=True, help="项目名称")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init", help="初始化知识库")
    init_parser.set_defaults(func=command_init)

    upsert = subparsers.add_parser("upsert", help="创建或更新原子记录")
    upsert.add_argument("--kind", required=True, choices=sorted(KIND_DIRS))
    upsert.add_argument("--id", required=True)
    upsert.add_argument("--title", required=True)
    body_group = upsert.add_mutually_exclusive_group(required=True)
    body_group.add_argument("--body")
    body_group.add_argument("--body-file")
    upsert.add_argument("--status", required=True, choices=sorted(VALID_STATUSES))
    upsert.add_argument("--source", required=True)
    upsert.add_argument("--verified-at")
    upsert.add_argument("--module", action="append", default=[])
    upsert.add_argument("--supersedes", action="append", default=[])
    upsert.add_argument("--expected-fingerprint")
    upsert.set_defaults(func=command_upsert)

    current = subparsers.add_parser("set-current", help="更新短当前状态")
    current.add_argument("--body-file", required=True)
    current.set_defaults(func=command_set_current)

    inbox = subparsers.add_parser("mark-inbox", help="标记 Hook 收件箱记录")
    inbox.add_argument("--file", required=True)
    inbox.add_argument("--status", required=True, choices=["processed", "ignored"])
    inbox.set_defaults(func=command_mark_inbox)

    validate = subparsers.add_parser("validate", help="检查重复和元数据错误")
    validate.set_defaults(func=command_validate)
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    if not args.vault_root:
        fail("缺少 --vault-root，且未设置 CODEX_MEMORY_VAULT")
    args.func(args)


if __name__ == "__main__":
    main()
