from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


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


class MemoryValidationTests(unittest.TestCase):
    def run_command(
        self,
        script: Path,
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
                str(script),
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

    def run_store(
        self,
        vault: Path,
        project: str,
        *args: str,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        return self.run_command(STORE, vault, project, *args, check=check)

    def run_maintenance(
        self,
        vault: Path,
        project: str,
        *args: str,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        return self.run_command(MAINTENANCE, vault, project, *args, check=check)

    def init_vault(self, vault: Path, project: str) -> Path:
        self.run_store(vault, project, "init")
        return vault / project / "知识库"

    def write_record(
        self,
        root: Path,
        *,
        kind: str = "convention",
        record_id: str = "CONV-valid",
        title: str = "有效记录",
        body: str = "有效正文",
        modules: list[str] | None = None,
        overrides: dict[str, object] | None = None,
        filename: str | None = None,
    ) -> Path:
        values: dict[str, object] = {
            "id": record_id,
            "type": kind,
            "status": "active",
            "title": title,
            "project": root.parent.name,
            "source": "test-source",
            "created": "2026-09-05",
            "updated": "2026-09-05",
            "verified_at": "2026-09-05",
            "supersedes": [],
            "fingerprint": record_fingerprint(kind, title, body, modules or []),
        }
        if modules is not None:
            values["module"] = modules
        if overrides:
            values.update(overrides)
        target = root / KIND_DIRS[kind] / f"{filename or record_id}.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        lines = ["---"]
        for key, value in values.items():
            lines.append(f"{key}: {json.dumps(value, ensure_ascii=False)}")
        lines.extend(
            [
                "---",
                "",
                f"# {record_id}: {title}",
                "",
                "## 内容",
                "",
                body,
                "",
            ]
        )
        target.write_text("\n".join(lines), encoding="utf-8")
        return target

    def test_validate_missing_vault_and_maintenance_audit_fail(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            vault = Path(temp) / "vault"
            project = "不存在的项目"
            store_result = self.run_store(vault, project, "validate", check=False)
            self.assertNotEqual(store_result.returncode, 0)
            self.assertIn("尚未初始化", store_result.stderr)

            maintenance_result = self.run_maintenance(
                vault, project, "audit", check=False
            )
            self.assertNotEqual(maintenance_result.returncode, 0)
            self.assertIn("尚未初始化", maintenance_result.stderr)

    def test_initialized_empty_vault_is_explicitly_empty(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            vault = Path(temp) / "vault"
            project = "空知识库"
            self.init_vault(vault, project)

            result = self.run_store(vault, project, "validate")
            payload = json.loads(result.stdout)
            self.assertTrue(payload["ok"])
            self.assertTrue(payload["empty"])
            self.assertEqual(payload["records"], 0)
            self.assertEqual(payload["errors"], [])

            audit = json.loads(self.run_maintenance(vault, project, "audit").stdout)
            self.assertTrue(audit["ok"])
            self.assertTrue(audit["empty"])
            self.assertEqual(audit["stats"]["records"], 0)

    def test_root_legacy_note_and_legacy_record_without_module_are_supported(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            vault = Path(temp) / "vault"
            project = "旧格式兼容"
            root = self.init_vault(vault, project)
            (root / "旧项目架构.md").write_text(
                "这是项目根目录的旧笔记，不是原子记录。\n", encoding="utf-8"
            )
            self.write_record(root)

            validated = json.loads(self.run_store(vault, project, "validate").stdout)
            self.assertTrue(validated["ok"])
            self.assertFalse(validated["empty"])
            self.assertEqual(validated["records"], 1)

            audit = json.loads(self.run_maintenance(vault, project, "audit").stdout)
            self.assertTrue(audit["ok"])
            self.assertEqual(audit["stats"]["records"], 1)

    def test_bad_category_files_fail_fast_with_the_file_path(self) -> None:
        bad_files = {
            "缺少id.md": "---\ntitle: \"没有 ID\"\n---\n\n正文\n",
            "坏frontmatter.md": "这不是 frontmatter\n",
            "frontmatter未闭合.md": "---\nid: \"CONV-bad\"\n",
            "frontmatter坏行.md": "---\nid: \"CONV-bad\"\n坏行\n---\n\n正文\n",
        }
        for filename, content in bad_files.items():
            with self.subTest(filename=filename), tempfile.TemporaryDirectory() as temp:
                vault = Path(temp) / "vault"
                project = "损坏文件"
                root = self.init_vault(vault, project)
                target = root / "约定" / filename
                target.write_text(content, encoding="utf-8")

                store_result = self.run_store(vault, project, "validate", check=False)
                self.assertNotEqual(store_result.returncode, 0)
                self.assertIn(filename, store_result.stderr)

                maintenance_result = self.run_maintenance(
                    vault, project, "audit", check=False
                )
                self.assertNotEqual(maintenance_result.returncode, 0)
                self.assertIn(filename, maintenance_result.stderr)

        with tempfile.TemporaryDirectory() as temp:
            vault = Path(temp) / "vault"
            project = "读取失败文件"
            root = self.init_vault(vault, project)
            target = root / "约定" / "读取失败.md"
            target.mkdir()

            store_result = self.run_store(vault, project, "validate", check=False)
            self.assertNotEqual(store_result.returncode, 0)
            self.assertIn("读取失败.md", store_result.stderr)
            maintenance_result = self.run_maintenance(
                vault, project, "audit", check=False
            )
            self.assertNotEqual(maintenance_result.returncode, 0)
            self.assertIn("读取失败.md", maintenance_result.stderr)

    def test_validate_checks_id_type_source_and_verified_at(self) -> None:
        cases = {
            "ID 不合法": {"id": "CONV bad"},
            "类型与目录不匹配": {"type": "bug"},
            "source 为空": {"source": ""},
            "verified_at 不是合法日期": {"verified_at": "2026-02-30"},
        }
        for expected_error, overrides in cases.items():
            with self.subTest(expected_error=expected_error), tempfile.TemporaryDirectory() as temp:
                vault = Path(temp) / "vault"
                project = "元数据校验"
                root = self.init_vault(vault, project)
                self.write_record(root, overrides=overrides)

                result = self.run_store(vault, project, "validate", check=False)
                self.assertNotEqual(result.returncode, 0)
                payload = json.loads(result.stdout)
                self.assertFalse(payload["ok"])
                self.assertTrue(
                    any(expected_error in error for error in payload["errors"]),
                    payload["errors"],
                )

    def test_validate_rejects_missing_superseded_by_target(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            vault = Path(temp) / "vault"
            project = "反向替代关系"
            root = self.init_vault(vault, project)
            self.write_record(
                root,
                record_id="CONV-old",
                overrides={"status": "superseded", "superseded_by": "CONV-new"},
            )
            replacement = self.write_record(
                root,
                record_id="CONV-new",
                overrides={"supersedes": ["CONV-old"]},
            )

            valid = json.loads(self.run_store(vault, project, "validate").stdout)
            self.assertTrue(valid["ok"])

            replacement.unlink()
            result = self.run_store(vault, project, "validate", check=False)
            self.assertNotEqual(result.returncode, 0)
            payload = json.loads(result.stdout)
            self.assertFalse(payload["ok"])
            self.assertIn(
                "superseded_by 目标不存在：CONV-old -> CONV-new", payload["errors"]
            )

    def test_maintenance_audit_reports_invalid_record_instead_of_dropping_it(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            vault = Path(temp) / "vault"
            project = "维护坏记录"
            root = self.init_vault(vault, project)
            record = self.write_record(root, overrides={"source": "  "})

            result = self.run_maintenance(vault, project, "audit")
            payload = json.loads(result.stdout)
            self.assertFalse(payload["ok"])
            self.assertEqual(payload["stats"]["records"], 1)
            self.assertEqual(payload["missing_fields"], [])
            self.assertEqual(payload["metadata_errors"][0]["id"], "CONV-valid")
            self.assertIn("source 为空", payload["metadata_errors"][0]["errors"])
            self.assertEqual(payload["metadata_errors"][0]["path"], "约定/CONV-valid")
            self.assertTrue(record.exists())


if __name__ == "__main__":
    unittest.main()
