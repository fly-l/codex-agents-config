from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SESSION_START = REPO_ROOT / "Hook" / "project_memory_session_start.py"
INBOX = REPO_ROOT / "Skills" / "project-memory" / "scripts" / "memory_inbox.py"


class MemoryAutoReviewTests(unittest.TestCase):
    @staticmethod
    def write_project(repo: Path, *, auto_load: str = "否", auto_review: str = "否") -> None:
        (repo / ".git").mkdir(parents=True)
        (repo / "AGENTS.md").write_text(
            "## 知识体系\n"
            "- 启用：是\n"
            "- 项目名称：自动审核测试\n"
            f"- 自动加载：{auto_load}\n"
            f"- 自动审核：{auto_review}\n"
            "- 自动收集：是\n",
            encoding="utf-8",
        )

    @staticmethod
    def write_candidate(inbox: Path, name: str, *, status: str = "pending", index: int = 0) -> None:
        inbox.mkdir(parents=True, exist_ok=True)
        (inbox / name).write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "status": status,
                    "project": "自动审核测试",
                    "host": "codex",
                    "session_id": f"session-{index}",
                    "turn_id": f"turn-{index}",
                    "reason": "other",
                    "updated_at": f"2026-09-26T00:00:0{index}+00:00",
                    "transcript_path": "C:/private/transcript.jsonl",
                    "transcript_exists": True,
                    "repository_root": "C:/repo",
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

    @staticmethod
    def run_start(repo: Path, vault: Path, *, extra_env: dict[str, str] | None = None) -> str:
        env = os.environ.copy()
        env.update(
            {
                "PROJECT_MEMORY_VAULT": str(vault),
                "PYTHONDONTWRITEBYTECODE": "1",
                "PYTHONUTF8": "0",
            }
        )
        if extra_env:
            env.update(extra_env)
        result = subprocess.run(
            [sys.executable, "-B", str(SESSION_START)],
            input=json.dumps({"cwd": str(repo), "hook_event_name": "SessionStart"}).encode("utf-8"),
            capture_output=True,
            check=True,
            env=env,
        )
        return result.stdout.decode("utf-8")

    def test_auto_review_is_opt_in_and_independent_of_auto_load(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            repo = base / "repo"
            vault = base / "vault"
            self.write_project(repo, auto_review="否")
            inbox = vault / "自动审核测试" / "知识库" / "收件箱"
            self.write_candidate(inbox, "candidate.json", index=1)

            self.assertEqual(self.run_start(repo, vault), "")

            (repo / "AGENTS.md").write_text(
                (repo / "AGENTS.md").read_text(encoding="utf-8").replace("自动审核：否", "自动审核：是"),
                encoding="utf-8",
            )
            output = self.run_start(repo, vault)
            self.assertIn("session-1", output)
            self.assertIn("仅为元数据", output)
            self.assertNotIn("private/transcript.jsonl", output)

    def test_auto_review_prompt_is_bounded_and_does_not_read_transcript(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            repo = base / "repo"
            vault = base / "vault"
            self.write_project(repo, auto_review="是")
            inbox = vault / "自动审核测试" / "知识库" / "收件箱"
            self.write_candidate(inbox, "candidate-1.json", index=1)
            self.write_candidate(inbox, "candidate-2.json", index=2)
            transcript = base / "transcript.jsonl"
            transcript.write_text("机密聊天正文 sentinel-transcript-body\n", encoding="utf-8")

            output = self.run_start(
                repo,
                vault,
                extra_env={"CODEX_MEMORY_REVIEW_CHARS": "800"},
            )
            payload = json.loads(output)
            context = payload["hookSpecificOutput"]["additionalContext"]
            self.assertLessEqual(len(context), 800)
            self.assertIn("session-2", context)
            self.assertNotIn("sentinel-transcript-body", context)
            self.assertNotIn("机密聊天正文", context)

    def test_auto_review_and_auto_load_share_context_budget(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            repo = base / "repo"
            vault = base / "vault"
            self.write_project(repo, auto_load="是", auto_review="是")
            inbox = vault / "自动审核测试" / "知识库" / "收件箱"
            self.write_candidate(inbox, "candidate.json", index=1)
            current = vault / "自动审核测试" / "知识库" / "当前状态.md"
            current.parent.mkdir(parents=True, exist_ok=True)
            current.write_text("# 当前状态\n\n当前状态标记\n" + ("x" * 3000), encoding="utf-8")

            output = self.run_start(
                repo,
                vault,
                extra_env={
                    "CODEX_MEMORY_CONTEXT_CHARS": "800",
                    "CODEX_MEMORY_REVIEW_CHARS": "500",
                },
            )
            context = json.loads(output)["hookSpecificOutput"]["additionalContext"]
            self.assertLessEqual(len(context), 800)
            self.assertIn("当前状态标记", context)
            self.assertIn("session-1", context)

    def test_inbox_list_filters_pending_and_bounds_output(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            vault = base / "vault"
            inbox = vault / "自动审核测试" / "知识库" / "收件箱"
            self.write_candidate(inbox, "pending-1.json", index=1)
            self.write_candidate(inbox, "pending-2.json", index=2)
            self.write_candidate(inbox, "pending-3.json", index=3)
            self.write_candidate(inbox, "processed.json", status="processed", index=4)
            (inbox / "broken.json").write_text("{broken", encoding="utf-8")

            env = os.environ.copy()
            env["PYTHONDONTWRITEBYTECODE"] = "1"
            result = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    str(INBOX),
                    "--vault-root",
                    str(vault),
                    "--project",
                    "自动审核测试",
                    "list",
                    "--limit",
                    "1",
                    "--max-chars",
                    "800",
                ],
                capture_output=True,
                check=True,
                env=env,
            )
            text = result.stdout.decode("utf-8").strip()
            payload = json.loads(text)
            self.assertLessEqual(len(result.stdout.decode("utf-8")), 800)
            self.assertEqual(payload["pending"], 3)
            self.assertEqual(payload["invalid_count"], 1)
            self.assertEqual(payload["shown"], 1)
            self.assertEqual(payload["next_offset"], 1)
            self.assertTrue(payload["truncated"])
            self.assertEqual(len(payload["items"]), 1)
            self.assertNotIn("processed.json", text)

            page_two = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    str(INBOX),
                    "--vault-root",
                    str(vault),
                    "--project",
                    "自动审核测试",
                    "list",
                    "--offset",
                    "1",
                    "--limit",
                    "1",
                    "--max-chars",
                    "800",
                ],
                capture_output=True,
                check=True,
                env=env,
            )
            second = json.loads(page_two.stdout.decode("utf-8"))
            self.assertEqual(second["offset"], 1)
            self.assertEqual(second["shown"], 1)
            self.assertEqual(second["next_offset"], 2)


if __name__ == "__main__":
    unittest.main()
