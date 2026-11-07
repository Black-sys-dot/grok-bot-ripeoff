from __future__ import annotations

import hmac
from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator, Literal

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from agent.browser_session import get_session
from agent.config import OPENROUTER_API_KEY, OPENROUTER_MODEL, HOST, PORT, TOKEN
from agent.root_gate import decide_root
from agent.runner import run_agent_task


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    yield
    get_session().shutdown()


app = FastAPI(title="Grok Agent Browser Worker", version="0.2.0", lifespan=lifespan)


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
    approval_token: str = Field(min_length=10, max_length=128)
    allow: bool


class AgentTaskRequest(BaseModel):
    goal: str = Field(min_length=1)
    max_steps: int | None = Field(default=None, ge=1, le=60)
    use_vision: bool | None = None
    model: str | None = None
    persona: str | None = Field(default=None, max_length=2000)
    bot_id: str | None = Field(default=None, max_length=40)


def verify_token(authorization: str | None = Header(default=None)) -> None:
    if not TOKEN:
        raise HTTPException(
            status_code=500,
            detail="Authentication token is misconfigured on the agent server.",
        )
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="missing bearer token")
    provided = authorization.removeprefix("Bearer ").strip()
    if not hmac.compare_digest(provided.encode("utf-8"), TOKEN.encode("utf-8")):
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
            persona=body.persona or "",
            bot_id=body.bot_id or "default",
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


class ToolExecutionRequest(BaseModel):
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


@app.post("/agent/tool")
def agent_tool(body: ToolExecutionRequest, _: None = Depends(verify_token)) -> dict[str, Any]:
    session = get_session()
    name = body.name
    args = body.arguments

    if name == "show_on_screen":
        from agent.runner import show_on_screen
        return show_on_screen(str(args.get("target", "")))

    if name == "run_root":
        from agent.root_gate import request_root
        return request_root(args.get("command", ""), args.get("reason", ""))

    from agent.computer import execute_computer_tool
    comp_res = execute_computer_tool(name, args)
    if not (comp_res.get("detail", "").startswith("unknown computer tool")):
        return comp_res

    from agent.browser_tools import execute_browser_tool
    from agent.page_observe import observe_page
    from agent.config import SCREENSHOTS_DIR

    page = session.get_page()
    result = execute_browser_tool(page, name, args)
    if result.get("ok"):
        try:
            obs = observe_page(page, SCREENSHOTS_DIR)
            result["observation"] = obs.get("text_summary", "")
            result["url"] = page.url
            result["screenshot_base64"] = obs.get("screenshot_base64")
        except Exception:
            pass
    return result


@app.post("/agent/desktop/show")
def desktop_show(_: None = Depends(verify_token)) -> dict[str, Any]:
    try:
        from agent.computer import desktop_show as show_impl

        return show_impl()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


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


def main() -> None:
    import uvicorn

    uvicorn.run("agent.server:app", host=HOST, port=PORT, log_level="info")


if __name__ == "__main__":
    main()
