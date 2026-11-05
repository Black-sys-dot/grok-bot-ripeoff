#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export GROK_USER_DATA="${GROK_USER_DATA:-$HOME/.local/share/grok-ripeoff/dev-data}"
export GROK_APP_CHANNEL="v2-dev"

echo "==> Starting Grok Ripeoff in v2 development mode"
echo "    Isolated dev user data: $GROK_USER_DATA"

bash "$ROOT/scripts/grok-ripeoff-launcher.sh" "$@"
