#!/usr/bin/env python3
"""统一安装 Codex、Claude Code 或 Pi 配置；默认预览，--apply 才写入。"""

import argparse
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "Hook"))
import manage_installation


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", choices=("codex", "claude", "pi"), required=True)
    parser.add_argument("--home", help="目标宿主目录，默认使用对应宿主的环境变量或用户目录")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true", help="实际写入配置")
    mode.add_argument("--dry-run", action="store_true", help="预览安装计划（默认）")
    args = parser.parse_args()
    env_name, default_home = manage_installation.HOST_HOMES[args.host]
    home = Path(os.path.expandvars(args.home or os.environ.get(env_name) or default_home)).expanduser().resolve()
    source_name, target_name, hook_script, hook_target = {
        "codex": ("AGENTS.md", "AGENTS.md", "install.py", "hooks.json"),
        "claude": ("CLAUDE.md", "CLAUDE.md", "install_claude.py", "settings.json"),
        "pi": ("PI.AGENTS.md", "AGENTS.md", "install_pi.py", "extensions/project-memory-hook.ts"),
    }[args.host]
    instructions = [(ROOT / source_name, home / target_name), (ROOT / "SUBAGENTS.md", home / "SUBAGENTS.md")]
    conflicts = []
    for source, target in instructions:
        if target.exists() and target.read_bytes() != source.read_bytes():
            conflicts.append(str(target))
        print(f"指令：{source} -> {target}", flush=True)
    if conflicts:
        parser.exit(2, "指令文件内容冲突，请先备份并合并以下文件；未执行安装：\n" + "\n".join(conflicts) + "\n")

    # 先预览所有步骤，确保 Hook 配置可解析后再执行写入。
    skill_command = [sys.executable, str(ROOT / "Hook/manage_installation.py"), "sync", "--host", args.host, "--home", str(home)]
    hook_command = [sys.executable, str(ROOT / "Hook" / hook_script), "--target", str(home / hook_target)]
    subprocess.run(skill_command, check=True)
    subprocess.run(hook_command + ["--dry-run"], check=True)
    if not args.apply:
        print("仅预览，未写入；添加 --apply 执行安装。")
        return
    subprocess.run(skill_command + ["--apply"], check=True)
    subprocess.run(hook_command, check=True)
    for source, target in instructions:
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(source.read_bytes())
    print("安装完成。Vault 统一使用 PROJECT_MEMORY_VAULT；模型与项目知识体系配置仍由用户按需设置。")
    if args.host == "codex":
        print("请确认 config.toml 的 [features] 中 hooks = true，重启 Codex 后通过 /hooks 审核。")


if __name__ == "__main__":
    main()
