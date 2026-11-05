from __future__ import annotations

import os
import subprocess
import threading
import time
from typing import Any

from patchright.sync_api import BrowserContext, Page, sync_playwright

from agent.config import BROWSER_ARGS, DISPLAY, DOWNLOADS_DIR, HOME, PROFILE_DIR, SCREENSHOTS_DIR


def _xdo(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["xdotool", *args],
        env={**os.environ, "DISPLAY": DISPLAY},
        timeout=5,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )


def show_on_screen(what: str) -> dict[str, Any]:
    """Map one window and put it above the others. Take control does not change this."""
    label = (what or "").strip()
    kind = label.lower()
    if kind in {"browser", "chrome", "chromium"}:
        found = _xdo(["search", "--class", "Chromium-browser"])
    elif kind in {"terminal", "xterm", "shell"}:
        found = _xdo(["search", "--class", "XTerm"])
    elif label:
        found = _xdo(["search", "--name", label])
    else:
        return {"ok": False, "detail": "Say browser, terminal, or a window title."}

    best = ""
    best_area = -1
    for wid in found.stdout.split():
        geo = _xdo(["getwindowgeometry", "--shell", wid])
        width = height = 0
        for line in geo.stdout.splitlines():
            if line.startswith("WIDTH="):
                width = int(line.split("=", 1)[1] or 0)
            elif line.startswith("HEIGHT="):
                height = int(line.split("=", 1)[1] or 0)
        if width * height >= best_area:
            best_area = width * height
            best = wid
    if not best:
        return {"ok": False, "detail": f"No window on screen matched {label!r}."}

    _xdo(["windowmap", best])
    _xdo(["windowmove", best, "0", "0"])
    _xdo(["windowsize", best, "1280", "720"])
    _xdo(["windowraise", best])
    _xdo(["windowactivate", best])
    name = _xdo(["getwindowname", best]).stdout.strip()
    return {"ok": True, "detail": name or label}


class BrowserSession:
    def __init__(self) -> None:
        # RLock: run_actions/run_agent already hold the lock, then call _ensure.
        self._lock = threading.RLock()
        self._playwright = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None

    def _reset(self) -> None:
        self._page = None
        if self._context:
            try:
                self._context.close()
            except Exception:
                pass
            self._context = None
        if self._playwright:
            try:
                self._playwright.stop()
            except Exception:
                pass
            self._playwright = None

    def _page_alive(self) -> bool:
        if not self._page:
            return False
        try:
            return not self._page.is_closed()
        except Exception:
            return False

    def _ensure(self) -> Page:
        with self._lock:
            if self._page_alive():
                return self._page

            PROFILE_DIR.mkdir(parents=True, exist_ok=True)
            SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)
            DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)
            self._reset()
            self._playwright = sync_playwright().start()

            try:
                self._context = self._playwright.chromium.launch_persistent_context(
                    user_data_dir=str(PROFILE_DIR),
                    headless=False,
                    accept_downloads=True,
                    downloads_path=str(DOWNLOADS_DIR),
                    args=BROWSER_ARGS,
                    viewport={"width": 1280, "height": 720},
                    env={"DISPLAY": DISPLAY, "HOME": str(HOME)},
                )
                if self._context.pages:
                    self._page = self._context.pages[0]
                else:
                    self._page = self._context.new_page()
            except Exception:
                self._reset()
                raise
            show_on_screen("browser")
            return self._page

    def get_page(self) -> Page:
        return self._ensure()

    def run_actions(self, actions: list[dict[str, Any]]) -> dict[str, Any]:
        with self._lock:
            return self._run_actions_unlocked(actions)

    def _run_actions_unlocked(self, actions: list[dict[str, Any]]) -> dict[str, Any]:
        page = self._ensure()
        results: list[dict[str, Any]] = []

        for i, action in enumerate(actions):
            kind = action.get("type")
            if not kind:
                raise ValueError(f"action[{i}] missing type")

            if kind == "goto":
                url = action["url"]
                page.goto(url, wait_until=action.get("wait_until", "domcontentloaded"))
                results.append({"type": kind, "url": url, "title": page.title()})

            elif kind == "click":
                selector = action["selector"]
                page.click(selector, timeout=action.get("timeout", 30000))
                results.append({"type": kind, "selector": selector})

            elif kind == "type":
                selector = action["selector"]
                text = action["text"]
                page.fill(selector, text, timeout=action.get("timeout", 30000))
                results.append({"type": kind, "selector": selector})

            elif kind == "press":
                selector = action.get("selector")
                key = action["key"]
                if selector:
                    page.press(selector, key, timeout=action.get("timeout", 30000))
                else:
                    page.keyboard.press(key)
                results.append({"type": kind, "key": key, "selector": selector})

            elif kind == "select":
                selector = action["selector"]
                value = action["value"]
                page.select_option(selector, value, timeout=action.get("timeout", 30000))
                results.append({"type": kind, "selector": selector, "value": value})

            elif kind == "wait":
                ms = int(action.get("ms", 1000))
                time.sleep(ms / 1000.0)
                results.append({"type": kind, "ms": ms})

            elif kind == "wait_for_selector":
                selector = action["selector"]
                state = action.get("state", "visible")
                page.wait_for_selector(selector, state=state, timeout=action.get("timeout", 30000))
                results.append({"type": kind, "selector": selector, "state": state})

            else:
                raise ValueError(f"unknown action type: {kind}")

        screenshot_path = SCREENSHOTS_DIR / f"last-{int(time.time())}.png"
        page.screenshot(path=str(screenshot_path), full_page=False)

        return {
            "ok": True,
            "results": results,
            "url": page.url,
            "title": page.title(),
            "screenshot": str(screenshot_path),
        }

    def run_agent(self, fn):
        with self._lock:
            return fn(None)

    def shutdown(self) -> None:
        with self._lock:
            if self._context:
                try:
                    self._context.close()
                except Exception:
                    pass
                self._context = None
            if self._playwright:
                try:
                    self._playwright.stop()
                except Exception:
                    pass
                self._playwright = None
            self._page = None


_SESSION = BrowserSession()


def get_session() -> BrowserSession:
    return _SESSION
