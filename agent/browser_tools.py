from __future__ import annotations

import time
from typing import Any

from patchright.sync_api import Page


def ref_selector(ref: str) -> str:
    return f'[data-agent-ref="{ref}"]'


def execute_browser_tool(page: Page, name: str, args: dict[str, Any]) -> dict[str, Any]:
    try:
        if name == "browser_goto":
            url = args["url"]
            wait_until = args.get("wait_until", "domcontentloaded")
            page.goto(url, wait_until=wait_until, timeout=60000)
            return {"ok": True, "detail": f"navigated to {page.url}"}

        if name == "browser_back":
            page.go_back(wait_until="domcontentloaded", timeout=30000)
            return {"ok": True, "detail": f"back to {page.url}"}

        if name == "browser_click":
            ref = args["ref"]
            page.click(ref_selector(ref), timeout=args.get("timeout", 30000))
            page.wait_for_load_state("domcontentloaded", timeout=15000)
            return {"ok": True, "detail": f"clicked {ref}"}

        if name == "browser_download":
            ref = args["ref"]
            with page.expect_download(timeout=args.get("timeout", 60000)) as download_info:
                page.click(ref_selector(ref), timeout=15000)
            download = download_info.value
            suggested = download.suggested_filename or "download"
            from agent.config import DOWNLOADS_DIR

            dest = DOWNLOADS_DIR / suggested
            download.save_as(str(dest))
            return {"ok": True, "detail": f"saved {dest}"}

        if name == "browser_type":
            ref = args["ref"]
            text = args["text"]
            sel = ref_selector(ref)
            if args.get("clear", True):
                page.fill(sel, "", timeout=15000)
            page.fill(sel, text, timeout=15000)
            return {"ok": True, "detail": f"typed into {ref}"}

        if name == "browser_press":
            key = args["key"]
            ref = args.get("ref")
            if ref:
                page.press(ref_selector(ref), key, timeout=15000)
            else:
                page.keyboard.press(key)
            return {"ok": True, "detail": f"pressed {key}"}

        if name == "browser_select":
            ref = args["ref"]
            value = args["value"]
            page.select_option(ref_selector(ref), value, timeout=15000)
            return {"ok": True, "detail": f"selected {value} on {ref}"}

        if name == "browser_scroll":
            direction = args.get("direction", "down")
            amount = int(args.get("amount", 600))
            delta = amount if direction == "down" else -amount
            page.mouse.wheel(0, delta)
            time.sleep(0.3)
            return {"ok": True, "detail": f"scrolled {direction} {amount}px"}

        if name == "browser_wait":
            seconds = float(args.get("seconds", 2))
            time.sleep(seconds)
            return {"ok": True, "detail": f"waited {seconds}s"}

        return {"ok": False, "detail": f"unknown browser tool: {name}"}
    except Exception as exc:
        return {"ok": False, "detail": str(exc)}
