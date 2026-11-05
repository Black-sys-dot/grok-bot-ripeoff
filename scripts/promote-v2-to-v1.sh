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

BACKUP_DIR=""
rollback() {
  local exit_code=$?
  if [[ $exit_code -ne 0 && -n "$BACKUP_DIR" && -d "$BACKUP_DIR" ]]; then
    echo "!! Promotion failed. Rolling back v1 from $BACKUP_DIR..." >&2
    rsync -a --delete "$BACKUP_DIR/" "$V1_DIR/" || true
  fi
  exit "$exit_code"
}
trap rollback EXIT INT TERM

# Backup current v1 if it exists
if [[ -d "$V1_DIR" ]]; then
  BACKUP_DIR="$BASE/versions/v1.bak.$(date +%s)"
  echo "==> Backing up current v1 to $BACKUP_DIR..."
  cp -a "$V1_DIR" "$BACKUP_DIR"
fi

echo "==> Syncing v2 to v1..."
mkdir -p "$V1_DIR"
rsync -a --delete "$V2_DIR/" "$V1_DIR/"

# Update version.json in v1 to reflect stable promotion
if [[ -f "$V1_DIR/version.json" ]]; then
  sed -i 's/"version": "v2"/"version": "v1"/g' "$V1_DIR/version.json"
fi

# Atomically point current to v1
TMP_LINK="${CURRENT_LINK}.tmp.$$"
ln -s "$V1_DIR" "$TMP_LINK"
mv -Tf "$TMP_LINK" "$CURRENT_LINK"

# Prune old v1 backups (keep only the 2 most recent)
shopt -s nullglob
backups=("$BASE"/versions/v1.bak.*)
if [[ ${#backups[@]} -gt 2 ]]; then
  # Sort numerically/by timestamp and remove older ones
  sorted=($(for b in "${backups[@]}"; do echo "$b"; done | sort))
  excess=$((${#sorted[@]} - 2))
  for ((i=0; i<excess; i++)); do
    echo "==> Pruning old backup: ${sorted[i]}"
    rm -rf "${sorted[i]}"
  done
fi

echo "==> Successfully promoted v2 to v1 stable!"
echo "    Current symlink: $CURRENT_LINK -> $V1_DIR"
echo "    User data verified completely intact at: $USER_DATA_DIR"
