from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
import textwrap
import time
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
HOOK = REPO_ROOT / "Hook" / "project_memory_session_end.py"
STORE = REPO_ROOT / "Skills" / "project-memory" / "scripts" / "memory_store.py"
LOCK_MODULE = STORE.parent / "memory_inbox.py"

WORKER = textwrap.dedent(
    """
    import sys
    import time
    from pathlib import Path

    sys.path.insert(0, sys.argv[1])
    from memory_inbox import candidate_lock

    target = Path(sys.argv[2])
    log = Path(sys.argv[3])
    started = Path(sys.argv[4])
    release = Path(sys.argv[5])
    token = sys.argv[6]
    started.write_text("started", encoding="utf-8")
    with candidate_lock(target):
        with log.open("a", encoding="utf-8", newline="") as stream:
            stream.write(token + ":entered\\n")
            stream.flush()
        while not release.exists():
            time.sleep(0.01)
        with log.open("a", encoding="utf-8", newline="") as stream:
            stream.write(token + ":leaving\\n")
            stream.flush()
    """
)


class InboxConcurrencyTests(unittest.TestCase):
    @staticmethod
    def finish_process(process: subprocess.Popen) -> None:
        if process.poll() is None:
            process.kill()
        process.communicate(timeout=5)

    def setUp(self) -> None:
        self.env = os.environ.copy()
        self.env["PYTHONUTF8"] = "1"
        self.env["PYTHONDONTWRITEBYTECODE"] = "1"

    @staticmethod
    def wait_until(predicate, timeout: float = 5.0) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate():
                return
            time.sleep(0.01)
        raise AssertionError("等待临时进程或文件状态超时")

    def start_worker(
        self,
        target: Path,
        log: Path,
        started: Path,
        release: Path,
        token: str,
    ) -> subprocess.Popen[bytes]:
        process = subprocess.Popen(
            [
                sys.executable,
                "-B",
                "-c",
                WORKER,
                str(LOCK_MODULE.parent),
                str(target),
                str(log),
                str(started),
                str(release),
                token,
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=self.env,
        )
        self.addCleanup(self.finish_process, process)
        return process

    def test_independent_processes_are_mutually_exclusive(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            target = base / "candidate.json"
            log = base / "lock.log"
            first_started = base / "first.started"
            second_started = base / "second.started"
            release = base / "release"
            first = self.start_worker(
                target, log, first_started, release, "first"
            )
            second = None
            try:
                self.wait_until(first_started.exists)
                self.wait_until(
                    lambda: log.exists() and "first:entered\n" in log.read_text(encoding="utf-8")
                )
                second = self.start_worker(
                    target, log, second_started, release, "second"
                )
                self.wait_until(second_started.exists)
                time.sleep(0.2)
                self.assertNotIn(
                    "second:entered\n", log.read_text(encoding="utf-8")
                )
                release.write_text("release", encoding="utf-8")
                first_output, first_error = first.communicate(timeout=5)
                second_output, second_error = second.communicate(timeout=5)
                self.assertEqual(first.returncode, 0, first_error.decode(errors="replace"))
                self.assertEqual(second.returncode, 0, second_error.decode(errors="replace"))
                self.assertEqual(
                    log.read_text(encoding="utf-8").splitlines(),
                    ["first:entered", "first:leaving", "second:entered", "second:leaving"],
                )
                self.assertTrue(target.with_suffix(".lock").exists())
            finally:
                release.touch()
                for process in (first, second):
                    if process is not None and process.poll() is None:
                        process.kill()
                        process.wait()

    def write_project(self, repo: Path, project: str = "InboxTest") -> None:
        (repo / ".git").mkdir(parents=True)
        (repo / "AGENTS.md").write_text(
            "## 知识体系\n"
            "- 启用：是\n"
            f"- 项目名称：{project}\n"
            "- 自动收集：是\n",
            encoding="utf-8",
        )

    def run_stop(
        self,
        repo: Path,
        vault: Path,
        transcript: Path,
        turn_id: str,
        session_id: str = "session",
    ) -> subprocess.CompletedProcess[bytes]:
        event = {
            "hook_event_name": "Stop",
            "session_id": session_id,
            "turn_id": turn_id,
            "cwd": str(repo),
            "transcript_path": str(transcript),
            "reason": "other",
        }
        env = self.env.copy()
        env["PROJECT_MEMORY_VAULT"] = str(vault)
        result = subprocess.run(
            [sys.executable, "-B", str(HOOK)],
            input=json.dumps(event, ensure_ascii=False).encode("utf-8"),
            capture_output=True,
            env=env,
        )
        self.assertEqual(
            result.returncode,
            0,
            result.stderr.decode("utf-8", errors="replace"),
        )
        return result

    def read_candidate(self, vault: Path, project: str = "InboxTest") -> tuple[Path, dict]:
        candidates = list((vault / project / "知识库" / "收件箱").glob("*.json"))
        self.assertEqual(len(candidates), 1)
        target = candidates[0]
        return target, json.loads(target.read_text(encoding="utf-8"))

    def run_mark(
        self,
        vault: Path,
        project: str,
        filename: str,
        expected: str,
        status: str = "processed",
    ) -> subprocess.CompletedProcess[bytes]:
        env = self.env.copy()
        result = subprocess.run(
            [
                sys.executable,
                "-B",
                str(STORE),
                "--vault-root",
                str(vault),
                "--project",
                project,
                "mark-inbox",
                "--file",
                filename,
                "--status",
                status,
                "--expected-updated-at",
                expected,
            ],
            capture_output=True,
            env=env,
        )
        return result

    def create_candidate(self, base: Path, turn_id: str = "turn-1") -> tuple[Path, Path, Path, dict]:
        repo = base / "repo"
        vault = base / "vault"
        transcript = base / "transcript.jsonl"
        self.write_project(repo)
        transcript.write_text("{}\n", encoding="utf-8")
        self.run_stop(repo, vault, transcript, turn_id)
        target, payload = self.read_candidate(vault)
        return repo, vault, transcript, payload

    def test_locked_hook_and_mark_do_not_lose_new_stop(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            repo, vault, transcript, first_payload = self.create_candidate(base)
            target, _ = self.read_candidate(vault)
            log = base / "holder.log"
            started = base / "holder.started"
            release = base / "holder.release"
            holder = self.start_worker(target, log, started, release, "holder")
            mark = None
            hook_result: dict[str, subprocess.CompletedProcess[bytes]] = {}
            hook_thread = None
            try:
                self.wait_until(started.exists)
                self.wait_until(
                    lambda: log.exists() and "holder:entered\n" in log.read_text(encoding="utf-8")
                )
                mark = subprocess.Popen(
                    [
                        sys.executable,
                        "-B",
                        str(STORE),
                        "--vault-root",
                        str(vault),
                        "--project",
                        "InboxTest",
                        "mark-inbox",
                        "--file",
                        target.name,
                        "--status",
                        "processed",
                        "--expected-updated-at",
                        str(first_payload["updated_at"]),
                    ],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    env=self.env,
                )
                self.addCleanup(self.finish_process, mark)
                time.sleep(0.1)
                hook_event = {
                    "hook_event_name": "Stop",
                    "session_id": "session",
                    "turn_id": "turn-2",
                    "cwd": str(repo),
                    "transcript_path": str(transcript),
                    "reason": "other",
                }
                hook_env = self.env.copy()
                hook_env["PROJECT_MEMORY_VAULT"] = str(vault)
                hook_input = json.dumps(hook_event, ensure_ascii=False).encode("utf-8")

                def run_hook() -> None:
                    hook_result["result"] = subprocess.run(
                        [sys.executable, "-B", str(HOOK)],
                        input=hook_input,
                        capture_output=True,
                        env=hook_env,
                    )

                hook_thread = threading.Thread(target=run_hook)
                hook_thread.start()
                time.sleep(0.1)
            finally:
                release.touch()
            holder.communicate(timeout=5)
            if mark is not None:
                mark_output, mark_error = mark.communicate(timeout=5)
                self.assertIn(mark.returncode, (0, 3), mark_error.decode(errors="replace"))
            if hook_thread is not None:
                hook_thread.join(timeout=5)
                self.assertFalse(hook_thread.is_alive())
                completed_hook = hook_result["result"]
                self.assertEqual(
                    completed_hook.returncode,
                    0,
                    completed_hook.stderr.decode("utf-8", errors="replace"),
                )
            _, final = self.read_candidate(vault)
            self.assertEqual(final["turn_id"], "turn-2")
            self.assertEqual(final["status"], "pending")
            self.assertNotIn("processed_at", final)

    def test_old_token_is_rejected_after_new_stop(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            repo, vault, transcript, first_payload = self.create_candidate(base)
            target, _ = self.read_candidate(vault)
            self.run_stop(repo, vault, transcript, "turn-2")
            result = self.run_mark(
                vault,
                "InboxTest",
                target.name,
                str(first_payload["updated_at"]),
            )
            self.assertEqual(result.returncode, 3, result.stderr.decode(errors="replace"))
            _, final = self.read_candidate(vault)
            self.assertEqual(final["turn_id"], "turn-2")
            self.assertEqual(final["status"], "pending")

    def test_processed_candidate_is_reset_by_new_stop(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            repo, vault, transcript, first_payload = self.create_candidate(base)
            target, _ = self.read_candidate(vault)
            marked = self.run_mark(
                vault,
                "InboxTest",
                target.name,
                str(first_payload["updated_at"]),
            )
            self.assertEqual(marked.returncode, 0, marked.stderr.decode(errors="replace"))
            self.run_stop(repo, vault, transcript, "turn-2")
            _, final = self.read_candidate(vault)
            self.assertEqual(final["turn_id"], "turn-2")
            self.assertEqual(final["status"], "pending")
            self.assertNotIn("processed_at", final)

    def test_mark_accepts_legacy_candidate_with_only_created_at(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            vault = base / "vault"
            inbox = vault / "InboxTest" / "知识库" / "收件箱"
            inbox.mkdir(parents=True)
            target = inbox / "legacy.json"
            created_at = "2026-09-12T00:00:00+00:00"
            target.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "status": "pending",
                        "created_at": created_at,
                        "session_id": "legacy",
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            result = self.run_mark(
                vault,
                "InboxTest",
                target.name,
                created_at,
            )
            self.assertEqual(result.returncode, 0, result.stderr.decode(errors="replace"))
            payload = json.loads(target.read_text(encoding="utf-8"))
            self.assertEqual(payload["status"], "processed")
            self.assertTrue(payload.get("processed_at"))


if __name__ == "__main__":
    unittest.main()
