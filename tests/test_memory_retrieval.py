from __future__ import annotations

import hashlib
import datetime as dt
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
STORE = REPO_ROOT / "Skills" / "project-memory" / "scripts" / "memory_store.py"
MAINTENANCE = (
    REPO_ROOT
    / "Skills"
    / "project-memory-maintenance"
    / "scripts"
    / "memory_maintenance.py"
)

KIND_DIRS = {
    "decision": "决策",
    "bug": "Bug",
    "api": "API",
    "architecture": "架构",
    "convention": "约定",
    "environment": "环境",
}
SEARCH_RECORD_FIELDS = {
    "id",
    "title",
    "status",
    "module",
    "path",
    "source",
    "verified_at",
    "excerpt",
}


def normalize(value: str) -> str:
    return " ".join(value.replace("\r\n", "\n").replace("\r", "\n").split()).casefold()


def record_fingerprint(kind: str, title: str, body: str, modules: list[str]) -> str:
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


class MemoryRetrievalTests(unittest.TestCase):
    def run_store(
        self,
        vault: Path,
        project: str,
        *args: str,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        return subprocess.run(
            [
                sys.executable,
                str(STORE),
                "--vault-root",
                str(vault),
                "--project",
                project,
                *args,
            ],
            check=check,
            text=True,
            capture_output=True,
            env=env,
        )

    def run_maintenance(
        self,
        vault: Path,
        project: str,
        *args: str,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        return subprocess.run(
            [
                sys.executable,
                str(MAINTENANCE),
                "--vault-root",
                str(vault),
                "--project",
                project,
                *args,
            ],
            check=check,
            text=True,
            capture_output=True,
            env=env,
        )

    def write_record(
        self,
        root: Path,
        *,
        kind: str,
        record_id: str,
        title: str,
        body: str,
        status: str = "active",
        modules: list[str] | None = None,
        source: str = "test-source",
        updated: str = "2026-09-05",
        verified_at: str | None = None,
    ) -> Path:
        if verified_at is None:
            verified_at = updated
        module_line = ""
        if modules is not None:
            module_line = f"module: {json.dumps(modules, ensure_ascii=False)}\n"
        digest = record_fingerprint(kind, title, body, modules or [])
        target = root / KIND_DIRS[kind] / f"{record_id}.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            "---\n"
            f"id: {json.dumps(record_id, ensure_ascii=False)}\n"
            f"type: {json.dumps(kind, ensure_ascii=False)}\n"
            f"status: {json.dumps(status, ensure_ascii=False)}\n"
            f"title: {json.dumps(title, ensure_ascii=False)}\n"
            f"project: {json.dumps(root.parent.name, ensure_ascii=False)}\n"
            f"{module_line}"
            f"source: {json.dumps(source, ensure_ascii=False)}\n"
            f"created: {json.dumps(updated, ensure_ascii=False)}\n"
            f"updated: {json.dumps(updated, ensure_ascii=False)}\n"
            f"verified_at: {json.dumps(verified_at, ensure_ascii=False)}\n"
            "supersedes: []\n"
            f"fingerprint: {json.dumps(digest, ensure_ascii=False)}\n"
            "---\n\n"
            f"# {record_id}: {title}\n\n"
            "## 内容\n\n"
            f"{body}\n",
            encoding="utf-8",
        )
        return target

    def upsert(
        self,
        vault: Path,
        project: str,
        *,
        kind: str,
        record_id: str,
        title: str,
        body: str,
        status: str = "active",
        modules: list[str] | None = None,
        source: str = "test-source",
    ) -> dict[str, Any]:
        args = [
            "upsert",
            "--kind",
            kind,
            "--id",
            record_id,
            "--title",
            title,
            "--body",
            body,
            "--status",
            status,
            "--source",
            source,
        ]
        for module in modules or []:
            args.extend(["--module", module])
        return json.loads(self.run_store(vault, project, *args).stdout)

    def init_vault(self, vault: Path, project: str) -> Path:
        self.run_store(vault, project, "init")
        return vault / project / "知识库"

    def search(
        self,
        vault: Path,
        project: str,
        *args: str,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        return self.run_store(vault, project, "search", *args, check=check)

    def assert_search_record_shape(self, record: dict[str, Any]) -> None:
        self.assertTrue(SEARCH_RECORD_FIELDS <= set(record))
        self.assertIsInstance(record["module"], list)
        for field in SEARCH_RECORD_FIELDS - {"module"}:
            self.assertIsInstance(record[field], str)

    def test_search_requires_scope_and_excludes_non_authoritative_statuses(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            vault = Path(temp) / "vault"
            project = "检索状态测试"
            root = self.init_vault(vault, project)

            allowed = {
                "DEC-search-active": ("decision", "active"),
                "BUG-search-accepted": ("bug", "accepted"),
                "API-search-fixed": ("api", "fixed"),
                "ARCH-search-active": ("architecture", "active"),
                "CONV-search-accepted": ("convention", "accepted"),
                "ENV-search-fixed": ("environment", "fixed"),
            }
            excluded = {
                "DEC-search-proposed": ("decision", "proposed"),
                "BUG-search-deprecated": ("bug", "deprecated"),
                "API-search-superseded": ("api", "superseded"),
            }
            for record_id, (kind, status) in {**allowed, **excluded}.items():
                self.write_record(
                    root,
                    kind=kind,
                    record_id=record_id,
                    title=f"状态检索 {record_id}",
                    body=f"status-probe 正文 {record_id}",
                    status=status,
                    source=f"status-probe-source-{record_id}",
                )
            self.run_store(vault, project, "rebuild-indexes")

            result = json.loads(
                self.search(vault, project, "--query", "status-probe", "--limit", "20").stdout
            )
            self.assertTrue(result["ok"])
            self.assertEqual(result["total"], len(allowed))
            self.assertEqual(
                {record["id"] for record in result["records"]}, set(allowed)
            )
            for record in result["records"]:
                self.assert_search_record_shape(record)
                self.assertIn(record["status"], {"active", "accepted", "fixed"})

            missing_scope = self.search(
                vault, project, "--query", "", check=False
            )
            self.assertNotEqual(missing_scope.returncode, 0)

    def test_search_finds_hidden_records_across_categories_and_matches_query_terms_with_or(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            vault = Path(temp) / "vault"
            project = "检索字段测试"
            root = self.init_vault(vault, project)

            # 该记录故意排在首页 60 条之后；召回入口应直接搜索正式分类目录。
            for index in range(64):
                self.write_record(
                    root,
                    kind="convention",
                    record_id=f"CONV-hidden-filler-{index:03d}",
                    title=f"无关索引填充 {index:03d}",
                    body=f"index filler {index:03d}",
                    updated="2026-09-05",
                )
            self.write_record(
                root,
                kind="convention",
                record_id="CONV-hidden-critical",
                title="旧版关键召回规则",
                body="ancient-retrieval 记录不在首页，但仍是有效事实。",
                source="source:old-memory-store.py:42",
                updated="2024-01-02",
            )
            self.run_store(vault, project, "rebuild-indexes")
            index = (root / "索引.md").read_text(encoding="utf-8")
            self.assertNotIn("CONV-hidden-critical", index)

            hidden = json.loads(
                self.search(
                    vault, project, "--query", "ancient-retrieval", "--limit", "5"
                ).stdout
            )
            self.assertEqual(
                [record["id"] for record in hidden["records"]],
                ["CONV-hidden-critical"],
            )

            field_records = {
                "CONV-or-title": {
                    "title": "alpha 标题命中",
                    "body": "只有普通正文",
                    "source": "field-title",
                    "modules": ["field-none"],
                },
                "CONV-or-id-beta": {
                    "title": "普通标题",
                    "body": "只有普通正文",
                    "source": "field-id",
                    "modules": ["field-none"],
                },
                "CONV-or-source": {
                    "title": "普通标题",
                    "body": "只有普通正文",
                    "source": "beta 来源命中",
                    "modules": ["field-none"],
                },
                "CONV-or-body": {
                    "title": "普通标题",
                    "body": "正文 alpha 命中",
                    "source": "field-body",
                    "modules": ["field-none"],
                },
                "CONV-or-module": {
                    "title": "普通标题",
                    "body": "只有普通正文",
                    "source": "field-module",
                    "modules": ["module-beta"],
                },
                "CONV-or-high-relevance": {
                    "title": "alpha beta 双词高相关",
                    "body": "正文同时出现 alpha 和 beta",
                    "source": "field-high",
                    "modules": ["field-high"],
                },
            }
            for index, (record_id, values) in enumerate(field_records.items()):
                self.write_record(
                    root,
                    kind="convention",
                    record_id=record_id,
                    title=values["title"],
                    body=values["body"],
                    source=values["source"],
                    modules=values["modules"],
                    # 高相关记录更旧，便于验证相关性排序优先于时间排序。
                    updated="2026-08-01" if record_id == "CONV-or-high-relevance" else f"2026-09-{index + 1:02d}",
                )
            terms = json.loads(
                self.search(
                    vault,
                    project,
                    "--query",
                    "alpha beta",
                    "--limit",
                    "20",
                ).stdout
            )
            expected = set(field_records)
            self.assertEqual({record["id"] for record in terms["records"]}, expected)
            self.assertEqual(terms["total"], len(expected))
            self.assertEqual(terms["records"][0]["id"], "CONV-or-high-relevance")

    def test_module_filter_includes_global_and_legacy_records_but_excludes_unrelated_and_proposed(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            vault = Path(temp) / "vault"
            project = "检索模块测试"
            root = self.init_vault(vault, project)
            self.write_record(
                root,
                kind="architecture",
                record_id="ARCH-module-target",
                title="memory 模块规则",
                body="module-scope target",
                modules=["memory"],
            )
            self.write_record(
                root,
                kind="decision",
                record_id="DEC-global-rule",
                title="全局规则",
                body="module-scope global",
                modules=["global"],
            )
            self.write_record(
                root,
                kind="bug",
                record_id="BUG-legacy-no-module",
                title="旧记录无模块字段",
                body="module-scope legacy",
                modules=None,
            )
            self.write_record(
                root,
                kind="api",
                record_id="API-unrelated-module",
                title="other 模块规则",
                body="module-scope unrelated",
                modules=["other"],
            )
            self.write_record(
                root,
                kind="convention",
                record_id="CONV-proposed-memory",
                title="memory 待确认规则",
                body="module-scope proposed",
                status="proposed",
                modules=["memory"],
            )

            result = json.loads(
                self.search(vault, project, "--module", "memory", "--limit", "20").stdout
            )
            self.assertEqual(
                {record["id"] for record in result["records"]},
                {
                    "ARCH-module-target",
                    "DEC-global-rule",
                    "BUG-legacy-no-module",
                },
            )
            self.assertEqual(result["total"], 3)
            review_flags = {
                record["id"]: record["scope_needs_review"]
                for record in result["records"]
            }
            self.assertTrue(review_flags["BUG-legacy-no-module"])
            self.assertFalse(review_flags["ARCH-module-target"])
            self.assertFalse(review_flags["DEC-global-rule"])

    def test_search_paginates_default_three_results_and_respects_whole_json_character_limit(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            vault = Path(temp) / "vault"
            project = "检索分页测试"
            root = self.init_vault(vault, project)
            for index in range(8):
                self.write_record(
                    root,
                    kind="convention",
                    record_id=f"CONV-page-{index:02d}",
                    title=f"分页记录 {index:02d}",
                    body=f"page-token 正文 {index:02d}",
                    modules=["memory"],
                )

            first = json.loads(self.search(vault, project, "--query", "page-token").stdout)
            self.assertEqual(len(first["records"]), 3)
            self.assertEqual(first["total"], 8)
            self.assertEqual(first["next_offset"], 3)
            self.assertIsInstance(first["truncated"], bool)

            page_ids: list[str] = []
            offset = 0
            for _ in range(10):
                page = json.loads(
                    self.search(
                        vault,
                        project,
                        "--query",
                        "page-token",
                        "--limit",
                        "3",
                        "--offset",
                        str(offset),
                    ).stdout
                )
                self.assertLessEqual(len(page["records"]), 3)
                page_ids.extend(record["id"] for record in page["records"])
                next_offset = page["next_offset"]
                self.assertIsInstance(page["truncated"], bool)
                if next_offset is None:
                    break
                self.assertGreater(next_offset, offset)
                offset = next_offset
            else:
                self.fail("分页没有在有限页数内结束")
            self.assertEqual(len(page_ids), 8)
            self.assertEqual(len(set(page_ids)), 8)

            capped_process = self.search(
                vault,
                project,
                "--query",
                "page-token",
                "--limit",
                "8",
                "--max-chars",
                "500",
            )
            capped = json.loads(capped_process.stdout)
            self.assertLessEqual(len(capped_process.stdout.rstrip("\r\n")), 500)
            self.assertTrue(capped["truncated"])
            self.assertLess(len(capped["records"]), capped["total"])

            too_small = self.search(
                vault,
                project,
                "--query",
                "page-token",
                "--limit",
                "1",
                "--max-chars",
                "10",
                check=False,
            )
            self.assertNotEqual(too_small.returncode, 0)

    def test_module_summary_uses_scoped_fingerprint_and_complete_coverage(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            vault = base / "vault"
            project = "模块摘要测试"
            root = self.init_vault(vault, project)
            self.upsert(
                vault,
                project,
                kind="architecture",
                record_id="ARCH-module-a",
                title="模块 A 结构",
                body="module-a original",
                modules=["A"],
            )
            self.upsert(
                vault,
                project,
                kind="decision",
                record_id="DEC-module-global",
                title="全局结构",
                body="module-global original",
                modules=["global"],
            )
            self.upsert(
                vault,
                project,
                kind="convention",
                record_id="CONV-module-legacy",
                title="旧项目级约定",
                body="module-legacy original",
            )
            self.upsert(
                vault,
                project,
                kind="bug",
                record_id="BUG-module-b",
                title="模块 B 缺陷",
                body="module-b original",
                modules=["B"],
            )

            body_file = base / "module-a-summary.md"
            body_file.write_text(
                "- A 结构：ARCH-module-a\n"
                "- 全局约定：DEC-module-global\n"
                "- 旧项目级约定：CONV-module-legacy\n",
                encoding="utf-8",
            )
            written = json.loads(
                self.run_maintenance(
                    vault,
                    project,
                    "write-summary",
                    "--module",
                    "A",
                    "--body-file",
                    str(body_file),
                    "--source-id",
                    "ARCH-module-a",
                    "--source-id",
                    "DEC-module-global",
                    "--source-id",
                    "CONV-module-legacy",
                    "--coverage",
                    "complete",
                ).stdout
            )
            expected_path = (
                root
                / "模块摘要"
                / f"{hashlib.sha256('A'.encode('utf-8')).hexdigest()}.md"
            )
            self.assertEqual(written["path"], str(expected_path))
            self.assertTrue(expected_path.exists())

            def audit() -> dict[str, Any]:
                return json.loads(
                    self.run_maintenance(
                        vault, project, "audit", "--module", "A"
                    ).stdout
                )

            fresh = audit()
            self.assertEqual(fresh["summary"]["path"], str(expected_path))
            self.assertEqual(fresh["summary"]["module"], "A")
            self.assertFalse(fresh["summary"]["stale"])
            self.assertTrue(fresh["summary"]["usable"])

            # B 更新不应改变 A 摘要的输入指纹。
            self.upsert(
                vault,
                project,
                kind="bug",
                record_id="BUG-module-b",
                title="模块 B 缺陷",
                body="module-b updated",
                modules=["B"],
            )
            self.assertTrue(audit()["summary"]["usable"])
            self.assertFalse(audit()["summary"]["stale"])

            self.upsert(
                vault,
                project,
                kind="architecture",
                record_id="ARCH-module-a",
                title="模块 A 结构",
                body="module-a updated",
                modules=["A"],
            )
            self.assertTrue(audit()["summary"]["stale"])
            self.assertFalse(audit()["summary"]["usable"])

            # 重新生成摘要后，再修改 global 记录也必须使 A 摘要过期。
            self.run_maintenance(
                vault,
                project,
                "write-summary",
                "--module",
                "A",
                "--body-file",
                str(body_file),
                "--source-id",
                "ARCH-module-a",
                "--source-id",
                "DEC-module-global",
                "--source-id",
                "CONV-module-legacy",
                "--coverage",
                "complete",
            )
            self.assertTrue(audit()["summary"]["usable"])
            self.upsert(
                vault,
                project,
                kind="decision",
                record_id="DEC-module-global",
                title="全局结构",
                body="module-global updated",
                modules=["global"],
            )
            self.assertTrue(audit()["summary"]["stale"])
            self.assertFalse(audit()["summary"]["usable"])

            self.run_maintenance(
                vault,
                project,
                "write-summary",
                "--module",
                "A",
                "--body-file",
                str(body_file),
                "--source-id",
                "ARCH-module-a",
                "--source-id",
                "DEC-module-global",
                "--source-id",
                "CONV-module-legacy",
                "--coverage",
                "complete",
            )
            self.assertTrue(audit()["summary"]["usable"])
            self.upsert(
                vault,
                project,
                kind="decision",
                record_id="DEC-module-global",
                title="全局结构",
                body="module-global updated",
                modules=["global"],
                source="changed-evidence-source",
            )
            self.assertTrue(audit()["summary"]["stale"])
            self.assertFalse(audit()["summary"]["usable"])

            store_audit = json.loads(
                self.run_store(
                    vault, project, "maintenance-audit", "--module", "A"
                ).stdout
            )
            # B 属于范围外模块；A、global 和无模块旧记录共 3 条。
            self.assertEqual(store_audit["active_records"], 3)
            self.assertEqual(store_audit["status_counts"]["active"], 3)

    def test_query_coverage_precedes_heading_weight_and_excerpt_finds_late_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            vault = Path(temp) / "vault"
            project = "相关性验收"
            root = self.init_vault(vault, project)
            self.write_record(root, kind="bug", record_id="BUG-specific",
                              title="重复扣减", body="背景说明。" * 100 + "库存 幂等：重复请求不能再次扣减。",
                              modules=["stock"], updated="2025-01-01")
            self.write_record(root, kind="convention", record_id="CONV-broad",
                              title="库存管理一般约定", body="库存展示与筛选。",
                              modules=["stock"], updated="2026-09-26")
            result = json.loads(self.search(vault, project, "--query", "库存 幂等").stdout)
            self.assertEqual(result["records"][0]["id"], "BUG-specific")
            self.assertIn("重复请求不能再次扣减", result["records"][0]["excerpt"])
            self.assertLessEqual(len(result["records"][0]["excerpt"]), 240)
            strict = json.loads(self.search(vault, project, "--query", "库存 幂等", "--match", "all").stdout)
            self.assertEqual([row["id"] for row in strict["records"]], ["BUG-specific"])
            self.write_record(root, kind="convention", record_id="CONV-reference",
                              title="BUG-specific 引用说明", body="BUG-specific 的检索示例。",
                              modules=["stock"])
            exact = json.loads(self.search(vault, project, "--query", "BUG-specific").stdout)
            self.assertEqual(exact["records"][0]["id"], "BUG-specific")

    def test_snapshot_rejects_changed_content_beyond_excerpt_and_changed_query(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            vault = Path(temp) / "vault"
            project = "分页版本验收"
            root = self.init_vault(vault, project)
            for index in range(4):
                self.write_record(root, kind="api", record_id=f"API-page-{index}",
                                  title="接口约定", body="payment refund " + "背景" * 200,
                                  modules=["payments"])
            first = json.loads(self.search(vault, project, "--query", "payment").stdout)
            page = json.loads(self.search(vault, project, "--query", "payment", "--offset", "3",
                                          "--expected-snapshot", first["snapshot"]).stdout)
            self.assertEqual(len(page["records"]), 1)
            self.assertFalse({r["id"] for r in first["records"]} & {r["id"] for r in page["records"]})
            changed_query = self.search(vault, project, "--query", "refund", "--offset", "3",
                                        "--expected-snapshot", first["snapshot"], check=False)
            self.assertNotEqual(changed_query.returncode, 0)
            target = root / "API" / "API-page-0.md"
            target.write_text(target.read_text(encoding="utf-8") + "正文末尾的新约束。\n", encoding="utf-8")
            changed_body = self.search(vault, project, "--query", "payment", "--offset", "3",
                                       "--expected-snapshot", first["snapshot"], check=False)
            self.assertNotEqual(changed_body.returncode, 0)

    def test_summary_only_returns_same_availability_without_maintenance_details(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            vault = Path(temp) / "vault"
            project = "摘要入口验收"
            self.init_vault(vault, project)
            full = self.run_store(vault, project, "maintenance-audit", "--module", "orders")
            compact = self.run_store(vault, project, "maintenance-audit", "--module", "orders", "--summary-only")
            self.assertEqual(json.loads(full.stdout)["summary"], json.loads(compact.stdout)["summary"])
            self.assertEqual(set(json.loads(compact.stdout)), {"ok", "summary"})
            self.assertLess(len(compact.stdout), len(full.stdout))

    def test_audit_date_boundary_and_invalid_verification_date(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            vault = Path(temp) / "vault"
            project = "验证日期边界"
            root = self.init_vault(vault, project)
            today = dt.date.today().isoformat()
            path = self.write_record(root, kind="environment", record_id="ENV-current",
                                     title="环境基线", body="版本已核实", verified_at=today)
            audit = json.loads(self.run_store(vault, project, "maintenance-audit", "--stale-days", "0").stdout)
            self.assertEqual(audit["stale_active_records"], 1)
            content = path.read_text(encoding="utf-8").replace(f'verified_at: "{today}"', 'verified_at: "invalid-date"')
            path.write_text(content, encoding="utf-8")
            invalid = self.run_store(vault, project, "maintenance-audit", check=False)
            self.assertNotEqual(invalid.returncode, 0)

    def test_project_level_summary_without_module_remains_project_level(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            vault = base / "vault"
            project = "项目级摘要测试"
            root = self.init_vault(vault, project)
            self.upsert(
                vault,
                project,
                kind="convention",
                record_id="CONV-project-level",
                title="项目级约定",
                body="project-level fact",
            )
            body_file = base / "project-summary.md"
            body_file.write_text("项目级事实：CONV-project-level\n", encoding="utf-8")
            result = json.loads(
                self.run_maintenance(
                    vault,
                    project,
                    "write-summary",
                    "--body-file",
                    str(body_file),
                    "--source-id",
                    "CONV-project-level",
                    "--coverage",
                    "complete",
                ).stdout
            )
            self.assertEqual(result["path"], str(root / "知识摘要.md"))
            self.assertTrue((root / "知识摘要.md").exists())
            self.assertFalse((root / "模块摘要").exists())

    def test_proposed_records_are_excluded_from_index_search_and_authoritative_summary(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            vault = base / "vault"
            project = "待确认记录测试"
            root = self.init_vault(vault, project)
            self.upsert(
                vault,
                project,
                kind="architecture",
                record_id="ARCH-proposed-base",
                title="memory 已确认规则",
                body="proposed-scope active",
                modules=["memory"],
            )
            self.upsert(
                vault,
                project,
                kind="decision",
                record_id="DEC-proposed-only",
                title="memory 待确认规则",
                body="proposed-scope proposed",
                status="proposed",
                modules=["memory"],
            )
            self.run_store(vault, project, "rebuild-indexes")
            index = (root / "索引.md").read_text(encoding="utf-8")
            self.assertIn("ARCH-proposed-base", index)
            self.assertNotIn("DEC-proposed-only", index)

            search = json.loads(
                self.search(
                    vault,
                    project,
                    "--query",
                    "proposed-scope",
                    "--module",
                    "memory",
                    "--limit",
                    "20",
                ).stdout
            )
            self.assertEqual(
                {record["id"] for record in search["records"]},
                {"ARCH-proposed-base"},
            )

            body_file = base / "proposed-summary.md"
            body_file.write_text("已确认规则：ARCH-proposed-base\n", encoding="utf-8")
            self.run_maintenance(
                vault,
                project,
                "write-summary",
                "--module",
                "memory",
                "--body-file",
                str(body_file),
                "--source-id",
                "ARCH-proposed-base",
                "--coverage",
                "complete",
            )
            summary_path = (
                root
                / "模块摘要"
                / f"{hashlib.sha256('memory'.encode('utf-8')).hexdigest()}.md"
            )
            before_rejected_write = summary_path.read_bytes()
            rejected = self.run_maintenance(
                vault,
                project,
                "write-summary",
                "--module",
                "memory",
                "--body-file",
                str(body_file),
                "--source-id",
                "ARCH-proposed-base",
                "--source-id",
                "DEC-proposed-only",
                "--coverage",
                "complete",
                check=False,
            )
            self.assertNotEqual(rejected.returncode, 0)
            self.assertEqual(summary_path.read_bytes(), before_rejected_write)

            # proposed 更新不应成为权威摘要的输入，也不要求脚本自动验证源码引用。
            self.upsert(
                vault,
                project,
                kind="decision",
                record_id="DEC-proposed-only",
                title="memory 待确认规则",
                body="proposed-scope proposed updated",
                status="proposed",
                modules=["memory"],
            )
            audit = json.loads(
                self.run_maintenance(vault, project, "audit", "--module", "memory").stdout
            )
            self.assertTrue(audit["summary"]["usable"])


if __name__ == "__main__":
    unittest.main()
