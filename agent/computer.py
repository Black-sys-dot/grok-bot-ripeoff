"""Files and downloads inside the agent's own home. Nothing outside it."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

from agent.config import DOWNLOADS_DIR, HOME

MAX_DOWNLOAD_BYTES = 200 * 1024 * 1024
MAX_READ_BYTES = 100_000
SECRET_ENV = {"OPENROUTER_API_KEY", "GROK_AGENT_TOKEN"}


def inside_home(raw: str | None, default: Path | None = None) -> Path:
    root = HOME.resolve()
    if not raw:
        if default is None:
            raise ValueError("path is required")
        path = default.resolve()
    else:
        candidate = Path(raw)
        path = candidate.resolve() if candidate.is_absolute() else (root / candidate).resolve()
    if path != root and root not in path.parents:
        raise ValueError("that path is outside this computer")
    return path


def download_file(url: str, filename: str | None = None) -> dict[str, Any]:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("only http and https downloads are allowed")
    DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)
    name = filename or Path(parsed.path).name or "download"
    name = Path(name).name
    if not name or name in {".", ".."}:
        name = "download"
    dest = inside_home(str(DOWNLOADS_DIR / name))

    written = 0
    with httpx.stream("GET", url, follow_redirects=True, timeout=120.0) as response:
        response.raise_for_status()
        with dest.open("wb") as handle:
            for chunk in response.iter_bytes():
                written += len(chunk)
                if written > MAX_DOWNLOAD_BYTES:
                    dest.unlink(missing_ok=True)
                    raise ValueError("download is larger than 200 MB")
                handle.write(chunk)
    return {"ok": True, "detail": f"saved {dest} ({written} bytes)"}


def list_files(path: str | None = None) -> dict[str, Any]:
    folder = inside_home(path, HOME)
    if not folder.is_dir():
        raise ValueError("not a directory")
    rows = []
    for entry in sorted(folder.iterdir(), key=lambda p: p.name.lower()):
        kind = "dir" if entry.is_dir() else "file"
        size = entry.stat().st_size if entry.is_file() else 0
        rows.append(f"{kind}\t{size}\t{entry.name}")
    body = "\n".join(rows) if rows else "(empty)"
    return {"ok": True, "detail": f"{folder}\n{body}"}


def read_file(path: str) -> dict[str, Any]:
    file = inside_home(path)
    if not file.is_file():
        raise ValueError("not a file")
    data = file.read_bytes()[:MAX_READ_BYTES]
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return {"ok": True, "detail": f"{file} is binary ({file.stat().st_size} bytes)"}
    return {"ok": True, "detail": text}


def run_command(command: str, cwd: str | None = None) -> dict[str, Any]:
    lowered = command.lower()
    if any(word in lowered for word in ("sudo", "pkexec", "grok-root-")):
        return {
            "ok": False,
            "detail": "That needs root. Call run_root so the user can approve the exact command.",
        }
    folder = inside_home(cwd, HOME)
    if not folder.is_dir():
        raise ValueError("cwd is not a directory")
    env = {k: v for k, v in os.environ.items() if k not in SECRET_ENV}
    env["HOME"] = str(HOME)
    completed = subprocess.run(
        command,
        shell=True,
        cwd=folder,
        env=env,
        text=True,
        capture_output=True,
        timeout=60,
    )
    output = (completed.stdout + completed.stderr).strip()
    if len(output) > 8000:
        output = output[:8000] + "\n…(truncated)"
    status = "ok" if completed.returncode == 0 else f"exit {completed.returncode}"
    return {"ok": completed.returncode == 0, "detail": f"{status}\n{output}".strip()}


def execute_computer_tool(name: str, args: dict[str, Any]) -> dict[str, Any]:
    try:
        if name == "download_file":
            return download_file(args["url"], args.get("filename"))
        if name == "list_files":
            return list_files(args.get("path"))
        if name == "read_file":
            return read_file(args["path"])
        if name == "run_command":
            return run_command(args["command"], args.get("cwd"))
        return {"ok": False, "detail": f"unknown computer tool: {name}"}
    except Exception as exc:
        return {"ok": False, "detail": str(exc)}
