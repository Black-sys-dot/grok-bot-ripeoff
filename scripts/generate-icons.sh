#!/usr/bin/env bash
set -euo pipefail

SRC="/home/black/.gemini/antigravity-cli/brain/b403e4fd-947b-4a84-8ea6-2aeeedb37db0/.user_uploaded/uploaded_media_1793895748594.jpg"
MASK_SRC="/home/black/.local/share/zani-harness/versions/v1/.zani-icons/icon.png"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

echo "==> Cropping source image and applying squircle mask..."
# 1. Crop to 1200x1200 square and resize to 1024x1024
magick "$SRC" -crop 1200x1200+0+0 +repage -resize 1024x1024 /tmp/grok-logo-square-1024.png

# 2. Apply squircle alpha mask
if [[ -f "$MASK_SRC" ]]; then
  magick /tmp/grok-logo-square-1024.png \
    \( "$MASK_SRC" -alpha extract \) \
    -alpha off -compose CopyOpacity -composite \
    /tmp/grok-logo-masked-1024.png
else
  # Fallback to programmatic squircle if mask source missing
  magick /tmp/grok-logo-square-1024.png \
    \( -size 1024x1024 xc:none -fill white -draw "roundrectangle 0,0,1024,1024,220,220" \) \
    -alpha off -compose CopyOpacity -composite \
    /tmp/grok-logo-masked-1024.png
fi

# 3. Save master 1024x1024 PNG and Electron app icon (512x512)
cp -p /tmp/grok-logo-masked-1024.png "$ROOT/app/icon-1024.png"
magick /tmp/grok-logo-masked-1024.png -resize 512x512 "$ROOT/app/icon.png"
mkdir -p "$ROOT/app/public"
cp -p "$ROOT/app/icon.png" "$ROOT/app/public/icon.png"

# 4. Generate embedded SVG for scalable lookups
B64="$(base64 -w 0 /tmp/grok-logo-masked-1024.png)"
cat > "$ROOT/app/icon.svg" <<SVG
<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" viewBox="0 0 1024 1024" width="1024" height="1024">
  <image width="1024" height="1024" href="data:image/png;base64,${B64}"/>
</svg>
SVG

echo "==> Successfully created app/icon.png and app/icon.svg"
