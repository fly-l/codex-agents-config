from __future__ import annotations

import json
import hashlib
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
SESSION_START = REPO_ROOT / "Hook" / "project_memory_session_start.py"
SESSION_END = REPO_ROOT / "Hook" / "project_memory_session_end.py"
INSTALL_CLAUDE = REPO_ROOT / "Hook" / "install_claude.py"


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

    def run_maintenance(
        self, vault: Path, project: str, *args: str
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                str(MAINTENANCE),
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

    def test_claude_hooks_read_claude_config(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            repo = base / "repo"
            vault = base / "vault"
            (repo / ".git").mkdir(parents=True)
            (repo / "AGENTS.md").write_text(
                "## 知识体系\n"
                "- 启用：是\n"
                "- 项目名称：错误项目\n",
                encoding="utf-8",
            )
            (repo / "CLAUDE.md").write_text(
                "## 知识体系\n"
                "- 启用：是\n"
                "- 项目名称：Claude测试\n"
                "- 自动加载：是\n"
                "- 自动收集：是\n",
                encoding="utf-8",
            )
            self.run_store(vault, "Claude测试", "init")
            current = vault / "Claude测试" / "知识库" / "当前状态.md"
            current.write_text("# 当前状态\n\n- Claude Hook 已加载。\n", encoding="utf-8")
            transcript = base / "claude-transcript.jsonl"
            transcript.write_text("{}\n", encoding="utf-8")
            event = {
                "session_id": "claude_test",
                "transcript_path": str(transcript),
                "cwd": str(repo),
                "reason": "other",
            }
            env = os.environ.copy()
            env["CLAUDE_MEMORY_VAULT"] = str(vault)
            env["CODEX_MEMORY_VAULT"] = str(base / "wrong-vault")

            started = subprocess.run(
                [sys.executable, str(SESSION_START), "--host", "claude"],
                input=json.dumps({**event, "hook_event_name": "SessionStart"}),
                text=True,
                capture_output=True,
                check=True,
                env=env,
            )
            self.assertIn("Claude Hook 已加载", started.stdout)

            subprocess.run(
                [sys.executable, str(SESSION_END), "--host", "claude"],
                input=json.dumps({**event, "hook_event_name": "SessionEnd"}),
                text=True,
                capture_output=True,
                check=True,
                env=env,
            )
            inbox = list((vault / "Claude测试" / "知识库" / "收件箱").glob("*.json"))
            self.assertEqual(len(inbox), 1)

    def test_claude_hook_installer_merges_backs_up_and_deduplicates(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / ".claude" / "settings.json"
            target.parent.mkdir(parents=True)
            original = {
                "model": "custom-model",
                "hooks": {
                    "SessionStart": [
                        {
                            "matcher": "startup",
                            "hooks": [
                                {"type": "command", "command": "keep-existing-hook"}
                            ],
                        }
                    ]
                },
            }
            target.write_text(
                json.dumps(original, ensure_ascii=False), encoding="utf-8"
            )

            dry_run = subprocess.run(
                [
                    sys.executable,
                    str(INSTALL_CLAUDE),
                    "--target",
                    str(target),
                    "--dry-run",
                ],
                text=True,
                capture_output=True,
                check=True,
            )
            preview = json.loads(dry_run.stdout)
            self.assertEqual(preview["model"], "custom-model")
            self.assertEqual(
                json.loads(target.read_text(encoding="utf-8")), original
            )

            command = [
                sys.executable,
                str(INSTALL_CLAUDE),
                "--target",
                str(target),
            ]
            subprocess.run(command, text=True, capture_output=True, check=True)
            backup = target.with_suffix(".json.bak")
            self.assertEqual(json.loads(backup.read_text(encoding="utf-8")), original)

            subprocess.run(command, text=True, capture_output=True, check=True)
            installed = json.loads(target.read_text(encoding="utf-8"))
            self.assertEqual(installed["model"], "custom-model")
            rendered = json.dumps(installed, ensure_ascii=False)
            self.assertEqual(rendered.count("project_memory_session_start.py"), 1)
            self.assertEqual(rendered.count("project_memory_session_end.py"), 1)
            self.assertIn("keep-existing-hook", rendered)
            for event in ("SessionStart", "SessionEnd"):
                ours = [
                    item
                    for item in installed["hooks"][event]
                    if "project_memory_session_" in json.dumps(item)
                ]
                self.assertEqual(ours[0]["hooks"][0]["args"][-2:], ["--host", "claude"])

    def test_supersede_splits_active_history_and_audits_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            vault = Path(temp) / "vault"
            project = "维护测试"
            self.run_store(vault, project, "init")
            self.run_store(
                vault,
                project,
                "upsert",
                "--kind",
                "architecture",
                "--id",
                "ARCH-memory-v1",
                "--title",
                "旧召回结构",
                "--body",
                "索引包含全部记录。",
                "--status",
                "active",
                "--source",
                "test",
                "--module",
                "memory",
            )
            consolidated = self.run_store(
                vault,
                project,
                "upsert",
                "--kind",
                "architecture",
                "--id",
                "ARCH-memory-current",
                "--title",
                "当前召回结构",
                "--body",
                "活跃索引与历史索引分离。",
                "--status",
                "active",
                "--source",
                "test",
                "--module",
                "memory",
                "--supersedes",
                "ARCH-memory-v1",
            )
            self.assertEqual(json.loads(consolidated.stdout)["superseded"], ["ARCH-memory-v1"])

            root = vault / project / "知识库"
            old = (root / "架构" / "ARCH-memory-v1.md").read_text(encoding="utf-8")
            active_index = (root / "索引.md").read_text(encoding="utf-8")
            history_index = (root / "历史索引.md").read_text(encoding="utf-8")
            self.assertIn('status: "superseded"', old)
            self.assertIn('superseded_by: "ARCH-memory-current"', old)
            self.assertNotIn("ARCH-memory-v1", active_index)
            self.assertIn("ARCH-memory-current", active_index)
            self.assertIn("ARCH-memory-v1", history_index)

            self.run_store(
                vault,
                project,
                "upsert",
                "--kind",
                "architecture",
                "--id",
                "ARCH-memory-limit",
                "--title",
                "召回字符上限",
                "--body",
                "召回入口必须有字符上限。",
                "--status",
                "active",
                "--source",
                "test",
                "--module",
                "memory",
            )
            before_audit = {
                path.relative_to(root): path.read_bytes()
                for path in root.rglob("*")
                if path.is_file()
            }
            audit = self.run_store(vault, project, "maintenance-audit")
            payload = json.loads(audit.stdout)
            self.assertEqual(payload["active_records"], 2)
            self.assertEqual(payload["historical_records"], 1)
            self.assertEqual(payload["candidate_groups"][0]["records"], 2)
            after_audit = {
                path.relative_to(root): path.read_bytes()
                for path in root.rglob("*")
                if path.is_file()
            }
            self.assertEqual(before_audit, after_audit)
            validated = self.run_store(vault, project, "validate")
            self.assertTrue(json.loads(validated.stdout)["ok"])

    def test_summary_fingerprint_detects_stale_knowledge(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            vault = base / "vault"
            project = "摘要测试"
            self.run_store(vault, project, "init")
            self.run_store(
                vault,
                project,
                "upsert",
                "--kind",
                "architecture",
                "--id",
                "ARCH-summary-source",
                "--title",
                "摘要来源",
                "--body",
                "活跃索引与历史索引分离。",
                "--status",
                "active",
                "--source",
                "test",
            )
            body = base / "summary.md"
            body.write_text(
                "- 活跃知识与历史知识分层。来源：ARCH-summary-source\n",
                encoding="utf-8",
            )
            self.run_maintenance(
                vault,
                project,
                "write-summary",
                "--body-file",
                str(body),
                "--source-id",
                "ARCH-summary-source",
                "--coverage",
                "complete",
            )
            fresh = json.loads(
                self.run_store(vault, project, "maintenance-audit").stdout
            )
            self.assertFalse(fresh["summary"]["stale"])
            self.assertTrue(fresh["summary"]["usable"])

            record = (
                vault
                / project
                / "知识库"
                / "架构"
                / "ARCH-summary-source.md"
            )
            original_record = record.read_text(encoding="utf-8")
            record.write_text(
                original_record.replace(
                    "活跃索引与历史索引分离。",
                    "正文被手工修改但 frontmatter 指纹未更新。",
                ),
                encoding="utf-8",
            )
            tampered_light = json.loads(
                self.run_store(vault, project, "maintenance-audit").stdout
            )
            tampered_deep = json.loads(
                self.run_maintenance(vault, project, "audit").stdout
            )
            self.assertTrue(tampered_light["summary"]["stale"])
            self.assertTrue(tampered_deep["summary"]["stale"])
            record.write_text(original_record, encoding="utf-8")

            self.run_store(
                vault,
                project,
                "upsert",
                "--kind",
                "convention",
                "--id",
                "CONV-summary-limit",
                "--title",
                "摘要长度限制",
                "--body",
                "摘要不得超过硬上限。",
                "--status",
                "active",
                "--source",
                "test",
            )
            stale = json.loads(
                self.run_maintenance(vault, project, "audit").stdout
            )
            self.assertTrue(stale["summary"]["stale"])
            with self.assertRaises(subprocess.CalledProcessError):
                self.run_maintenance(
                    vault,
                    project,
                    "write-summary",
                    "--body-file",
                    str(body),
                    "--source-id",
                    "ARCH-summary-source",
                    "--coverage",
                    "complete",
                )

    def test_exact_duplicate_can_be_consolidated_without_deleting_history(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            vault = Path(temp) / "vault"
            project = "精确去重测试"
            self.run_store(vault, project, "init")
            common = (
                "--kind",
                "convention",
                "--title",
                "稳定 ID 约定",
                "--body",
                "同一主题始终更新稳定 ID。",
                "--status",
                "active",
                "--source",
                "test",
                "--module",
                "memory",
            )
            self.run_store(
                vault,
                project,
                "upsert",
                "--id",
                "CONV-id-v1",
                *common,
            )
            consolidated = self.run_store(
                vault,
                project,
                "upsert",
                "--id",
                "CONV-id-current",
                *common,
                "--supersedes",
                "CONV-id-v1",
            )
            self.assertEqual(json.loads(consolidated.stdout)["action"], "created")
            validated = self.run_store(vault, project, "validate")
            self.assertTrue(json.loads(validated.stdout)["ok"])

            root = vault / project / "知识库"
            self.assertIn(
                "CONV-id-current",
                (root / "索引.md").read_text(encoding="utf-8"),
            )
            self.assertIn(
                "CONV-id-v1",
                (root / "历史索引.md").read_text(encoding="utf-8"),
            )

    def test_active_index_has_hard_context_limits(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            vault = Path(temp) / "vault"
            project = "索引上限测试"
            self.run_store(vault, project, "init")
            folder = vault / project / "知识库" / "约定"
            for index in range(75):
                record_id = f"CONV-limit-{index:03d}"
                title = f"上下文限制规则 {index:03d}"
                body = f"这是第 {index:03d} 条独立且仍有效的规则。"
                digest_payload = json.dumps(
                    {
                        "type": "convention",
                        "title": title.casefold(),
                        "body": body.casefold(),
                        "module": [],
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                )
                digest = hashlib.sha256(digest_payload.encode("utf-8")).hexdigest()
                (folder / f"{record_id}.md").write_text(
                    "---\n"
                    f'id: "{record_id}"\n'
                    'type: "convention"\n'
                    'status: "active"\n'
                    f'title: "{title}"\n'
                    f'project: "{project}"\n'
                    "module: []\n"
                    'source: "test"\n'
                    "created: 2026-08-31\n"
                    "updated: 2026-08-31\n"
                    "verified_at: 2026-08-31\n"
                    "supersedes: []\n"
                    f'fingerprint: "{digest}"\n'
                    "---\n\n"
                    f"# {record_id}: {title}\n\n"
                    "## 内容\n\n"
                    f"{body}\n",
                    encoding="utf-8",
                )

            self.run_store(vault, project, "rebuild-indexes")
            active_index = (
                vault / project / "知识库" / "索引.md"
            ).read_text(encoding="utf-8")
            self.assertLessEqual(len(active_index), 6000)
            self.assertLessEqual(active_index.count("[[约定/"), 60)
            self.assertIn("未展示的活跃记录", active_index)
            validated = self.run_store(vault, project, "validate")
            self.assertTrue(json.loads(validated.stdout)["ok"])


if __name__ == "__main__":
    unittest.main()
