from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


STORE = Path(__file__).resolve().parents[1] / "Skills/project-memory/scripts/memory_store.py"


class MemoryWriteBoundaryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "review/知识库"
        self.env = {**os.environ, "PYTHONUTF8": "1", "PYTHONDONTWRITEBYTECODE": "1", "PYTHONIOENCODING": "utf-8"}

    def run_store(self, *args: str, ok: bool = True) -> dict:
        result = subprocess.run(
            [sys.executable, "-B", str(STORE), "--vault-root", self.temp.name, "--project", "review", *args],
            capture_output=True, text=True, encoding="utf-8", env=self.env,
        )
        if ok:
            self.assertEqual(result.returncode, 0, result.stderr)
            return json.loads(result.stdout)
        self.assertNotEqual(result.returncode, 0, result.stdout)
        return {"code": result.returncode, "error": result.stderr}

    def upsert(self, record_id: str, body: str, *extra: str, ok: bool = True) -> dict:
        return self.run_store("upsert", "--kind", "convention", "--id", record_id,
                              "--title", "接口规则", "--body", body, "--status", "active",
                              "--source", "fixture", "--module", "core", *extra, ok=ok)

    def snapshot(self) -> dict[str, bytes]:
        return {str(path.relative_to(self.root)): path.read_bytes() for path in self.root.rglob("*.md")}

    def test_draft_cannot_retire_current_fact(self) -> None:
        self.upsert("OLD", "当前规则")
        before = self.snapshot()
        self.upsert("DRAFT", "待确认规则", "--status", "proposed", "--supersedes", "OLD", ok=False)
        self.assertEqual(before, self.snapshot())
        self.assertEqual(self.run_store("search", "--module", "core")["records"][0]["id"], "OLD")
        self.assertTrue(self.run_store("validate")["ok"])

    def test_cycle_is_rejected_before_any_write(self) -> None:
        self.upsert("A", "第一版")
        self.upsert("B", "第二版", "--supersedes", "A")
        before = self.snapshot()
        self.upsert("A", "形成环", "--supersedes", "B", ok=False)
        self.assertEqual(before, self.snapshot())
        self.assertTrue(self.run_store("validate")["ok"])

    def test_valid_chain_and_historical_edit_remain_valid(self) -> None:
        self.upsert("A", "第一版")
        self.upsert("B", "第二版", "--supersedes", "A")
        self.upsert("C", "第三版", "--supersedes", "B")
        self.upsert("B", "第二版的补充证据", "--status", "superseded")
        self.assertTrue(self.run_store("validate")["ok"])
        self.assertEqual([row["id"] for row in self.run_store("search", "--module", "core")["records"]], ["C"])

    def test_cross_type_duplicate_id_is_rejected(self) -> None:
        self.upsert("SAME", "约定")
        before = self.snapshot()
        self.upsert("SAME", "架构", "--kind", "architecture", ok=False)
        self.assertEqual(before, self.snapshot())

    def test_edit_preserves_verification_date_until_explicit_recheck(self) -> None:
        first = self.upsert("DATED", "已有规则", "--verified-at", "2025-01-01")
        self.upsert("DATED", "已有规则的措辞修正", "--expected-fingerprint", first["fingerprint"])
        saved = self.run_store("search", "--query", "DATED")["records"][0]
        self.assertEqual(saved["verified_at"], "2025-01-01")
        self.upsert("DATED", "已有规则的措辞修正", "--verified-at", "2026-09-26")
        rechecked = self.run_store("search", "--query", "DATED")["records"][0]
        self.assertEqual(rechecked["verified_at"], "2026-09-26")

    def test_semantic_case_and_spacing_are_not_duplicates(self) -> None:
        first = self.upsert("ONE", "调用 `/Users`；值为 `a  b`。")
        changed = self.upsert("ONE", "调用 `/users`；值为 `a  b`。", "--expected-fingerprint", first["fingerprint"])
        self.assertNotEqual(first["fingerprint"], changed["fingerprint"])
        second = self.upsert("TWO", "调用 `/users`；值为 `a b`。")
        self.assertEqual(second["action"], "created")
        self.assertTrue(self.run_store("validate")["ok"])

    def test_legacy_fingerprint_is_accepted_without_rewriting_record(self) -> None:
        row = self.upsert("OLD", "Call `/Users`\n    Keep Indent")
        path = Path(row["path"])
        text = path.read_text(encoding="utf-8")
        normalize = lambda value: " ".join(value.split()).casefold()
        payload = {"type": "convention", "title": normalize("接口规则"),
                   "body": normalize("Call `/Users`\n    Keep Indent"), "module": ["core"]}
        legacy = hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        path.write_text(text.replace("fingerprint_version: 2\n", "").replace(row["fingerprint"], legacy), encoding="utf-8")
        before = self.snapshot()
        self.assertTrue(self.run_store("validate")["ok"])
        self.assertEqual(before, self.snapshot())
        # 旧记录的哈希不再参与新记录的重复判断。
        other = self.upsert("NEW", "Call `/users`\n    Keep Indent")
        self.assertEqual(other["action"], "created")

    def test_malformed_module_fails_both_search_modes(self) -> None:
        row = self.upsert("RULE", "probe")
        path = Path(row["path"])
        path.write_text(path.read_text(encoding="utf-8").replace('module: ["core"]', 'module: "core"'), encoding="utf-8")
        for query in (("--query", "probe"), ("--query", "probe", "--module", "core")):
            with self.subTest(query=query):
                result = self.run_store("search", *query, ok=False)
                self.assertIn("module", result["error"])


if __name__ == "__main__":
    unittest.main()
