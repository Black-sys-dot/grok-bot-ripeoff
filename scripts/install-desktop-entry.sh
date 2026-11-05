#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BIN_DIR="$HOME/.local/bin"
DESKTOP_DIR="$HOME/.local/share/applications"
ICONS_BASE="$HOME/.local/share/icons/hicolor"

mkdir -p "$BIN_DIR" "$DESKTOP_DIR"

# 1. Ensure v1 is packaged so ~/.local/share/grok-ripeoff/current is live
if [[ ! -d "$HOME/.local/share/grok-ripeoff/current" ]]; then
  echo "==> Packaging v1 to initialize current release..."
  bash "$ROOT/scripts/package-version.sh" v1
fi

# 2. Install launcher script to ~/.local/bin/grok-ripeoff
echo "==> Installing launcher to $BIN_DIR/grok-ripeoff"
cp -p "$ROOT/scripts/grok-ripeoff-launcher.sh" "$BIN_DIR/grok-ripeoff"
chmod +x "$BIN_DIR/grok-ripeoff"

# 3. Install icons across all standard resolutions (including 48x48)
echo "==> Generating and installing icons..."
SIZES=(16 32 48 64 128 256 512)
has_converter=false

for size in "${SIZES[@]}"; do
  dir="$ICONS_BASE/${size}x${size}/apps"
  mkdir -p "$dir"
  if command -v rsvg-convert >/dev/null 2>&1; then
    rsvg-convert -w "$size" -h "$size" "$ROOT/app/icon.svg" -o "$dir/grok-ripeoff.png"
    has_converter=true
  elif command -v convert >/dev/null 2>&1; then
    convert -background none -resize "${size}x${size}" "$ROOT/app/icon.svg" "$dir/grok-ripeoff.png"
    has_converter=true
  fi
done

# Fallback raster copy if conversion tools were missing
if [[ "$has_converter" != "true" && -f "$ROOT/app/icon.png" ]]; then
  mkdir -p "$ICONS_BASE/256x256/apps"
  cp -p "$ROOT/app/icon.png" "$ICONS_BASE/256x256/apps/grok-ripeoff.png"
fi

# Scalable SVG icon
mkdir -p "$ICONS_BASE/scalable/apps"
cp -p "$ROOT/app/icon.svg" "$ICONS_BASE/scalable/apps/grok-ripeoff.svg"

# 4. Generate and install desktop entry with dynamic paths
echo "==> Installing desktop entry to $DESKTOP_DIR/grok-ripeoff.desktop"
cat > "$DESKTOP_DIR/grok-ripeoff.desktop" <<EOF
[Desktop Entry]
Type=Application
Version=1.0
Name=Grok Ripeoff
GenericName=Autonomous Cloud Assistant
Comment=Chat with your autonomous cloud browser and desktop agent
Exec=$BIN_DIR/grok-ripeoff %U
Icon=grok-ripeoff
Terminal=false
Categories=Network;Chat;
Keywords=grok;agent;browser;ai;cloud;
StartupNotify=true
StartupWMClass=grok-ripeoff-app
EOF
chmod +x "$DESKTOP_DIR/grok-ripeoff.desktop"

# 5. Refresh FreeDesktop icon and desktop databases
gtk-update-icon-cache -f -t "$ICONS_BASE" 2>/dev/null || true
update-desktop-database "$DESKTOP_DIR" 2>/dev/null || true

echo "==> Grok Ripeoff desktop application installed successfully!"
echo "    Launcher: $BIN_DIR/grok-ripeoff"
echo "    Desktop Entry: $DESKTOP_DIR/grok-ripeoff.desktop"
echo "    App is now ready in your application menu."
