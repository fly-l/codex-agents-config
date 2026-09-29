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
SESSION_END = REPO_ROOT / "Hook" / "project_memory_session_end.py"


class HookInputTests(unittest.TestCase):
    @staticmethod
    def write_project(repo: Path, config: str) -> None:
        (repo / ".git").mkdir(parents=True)
        (repo / "AGENTS.md").write_text(config, encoding="utf-8")

    @staticmethod
    def run_hook(
        script: Path, event: dict, *, vault: Path, check: bool = True
    ) -> subprocess.CompletedProcess[bytes]:
        env = os.environ.copy()
        env["PROJECT_MEMORY_VAULT"] = str(vault)
        env["PYTHONUTF8"] = "0"
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        env.pop("PYTHONIOENCODING", None)
        env.pop("CODEX_RENAME_CURRENT_TITLE_CHILD", None)
        return subprocess.run(
            [sys.executable, str(script)],
            input=json.dumps(event, ensure_ascii=False).encode("utf-8"),
            capture_output=True,
            check=check,
            env=env,
        )

    def test_only_fenced_configuration_does_not_enable_hooks(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            repo = base / "中文工作区"
            vault = base / "临时Vault"
            self.write_project(
                repo,
                "# 配置示例\n"
                "````markdown\n"
                "```markdown\n"
                "## 知识体系\n"
                "- 启用：是\n"
                "- 项目名称：反引号示例\n"
                "```\n"
                "````\n"
                "~~~~~markdown\n"
                "~~~yaml\n"
                "## 知识体系\n"
                "- 启用：是\n"
                "- 项目名称：波浪号示例\n"
                "~~~\n"
                "~~~~~\n",
            )
            event = {
                "session_id": "示例会话",
                "cwd": str(repo),
                "transcript_path": str(base / "转录.jsonl"),
            }

            started = self.run_hook(SESSION_START, event, vault=vault)
            stopped = self.run_hook(SESSION_END, event, vault=vault)

            self.assertEqual(started.stdout, b"")
            self.assertEqual(json.loads(stopped.stdout.decode("utf-8")), {})
            self.assertFalse(vault.exists())

    def test_real_heading_after_fenced_examples_is_used_with_utf8_io(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            repo = base / "中文工作区"
            vault = base / "临时Vault"
            project = "真实项目"
            self.write_project(
                repo,
                "# 配置示例\n"
                "````markdown\n"
                "## 知识体系\n"
                "- 启用：是\n"
                "- 项目名称：错误项目\n"
                "````\n"
                "~~~~~markdown\n"
                "## 知识体系\n"
                "- 启用：是\n"
                "- 项目名称：另一个错误项目\n"
                "~~~~~\n"
                "## 知识体系\n"
                "- 启用：是\n"
                f"- 项目名称：{project}\n"
                "- 自动加载：是\n"
                "- 自动收集：是\n"
                "## 其他章节\n",
            )
            current = vault / project / "知识库" / "当前状态.md"
            current.parent.mkdir(parents=True)
            current.write_text("# 真实状态\n\n- 中文摘要已加载。\n", encoding="utf-8")
            transcript = base / "转录.jsonl"
            transcript.write_text("{}\n", encoding="utf-8")
            event = {
                "hook_event_name": "SessionStart",
                "session_id": "中文会话",
                "turn_id": "中文轮次",
                "cwd": str(repo),
                "transcript_path": str(transcript),
            }

            started = self.run_hook(SESSION_START, event, vault=vault)
            stopped = self.run_hook(SESSION_END, {**event, "hook_event_name": "Stop"}, vault=vault)

            self.assertIn("中文摘要已加载", started.stdout.decode("utf-8"))
            self.assertEqual(json.loads(stopped.stdout.decode("utf-8")), {})
            inbox = list((vault / project / "知识库" / "收件箱").glob("*.json"))
            self.assertEqual(len(inbox), 1)
            payload = json.loads(inbox[0].read_text(encoding="utf-8"))
            self.assertEqual(payload["project"], project)
            self.assertEqual(payload["cwd"], str(repo))
            self.assertEqual(payload["transcript_path"], str(transcript))

    def test_real_disabled_flags_override_enabled_example(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            repo = base / "中文工作区"
            vault = base / "临时Vault"
            project = "真实关闭"
            self.write_project(
                repo,
                "````markdown\n"
                "## 知识体系\n"
                "- 启用：是\n"
                "- 项目名称：示例项目\n"
                "- 自动加载：是\n"
                "- 自动收集：是\n"
                "````\n"
                "## 知识体系\n"
                "- 启用：是\n"
                f"- 项目名称：{project}\n"
                "- 自动加载：否\n"
                "- 自动收集：否\n",
            )
            event = {
                "session_id": "关闭会话",
                "cwd": str(repo),
                "transcript_path": str(base / "转录.jsonl"),
            }

            started = self.run_hook(SESSION_START, event, vault=vault)
            stopped = self.run_hook(SESSION_END, event, vault=vault)

            self.assertEqual(started.stdout, b"")
            self.assertEqual(json.loads(stopped.stdout.decode("utf-8")), {})
            self.assertFalse(vault.exists())


if __name__ == "__main__":
    unittest.main()
