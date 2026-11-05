from __future__ import annotations

import base64
import time
from pathlib import Path
from typing import Any

from patchright.sync_api import Page

OBSERVE_SCRIPT = """
() => {
  const MAX = 100;
  const isVisible = (el) => {
    const style = window.getComputedStyle(el);
    const rect = el.getBoundingClientRect();
    return (
      style.visibility !== 'hidden' &&
      style.display !== 'none' &&
      rect.width > 0 &&
      rect.height > 0
    );
  };

  document.querySelectorAll('[data-agent-ref]').forEach((el) => {
    el.removeAttribute('data-agent-ref');
  });

  const candidates = Array.from(
    document.querySelectorAll(
      'a[href], button, input, textarea, select, [role="button"], [role="link"], [contenteditable="true"]'
    )
  ).filter(isVisible);

  const elements = [];
  for (let i = 0; i < Math.min(candidates.length, MAX); i++) {
    const el = candidates[i];
    const ref = 'e' + (i + 1);
    el.setAttribute('data-agent-ref', ref);
    const tag = el.tagName.toLowerCase();
    const type = el.getAttribute('type') || '';
    const name = el.getAttribute('name') || '';
    const id = el.getAttribute('id') || '';
    const placeholder = el.getAttribute('placeholder') || '';
    const aria = el.getAttribute('aria-label') || '';
    const text = (el.innerText || el.textContent || el.value || '').trim().slice(0, 120);
    elements.push({
      ref,
      tag,
      type,
      name,
      id,
      placeholder,
      aria,
      text,
      href: el.href || '',
    });
  }
  return elements;
}
"""

PAGE_TEXT_SCRIPT = """
() => {
  const body = document.body;
  if (!body) return '';
  return (body.innerText || '').replace(/\\s+/g, ' ').trim().slice(0, 12000);
}
"""


def observe_page(page: Page, screenshots_dir: Path) -> dict[str, Any]:
    elements: list[dict[str, Any]] = page.evaluate(OBSERVE_SCRIPT)
    page_text: str = page.evaluate(PAGE_TEXT_SCRIPT)
    screenshot_path = screenshots_dir / f"observe-{int(time.time())}.png"
    page.screenshot(path=str(screenshot_path), full_page=False)
    screenshot_b64 = base64.b64encode(screenshot_path.read_bytes()).decode("ascii")

    return {
        "url": page.url,
        "title": page.title(),
        "elements": elements,
        "page_text_excerpt": page_text[:4000],
        "screenshot": str(screenshot_path),
        "screenshot_base64": screenshot_b64,
    }
