"""Local Filesystem Plugin for Grok Bot.

Provides safe access to files on the user's laptop.
"""

from __future__ import annotations

import fnmatch
from pathlib import Path
from typing import Any

PLUGIN_META = {
    "id": "local_files",
    "name": "Local Files",
    "description": "Read, list, and search files and directories on your local machine.",
    "version": "1.0.0",
}

MAX_FILE_BYTES = 500_000  # 500 KB limit for reading text files into context

BLOCKED_SENSITIVE_PARTS = {
    ".ssh",
    ".gnupg",
    ".aws",
    ".azure",
    ".kube",
    ".docker",
    "id_rsa",
    "id_ed25519",
    "id_ecdsa",
    "id_dsa",
    "shadow",
    "gshadow",
    "sudoers",
    ".bash_history",
    ".zsh_history",
}


def _resolve_path(raw: str) -> Path:
    p = Path(raw).expanduser()
    if not p.is_absolute():
        p = (Path.home() / p).resolve()
    else:
        p = p.resolve()
    return p


def local_list_directory(path: str = "") -> dict[str, Any]:
    """List contents of a directory on your local laptop.

    Args:
        path: Directory path. Defaults to home directory if empty.
    """
    target = _resolve_path(path) if path else Path.home()
    if not target.exists():
        return {"ok": False, "error": f"Path not found: {target}"}
    if not target.is_dir():
        return {"ok": False, "error": f"Not a directory: {target}"}

    items = []
    try:
        for entry in sorted(target.iterdir()):
            if entry.name.startswith("."):
                continue
            items.append({
                "name": entry.name,
                "is_dir": entry.is_dir(),
                "size_bytes": entry.stat().st_size if entry.is_file() else None,
            })
        return {
            "ok": True,
            "path": str(target),
            "total": len(items),
            "items": items[:100],  # Bound to 100 items
        }
    except PermissionError:
        return {"ok": False, "error": f"Permission denied accessing {target}"}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def local_read_file(path: str) -> dict[str, Any]:
    """Read contents of a text file from your local laptop.

    Args:
        path: Path to the file.
    """
    target = _resolve_path(path)
    if any(part in BLOCKED_SENSITIVE_PARTS for part in target.parts):
        return {"ok": False, "error": "Access to sensitive credentials/keys is blocked for security."}

    if not target.is_file():
        return {"ok": False, "error": f"File not found: {target}"}

    try:
        stat = target.stat()
        if stat.st_size > MAX_FILE_BYTES:
            return {
                "ok": False,
                "error": f"File is too large ({stat.st_size} bytes). Limit is {MAX_FILE_BYTES} bytes.",
            }
        content = target.read_text(encoding="utf-8", errors="replace")
        return {
            "ok": True,
            "path": str(target),
            "size": stat.st_size,
            "content": content,
        }
    except PermissionError:
        return {"ok": False, "error": f"Permission denied reading {target}"}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def local_search_files(folder: str = "", pattern: str = "*") -> dict[str, Any]:
    """Search for files matching a pattern in a local folder (depth 3 max).

    Args:
        folder: Folder to search in. Defaults to current or home directory.
        pattern: Wildcard search pattern (e.g. '*.py', '*.pdf', 'notes*').
    """
    base = _resolve_path(folder) if folder else Path.home()
    if not base.is_dir():
        return {"ok": False, "error": f"Folder not found: {base}"}

    matches = []
    try:
        for p in base.rglob(pattern):
            # Ignore hidden dirs like .git, node_modules
            if any(part.startswith(".") or part in ("node_modules", ".venv") for part in p.parts):
                continue
            if len(p.relative_to(base).parts) > 3:
                continue
            matches.append({
                "path": str(p),
                "is_dir": p.is_dir(),
                "size_bytes": p.stat().st_size if p.is_file() else None,
            })
            if len(matches) >= 50:
                break
        return {"ok": True, "base": str(base), "pattern": pattern, "matches": matches}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


TOOLS = [
    {
        "name": "local_list_directory",
        "description": "List files and directories in a local folder on your machine.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Local directory path (defaults to home)."}
            },
        },
        "func": local_list_directory,
    },
    {
        "name": "local_read_file",
        "description": "Read the text contents of a file on your local machine.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Absolute or home-relative path to the file."}
            },
            "required": ["path"],
        },
        "func": local_read_file,
    },
    {
        "name": "local_search_files",
        "description": "Search for files by wildcard pattern in a local directory.",
        "parameters": {
            "type": "object",
            "properties": {
                "folder": {"type": "string", "description": "Local base directory to search in."},
                "pattern": {"type": "string", "description": "Filename pattern e.g. '*.txt'."},
            },
        },
        "func": local_search_files,
    },
]
