#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BIN_DIR="$HOME/.local/bin"
DESKTOP_DIR="$HOME/.local/share/applications"
ICONS_BASE="$HOME/.local/share/icons/hicolor"

mkdir -p "$BIN_DIR" "$DESKTOP_DIR"

# 1. Install launcher script to ~/.local/bin/grok-ripeoff
echo "==> Installing launcher to $BIN_DIR/grok-ripeoff"
cp -p "$ROOT/scripts/grok-ripeoff-launcher.sh" "$BIN_DIR/grok-ripeoff"
chmod +x "$BIN_DIR/grok-ripeoff"

# 2. Install icons
echo "==> Generating and installing icons..."
SIZES=(16 32 64 128 256 512)
for size in "${SIZES[@]}"; do
  dir="$ICONS_BASE/${size}x${size}/apps"
  mkdir -p "$dir"
  if command -v rsvg-convert >/dev/null 2>&1; then
    rsvg-convert -w "$size" -h "$size" "$ROOT/app/icon.svg" -o "$dir/grok-ripeoff.png"
  elif command -v convert >/dev/null 2>&1; then
    convert -background none -resize "${size}x${size}" "$ROOT/app/icon.svg" "$dir/grok-ripeoff.png"
  fi
done

# Scalable SVG icon
mkdir -p "$ICONS_BASE/scalable/apps"
cp -p "$ROOT/app/icon.svg" "$ICONS_BASE/scalable/apps/grok-ripeoff.svg"

# 3. Install desktop entry
echo "==> Installing desktop entry to $DESKTOP_DIR/grok-ripeoff.desktop"
cp -p "$ROOT/scripts/grok-ripeoff.desktop" "$DESKTOP_DIR/grok-ripeoff.desktop"
chmod +x "$DESKTOP_DIR/grok-ripeoff.desktop"

# 4. Refresh icon and desktop databases
gtk-update-icon-cache -f -t "$ICONS_BASE" 2>/dev/null || true
update-desktop-database "$DESKTOP_DIR" 2>/dev/null || true

echo "==> Grok Ripeoff desktop application installed successfully!"
echo "    Launcher: $BIN_DIR/grok-ripeoff"
echo "    Desktop Entry: $DESKTOP_DIR/grok-ripeoff.desktop"
