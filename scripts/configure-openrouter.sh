#!/usr/bin/env bash
set -euo pipefail

ENV_FILE="${1:-/etc/grok-agent/env}"

if [[ ! -f "$ENV_FILE" ]]; then
  install -d -m 700 "$(dirname "$ENV_FILE")"
  cp "$(dirname "$0")/../deploy/env.example" "$ENV_FILE"
  chmod 600 "$ENV_FILE"
fi

echo "Edit $ENV_FILE and set OPENROUTER_API_KEY, then:"
echo "  systemctl restart grok-agent"
