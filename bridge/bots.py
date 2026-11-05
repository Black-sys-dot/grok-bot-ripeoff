"""Shared bot roster for Electron and the browser UI with isolated user data."""

from __future__ import annotations

import json
import os
import shutil
import threading
import uuid
from pathlib import Path
from typing import Any

_LOCK = threading.Lock()

DEFAULT_DATA_DIR = Path.home() / ".local" / "share" / "grok-ripeoff" / "user-data"
DATA_DIR = Path(os.environ.get("GROK_USER_DATA") or DEFAULT_DATA_DIR).resolve()
STORE = DATA_DIR / "bots.json"
LEGACY_STORE = Path.home() / ".local" / "share" / "grok-ripeoff" / "bots.json"


def _ensure_store_migrated() -> None:
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    except OSError:
        pass

    if not STORE.is_file() and LEGACY_STORE.is_file() and STORE != LEGACY_STORE:
        try:
            content = LEGACY_STORE.read_text(encoding="utf-8")
            parsed = json.loads(content)
            if isinstance(parsed, dict) and isinstance(parsed.get("bots"), list):
                tmp_file = DATA_DIR / f"bots.tmp.{os.getpid()}.{uuid.uuid4().hex}"
                tmp_file.write_text(content, encoding="utf-8")
                tmp_file.chmod(0o600)
                tmp_file.replace(STORE)
                # Rename legacy store so deleted bots aren't resurrected on future restarts
                migrated_target = LEGACY_STORE.with_suffix(".json.migrated")
                try:
                    LEGACY_STORE.rename(migrated_target)
                except OSError:
                    pass
        except Exception:
            pass


def load_bots() -> dict[str, Any]:
    with _LOCK:
        _ensure_store_migrated()
        try:
            if STORE.is_file():
                data = json.loads(STORE.read_text(encoding="utf-8"))
                if isinstance(data, dict) and isinstance(data.get("bots"), list):
                    return {
                        "bots": data["bots"],
                        "activeId": str(data.get("activeId") or ""),
                    }
        except Exception:
            pass
        return {"bots": [], "activeId": ""}


def save_bots(payload: dict[str, Any]) -> dict[str, Any]:
    with _LOCK:
        _ensure_store_migrated()
        bots = payload.get("bots")
        if not isinstance(bots, list) or not bots:
            raise ValueError("bots must be a non-empty list")
        data = {"bots": bots, "activeId": str(payload.get("activeId") or "")}
        try:
            DATA_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
            tmp = DATA_DIR / f"bots.tmp.{os.getpid()}.{uuid.uuid4().hex}"
            tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
            tmp.chmod(0o600)
            tmp.replace(STORE)
        except Exception as exc:
            raise ValueError(f"Failed to persist bot roster: {exc}") from exc
        return data
