from __future__ import annotations

from typing import Any, Literal

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from agent.browser_session import get_session
from agent.config import OPENROUTER_API_KEY, OPENROUTER_MODEL, HOST, PORT, TOKEN
from agent.root_gate import decide_root
from agent.runner import run_agent_task

app = FastAPI(title="Grok Agent Browser Worker", version="0.2.0")


class Action(BaseModel):
    type: Literal[
        "goto",
        "click",
        "type",
        "press",
        "select",
        "wait",
        "wait_for_selector",
    ]
    url: str | None = None
    selector: str | None = None
    text: str | None = None
    key: str | None = None
    value: str | None = None
    ms: int | None = None
    timeout: int | None = None
    wait_until: str | None = None
    state: str | None = None


class RunRequest(BaseModel):
    actions: list[Action] = Field(min_length=1)


class RootDecision(BaseModel):
    id: str = Field(pattern=r"^[a-f0-9]{32}$")
    approval_token: str = Field(min_length=10)
    allow: bool


class AgentTaskRequest(BaseModel):
    goal: str = Field(min_length=3)
    max_steps: int | None = Field(default=None, ge=1, le=60)
    use_vision: bool | None = None
    model: str | None = None
    persona: str | None = Field(default=None, max_length=2000)
    bot_id: str | None = Field(default=None, max_length=40)


def verify_token(authorization: str | None = Header(default=None)) -> None:
    if not TOKEN:
        return
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="missing bearer token")
    if authorization.removeprefix("Bearer ").strip() != TOKEN:
        raise HTTPException(status_code=401, detail="invalid token")


@app.get("/health")
def health(_: None = Depends(verify_token)) -> dict[str, str]:
    return {"status": "ok"}


@app.get("/agent/status")
def agent_status(_: None = Depends(verify_token)) -> dict[str, Any]:
    return {
        "openrouter_configured": bool(OPENROUTER_API_KEY),
        "model": OPENROUTER_MODEL,
        "browser_profile": "persistent",
    }


@app.post("/run")
def run_job(body: RunRequest, _: None = Depends(verify_token)) -> dict[str, Any]:
    actions = [a.model_dump(exclude_none=True) for a in body.actions]
    try:
        return get_session().run_actions(actions)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/agent/task")
def agent_task(body: AgentTaskRequest, _: None = Depends(verify_token)) -> dict[str, Any]:
    if not OPENROUTER_API_KEY:
        raise HTTPException(
            status_code=503,
            detail="OPENROUTER_API_KEY not configured on server",
        )
    try:
        return run_agent_task(
            goal=body.goal,
            max_steps=body.max_steps,
            use_vision=body.use_vision,
            model=body.model,
            persona=body.persona,
            bot_id=body.bot_id,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/agent/desktop/show")
def desktop_show(_: None = Depends(verify_token)) -> dict[str, str]:
    # The agent chooses the top window with show_on_screen. This does not rearrange it.
    return {"status": "ok"}


@app.post("/agent/root/decide")
def root_decide(body: RootDecision, _: None = Depends(verify_token)) -> dict[str, Any]:
    try:
        result = decide_root(body.id, body.approval_token, body.allow)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not body.allow:
        return {"status": "denied", "reply": "Denied. That root command did not run.", "output": ""}
    output = result.get("output", "")
    return {
        "status": "completed" if result.get("ok") else "failed",
        "reply": output or "The command finished with no output.",
        "output": output,
    }


@app.on_event("shutdown")
def on_shutdown() -> None:
    get_session().shutdown()


def main() -> None:
    import uvicorn

    uvicorn.run("agent.server:app", host=HOST, port=PORT, log_level="info")


if __name__ == "__main__":
    main()


