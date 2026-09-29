"""验证统一安装入口的预览、宿主分发和冲突保护。"""

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class UnifiedInstallTests(unittest.TestCase):
    def test_preview_apply_repeat_and_conflict_for_each_host(self):
        for host, instruction, hook in (
            ("codex", "AGENTS.md", "hooks.json"),
            ("claude", "CLAUDE.md", "settings.json"),
            ("pi", "AGENTS.md", "extensions/project-memory-hook.ts"),
        ):
            with self.subTest(host=host), tempfile.TemporaryDirectory() as temporary:
                home = Path(temporary) / "home"
                command = [sys.executable, str(ROOT / "install.py"), "--host", host, "--home", str(home)]
                env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONDONTWRITEBYTECODE": "1"}
                preview = subprocess.run(command, capture_output=True, env=env)
                self.assertEqual(preview.returncode, 0, preview.stderr)
                self.assertFalse(home.exists())
                for _ in range(2):
                    applied = subprocess.run(command + ["--apply"], capture_output=True, env=env)
                    self.assertEqual(applied.returncode, 0, applied.stderr)
                self.assertTrue((home / instruction).is_file())
                self.assertTrue((home / "SUBAGENTS.md").is_file())
                self.assertTrue((home / hook).is_file())
                self.assertTrue((home / "skills/project-memory/SKILL.md").is_file())
                (home / instruction).write_text("用户规则", encoding="utf-8")
                before = (home / hook).read_bytes()
                conflict = subprocess.run(command + ["--apply"], capture_output=True, env=env)
                self.assertEqual(conflict.returncode, 2)
                self.assertEqual((home / instruction).read_text(encoding="utf-8"), "用户规则")
                self.assertEqual((home / hook).read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
