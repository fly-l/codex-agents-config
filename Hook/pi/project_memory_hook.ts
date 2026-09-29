/**
 * 项目记忆 pi 扩展：SessionStart 摘要注入 + Stop 候选登记。
 *
 * 本文件是 Hook/install_pi.py 使用的模板，安装时会替换下面的占位符并写入
 * `$PI_CODING_AGENT_DIR/extensions/project-memory-hook.ts`（默认 `~/.pi/agent/extensions/`）。
 * 两个 Hook 脚本仍由 Python 实现，pi 只负责把生命周期事件转成同一份 JSON 输入。
 */
import { spawn } from "node:child_process";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

const PYTHON = "__PYTHON__";
const SESSION_START = "__SESSION_START__";
const SESSION_END = "__SESSION_END__";
const TIMEOUT_MS = 5000;

/** 运行一次 Hook 脚本并返回标准输出；任何失败都返回空串，不影响 pi 会话。 */
function runHook(script: string, event: Record<string, unknown>): Promise<string> {
  return new Promise((resolve) => {
    const child = spawn(PYTHON, [script, "--host", "pi"], {
      stdio: ["pipe", "pipe", "ignore"],
    });
    let stdout = "";
    let settled = false;
    const finish = (value: string) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      resolve(value);
    };
    const timer = setTimeout(() => {
      child.kill();
      finish("");
    }, TIMEOUT_MS);

    child.stdout.setEncoding("utf-8");
    child.stdout.on("data", (chunk: string) => {
      stdout += chunk;
    });
    child.on("error", () => finish(""));
    child.on("close", (code) => finish(code === 0 ? stdout : ""));
    child.stdin.end(JSON.stringify(event), "utf-8");
  });
}

/** 解析 project_memory_session_start.py 输出的 additionalContext。 */
function parseContext(stdout: string): string | null {
  try {
    const payload = JSON.parse(stdout.trim()) as {
      hookSpecificOutput?: { additionalContext?: unknown };
    };
    const content = payload.hookSpecificOutput?.additionalContext;
    return typeof content === "string" && content.trim() ? content : null;
  } catch {
    return null;
  }
}

export default function (pi: ExtensionAPI) {
  let contextPromise: Promise<string | null> | null = null;
  let injected = false;

  const loadContext = (cwd: string) =>
    runHook(SESSION_START, { cwd, hook_event_name: "SessionStart" }).then(parseContext);

  // pi 的 session_start 对应 Claude Code 的 SessionStart：每个会话只注入一次摘要。
  pi.on("session_start", async (_event, ctx) => {
    injected = false;
    contextPromise = loadContext(ctx.cwd);
    await contextPromise;
  });

  pi.on("before_agent_start", async (_event, ctx) => {
    if (injected) return;
    injected = true;
    const content = await (contextPromise ?? loadContext(ctx.cwd));
    if (!content) return;
    return {
      message: {
        customType: "project-memory-context",
        content,
        display: false,
      },
    };
  });

  // pi 的 agent_settled 对应 Claude Code 的 Stop：只登记待审核元数据。
  pi.on("agent_settled", async (_event, ctx) => {
    await runHook(SESSION_END, {
      cwd: ctx.cwd,
      hook_event_name: "Stop",
      session_id: ctx.sessionManager.getSessionId(),
      transcript_path: ctx.sessionManager.getSessionFile() ?? "",
    });
  });
}
