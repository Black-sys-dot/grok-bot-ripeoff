"""Local System and Clipboard Plugin for Grok Bot.

Provides local system telemetry, clipboard reading and writing on the user's laptop.
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import time
from typing import Any

PLUGIN_META = {
    "id": "local_system",
    "name": "Local System & Clipboard",
    "description": "Inspect local OS status and interact with the system clipboard.",
    "version": "1.0.0",
}


def local_system_info() -> dict[str, Any]:
    """Get system telemetry and status for your local machine."""
    try:
        uname = platform.uname()
        mem_info: dict[str, Any] = {}
        if os.path.exists("/proc/meminfo"):
            try:
                with open("/proc/meminfo", "r") as f:
                    for line in f:
                        if line.startswith("MemTotal:"):
                            mem_info["total_kb"] = int(line.split()[1])
                        elif line.startswith("MemAvailable:"):
                            mem_info["available_kb"] = int(line.split()[1])
            except Exception:
                pass

        total_disk, used_disk, free_disk = shutil.disk_usage(os.path.expanduser("~"))

        return {
            "ok": True,
            "os": platform.system(),
            "release": platform.release(),
            "arch": uname.machine,
            "node": uname.node,
            "session_type": os.environ.get("XDG_SESSION_TYPE", "unknown"),
            "memory": {
                "total_mb": round(mem_info.get("total_kb", 0) / 1024, 1),
                "available_mb": round(mem_info.get("available_kb", 0) / 1024, 1),
            },
            "disk_home_gb": {
                "total": round(total_disk / (1024**3), 1),
                "free": round(free_disk / (1024**3), 1),
            },
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def local_get_clipboard() -> dict[str, Any]:
    """Read the current text from the user's local system clipboard."""
    is_wayland = os.environ.get("XDG_SESSION_TYPE") == "wayland" or "WAYLAND_DISPLAY" in os.environ

    # Try Wayland wl-paste first
    if is_wayland and shutil.which("wl-paste"):
        try:
            out = subprocess.check_output(["wl-paste", "--no-newline"], text=True, timeout=2)
            return {"ok": True, "text": out, "method": "wl-paste"}
        except Exception:
            pass

    # Try X11 xclip
    if shutil.which("xclip"):
        try:
            out = subprocess.check_output(
                ["xclip", "-selection", "clipboard", "-o"], text=True, timeout=2
            )
            return {"ok": True, "text": out, "method": "xclip"}
        except Exception:
            pass

    # Try xsel
    if shutil.which("xsel"):
        try:
            out = subprocess.check_output(["xsel", "--clipboard", "--output"], text=True, timeout=2)
            return {"ok": True, "text": out, "method": "xsel"}
        except Exception:
            pass

    return {
        "ok": False,
        "error": "No supported clipboard tool found (install wl-clipboard or xclip).",
    }


def local_set_clipboard(text: str) -> dict[str, Any]:
    """Copy text into the user's local system clipboard.

    Args:
        text: Text to copy to clipboard.
    """
    is_wayland = os.environ.get("XDG_SESSION_TYPE") == "wayland" or "WAYLAND_DISPLAY" in os.environ

    if is_wayland and shutil.which("wl-copy"):
        try:
            proc = subprocess.Popen(["wl-copy"], stdin=subprocess.PIPE, text=True)
            proc.communicate(input=text, timeout=2)
            return {"ok": True, "detail": "Copied to clipboard via wl-copy"}
        except Exception as exc:
            return {"ok": False, "error": f"wl-copy failed: {exc}"}

    if shutil.which("xclip"):
        try:
            proc = subprocess.Popen(
                ["xclip", "-selection", "clipboard"], stdin=subprocess.PIPE, text=True
            )
            proc.communicate(input=text, timeout=2)
            return {"ok": True, "detail": "Copied to clipboard via xclip"}
        except Exception as exc:
            return {"ok": False, "error": f"xclip failed: {exc}"}

    return {
        "ok": False,
        "error": "No clipboard utility found to set clipboard (install wl-clipboard or xclip).",
    }


TOOLS = [
    {
        "name": "local_system_info",
        "description": "Get CPU, memory, disk, and operating system info for this laptop.",
        "parameters": {"type": "object", "properties": {}},
        "func": local_system_info,
    },
    {
        "name": "local_get_clipboard",
        "description": "Read text currently stored in the local system clipboard.",
        "parameters": {"type": "object", "properties": {}},
        "func": local_get_clipboard,
    },
    {
        "name": "local_set_clipboard",
        "description": "Copy text into the user's local system clipboard.",
        "parameters": {
            "type": "object",
            "properties": {"text": {"type": "string", "description": "Text to copy to clipboard."}},
            "required": ["text"],
        },
        "func": local_set_clipboard,
    },
]
