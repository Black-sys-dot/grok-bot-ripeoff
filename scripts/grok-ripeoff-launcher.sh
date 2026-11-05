#!/usr/bin/env bash
set -euo pipefail

# Find App Root (defaults to current symlink, then fallback to repo root)
if [[ -d "$HOME/.local/share/grok-ripeoff/current" ]]; then
  APP_ROOT="$HOME/.local/share/grok-ripeoff/current"
else
  APP_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
fi

USER_DATA="${GROK_USER_DATA:-$HOME/.local/share/grok-ripeoff/user-data}"
LOG_DIR="$USER_DATA/logs"
mkdir -p "$LOG_DIR"

LOG_FILE="$LOG_DIR/app.log"
exec >> "$LOG_FILE" 2>&1

echo "========================================="
echo "[$(date -Iseconds)] Launching Grok Ripeoff"
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
    echo "Failed to install electron binary"
    exit 1
  }
fi

cleanup() {
  echo "[$(date -Iseconds)] Cleaning up launcher processes"
  [[ -n "$BRIDGE_PID" ]] && kill "$BRIDGE_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

# 1. Forward SSH ports if not open
forward_port() {
  local port="$1"
  if nc -z -w 1 127.0.0.1 "$port" 2>/dev/null; then
    echo "Port $port already reachable"
    return 0
  fi
  echo "Opening SSH tunnel for :${port} to $SSH_HOST"
  timeout 8 ssh -f -N \
    -o BatchMode=yes \
    -o ConnectTimeout=5 \
    -o ConnectionAttempts=1 \
    -o ExitOnForwardFailure=yes \
    -o ServerAliveInterval=30 \
    -L "${port}:127.0.0.1:${port}" \
    "$SSH_HOST" >"$LOG_DIR/tunnel-${port}.log" 2>&1 || {
      echo "Notice: SSH tunnel for :$port not established. Continuing."
    }
}

forward_port 8765
forward_port 6080

# 2. Check & start bridge
if nc -z 127.0.0.1 "$BRIDGE_PORT" 2>/dev/null; then
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

  # Wait for bridge
  for _ in $(seq 1 40); do
    if curl -sf --max-time 1 "http://127.0.0.1:${BRIDGE_PORT}/api/status" -o /dev/null 2>/dev/null; then
      echo "Bridge is ready"
      break
    fi
    kill -0 "$BRIDGE_PID" 2>/dev/null || {
      echo "Bridge process exited unexpectedly"
      exit 1
    }
    sleep 0.2
  done
fi

# 3. Build UI if dist is missing
if [[ ! -f "$APP_ROOT/app/dist/index.html" ]]; then
  echo "Building app dist..."
  (cd "$APP_ROOT/app" && npm run build) >> "$LOG_FILE" 2>&1
fi

# 4. Launch Electron
flags=(--no-sandbox)
if [[ "${XDG_SESSION_TYPE:-}" == "wayland" || -n "${WAYLAND_DISPLAY:-}" ]]; then
  flags+=(--ozone-platform=wayland --enable-features=UseOzonePlatform)
fi

echo "[$(date -Iseconds)] Opening Electron window"
cd "$APP_ROOT/app"
export GROK_USER_DATA="$USER_DATA"
export ELECTRON_START_URL="http://127.0.0.1:${BRIDGE_PORT}"
exec env -u ELECTRON_RUN_AS_NODE "$ELECTRON_BIN" . "${flags[@]}" --class="grok-ripeoff-app" "$@"
