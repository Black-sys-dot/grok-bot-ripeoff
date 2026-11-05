"""Shared bot roster for Electron and the browser UI."""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any

DEFAULT_DATA_DIR = Path.home() / ".local" / "share" / "grok-ripeoff" / "user-data"
DATA_DIR = Path(os.environ.get("GROK_USER_DATA", str(DEFAULT_DATA_DIR))).resolve()
STORE = DATA_DIR / "bots.json"
LEGACY_STORE = Path.home() / ".local" / "share" / "grok-ripeoff" / "bots.json"


def _ensure_store_migrated() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not STORE.is_file() and LEGACY_STORE.is_file() and STORE != LEGACY_STORE:
        try:
            shutil.copy2(LEGACY_STORE, STORE)
        except Exception:
            pass


def load_bots() -> dict[str, Any]:
    _ensure_store_migrated()
    try:
        if STORE.is_file():
            data = json.loads(STORE.read_text())
            if isinstance(data, dict) and isinstance(data.get("bots"), list):
                return {
                    "bots": data["bots"],
                    "activeId": str(data.get("activeId") or ""),
                }
    except Exception:
        pass
    return {"bots": [], "activeId": ""}


def save_bots(payload: dict[str, Any]) -> dict[str, Any]:
    _ensure_store_migrated()
    bots = payload.get("bots")
    if not isinstance(bots, list) or not bots:
        raise ValueError("bots must be a non-empty list")
    data = {"bots": bots, "activeId": str(payload.get("activeId") or "")}
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = STORE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data))
    tmp.replace(STORE)
    return data
