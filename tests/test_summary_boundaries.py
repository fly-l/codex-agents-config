from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


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


def load_maintenance():
    spec = importlib.util.spec_from_file_location("summary_boundary_maintenance", MAINTENANCE)
    if spec is None or spec.loader is None:
        raise AssertionError("无法加载维护脚本")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def legacy_normalize(value: str) -> str:
    return " ".join(value.replace("\r\n", "\n").replace("\r", "\n").split()).casefold()


def legacy_fingerprint(kind: str, title: str, body: str, modules: list[str]) -> str:
    payload = json.dumps(
        {
            "type": kind,
            "title": legacy_normalize(title),
            "body": legacy_normalize(body),
            "module": sorted(legacy_normalize(value) for value in modules),
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class SummaryBoundaryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.env = os.environ.copy()
        self.env["PYTHONDONTWRITEBYTECODE"] = "1"
        self.env["PYTHONUTF8"] = "1"

    def run_script(
        self,
        script: Path,
        vault: Path,
        project: str,
        *args: str,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                "-B",
                str(script),
                "--vault-root",
                str(vault),
                "--project",
                project,
                *args,
            ],
            check=check,
            text=True,
            encoding="utf-8",
            capture_output=True,
            env=self.env,
        )

    def run_store(
        self,
        vault: Path,
        project: str,
        *args: str,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        return self.run_script(STORE, vault, project, *args, check=check)

    def run_maintenance(
        self,
        vault: Path,
        project: str,
        *args: str,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        return self.run_script(MAINTENANCE, vault, project, *args, check=check)

    def init(self, vault: Path, project: str) -> Path:
        self.run_store(vault, project, "init")
        return vault / project / "知识库"

    def upsert(
        self,
        vault: Path,
        project: str,
        *,
        kind: str,
        record_id: str,
        title: str,
        body: str,
        modules: list[str] | None = None,
        status: str = "active",
    ) -> Path:
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
            "summary-boundary-test",
        ]
        for module in modules or []:
            args.extend(["--module", module])
        self.run_store(vault, project, *args)
        return vault / project / "知识库" / KIND_DIRS[kind] / f"{record_id}.md"

    def write_summary(
        self,
        vault: Path,
        project: str,
        body_file: Path,
        *source_ids: str,
        module: str | None = None,
        coverage: str = "complete",
        include_retired: bool = False,
    ) -> dict:
        args = ["write-summary", "--body-file", str(body_file)]
        if module is not None:
            args.extend(["--module", module])
        for source_id in source_ids:
            args.extend(["--source-id", source_id])
        if include_retired:
            args.append("--include-retired")
        args.extend(["--coverage", coverage])
        return json.loads(self.run_maintenance(vault, project, *args).stdout)

    def audit(
        self,
        vault: Path,
        project: str,
        *,
        module: str | None = None,
    ) -> dict:
        args = ["audit"]
        if module is not None:
            args.extend(["--module", module])
        return json.loads(self.run_maintenance(vault, project, *args).stdout)

    def summary_path(self, root: Path, module: str | None = None) -> Path:
        if module is None:
            return root / "知识摘要.md"
        digest = hashlib.sha256(module.encode("utf-8")).hexdigest()
        return root / "模块摘要" / f"{digest}.md"

    def test_summary_scope_rejects_cross_project_copy_and_wrong_module(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            vault = base / "vault"
            root_a = self.init(vault, "项目甲")
            root_b = self.init(vault, "项目乙")
            self.upsert(
                vault,
                "项目甲",
                kind="architecture",
                record_id="ARCH-scope-shared",
                title="共享摘要边界",
                body="scope boundary",
            )
            self.upsert(
                vault,
                "项目乙",
                kind="architecture",
                record_id="ARCH-scope-shared",
                title="共享摘要边界",
                body="scope boundary",
            )

            body_file = base / "project-summary.md"
            body_file.write_text("共享摘要：ARCH-scope-shared\n", encoding="utf-8")
            self.write_summary(vault, "项目甲", body_file, "ARCH-scope-shared")
            root_b.joinpath("知识摘要.md").write_bytes(
                root_a.joinpath("知识摘要.md").read_bytes()
            )

            copied = self.audit(vault, "项目乙")
            self.assertFalse(copied["summary"]["scope_valid"])
            self.assertFalse(copied["summary"]["usable"])
            self.assertTrue(
                any("project" in error and "不匹配" in error for error in copied["summary"]["scope_errors"])
            )

            root = self.init(vault, "模块范围")
            self.upsert(
                vault,
                "模块范围",
                kind="architecture",
                record_id="ARCH-scope-a",
                title="A 模块摘要",
                body="module A",
                modules=["A"],
            )
            self.upsert(
                vault,
                "模块范围",
                kind="architecture",
                record_id="ARCH-scope-b",
                title="B 模块摘要",
                body="module B",
                modules=["B"],
            )
            module_body = base / "module-summary.md"
            module_body.write_text("A 摘要：ARCH-scope-a\n", encoding="utf-8")
            self.write_summary(
                vault,
                "模块范围",
                module_body,
                "ARCH-scope-a",
                module="A",
            )
            target = self.summary_path(root, "B")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(self.summary_path(root, "A").read_bytes())

            wrong_module = self.audit(vault, "模块范围", module="B")
            self.assertFalse(wrong_module["summary"]["scope_valid"])
            self.assertFalse(wrong_module["summary"]["usable"])
            self.assertTrue(
                any("module" in error and "不匹配" in error for error in wrong_module["summary"]["scope_errors"])
            )

    def test_summary_scope_rejects_missing_sources_and_keeps_partial_non_usable(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            vault = base / "vault"
            root = self.init(vault, "来源覆盖")
            self.upsert(
                vault,
                "来源覆盖",
                kind="architecture",
                record_id="ARCH-source-a",
                title="来源 A",
                body="source A",
            )
            self.upsert(
                vault,
                "来源覆盖",
                kind="decision",
                record_id="DEC-source-b",
                title="来源 B",
                body="source B",
            )
            body_file = base / "summary.md"
            body_file.write_text(
                "A：ARCH-source-a\nB：DEC-source-b\n",
                encoding="utf-8",
            )
            self.write_summary(
                vault,
                "来源覆盖",
                body_file,
                "ARCH-source-a",
                "DEC-source-b",
            )

            summary = root / "知识摘要.md"
            text = summary.read_text(encoding="utf-8")
            text = text.replace(
                'source_records: ["ARCH-source-a", "DEC-source-b"]',
                'source_records: ["ARCH-source-a"]',
            )
            summary.write_text(text, encoding="utf-8")
            missing = self.audit(vault, "来源覆盖")
            self.assertFalse(missing["summary"]["scope_valid"])
            self.assertFalse(missing["summary"]["usable"])
            self.assertTrue(
                any("完整摘要未覆盖" in error for error in missing["summary"]["scope_errors"])
            )

            text = text.replace(
                'coverage: "complete"',
                'coverage: "partial"',
            )
            summary.write_text(text, encoding="utf-8")
            partial = self.audit(vault, "来源覆盖")
            self.assertTrue(partial["summary"]["scope_valid"])
            self.assertFalse(partial["summary"]["usable"])

            summary.write_text(
                text.replace('source_records: ["ARCH-source-a"]\n', ""),
                encoding="utf-8",
            )
            missing_field = self.audit(vault, "来源覆盖")
            self.assertIsNone(missing_field["summary"]["source_records"])
            self.assertFalse(missing_field["summary"]["scope_valid"])
            self.assertFalse(missing_field["summary"]["usable"])
            self.assertTrue(
                any(
                    "source_records" in error and "字符串列表" in error
                    for error in missing_field["summary"]["scope_errors"]
                )
            )

    def test_strict_digest_detects_same_day_case_and_indentation_changes(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            vault = base / "vault"
            root = self.init(vault, "同日指纹")
            record = self.upsert(
                vault,
                "同日指纹",
                kind="architecture",
                record_id="ARCH-digest-boundary",
                title="Case Stable",
                body="第一行\n第二行",
            )
            body_file = base / "summary.md"
            body_file.write_text("摘要：ARCH-digest-boundary\n", encoding="utf-8")
            self.write_summary(vault, "同日指纹", body_file, "ARCH-digest-boundary")
            original = record.read_text(encoding="utf-8")

            record.write_text(
                original.replace('title: "Case Stable"', 'title: "case stable"'),
                encoding="utf-8",
            )
            case_changed = self.audit(vault, "同日指纹")
            self.assertTrue(case_changed["summary"]["stale"])
            self.assertFalse(case_changed["summary"]["usable"])
            self.assertTrue(case_changed["metadata_errors"])

            self.write_summary(vault, "同日指纹", body_file, "ARCH-digest-boundary")
            changed = record.read_text(encoding="utf-8")
            record.write_text(
                changed.replace("第一行\n第二行", "第一行\n  第二行"),
                encoding="utf-8",
            )
            indent_changed = self.audit(vault, "同日指纹")
            self.assertTrue(indent_changed["summary"]["stale"])
            self.assertFalse(indent_changed["summary"]["usable"])

            # 换行风格属于同一内容；大小写和缩进则必须保持内容身份差异。
            maintenance = load_maintenance()
            base_record = {
                "type": "architecture",
                "title": "Line\r\nTitle",
                "body": "A\rB",
                "module": ["A", "B"],
            }
            crlf = maintenance.record_digest(base_record)
            lf = maintenance.record_digest(
                {**base_record, "title": "Line\nTitle", "body": "A\nB"}
            )
            self.assertEqual(crlf, lf)
            self.assertEqual(
                crlf,
                maintenance.record_digest({**base_record, "module": ["B", "A"]}),
            )
            self.assertNotEqual(
                crlf,
                maintenance.record_digest({**base_record, "title": "line\r\ntitle"}),
            )
            self.assertNotEqual(
                crlf,
                maintenance.record_digest({**base_record, "body": "A\r  B"}),
            )
            self.assertNotEqual(
                crlf,
                maintenance.record_digest({**base_record, "module": ["A\n", "B"]}),
            )

    def test_legacy_record_fingerprint_is_read_only_compatible_and_v2_is_strict(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            vault = base / "vault"
            root = self.init(vault, "旧指纹")
            record = self.upsert(
                vault,
                "旧指纹",
                kind="architecture",
                record_id="ARCH-legacy-fingerprint",
                title="Legacy Title",
                body="legacy body",
                modules=["legacy"],
            )
            text = record.read_text(encoding="utf-8")
            digest = legacy_fingerprint("architecture", "Legacy Title", "legacy body", ["legacy"])
            text = text.replace("fingerprint_version: 2\n", "")
            text = re.sub(
                r'fingerprint: "[0-9a-f]+"',
                f'fingerprint: "{digest}"',
                text,
                count=1,
            )
            record.write_text(text, encoding="utf-8")
            compatible = self.audit(vault, "旧指纹")
            self.assertFalse(
                any("内容指纹不匹配" in error for item in compatible["metadata_errors"] for error in item["errors"])
            )

            strict_text = record.read_text(encoding="utf-8")
            strict_text = strict_text.replace(
                'fingerprint: "' + digest + '"',
                'fingerprint_version: 2\nfingerprint: "' + digest + '"',
            )
            record.write_text(strict_text, encoding="utf-8")
            strict = self.audit(vault, "旧指纹")
            self.assertTrue(
                any("内容指纹不匹配" in error for item in strict["metadata_errors"] for error in item["errors"])
            )

            # 维护脚本只读兼容旧值，不改动旧记录的验证日期和正文。
            self.assertIn('verified_at: ', record.read_text(encoding="utf-8"))
            self.assertEqual(strict["summary"]["path"], str(root / "知识摘要.md"))

    def test_archive_rechecks_candidate_after_lock(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            vault = base / "vault"
            inbox = vault / "归档竞态" / "知识库" / "收件箱"
            inbox.mkdir(parents=True)
            candidate = inbox / "candidate.json"
            candidate.write_text(
                json.dumps(
                    {
                        "status": "processed",
                        "processed_at": "2000-01-01T00:00:00+00:00",
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            maintenance = load_maintenance()

            @contextlib.contextmanager
            def mutate_under_lock(path: Path):
                payload = json.loads(path.read_text(encoding="utf-8"))
                payload["status"] = "pending"
                path.write_text(json.dumps(payload), encoding="utf-8")
                yield

            output = io.StringIO()
            args = type(
                "ArchiveArgs",
                (),
                {
                    "vault_root": str(vault),
                    "project": "归档竞态",
                    "older_than_days": 30,
                    "apply": True,
                },
            )()
            with mock.patch.object(maintenance, "candidate_lock", mutate_under_lock):
                with mock.patch("sys.stdout", output):
                    maintenance.command_archive_inbox(args)

            result = json.loads(output.getvalue())
            self.assertEqual(result["candidates"], [candidate.name])
            self.assertEqual(result["moved"], [])
            self.assertTrue(candidate.exists())
            self.assertFalse((inbox / "归档" / "2000" / candidate.name).exists())


if __name__ == "__main__":
    unittest.main()
