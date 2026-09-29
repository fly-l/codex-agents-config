#!/usr/bin/env python3
"""检查并按需同步仓库中的两个项目记忆 Skill。"""

from __future__ import annotations

import argparse
import datetime as _datetime
import hashlib
import json
import os
import platform
import re
import shutil
import sys
import tempfile
import uuid
from pathlib import Path
from typing import Any, Iterable, Iterator


REPO_ROOT = Path(__file__).resolve().parents[1]
MANAGED_SKILLS = ("project-memory", "project-memory-maintenance")
MANAGED_HOOKS = (
    "project_memory_session_start.py",
    "project_memory_session_end.py",
    "conversation_title_session_end.py",
)
HOST_HOMES = {
    "claude": ("CLAUDE_CONFIG_DIR", "~/.claude"),
    "codex": ("CODEX_HOME", "~/.codex"),
    "pi": ("PI_CODING_AGENT_DIR", "~/.pi/agent"),
}
IGNORED_PARTS = {"__pycache__"}


class InstallationError(RuntimeError):
    """安装状态无法安全读取或写入。"""


def _path_text(path: Path) -> str:
    """将路径作为 JSON 中的普通本地路径输出。"""

    return str(path)


def _resolve_path(raw: str | os.PathLike[str], *, label: str) -> Path:
    """解析外部路径，并拒绝不能作为路径处理的值。"""

    text = os.fspath(raw)
    if "\x00" in text:
        raise InstallationError(f"{label}不能包含 NUL 字符。")
    try:
        return Path(os.path.expandvars(text)).expanduser().resolve(strict=False)
    except (OSError, RuntimeError, ValueError) as exc:
        raise InstallationError(f"无法解析{label}：{exc}") from exc


def _inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _validate_home(raw_home: str | None, host: str) -> Path:
    if raw_home is None:
        variable, default = HOST_HOMES[host]
        raw_home = os.environ.get(variable, default)
    home = _resolve_path(raw_home, label="宿主 home")
    if home.exists() and not home.is_dir():
        raise InstallationError(f"宿主 home 必须是目录：{home}")
    return home


def _validate_write_location(path: Path, home: Path) -> None:
    """确认写入路径及其现有符号链接目标均位于宿主 home 内。"""

    resolved_home = home.resolve(strict=False)
    try:
        resolved_parent = path.parent.resolve(strict=False)
    except (OSError, RuntimeError) as exc:
        raise InstallationError(f"无法解析写入路径：{path}") from exc
    if not _inside(resolved_parent, resolved_home):
        raise InstallationError(
            f"拒绝写入宿主 home 外的路径：{path}（父目录解析为 {resolved_parent}）。"
        )
    if path.is_symlink():
        try:
            resolved_target = path.resolve(strict=False)
        except (OSError, RuntimeError) as exc:
            raise InstallationError(f"无法解析目标符号链接：{path}") from exc
        if not _inside(resolved_target, resolved_home):
            raise InstallationError(
                f"拒绝写入指向宿主 home 外部的符号链接：{path} -> {resolved_target}"
            )


def _validate_directory_for_write(path: Path, home: Path) -> None:
    _validate_write_location(path / "placeholder", home)
    if path.exists() and not path.is_dir():
        raise InstallationError(f"目标目录不是目录：{path}")


def _is_managed_file(path: Path) -> bool:
    return not any(part in IGNORED_PARTS for part in path.parts) and path.suffix.lower() != ".pyc"


def _formal_files(root: Path) -> list[Path]:
    if not root.exists() or not root.is_dir():
        raise InstallationError(f"仓库 Skill 目录不存在：{root}")
    result: list[Path] = []
    for path in root.rglob("*"):
        if path.is_file() and _is_managed_file(path):
            result.append(path)
    return sorted(result, key=lambda item: item.relative_to(root).as_posix())


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
    except (OSError, UnicodeError) as exc:
        raise InstallationError(f"无法读取文件：{path}") from exc
    return digest.hexdigest()


def _content_hash(root: Path, relative_paths: Iterable[Path]) -> str:
    """按相对路径和内容计算稳定摘要；额外文件不参与摘要。"""

    digest = hashlib.sha256()
    for relative in sorted(relative_paths, key=lambda item: item.as_posix()):
        target = root / relative
        digest.update(relative.as_posix().encode("utf-8"))
        digest.update(b"\0")
        if not target.exists() and not target.is_symlink():
            digest.update(b"<missing>\0")
            continue
        if not target.is_file():
            digest.update(b"<not-file>\0")
            continue
        digest.update(_sha256_file(target).encode("ascii"))
        digest.update(b"\0")
    return digest.hexdigest()


def _skill_status(source_root: Path, installed_root: Path) -> dict[str, Any]:
    source_files = _formal_files(source_root)
    relative_paths = [path.relative_to(source_root) for path in source_files]
    missing = 0
    changed = 0
    matching = 0
    changes: list[dict[str, str]] = []
    for source in source_files:
        relative = source.relative_to(source_root)
        installed = installed_root / relative
        if not installed.exists() and not installed.is_symlink():
            missing += 1
            changes.append(
                {
                    "path": relative.as_posix(),
                    "source": _path_text(source),
                    "installed": _path_text(installed),
                    "action": "create",
                }
            )
            continue
        if not installed.is_file():
            changed += 1
            changes.append(
                {
                    "path": relative.as_posix(),
                    "source": _path_text(source),
                    "installed": _path_text(installed),
                    "action": "replace",
                }
            )
            continue
        if _sha256_file(source) == _sha256_file(installed):
            matching += 1
        else:
            changed += 1
            changes.append(
                {
                    "path": relative.as_posix(),
                    "source": _path_text(source),
                    "installed": _path_text(installed),
                    "action": "update",
                }
            )
    return {
        "source": _path_text(source_root),
        "installed": _path_text(installed_root),
        "source_hash": _content_hash(source_root, relative_paths),
        "installed_hash": _content_hash(installed_root, relative_paths),
        "missing": missing,
        "changed": changed,
        "matching": matching,
        "extra": _extra_file_count(installed_root, set(relative_paths)),
        "in_sync": missing == 0 and changed == 0,
        "changes": changes,
    }


def _extra_file_count(root: Path, managed_paths: set[Path]) -> int:
    if not root.exists() or not root.is_dir():
        return 0
    count = 0
    for path in root.rglob("*"):
        if path.is_file() and _is_managed_file(path):
            if path.relative_to(root) not in managed_paths:
                count += 1
    return count


def _config_name(host: str) -> str:
    if host == "claude":
        return "settings.json"
    if host == "pi":
        return "extensions/project-memory-hook.ts"
    return "hooks.json"


def _iter_config_strings(value: Any, key: str | None = None) -> Iterator[tuple[str | None, str]]:
    if isinstance(value, str):
        yield key, value
    elif isinstance(value, dict):
        for child_key, child_value in value.items():
            yield from _iter_config_strings(child_value, str(child_key))
    elif isinstance(value, list):
        for child_value in value:
            yield from _iter_config_strings(child_value, key)


def _reference_fragment(value: str, filename: str) -> str | None:
    start = value.find(filename)
    if start < 0:
        return None
    left = start
    while left > 0 and value[left - 1] not in " \t\r\n\"'`":
        left -= 1
    fragment = value[left : start + len(filename)]
    fragment = fragment.strip(" \t\r\n\"'`=,:([{<")
    if "=" in fragment:
        fragment = fragment.rsplit("=", 1)[1].strip(" \t\r\n\"'`")
    return fragment or filename


def _resolve_reference(fragment: str, config_path: Path) -> Path:
    expanded = os.path.expandvars(fragment).strip()
    candidate = Path(expanded).expanduser()
    if not candidate.is_absolute():
        candidate = config_path.parent / candidate
    return candidate.resolve(strict=False)


def _pi_hook_status(home: Path) -> dict[str, Any]:
    """pi 的 Hook 是单个扩展文件，按文本扫描受管脚本引用。"""

    path = home / _config_name("pi")
    result: dict[str, Any] = {
        "path": _path_text(path),
        "config_path": _path_text(path),
        "exists": path.is_file(),
        "references": [],
    }
    if not path.is_file():
        return result
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise InstallationError(f"无法读取 pi 扩展：{path}：{exc}") from exc

    references: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for filename in MANAGED_HOOKS:
        fragment = _reference_fragment(text, filename)
        if fragment is None:
            continue
        script = _resolve_reference(fragment, path)
        identity = (filename, _path_text(script))
        if identity in seen:
            continue
        seen.add(identity)
        references.append(
            {
                "script": filename,
                "path": _path_text(script),
                "exists": script.is_file(),
            }
        )
    result["references"] = references
    return result


def _hook_status(home: Path, host: str) -> dict[str, Any]:
    if host == "pi":
        return _pi_hook_status(home)
    config_path = home / _config_name(host)
    result: dict[str, Any] = {
        "path": _path_text(config_path),
        "config_path": _path_text(config_path),
        "exists": config_path.is_file(),
        "references": [],
    }
    if not config_path.exists():
        return result
    if not config_path.is_file():
        raise InstallationError(f"Hook 配置路径不是文件：{config_path}")
    try:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise InstallationError(f"无法读取 Hook 配置：{config_path}：{exc}") from exc
    if not isinstance(payload, (dict, list)):
        raise InstallationError(f"Hook 配置顶层必须是 JSON 对象或数组：{config_path}")

    references: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for key, value in _iter_config_strings(payload):
        for filename in MANAGED_HOOKS:
            fragment = _reference_fragment(value, filename)
            if fragment is None:
                continue
            # statusMessage 等说明字段里的文件名不是可执行引用。
            if key not in {"command", "args", "path", "script", "file"}:
                if "/" not in fragment and "\\" not in fragment and ":" not in fragment:
                    continue
            path = _resolve_reference(fragment, config_path)
            identity = (filename, _path_text(path))
            if identity in seen:
                continue
            seen.add(identity)
            references.append(
                {
                    "script": filename,
                    "path": _path_text(path),
                    "exists": path.is_file(),
                }
            )
    result["references"] = references
    return result


def _optional_path(raw: str | None, default: Path | str) -> Path | None:
    candidate = raw if raw is not None else default
    if isinstance(candidate, Path):
        path = candidate
    else:
        path = Path(candidate)
    try:
        path = path.expanduser()
        resolved = shutil.which(str(path)) if not path.is_absolute() else None
        if resolved:
            return Path(resolved).resolve(strict=False)
        return path.resolve(strict=False)
    except (OSError, RuntimeError, ValueError):
        return None


def _optional_dependencies(home: Path, host: str) -> dict[str, dict[str, Any]]:
    node_path = _optional_path(os.environ.get("CODEX_MCP_NODE_PATH"), "node")

    def state(path: Path | None, *, file_required: bool = True) -> dict[str, Any]:
        exists = bool(path and (path.is_file() if file_required else path.exists()))
        return {"path": _path_text(path) if path else None, "exists": exists}

    if host == "pi":
        return {"node": state(node_path)}

    title_default = home / "skills" / "rename-current-conversation-title" / "SKILL.md"
    title_path = _optional_path(os.environ.get("CODEX_RENAME_CURRENT_TITLE_SKILL"), title_default)
    codex_path = _optional_path(os.environ.get("CODEX_CLI_PATH"), "codex")

    return {
        "title_skill": state(title_path),
        "node": state(node_path),
        "codex": state(codex_path),
    }


def _status_payload(home: Path, host: str) -> dict[str, Any]:
    skills: dict[str, dict[str, Any]] = {}
    for name in MANAGED_SKILLS:
        skills[name] = _skill_status(
            REPO_ROOT / "Skills" / name,
            home / "skills" / name,
        )
    missing = sum(item["missing"] for item in skills.values())
    changed = sum(item["changed"] for item in skills.values())
    matching = sum(item["matching"] for item in skills.values())
    return {
        "host": host,
        "home": _path_text(home),
        "host_home": _path_text(home),
        "python": {
            "executable": _path_text(Path(sys.executable).resolve()),
            "version": platform.python_version(),
        },
        "skills": skills,
        "missing": missing,
        "changed": changed,
        "matching": matching,
        "counts": {"missing": missing, "changed": changed, "matching": matching},
        "in_sync": missing == 0 and changed == 0,
        "hooks": _hook_status(home, host),
        "optional_dependencies": _optional_dependencies(home, host),
    }


def status(host: str = "codex", home: str | None = None) -> dict[str, Any]:
    """返回安装状态，不创建宿主目录或执行任何 Hook。"""

    resolved_home = _validate_home(home, host)
    return _status_payload(resolved_home, host)


def _new_run_directory(home: Path) -> tuple[Path, str]:
    backup_root = home / "backups" / "codex-agents-config"
    _validate_directory_for_write(backup_root, home)
    backup_root.mkdir(parents=True, exist_ok=True)
    timestamp = _datetime.datetime.now().strftime("%Y%m%d%H%M%S%f")
    for _ in range(10):
        run = f"{timestamp}-{uuid.uuid4().hex[:8]}"
        run_dir = backup_root / run
        _validate_directory_for_write(run_dir, home)
        try:
            run_dir.mkdir()
        except FileExistsError:
            continue
        return run_dir, run
    raise InstallationError("无法创建唯一备份目录。")


def _atomic_write_bytes(target: Path, data: bytes, home: Path) -> None:
    _validate_write_location(target, home)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", dir=target.parent, prefix=f".{target.name}.", delete=False
        ) as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
            temporary = Path(handle.name)
        os.replace(temporary, target)
        temporary = None
    finally:
        if temporary is not None:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass


def _atomic_copy(source: Path, target: Path, home: Path) -> None:
    _validate_write_location(target, home)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with source.open("rb") as source_handle:
            with tempfile.NamedTemporaryFile(
                mode="wb", dir=target.parent, prefix=f".{target.name}.", delete=False
            ) as handle:
                shutil.copyfileobj(source_handle, handle)
                handle.flush()
                os.fsync(handle.fileno())
                temporary = Path(handle.name)
        os.replace(temporary, target)
        temporary = None
    finally:
        if temporary is not None:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass


def _backup_file(source: Path, backup: Path, home: Path) -> None:
    _validate_write_location(backup, home)
    backup.parent.mkdir(parents=True, exist_ok=True)
    try:
        shutil.copy2(source, backup)
    except (OSError, UnicodeError) as exc:
        raise InstallationError(f"无法备份文件：{source}") from exc


def _sync_changes(home: Path, status_payload: dict[str, Any]) -> list[dict[str, Any]]:
    changes: list[dict[str, Any]] = []
    for name, skill in status_payload["skills"].items():
        for change in skill["changes"]:
            source = Path(change["source"])
            target = Path(change["installed"])
            _validate_write_location(target, home)
            if target.exists() and target.is_dir():
                raise InstallationError(f"目标文件路径是目录：{target}")
            old_hash = _sha256_file(target) if target.exists() else None
            new_hash = _sha256_file(source)
            changes.append(
                {
                    "skill": name,
                    "relative_path": change["path"],
                    "source": _path_text(source),
                    "target": _path_text(target),
                    "old_hash": old_hash,
                    "new_hash": new_hash,
                    "action": change["action"],
                }
            )
    return changes


def _apply_sync(home: Path, host: str, initial: dict[str, Any]) -> dict[str, Any]:
    changes = _sync_changes(home, initial)
    if not changes:
        final = _status_payload(home, host)
        final.update({"operation": "sync", "dry_run": False, "applied": True, "changes": [], "backup": None})
        return final

    run_dir, run = _new_run_directory(home)
    manifest_entries: list[dict[str, Any]] = []
    for change in changes:
        target = Path(change["target"])
        backup_relative: str | None = None
        if target.exists():
            backup_path = run_dir / Path("skills") / Path(change["skill"]) / Path(change["relative_path"])
            _backup_file(target, backup_path, home)
            backup_relative = _path_text(backup_path.relative_to(home))
        manifest_entries.append(
            {
                "source": change["source"],
                "target": change["target"],
                "old_hash": change["old_hash"],
                "new_hash": change["new_hash"],
                "backup_relative_path": backup_relative,
            }
        )

    manifest = {
        "version": 1,
        "run": run,
        "host": host,
        "home": _path_text(home),
        "created_at": _datetime.datetime.now(_datetime.timezone.utc).isoformat(),
        "files": manifest_entries,
    }
    _atomic_write_bytes(
        run_dir / "manifest.json",
        (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
        home,
    )

    for change in changes:
        _atomic_copy(Path(change["source"]), Path(change["target"]), home)

    final = _status_payload(home, host)
    if not final["in_sync"]:
        raise InstallationError("同步完成后仍存在缺失或变更文件。")
    final.update(
        {
            "operation": "sync",
            "dry_run": False,
            "applied": True,
            "changes": changes,
            "backup": {
                "run": run,
                "directory": _path_text(run_dir),
                "manifest": _path_text(run_dir / "manifest.json"),
            },
        }
    )
    return final


def sync(host: str = "codex", home: str | None = None, *, apply: bool = False) -> dict[str, Any]:
    """同步两个 Skill；默认只返回将要执行的变更计划。"""

    resolved_home = _validate_home(home, host)
    initial = _status_payload(resolved_home, host)
    changes = _sync_changes(resolved_home, initial)
    if not apply:
        initial.update(
            {
                "operation": "sync",
                "dry_run": True,
                "applied": False,
                "changes": changes,
                "backup": None,
            }
        )
        return initial
    return _apply_sync(resolved_home, host, initial)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("status", "sync"):
        command = commands.add_parser(name, help=f"{name} 安装状态")
        command.add_argument("--host", choices=("codex", "claude", "pi"), default="codex")
        command.add_argument(
            "--home",
            help="宿主根目录；默认读取 CODEX_HOME、CLAUDE_CONFIG_DIR 或 PI_CODING_AGENT_DIR",
        )
        if name == "sync":
            command.add_argument("--apply", action="store_true", help="实际写入 Skill 文件")
            command.add_argument("--dry-run", action="store_true", help="显式执行默认的预览模式")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "status":
            payload = status(args.host, args.home)
        else:
            if args.apply and args.dry_run:
                raise InstallationError("--apply 与 --dry-run 不能同时使用。")
            payload = sync(args.host, args.home, apply=args.apply)
    except InstallationError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
