from __future__ import annotations

import json
from typing import Any

from openai import OpenAI

from agent.config import (
    OPENROUTER_API_KEY,
    OPENROUTER_APP_NAME,
    OPENROUTER_APP_URL,
    OPENROUTER_BASE_URL,
    OPENROUTER_MODEL,
)

TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "browser_goto",
            "description": "Open a URL in the browser tab.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string"},
                    "wait_until": {
                        "type": "string",
                        "enum": ["domcontentloaded", "load", "networkidle"],
                    },
                },
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browser_click",
            "description": "Click an interactive element by ref (e.g. e3).",
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
            "description": "Type text into an input/textarea by ref.",
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
            "description": "Press a keyboard key (Enter, Tab, Escape, etc.).",
            "parameters": {
                "type": "object",
                "properties": {
                    "key": {"type": "string"},
                    "ref": {"type": "string"},
                },
                "required": ["key"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browser_select",
            "description": "Select an option in a <select> by ref.",
            "parameters": {
                "type": "object",
                "properties": {
                    "ref": {"type": "string"},
                    "value": {"type": "string"},
                },
                "required": ["ref", "value"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browser_scroll",
            "description": "Scroll the page up or down.",
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
            "description": "Wait for dynamic content to load.",
            "parameters": {
                "type": "object",
                "properties": {"seconds": {"type": "number"}},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browser_back",
            "description": "Go back in browser history.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browser_download",
            "description": "Click a link or button that downloads a file. The file is saved in Downloads.",
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
            "name": "download_file",
            "description": "Download a direct http(s) file into this computer's Downloads folder.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string"},
                    "filename": {"type": "string"},
                },
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_files",
            "description": "List a folder on this computer. Defaults to the home directory.",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read a text file on this computer.",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_command",
            "description": (
                "Run a shell command on this computer. Working directory stays inside the home folder. "
                "Use it to unzip, convert, move, or inspect files you downloaded."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string"},
                    "cwd": {"type": "string"},
                },
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_root",
            "description": (
                "Run one shell command as root. Use this only when the normal user cannot do the job. "
                "It does not run until the user approves that exact command."
            ),
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
            "name": "show_on_screen",
            "description": (
                "Put one window on top of the cloud desktop and fill the screen with it. "
                "Call this as the last screen action when the user should see a window. "
                "Take control shows whatever is already on top, so this choice is what they see. "
                "Use browser for the Chromium window, terminal for the terminal, or the window title."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "target": {
                        "type": "string",
                        "description": "browser, terminal, or part of a window title",
                    },
                },
                "required": ["target"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "handoff_computer",
            "description": "Give the user the live computer. Call show_on_screen first so the window they should see is the one on top.",
            "parameters": {
                "type": "object",
                "properties": {
                    "reason": {"type": "string"},
                },
                "required": ["reason"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ask_user",
            "description": (
                "Pause and ask the human for help (CAPTCHA, 2FA, login approval, "
                "payment, or missing secret)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {"type": "string"},
                    "reason": {"type": "string"},
                },
                "required": ["question", "reason"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "finish_task",
            "description": (
                "End the turn. reply is the only text the user will see in chat. "
                "summary is a private one-line note for the activity log."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "reply": {
                        "type": "string",
                        "description": "Message to the user. Speak to them directly. No process narration.",
                    },
                    "summary": {
                        "type": "string",
                        "description": "Private log line. The user does not see this in chat.",
                    },
                    "success": {"type": "boolean"},
                },
                "required": ["reply", "success"],
            },
        },
    },
]


def get_client() -> OpenAI:
    if not OPENROUTER_API_KEY:
        raise RuntimeError(
            "OPENROUTER_API_KEY is not set. Add it to /etc/grok-agent/env on the VPS."
        )
    return OpenAI(
        base_url=OPENROUTER_BASE_URL,
        api_key=OPENROUTER_API_KEY,
        default_headers={
            "HTTP-Referer": OPENROUTER_APP_URL,
            "X-Title": OPENROUTER_APP_NAME,
        },
    )


def chat_with_tools(
    messages: list[dict[str, Any]],
    model: str | None = None,
) -> Any:
    client = get_client()
    return client.chat.completions.create(
        model=model or OPENROUTER_MODEL,
        messages=messages,
        tools=TOOL_DEFINITIONS,
        tool_choice="auto",
        temperature=0.2,
    )


def parse_tool_calls(message: Any) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []
    if not message.tool_calls:
        return calls
    for call in message.tool_calls:
        args = json.loads(call.function.arguments or "{}")
        calls.append({"id": call.id, "name": call.function.name, "arguments": args})
    return calls
