import os
from pathlib import Path

DISPLAY = os.environ.get("DISPLAY", ":99")
HOST = os.environ.get("GROK_AGENT_HOST", "127.0.0.1")
PORT = int(os.environ.get("GROK_AGENT_PORT", "8765"))
TOKEN = os.environ.get("GROK_AGENT_TOKEN", "")

HOME = Path(os.environ.get("HOME", "/home/grok")).resolve()
DOWNLOADS_DIR = HOME / "Downloads"
DATA_DIR = Path(os.environ.get("GROK_AGENT_DATA", str(HOME / ".grok-agent")))
PROFILE_DIR = DATA_DIR / "browser-profile"
SCREENSHOTS_DIR = DATA_DIR / "screenshots"
MEMORY_DIR = DATA_DIR / "memory"

OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
OPENROUTER_BASE_URL = os.environ.get(
    "OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"
)
OPENROUTER_MODEL = os.environ.get(
    "OPENROUTER_MODEL", "google/gemini-2.5-flash"
)
OPENROUTER_APP_NAME = os.environ.get("OPENROUTER_APP_NAME", "grok-bot-ripeoff")
OPENROUTER_APP_URL = os.environ.get("OPENROUTER_APP_URL", "https://github.com/local/grok-bot-ripeoff")

AGENT_MAX_STEPS = int(os.environ.get("GROK_AGENT_MAX_STEPS", "30"))
AGENT_USE_VISION = os.environ.get("GROK_AGENT_USE_VISION", "true").lower() in (
    "1",
    "true",
    "yes",
)

BROWSER_ARGS = [
    "--disable-dev-shm-usage",
    "--disable-gpu",
    "--no-sandbox",
    "--window-size=1280,720",
]
