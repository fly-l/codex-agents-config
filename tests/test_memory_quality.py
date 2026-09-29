from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
STORE = REPO_ROOT / "Skills/project-memory/scripts/memory_store.py"
MAINTENANCE = REPO_ROOT / "Skills/project-memory-maintenance/scripts/memory_maintenance.py"


class MemoryQualityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.vault = Path(self.temp.name) / "vault"
        self.project = "摘要历史指纹"
        self.env = {
            **os.environ,
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONIOENCODING": "utf-8",
        }

    def run_script(
        self,
        script: Path,
        *args: str,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(
            [
                sys.executable,
                "-B",
                str(script),
                "--vault-root",
                str(self.vault),
                "--project",
                self.project,
                *args,
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=self.env,
        )
        if check:
            self.assertEqual(result.returncode, 0, result.stderr)
        return result

    def run_store(self, *args: str) -> subprocess.CompletedProcess[str]:
        return self.run_script(STORE, *args)

    def run_maintenance(self, *args: str) -> subprocess.CompletedProcess[str]:
        return self.run_script(MAINTENANCE, *args)

    def init(self) -> Path:
        self.run_store("init")
        return self.vault / self.project / "知识库"

    def upsert(
        self,
        record_id: str,
        title: str,
        body: str,
        *extra: str,
    ) -> dict[str, object]:
        result = self.run_store(
            "upsert",
            "--kind",
            "convention",
            "--id",
            record_id,
            "--title",
            title,
            "--body",
            body,
            "--status",
            "active",
            "--source",
            "quality-fixture",
            "--module",
            "core",
            *extra,
        )
        return json.loads(result.stdout)

    def write_summary(
        self,
        root: Path,
        *source_ids: str,
        include_retired: bool = True,
    ) -> None:
        body_file = Path(self.temp.name) / "summary.md"
        body_file.write_text(
            "\n".join(f"- 来源记录：{record_id}" for record_id in source_ids) + "\n",
            encoding="utf-8",
        )
        args = [
            "write-summary",
            "--body-file",
            str(body_file),
            *sum((["--source-id", record_id] for record_id in source_ids), []),
        ]
        if include_retired:
            args.append("--include-retired")
        args.extend(["--coverage", "complete"])
        self.run_maintenance(*args)

    def audit_summaries(self) -> tuple[dict[str, object], dict[str, object]]:
        maintenance = json.loads(self.run_maintenance("audit").stdout)["summary"]
        store = json.loads(self.run_store("maintenance-audit").stdout)["summary"]
        return maintenance, store

    def change_source(self, root: Path, record_id: str, source: str) -> None:
        path = root / "约定" / f"{record_id}.md"
        text = re.sub(
            r'source: "[^"]*"',
            f'source: "{source}"',
            path.read_text(encoding="utf-8"),
            count=1,
        )
        path.write_text(text, encoding="utf-8")

    def test_referenced_history_body_and_source_changes_stale_both_audits(self) -> None:
        root = self.init()
        self.upsert("CONV-old", "旧约定", "old body")
        self.upsert(
            "CONV-new",
            "新约定",
            "new body",
            "--supersedes",
            "CONV-old",
        )
        self.write_summary(root, "CONV-new", "CONV-old")

        fresh_maintenance, fresh_store = self.audit_summaries()
        self.assertFalse(fresh_maintenance["stale"])
        self.assertFalse(fresh_store["stale"])

        self.change_source(root, "CONV-old", "changed-source")
        source_changed_maintenance, source_changed_store = self.audit_summaries()
        self.assertTrue(source_changed_maintenance["stale"])
        self.assertTrue(source_changed_store["stale"])

        self.write_summary(root, "CONV-new", "CONV-old")
        old_path = root / "约定" / "CONV-old.md"
        old_path.write_text(
            old_path.read_text(encoding="utf-8").replace("old body", "edited old body"),
            encoding="utf-8",
        )
        body_changed_maintenance, body_changed_store = self.audit_summaries()
        self.assertTrue(body_changed_maintenance["stale"])
        self.assertTrue(body_changed_store["stale"])

    def test_unreferenced_history_change_does_not_stale_summary(self) -> None:
        root = self.init()
        self.upsert("CONV-old-used", "已引用旧约定", "used old body")
        self.upsert("CONV-old-unused", "未引用旧约定", "unused old body")
        self.upsert(
            "CONV-new",
            "当前约定",
            "new body",
            "--supersedes",
            "CONV-old-used",
        )
        self.run_store(
            "upsert",
            "--kind",
            "convention",
            "--id",
            "CONV-old-unused",
            "--title",
            "未引用旧约定",
            "--body",
            "unused old body",
            "--status",
            "superseded",
            "--source",
            "quality-fixture",
            "--module",
            "core",
        )
        self.write_summary(root, "CONV-new", "CONV-old-used")

        self.change_source(root, "CONV-old-unused", "unreferenced-source-changed")
        maintenance, store = self.audit_summaries()
        self.assertFalse(maintenance["stale"])
        self.assertTrue(maintenance["usable"])
        self.assertFalse(store["stale"])
        self.assertTrue(store["usable"])

    def test_active_only_summary_keeps_existing_fingerprint_compatibility(self) -> None:
        root = self.init()
        self.upsert("CONV-active", "当前约定", "active body")
        self.write_summary(root, "CONV-active", include_retired=False)
        summary = root / "知识摘要.md"
        summary.write_text(
            summary.read_text(encoding="utf-8").replace("include_retired: false\n", ""),
            encoding="utf-8",
        )

        maintenance, store = self.audit_summaries()
        self.assertFalse(maintenance["stale"])
        self.assertTrue(maintenance["usable"])
        self.assertFalse(store["stale"])
        self.assertTrue(store["usable"])


if __name__ == "__main__":
    unittest.main()
