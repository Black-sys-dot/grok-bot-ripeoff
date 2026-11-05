"""Local bridge: chat UI on your machine → agent API on the VPS (via SSH tunnel)."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from starlette.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from bridge.bots import load_bots, save_bots
from bridge.tunnel import Tunnel, port_open

ROOT = Path(__file__).resolve().parents[1]
APP_DIST = ROOT / "app" / "dist"

AGENT_BASE = os.environ.get("GROK_AGENT_BASE_URL", "http://127.0.0.1:8765").rstrip("/")
AGENT_TOKEN = os.environ.get("GROK_AGENT_TOKEN", "")
SSH_HOST = os.environ.get("GROK_SSH_HOST", "webeye-vps")


_TOKEN_CACHE = AGENT_TOKEN


def _load_token() -> str:
    global _TOKEN_CACHE
    if _TOKEN_CACHE:
        return _TOKEN_CACHE
    if not port_open(8765):
        return ""
    try:
        out = subprocess.check_output(
            ["ssh", "-o", "ConnectTimeout=8", SSH_HOST, "cat /etc/grok-agent/token"],
            text=True,
            timeout=15,
        )
        _TOKEN_CACHE = out.strip()
        return _TOKEN_CACHE
    except Exception:
        return ""


TUNNEL = Tunnel(SSH_HOST)

app = FastAPI(title="Grok Ripeoff Bridge", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1)
    context: str | None = None
    persona: str | None = Field(default=None, max_length=8000)
    bot_id: str | None = Field(default=None, max_length=40)


class BotsPayload(BaseModel):
    bots: list[dict[str, Any]] = Field(min_length=1)
    activeId: str = ""


def _agent_headers() -> dict[str, str]:
    token = _load_token()
    if not token:
        raise HTTPException(
            status_code=503,
            detail="The cloud computer is unreachable.",
        )
    return {"Authorization": f"Bearer {token}"}


@app.get("/api/status")
def status() -> dict[str, Any]:
    tunnel = TUNNEL.snapshot()
    token = _load_token() if tunnel["agent"] else ""
    remote: dict[str, Any] = {"reachable": False}
    if token:
        try:
            r = httpx.get(
                f"{AGENT_BASE}/agent/status",
                headers={"Authorization": f"Bearer {token}"},
                timeout=10.0,
            )
            remote = {"reachable": r.is_success, "body": r.json() if r.is_success else r.text}
        except Exception as exc:
            remote = {"reachable": False, "error": str(exc)}
    return {
        "bridge": "ok",
        "agent_base": AGENT_BASE,
        "ssh_host": SSH_HOST,
        "token_configured": bool(token),
        "tunnel": TUNNEL.snapshot(),
        "remote": remote,
    }


@app.on_event("startup")
def start_tunnel() -> None:
    TUNNEL.start()


@app.on_event("shutdown")
def stop_tunnel() -> None:
    TUNNEL.stop()


@app.get("/api/bots")
def get_bots() -> dict[str, Any]:
    return load_bots()


@app.put("/api/bots")
def put_bots(body: BotsPayload) -> dict[str, Any]:
    try:
        return save_bots(body.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/chat")
def chat(body: ChatRequest) -> dict[str, Any]:
    try:
        r = httpx.post(
            f"{AGENT_BASE}/agent/task",
            headers=_agent_headers(),
            json={
                "goal": body.message,
                "persona": body.persona or "",
                "bot_id": body.bot_id or "default",
            },
            timeout=600.0,
        )
    except httpx.ConnectError:
        raise HTTPException(
            status_code=503,
            detail="The cloud computer is unreachable.",
        ) from None
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    if not r.is_success:
        raise HTTPException(status_code=r.status_code, detail=r.text)

    data = r.json()
    # Chat gets reply only. Activity is the private log. Drop the model transcript.
    return {
        "status": data.get("status"),
        "reply": data.get("reply") or data.get("question") or "",
        "activity": data.get("activity") or [],
        "url": data.get("url"),
        "screenshot_base64": data.get("screenshot_base64"),
        "question": data.get("question"),
        "root_approval": data.get("root_approval"),
    }


class RootDecision(BaseModel):
    id: str
    approval_token: str
    allow: bool


@app.post("/api/desktop/show")
def desktop_show() -> dict[str, Any]:
    try:
        r = httpx.post(
            f"{AGENT_BASE}/agent/desktop/show",
            headers=_agent_headers(),
            timeout=15.0,
        )
    except httpx.ConnectError:
        raise HTTPException(status_code=503, detail="The cloud computer is unreachable.") from None
    if not r.is_success:
        raise HTTPException(status_code=r.status_code, detail=r.text)
    return r.json()


@app.post("/api/root/decide")
def root_decide(body: RootDecision) -> dict[str, Any]:
    try:
        r = httpx.post(
            f"{AGENT_BASE}/agent/root/decide",
            headers=_agent_headers(),
            json=body.model_dump(),
            timeout=200.0,
        )
    except httpx.ConnectError:
        raise HTTPException(status_code=503, detail="Cannot reach agent API") from None
    if not r.is_success:
        raise HTTPException(status_code=r.status_code, detail=r.text)
    return r.json()

if APP_DIST.is_dir():
    app.mount("/", StaticFiles(directory=str(APP_DIST), html=True), name="static")
