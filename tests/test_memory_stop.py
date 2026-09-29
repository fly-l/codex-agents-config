from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
STOP_HOOK = REPO_ROOT / "Hook" / "project_memory_session_end.py"
CODEX_INSTALLER = REPO_ROOT / "Hook" / "install.py"
CLAUDE_INSTALLER = REPO_ROOT / "Hook" / "install_claude.py"


class MemoryStopTests(unittest.TestCase):
    def write_project(self, repo: Path, project: str = "Stop测试") -> None:
        (repo / ".git").mkdir(parents=True)
        config = (
            "## 知识体系\n"
            "- 启用：是\n"
            f"- 项目名称：{project}\n"
            "- 自动收集：是\n"
        )
        (repo / "AGENTS.md").write_text(config, encoding="utf-8")
        (repo / "CLAUDE.md").write_text(config, encoding="utf-8")

    def run_stop(
        self,
        event: dict,
        vault: Path,
        *,
        host: str = "codex",
        child: bool = False,
    ) -> subprocess.CompletedProcess[bytes]:
        env = os.environ.copy()
        vault_env = {
            "codex": "PROJECT_MEMORY_VAULT",
            "claude": "PROJECT_MEMORY_VAULT",
            "pi": "PROJECT_MEMORY_VAULT",
        }[host]
        env[vault_env] = str(vault)
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        env["PYTHONUTF8"] = "0"
        env.pop("PYTHONIOENCODING", None)
        env.pop("CODEX_RENAME_CURRENT_TITLE_CHILD", None)
        if child:
            env["CODEX_RENAME_CURRENT_TITLE_CHILD"] = "1"
        command = [sys.executable, str(STOP_HOOK)]
        if host != "codex":
            command.extend(["--host", host])
        return subprocess.run(
            command,
            input=json.dumps(event, ensure_ascii=False).encode("utf-8"),
            text=False,
            capture_output=True,
            check=True,
            env=env,
        )

    @staticmethod
    def read_inbox(vault: Path, project: str = "Stop测试") -> list[Path]:
        return sorted((vault / project / "知识库" / "收件箱").glob("*.json"))

    @staticmethod
    def execution_texts(hook: dict) -> list[str]:
        values: list[str] = []
        for key in ("command", "commandWindows", "args"):
            value = hook.get(key)
            if isinstance(value, list):
                values.extend(str(item) for item in value)
            elif isinstance(value, (str, int, float)):
                values.append(str(value))
        return values

    def test_codex_install_migrates_and_preserves_custom_group(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / "hooks.json"
            original = {
                "description": "保留",
                "hooks": {
                    "Stop": [
                        {
                            "matcher": "custom-stop",
                            "description": "自定义组",
                            "metadata": {"keep": True},
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": "keep-stop",
                                    "description": "提及 project_memory_session_end.py",
                                },
                                {
                                    "type": "command",
                                    "command": "old/conversation_title_session_end.py",
                                },
                            ],
                        }
                    ],
                    "SessionEnd": [
                        {
                            "matcher": "legacy",
                            "description": "说明 project_memory_session_end.py 但不是执行命令",
                            "metadata": {"keep": "legacy"},
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": "old/project_memory_session_end.py",
                                },
                                {
                                    "type": "command",
                                    "command": "keep-legacy",
                                    "description": "project_memory_session_end.py",
                                },
                            ],
                        }
                    ],
                },
            }
            target.write_text(json.dumps(original, ensure_ascii=False), encoding="utf-8")

            dry_run = subprocess.run(
                [sys.executable, str(CODEX_INSTALLER), "--target", str(target), "--dry-run"],
                text=True,
                capture_output=True,
                check=True,
            )
            preview = json.loads(dry_run.stdout)
            self.assertEqual(preview["description"], original["description"])
            self.assertIn("Stop", preview["hooks"])
            self.assertEqual(
                json.loads(target.read_text(encoding="utf-8")), original
            )

            command = [sys.executable, str(CODEX_INSTALLER), "--target", str(target)]
            subprocess.run(command, text=True, capture_output=True, check=True)
            first = json.loads(target.read_text(encoding="utf-8"))
            subprocess.run(command, text=True, capture_output=True, check=True)
            second = json.loads(target.read_text(encoding="utf-8"))
            self.assertEqual(second, first)

            stop_groups = first["hooks"]["Stop"]
            stop_handlers = [hook for group in stop_groups for hook in group["hooks"]]
            self.assertEqual(
                sum(
                    any(
                        "conversation_title_session_end.py" in text
                        for text in self.execution_texts(hook)
                    )
                    for hook in stop_handlers
                ),
                1,
            )
            self.assertEqual(
                sum(
                    any(
                        "project_memory_session_end.py" in text
                        for text in self.execution_texts(hook)
                    )
                    for hook in stop_handlers
                ),
                1,
            )
            custom_stop = next(group for group in stop_groups if group.get("matcher") == "custom-stop")
            self.assertEqual(custom_stop["metadata"], {"keep": True})
            self.assertEqual(len(custom_stop["hooks"]), 1)
            self.assertEqual(custom_stop["hooks"][0]["command"], "keep-stop")

            legacy = first["hooks"]["SessionEnd"]
            self.assertEqual(len(legacy), 1)
            self.assertEqual(legacy[0]["matcher"], "legacy")
            self.assertEqual(legacy[0]["metadata"], {"keep": "legacy"})
            self.assertEqual(legacy[0]["hooks"][0]["command"], "keep-legacy")

    def test_claude_install_migrates_only_managed_execution_handler(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / "settings.json"
            original = {
                "model": "custom",
                "hooks": {
                    "SessionEnd": [
                        {
                            "matcher": "legacy",
                            "description": "project_memory_session_end.py 说明",
                            "metadata": {"keep": True},
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": sys.executable,
                                    "args": ["old/project_memory_session_end.py", "--host", "claude"],
                                },
                                {
                                    "type": "command",
                                    "command": "keep",
                                    "description": "project_memory_session_end.py",
                                },
                            ],
                        }
                    ]
                },
            }
            target.write_text(json.dumps(original, ensure_ascii=False), encoding="utf-8")
            command = [sys.executable, str(CLAUDE_INSTALLER), "--target", str(target)]
            subprocess.run(command, text=True, capture_output=True, check=True)
            installed = json.loads(target.read_text(encoding="utf-8"))

            self.assertEqual(installed["model"], "custom")
            self.assertIn("Stop", installed["hooks"])
            legacy = installed["hooks"]["SessionEnd"][0]
            self.assertEqual(legacy["matcher"], "legacy")
            self.assertEqual(legacy["metadata"], {"keep": True})
            self.assertEqual(legacy["hooks"][0]["command"], "keep")
            self.assertEqual(
                legacy["hooks"][0].get("description"),
                "project_memory_session_end.py",
            )
            stop = [group for group in installed["hooks"]["Stop"] if group.get("hooks")]
            self.assertEqual(len(stop), 1)
            self.assertEqual(stop[0]["hooks"][0]["args"][-2:], ["--host", "claude"])
            self.assertNotIn("matcher", stop[0])

    def test_stop_is_stable_and_keeps_processed_candidate_until_new_version(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            repo = base / "repo"
            vault = base / "vault"
            self.write_project(repo)
            transcript = base / "transcript.jsonl"
            transcript.write_text("{}\n", encoding="utf-8")
            event = {
                "hook_event_name": "Stop",
                "session_id": "session/one",
                "turn_id": "turn-1",
                "cwd": str(repo),
                "transcript_path": str(transcript),
                "reason": "other",
            }

            first = self.run_stop(event, vault)
            self.assertEqual(json.loads(first.stdout), {})
            inbox = self.read_inbox(vault)
            self.assertEqual(len(inbox), 1)
            self.assertIn("session-one-", inbox[0].name)
            payload = json.loads(inbox[0].read_text(encoding="utf-8"))
            self.assertEqual(payload["host"], "codex")
            self.assertEqual(payload["session_id"], "session/one")
            self.assertEqual(payload["turn_id"], "turn-1")
            self.assertEqual(payload["transcript_size"], transcript.stat().st_size)
            self.assertEqual(payload["transcript_mtime_ns"], transcript.stat().st_mtime_ns)
            self.assertTrue(payload["updated_at"])

            before_bytes = inbox[0].read_bytes()
            before_stat = inbox[0].stat()
            time.sleep(0.01)
            second = self.run_stop(event, vault)
            self.assertEqual(json.loads(second.stdout), {})
            self.assertEqual(inbox[0].read_bytes(), before_bytes)
            self.assertEqual(inbox[0].stat().st_mtime_ns, before_stat.st_mtime_ns)

            processed = dict(payload)
            processed["status"] = "processed"
            processed["processed_at"] = "2026-09-08T00:00:00+00:00"
            inbox[0].write_text(json.dumps(processed, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            processed_bytes = inbox[0].read_bytes()
            self.run_stop(event, vault)
            self.assertEqual(inbox[0].read_bytes(), processed_bytes)
            self.assertEqual(json.loads(inbox[0].read_text(encoding="utf-8"))["status"], "processed")

            self.run_stop({**event, "turn_id": "turn-2"}, vault)
            renewed = json.loads(inbox[0].read_text(encoding="utf-8"))
            self.assertEqual(renewed["status"], "pending")
            self.assertEqual(renewed["turn_id"], "turn-2")
            self.assertNotIn("processed_at", renewed)

            ignored = dict(renewed)
            ignored["status"] = "ignored"
            ignored["processed_at"] = "2026-09-08T00:00:00+00:00"
            inbox[0].write_text(json.dumps(ignored, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            ignored_bytes = inbox[0].read_bytes()
            self.run_stop({**event, "turn_id": "turn-2"}, vault)
            self.assertEqual(inbox[0].read_bytes(), ignored_bytes)
            self.assertEqual(json.loads(inbox[0].read_text(encoding="utf-8"))["status"], "ignored")

            transcript.write_text("changed\n", encoding="utf-8")
            self.run_stop({**event, "turn_id": "turn-2"}, vault)
            changed = json.loads(inbox[0].read_text(encoding="utf-8"))
            self.assertEqual(changed["status"], "pending")
            self.assertNotIn("processed_at", changed)
            self.assertNotEqual(changed["transcript_size"], ignored["transcript_size"])

    def test_stop_requires_identity_and_skips_title_child_and_active_stop(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            repo = base / "repo"
            vault = base / "vault"
            self.write_project(repo)
            common = {"cwd": str(repo), "transcript_path": str(base / "missing.jsonl")}

            for event, child in (
                ({**common}, False),
                ({**common, "session_id": "child", "turn_id": "turn-1"}, True),
                ({**common, "session_id": "active", "turn_id": "turn-1", "stop_hook_active": True}, False),
            ):
                result = self.run_stop(event, vault, child=child)
                self.assertEqual(json.loads(result.stdout), {})
            self.assertFalse(vault.exists())

    def test_host_is_part_of_stable_candidate_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            repo = base / "repo"
            vault = base / "vault"
            self.write_project(repo, "同名会话")
            transcript = base / "transcript.jsonl"
            transcript.write_text("x\n", encoding="utf-8")
            event = {
                "session_id": "same-session",
                "turn_id": "turn-1",
                "cwd": str(repo),
                "transcript_path": str(transcript),
            }
            self.run_stop(event, vault, host="codex")
            self.run_stop(event, vault, host="claude")
            self.run_stop(event, vault, host="pi")
            inbox = self.read_inbox(vault, "同名会话")
            self.assertEqual(len(inbox), 3)
            self.assertEqual(
                {json.loads(path.read_text(encoding="utf-8"))["host"] for path in inbox},
                {"codex", "claude", "pi"},
            )


if __name__ == "__main__":
    unittest.main()
