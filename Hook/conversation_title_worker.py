#!/usr/bin/env python3
"""后台检查标题，只有需要整理时才调用模型，并核验最终标题。"""

from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any

import conversation_title_session_end as hook


class AppTools:
    """通过桌面提供的 MCP stdio 通道读取目标线程。"""

    def __init__(self, thread_id: str):
        self.thread_id = thread_id
        self.process = subprocess.Popen(
            [hook.configured_node(), str(hook.configured_app_tools_server())],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, encoding="utf-8",
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        self.responses: queue.Queue = queue.Queue()
        self.request_id = 0
        threading.Thread(target=self.read_lines, daemon=True).start()
        try:
            self.request("initialize", {
                "protocolVersion": "2024-11-05", "capabilities": {},
                "clientInfo": {"name": "conversation-title-check", "version": "1"},
            })
            self.process.stdin.write(json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n")
            self.process.stdin.flush()
            self.request("tools/list", {})
        except Exception:
            self.close()
            raise

    def read_lines(self) -> None:
        for line in self.process.stdout:
            try:
                self.responses.put(json.loads(line))
            except json.JSONDecodeError:
                self.responses.put({"error": "invalid_json"})
        self.responses.put({"error": "eof"})

    def request(self, method: str, params: dict) -> dict:
        self.request_id += 1
        if method == "tools/call":
            params = {
                **params,
                "_meta": {"x-codex-turn-metadata": {"thread_id": self.thread_id}},
            }
        self.process.stdin.write(json.dumps({"jsonrpc": "2.0", "id": self.request_id,
                                            "method": method, "params": params}) + "\n")
        self.process.stdin.flush()
        # 通道响应是外部输入；超时、错误和提前退出都必须快速失败。
        import time
        deadline = time.monotonic() + 30
        while True:
            response = self.responses.get(timeout=max(0, deadline - time.monotonic()))
            if "error" in response:
                raise RuntimeError("app_tools_error")
            if response.get("id") == self.request_id:
                return response["result"]

    def read_thread(self, thread_id: str) -> dict:
        result = self.request("tools/call", {"name": "read_thread", "arguments": {
            "threadId": thread_id, "turnLimit": 20, "includeOutputs": False,
        }})
        if result.get("isError"):
            raise RuntimeError("read_thread_failed")
        payload = json.loads("".join(item["text"] for item in result["content"]
                                    if item.get("type") == "text"))
        thread = payload["thread"]
        if thread.get("id") != thread_id or not hook.created_at_mmdd(thread.get("createdAt")):
            raise ValueError("invalid_thread_identity_or_date")
        user_messages = []
        for turn in payload.get("turns", []):
            for item in turn.get("items", []):
                if item.get("type") != "userMessage":
                    continue
                content = item.get("content", [])
                message = "".join(
                    part.get("text", "")
                    for part in content
                    if isinstance(part, dict) and part.get("type") == "text"
                )
                if message:
                    user_messages.append(message[-4000:])
        thread["user_messages"] = user_messages[-12:]
        return thread

    def set_thread_title(self, title: str) -> None:
        result = self.request("tools/call", {"name": "set_thread_title", "arguments": {
            "source": "codex", "threadId": self.thread_id, "title": title,
        }})
        if result.get("isError"):
            raise RuntimeError("set_thread_title_failed")

    def close(self) -> None:
        self.process.terminate()
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait()
        self.process.stdin.close()
        self.process.stdout.close()


def organize(thread_id: str, cwd: Path | None, app: Any) -> None:
    before = app.read_thread(thread_id)
    if hook.is_organized_title(before.get("title"), before["createdAt"]):
        hook.write_status(thread_id, "already_organized")
        return
    prompt = hook.build_prompt(thread_id, hook.configured_skill(), before)
    command = hook.build_command(hook.configured_cli(), cwd)
    hook.write_status(thread_id, "agent_started")
    result = subprocess.run(command, input=prompt, stdout=subprocess.PIPE,
                            stderr=subprocess.DEVNULL, text=True, encoding="utf-8", timeout=180,
                            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    if result.returncode:
        hook.write_status(thread_id, "agent_failed", returncode=result.returncode)
        return
    title = result.stdout.strip()
    if not hook.is_organized_title(title, before["createdAt"]):
        hook.write_status(thread_id, "invalid_title")
        return
    if title == before.get("title"):
        hook.write_status(thread_id, "unchanged")
        return
    app.set_thread_title(title)
    after = app.read_thread(thread_id)
    if after["createdAt"] != before["createdAt"]:
        raise ValueError("created_at_changed")
    if after.get("title") == title and hook.is_organized_title(after.get("title"), after["createdAt"]):
        hook.write_status(thread_id, "verified")
    else:
        hook.write_status(thread_id, "verification_failed")


def main() -> None:
    thread_id, cwd_text = sys.argv[1:]
    app = None
    try:
        app = AppTools(thread_id)
        organize(thread_id, Path(cwd_text) if cwd_text else None, app)
    except subprocess.TimeoutExpired:
        hook.write_status(thread_id, "agent_timeout")
    except Exception as error:
        hook.write_status(thread_id, "worker_failed", error_type=type(error).__name__)
    finally:
        if app is not None:
            app.close()


if __name__ == "__main__":
    main()
