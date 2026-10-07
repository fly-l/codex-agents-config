#!/usr/bin/env python3
"""一站式安装 Codex、Claude Code 或 Pi 配置；默认预览，--apply 才写入。"""

import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

if sys.version_info < (3, 11):
    raise SystemExit("需要 Python 3.11 或更新版本；请升级后重试。")
import tomllib

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "Hook"))
import manage_installation as manager

BEGIN = "<!-- codex-agents-config:begin -->"
END = "<!-- codex-agents-config:end -->"
# 仅识别上一版本完整原文（允许 CRLF 换行），不把定制内容当作仓库文件。
LEGACY_INSTRUCTIONS = {
    "AGENTS.md": "40a320d16c87ed3ae481f1c0e40d8fe7ef9644faac6937c1a958e75c16f51c83",
    "CLAUDE.md": "0f8f4731d39339ec72f1dc96a2b5848c7fe98b5eb937d5c05db9716be3a82f79",
    "PI.AGENTS.md": "ae2a7bada58f4bc78cb168847c6dae070c6cdab9b9ca4073f8182c739c5d8769",
}
LEGACY_SUBAGENTS = "b8be65be9f668db912419f2a0d19a6c328cd09e525064f94f330acc8ca032aa5"


def instruction_content(source: bytes, existing: bytes | None, merge: bool) -> bytes:
    block = BEGIN + "\n" + source.decode("utf-8").rstrip() + "\n" + END
    if existing is None or existing == source:
        return (block + "\n").encode("utf-8")
    text = existing.decode("utf-8")
    if BEGIN in text or END in text:
        if text.count(BEGIN) != 1 or text.count(END) != 1 or text.index(BEGIN) > text.index(END):
            raise ValueError("受管指令标记损坏，请先修复 begin/end 标记。")
        start, end = text.index(BEGIN), text.index(END) + len(END)
        return (text[:start] + block + text[end:]).encode("utf-8")
    if not merge:
        raise ValueError("指令文件内容冲突；可用 --merge-instructions 备份并追加受管章节，或先人工合并。")
    return existing + ("\n\n" + block + "\n").encode("utf-8")


def enable_codex_hooks(data: bytes) -> bytes:
    """只改 hooks 开关；用解析后的完整数据比较防止误改其他 TOML 内容。"""
    text = data.decode("utf-8")
    original = tomllib.loads(text)
    desired = copy.deepcopy(original)
    features = desired.setdefault("features", {})
    if not isinstance(features, dict):
        raise ValueError("config.toml 的 features 必须是表。")
    if features.get("hooks") is True:
        return data
    features["hooks"] = True
    lines = text.splitlines(keepends=True)
    section = None
    candidate = None
    for index, line in enumerate(lines):
        if re.match(r'^\s*\[features\]\s*(?:#.*)?$', line):
            section = index
            continue
        if section is not None and re.match(r'^\s*\[', line):
            break
        if section is not None and re.match(r'^\s*hooks\s*=', line):
            candidate = ''.join(lines[:index] + [re.sub(r'(=\s*)(true|false)', r'\g<1>true', line, count=1)] + lines[index + 1:])
            break
    if candidate is None and section is not None:
        lines[section] = lines[section].rstrip('\r\n') + '\n'
        candidate = ''.join(lines[:section + 1] + ['hooks = true\n'] + lines[section + 1:])
    if candidate is None:
        candidate = text.rstrip() + '\n\n[features]\nhooks = true\n'
    try:
        if tomllib.loads(candidate) == desired:
            return candidate.encode("utf-8")
    except tomllib.TOMLDecodeError:
        pass
    raise ValueError("无法安全修改 config.toml 的特殊 TOML 写法；请手动设置 features.hooks = true 后重试。")


def hook_content(host: str, home: Path) -> bytes:
    required = ["project_memory_common.py", "project_memory_session_start.py", "project_memory_session_end.py"]
    if host == "codex":
        required.extend(["conversation_title_session_end.py", "conversation_title_worker.py"])
    for name in required:
        if not (ROOT / "Hook" / name).is_file():
            raise ValueError(f"仓库 Hook 脚本缺失：{ROOT / 'Hook' / name}；请恢复仓库后重试。")
    script = {"codex": "install.py", "claude": "install_claude.py", "pi": "install_pi.py"}[host]
    command = [sys.executable, str(ROOT / "Hook" / script), "--target", str(home / manager._config_name(host)), "--dry-run"]
    result = subprocess.run(command, capture_output=True, env={**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONDONTWRITEBYTECODE": "1"})
    if result.returncode:
        raise ValueError("Hook 预检失败：" + result.stderr.decode("utf-8", errors="replace").strip())
    return result.stdout


def plan(host: str, home: Path, merge: bool) -> list[tuple[Path, bytes | None]]:
    source, target = {"codex": ("AGENTS.md", "AGENTS.md"), "claude": ("CLAUDE.md", "CLAUDE.md"), "pi": ("PI.AGENTS.md", "AGENTS.md")}[host]
    required = [f"Skills/{name}/SKILL.md" for name in manager.MANAGED_SKILLS]
    required.extend([
        "Skills/project-memory/scripts/memory_inbox.py",
        "Skills/project-memory/scripts/memory_store.py",
        "Skills/project-memory-maintenance/scripts/memory_maintenance.py",
    ])
    for relative in required:
        if not (ROOT / relative).is_file():
            raise ValueError(f"仓库 Skill 文件缺失：{ROOT / relative}；请恢复仓库后重试。")
    files = []
    path = home / target
    manager._validate_write_location(path, home)
    existing = path.read_bytes() if path.exists() else None
    if existing is not None and hashlib.sha256(existing.replace(b"\r\n", b"\n")).hexdigest() == LEGACY_INSTRUCTIONS[source]:
        existing = None
    try:
        content = instruction_content((ROOT / source).read_bytes(), existing, merge)
    except ValueError as exc:
        raise ValueError(f"{path}：{exc}") from exc
    files.append((path, content))
    retired = home / "SUBAGENTS.md"
    if retired.exists() or retired.is_symlink():
        # 外部链接或定制内容均不改写；只退役已确认的旧仓库原文（允许 CRLF 换行）。
        if retired.is_file() and not retired.is_symlink():
            old = retired.read_bytes().replace(b"\r\n", b"\n")
            wrapped_begin = (BEGIN + "\n").encode("utf-8")
            wrapped_end = ("\n" + END + "\n").encode("utf-8")
            if old.startswith(wrapped_begin) and old.endswith(wrapped_end):
                old = old[len(wrapped_begin):-len(wrapped_end)] + b"\n"
            if hashlib.sha256(old).hexdigest() == LEGACY_SUBAGENTS:
                manager._validate_write_location(retired, home)
                files.append((retired, None))
    if b"SUBAGENTS.md" in content:
        print(f"提示：{path} 的用户内容仍引用 SUBAGENTS.md，请人工检查并移除不再需要的旧调度规则。")
    hook = home / manager._config_name(host)
    manager._validate_write_location(hook, home)
    files.append((hook, hook_content(host, home)))
    if host == "codex":
        config = home / "config.toml"
        manager._validate_write_location(config, home)
        files.append((config, enable_codex_hooks(config.read_bytes() if config.exists() else b"")))
    return [(path, data) for path, data in files if not path.exists() or path.read_bytes() != data]


def doctor(host: str, home: Path) -> int:
    issues = []
    try:
        changes = plan(host, home, False)
        issues.extend(f"需要安装或更新：{path}" for path, _ in changes)
        status = manager.status(host, str(home))
        if not status["in_sync"]:
            issues.append(f"Skills 缺失 {status['missing']} 项、变更 {status['changed']} 项")
    except (ValueError, OSError, manager.InstallationError) as exc:
        issues.append(str(exc))
    print(f"宿主：{host}\n目录：{home}\nPython：{sys.version.split()[0]} ({sys.executable})")
    if not shutil.which(host):
        print(f"提示：PATH 中未找到 {host}；桌面宿主可能不提供命令行，请在实际宿主中验收。")
    retired = home / "SUBAGENTS.md"
    if retired.exists() or retired.is_symlink():
        print(f"提示：发现旧 SUBAGENTS.md；原版将由 --apply 备份退役，定制文件或链接保留，请检查是否仍有其他入口引用：{retired}")
    for issue in issues:
        print("待处理：" + issue)
    if issues:
        print("运行 python install.py --apply（其他宿主加 --host）修复；此检查未写入任何文件。")
        return 1
    print("静态安装检查通过；请重启宿主验证 Skills 与 Hook，检查结果不代表真实会话已经生效。")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", choices=("codex", "claude", "pi"), default="codex", help="目标宿主（默认 codex）")
    parser.add_argument("--home", help="目标宿主目录，默认使用对应环境变量或用户目录")
    parser.add_argument("--merge-instructions", action="store_true", help="保留已有指令，在备份后追加受管章节；需自行检查语义冲突")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true", help="实际写入配置")
    mode.add_argument("--dry-run", action="store_true", help="预览安装计划（默认）")
    mode.add_argument("--doctor", action="store_true", help="只读检查安装，缺失或漂移时返回非零状态")
    args = parser.parse_args()
    try:
        home = manager._validate_home(args.home, args.host)
        if args.doctor:
            return doctor(args.host, home)
        changes = plan(args.host, home, args.merge_instructions)
        skills = manager.sync(args.host, str(home))
        # 在任何写入前检查备份目录；全部配置完成解析后才安装。
        manager._validate_directory_for_write(home / "backups/codex-agents-config", home)
        write_paths = [path for path, _ in changes]
        write_paths.extend(Path(item["target"]) for item in skills["changes"])
        write_paths.append(home / "backups/codex-agents-config/placeholder")
        for path in write_paths:
            for parent in path.parents:
                if (parent.exists() or parent.is_symlink()) and not parent.is_dir():
                    raise ValueError(f"目标父路径不是目录：{parent}")
                if parent == home:
                    break
        print(f"宿主：{args.host}\n目录：{home}\nPython：{sys.version.split()[0]}")
        for path, data in changes:
            action = "备份并退役" if data is None else ("更新" if path.exists() else "创建")
            print(f"{action}：{path}")
        print(f"Skills：{len(skills['changes'])} 项变更")
        if not args.apply:
            print("仅预览，未写入；添加 --apply 执行安装。")
            return 0
        if changes:
            backup, _ = manager._new_run_directory(home)
            for path, _ in changes:
                if path.exists():
                    manager._backup_file(path, backup / path.relative_to(home), home)
            print(f"配置备份：{backup}")
        result = manager.sync(args.host, str(home), apply=True)
        if result["backup"]:
            print(f"Skills 备份：{result['backup']['directory']}")
        for path, data in changes:
            if data is None:
                path.unlink()
            else:
                manager._atomic_write_bytes(path, data, home)
        print("安装完成。Vault 使用 PROJECT_MEMORY_VAULT；模型与项目知识体系配置保持不变。")
        if args.host == "codex":
            print("已启用 hooks；重启 Codex 后通过 /hooks 审核并信任新增 Hook。")
        elif args.host == "claude":
            print("请重启 Claude Code，用 /memory、/skills 和 /hooks 验证。")
        else:
            print("请重启 Pi 或执行 /reload，用 /help 检查 Skills。")
        return doctor(args.host, home)
    except (ValueError, OSError, manager.InstallationError) as exc:
        parser.exit(2, f"安装停止：{exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
