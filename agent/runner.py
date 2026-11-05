from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any

from agent.browser_session import get_session, show_on_screen
from agent.browser_tools import execute_browser_tool
from agent.computer import execute_computer_tool
from agent.root_gate import request_root
from agent.chat_store import append_turn, begin_bot, end_bot, load_history
from agent.config import AGENT_MAX_STEPS, AGENT_USE_VISION, SCREENSHOTS_DIR
from agent.llm import chat_with_tools, parse_tool_calls
from agent.page_observe import observe_page
from agent.prompts import SYSTEM_PROMPT


def _attach_screenshot(result: dict[str, Any]) -> dict[str, Any]:
    path = result.get("screenshot")
    if not path:
        return result
    file = Path(path)
    if file.is_file():
        result["screenshot_base64"] = base64.b64encode(file.read_bytes()).decode("ascii")
    return result


def _observation_user_content(obs: dict[str, Any], use_vision: bool) -> list[dict[str, Any]]:
    payload = {
        "url": obs["url"],
        "title": obs["title"],
        "elements": obs["elements"],
        "page_text_excerpt": obs["page_text_excerpt"],
    }
    text = "Current browser state:\n" + json.dumps(payload, indent=2)
    if use_vision:
        return [
            {"type": "text", "text": text},
            {
                "type": "image_url",
                "image_url": {
                    "url": f"data:image/png;base64,{obs['screenshot_base64']}",
                },
            },
        ]
    return [{"type": "text", "text": text}]


BROWSER_TOOLS = {
    "browser_goto",
    "browser_click",
    "browser_type",
    "browser_press",
    "browser_select",
    "browser_scroll",
    "browser_wait",
    "browser_back",
    "browser_download",
}

COMPUTER_TOOLS = {
    "download_file",
    "list_files",
    "read_file",
    "run_command",
}


def _log(activity: list[dict[str, Any]], step: int, kind: str, title: str, detail: str = "") -> None:
    activity.append(
        {
            "step": step,
            "kind": kind,
            "title": title,
            "detail": (detail or "")[:500],
        }
    )


def _done(
    *,
    status: str,
    reply: str,
    activity: list[dict[str, Any]],
    goal: str,
    last_obs: dict[str, Any] | None,
    page,
    remember: bool = True,
) -> dict[str, Any]:
    text = (reply or "").strip()
    if not text:
        text = "Done." if status == "completed" else "I couldn't finish that."
    if remember:
        append_turn(goal, text)
    return _attach_screenshot(
        {
            "status": status,
            "reply": text,
            "activity": activity,
            "screenshot": last_obs["screenshot"] if last_obs else None,
            "url": last_obs["url"] if last_obs else (page.url if page else None),
        }
    )


def _wants_computer(text: str) -> bool:
    folded = text.lower()
    cues = (
        "your computer",
        "the computer",
        "take over",
        "take control",
        "give me access",
        "your screen",
        "the screen",
        "remote desktop",
        "let me use",
        "hand me",
        "hand off",
        "handoff",
    )
    return any(cue in folded for cue in cues)


def _task_before_computer(text: str) -> bool:
    """The user asked for work and also for the computer. Do the work first."""
    if not _wants_computer(text):
        return False
    folded = text.lower()
    work = (
        "open",
        "browser",
        "go to",
        "goto",
        "navigate",
        "visit",
        "click",
        "fill",
        "download",
        "search",
        "then",
        "after",
        "first",
        "http",
        "www.",
    )
    return any(part in folded for part in work)


def _command_opens_window(command: str) -> bool:
    folded = command.lower()
    return any(
        name in folded
        for name in ("xterm", "pcmanfm", "nautilus", "thunar", "xdg-open", "gnome-terminal", "firefox")
    )


_SHOW_FIRST = (
    "Call show_on_screen first. target is browser, terminal, or a window title. "
    "That window stays on top when the user takes control."
)


def _handoff(
    goal: str,
    activity: list[dict[str, Any]],
    reason: str,
    last_obs: dict[str, Any] | None = None,
    page=None,
) -> dict[str, Any]:
    _log(activity, len(activity) + 1, "wait", "computer", reason)
    return _done(
        status="needs_user",
        reply="The computer is on the right. Take control and use it. Choose I'm done when you want me to continue.",
        activity=activity,
        goal=goal,
        last_obs=last_obs,
        page=page,
    )


def _system_prompt(persona: str | None) -> str:
    extra = (persona or "").strip()[:2000]
    if not extra:
        return SYSTEM_PROMPT
    return (
        f"{SYSTEM_PROMPT}\n\n"
        "This bot's extra instructions sit on top of the rules above. "
        "Follow them for what this bot focuses on and how it talks. "
        "They do not override the computer, handoff, root, or show_on_screen rules.\n"
        f"{extra}"
    )


def _run_agent_task_unlocked(
    session,
    goal: str,
    steps_limit: int,
    vision: bool,
    model: str | None,
    persona: str | None = None,
) -> dict[str, Any]:
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": _system_prompt(persona)},
        *load_history(),
        {"role": "user", "content": goal},
    ]

    activity: list[dict[str, Any]] = []
    last_obs: dict[str, Any] | None = None
    page = None

    # A bare "give me the computer" hands over now. A task plus a handoff
    # has to finish the task first, or the screen shows up with nothing done.
    work_first = _task_before_computer(goal)
    screen_dirty = False
    if _wants_computer(goal) and not work_first:
        return _handoff(goal, activity, "user asked for the computer")

    for step in range(1, steps_limit + 1):
        response = chat_with_tools(messages, model=model)
        choice = response.choices[0].message
        tool_calls = parse_tool_calls(choice)
        if choice.content and choice.content.strip() and tool_calls:
            _log(activity, step, "thought", "thinking", choice.content.strip())

        if not tool_calls:
            _log(activity, step, "reply", "message", choice.content or "")
            return _done(
                status="completed",
                reply=choice.content or "Done.",
                activity=activity,
                goal=goal,
                last_obs=last_obs,
                page=page,
            )

        messages.append(
            {
                "role": "assistant",
                "content": choice.content,
                "tool_calls": [
                    {
                        "id": tc["id"],
                        "type": "function",
                        "function": {
                            "name": tc["name"],
                            "arguments": json.dumps(tc["arguments"]),
                        },
                    }
                    for tc in tool_calls
                ],
            }
        )

        for tc in tool_calls:
            name = tc["name"]
            args = tc["arguments"]

            if name == "show_on_screen":
                result = show_on_screen(str(args.get("target", "")))
                if result.get("ok"):
                    screen_dirty = False
                _log(
                    activity,
                    step,
                    "tool" if result.get("ok") else "error",
                    "show",
                    result.get("detail", ""),
                )
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc["id"],
                        "content": json.dumps(result),
                    }
                )
                continue

            if name == "handoff_computer":
                if screen_dirty:
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tc["id"],
                            "content": json.dumps({"ok": False, "detail": _SHOW_FIRST}),
                        }
                    )
                    continue
                if work_first and page is None:
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tc["id"],
                            "content": json.dumps(
                                {
                                    "ok": False,
                                    "detail": (
                                        "Do the requested work first and leave it on screen. "
                                        "Then call handoff_computer."
                                    ),
                                }
                            ),
                        }
                    )
                    continue
                return _handoff(
                    goal,
                    activity,
                    args.get("reason", "needs the user"),
                    last_obs=last_obs,
                    page=page,
                )

            if name == "ask_user":
                if screen_dirty:
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tc["id"],
                            "content": json.dumps({"ok": False, "detail": _SHOW_FIRST}),
                        }
                    )
                    continue
                question = args.get("question", "")
                _log(activity, step, "wait", "needs you", args.get("reason", ""))
                result = _done(
                    status="needs_user",
                    reply=question or "I need your help to continue.",
                    activity=activity,
                    goal=goal,
                    last_obs=last_obs,
                    page=page,
                )
                result["question"] = question
                result["reason"] = args.get("reason", "")
                return result

            if name == "run_root":
                result = request_root(args.get("command", ""), args.get("reason", ""))
                approval = result.get("root_approval")
                _log(activity, step, "wait", "root", args.get("command", ""))
                if not approval:
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tc["id"],
                            "content": json.dumps({"ok": False, "detail": result.get("detail", "")}),
                        }
                    )
                    continue
                done = _done(
                    status="needs_root",
                    reply="I need root for one command. Approve it below if you want it to run.",
                    activity=activity,
                    goal=goal,
                    last_obs=last_obs,
                    page=page,
                )
                done["root_approval"] = approval
                return done

            if name == "finish_task":
                if screen_dirty:
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tc["id"],
                            "content": json.dumps({"ok": False, "detail": _SHOW_FIRST}),
                        }
                    )
                    continue
                success = bool(args.get("success", True))
                _log(activity, step, "note", "done" if success else "stopped", args.get("summary", ""))
                return _done(
                    status="completed" if success else "failed",
                    reply=args.get("reply", ""),
                    activity=activity,
                    goal=goal,
                    last_obs=last_obs,
                    page=page,
                )

            if name in COMPUTER_TOOLS:
                result = execute_computer_tool(name, args)
                if (
                    name == "run_command"
                    and result.get("ok")
                    and _command_opens_window(str(args.get("command", "")))
                ):
                    screen_dirty = True
            else:
                if name in BROWSER_TOOLS and page is None:
                    page = session.get_page()
                result = execute_browser_tool(page, name, args)
                if name in BROWSER_TOOLS and result.get("ok"):
                    screen_dirty = True
            detail = result.get("detail", "")
            if name == "browser_goto":
                detail = args.get("url", detail)
            elif name in ("browser_click", "browser_type", "browser_select"):
                detail = f"{args.get('ref', '')} {detail}".strip()
            _log(
                activity,
                step,
                "tool" if result.get("ok") else "error",
                name.removeprefix("browser_"),
                detail,
            )
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": json.dumps(result),
                }
            )

        if page is not None and any(tc["name"] in BROWSER_TOOLS for tc in tool_calls):
            last_obs = observe_page(page, SCREENSHOTS_DIR)
            messages.append(
                {
                    "role": "user",
                    "content": _observation_user_content(last_obs, vision),
                }
            )

    return _done(
        status="max_steps",
        reply="I stopped before this was finished. The activity log has what I got through.",
        activity=activity,
        goal=goal,
        last_obs=last_obs,
        page=page,
    )


def run_agent_task(
    goal: str,
    max_steps: int | None = None,
    use_vision: bool | None = None,
    model: str | None = None,
    persona: str | None = None,
    bot_id: str | None = None,
) -> dict[str, Any]:
    steps_limit = max_steps or AGENT_MAX_STEPS
    vision = use_vision if use_vision is not None else AGENT_USE_VISION
    session = get_session()
    token = begin_bot(bot_id)

    def _inner(_page):
        return _run_agent_task_unlocked(session, goal, steps_limit, vision, model, persona)

    try:
        return session.run_agent(_inner)
    finally:
        end_bot(token)
