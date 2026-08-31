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
HISTORICAL_STATUSES = {"deprecated", "superseded"}
ACTIVE_INDEX_MAX_RECORDS = 60
ACTIVE_INDEX_MAX_CHARS = 6000
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


def active_input_fingerprint(root: Path, records: list[dict[str, Any]]) -> str:
    payload: list[dict[str, str]] = []
    for item in sorted(records, key=lambda row: str(row.get("id", ""))):
        if item.get("status") in HISTORICAL_STATUSES:
            continue
        body = read_record_content(root / f"{item.get('path', '')}.md")
        modules = item.get("module", [])
        if body is None or not isinstance(modules, list):
            digest = "invalid-content"
        else:
            digest = fingerprint(
                str(item.get("type", "")),
                str(item.get("title", "")),
                body,
                [str(value) for value in modules],
            )
        payload.append(
            {
                "id": str(item.get("id", "")),
                "status": str(item.get("status", "")),
                "fingerprint": digest,
                "updated": str(item.get("updated", "")),
            }
        )
    rendered = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(rendered.encode("utf-8")).hexdigest()


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


def markdown_body(text: str) -> str:
    if text.startswith("---\n"):
        end = text.find("\n---\n", 4)
        if end >= 0:
            text = text[end + len("\n---\n") :]
    lines = text.splitlines()
    while lines and not lines[0].strip():
        lines.pop(0)
    if lines and lines[0].startswith("# "):
        lines.pop(0)
    while lines and not lines[0].strip():
        lines.pop(0)
    return "\n".join(lines).strip()


def read_record_content(path: Path) -> str | None:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return None
    marker = "\n## 内容\n\n"
    if marker not in text:
        return None
    return text.split(marker, 1)[1].strip()


def update_frontmatter(path: Path, updates: dict[str, Any]) -> None:
    """仅更新指定 frontmatter 字段，保留正文和其他元数据。"""
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        fail(f"无法读取记录 {path.name}：{exc}")
    if not text.startswith("---\n"):
        fail(f"记录缺少 frontmatter：{path.name}")
    end = text.find("\n---\n", 4)
    if end < 0:
        fail(f"记录 frontmatter 不完整：{path.name}")

    pending = dict(updates)
    rendered: list[str] = []
    for line in text[4:end].splitlines():
        if ":" not in line:
            rendered.append(line)
            continue
        key = line.split(":", 1)[0].strip()
        if key not in pending:
            rendered.append(line)
            continue
        value = pending.pop(key)
        rendered.append(f"{key}: {json.dumps(value, ensure_ascii=False)}")
    for key, value in pending.items():
        rendered.append(f"{key}: {json.dumps(value, ensure_ascii=False)}")
    atomic_write(path, "---\n" + "\n".join(rendered) + text[end:])


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
    history_index = root / "历史索引.md"
    if not index.exists():
        atomic_write(index, render_index(project, [], 0))
        created.append(str(index))
    if not history_index.exists():
        atomic_write(history_index, render_history_index(project, []))
        created.append(str(history_index))
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


def render_index(
    project: str, records: list[dict[str, Any]], historical_count: int
) -> str:
    lines = [
        "---",
        f"project: {scalar(project)}",
        f"updated: {dt.date.today().isoformat()}",
        "---",
        "",
        f"# {project} 知识索引",
        "",
        "> 仅列出活跃记录，由 memory_store.py 生成；不要手工追加反向链接。",
        f"> 历史记录 {historical_count} 条；仅在追溯历史时读取 [[历史索引]]。",
        (
            f"> 活跃记录 {len(records)} 条；入口最多展示 {ACTIVE_INDEX_MAX_RECORDS} 条，"
            f"且不超过 {ACTIVE_INDEX_MAX_CHARS} 字符。"
        ),
        "",
        "| ID | 类型 | 状态 | 标题 | 最近验证 |",
        "|---|---|---|---|---|",
    ]
    rows: list[str] = []
    ordered = sorted(records, key=lambda row: str(row.get("updated", "")), reverse=True)
    overflow_note = "> 未展示的活跃记录请按关键词搜索分类目录，不要加载整个知识库。"
    for item in ordered[:ACTIVE_INDEX_MAX_RECORDS]:
        record_id = str(item.get("id", ""))
        path = str(item.get("path", ""))
        title = str(item.get("title", "")).replace("|", "\\|")[:120]
        row = (
            f"| [[{path}|{record_id}]] | {item.get('type', '')} | "
            f"{item.get('status', '')} | {title} | {item.get('verified_at', '')} |"
        )
        candidate = "\n".join([*lines, *rows, row, "", overflow_note]) + "\n"
        if len(candidate) > ACTIVE_INDEX_MAX_CHARS:
            break
        rows.append(row)
    if len(rows) < len(records):
        rows.extend(["", overflow_note])
    return "\n".join([*lines, *rows]) + "\n"


def render_history_index(project: str, records: list[dict[str, Any]]) -> str:
    lines = [
        "---",
        f"project: {scalar(project)}",
        f"updated: {dt.date.today().isoformat()}",
        "---",
        "",
        f"# {project} 历史知识索引",
        "",
        "> 仅用于追溯已弃用或已替代记录；普通回忆不要加载此文件。",
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


def rebuild_indexes(root: Path, project: str) -> None:
    records = collect_records(root)
    active = [item for item in records if item.get("status") not in HISTORICAL_STATUSES]
    historical = [item for item in records if item.get("status") in HISTORICAL_STATUSES]
    atomic_write(root / "索引.md", render_index(project, active, len(historical)))
    atomic_write(root / "历史索引.md", render_history_index(project, historical))


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
    requested_supersedes = [validate_id(item) for item in args.supersedes]
    digest = fingerprint(args.kind, args.title, body, modules)
    target = root / KIND_DIRS[args.kind] / f"{record_id}.md"

    existing = read_frontmatter(target) if target.exists() else {}
    if args.expected_fingerprint and existing.get("fingerprint") != args.expected_fingerprint:
        fail("现有记录指纹与 --expected-fingerprint 不一致，拒绝覆盖", 3)

    records = collect_records(root)
    records_by_id = {str(item.get("id")): item for item in records}
    existing_supersedes = existing.get("supersedes", [])
    if not isinstance(existing_supersedes, list):
        existing_supersedes = []
    supersedes = list(dict.fromkeys([*existing_supersedes, *requested_supersedes]))
    for old_id in supersedes:
        if old_id == record_id:
            fail("记录不能替代自身")
        old = records_by_id.get(old_id)
        if not old:
            fail(f"被替代记录不存在：{old_id}")
        if old.get("type") != args.kind:
            fail(f"被替代记录类型不一致：{old_id}")

    for item in records:
        if (
            item.get("fingerprint") == digest
            and item.get("id") != record_id
            and item.get("id") not in supersedes
            and item.get("status") not in HISTORICAL_STATUSES
        ):
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
    for old_id in supersedes:
        old = records_by_id[old_id]
        old_path = root / f"{old['path']}.md"
        update_frontmatter(
            old_path,
            {"status": "superseded", "updated": today, "superseded_by": record_id},
        )
    rebuild_indexes(root, args.project)
    print(
        json.dumps(
            {
                "ok": True,
                "action": "updated" if existing else "created",
                "path": str(target),
                "fingerprint": digest,
                "superseded": supersedes,
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
    if len(body) > args.max_chars:
        fail(f"当前状态摘要超过 {args.max_chars} 字符")
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
    fingerprints: dict[str, str] = {}
    records_by_id = {str(item.get("id", "")): item for item in records}
    for item in records:
        record_id = str(item.get("id", ""))
        path = str(item.get("path", ""))
        digest = str(item.get("fingerprint", ""))
        if record_id in ids:
            errors.append(f"重复 ID：{record_id} ({ids[record_id]}, {path})")
        ids[record_id] = path
        if digest and item.get("status") not in HISTORICAL_STATUSES:
            if digest in fingerprints:
                errors.append(f"重复指纹：{record_id} 与 {fingerprints[digest]}")
            fingerprints[digest] = record_id
        record_path = root / f"{path}.md"
        body = read_record_content(record_path)
        modules = item.get("module", [])
        if body is None:
            errors.append(f"无法提取记录正文：{record_id}")
        elif not isinstance(modules, list):
            errors.append(f"module 不是列表：{record_id}")
        else:
            expected_digest = fingerprint(
                str(item.get("type", "")),
                str(item.get("title", "")),
                body,
                [str(value) for value in modules],
            )
            if digest != expected_digest:
                errors.append(f"内容指纹不匹配：{record_id}")
        if item.get("status") not in VALID_STATUSES:
            errors.append(f"无效状态：{record_id} -> {item.get('status')}")
        supersedes = item.get("supersedes", [])
        if not isinstance(supersedes, list):
            errors.append(f"supersedes 不是列表：{record_id}")
            continue
        for old_id in supersedes:
            if old_id == record_id:
                errors.append(f"记录替代自身：{record_id}")
                continue
            old = records_by_id.get(str(old_id))
            if not old:
                errors.append(f"被替代记录不存在：{record_id} -> {old_id}")
            elif old.get("status") != "superseded":
                errors.append(f"被替代记录状态错误：{old_id} -> {old.get('status')}")
            elif old.get("type") != item.get("type"):
                errors.append(f"被替代记录类型不一致：{record_id} -> {old_id}")
            elif old.get("superseded_by") != record_id:
                errors.append(
                    f"被替代记录缺少正确 superseded_by：{old_id} -> "
                    f"{old.get('superseded_by')}"
                )

    graph = {
        str(item.get("id", "")): [str(value) for value in item.get("supersedes", [])]
        for item in records
        if isinstance(item.get("supersedes", []), list)
    }
    visited: set[str] = set()
    visiting: set[str] = set()

    def visit(record_id: str) -> bool:
        if record_id in visiting:
            return True
        if record_id in visited:
            return False
        visiting.add(record_id)
        cyclic = any(visit(old_id) for old_id in graph.get(record_id, []))
        visiting.remove(record_id)
        visited.add(record_id)
        return cyclic

    for start in graph:
        if start not in visited and visit(start):
            errors.append(f"supersedes 存在环：{start}")
    result = {"ok": not errors, "records": len(records), "errors": errors}
    print(json.dumps(result, ensure_ascii=False))
    if errors:
        raise SystemExit(1)


def command_rebuild_indexes(args: argparse.Namespace) -> None:
    root = knowledge_root(args.vault_root, args.project)
    ensure_initialized(root, args.project)
    rebuild_indexes(root, args.project)
    print(json.dumps({"ok": True, "root": str(root)}, ensure_ascii=False))


def command_maintenance_audit(args: argparse.Namespace) -> None:
    if args.stale_days < 0 or args.batch_size < 1 or args.max_groups < 1:
        fail("审计参数必须为非负天数和正数批次")
    root = knowledge_root(args.vault_root, args.project)
    if not root.is_dir():
        fail("项目知识库尚未初始化")
    records = collect_records(root)
    active = [item for item in records if item.get("status") not in HISTORICAL_STATUSES]
    historical = [item for item in records if item.get("status") in HISTORICAL_STATUSES]

    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for item in active:
        modules = item.get("module", [])
        if not isinstance(modules, list):
            modules = []
        module_key = ", ".join(sorted(str(value) for value in modules)) or "未分类"
        key = (str(item.get("type", "")), module_key)
        grouped.setdefault(key, []).append(item)

    candidates: list[dict[str, Any]] = []
    for (kind, module), items in grouped.items():
        if len(items) < 2:
            continue
        ordered = sorted(items, key=lambda row: str(row.get("updated", "")), reverse=True)
        candidates.append(
            {
                "type": kind,
                "module": module,
                "records": len(ordered),
                "sample_ids": [str(item.get("id")) for item in ordered[: args.batch_size]],
                "truncated": len(ordered) > args.batch_size,
            }
        )
    candidates.sort(key=lambda item: int(item["records"]), reverse=True)

    cutoff = dt.date.today() - dt.timedelta(days=args.stale_days)
    stale_ids = [
        str(item.get("id"))
        for item in active
        if str(item.get("verified_at", "")) < cutoff.isoformat()
    ]
    current = root / "当前状态.md"
    try:
        current_text = current.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        current_text = ""
    current_body = markdown_body(current_text)
    index = root / "索引.md"
    try:
        index_chars = len(index.read_text(encoding="utf-8"))
    except (OSError, UnicodeError):
        index_chars = 0
    pending_inbox = 0
    for path in (root / "收件箱").glob("*.json"):
        try:
            if json.loads(path.read_text(encoding="utf-8")).get("status") == "pending":
                pending_inbox += 1
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue

    summary_path = root / "知识摘要.md"
    summary_metadata = read_frontmatter(summary_path) if summary_path.exists() else {}
    current_fingerprint = active_input_fingerprint(root, records)
    summary_fingerprint = str(summary_metadata.get("source_fingerprint") or "")
    summary_coverage = str(summary_metadata.get("coverage") or "partial")
    summary_stale = not summary_path.exists() or summary_fingerprint != current_fingerprint
    result = {
        "ok": True,
        "root": str(root),
        "active_records": len(active),
        "historical_records": len(historical),
        "status_counts": {
            status: sum(1 for item in records if item.get("status") == status)
            for status in sorted(VALID_STATUSES)
        },
        "active_index_chars": index_chars,
        "current_state_lines": len(current_body.splitlines()),
        "current_state_chars": len(current_body),
        "pending_inbox": pending_inbox,
        "stale_active_records": len(stale_ids),
        "stale_sample_ids": stale_ids[: args.batch_size],
        "candidate_groups": candidates[: args.max_groups],
        "summary": {
            "exists": summary_path.exists(),
            "updated": summary_metadata.get("updated"),
            "source_fingerprint": summary_fingerprint,
            "current_fingerprint": current_fingerprint,
            "coverage": summary_coverage,
            "stale": summary_stale,
            "usable": not summary_stale and summary_coverage == "complete",
        },
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


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
    current.add_argument("--max-chars", type=int, default=6000)
    current.set_defaults(func=command_set_current)

    inbox = subparsers.add_parser("mark-inbox", help="标记 Hook 收件箱记录")
    inbox.add_argument("--file", required=True)
    inbox.add_argument("--status", required=True, choices=["processed", "ignored"])
    inbox.set_defaults(func=command_mark_inbox)

    validate = subparsers.add_parser("validate", help="检查重复和元数据错误")
    validate.set_defaults(func=command_validate)

    rebuild = subparsers.add_parser("rebuild-indexes", help="重建活跃索引和历史索引")
    rebuild.set_defaults(func=command_rebuild_indexes)

    audit = subparsers.add_parser("maintenance-audit", help="输出知识库维护审计摘要")
    audit.add_argument("--stale-days", type=int, default=180)
    audit.add_argument("--batch-size", type=int, default=12)
    audit.add_argument("--max-groups", type=int, default=20)
    audit.set_defaults(func=command_maintenance_audit)
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    if not args.vault_root:
        fail("缺少 --vault-root，且未设置 CODEX_MEMORY_VAULT")
    args.func(args)


if __name__ == "__main__":
    main()
