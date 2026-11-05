#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

INSTALL_ROOT="${INSTALL_ROOT:-/opt/grok-agent}"
DATA_DIR="${DATA_DIR:-/var/lib/grok-agent}"
SWAP_SIZE_GB="${SWAP_SIZE_GB:-3}"

echo "[1/8] apt packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq \
  python3 python3-venv python3-pip \
  xvfb openbox \
  fonts-liberation fonts-noto-color-emoji \
  libnss3 libatk-bridge2.0-0 libdrm2 libxkbcommon0 libgbm1 libasound2t64 \
  curl ca-certificates rsync openssl

echo "[2/8] swap (${SWAP_SIZE_GB}G)"
if ! swapon --show | grep -q '/swapfile'; then
  fallocate -l "${SWAP_SIZE_GB}G" /swapfile || dd if=/dev/zero of=/swapfile bs=1M count=$((SWAP_SIZE_GB * 1024))
  chmod 600 /swapfile
  mkswap /swapfile
  swapon /swapfile
  grep -q '/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

echo "[3/8] zram"
apt-get install -y -qq systemd-zram-generator 2>/dev/null || true
mkdir -p /etc/systemd/zram-generator.conf.d
cat > /etc/systemd/zram-generator.conf.d/grok-agent.conf <<'EOF'
[zram0]
zram-size = ram / 2
compression-algorithm = zstd
EOF
systemctl daemon-reload
timeout 15 systemctl restart systemd-zram-setup@zram0.service 2>/dev/null \
  || timeout 15 systemctl start systemd-zram-setup@zram0.service 2>/dev/null \
  || true

echo "[4/8] install app to ${INSTALL_ROOT}"
mkdir -p "${INSTALL_ROOT}"
rsync -a --delete \
  --exclude '.venv' \
  --exclude '__pycache__' \
  --exclude '.git' \
  "${ROOT_DIR}/" "${INSTALL_ROOT}/"

python3 -m venv "${INSTALL_ROOT}/.venv"
"${INSTALL_ROOT}/.venv/bin/pip" install -U pip wheel
"${INSTALL_ROOT}/.venv/bin/pip" install -r "${INSTALL_ROOT}/requirements.txt"
"${INSTALL_ROOT}/.venv/bin/patchright" install chromium

echo "[5/8] data dir + token"
mkdir -p "${DATA_DIR}/browser-profile" "${DATA_DIR}/screenshots" "${DATA_DIR}/memory"
chmod 700 "${DATA_DIR}"
mkdir -p /etc/grok-agent
if [[ ! -f /etc/grok-agent/token ]]; then
  openssl rand -hex 32 > /etc/grok-agent/token
  chmod 600 /etc/grok-agent/token
fi
if [[ ! -f /etc/grok-agent/env ]]; then
  cp "${INSTALL_ROOT}/deploy/env.example" /etc/grok-agent/env
  chmod 600 /etc/grok-agent/env
fi

echo "[6/8] agent user + systemd units"
bash "${INSTALL_ROOT}/deploy/setup-user.sh"
cp "${INSTALL_ROOT}/deploy/grok-xvfb.service" /etc/systemd/system/
cp "${INSTALL_ROOT}/deploy/grok-openbox.service" /etc/systemd/system/
cp "${INSTALL_ROOT}/deploy/grok-agent.service" /etc/systemd/system/
systemctl daemon-reload
systemctl enable grok-xvfb.service grok-openbox.service grok-agent.service
systemctl restart grok-xvfb.service grok-openbox.service
sleep 2
systemctl restart grok-agent.service

echo "[7/8] status"
systemctl --no-pager --full status grok-xvfb.service grok-openbox.service grok-agent.service || true
free -h
swapon --show || true

echo "[8/8] done"
echo "Token: $(cat /etc/grok-agent/token)"
echo "Worker: http://127.0.0.1:8765 (localhost only)"
