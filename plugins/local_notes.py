"""Local Notes & Memory Plugin for Grok Bot.

Stores lightweight notes, bookmarks, and reminders on the user's laptop.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

PLUGIN_META = {
    "id": "local_notes",
    "name": "Local Notes & Reminders",
    "description": "Save, list, and read personal notes and scratchpads on your laptop.",
    "version": "1.0.0",
}

USER_DATA_DIR = Path(
    os.environ.get("GROK_USER_DATA")
    or (Path.home() / ".local" / "share" / "grok-ripeoff" / "user-data")
).resolve()
NOTES_DIR = USER_DATA_DIR / "notes"


def _ensure_dir() -> Path:
    NOTES_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    return NOTES_DIR


def _sanitize_title(title: str) -> str:
    cleaned = re.sub(r"[^\w\s.-]", "", title).strip()
    return cleaned.replace(" ", "_") or "untitled"


def local_save_note(title: str, content: str) -> dict[str, Any]:
    """Save a local note or snippet.

    Args:
        title: Title or filename of the note.
        content: Note body content.
    """
    d = _ensure_dir()
    slug = _sanitize_title(title)
    if not slug.endswith(".md"):
        slug += ".md"
    file_path = d / slug
    try:
        file_path.write_text(content, encoding="utf-8")
        file_path.chmod(0o600)
        return {
            "ok": True,
            "title": title,
            "path": str(file_path),
            "detail": f"Note '{title}' saved successfully.",
        }
    except Exception as exc:
        return {"ok": False, "error": f"Failed to save note: {exc}"}


def local_list_notes() -> dict[str, Any]:
    """List all saved notes on this machine."""
    d = _ensure_dir()
    notes = []
    try:
        for p in sorted(d.glob("*.md")):
            stat = p.stat()
            notes.append({
                "title": p.stem.replace("_", " "),
                "file": p.name,
                "modified": stat.st_mtime,
                "size_bytes": stat.st_size,
            })
        return {"ok": True, "total": len(notes), "notes": notes}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def local_read_note(title: str) -> dict[str, Any]:
    """Read a saved local note by title.

    Args:
        title: Note title to read.
    """
    d = _ensure_dir()
    slug = _sanitize_title(title)
    if not slug.endswith(".md"):
        slug += ".md"
    target = d / slug
    if not target.is_file():
        # Try loose search
        for p in d.glob("*.md"):
            if title.lower() in p.stem.lower():
                target = p
                break

    if not target.is_file():
        return {"ok": False, "error": f"Note not found: {title}"}

    try:
        return {
            "ok": True,
            "title": target.stem.replace("_", " "),
            "content": target.read_text(encoding="utf-8"),
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


TOOLS = [
    {
        "name": "local_save_note",
        "description": "Save a text note or memory snippet to your local computer.",
        "parameters": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Title or headline of the note."},
                "content": {"type": "string", "description": "Markdown or text content."},
            },
            "required": ["title", "content"],
        },
        "func": local_save_note,
    },
    {
        "name": "local_list_notes",
        "description": "List all notes previously saved on this local machine.",
        "parameters": {"type": "object", "properties": {}},
        "func": local_list_notes,
    },
    {
        "name": "local_read_note",
        "description": "Read the contents of a saved local note by title.",
        "parameters": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Title or keyword of the note."}
            },
            "required": ["title"],
        },
        "func": local_read_note,
    },
]
