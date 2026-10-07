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
TYPE_BY_DIRECTORY = {directory: kind for kind, directory in KIND_DIRS.items()}
VALID_STATUSES = {
    "proposed",
    "accepted",
    "active",
    "fixed",
    "deprecated",
    "superseded",
}
HISTORICAL_STATUSES = {"deprecated", "superseded"}
AUTHORITATIVE_STATUSES = {"active", "accepted", "fixed"}
ACTIVE_INDEX_MAX_RECORDS = 60
ACTIVE_INDEX_MAX_CHARS = 6000
SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def fail(message: str, code: int = 2) -> None:
    print(json.dumps({"ok": False, "error": message}, ensure_ascii=False), file=sys.stderr)
    raise SystemExit(code)


def scalar(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def normalize(value: str) -> str:
    return " ".join(value.replace("\r\n", "\n").replace("\r", "\n").split()).casefold()


def fingerprint(kind: str, title: str, body: str, modules: list[str], *, legacy: bool = False) -> str:
    # 旧算法仅用于验证历史记录；内容身份必须保留代码大小写和缩进。
    values = [title, body, *modules]
    values = [normalize(value) if legacy else value.replace("\r\n", "\n").replace("\r", "\n")
              for value in values]
    payload = json.dumps(
        {
            "type": kind,
            "title": values[0],
            "body": values[1],
            "module": sorted(values[2:]),
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def active_input_fingerprint(
    root: Path, records: list[dict[str, Any]], included_history: list[str] | None = None,
) -> str:
    payload: list[dict[str, str]] = []
    historical_ids = set(included_history or [])
    for item in sorted(records, key=lambda row: str(row.get("id", ""))):
        if item.get("status") not in AUTHORITATIVE_STATUSES and not (
            item.get("status") in HISTORICAL_STATUSES and item.get("id") in historical_ids
        ):
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
                "source": str(item.get("source", "")),
                "verified_at": str(item.get("verified_at", "")),
            }
        )
    rendered = json.dumps({"version": 2, "records": payload}, ensure_ascii=False, sort_keys=True)
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


def valid_iso_date(value: Any) -> bool:
    if not isinstance(value, str) or not ISO_DATE.fullmatch(value):
        return False
    try:
        dt.date.fromisoformat(value)
    except ValueError:
        return False
    return True


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


def read_frontmatter(path: Path, *, strict: bool = False) -> dict[str, Any]:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        if strict:
            fail(f"无法读取记录 {path}：{exc}")
        return {}
    if not text.startswith("---\n"):
        if strict:
            fail(f"记录缺少 frontmatter：{path}")
        return {}
    end = text.find("\n---\n", 4)
    if end < 0:
        if strict:
            fail(f"记录 frontmatter 不完整：{path}")
        return {}
    result: dict[str, Any] = {}
    for line in text[4:end].splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if ":" not in line:
            if strict:
                fail(f"记录 frontmatter 格式错误：{path}")
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        if not key:
            if strict:
                fail(f"记录 frontmatter 格式错误：{path}")
            continue
        if key in result and strict:
            fail(f"记录 frontmatter 存在重复字段 {key}：{path}")
        result[key] = parse_scalar(value.strip())
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
        if not folder.is_dir():
            fail(f"分类目录不是目录：{folder}")
        for path in sorted(folder.glob("*.md")):
            metadata = read_frontmatter(path, strict=True)
            if not metadata.get("id"):
                fail(f"记录缺少 id：{path}")
            modules = metadata.get("module", [])
            if not isinstance(modules, list) or any(not isinstance(value, str) or not value.strip() for value in modules):
                fail(f"module 必须是非空字符串列表（旧记录可缺省）：{path}")
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


def select_modules(records: list[dict[str, Any]], modules: list[str]) -> list[dict[str, Any]]:
    """模块查询同时保留全局规则和需要复核范围的旧记录。"""
    if not modules:
        return records
    requested = set(modules)
    return [
        item for item in records
        if not item.get("module")
        or "global" in item["module"]
        or requested.intersection(item["module"])
    ]


def command_search(args: argparse.Namespace) -> None:
    terms = list(dict.fromkeys(normalize(args.query).split()))
    modules = [value.strip() for value in args.module]
    if any(not value for value in modules) or (not terms and not modules):
        fail("检索必须提供非空 --query 或 --module")
    if args.limit < 1 or args.offset < 0 or args.max_chars < 1:
        fail("--limit、--max-chars 必须为正数，--offset 不能为负数")
    root = knowledge_root(args.vault_root, args.project)
    if not root.is_dir():
        fail("项目知识库尚未初始化")
    candidates = select_modules(collect_records(root), modules)
    matches: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
    snapshot_records: list[dict[str, Any]] = []
    for item in candidates:
        if item.get("status") not in AUTHORITATIVE_STATUSES:
            continue
        body = read_record_content(root / f"{item['path']}.md")
        if body is None:
            fail(f"无法读取记录正文：{item['id']}")
        heading = normalize(f"{item['id']} {item.get('title', '')} {' '.join(item.get('module', []))}")
        content = normalize(f"{item.get('source', '')} {body}")
        matched_terms = [term for term in terms if term in heading or term in content]
        score = sum(3 * (term in heading) + (term in content) for term in terms)
        if terms and (not matched_terms or (args.match == "all" and len(matched_terms) != len(terms))):
            continue
        result = {
            key: item.get(key, "")
            for key in ("id", "title", "status", "path", "source", "verified_at")
        }
        result["module"] = item.get("module", [])
        result["scope_needs_review"] = not bool(item.get("module"))
        # 预览围绕实际命中位置展开，避免长笔记的开头掩盖有效证据。
        positions = [match.start() for term in terms
                     if (match := re.search(re.escape(term), body, re.IGNORECASE))]
        start = max(0, min(positions) - 60) if positions else 0
        excerpt = body[start : start + 238]
        result["excerpt"] = ("…" if start else "") + excerpt + ("…" if start + 238 < len(body) else "")
        rank = (
            normalize(args.query) == normalize(str(item["id"])),
            len(matched_terms), score,
            bool(set(modules).intersection(item.get("module", []))),
            str(item.get("updated", "")), str(item["id"]),
        )
        matches.append((rank, result))
        # 包含完整正文与元数据，预览之外的修改也必须使下一页失效。
        snapshot_records.append({**item, "body_hash": hashlib.sha256(body.encode("utf-8")).hexdigest()})
    matches.sort(key=lambda item: item[0], reverse=True)
    snapshot = hashlib.sha256(json.dumps(
        {"query": terms, "module": sorted(modules), "match": args.match, "records": snapshot_records},
        ensure_ascii=False, sort_keys=True,
    ).encode("utf-8")).hexdigest()
    if args.expected_snapshot and args.expected_snapshot != snapshot:
        fail("检索范围或记录已变化，请从第一页重新检索，不能沿用旧分页偏移")
    selected = [item[1] for item in matches[args.offset : args.offset + args.limit]]
    while True:
        next_offset = args.offset + len(selected)
        more = next_offset < len(matches)
        payload = {
            "ok": True,
            "records": selected,
            "total": len(matches),
            "next_offset": next_offset if more else None,
            "truncated": more,
            "snapshot": snapshot,
        }
        rendered = json.dumps(payload, ensure_ascii=False)
        if len(rendered) + 1 <= args.max_chars:
            if more and not selected:
                fail("--max-chars 无法容纳一条结果，请提高上限")
            print(rendered)
            return
        if not selected:
            fail("--max-chars 无法容纳检索结果，请提高上限")
        selected.pop()


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
    active = [item for item in records if item.get("status") in AUTHORITATIVE_STATUSES]
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
    if not args.title.strip() or not args.source.strip():
        fail("title 和 source 不能为空")
    if args.verified_at and not valid_iso_date(args.verified_at):
        fail("verified_at 必须为合法的 YYYY-MM-DD 日期")
    root = knowledge_root(args.vault_root, args.project)
    ensure_initialized(root, args.project)
    body = read_body(args)
    modules = [item.strip() for item in args.module if item.strip()]
    requested_supersedes = [validate_id(item) for item in args.supersedes]
    digest = fingerprint(args.kind, args.title.strip(), body, modules)
    target = root / KIND_DIRS[args.kind] / f"{record_id}.md"

    existing = read_frontmatter(target) if target.exists() else {}
    if args.expected_fingerprint and existing.get("fingerprint") != args.expected_fingerprint:
        fail("现有记录指纹与 --expected-fingerprint 不一致，拒绝覆盖", 3)

    records = collect_records(root)
    records_by_id = {str(item.get("id")): item for item in records}
    if len(records_by_id) != len(records):
        fail("知识库存在重复 ID，请先修复重复记录")
    if record_id in records_by_id and records_by_id[record_id]["path"] != target.relative_to(root).with_suffix("").as_posix():
        fail(f"ID 已被其他分类记录占用：{record_id}")
    existing_supersedes = existing.get("supersedes", [])
    if not isinstance(existing_supersedes, list):
        existing_supersedes = []
    supersedes = list(dict.fromkeys([*existing_supersedes, *requested_supersedes]))
    new_edges = set(requested_supersedes) - set(existing_supersedes)
    if supersedes and args.status not in AUTHORITATIVE_STATUSES and (args.status == "proposed" or new_edges):
        fail("只有已确认的权威记录可以建立替代关系")
    for old_id in supersedes:
        if old_id == record_id:
            fail("记录不能替代自身")
        old = records_by_id.get(old_id)
        if not old:
            fail(f"被替代记录不存在：{old_id}")
        if old.get("type") != args.kind:
            fail(f"被替代记录类型不一致：{old_id}")
        # 在任何落盘前检查新增关系是否回到当前记录。
        pending, visited = [old_id], set()
        while pending:
            ancestor = pending.pop()
            if ancestor == record_id:
                fail("supersedes 将形成环，拒绝写入")
            if ancestor in visited:
                continue
            visited.add(ancestor)
            links = records_by_id.get(ancestor, {}).get("supersedes", [])
            if not isinstance(links, list) or any(not isinstance(value, str) for value in links):
                fail(f"supersedes 格式错误：{ancestor}")
            pending.extend(links)
        if old.get("superseded_by") and old["superseded_by"] != record_id:
            fail(f"记录已被其他记录替代：{old_id}")
    if existing.get("superseded_by") and args.status != "superseded":
        fail("已被替代的记录不能直接恢复为当前事实，请使用新 ID")

    for item in records:
        if item.get("id") == record_id or item.get("id") in supersedes or item.get("status") in HISTORICAL_STATUSES:
            continue
        candidate_body = read_record_content(root / f"{item['path']}.md")
        if candidate_body is None:
            fail(f"无法读取记录正文：{item['path']}")
        if fingerprint(str(item.get("type", "")), str(item.get("title", "")),
                       candidate_body, item.get("module", [])) == digest:
            print(
                json.dumps(
                    {"ok": True, "action": "duplicate", "existing_id": item.get("id")},
                    ensure_ascii=False,
                )
            )
            return

    today = dt.date.today().isoformat()
    created = str(existing.get("created") or today)
    # 编辑记录不等于重新验证；只有显式提供日期才刷新已有记录的验证时间。
    verified_at = args.verified_at or (existing.get("verified_at") if existing else today)
    if not valid_iso_date(verified_at):
        fail("已有记录缺少有效验证日期，请完成复核后显式提供 --verified-at")
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
        f"verified_at: {verified_at}",
        f"supersedes: {json.dumps(supersedes, ensure_ascii=False)}",
        *([f"superseded_by: {scalar(existing['superseded_by'])}"] if existing.get("superseded_by") else []),
        "fingerprint_version: 2",
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
    from memory_inbox import candidate_lock

    root = knowledge_root(args.vault_root, args.project)
    inbox = (root / "收件箱").resolve()
    target = (inbox / args.file).resolve()
    if target.parent != inbox or target.suffix != ".json":
        fail("收件箱文件名不安全")
    with candidate_lock(target):
        try:
            payload = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            fail(f"无法读取收件箱记录：{exc}")
        if not isinstance(payload, dict):
            fail("收件箱记录必须是 JSON 对象")
        version = payload.get("updated_at") or payload.get("created_at")
        if not version or version != args.expected_updated_at:
            fail("候选已更新，请重新读取并审核后再标记", 3)
        payload["status"] = args.status
        payload["processed_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
        atomic_write(target, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"ok": True, "path": str(target), "status": args.status}, ensure_ascii=False))


def command_validate(args: argparse.Namespace) -> None:
    root = knowledge_root(args.vault_root, args.project)
    if not root.is_dir():
        fail("项目知识库尚未初始化")
    records = collect_records(root)
    errors: list[str] = []
    ids: dict[str, str] = {}
    fingerprints: dict[str, str] = {}
    records_by_id = {str(item.get("id", "")): item for item in records}
    for item in records:
        raw_id = item.get("id")
        record_id = str(raw_id or "")
        path = str(item.get("path", ""))
        digest = str(item.get("fingerprint", ""))
        directory = path.split("/", 1)[0]
        expected_type = TYPE_BY_DIRECTORY[directory]
        if not isinstance(raw_id, str) or not SAFE_ID.fullmatch(raw_id):
            errors.append(f"ID 不合法：{record_id} ({path})")
        if record_id in ids:
            errors.append(f"重复 ID：{record_id} ({ids[record_id]}, {path})")
        ids[record_id] = path
        record_type = item.get("type")
        if not isinstance(record_type, str) or record_type != expected_type:
            errors.append(
                f"类型与目录不匹配：{record_id} ({path}，应为 {expected_type}，实际为 {record_type})"
            )
        source = item.get("source")
        if not isinstance(source, str) or not source.strip():
            errors.append(f"source 为空：{record_id}")
        if not valid_iso_date(item.get("verified_at")):
            errors.append(f"verified_at 不是合法日期：{record_id} -> {item.get('verified_at')}")
        record_path = root / f"{path}.md"
        body = read_record_content(record_path)
        modules = item.get("module", [])
        if body is None:
            errors.append(f"无法提取记录正文：{record_id} ({path})")
        elif not isinstance(modules, list):
            errors.append(f"module 不是列表：{record_id}")
        else:
            expected_digest = fingerprint(
                str(item.get("type", "")),
                str(item.get("title", "")),
                body,
                [str(value) for value in modules],
            )
            compatible = {expected_digest}
            version = item.get("fingerprint_version")
            if version in (None, 1):
                compatible.add(fingerprint(str(item.get("type", "")), str(item.get("title", "")), body, modules, legacy=True))
            elif version != 2:
                errors.append(f"未知指纹版本：{record_id} -> {version}")
            if digest not in compatible:
                errors.append(f"内容指纹不匹配：{record_id}")
            if item.get("status") not in HISTORICAL_STATUSES:
                if expected_digest in fingerprints:
                    errors.append(f"重复指纹：{record_id} 与 {fingerprints[expected_digest]}")
                fingerprints[expected_digest] = record_id
        if item.get("status") not in VALID_STATUSES:
            errors.append(f"无效状态：{record_id} -> {item.get('status')}")
        superseded_by = item.get("superseded_by")
        if superseded_by and str(superseded_by) not in records_by_id:
            errors.append(f"superseded_by 目标不存在：{record_id} -> {superseded_by}")
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
    result = {
        "ok": not errors,
        "empty": not records,
        "records": len(records),
        "errors": errors,
    }
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
    module = args.module.strip() if args.module is not None else None
    if module == "":
        fail("--module 不能为空")
    records = select_modules(collect_records(root), [module] if module else [])
    active = [item for item in records if item.get("status") in AUTHORITATIVE_STATUSES]
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
    for (kind, candidate_module), items in grouped.items():
        if len(items) < 2:
            continue
        ordered = sorted(items, key=lambda row: str(row.get("updated", "")), reverse=True)
        candidates.append(
            {
                "type": kind,
                "module": candidate_module,
                "records": len(ordered),
                "sample_ids": [str(item.get("id")) for item in ordered[: args.batch_size]],
                "truncated": len(ordered) > args.batch_size,
            }
        )
    candidates.sort(key=lambda item: int(item["records"]), reverse=True)

    cutoff = dt.date.today() - dt.timedelta(days=args.stale_days)
    stale_ids: list[str] = []
    for item in active:
        verified_at = item.get("verified_at")
        if not valid_iso_date(verified_at):
            fail(f"verified_at 不是合法日期：{item['id']} -> {verified_at}")
        if dt.date.fromisoformat(verified_at) <= cutoff:
            stale_ids.append(str(item["id"]))
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
    if module:
        summary_path = root / "模块摘要" / f"{hashlib.sha256(module.encode('utf-8')).hexdigest()}.md"
    summary_metadata = read_frontmatter(summary_path) if summary_path.exists() else {}
    source_ids = summary_metadata.get("source_records")
    included_history = source_ids if isinstance(source_ids, list) and all(isinstance(value, str) for value in source_ids) else []
    current_fingerprint = active_input_fingerprint(root, records, included_history)
    summary_fingerprint = str(summary_metadata.get("source_fingerprint") or "")
    summary_coverage = str(summary_metadata.get("coverage") or "partial")
    summary_stale = not summary_path.exists() or summary_fingerprint != current_fingerprint
    scope_errors: list[str] = []
    if summary_metadata.get("project") != args.project:
        scope_errors.append("摘要 project 与当前项目不匹配")
    if "module" not in summary_metadata or summary_metadata["module"] != module:
        scope_errors.append("摘要 module 与当前范围不匹配")
    if summary_metadata.get("kind") != "knowledge-summary":
        scope_errors.append("摘要 kind 无效")
    if summary_metadata.get("coverage") not in ("partial", "complete"):
        scope_errors.append("摘要 coverage 缺失或无效")
    source_ids = summary_metadata.get("source_records")
    if not isinstance(source_ids, list) or any(not isinstance(value, str) for value in source_ids):
        scope_errors.append("摘要 source_records 必须是字符串列表")
    else:
        by_id = {str(item["id"]): item for item in records}
        if len(set(source_ids)) != len(source_ids):
            scope_errors.append("摘要 source_records 含重复 ID")
        if any(value not in by_id or by_id[value].get("status") not in AUTHORITATIVE_STATUSES | HISTORICAL_STATUSES for value in source_ids):
            scope_errors.append("摘要引用了不存在、越界或非权威来源")
        if summary_coverage == "complete" and not {str(item["id"]) for item in active}.issubset(source_ids):
            scope_errors.append("完整摘要未覆盖当前全部权威记录")
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
            "path": str(summary_path),
            "module": module,
            "exists": summary_path.exists(),
            "updated": summary_metadata.get("updated"),
            "source_fingerprint": summary_fingerprint,
            "current_fingerprint": current_fingerprint,
            "coverage": summary_coverage,
            "stale": summary_stale,
            "scope_valid": not scope_errors,
            "scope_errors": scope_errors,
            "usable": not summary_stale and summary_coverage == "complete" and not scope_errors,
        },
    }
    if args.summary_only:
        print(json.dumps({"ok": True, "summary": result["summary"]}, ensure_ascii=False))
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--vault-root",
        default=os.environ.get("PROJECT_MEMORY_VAULT"),
        help="Obsidian Vault 根目录；默认读取 PROJECT_MEMORY_VAULT",
    )
    parser.add_argument("--project", required=True, help="项目名称")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init", help="初始化知识库")
    init_parser.set_defaults(func=command_init)

    search = subparsers.add_parser("search", help="按关键词和模块检索全部正式记录，分页返回相关结果")
    search.add_argument("--query", default="")
    search.add_argument("--match", choices=("any", "all"), default="any", help="匹配任一或全部关键词")
    search.add_argument("--expected-snapshot", help="续页时传入第一页 snapshot，发现变化即停止")
    search.add_argument("--module", action="append", default=[])
    search.add_argument("--limit", type=int, default=3)
    search.add_argument("--offset", type=int, default=0)
    search.add_argument("--max-chars", type=int, default=6000)
    search.set_defaults(func=command_search)

    upsert = subparsers.add_parser("upsert", help="创建或更新原子记录")
    upsert.add_argument("--kind", required=True, choices=sorted(KIND_DIRS))
    upsert.add_argument("--id", required=True)
    upsert.add_argument("--title", required=True)
    body_group = upsert.add_mutually_exclusive_group(required=True)
    body_group.add_argument("--body")
    body_group.add_argument("--body-file")
    upsert.add_argument("--status", required=True, choices=sorted(VALID_STATUSES))
    upsert.add_argument("--source", required=True)
    upsert.add_argument("--verified-at", help="复核日期；更新时省略则保留原日期，新建时默认当天")
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
    inbox.add_argument("--expected-updated-at", required=True,
                       help="审核前读取的 updated_at；旧候选没有该字段时使用 created_at")
    inbox.set_defaults(func=command_mark_inbox)

    validate = subparsers.add_parser("validate", help="检查重复和元数据错误")
    validate.set_defaults(func=command_validate)

    rebuild = subparsers.add_parser("rebuild-indexes", help="重建活跃索引和历史索引")
    rebuild.set_defaults(func=command_rebuild_indexes)

    audit = subparsers.add_parser("maintenance-audit", help="输出知识库维护审计摘要")
    audit.add_argument("--module", help="只审计指定模块、global 和未分类旧记录")
    audit.add_argument("--summary-only", action="store_true", help="只输出摘要可用性，省略维护统计与候选")
    audit.add_argument("--stale-days", type=int, default=180)
    audit.add_argument("--batch-size", type=int, default=12)
    audit.add_argument("--max-groups", type=int, default=20)
    audit.set_defaults(func=command_maintenance_audit)
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    if not args.vault_root:
        fail("缺少 --vault-root，且未设置 PROJECT_MEMORY_VAULT")
    args.func(args)


if __name__ == "__main__":
    main()
