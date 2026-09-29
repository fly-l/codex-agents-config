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
MANAGER = REPO_ROOT / "Hook" / "manage_installation.py"


class InstallationManagerTests(unittest.TestCase):
    def run_manager(
        self,
        home: Path,
        command: str,
        *arguments: str,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        environment = os.environ.copy()
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        return subprocess.run(
            [sys.executable, str(MANAGER), command, "--home", str(home), *arguments],
            check=check,
            capture_output=True,
            text=True,
            env=environment,
        )

    def test_status_reports_empty_installation_without_creating_home(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary) / "empty-home"
            result = self.run_manager(home, "status")
            payload = json.loads(result.stdout)

            self.assertEqual(payload["home"], str(home.resolve()))
            self.assertIn("executable", payload["python"])
            self.assertIn("version", payload["python"])
            self.assertGreater(payload["missing"], 0)
            self.assertEqual(payload["changed"], 0)
            self.assertFalse(payload["in_sync"])
            self.assertEqual(payload["hooks"]["config_path"], str(home.resolve() / "hooks.json"))
            self.assertFalse(payload["hooks"]["exists"])
            self.assertEqual(
                set(payload["optional_dependencies"]),
                {"title_skill", "node", "codex"},
            )
            self.assertFalse(home.exists())

    def test_dry_run_has_a_plan_and_does_not_change_home(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary) / "dry-run-home"
            result = self.run_manager(home, "sync")
            payload = json.loads(result.stdout)

            self.assertTrue(payload["dry_run"])
            self.assertFalse(payload["applied"])
            self.assertGreater(len(payload["changes"]), 0)
            self.assertFalse(home.exists())

    def test_apply_then_same_content_is_idempotent_without_duplicate_backup(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary) / "installed-home"
            first = json.loads(self.run_manager(home, "sync", "--apply").stdout)
            self.assertTrue(first["applied"])
            self.assertTrue(first["in_sync"])
            self.assertIsNotNone(first["backup"])
            run_directories = list(
                (home / "backups" / "codex-agents-config").iterdir()
            )
            self.assertEqual(len(run_directories), 1)

            second = json.loads(self.run_manager(home, "sync", "--apply").stdout)
            self.assertTrue(second["in_sync"])
            self.assertEqual(second["changes"], [])
            self.assertIsNone(second["backup"])
            self.assertEqual(
                len(list((home / "backups" / "codex-agents-config").iterdir())),
                1,
            )

    def test_upgrade_backups_overwritten_file_and_records_hashes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary) / "upgrade-home"
            self.run_manager(home, "sync", "--apply")
            target = home / "skills" / "project-memory" / "SKILL.md"
            old_content = b"old installed content\n"
            target.write_bytes(old_content)
            old_hash = hashlib.sha256(old_content).hexdigest()
            new_hash = hashlib.sha256(
                (REPO_ROOT / "Skills" / "project-memory" / "SKILL.md").read_bytes()
            ).hexdigest()

            result = json.loads(self.run_manager(home, "sync", "--apply").stdout)
            manifest_path = Path(result["backup"]["manifest"])
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            entry = next(
                item
                for item in manifest["files"]
                if item["target"] == str(target.resolve())
            )

            self.assertEqual(entry["old_hash"], old_hash)
            self.assertEqual(entry["new_hash"], new_hash)
            backup = home / entry["backup_relative_path"]
            self.assertEqual(backup.read_bytes(), old_content)
            self.assertEqual(target.read_bytes(), (REPO_ROOT / "Skills" / "project-memory" / "SKILL.md").read_bytes())

    def test_user_extra_file_is_retained(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary) / "extras-home"
            self.run_manager(home, "sync", "--apply")
            extra = home / "skills" / "project-memory" / "user-extra.txt"
            extra.write_text("由用户维护\n", encoding="utf-8")

            self.run_manager(home, "sync", "--apply")

            self.assertEqual(extra.read_text(encoding="utf-8"), "由用户维护\n")
            self.assertEqual(
                json.loads(self.run_manager(home, "status").stdout)["skills"]["project-memory"]["extra"],
                1,
            )

    def test_status_reports_hook_reference_existence_without_dumping_config(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            home = base / "codex-home"
            home.mkdir()
            existing = REPO_ROOT / "Hook" / "project_memory_session_start.py"
            missing = base / "gone" / "project_memory_session_end.py"
            config = {
                "hooks": {
                    "SessionStart": [
                        {
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": f'python "{existing}"',
                                }
                            ]
                        }
                    ],
                    "SessionEnd": [
                        {
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": f'python "{missing}" --token SECRET_SHOULD_NOT_BE_PRINTED',
                                }
                            ]
                        }
                    ],
                }
            }
            (home / "hooks.json").write_text(
                json.dumps(config, ensure_ascii=False), encoding="utf-8"
            )

            result = self.run_manager(home, "status")
            payload = json.loads(result.stdout)
            references = payload["hooks"]["references"]
            by_script = {item["script"]: item for item in references}

            self.assertTrue(by_script["project_memory_session_start.py"]["exists"])
            self.assertFalse(by_script["project_memory_session_end.py"]["exists"])
            self.assertNotIn("SECRET_SHOULD_NOT_BE_PRINTED", result.stdout)

    def test_apply_rejects_directory_target_before_writing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary) / "bad-home"
            target = home / "skills" / "project-memory" / "SKILL.md"
            target.mkdir(parents=True)

            result = self.run_manager(home, "sync", "--apply", check=False)

            self.assertNotEqual(result.returncode, 0)
            self.assertTrue(target.is_dir())
            self.assertFalse((home / "backups").exists())

    def test_apply_rejects_symlink_target_outside_home(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            home = base / "symlink-home"
            outside = base / "outside.txt"
            outside.write_text("must remain\n", encoding="utf-8")
            target = home / "skills" / "project-memory" / "SKILL.md"
            target.parent.mkdir(parents=True)
            try:
                target.symlink_to(outside)
            except (OSError, NotImplementedError):
                self.skipTest("当前 Windows 环境不允许创建符号链接")

            result = self.run_manager(home, "sync", "--apply", check=False)

            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(outside.read_text(encoding="utf-8"), "must remain\n")


if __name__ == "__main__":
    unittest.main()
