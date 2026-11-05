#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SSH_HOST="${GROK_SSH_HOST:-webeye-vps}"
MODE="${1:-}"
BRIDGE_PORT=8787
BRIDGE_PID=""
VITE_PID=""
ELECTRON_BIN="$ROOT/app/node_modules/electron/dist/electron"

cleanup() {
  [[ -n "$VITE_PID" ]] && kill "$VITE_PID" 2>/dev/null || true
  [[ -n "$BRIDGE_PID" ]] && kill "$BRIDGE_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

log() { printf '\033[1;36m==>\033[0m %s\n' "$*"; }
die() { printf '\033[1;31m!!\033[0m %s\n' "$*" >&2; exit 1; }

forward_port() {
  local port="$1"
  # nc without a deadline can sit on a half-open port. ssh -f returns only
  # after the remote accepts, so a silent VPS leaves the script stuck here.
  if nc -z -w 1 127.0.0.1 "$port" 2>/dev/null; then
    log "Tunnel already up on :${port}"
    return 0
  fi
  log "Opening SSH tunnel for :${port}"
  if timeout 10 ssh -f -N \
    -o BatchMode=yes \
    -o ConnectTimeout=8 \
    -o ConnectionAttempts=1 \
    -o ExitOnForwardFailure=yes \
    -o ServerAliveInterval=30 \
    -L "${port}:127.0.0.1:${port}" \
    "$SSH_HOST" >/tmp/grok-tunnel-${port}.log 2>&1; then
    log "Tunnel up on :${port}"
  else
    log "Tunnel for :${port} did not connect. Opening the window anyway."
  fi
}

start_tunnel() {
  [[ "$MODE" == "--no-tunnel" ]] && return 0
  forward_port 8765
  forward_port 6080
}

ensure_python_deps() {
  [[ -d "$ROOT/bridge/.venv" ]] || python3 -m venv "$ROOT/bridge/.venv"
  "$ROOT/bridge/.venv/bin/pip" install -q -r "$ROOT/bridge/requirements.txt"
}

ensure_node_deps() {
  [[ -d "$ROOT/app/node_modules" ]] || (cd "$ROOT/app" && npm install)
  [[ -x "$ELECTRON_BIN" ]] || bash "$ROOT/scripts/fix-electron.sh"
  [[ -x "$ELECTRON_BIN" ]] || die "Electron is still missing. See scripts/fix-electron.sh output above."
}

start_bridge() {
  if nc -z 127.0.0.1 "$BRIDGE_PORT" 2>/dev/null; then
    log "Bridge already running on :${BRIDGE_PORT}"
    return 0
  fi
  log "Starting bridge on :${BRIDGE_PORT}"
  (
    cd "$ROOT"
    exec "$ROOT/bridge/.venv/bin/python" -m uvicorn bridge.main:app \
      --host 127.0.0.1 --port "$BRIDGE_PORT" --log-level warning
  ) &
  BRIDGE_PID=$!

  for _ in $(seq 1 40); do
    if curl -sf --max-time 1 "http://127.0.0.1:${BRIDGE_PORT}/api/status" -o /dev/null; then
      log "Bridge is ready"
      return 0
    fi
    kill -0 "$BRIDGE_PID" 2>/dev/null || die "Bridge exited on startup. Run it manually to see the error."
    sleep 0.25
  done
  die "Bridge did not become ready on :${BRIDGE_PORT}"
}

launch_electron() {
  local url="$1"
  local flags=(--no-sandbox)

  # Without an explicit ozone platform, Electron starts but never creates a
  # renderer on this Wayland session.
  if [[ "${XDG_SESSION_TYPE:-}" == "wayland" ]]; then
    flags+=(--ozone-platform=wayland --enable-features=UseOzonePlatform)
  fi

  log "Opening Grok Ripeoff window"
  cd "$ROOT/app"
  env -u ELECTRON_RUN_AS_NODE ELECTRON_START_URL="$url" "$ELECTRON_BIN" . "${flags[@]}"
}

start_tunnel
ensure_python_deps
ensure_node_deps

export GROK_SSH_HOST="$SSH_HOST"
export GROK_AGENT_BASE_URL="${GROK_AGENT_BASE_URL:-http://127.0.0.1:8765}"

if [[ "$MODE" == "--dev" ]]; then
  start_bridge
  log "Starting Vite dev server"
  (cd "$ROOT/app" && npm run dev >/dev/null 2>&1) &
  VITE_PID=$!
  for _ in $(seq 1 40); do
    nc -z 127.0.0.1 5173 2>/dev/null && break
    sleep 0.25
  done
  launch_electron "http://localhost:5173"
  exit 0
fi

log "Building UI"
(cd "$ROOT/app" && npm run build >/dev/null)
start_bridge
launch_electron "http://127.0.0.1:${BRIDGE_PORT}"
