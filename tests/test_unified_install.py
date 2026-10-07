"""验证统一安装入口的预览、宿主分发和冲突保护。"""

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import tomllib
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
                self.assertFalse((home / "SUBAGENTS.md").exists())
                self.assertTrue((home / hook).is_file())
                self.assertTrue((home / "skills/project-memory/SKILL.md").is_file())
                (home / instruction).write_text("用户规则", encoding="utf-8")
                before = (home / hook).read_bytes()
                conflict = subprocess.run(command + ["--apply"], capture_output=True, env=env)
                self.assertEqual(conflict.returncode, 2)
                self.assertEqual((home / instruction).read_text(encoding="utf-8"), "用户规则")
                self.assertEqual((home / hook).read_bytes(), before)

    def run_install(self, home, *arguments):
        return subprocess.run(
            [sys.executable, "-B", str(ROOT / "install.py"), "--home", str(home), *arguments],
            capture_output=True, text=True, encoding="utf-8",
            env={**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONDONTWRITEBYTECODE": "1"},
        )

    def snapshot(self, home):
        return {str(path.relative_to(home)): path.read_bytes() for path in home.rglob("*") if path.is_file()}

    def test_default_codex_enables_hooks_and_repeat_is_noop(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary) / "home with spaces 和中文"
            home.mkdir()
            config = '# 保留模型与其他开关\nmodel = "my-model"\n[features] # 特性\nhooks = false # 开关\nother = true\n[agents]\nenabled = true\n'
            (home / "config.toml").write_text(config, encoding="utf-8")
            before = self.snapshot(home)
            preview = self.run_install(home)
            self.assertEqual(preview.returncode, 0, preview.stderr)
            self.assertEqual(self.snapshot(home), before)
            result = self.run_install(home, "--apply")
            self.assertEqual(result.returncode, 0, result.stderr)
            installed = (home / "config.toml").read_text(encoding="utf-8")
            self.assertEqual(installed, config.replace('hooks = false', 'hooks = true'))
            self.assertEqual(tomllib.loads(installed)["model"], "my-model")
            self.assertTrue(any(path.read_text(encoding="utf-8") == config for path in (home / "backups").rglob("config.toml")))
            before = self.snapshot(home)
            self.assertEqual(self.run_install(home, "--apply").returncode, 0)
            self.assertEqual(self.snapshot(home), before)
            self.assertEqual(self.run_install(home, "--doctor").returncode, 0)
            self.assertEqual(self.snapshot(home), before)

    def test_merge_preserves_user_rules_and_backups_for_each_host(self):
        for host, name in (("codex", "AGENTS.md"), ("claude", "CLAUDE.md"), ("pi", "AGENTS.md")):
            with self.subTest(host=host), tempfile.TemporaryDirectory() as temporary:
                home = Path(temporary)
                original = b"User rules, preserve exactly.\n"
                for file in (name, "SUBAGENTS.md"):
                    (home / file).write_bytes(original)
                result = self.run_install(home, "--host", host, "--merge-instructions", "--apply")
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertTrue((home / name).read_bytes().startswith(original))
                self.assertTrue(any(path.read_bytes() == original for path in (home / "backups").rglob(name)))
                self.assertEqual((home / "SUBAGENTS.md").read_bytes(), original)
                before = self.snapshot(home)
                self.assertEqual(self.run_install(home, "--host", host, "--apply").returncode, 0)
                self.assertEqual(self.snapshot(home), before)

    def test_managed_block_updates_without_duplication(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            prefix = "我的前置规则\n"
            suffix = "\n我的后置规则\n"
            (home / "AGENTS.md").write_text(prefix + "<!-- codex-agents-config:begin -->\n旧规则\n<!-- codex-agents-config:end -->" + suffix, encoding="utf-8")
            result = self.run_install(home, "--apply")
            self.assertEqual(result.returncode, 0, result.stderr)
            text = (home / "AGENTS.md").read_text(encoding="utf-8")
            self.assertTrue(text.startswith(prefix))
            self.assertTrue(text.endswith(suffix))
            self.assertEqual(text.count("<!-- codex-agents-config:begin -->"), 1)
            self.assertNotIn("旧规则", text)
            self.assertIn((ROOT / "AGENTS.md").read_text(encoding="utf-8").strip(), text)

    def test_broken_markers_and_special_toml_fail_without_writes(self):
        for file, content in (("AGENTS.md", '<!-- codex-agents-config:begin -->\n'), ("config.toml", 'features = { hooks = false, other = true }\n')):
            with self.subTest(file=file), tempfile.TemporaryDirectory() as temporary:
                home = Path(temporary)
                (home / file).write_text(content, encoding="utf-8")
                before = self.snapshot(home)
                result = self.run_install(home, "--merge-instructions", "--apply")
                self.assertEqual(result.returncode, 2, result.stdout)
                self.assertEqual(self.snapshot(home), before)

    def test_legacy_instructions_migrate_and_subagents_retire_with_backup(self):
        legacy_section = "# 多代理协作规则\n\n开始任务时，先读取与本指令文件同目录的 [SUBAGENTS.md](SUBAGENTS.md)，按其中的通用规则判断是否委派，并只使用当前宿主的配置。子代理遵守主代理传入的相关规则，不重复加载其他宿主配置。\n"
        original_subagents = (ROOT / "tests/fixtures/legacy_subagents.txt").read_bytes()
        for host, source, name in (("codex", "AGENTS.md", "AGENTS.md"), ("claude", "CLAUDE.md", "CLAUDE.md"), ("pi", "PI.AGENTS.md", "AGENTS.md")):
            with self.subTest(host=host), tempfile.TemporaryDirectory() as temporary:
                home = Path(temporary)
                current = (ROOT / source).read_text(encoding="utf-8")
                original = (current[:current.index("# 多代理协作")] + legacy_section).encode("utf-8")
                if host == "claude":
                    original = original.replace(b"\n", b"\r\n")
                subagents = original_subagents.replace(b"\n", b"\r\n") if host == "claude" else original_subagents
                (home / name).write_bytes(original)
                (home / "SUBAGENTS.md").write_bytes(subagents)
                before = self.snapshot(home)
                self.assertEqual(self.run_install(home, "--host", host).returncode, 0)
                self.assertEqual(self.snapshot(home), before)
                applied = self.run_install(home, "--host", host, "--apply")
                self.assertEqual(applied.returncode, 0, applied.stderr)
                self.assertFalse((home / "SUBAGENTS.md").exists())
                self.assertNotIn("SUBAGENTS.md", (home / name).read_text(encoding="utf-8"))
                self.assertTrue(any(path.read_bytes() == original for path in (home / "backups").rglob(name)))
                self.assertTrue(any(path.read_bytes() == subagents for path in (home / "backups").rglob("SUBAGENTS.md")))
                before = self.snapshot(home)
                self.assertEqual(self.run_install(home, "--host", host, "--apply").returncode, 0)
                self.assertEqual(self.snapshot(home), before)

    def test_wrapped_original_subagents_retire_but_custom_content_survives(self):
        original = (ROOT / "tests/fixtures/legacy_subagents.txt").read_bytes()
        wrapped = b"<!-- codex-agents-config:begin -->\n" + original.rstrip() + b"\n<!-- codex-agents-config:end -->\n"
        for content, keep in ((wrapped, False), (wrapped.replace(b"\n", b"\r\n"), False), (original + b"custom rule\n", True), (b"custom rule\n" + wrapped, True)):
            with self.subTest(keep=keep), tempfile.TemporaryDirectory() as temporary:
                home = Path(temporary)
                file = home / "SUBAGENTS.md"
                file.write_bytes(content)
                applied = self.run_install(home, "--apply")
                self.assertEqual(applied.returncode, 0, applied.stderr)
                self.assertEqual(file.exists(), keep)
                if keep:
                    self.assertEqual(file.read_bytes(), content)
                    self.assertIn("定制文件或链接保留", applied.stdout)

    def test_custom_legacy_reference_is_preserved_and_warned(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            original = "用户约定：继续参考 SUBAGENTS.md\n"
            (home / "AGENTS.md").write_text(original, encoding="utf-8")
            before = self.snapshot(home)
            self.assertEqual(self.run_install(home, "--apply").returncode, 2)
            self.assertEqual(self.snapshot(home), before)
            result = self.run_install(home, "--merge-instructions", "--apply")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue((home / "AGENTS.md").read_text(encoding="utf-8").startswith(original))
            self.assertIn("用户内容仍引用 SUBAGENTS.md", result.stdout)

    def test_invalid_config_and_hook_fail_before_any_write(self):
        for file, content in (("config.toml", '[features\n'), ("hooks.json", '{bad json')):
            with self.subTest(file=file), tempfile.TemporaryDirectory() as temporary:
                home = Path(temporary)
                (home / file).write_text(content, encoding="utf-8")
                before = self.snapshot(home)
                result = self.run_install(home, "--apply")
                self.assertEqual(result.returncode, 2, result.stdout)
                self.assertEqual(self.snapshot(home), before)

    def test_doctor_missing_and_drift_are_nonzero_and_read_only(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary) / "home"
            self.assertEqual(self.run_install(home, "--doctor").returncode, 1)
            self.assertFalse(home.exists())
            self.assertEqual(self.run_install(home, "--apply").returncode, 0)
            (home / "skills/project-memory/SKILL.md").write_text("changed", encoding="utf-8")
            before = self.snapshot(home)
            self.assertEqual(self.run_install(home, "--doctor").returncode, 1)
            self.assertEqual(self.snapshot(home), before)

    def test_unrelated_hooks_settings_and_skill_files_survive(self):
        import json
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            unrelated = {"type": "command", "command": "echo user-hook"}
            settings = {"env": {"USER_SETTING": "keep"}, "hooks": {"Stop": [{"hooks": [unrelated]}]}}
            (home / "settings.json").write_text(json.dumps(settings), encoding="utf-8")
            extra = home / "skills/project-memory/my-notes.md"
            extra.parent.mkdir(parents=True)
            extra.write_text("preserve", encoding="utf-8")
            result = self.run_install(home, "--host", "claude", "--apply")
            self.assertEqual(result.returncode, 0, result.stderr)
            after = json.loads((home / "settings.json").read_text(encoding="utf-8"))
            self.assertEqual(after["env"], settings["env"])
            self.assertIn({"hooks": [unrelated]}, after["hooks"]["Stop"])
            self.assertEqual(extra.read_text(encoding="utf-8"), "preserve")

    def test_parent_file_conflicts_fail_before_any_write(self):
        for host, parent in (("pi", "extensions"), ("codex", "skills"), ("codex", "backups")):
            with self.subTest(host=host, parent=parent), tempfile.TemporaryDirectory() as temporary:
                home = Path(temporary)
                (home / parent).write_text("user file", encoding="utf-8")
                before = self.snapshot(home)
                for mode in ("--dry-run", "--apply"):
                    result = self.run_install(home, "--host", host, mode)
                    self.assertEqual(result.returncode, 2, result.stdout)
                    self.assertEqual(self.snapshot(home), before)

    def test_missing_hook_source_fails_doctor_and_apply(self):
        import shutil
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            checkout = root / "checkout"
            shutil.copytree(ROOT, checkout, ignore=shutil.ignore_patterns(".git", "__pycache__"))
            home = root / "home"
            command = [sys.executable, "-B", str(checkout / "install.py"), "--home", str(home)]
            env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONIOENCODING": "utf-8"}
            result = subprocess.run(command + ["--apply"], capture_output=True, env=env)
            self.assertEqual(result.returncode, 0, result.stderr)
            for relative in ("Hook/project_memory_session_start.py", "Skills/project-memory/scripts/memory_inbox.py", "Skills/project-memory/SKILL.md"):
                source = checkout / relative
                original = source.read_bytes()
                source.unlink()
                before = self.snapshot(home)
                for mode, code in (("--doctor", 1), ("--apply", 2)):
                    result = subprocess.run(command + [mode], capture_output=True, env=env)
                    self.assertEqual(result.returncode, code, result.stdout)
                    self.assertEqual(self.snapshot(home), before)
                source.write_bytes(original)

    def test_legacy_retirement_waits_for_successful_preflight(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            old = (ROOT / "tests/fixtures/legacy_subagents.txt").read_bytes()
            (home / "SUBAGENTS.md").write_bytes(old)
            (home / "hooks.json").write_bytes(b"invalid json")
            before = self.snapshot(home)
            self.assertEqual(self.run_install(home, "--apply").returncode, 2)
            self.assertEqual(self.snapshot(home), before)

    @unittest.skipIf(os.name == "nt", "Windows 创建符号链接需要额外权限")
    def test_legacy_subagents_symlink_is_not_retired(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            home = root / "home"
            home.mkdir()
            original = (ROOT / "tests/fixtures/legacy_subagents.txt").read_bytes()
            external = root / "shared-rules.md"
            external.write_bytes(original)
            link = home / "SUBAGENTS.md"
            link.symlink_to(external)
            result = self.run_install(home, "--apply")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(link.is_symlink())
            self.assertEqual(external.read_bytes(), original)

    @unittest.skipIf(os.name == "nt", "Windows 创建符号链接需要额外权限")
    def test_dangling_parent_symlink_fails_before_writes(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            (home / "extensions").symlink_to(home / "missing", target_is_directory=True)
            for mode in ("--dry-run", "--apply"):
                result = self.run_install(home, "--host", "pi", mode)
                self.assertEqual(result.returncode, 2, result.stdout)
                self.assertEqual(list(home.iterdir()), [home / "extensions"])

    @unittest.skipIf(os.name == "nt", "Windows 创建符号链接需要额外权限")
    def test_external_symlink_rejected_before_writes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            home = root / "home"
            home.mkdir()
            outside = root / "outside.toml"
            outside.write_text('model = "keep"\n', encoding="utf-8")
            (home / "config.toml").symlink_to(outside)
            before = self.snapshot(home)
            self.assertEqual(self.run_install(home, "--apply").returncode, 2)
            self.assertEqual(self.snapshot(home), before)
            self.assertEqual(outside.read_text(encoding="utf-8"), 'model = "keep"\n')


if __name__ == "__main__":
    unittest.main()
