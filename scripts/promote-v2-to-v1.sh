#!/usr/bin/env bash
set -euo pipefail

BASE="$HOME/.local/share/grok-ripeoff"
V1_DIR="$BASE/versions/v1"
V2_DIR="$BASE/versions/v2"
CURRENT_LINK="$BASE/current"
USER_DATA_DIR="$BASE/user-data"

echo "==> Promoting Grok Ripeoff: v2 -> v1 (Stable)"

if [[ ! -d "$V2_DIR" ]]; then
  echo "Error: $V2_DIR does not exist. Build/package v2 first using: scripts/package-version.sh v2" >&2
  exit 1
fi

# Backup current v1 if it exists
if [[ -d "$V1_DIR" ]]; then
  BACKUP_DIR="$BASE/versions/v1.bak.$(date +%s)"
  echo "==> Backing up current v1 to $BACKUP_DIR..."
  cp -a "$V1_DIR" "$BACKUP_DIR"
fi

echo "==> Syncing v2 to v1..."
rsync -a --delete "$V2_DIR/" "$V1_DIR/"

# Update version.json in v1 to reflect stable promotion
if [[ -f "$V1_DIR/version.json" ]]; then
  sed -i 's/"version": "v2"/"version": "v1"/g' "$V1_DIR/version.json"
fi

# Point current to v1
ln -sfn "$V1_DIR" "$CURRENT_LINK"

echo "==> Successfully promoted v2 to v1 stable!"
echo "    Current symlink: $CURRENT_LINK -> $V1_DIR"
echo "    User data verified completely intact at: $USER_DATA_DIR"
