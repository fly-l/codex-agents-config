#!/usr/bin/env python3
"""在 Codex SessionEnd 时启动一次性子代理整理当前对话标题。"""

from __future__ import annotations

import datetime as dt
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


CHILD_ENV = "CODEX_RENAME_CURRENT_TITLE_CHILD"
SKILL_ENV = "CODEX_RENAME_CURRENT_TITLE_SKILL"
MODEL_ENV = "CODEX_RENAME_CURRENT_TITLE_MODEL"
APP_TOOLS_SERVER_ENV = "CODEX_APP_TOOLS_SERVER"
APP_TOOLS_PIPE_ENV = "CODEX_APP_TOOLS_PIPE_PATH"
MCP_NODE_ENV = "CODEX_MCP_NODE_PATH"
CLI_ENV = "CODEX_CLI_PATH"
ALLOWED_TYPES = "功能|设计|修复|优化|发布|探索|文档|研究"
TITLE_PATTERN = re.compile(
    rf"^(?P<date>\d{{4}})｜(?P<kind>{ALLOWED_TYPES})｜"
    r"(?P<topic>[^\s｜](?:[^｜\r\n]*[^\s｜])?)$"
)
THREAD_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,200}$")

try:
    SHANGHAI = ZoneInfo("Asia/Shanghai")
except ZoneInfoNotFoundError:
    # Asia/Shanghai 全年固定为 UTC+08:00；缺少系统时区数据库时保持相同结果。
    SHANGHAI = dt.timezone(dt.timedelta(hours=8))


def created_at_mmdd(value: Any) -> str | None:
    """将线程的 createdAt 转换为上海时区的 MMDD。"""

    try:
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            timestamp = float(value)
            if timestamp > 10_000_000_000:
                timestamp /= 1000
            parsed = dt.datetime.fromtimestamp(timestamp, tz=dt.timezone.utc)
        elif isinstance(value, str) and value.strip():
            raw = value.strip()
            if raw.endswith("Z"):
                raw = raw[:-1] + "+00:00"
            parsed = dt.datetime.fromisoformat(raw)
            if parsed.tzinfo is None:
                return None
        else:
            return None
    except (OSError, OverflowError, TypeError, ValueError):
        return None
    return parsed.astimezone(SHANGHAI).strftime("%m%d")


def is_organized_title(title: Any, created_at: Any) -> bool:
    """仅在标题格式正确且日期确实来自 createdAt 时返回 True。"""

    if not isinstance(title, str):
        return False
    match = TITLE_PATTERN.fullmatch(title)
    expected_date = created_at_mmdd(created_at)
    return bool(match and expected_date and match.group("date") == expected_date)


def thread_id_from_event(event: dict[str, Any]) -> str | None:
    for key in ("thread_id", "threadId", "session_id"):
        value = event.get(key)
        if isinstance(value, str) and THREAD_ID_PATTERN.fullmatch(value):
            return value
    return None


def configured_skill() -> Path | None:
    configured = os.environ.get(SKILL_ENV, "").strip()
    if configured:
        path = Path(os.path.expandvars(configured)).expanduser()
    else:
        codex_home = Path(
            os.path.expandvars(os.environ.get("CODEX_HOME", "~/.codex"))
        ).expanduser()
        path = codex_home / "skills" / "rename-current-conversation-title" / "SKILL.md"
    return path if path.is_file() else None


def configured_cli() -> str | None:
    configured = os.environ.get(CLI_ENV, "").strip().strip('"')
    if configured:
        return configured
    return shutil.which("codex")


def configured_node() -> str | None:
    configured = os.environ.get(MCP_NODE_ENV, "").strip().strip('"')
    if configured:
        return configured
    return shutil.which("node")


def configured_app_tools_server() -> Path | None:
    configured = os.environ.get(APP_TOOLS_SERVER_ENV, "").strip().strip('"')
    if configured:
        path = Path(configured)
        return path if path.is_file() else None

    codex_home = Path(
        os.path.expandvars(os.environ.get("CODEX_HOME", "~/.codex"))
    ).expanduser()
    roots = (
        codex_home / "plugins" / "cache" / "openai-bundled" / "codex-app-tools",
        codex_home
        / ".tmp"
        / "bundled-marketplaces"
        / "openai-bundled"
        / "plugins"
        / "codex-app-tools",
    )
    candidates: list[Path] = []
    for root in roots:
        candidates.append(root / "server.mjs")
        if root.is_dir():
            candidates.extend(sorted(root.glob("*/server.mjs"), reverse=True))
    return next((path for path in candidates if path.is_file()), None)


def toml_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def app_tools_overrides(
    node: str, server: Path, pipe: str, thread_id: str
) -> list[str]:
    args = [str(server), "--interaction-client-id", thread_id]
    return [
        "-c",
        'mcp_servers.codex_app_tools.type="stdio"',
        "-c",
        f"mcp_servers.codex_app_tools.command={toml_string(node)}",
        "-c",
        "mcp_servers.codex_app_tools.args=["
        + ",".join(toml_string(value) for value in args)
        + "]",
        "-c",
        "mcp_servers.codex_app_tools.env.CODEX_APP_TOOLS_PIPE_PATH="
        + toml_string(pipe),
        "-c",
        'mcp_servers.codex_app_tools.tools.read_thread.approval_mode="approve"',
        "-c",
        'mcp_servers.codex_app_tools.tools.set_thread_title.approval_mode="approve"',
    ]


def build_prompt(thread_id: str, skill_path: Path, transcript_path: str) -> str:
    return f"""你是 Codex SessionEnd 的一次性标题整理子代理。

这是用户已经明确授权的自动化任务：请完整遵守标题整理 Skill 的命名和不可变范围规则，但不要输出确认表、不要等待再次确认。先读取并遵守 Skill：{json.dumps(str(skill_path), ensure_ascii=False)}。

目标线程 ID：{json.dumps(thread_id, ensure_ascii=False)}
SessionEnd 提供的 transcript 路径（仅在需要核对当前线程内容时读取）：{json.dumps(transcript_path, ensure_ascii=False)}

执行要求：
1. 只读取目标线程，不读取其他线程、项目列表或归档列表。通过当前代理实际显示的 Codex App-Tools MCP 调用 read_thread，核实返回的 thread.id 必须等于目标线程 ID，并读取标题、用户消息和 createdAt；此一次性进程中的工具前缀通常是 mcp__codex_app_tools__，以实际可用名称为准。日期必须由 createdAt 按 Asia/Shanghai 转换，绝对不要使用 updatedAt、SessionEnd 时间或 created_at。
2. 如果当前标题已经严格符合 MMDD｜类型｜主题，且 MMDD 与 createdAt 一致，立即结束，不调用任何写入工具。
3. 如果无法从目标线程实际内容可靠判断主题，也立即结束并保留原名，不猜测。
4. 只有能够确定新标题时，才通过当前代理实际显示的 Codex App-Tools MCP 调用 set_thread_title，目标 threadId 必须是 {json.dumps(thread_id, ensure_ascii=False)}。标题格式只能使用功能、设计、修复、优化、发布、探索、文档、研究之一。
5. 除标题外绝对不能修改项目名称、项目归属、对话内容、排序、置顶、归档或其他线程；不能发送消息，不能创建或继续其他代理，不能通过文件、SQLite 或其他 CLI 直接修改标题。
6. 如果 App-Tools MCP 不可用，立即停止，不使用替代写入方式。

完成后不需要向用户发送消息，只结束本次子代理运行。"""


def build_command(
    cli: str,
    cwd: Path | None,
    thread_id: str,
    prompt: str,
    node: str,
    server: Path,
    pipe: str,
) -> list[str]:
    command = [
        cli,
        "exec",
        "--ephemeral",
        "--skip-git-repo-check",
        "--sandbox",
        "read-only",
    ]
    if cwd is not None:
        command.extend(["-C", str(cwd)])
    model = os.environ.get(MODEL_ENV, "").strip()
    if model:
        command.extend(["--model", model])
    command.extend(app_tools_overrides(node, server, pipe, thread_id))
    command.append(prompt)
    return command


def spawn_agent(command: list[str], cwd: Path | None) -> None:
    environment = os.environ.copy()
    environment[CHILD_ENV] = "1"
    kwargs: dict[str, Any] = {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "env": environment,
        "close_fds": True,
    }
    if os.name == "nt":
        kwargs["creationflags"] = (
            getattr(subprocess, "DETACHED_PROCESS", 0)
            | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        )
    else:
        kwargs["start_new_session"] = True
    if cwd is not None:
        kwargs["cwd"] = str(cwd)
    subprocess.Popen(command, **kwargs)


def main() -> None:
    if os.environ.get(CHILD_ENV) == "1":
        return

    try:
        event = json.load(sys.stdin)
    except (json.JSONDecodeError, OSError):
        return
    if not isinstance(event, dict):
        return

    thread_id = thread_id_from_event(event)
    pipe = os.environ.get(APP_TOOLS_PIPE_ENV, "").strip()
    cli = configured_cli()
    node = configured_node()
    server = configured_app_tools_server()
    skill_path = configured_skill()
    if not thread_id or not pipe or not cli or not node or not server or not skill_path:
        return

    cwd_value = event.get("cwd")
    cwd = Path(cwd_value) if isinstance(cwd_value, str) and cwd_value else None
    if cwd is not None and not cwd.is_dir():
        cwd = None
    transcript = event.get("transcript_path")
    transcript_path = transcript if isinstance(transcript, str) else ""
    prompt = build_prompt(thread_id, skill_path, transcript_path)
    command = build_command(cli, cwd, thread_id, prompt, node, server, pipe)
    try:
        spawn_agent(command, cwd)
    except (OSError, ValueError):
        return


if __name__ == "__main__":
    main()
