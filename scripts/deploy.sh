#!/usr/bin/env bash
set -euo pipefail

HOST_ALIAS="${1:-webeye-vps}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TARBALL="/tmp/grok-agent-src.tgz"

tar -czf "$TARBALL" -C "$ROOT" .
echo "Uploading to ${HOST_ALIAS}..."
scp "$TARBALL" "${HOST_ALIAS}:/tmp/grok-agent-src.tgz"
ssh "$HOST_ALIAS" 'rm -rf /tmp/grok-agent-src && mkdir -p /tmp/grok-agent-src && tar -xzf /tmp/grok-agent-src.tgz -C /tmp/grok-agent-src && bash /tmp/grok-agent-src/deploy/install.sh'
