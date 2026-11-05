"""Native desktop window — pywebview (GTK) when available."""

from __future__ import annotations

import os
import sys

import webview


def main() -> None:
    url = os.environ.get("GROK_APP_URL", "http://127.0.0.1:8787")
    title = os.environ.get("GROK_APP_TITLE", "Grok Ripeoff")
    width = int(os.environ.get("GROK_APP_WIDTH", "1440"))
    height = int(os.environ.get("GROK_APP_HEIGHT", "920"))

    window = webview.create_window(title, url, width=width, height=height, min_size=(960, 640))
    webview.start(debug=False)


if __name__ == "__main__":
    main()
