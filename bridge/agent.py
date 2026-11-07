"""Local Agent Orchestrator for Grok Bot.

Runs the agent loop directly on the user's machine (in the bridge),
orchestrating local plugins, local MCP servers, and the cloud VPS computer.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
from pathlib import Path
from typing import Any

import httpx
from openai import OpenAI

from bridge.mcp import REGISTRY as mcp_registry
from bridge.plugins import REGISTRY as plugin_registry

logger = logging.getLogger("grok.agent")

USER_DATA_DIR = Path(
    os.environ.get("GROK_USER_DATA")
    or (Path.home() / ".local" / "share" / "grok-ripeoff" / "user-data")
).resolve()

_OPENROUTER_KEY_CACHE = os.environ.get("OPENROUTER_API_KEY", "")
_OPENROUTER_MODEL_CACHE = os.environ.get("OPENROUTER_MODEL", "")

CLOUD_TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "browser_goto",
            "description": "Open a URL in the cloud browser tab.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string"},
                    "wait_until": {"type": "string", "enum": ["domcontentloaded", "load", "networkidle"]},
                },
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browser_click",
            "description": "Click an interactive element in the cloud browser by ref (e.g. e3).",
            "parameters": {
                "type": "object",
                "properties": {"ref": {"type": "string"}},
                "required": ["ref"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browser_type",
            "description": "Type text into a cloud browser input/textarea by ref.",
            "parameters": {
                "type": "object",
                "properties": {
                    "ref": {"type": "string"},
                    "text": {"type": "string"},
                    "clear": {"type": "boolean"},
                },
                "required": ["ref", "text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browser_press",
            "description": "Press a keyboard key in the cloud browser (Enter, Tab, Escape, etc.).",
            "parameters": {
                "type": "object",
                "properties": {"key": {"type": "string"}, "ref": {"type": "string"}},
                "required": ["key"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browser_scroll",
            "description": "Scroll the cloud browser page up or down.",
            "parameters": {
                "type": "object",
                "properties": {
                    "direction": {"type": "string", "enum": ["up", "down"]},
                    "amount": {"type": "integer"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browser_wait",
            "description": "Wait for dynamic content to load in the cloud browser.",
            "parameters": {
                "type": "object",
                "properties": {"seconds": {"type": "number"}},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "show_on_screen",
            "description": "Put one window on top of the cloud desktop (e.g. 'browser', 'terminal').",
            "parameters": {
                "type": "object",
                "properties": {"target": {"type": "string"}},
                "required": ["target"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_root",
            "description": "Run a shell command as root on the cloud VPS computer (requires user approval).",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string"},
                    "reason": {"type": "string"},
                },
                "required": ["command", "reason"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "handoff_computer",
            "description": "Give the user control of the cloud computer screen when their manual input is needed.",
            "parameters": {
                "type": "object",
                "properties": {"reason": {"type": "string"}},
                "required": ["reason"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ask_user",
            "description": "Pause and ask the human a clarifying question or request credentials/help.",
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {"type": "string"},
                    "reason": {"type": "string"},
                },
                "required": ["question"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "finish_task",
            "description": "Mark the task as finished and provide a final answer or summary to the user.",
            "parameters": {
                "type": "object",
                "properties": {
                    "success": {"type": "boolean"},
                    "summary": {"type": "string"},
                    "reply": {"type": "string"},
                },
                "required": ["summary", "reply"],
            },
        },
    },
]

BASE_SYSTEM_PROMPT = """You are Grok Ripeoff, an intelligent autonomous agent running locally on the user's computer.
You have two distinct sets of capabilities:

1. LOCAL TOOLS (Running directly on the user's laptop):
   - Local Plugins (prefixed 'plugin__'): Access local files, notes, and local system telemetry.
   - Local MCP Servers (prefixed 'mcp__'): Model Context Protocol tools for services like Notion, YouTube, etc.
   Use local tools whenever the user asks about their personal machine, local files, notes, or local workflows.

2. CLOUD COMPUTER & BROWSER (Running on the remote cloud desktop on the right):
   - Cloud Tools (browser_goto, browser_click, browser_type, etc.): Perform live web browsing, form filling, research, or cloud computing.
   - You can also view or control the cloud desktop on the right.

Rules:
- Be concise, direct, and helpful.
- Choose the appropriate local or cloud tools to achieve the user's goal.
- When done, call 'finish_task' with your complete summary and reply.
- If you need the human's input or intervention, call 'ask_user'.
"""


def _resolve_openrouter_credentials(ssh_host: str) -> tuple[str, str]:
    global _OPENROUTER_KEY_CACHE, _OPENROUTER_MODEL_CACHE
    if _OPENROUTER_KEY_CACHE and _OPENROUTER_MODEL_CACHE:
        return _OPENROUTER_KEY_CACHE, _OPENROUTER_MODEL_CACHE

    key = os.environ.get("OPENROUTER_API_KEY", "")
    model = os.environ.get("OPENROUTER_MODEL", "")

    # Check local config in user-data
    cfg_file = USER_DATA_DIR / "config.json"
    if cfg_file.is_file():
        try:
            cfg = json.loads(cfg_file.read_text(encoding="utf-8"))
            key = key or cfg.get("openrouter_api_key", "")
            model = model or cfg.get("openrouter_model", "")
        except Exception:
            pass

    # If still not found, check VPS /etc/grok-agent/env over SSH
    if not key:
        try:
            out = subprocess.check_output(
                ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5", "--", ssh_host, "cat /etc/grok-agent/env"],
                text=True,
                timeout=8,
            )
            for line in out.splitlines():
                line = line.strip()
                if line.startswith("OPENROUTER_API_KEY="):
                    key = line.split("=", 1)[1].strip()
                elif line.startswith("OPENROUTER_MODEL="):
                    model = line.split("=", 1)[1].strip()
        except Exception:
            pass

    _OPENROUTER_KEY_CACHE = key or _OPENROUTER_KEY_CACHE
    _OPENROUTER_MODEL_CACHE = model or _OPENROUTER_MODEL_CACHE or "google/gemini-2.5-flash"
    return _OPENROUTER_KEY_CACHE, _OPENROUTER_MODEL_CACHE


def _log_activity(activity: list[dict[str, Any]], step: int, kind: str, title: str, detail: str) -> None:
    activity.append({
        "step": step,
        "kind": kind,
        "title": title,
        "detail": detail[:2000] if detail else "",
    })


def run_orchestrated_task(
    goal: str,
    persona: str = "",
    bot_id: str = "default",
    agent_base: str = "http://127.0.0.1:8765",
    ssh_host: str = "webeye-vps",
    agent_headers: dict[str, str] | None = None,
    max_steps: int = 25,
) -> dict[str, Any]:
    api_key, model = _resolve_openrouter_credentials(ssh_host)
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY not configured locally or on cloud VPS.")

    client = OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=api_key,
        default_headers={
            "HTTP-Referer": "https://github.com/black/grok-ripeoff",
            "X-Title": "Grok Ripeoff",
        },
    )

    # Gather tools: Cloud tools + Local Plugins + Local MCP servers
    tools = list(CLOUD_TOOLS)
    tools.extend(mcp_registry.get_definitions())
    tools.extend(plugin_registry.get_definitions())

    system_prompt = BASE_SYSTEM_PROMPT
    if persona:
        system_prompt += f"\n\nBot Persona & Focus:\n{persona.strip()[:2000]}"

    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": goal},
    ]

    activity: list[dict[str, Any]] = []
    last_url: str | None = None
    last_screenshot: str | None = None

    for step in range(1, max_steps + 1):
        try:
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                tools=tools,
                tool_choice="auto",
                temperature=0.2,
            )
        except Exception as exc:
            logger.exception("LLM call failed: %s", exc)
            _log_activity(activity, step, "error", "llm_error", str(exc))
            return {
                "status": "failed",
                "reply": f"Model error: {exc}",
                "activity": activity,
            }

        choice = response.choices[0].message
        if choice.content and choice.tool_calls:
            _log_activity(activity, step, "thought", "thinking", choice.content.strip())

        if not choice.tool_calls:
            reply_text = choice.content or "Done."
            _log_activity(activity, step, "reply", "message", reply_text)
            return {
                "status": "completed",
                "reply": reply_text,
                "activity": activity,
                "url": last_url,
                "screenshot_base64": last_screenshot,
            }

        # Append assistant response with tool calls to history
        assistant_msg: dict[str, Any] = {
            "role": "assistant",
            "content": choice.content,
            "tool_calls": [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                }
                for tc in choice.tool_calls
            ],
        }
        messages.append(assistant_msg)

        for tc in choice.tool_calls:
            t_name = tc.function.name
            raw_args = tc.function.arguments
            try:
                args = json.loads(raw_args) if isinstance(raw_args, str) else (raw_args or {})
            except Exception:
                args = {}

            # 1. finish_task
            if t_name == "finish_task":
                success = bool(args.get("success", True))
                summary = args.get("summary", "")
                reply = args.get("reply", "") or summary
                _log_activity(activity, step, "note", "done" if success else "stopped", summary)
                return {
                    "status": "completed" if success else "failed",
                    "reply": reply,
                    "activity": activity,
                    "url": last_url,
                    "screenshot_base64": last_screenshot,
                }

            # 2. ask_user
            if t_name == "ask_user":
                question = args.get("question", "I need your input.")
                reason = args.get("reason", "")
                _log_activity(activity, step, "wait", "needs you", reason or question)
                return {
                    "status": "needs_user",
                    "reply": question,
                    "question": question,
                    "activity": activity,
                    "url": last_url,
                    "screenshot_base64": last_screenshot,
                }

            # 3. handoff_computer
            if t_name == "handoff_computer":
                reason = args.get("reason", "Take control of the computer")
                _log_activity(activity, step, "wait", "computer", reason)
                return {
                    "status": "needs_user",
                    "reply": "The computer is on the right. Take control and use it.",
                    "activity": activity,
                    "url": last_url,
                    "screenshot_base64": last_screenshot,
                }

            # 4. Local MCP Tool call (mcp__<server>__<tool>)
            if t_name.startswith("mcp__"):
                mcp_res = mcp_registry.call_tool(t_name, args)
                ok = mcp_res.get("ok", True)
                server_tag = t_name.split("__")[1] if len(t_name.split("__")) > 1 else "mcp"
                _log_activity(activity, step, "tool" if ok else "error", f"mcp:{server_tag}", str(mcp_res.get("content", mcp_res))[:1000])
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": json.dumps(mcp_res),
                })
                continue

            # 5. Local Plugin Tool call (plugin__<id>__<tool>)
            if t_name.startswith("plugin__"):
                plug_res = plugin_registry.call_tool(t_name, args)
                ok = plug_res.get("ok", True)
                p_id = t_name.split("__")[1] if len(t_name.split("__")) > 1 else "plugin"
                detail = plug_res.get("detail") or plug_res.get("result") or plug_res.get("error") or plug_res
                _log_activity(activity, step, "tool" if ok else "error", f"plugin:{p_id}", str(detail)[:1000])
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": json.dumps(plug_res),
                })
                continue

            # 6. Cloud VPS Tools (browser_*, run_root, show_on_screen, etc.)
            try:
                r = httpx.post(
                    f"{agent_base}/agent/tool",
                    headers=agent_headers or {},
                    json={"name": t_name, "arguments": args},
                    timeout=90.0,
                )
                if r.is_success:
                    cloud_res = r.json()
                    last_url = cloud_res.get("url") or last_url
                    last_screenshot = cloud_res.get("screenshot_base64") or last_screenshot

                    # Check for root approval needed
                    if cloud_res.get("root_approval"):
                        approval = cloud_res["root_approval"]
                        _log_activity(activity, step, "wait", "root", args.get("command", ""))
                        return {
                            "status": "needs_root",
                            "reply": "I need root for one command. Approve it below if you want it to run.",
                            "activity": activity,
                            "root_approval": approval,
                            "url": last_url,
                            "screenshot_base64": last_screenshot,
                        }

                    obs = cloud_res.get("observation", "")
                    detail = cloud_res.get("detail", "")
                    content_str = obs or detail or json.dumps(cloud_res)
                    _log_activity(activity, step, "tool", t_name.removeprefix("browser_"), detail or obs or "executed")
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": content_str,
                    })
                else:
                    err_msg = f"VPS HTTP {r.status_code}: {r.text}"
                    _log_activity(activity, step, "error", t_name, err_msg)
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": json.dumps({"ok": False, "error": err_msg}),
                    })
            except Exception as exc:
                err_msg = f"Failed to reach VPS tool endpoint: {exc}"
                _log_activity(activity, step, "error", t_name, err_msg)
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": json.dumps({"ok": False, "error": err_msg}),
                })

    return {
        "status": "failed",
        "reply": "I stopped before this was finished (max step limit reached). Check the activity log for details.",
        "activity": activity,
        "url": last_url,
        "screenshot_base64": last_screenshot,
    }
