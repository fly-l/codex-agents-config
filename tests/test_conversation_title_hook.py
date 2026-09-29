from __future__ import annotations

import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock
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
sys.path.insert(0, str(HOOK.parent))
import conversation_title_worker as worker


class ConversationTitleHookTests(unittest.TestCase):
    def test_organized_thread_never_starts_model(self) -> None:
        app = Mock()
        app.read_thread.return_value = {
            "id": "target", "title": "0905｜功能｜标题",
            "createdAt": "2026-09-04T16:30:00Z",
        }
        with patch.object(worker.subprocess, "run") as run, patch.object(worker.hook, "write_status") as status:
            worker.organize("target", None, app)
        run.assert_not_called()
        status.assert_called_once_with("target", "already_organized")

    def test_model_success_requires_readback(self) -> None:
        before = {"id": "target", "title": "旧标题", "createdAt": "2026-09-04T16:30:00Z"}
        cases = [
            ("0905｜修复｜标题", "verified", True),
            ("", "invalid_title", False),
            ("0906｜修复｜标题", "invalid_title", False),
        ]
        for title, expected, writes_title in cases:
            with self.subTest(title=title):
                app = Mock()
                app.read_thread.side_effect = [before, {**before, "title": title}] if writes_title else [before]
                with patch.object(worker.hook, "build_prompt", return_value="prompt"), \
                     patch.object(worker.hook, "build_command", return_value=["codex"]), \
                     patch.object(worker.hook, "write_status") as status, \
                     patch.object(worker.subprocess, "run", return_value=Mock(returncode=0, stdout=title)):
                    worker.organize("target", None, app)
                self.assertEqual(app.read_thread.call_count, 2 if writes_title else 1)
                if writes_title:
                    app.set_thread_title.assert_called_once_with(title)
                else:
                    app.set_thread_title.assert_not_called()
                status.assert_called_with("target", expected)

    def test_agent_failure_is_not_reported_as_verified(self) -> None:
        app = Mock()
        app.read_thread.return_value = {"id": "target", "title": "旧标题", "createdAt": 1788589288}
        with patch.object(worker.hook, "build_prompt", return_value="prompt"), \
             patch.object(worker.hook, "build_command", return_value=["codex"]), \
             patch.object(worker.hook, "write_status") as status, \
             patch.object(worker.subprocess, "run", return_value=Mock(returncode=7, stdout="")):
            worker.organize("target", None, app)
        status.assert_called_with("target", "agent_failed", returncode=7)
        app.read_thread.assert_called_once()
        app.set_thread_title.assert_not_called()

    def test_mcp_read_rejects_wrong_target(self) -> None:
        app = object.__new__(worker.AppTools)
        app.thread_id = "target"
        app.request = Mock(return_value={"content": [{"type": "text", "text": json.dumps({
            "thread": {"id": "other", "createdAt": 1788589288, "title": "标题"}
        })}]})
        with self.assertRaises(ValueError):
            app.read_thread("target")

    def test_missing_dependencies_are_diagnostic_without_spawning(self) -> None:
        with tempfile.TemporaryDirectory() as temp, \
             patch.dict(os.environ, {title_hook.LOG_ENV: temp, title_hook.APP_TOOLS_PIPE_ENV: ""}), \
             patch.object(title_hook.sys, "stdin", io.StringIO('{"session_id":"target"}')), \
             patch.object(title_hook.subprocess, "Popen") as popen:
            title_hook.main()
            log = json.loads(next(Path(temp).glob("*.jsonl")).read_text())
        popen.assert_not_called()
        self.assertEqual(log["status"], "missing_dependencies")
        self.assertIn("app_tools_pipe", log["missing"])

    def test_model_defaults_to_luna_without_app_tools(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            command = title_hook.build_command("codex", None)
        self.assertEqual(command[command.index("--model") + 1], "gpt-5.6-luna")
        self.assertEqual(command[command.index("--sandbox") + 1], "read-only")
        self.assertNotIn("mcp_servers.codex_app_tools", " ".join(command))

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

    def test_missing_stop_title_starts_one_shot_agent(self) -> None:
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
                "hook_event_name": "Stop",
                "cwd": str(repo),
                "transcript_path": str(base / "rollout.jsonl"),
            }
            environment = {
                "CODEX_RENAME_CURRENT_TITLE_SKILL": str(skill),
                "CODEX_APP_TOOLS_SERVER": str(server),
                "CODEX_APP_TOOLS_PIPE_PATH": r"\\.\pipe\test",
                "CODEX_MCP_NODE_PATH": "node",
                "CODEX_CLI_PATH": "codex",
                "CODEX_RENAME_CURRENT_TITLE_LOG": str(base / "logs"),
            }
            with patch.dict(os.environ, environment, clear=False):
                with patch.object(title_hook.subprocess, "Popen") as popen:
                    with patch.object(
                        title_hook.sys, "stdin", io.StringIO(json.dumps(event))
                    ):
                        title_hook.main()

            popen.assert_called_once()
            command = popen.call_args.args[0]
            self.assertEqual(command[0], sys.executable)
            self.assertEqual(Path(command[1]).name, "conversation_title_worker.py")
            self.assertEqual(command[2], "thread-unorganized")
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
            environment["PROJECT_MEMORY_VAULT"] = str(base / "vault")
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
            stop_commands = [
                hook["hooks"][0]["command"]
                for hook in installed["hooks"]["Stop"]
                if hook.get("hooks")
            ]
            self.assertEqual(
                sum("conversation_title_session_end.py" in command for command in stop_commands),
                1,
            )
            session_end_commands = [
                hook["hooks"][0]["command"]
                for hook in installed["hooks"]["SessionEnd"]
                if hook.get("hooks")
            ]
            self.assertEqual(
                sum("conversation_title_session_end.py" in command for command in session_end_commands),
                0,
            )
            self.assertEqual(
                sum("project_memory_session_end.py" in command for command in session_end_commands),
                0,
            )
            self.assertIn('"command": "keep"', rendered)
            self.assertEqual(len(installed["hooks"]["Stop"]), 2)
            self.assertEqual(len(installed["hooks"]["SessionEnd"]), 1)


if __name__ == "__main__":
    unittest.main()
