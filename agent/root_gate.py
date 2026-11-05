"""Root commands wait for an approval token that the model never receives."""

from __future__ import annotations

import hashlib
import json
import secrets
import subprocess
import uuid
from typing import Any

PROPOSE = "/usr/local/sbin/grok-root-propose"
RUN = "/usr/local/sbin/grok-root-run"


def _sudo(script: str, approval_id: str, payload: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["sudo", "-n", script, approval_id],
        input=payload,
        text=True,
        capture_output=True,
        timeout=200,
    )


def request_root(command: str, reason: str) -> dict[str, Any]:
    command = command.strip()
    if not command:
        return {"ok": False, "detail": "empty command"}
    approval_id = uuid.uuid4().hex
    token = secrets.token_urlsafe(32)
    body = json.dumps(
        {
            "command": command,
            "reason": reason[:500],
            "token_hash": hashlib.sha256(token.encode()).hexdigest(),
        }
    )
    proc = _sudo(PROPOSE, approval_id, body)
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "could not store root request").strip()
        return {"ok": False, "detail": detail}
    return {
        "ok": True,
        "pending": True,
        "detail": "Waiting for approval. This command has not run.",
        "root_approval": {
            "id": approval_id,
            "command": command,
            "reason": reason[:500],
            "approval_token": token,
        },
    }


def decide_root(approval_id: str, token: str, allow: bool) -> dict[str, Any]:
    action = "run" if allow else "deny"
    proc = subprocess.run(
        ["sudo", "-n", RUN, action, approval_id],
        input=token,
        text=True,
        capture_output=True,
        timeout=200,
    )
    output = (proc.stdout or "").strip()
    if not allow:
        return {"ok": proc.returncode == 0, "output": "Denied. The command did not run."}
    if proc.returncode != 0 and not output:
        output = (proc.stderr or "root command failed").strip()
    return {"ok": proc.returncode == 0, "output": output or "(no output)"}
