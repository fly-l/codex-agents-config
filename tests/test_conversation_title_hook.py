from __future__ import annotations

import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[1]
HOOK = REPO_ROOT / "Hook" / "conversation_title_session_end.py"
INSTALL = REPO_ROOT / "Hook" / "install.py"
SESSION_END = REPO_ROOT / "Hook" / "project_memory_session_end.py"

spec = importlib.util.spec_from_file_location("conversation_title_session_end", HOOK)
assert spec and spec.loader
title_hook = importlib.util.module_from_spec(spec)
spec.loader.exec_module(title_hook)


class ConversationTitleHookTests(unittest.TestCase):
    def test_created_at_uses_shanghai_and_not_updated_at(self) -> None:
        self.assertEqual(
            title_hook.created_at_mmdd("2026-09-04T16:30:00Z"),
            "0905",
        )
        self.assertTrue(
            title_hook.is_organized_title(
                "0905｜功能｜标题",
                "2026-09-04T16:30:00Z",
            )
        )
        self.assertFalse(
            title_hook.is_organized_title(
                "0905｜功能｜标题",
                "2026-09-04T15:59:59Z",
            )
        )
        self.assertFalse(
            title_hook.is_organized_title(
                "0905｜功能｜标题",
                None,
            )
        )
        self.assertIsNone(
            title_hook.created_at_mmdd("2026-09-05 00:30:00")
        )

    def test_title_format_rejects_extra_separator_and_empty_parts(self) -> None:
        created_at = "2026-09-04T16:30:00Z"
        self.assertFalse(
            title_hook.is_organized_title("0905｜功能｜标题｜多余段", created_at)
        )
        self.assertFalse(title_hook.is_organized_title("0905｜｜标题", created_at))
        self.assertFalse(title_hook.is_organized_title("0905｜功能｜", created_at))
        self.assertFalse(
            title_hook.is_organized_title("0905｜功能｜ 标题", created_at)
        )

    def test_missing_event_title_starts_one_shot_agent(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            repo = base / "repo"
            repo.mkdir()
            skill = base / "SKILL.md"
            skill.write_text("# 标题 Skill\n", encoding="utf-8")
            server = base / "server.mjs"
            server.write_text("// test\n", encoding="utf-8")
            event = {
                "session_id": "thread-unorganized",
                "cwd": str(repo),
                "transcript_path": str(base / "rollout.jsonl"),
            }
            environment = {
                "CODEX_RENAME_CURRENT_TITLE_SKILL": str(skill),
                "CODEX_APP_TOOLS_SERVER": str(server),
                "CODEX_APP_TOOLS_PIPE_PATH": r"\\.\pipe\test",
                "CODEX_MCP_NODE_PATH": "node",
                "CODEX_CLI_PATH": "codex",
            }
            with patch.dict(os.environ, environment, clear=False):
                with patch.object(title_hook.subprocess, "Popen") as popen:
                    with patch.object(
                        title_hook.sys, "stdin", io.StringIO(json.dumps(event))
                    ):
                        title_hook.main()

            popen.assert_called_once()
            command = popen.call_args.args[0]
            self.assertEqual(
                command[0:7],
                [
                    "codex",
                    "exec",
                    "--ephemeral",
                    "--skip-git-repo-check",
                    "--sandbox",
                    "read-only",
                    "-C",
                ],
            )
            prompt = command[-1]
            self.assertIn("thread-unorganized", prompt)
            self.assertIn(skill.name, prompt)
            self.assertIn("createdAt", prompt)
            self.assertIn(
                'mcp_servers.codex_app_tools.tools.read_thread.approval_mode="approve"',
                command,
            )
            self.assertIn(
                'mcp_servers.codex_app_tools.tools.set_thread_title.approval_mode="approve"',
                command,
            )
            self.assertEqual(
                popen.call_args.kwargs["env"][title_hook.CHILD_ENV],
                "1",
            )

    def test_child_marker_prevents_recursion(self) -> None:
        with patch.dict(os.environ, {title_hook.CHILD_ENV: "1"}, clear=False):
            with patch.object(title_hook.subprocess, "Popen") as popen:
                with patch.object(title_hook.sys, "stdin", io.StringIO("not json")):
                    title_hook.main()
        popen.assert_not_called()

    def test_title_child_does_not_create_memory_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            repo = base / "repo"
            (repo / ".git").mkdir(parents=True)
            (repo / "AGENTS.md").write_text(
                "## 知识体系\n"
                "- 启用：是\n"
                "- 项目名称：标题子代理测试\n"
                "- 自动收集：是\n",
                encoding="utf-8",
            )
            environment = os.environ.copy()
            environment[title_hook.CHILD_ENV] = "1"
            environment["CODEX_MEMORY_VAULT"] = str(base / "vault")
            event = {
                "session_id": "title-child",
                "cwd": str(repo),
                "reason": "other",
            }
            subprocess.run(
                [sys.executable, str(SESSION_END)],
                input=json.dumps(event),
                text=True,
                capture_output=True,
                check=True,
                env=environment,
            )
            self.assertFalse((base / "vault").exists())

    def test_codex_installer_registers_and_deduplicates_title_hook(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / "hooks.json"
            original = {
                "description": "保留",
                "hooks": {
                    "SessionEnd": [
                        {
                            "matcher": "other",
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": "old/conversation_title_session_end.py",
                                },
                                {"type": "command", "command": "keep"},
                            ],
                        },
                    ]
                },
            }
            target.write_text(json.dumps(original, ensure_ascii=False), encoding="utf-8")
            command = [
                "python",
                str(INSTALL),
                "--target",
                str(target),
            ]
            subprocess.run(
                [*command, "--dry-run"],
                text=True,
                capture_output=True,
                check=True,
            )
            self.assertEqual(json.loads(target.read_text(encoding="utf-8")), original)

            subprocess.run(command, text=True, capture_output=True, check=True)
            installed = json.loads(target.read_text(encoding="utf-8"))
            rendered = json.dumps(installed, ensure_ascii=False)
            session_end_commands = [
                hook["hooks"][0]["command"]
                for hook in installed["hooks"]["SessionEnd"]
                if hook.get("hooks")
            ]
            self.assertEqual(
                sum("conversation_title_session_end.py" in command for command in session_end_commands),
                1,
            )
            self.assertEqual(
                sum("project_memory_session_end.py" in command for command in session_end_commands),
                1,
            )
            self.assertIn('"command": "keep"', rendered)
            self.assertEqual(len(installed["hooks"]["SessionEnd"]), 3)


if __name__ == "__main__":
    unittest.main()
