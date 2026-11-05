#!/usr/bin/env bash
# Installs the Electron binary. npm's postinstall is often blocked, and the
# bundled JS extractor fails silently here, so download + unzip explicitly.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT/app"

[[ -d node_modules/electron ]] || npm install electron --save-dev

VERSION="$(node -p "require('./node_modules/electron/package.json').version")"
echo "==> Fetching Electron v${VERSION}"

ZIP="$(node -e "
const {downloadArtifact} = require('@electron/get');
downloadArtifact({version: '${VERSION}', artifactName: 'electron', platform: 'linux', arch: process.arch})
  .then(p => console.log(p))
  .catch(e => { console.error(e.message); process.exit(1); });
")"

[[ -f "$ZIP" ]] || { echo "!! Download failed"; exit 1; }

echo "==> Extracting"
rm -rf node_modules/electron/dist
mkdir -p node_modules/electron/dist
unzip -q -o "$ZIP" -d node_modules/electron/dist
printf 'electron' > node_modules/electron/path.txt
chmod +x node_modules/electron/dist/electron

node_modules/electron/dist/electron --version
echo "==> Electron ready"
