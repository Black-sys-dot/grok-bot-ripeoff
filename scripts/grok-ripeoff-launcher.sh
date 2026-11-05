#!/usr/bin/env bash
set -euo pipefail

# Fallback repo root is baked in so launching from ~/.local/bin never falls back to ~/.local
BAKED_REPO="/home/black/Projects/grok-bot-ripeoff"
if [[ -d "$HOME/.local/share/grok-ripeoff/current" ]]; then
  APP_ROOT="$HOME/.local/share/grok-ripeoff/current"
elif [[ -d "$BAKED_REPO" ]]; then
  APP_ROOT="$BAKED_REPO"
else
  APP_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
fi

USER_DATA="${GROK_USER_DATA:-$HOME/.local/share/grok-ripeoff/user-data}"
LOG_DIR="$USER_DATA/logs"
mkdir -p "$LOG_DIR"

LOG_FILE="$LOG_DIR/app.log"
exec >> "$LOG_FILE" 2>&1

notify_fail() {
  local msg="$1"
  echo "[$(date -Iseconds)] ERROR: $msg" >&2
  if command -v notify-send >/dev/null 2>&1; then
    notify-send -u critical "Grok Ripeoff" "$msg (see $LOG_FILE)" 2>/dev/null || true
  fi
}

echo "========================================="
echo "[$(date -Iseconds)] Starting Grok Ripeoff"
echo "APP_ROOT=$APP_ROOT"
echo "USER_DATA=$USER_DATA"

SSH_HOST="${GROK_SSH_HOST:-webeye-vps}"
BRIDGE_PORT=8787
BRIDGE_PID=""
ELECTRON_BIN="$APP_ROOT/app/node_modules/electron/dist/electron"

# Verify Electron binary exists
if [[ ! -x "$ELECTRON_BIN" ]]; then
  echo "[$(date -Iseconds)] Electron binary missing at $ELECTRON_BIN, fixing..."
  bash "$APP_ROOT/scripts/fix-electron.sh" || {
    notify_fail "Failed to prepare Electron runtime"
    exit 1
  }
fi

# Ensure Python virtual environment exists
if [[ ! -x "$APP_ROOT/bridge/.venv/bin/python" ]]; then
  echo "[$(date -Iseconds)] Bridge venv missing, creating..."
  python3 -m venv "$APP_ROOT/bridge/.venv"
  "$APP_ROOT/bridge/.venv/bin/pip" install -q -r "$APP_ROOT/bridge/requirements.txt" || {
    notify_fail "Failed to install Python dependencies"
    exit 1
  }
fi

cleanup() {
  local exit_code=$?
  echo "[$(date -Iseconds)] Cleaning up launcher processes (exit $exit_code)..."
  if [[ -n "${BRIDGE_PID:-}" ]] && kill -0 "$BRIDGE_PID" 2>/dev/null; then
    echo "[$(date -Iseconds)] Stopping bridge process (PID $BRIDGE_PID)..."
    kill "$BRIDGE_PID" 2>/dev/null || true
    wait "$BRIDGE_PID" 2>/dev/null || true
  fi
  exit "$exit_code"
}
trap cleanup EXIT INT TERM

# 1. Forward SSH ports if not open (runs non-blocking check)
forward_port() {
  local port="$1"
  if nc -z -w 1 127.0.0.1 "$port" 2>/dev/null; then
    echo "Port $port already reachable"
    return 0
  fi
  echo "Opening SSH tunnel for :${port} to $SSH_HOST"
  timeout 4 ssh -f -N \
    -o BatchMode=yes \
    -o ConnectTimeout=3 \
    -o ConnectionAttempts=1 \
    -o ExitOnForwardFailure=yes \
    -o ServerAliveInterval=20 \
    -L "${port}:127.0.0.1:${port}" \
    -- "$SSH_HOST" >"$LOG_DIR/tunnel-${port}.log" 2>&1 || {
      echo "Notice: Initial tunnel for :$port did not connect immediately. Background monitor will retry."
    }
}

forward_port 8765
forward_port 6080

# 2. Start bridge server if not already running
if curl -sf --max-time 1 "http://127.0.0.1:${BRIDGE_PORT}/api/status" >/dev/null 2>&1; then
  echo "Bridge already running on :$BRIDGE_PORT"
else
  echo "Starting bridge on :$BRIDGE_PORT"
  (
    cd "$APP_ROOT"
    export GROK_USER_DATA="$USER_DATA"
    export GROK_SSH_HOST="$SSH_HOST"
    export GROK_AGENT_BASE_URL="${GROK_AGENT_BASE_URL:-http://127.0.0.1:8765}"
    exec "$APP_ROOT/bridge/.venv/bin/python" -m uvicorn bridge.main:app \
      --host 127.0.0.1 --port "$BRIDGE_PORT" --log-level warning
  ) >> "$LOG_DIR/bridge.log" 2>&1 &
  BRIDGE_PID=$!

  # Wait for bridge with active health verification
  bridge_ready=false
  for _ in $(seq 1 40); do
    if curl -sf --max-time 1 "http://127.0.0.1:${BRIDGE_PORT}/api/status" >/dev/null 2>&1; then
      bridge_ready=true
      echo "Bridge is ready"
      break
    fi
    kill -0 "$BRIDGE_PID" 2>/dev/null || {
      notify_fail "Bridge server terminated unexpectedly"
      exit 1
    }
    sleep 0.2
  done

  if [[ "$bridge_ready" != "true" ]]; then
    notify_fail "Bridge server did not become ready on port $BRIDGE_PORT"
    exit 1
  fi
fi

# 3. Build UI if dist is missing
if [[ ! -f "$APP_ROOT/app/dist/index.html" ]]; then
  echo "Building app dist..."
  (cd "$APP_ROOT/app" && npm run build) >> "$LOG_FILE" 2>&1
fi

# 4. Launch Electron with proper Wayland window decorations and app IDs
flags=(--no-sandbox)
if [[ "${XDG_SESSION_TYPE:-}" == "wayland" || -n "${WAYLAND_DISPLAY:-}" ]]; then
  flags+=(--ozone-platform=wayland --enable-features=WaylandWindowDecorations)
fi

export CHROME_DESKTOP="grok-ripeoff.desktop"
export GROK_USER_DATA="$USER_DATA"
export ELECTRON_START_URL="http://127.0.0.1:${BRIDGE_PORT}"

echo "[$(date -Iseconds)] Opening Electron window"
cd "$APP_ROOT/app"

# DO NOT use 'exec': running as a child allows 'trap cleanup' to terminate the bridge on window close!
env -u ELECTRON_RUN_AS_NODE "$ELECTRON_BIN" . "${flags[@]}" --class="grok-ripeoff-app" "$@"
