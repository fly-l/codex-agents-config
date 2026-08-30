from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
STORE = REPO_ROOT / "Skills" / "project-memory" / "scripts" / "memory_store.py"
CURATOR = REPO_ROOT / "Skills" / "project-memory-curator" / "scripts" / "memory_curator.py"
SESSION_START = REPO_ROOT / "Hook" / "project_memory_session_start.py"
SESSION_END = REPO_ROOT / "Hook" / "project_memory_session_end.py"


class MemorySystemTests(unittest.TestCase):
    def run_store(self, vault: Path, project: str, *args: str) -> subprocess.CompletedProcess[str]:
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
            check=True,
            text=True,
            capture_output=True,
        )

    def run_curator(
        self, vault: Path, project: str, *args: str
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                str(CURATOR),
                "--vault-root",
                str(vault),
                "--project",
                project,
                *args,
            ],
            check=True,
            text=True,
            capture_output=True,
        )

    def test_init_upsert_deduplicate_and_validate(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            vault = Path(temp) / "vault"
            project = "示例项目"
            self.run_store(vault, project, "init")
            created = self.run_store(
                vault,
                project,
                "upsert",
                "--kind",
                "decision",
                "--id",
                "ADR-20260829-001",
                "--title",
                "采用原子记忆",
                "--body",
                "每条决策使用独立文件。",
                "--status",
                "accepted",
                "--source",
                "user-confirmed",
            )
            self.assertEqual(json.loads(created.stdout)["action"], "created")

            updated = self.run_store(
                vault,
                project,
                "upsert",
                "--kind",
                "decision",
                "--id",
                "ADR-20260829-001",
                "--title",
                "采用原子记忆",
                "--body",
                "每条决策使用独立文件，并通过稳定 ID 更新。",
                "--status",
                "accepted",
                "--source",
                "user-confirmed",
            )
            self.assertEqual(json.loads(updated.stdout)["action"], "updated")

            duplicate = self.run_store(
                vault,
                project,
                "upsert",
                "--kind",
                "decision",
                "--id",
                "ADR-20260829-002",
                "--title",
                "采用原子记忆",
                "--body",
                "每条决策使用独立文件，并通过稳定 ID 更新。",
                "--status",
                "accepted",
                "--source",
                "user-confirmed",
            )
            self.assertEqual(json.loads(duplicate.stdout)["action"], "duplicate")
            validated = self.run_store(vault, project, "validate")
            self.assertTrue(json.loads(validated.stdout)["ok"])

    def test_hooks_load_summary_and_register_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            repo = base / "repo"
            vault = base / "vault"
            (repo / ".git").mkdir(parents=True)
            (repo / "AGENTS.md").write_text(
                "## 知识体系\n"
                "- 启用：是\n"
                "- 项目名称：Hook测试\n"
                "- 自动加载：是\n"
                "- 自动收集：是\n",
                encoding="utf-8",
            )
            self.run_store(vault, "Hook测试", "init")
            current = vault / "Hook测试" / "知识库" / "当前状态.md"
            current.write_text(
                "# 当前状态\n\n- 使用原子记录。\n" + "记" * 3000,
                encoding="utf-8",
            )
            transcript = base / "rollout.jsonl"
            transcript.write_text("{}\n", encoding="utf-8")
            event = {
                "session_id": "thr_test",
                "transcript_path": str(transcript),
                "cwd": str(repo),
                "reason": "other",
            }
            env = os.environ.copy()
            env["CODEX_MEMORY_VAULT"] = str(vault)

            started = subprocess.run(
                [sys.executable, str(SESSION_START)],
                input=json.dumps({**event, "hook_event_name": "SessionStart"}),
                text=True,
                capture_output=True,
                check=True,
                env=env,
            )
            self.assertIn("使用原子记录", started.stdout)
            injected = json.loads(started.stdout)["hookSpecificOutput"]["additionalContext"]
            self.assertLessEqual(len(injected), 2550)

            subprocess.run(
                [sys.executable, str(SESSION_END)],
                input=json.dumps({**event, "hook_event_name": "SessionEnd"}),
                text=True,
                capture_output=True,
                check=True,
                env=env,
            )
            inbox = list((vault / "Hook测试" / "知识库" / "收件箱").glob("*.json"))
            self.assertEqual(len(inbox), 1)
            payload = json.loads(inbox[0].read_text(encoding="utf-8"))
            self.assertEqual(payload["status"], "pending")
            self.assertTrue(payload["transcript_exists"])
            self.run_store(
                vault,
                "Hook测试",
                "mark-inbox",
                "--file",
                inbox[0].name,
                "--status",
                "processed",
            )
            payload = json.loads(inbox[0].read_text(encoding="utf-8"))
            self.assertEqual(payload["status"], "processed")

    def test_validation_allows_retired_duplicate_fingerprint(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            vault = Path(temp) / "vault"
            project = "旧库去重"
            self.run_store(vault, project, "init")
            self.run_store(
                vault,
                project,
                "upsert",
                "--kind",
                "decision",
                "--id",
                "ADR-20260830-010",
                "--title",
                "统一记忆格式",
                "--body",
                "统一使用原子记录。",
                "--status",
                "accepted",
                "--source",
                "user-confirmed",
            )
            decision_dir = vault / project / "知识库" / "决策"
            canonical = decision_dir / "ADR-20260830-010.md"
            duplicate = decision_dir / "ADR-20260830-011.md"
            duplicate.write_text(
                canonical.read_text(encoding="utf-8")
                .replace('id: "ADR-20260830-010"', 'id: "ADR-20260830-011"')
                .replace("# ADR-20260830-010:", "# ADR-20260830-011:"),
                encoding="utf-8",
            )

            audit = json.loads(self.run_curator(vault, project, "audit").stdout)
            self.assertEqual(audit["stats"]["exact_duplicate_groups"], 1)
            self.run_curator(
                vault,
                project,
                "supersede",
                "--canonical",
                "ADR-20260830-010",
                "--duplicate",
                "ADR-20260830-011",
                "--reason",
                "旧库完全重复记录",
                "--apply",
            )
            after = json.loads(self.run_curator(vault, project, "audit").stdout)
            self.assertEqual(after["stats"]["exact_duplicate_groups"], 0)
            self.assertEqual(after["stats"]["historical_duplicate_groups"], 1)
            validated = json.loads(self.run_store(vault, project, "validate").stdout)
            self.assertTrue(validated["ok"])

    def test_curator_audits_summarizes_supersedes_and_archives(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            vault = Path(temp) / "vault"
            project = "整理测试"
            self.run_store(vault, project, "init")
            self.run_store(
                vault,
                project,
                "upsert",
                "--kind",
                "decision",
                "--id",
                "ADR-20260830-001",
                "--title",
                "采用原子项目记忆",
                "--body",
                "项目记忆使用独立 Markdown 文件，并通过稳定 ID 原子更新。",
                "--status",
                "accepted",
                "--source",
                "user-confirmed",
            )
            self.run_store(
                vault,
                project,
                "upsert",
                "--kind",
                "decision",
                "--id",
                "ADR-20260830-002",
                "--title",
                "采用原子项目记忆",
                "--body",
                "项目知识分别写入 Markdown，并由稳定 ID 更新。",
                "--status",
                "accepted",
                "--source",
                "user-confirmed",
            )

            audit = json.loads(
                self.run_curator(
                    vault,
                    project,
                    "audit",
                    "--similarity-threshold",
                    "0.2",
                ).stdout
            )
            self.assertEqual(audit["stats"]["records"], 2)
            self.assertEqual(audit["stats"]["same_title_conflicts"], 1)

            preview = json.loads(
                self.run_curator(
                    vault,
                    project,
                    "supersede",
                    "--canonical",
                    "ADR-20260830-001",
                    "--duplicate",
                    "ADR-20260830-002",
                    "--reason",
                    "用户确认两条记录含义相同",
                ).stdout
            )
            self.assertEqual(preview["action"], "preview")
            duplicate_path = vault / project / "知识库" / "决策" / "ADR-20260830-002.md"
            self.assertIn("status: \"accepted\"", duplicate_path.read_text(encoding="utf-8"))

            applied = json.loads(
                self.run_curator(
                    vault,
                    project,
                    "supersede",
                    "--canonical",
                    "ADR-20260830-001",
                    "--duplicate",
                    "ADR-20260830-002",
                    "--reason",
                    "用户确认两条记录含义相同",
                    "--apply",
                ).stdout
            )
            self.assertEqual(applied["action"], "superseded")
            self.assertIn("status: \"superseded\"", duplicate_path.read_text(encoding="utf-8"))
            self.assertIn("superseded_by: \"ADR-20260830-001\"", duplicate_path.read_text(encoding="utf-8"))

            summary_body = Path(temp) / "summary.md"
            summary_body.write_text(
                "## 当前决策\n\n- 使用原子项目记忆（ADR-20260830-001）。\n",
                encoding="utf-8",
            )
            summary = json.loads(
                self.run_curator(
                    vault,
                    project,
                    "write-summary",
                    "--body-file",
                    str(summary_body),
                    "--source-id",
                    "ADR-20260830-001",
                ).stdout
            )
            self.assertEqual(summary["source_records"], ["ADR-20260830-001"])
            summary_path = vault / project / "知识库" / "知识摘要.md"
            self.assertIn("ADR-20260830-001", summary_path.read_text(encoding="utf-8"))

            inbox = vault / project / "知识库" / "收件箱"
            old_candidate = inbox / "old.json"
            old_candidate.write_text(
                json.dumps(
                    {
                        "status": "processed",
                        "created_at": "2020-01-01T00:00:00+00:00",
                        "processed_at": "2020-01-02T00:00:00+00:00",
                    }
                ),
                encoding="utf-8",
            )
            archive_preview = json.loads(
                self.run_curator(vault, project, "archive-inbox").stdout
            )
            self.assertEqual(archive_preview["action"], "preview")
            self.assertTrue(old_candidate.exists())
            archive = json.loads(
                self.run_curator(vault, project, "archive-inbox", "--apply").stdout
            )
            self.assertEqual(archive["action"], "archived")
            self.assertFalse(old_candidate.exists())
            self.assertTrue((inbox / "归档" / "2020" / "old.json").exists())

            validated = json.loads(self.run_store(vault, project, "validate").stdout)
            self.assertTrue(validated["ok"])


if __name__ == "__main__":
    unittest.main()
