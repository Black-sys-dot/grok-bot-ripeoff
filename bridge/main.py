"""Local bridge: chat UI on your machine → agent API on the VPS (via SSH tunnel),
with local plugins and local MCP server support.
"""

from __future__ import annotations

import logging
import os
import re
import subprocess
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncGenerator

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from starlette.staticfiles import StaticFiles

from bridge.agent import run_orchestrated_task
from bridge.bots import load_bots, save_bots
from bridge.mcp import REGISTRY as mcp_registry
from bridge.plugins import REGISTRY as plugin_registry
from bridge.tunnel import Tunnel, port_open

logger = logging.getLogger("grok.bridge")

ROOT = Path(__file__).resolve().parents[1]
APP_DIST = ROOT / "app" / "dist"

AGENT_BASE = os.environ.get("GROK_AGENT_BASE_URL", "http://127.0.0.1:8765").rstrip("/")
AGENT_TOKEN = os.environ.get("GROK_AGENT_TOKEN", "")
SSH_HOST = os.environ.get("GROK_SSH_HOST", "webeye-vps")

# Sanitize SSH_HOST to prevent option injection
if not re.match(r"^[a-zA-Z0-9_.-]+$", SSH_HOST):
    raise ValueError(f"Invalid GROK_SSH_HOST value: {SSH_HOST}")

_TOKEN_CACHE = AGENT_TOKEN
_TOKEN_LOCK = threading.Lock()


def _load_token() -> str:
    global _TOKEN_CACHE
    with _TOKEN_LOCK:
        if _TOKEN_CACHE:
            return _TOKEN_CACHE
        if not port_open(8765):
            return ""
        try:
            out = subprocess.check_output(
                [
                    "ssh",
                    "-o", "BatchMode=yes",
                    "-o", "ConnectTimeout=8",
                    "--",
                    SSH_HOST,
                    "cat /etc/grok-agent/token",
                ],
                text=True,
                timeout=12,
            )
            _TOKEN_CACHE = out.strip()
            return _TOKEN_CACHE
        except Exception:
            return ""


TUNNEL = Tunnel(SSH_HOST)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    TUNNEL.start()
    yield
    TUNNEL.stop()
    mcp_registry.stop_all()


app = FastAPI(title="Grok Ripeoff Bridge", version="0.2.0", lifespan=lifespan)

# Restrict CORS to local application origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:8787",
        "http://localhost:8787",
        "http://127.0.0.1:5173",
        "http://localhost:5173",
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["*"],
)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=10000)
    context: str | None = Field(default=None, max_length=10000)
    persona: str | None = Field(default=None, max_length=2000)
    bot_id: str | None = Field(default=None, max_length=40, pattern=r"^[a-zA-Z0-9_-]+$")


class BotsPayload(BaseModel):
    bots: list[dict[str, Any]] = Field(min_length=1)
    activeId: str = ""


class RootDecision(BaseModel):
    id: str = Field(pattern=r"^[a-f0-9]{32}$")
    approval_token: str = Field(min_length=10, max_length=128)
    allow: bool


class MCPServerAdd(BaseModel):
    name: str = Field(min_length=1, max_length=50, pattern=r"^[a-zA-Z0-9_-]+$")
    config: dict[str, Any]


def _agent_headers() -> dict[str, str]:
    token = _load_token()
    if not token:
        raise HTTPException(
            status_code=503,
            detail="The cloud computer is unreachable or unauthenticated.",
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
                timeout=4.0,
            )
            remote = {"reachable": r.is_success, "body": r.json() if r.is_success else r.text}
        except Exception as exc:
            remote = {"reachable": False, "error": str(exc)}

    return {
        "bridge": "ok",
        "agent_base": AGENT_BASE,
        "ssh_host": SSH_HOST,
        "token_configured": bool(token),
        "tunnel": tunnel,
        "remote": remote,
        "plugins": {
            "total": len(plugin_registry.plugins),
            "items": plugin_registry.get_status(),
        },
        "mcp": {
            "total": len(mcp_registry.sessions),
            "items": mcp_registry.get_status(),
        },
    }


@app.get("/api/bots")
def get_bots() -> dict[str, Any]:
    return load_bots()


@app.put("/api/bots")
def put_bots(body: BotsPayload) -> dict[str, Any]:
    try:
        return save_bots(body.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


# --- Plugins API ---
@app.get("/api/plugins")
def list_plugins() -> list[dict[str, Any]]:
    return plugin_registry.get_status()


@app.post("/api/plugins/reload")
def reload_plugins() -> list[dict[str, Any]]:
    plugin_registry.reload()
    return plugin_registry.get_status()


# --- MCP API ---
@app.get("/api/mcp")
def list_mcp_servers() -> list[dict[str, Any]]:
    return mcp_registry.get_status()


@app.post("/api/mcp/refresh")
def refresh_mcp() -> list[dict[str, Any]]:
    mcp_registry.refresh()
    return mcp_registry.get_status()


@app.post("/api/mcp/server")
def add_mcp_server(body: MCPServerAdd) -> list[dict[str, Any]]:
    mcp_registry.add_server(body.name, body.config)
    return mcp_registry.get_status()


@app.delete("/api/mcp/server/{name}")
def delete_mcp_server(name: str) -> list[dict[str, Any]]:
    mcp_registry.remove_server(name)
    return mcp_registry.get_status()


# --- Chat & Task Orchestration ---
@app.post("/api/chat")
def chat(body: ChatRequest) -> dict[str, Any]:
    headers = {}
    try:
        headers = _agent_headers()
    except Exception:
        pass

    # 1. Run via local orchestrator (executes local plugins, local MCP, and remote cloud tools)
    try:
        return run_orchestrated_task(
            goal=body.message,
            persona=body.persona or "",
            bot_id=body.bot_id or "default",
            agent_base=AGENT_BASE,
            ssh_host=SSH_HOST,
            agent_headers=headers,
        )
    except Exception as exc:
        logger.warning("Local orchestration encountered error: %s. Attempting remote fallback.", exc)
        if not headers:
            raise HTTPException(
                status_code=503,
                detail=f"Agent error: {exc}",
            ) from exc

        # 2. Fallback to VPS agent /agent/task if local LLM call fails
        try:
            r = httpx.post(
                f"{AGENT_BASE}/agent/task",
                headers=headers,
                json={
                    "goal": body.message,
                    "persona": body.persona or "",
                    "bot_id": body.bot_id or "default",
                },
                timeout=600.0,
            )
            if not r.is_success:
                raise HTTPException(status_code=r.status_code, detail=r.text)
            data = r.json()
            return {
                "status": data.get("status"),
                "reply": data.get("reply") or data.get("question") or "",
                "activity": data.get("activity") or [],
                "url": data.get("url"),
                "screenshot_base64": data.get("screenshot_base64"),
                "question": data.get("question"),
                "root_approval": data.get("root_approval"),
            }
        except httpx.ConnectError:
            raise HTTPException(status_code=503, detail="The cloud computer is unreachable.") from None
        except Exception as fallback_exc:
            raise HTTPException(status_code=502, detail=str(fallback_exc)) from fallback_exc


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
