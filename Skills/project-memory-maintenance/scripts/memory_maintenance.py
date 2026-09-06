#!/usr/bin/env python3
"""审计、总结并无损整理项目知识库。"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
from itertools import combinations
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
RETIRED_STATUSES = {"deprecated", "superseded"}
AUTHORITATIVE_STATUSES = {"active", "accepted", "fixed"}
ACTIVE_INDEX_MAX_RECORDS = 60
ACTIVE_INDEX_MAX_CHARS = 6000
REQUIRED_FIELDS = {"id", "type", "status", "title", "source", "verified_at", "fingerprint"}
SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
FRONTMATTER_END = "\n---\n"


def fail(message: str, code: int = 2) -> None:
    print(json.dumps({"ok": False, "error": message}, ensure_ascii=False), file=sys.stderr)
    raise SystemExit(code)


def scalar(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


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


def read_document(path: Path) -> tuple[dict[str, Any], str, str]:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        fail(f"无法读取 {path}：{exc}")
    if not text.startswith("---\n"):
        return {}, text, text
    end = text.find(FRONTMATTER_END, 4)
    if end < 0:
        return {}, text, text
    frontmatter = text[4:end]
    metadata: dict[str, Any] = {}
    for line in frontmatter.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        metadata[key.strip()] = parse_scalar(value.strip())
    body = text[end + len(FRONTMATTER_END) :]
    return metadata, body, text


def record_content(document_body: str) -> str:
    marker = "\n## 内容\n\n"
    if marker in document_body:
        return document_body.split(marker, 1)[1].strip()
    return document_body.strip()


def collect_records(root: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for expected_type, directory in KIND_DIRS.items():
        folder = root / directory
        if not folder.exists():
            continue
        for path in sorted(folder.glob("*.md")):
            metadata, document_body, raw = read_document(path)
            if not metadata.get("id"):
                continue
            records.append(
                {
                    "id": str(metadata.get("id")),
                    "type": str(metadata.get("type") or expected_type),
                    "status": str(metadata.get("status") or ""),
                    "title": str(metadata.get("title") or ""),
                    "module": metadata.get("module") if isinstance(metadata.get("module"), list) else [],
                    "source": str(metadata.get("source") or ""),
                    "verified_at": str(metadata.get("verified_at") or ""),
                    "fingerprint": str(metadata.get("fingerprint") or ""),
                    "metadata": metadata,
                    "body": record_content(document_body),
                    "raw": raw,
                    "path": path,
                    "relative_path": path.relative_to(root).with_suffix("").as_posix(),
                }
            )
    return records


def normalize(value: str) -> str:
    return " ".join(value.replace("\r\n", "\n").replace("\r", "\n").split()).casefold()


def select_module(records: list[dict[str, Any]], module: str | None) -> list[dict[str, Any]]:
    """与普通召回使用相同的模块范围，兼容尚未分类的旧记录。"""
    if module is None:
        return records
    return [
        record for record in records
        if not record["module"] or "global" in record["module"] or module in record["module"]
    ]


def summary_path(root: Path, module: str | None) -> Path:
    if module is None:
        return root / "知识摘要.md"
    return root / "模块摘要" / f"{hashlib.sha256(module.encode('utf-8')).hexdigest()}.md"


def features(value: str) -> set[str]:
    normalized = normalize(value)
    latin = re.findall(r"[a-z0-9_.-]+", normalized)
    han = "".join(re.findall(r"[\u3400-\u9fff]", normalized))
    han_grams = [han[index : index + 2] for index in range(max(0, len(han) - 1))]
    return set(latin + han_grams)


def feature_similarity(
    left_features: set[str], right_features: set[str], exact_match: bool = False
) -> float:
    if not left_features or not right_features:
        return 1.0 if exact_match else 0.0
    return len(left_features & right_features) / len(left_features | right_features)


def module_similarity(left: list[str], right: list[str]) -> float:
    left_set = {normalize(item) for item in left if normalize(item)}
    right_set = {normalize(item) for item in right if normalize(item)}
    if not left_set or not right_set:
        return 0.0
    return len(left_set & right_set) / len(left_set | right_set)


def record_digest(record: dict[str, Any]) -> str:
    payload = json.dumps(
        {
            "type": record["type"],
            "title": normalize(record["title"]),
            "body": normalize(record["body"]),
            "module": sorted(normalize(item) for item in record["module"]),
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def active_input_fingerprint(records: list[dict[str, Any]]) -> str:
    payload = [
        {
            "id": record["id"],
            "status": record["status"],
            "fingerprint": record_digest(record),
            "updated": record["metadata"].get("updated", ""),
            "source": record["source"],
            "verified_at": record["verified_at"],
        }
        for record in sorted(records, key=lambda item: item["id"])
        if record["status"] in AUTHORITATIVE_STATUSES
    ]
    rendered = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(rendered.encode("utf-8")).hexdigest()


def parse_date(value: str) -> dt.date | None:
    try:
        return dt.date.fromisoformat(value[:10])
    except (TypeError, ValueError):
        return None


def inbox_stats(root: Path, max_samples: int) -> dict[str, Any]:
    counts: dict[str, int] = {}
    invalid: list[str] = []
    inbox = root / "收件箱"
    if inbox.exists():
        for path in sorted(inbox.glob("*.json")):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                status = str(payload.get("status") or "unknown")
                counts[status] = counts.get(status, 0) + 1
            except (OSError, UnicodeError, json.JSONDecodeError):
                invalid.append(path.name)
    return {
        "counts": counts,
        "invalid_count": len(invalid),
        "invalid": invalid[:max_samples],
    }


def command_audit(args: argparse.Namespace) -> None:
    root = knowledge_root(args.vault_root, args.project)
    records = select_module(collect_records(root), args.module)
    if len(records) > args.max_records:
        fail(f"记录数 {len(records)} 超过 --max-records={args.max_records}，请缩小范围")

    digest_groups: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        digest_groups.setdefault(record_digest(record), []).append(record)
    exact_duplicates = [
        {
            "fingerprint": digest,
            "ids": sorted(
                record["id"]
                for record in group
                if record["status"] not in RETIRED_STATUSES
            ),
        }
        for digest, group in sorted(digest_groups.items())
        if sum(record["status"] not in RETIRED_STATUSES for record in group) > 1
    ]
    historical_duplicate_groups = sum(
        len(group) > 1
        and sum(record["status"] not in RETIRED_STATUSES for record in group) <= 1
        for group in digest_groups.values()
    )
    exact_pairs = {
        frozenset(pair)
        for group in exact_duplicates
        for pair in combinations(group["ids"], 2)
    }

    near_duplicates: list[dict[str, Any]] = []
    conflicts: list[dict[str, Any]] = []
    live_records = [record for record in records if record["status"] not in RETIRED_STATUSES]
    prepared = [
        {
            "record": record,
            "title_features": features(record["title"]),
            "body_features": features(record["body"]),
        }
        for record in live_records
    ]
    for left_item, right_item in combinations(prepared, 2):
        left = left_item["record"]
        right = right_item["record"]
        if left["type"] != right["type"] or frozenset((left["id"], right["id"])) in exact_pairs:
            continue
        same_title = normalize(left["title"]) == normalize(right["title"])
        title_score = feature_similarity(
            left_item["title_features"], right_item["title_features"], same_title
        )
        body_score = feature_similarity(
            left_item["body_features"],
            right_item["body_features"],
            normalize(left["body"]) == normalize(right["body"]),
        )
        module_score = module_similarity(left["module"], right["module"])
        score = 0.55 * title_score + 0.35 * body_score + 0.10 * module_score
        candidate = {
            "ids": [left["id"], right["id"]],
            "score": round(score, 3),
            "title_score": round(title_score, 3),
            "body_score": round(body_score, 3),
            "same_title": same_title,
        }
        if same_title and record_digest(left) != record_digest(right):
            conflicts.append(candidate)
        elif score >= args.similarity_threshold:
            near_duplicates.append(candidate)

    today = dt.date.today()
    stale: list[dict[str, Any]] = []
    missing_fields: list[dict[str, Any]] = []
    for record in records:
        missing = sorted(field for field in REQUIRED_FIELDS if not record["metadata"].get(field))
        if missing:
            missing_fields.append({"id": record["id"], "missing": missing})
        verified = parse_date(record["verified_at"])
        if (
            verified
            and record["status"] not in RETIRED_STATUSES
            and (today - verified).days >= args.stale_days
        ):
            stale.append(
                {
                    "id": record["id"],
                    "verified_at": record["verified_at"],
                    "age_days": (today - verified).days,
                }
            )

    current_input_fingerprint = active_input_fingerprint(records)
    target_summary = summary_path(root, args.module)
    summary_metadata = read_document(target_summary)[0] if target_summary.exists() else {}
    summary_fingerprint = str(summary_metadata.get("source_fingerprint") or "")
    summary_coverage = str(summary_metadata.get("coverage") or "partial")
    summary_stale = (
        not target_summary.exists() or summary_fingerprint != current_input_fingerprint
    )
    result = {
        "ok": not missing_fields,
        "root": str(root),
        "stats": {
            "records": len(records),
            "live": len(live_records),
            "retired": len(records) - len(live_records),
            "exact_duplicate_groups": len(exact_duplicates),
            "historical_duplicate_groups": historical_duplicate_groups,
            "near_duplicate_pairs": len(near_duplicates),
            "same_title_conflicts": len(conflicts),
            "stale": len(stale),
        },
        "exact_duplicates": exact_duplicates[: args.max_candidates],
        "near_duplicates": sorted(
            near_duplicates, key=lambda item: item["score"], reverse=True
        )[: args.max_candidates],
        "same_title_conflicts": conflicts[: args.max_candidates],
        "stale": sorted(stale, key=lambda item: item["age_days"], reverse=True)[
            : args.max_candidates
        ],
        "missing_fields": missing_fields[: args.max_candidates],
        "inbox": inbox_stats(root, args.max_candidates),
        "summary": {
            "path": str(target_summary),
            "module": args.module,
            "exists": target_summary.exists(),
            "updated": summary_metadata.get("updated"),
            "source_records": summary_metadata.get("source_records", []),
            "source_fingerprint": summary_fingerprint,
            "current_fingerprint": current_input_fingerprint,
            "coverage": summary_coverage,
            "stale": summary_stale,
            "usable": not summary_stale and summary_coverage == "complete",
        },
        "output_truncated_at": args.max_candidates,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


def update_frontmatter(raw: str, updates: dict[str, Any]) -> str:
    if not raw.startswith("---\n"):
        fail("记录缺少有效 frontmatter")
    end = raw.find(FRONTMATTER_END, 4)
    if end < 0:
        fail("记录缺少有效 frontmatter 结束标记")
    lines = raw[4:end].splitlines()
    replaced: set[str] = set()
    rendered: list[str] = []
    for line in lines:
        key = line.split(":", 1)[0].strip() if ":" in line else ""
        if key in updates:
            rendered.append(f"{key}: {scalar(updates[key])}")
            replaced.add(key)
        else:
            rendered.append(line)
    for key, value in updates.items():
        if key not in replaced:
            rendered.append(f"{key}: {scalar(value)}")
    return "---\n" + "\n".join(rendered) + FRONTMATTER_END + raw[end + len(FRONTMATTER_END) :]


def render_index(project: str, records: list[dict[str, Any]]) -> str:
    active = [record for record in records if record["status"] in AUTHORITATIVE_STATUSES]
    historical_count = sum(record["status"] in RETIRED_STATUSES for record in records)
    lines = [
        "---",
        f"project: {scalar(project)}",
        f"updated: {dt.date.today().isoformat()}",
        "---",
        "",
        f"# {project} 知识索引",
        "",
        "> 仅列出活跃记录；由记忆工具生成，不要手工追加反向链接。",
        f"> 历史记录 {historical_count} 条；仅在追溯历史时读取 [[历史索引]]。",
        (
            f"> 活跃记录 {len(active)} 条；入口最多展示 {ACTIVE_INDEX_MAX_RECORDS} 条，"
            f"且不超过 {ACTIVE_INDEX_MAX_CHARS} 字符。"
        ),
        "",
        "| ID | 类型 | 状态 | 标题 | 最近验证 |",
        "|---|---|---|---|---|",
    ]
    rows: list[str] = []
    ordered = sorted(
        active, key=lambda row: str(row["metadata"].get("updated", "")), reverse=True
    )
    overflow_note = "> 未展示的活跃记录请按关键词搜索分类目录，不要加载整个知识库。"
    for item in ordered[:ACTIVE_INDEX_MAX_RECORDS]:
        title = item["title"].replace("|", "\\|")[:120]
        row = (
            f"| [[{item['relative_path']}|{item['id']}]] | {item['type']} | "
            f"{item['status']} | {title} | {item['verified_at']} |"
        )
        candidate = "\n".join([*lines, *rows, row, "", overflow_note]) + "\n"
        if len(candidate) > ACTIVE_INDEX_MAX_CHARS:
            break
        rows.append(row)
    if len(rows) < len(active):
        rows.extend(["", overflow_note])
    return "\n".join([*lines, *rows]) + "\n"


def render_history_index(project: str, records: list[dict[str, Any]]) -> str:
    historical = [record for record in records if record["status"] in RETIRED_STATUSES]
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
    for item in sorted(
        historical,
        key=lambda row: str(row["metadata"].get("updated", "")),
        reverse=True,
    ):
        title = item["title"].replace("|", "\\|")
        lines.append(
            f"| [[{item['relative_path']}|{item['id']}]] | {item['type']} | "
            f"{item['status']} | {title} | {item['verified_at']} |"
        )
    return "\n".join(lines) + "\n"


def command_supersede(args: argparse.Namespace) -> None:
    root = knowledge_root(args.vault_root, args.project)
    records = collect_records(root)
    by_id = {record["id"]: record for record in records}
    canonical_id = validate_id(args.canonical)
    duplicate_ids = list(dict.fromkeys(validate_id(value) for value in args.duplicate))
    if canonical_id in duplicate_ids:
        fail("保留记录不能同时作为重复记录")
    missing = [record_id for record_id in [canonical_id, *duplicate_ids] if record_id not in by_id]
    if missing:
        fail(f"找不到记录：{', '.join(missing)}")
    canonical = by_id[canonical_id]
    if canonical["status"] in RETIRED_STATUSES:
        fail("保留记录已经停用")
    for record_id in duplicate_ids:
        if by_id[record_id]["type"] != canonical["type"]:
            fail(f"{record_id} 与保留记录类型不同")

    plan = {
        "canonical": canonical_id,
        "duplicates": duplicate_ids,
        "reason": args.reason,
        "apply": args.apply,
    }
    if not args.apply:
        print(json.dumps({"ok": True, "action": "preview", **plan}, ensure_ascii=False, indent=2))
        return

    today = dt.date.today().isoformat()
    supersedes = canonical["metadata"].get("supersedes")
    if not isinstance(supersedes, list):
        supersedes = []
    canonical_updates = {
        "supersedes": list(dict.fromkeys([*supersedes, *duplicate_ids])),
        "updated": today,
    }
    atomic_write(canonical["path"], update_frontmatter(canonical["raw"], canonical_updates))
    for record_id in duplicate_ids:
        record = by_id[record_id]
        updates = {
            "status": "superseded",
            "superseded_by": canonical_id,
            "curation_note": args.reason,
            "updated": today,
        }
        atomic_write(record["path"], update_frontmatter(record["raw"], updates))
    updated_records = collect_records(root)
    atomic_write(root / "索引.md", render_index(args.project, updated_records))
    atomic_write(root / "历史索引.md", render_history_index(args.project, updated_records))
    print(json.dumps({"ok": True, "action": "superseded", **plan}, ensure_ascii=False, indent=2))


def command_write_summary(args: argparse.Namespace) -> None:
    root = knowledge_root(args.vault_root, args.project)
    records = select_module(collect_records(root), args.module)
    by_id = {record["id"]: record for record in records}
    source_ids = list(dict.fromkeys(validate_id(value) for value in args.source_id))
    try:
        body = Path(args.body_file).read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError) as exc:
        fail(f"无法读取摘要正文：{exc}")
    if len(body) > args.max_chars or len(body.splitlines()) > args.max_lines:
        fail(f"摘要超过限制：最多 {args.max_chars} 字符、{args.max_lines} 行")
    if records and not source_ids:
        fail("知识库非空时必须提供至少一个 --source-id")
    missing = [record_id for record_id in source_ids if record_id not in by_id]
    if missing:
        fail(f"摘要引用了不存在或不属于当前模块范围的记录：{', '.join(missing)}")
    proposed = [record_id for record_id in source_ids if by_id[record_id]["status"] == "proposed"]
    if proposed:
        fail(f"摘要不能引用未确认提议：{', '.join(proposed)}")
    retired = [record_id for record_id in source_ids if by_id[record_id]["status"] in RETIRED_STATUSES]
    if retired and not args.include_retired:
        fail(f"摘要默认不能引用停用记录：{', '.join(retired)}")
    uncited = [record_id for record_id in source_ids if record_id not in body]
    if uncited:
        fail(f"摘要正文未出现这些来源 ID：{', '.join(uncited)}")
    active_ids = {
        record["id"] for record in records if record["status"] in AUTHORITATIVE_STATUSES
    }
    if args.coverage == "complete":
        missing_coverage = sorted(active_ids - set(source_ids))
        if missing_coverage:
            fail(f"完整摘要未覆盖活跃记录：{', '.join(missing_coverage)}")

    active_records = [record for record in records if record["status"] in AUTHORITATIVE_STATUSES]
    source_fingerprint = active_input_fingerprint(records)
    content = (
        "---\n"
        f"project: {scalar(args.project)}\n"
        "kind: knowledge-summary\n"
        f"module: {scalar(args.module)}\n"
        f"updated: {dt.date.today().isoformat()}\n"
        f"source_records: {scalar(source_ids)}\n"
        f"record_count: {len(active_records)}\n"
        f"source_fingerprint: {scalar(source_fingerprint)}\n"
        f"coverage: {scalar(args.coverage)}\n"
        "---\n\n"
        f"# {args.project} 知识摘要\n\n"
        "> 这是导航摘要；实现和决策仍以当前代码、测试及链接的原子记录为准。\n\n"
        f"{body}\n"
    )
    target = summary_path(root, args.module)
    atomic_write(target, content)
    print(
        json.dumps(
            {
                "ok": True,
                "path": str(target),
                "module": args.module,
                "source_records": source_ids,
                "source_fingerprint": source_fingerprint,
                "coverage": args.coverage,
            },
            ensure_ascii=False,
        )
    )


def command_archive_inbox(args: argparse.Namespace) -> None:
    root = knowledge_root(args.vault_root, args.project)
    inbox = root / "收件箱"
    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=args.older_than_days)
    candidates: list[tuple[Path, dt.datetime]] = []
    if inbox.exists():
        for path in sorted(inbox.glob("*.json")):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError):
                continue
            if payload.get("status") not in {"processed", "ignored"}:
                continue
            raw_date = str(payload.get("processed_at") or payload.get("created_at") or "")
            try:
                processed_at = dt.datetime.fromisoformat(raw_date.replace("Z", "+00:00"))
                if processed_at.tzinfo is None:
                    processed_at = processed_at.replace(tzinfo=dt.timezone.utc)
            except ValueError:
                continue
            if processed_at <= cutoff:
                candidates.append((path, processed_at))

    moved: list[str] = []
    conflicts: list[str] = []
    if args.apply:
        for path, processed_at in candidates:
            target = inbox / "归档" / str(processed_at.year) / path.name
            if target.exists():
                conflicts.append(path.name)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(path), str(target))
            moved.append(str(target))
    print(
        json.dumps(
            {
                "ok": not conflicts,
                "action": "archived" if args.apply else "preview",
                "candidates": [path.name for path, _ in candidates],
                "moved": moved,
                "conflicts": conflicts,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--vault-root",
        default=os.environ.get("CODEX_MEMORY_VAULT"),
        help="Obsidian Vault 根目录；默认读取 CODEX_MEMORY_VAULT",
    )
    parser.add_argument("--project", required=True, help="项目名称")
    subparsers = parser.add_subparsers(dest="command", required=True)

    audit = subparsers.add_parser("audit", help="盘点重复、冲突、陈旧知识和收件箱")
    audit.add_argument("--module", help="只审计指定模块、global 和未分类旧记录")
    audit.add_argument("--similarity-threshold", type=float, default=0.72)
    audit.add_argument("--stale-days", type=int, default=180)
    audit.add_argument("--max-records", type=int, default=2000)
    audit.add_argument("--max-candidates", type=int, default=50)
    audit.set_defaults(func=command_audit)

    supersede = subparsers.add_parser("supersede", help="无损标记重复记录为已替代")
    supersede.add_argument("--canonical", required=True)
    supersede.add_argument("--duplicate", action="append", required=True)
    supersede.add_argument("--reason", required=True)
    supersede.add_argument("--apply", action="store_true")
    supersede.set_defaults(func=command_supersede)

    summary = subparsers.add_parser("write-summary", help="写入带来源记录的知识摘要")
    summary.add_argument("--module", help="为指定模块、global 和未分类旧记录生成摘要")
    summary.add_argument("--body-file", required=True)
    summary.add_argument("--source-id", action="append", default=[])
    summary.add_argument("--include-retired", action="store_true")
    summary.add_argument("--coverage", choices=["partial", "complete"], default="partial")
    summary.add_argument("--max-lines", type=int, default=80)
    summary.add_argument("--max-chars", type=int, default=6000)
    summary.set_defaults(func=command_write_summary)

    archive = subparsers.add_parser("archive-inbox", help="归档已处理的旧收件箱记录")
    archive.add_argument("--older-than-days", type=int, default=30)
    archive.add_argument("--apply", action="store_true")
    archive.set_defaults(func=command_archive_inbox)
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    if not args.vault_root:
        fail("缺少 --vault-root，且未设置 CODEX_MEMORY_VAULT")
    if getattr(args, "module", None) is not None:
        args.module = args.module.strip()
        if not args.module:
            fail("--module 不能为空")
    threshold = getattr(args, "similarity_threshold", 0.72)
    if threshold < 0 or threshold > 1:
        fail("--similarity-threshold 必须在 0 到 1 之间")
    if getattr(args, "stale_days", 0) < 0 or getattr(args, "older_than_days", 0) < 0:
        fail("天数不能为负数")
    if getattr(args, "max_records", 1) < 1:
        fail("--max-records 必须大于 0")
    if getattr(args, "max_candidates", 1) < 1:
        fail("--max-candidates 必须大于 0")
    if getattr(args, "max_lines", 1) < 1 or getattr(args, "max_chars", 1) < 1:
        fail("摘要长度限制必须大于 0")
    args.func(args)


if __name__ == "__main__":
    main()
