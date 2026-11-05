"""Public chat history only. Tool traces never go back into the next prompt.

Each bot keeps its own transcript. They still share the computer.
"""

from __future__ import annotations

import json
import re
from contextvars import ContextVar, Token
from pathlib import Path
from threading import Lock

from agent.config import MEMORY_DIR

_LOCK = Lock()
_PATH = MEMORY_DIR / "chat.json"
_MAX = 24
_BOT: ContextVar[str] = ContextVar("grok_bot_id", default="")


def begin_bot(bot_id: str | None) -> Token[str]:
    key = re.sub(r"[^A-Za-z0-9_-]", "", (bot_id or "").strip())[:40]
    return _BOT.set(key)


def end_bot(token: Token[str]) -> None:
    _BOT.reset(token)


def _history_path() -> Path:
    key = _BOT.get()
    if not key or key == "default":
        return _PATH
    return MEMORY_DIR / f"chat-{key}.json"


def load_history() -> list[dict[str, str]]:
    path = _history_path()
    with _LOCK:
        if not path.is_file():
            return []
        try:
            data = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            return []
        if not isinstance(data, list):
            return []
        out: list[dict[str, str]] = []
        for item in data[-_MAX:]:
            if not isinstance(item, dict):
                continue
            role = item.get("role")
            content = item.get("content")
            if role in ("user", "assistant") and isinstance(content, str) and content.strip():
                out.append({"role": role, "content": content.strip()})
        return out


def append_turn(user_text: str, assistant_text: str) -> None:
    if not user_text.strip() or not assistant_text.strip():
        return
    path = _history_path()
    with _LOCK:
        history = []
        if path.is_file():
            try:
                raw = json.loads(path.read_text())
                if isinstance(raw, list):
                    history = raw
            except (OSError, json.JSONDecodeError):
                history = []
        history.append({"role": "user", "content": user_text.strip()})
        history.append({"role": "assistant", "content": assistant_text.strip()})
        MEMORY_DIR.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(history[-_MAX:], indent=2))


def clear() -> None:
    path = _history_path()
    with _LOCK:
        if path.is_file():
            path.unlink()
