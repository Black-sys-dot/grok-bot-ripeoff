#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VERSION_TAG="${1:-v1}"
TARGET_DIR="$HOME/.local/share/grok-ripeoff/versions/$VERSION_TAG"
CURRENT_LINK="$HOME/.local/share/grok-ripeoff/current"
USER_DATA_DIR="$HOME/.local/share/grok-ripeoff/user-data"

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

# 4. If target is v1 or current does not exist, set current symlink
if [[ "$VERSION_TAG" == "v1" || ! -L "$CURRENT_LINK" ]]; then
  echo "==> Pointing $CURRENT_LINK -> $TARGET_DIR"
  ln -sfn "$TARGET_DIR" "$CURRENT_LINK"
fi

echo "==> Packaging complete for $VERSION_TAG!"
echo "    Active app link: $CURRENT_LINK"
echo "    User data is safely preserved at: $USER_DATA_DIR"
