#!/usr/bin/env bash
# Dedicated unprivileged account for the agent. No sudo. Its home is its computer.
set -euo pipefail

if ! id grok >/dev/null 2>&1; then
  useradd --create-home --shell /bin/bash --comment "Grok agent" grok
fi

chmod 750 /home/grok
mkdir -p /home/grok/{Desktop,Documents,Downloads,Pictures,.config,.cache,.grok-agent}

if [[ -d /var/lib/grok-agent ]] && [[ -z "$(ls -A /home/grok/.grok-agent 2>/dev/null || true)" ]]; then
  cp -a /var/lib/grok-agent/. /home/grok/.grok-agent/
fi

if [[ -d /root/.cache/ms-playwright && ! -d /home/grok/.cache/ms-playwright ]]; then
  cp -a /root/.cache/ms-playwright /home/grok/.cache/ms-playwright
fi

chown -R grok:grok /home/grok /opt/grok-agent

# Other projects on this box run as root. Lock their homes so grok cannot read them.
for dir in /home/discord-bot /home/food_delivery; do
  if [[ -d "$dir" ]]; then
    chmod 700 "$dir"
  fi
done

python3 - <<'PY'
from pathlib import Path
env_path = Path("/etc/grok-agent/env")
token = Path("/etc/grok-agent/token").read_text().strip()
text = env_path.read_text() if env_path.exists() else ""
lines = [ln for ln in text.splitlines() if ln and not ln.startswith("GROK_AGENT_TOKEN=")]
lines.append(f"GROK_AGENT_TOKEN={token}")
env_path.write_text("\n".join(lines) + "\n")
env_path.chmod(0o600)
PY

echo "user grok ready"
