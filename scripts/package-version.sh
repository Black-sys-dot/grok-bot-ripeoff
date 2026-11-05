#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VERSION_TAG="${1:-v1}"

# Validate version tag against directory traversal
if [[ ! "$VERSION_TAG" =~ ^[a-zA-Z0-9._-]+$ ]]; then
  echo "Error: Invalid version tag '$VERSION_TAG'. Must match ^[a-zA-Z0-9._-]+$" >&2
  exit 1
fi

BASE_DIR="$HOME/.local/share/grok-ripeoff"
TARGET_DIR="$BASE_DIR/versions/$VERSION_TAG"
CURRENT_LINK="$BASE_DIR/current"
USER_DATA_DIR="$BASE_DIR/user-data"

echo "==> Packaging Grok Ripeoff [$VERSION_TAG]"
echo "    Source: $ROOT"
echo "    Destination: $TARGET_DIR"

mkdir -p "$TARGET_DIR"
mkdir -p "$USER_DATA_DIR/logs"

# 1. Build Frontend
echo "==> Building frontend assets..."
(cd "$ROOT/app" && npm run build)

# 2. Sync Application files into target version directory
echo "==> Syncing files to $TARGET_DIR..."
rsync -a --delete \
  --exclude '.git' \
  --exclude '.commandcode' \
  --exclude '__pycache__' \
  --exclude '*.pyc' \
  --exclude 'dev-data' \
  --exclude 'user-data' \
  --exclude 'output' \
  "$ROOT/" "$TARGET_DIR/"

# 3. Write version info
COMMIT_HASH="$(git -C "$ROOT" rev-parse --short HEAD 2>/dev/null || echo "v1-initial")"
TIMESTAMP="$(date -Iseconds)"
cat > "$TARGET_DIR/version.json" <<EOF
{
  "version": "$VERSION_TAG",
  "commit": "$COMMIT_HASH",
  "packaged_at": "$TIMESTAMP",
  "status": "production"
}
EOF

# 4. If target is v1 or current does not exist, atomically point current symlink to it
if [[ "$VERSION_TAG" == "v1" || ! -e "$CURRENT_LINK" ]]; then
  echo "==> Atomically pointing $CURRENT_LINK -> $TARGET_DIR"
  TMP_LINK="${CURRENT_LINK}.tmp.$$"
  ln -s "$TARGET_DIR" "$TMP_LINK"
  mv -Tf "$TMP_LINK" "$CURRENT_LINK"
fi

echo "==> Packaging complete for $VERSION_TAG!"
echo "    Active app link: $CURRENT_LINK"
echo "    User data is safely preserved at: $USER_DATA_DIR"
