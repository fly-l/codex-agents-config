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
            current.write_text("# 当前状态\n\n- 使用原子记录。\n", encoding="utf-8")
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


if __name__ == "__main__":
    unittest.main()
