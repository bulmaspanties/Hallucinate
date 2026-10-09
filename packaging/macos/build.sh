#!/usr/bin/env bash
# Build and zip a self-contained macOS .app for the host architecture.
set -euo pipefail
repo="$(cd "$(dirname "$0")/../.." && pwd)"
version="${1:-$(sed -n 's/^version = "\(.*\)"/\1/p' "$repo/pyproject.toml" | head -n1)}"
cd "$repo"

python3 -m pip install --upgrade pip
python3 -m pip install . pyinstaller
mkdir -p build/macos
sips -s format icns hallucinate/assets/hallucinate.png --out build/macos/hallucinate.icns >/dev/null

python3 -m PyInstaller \
  --noconfirm --clean --windowed --onedir \
  --name Hallucinate \
  --osx-bundle-identifier io.github.bulmaspanties.Hallucinate \
  --icon build/macos/hallucinate.icns \
  --add-data "hallucinate/qml:hallucinate/qml" \
  --add-data "hallucinate/assets:hallucinate/assets" \
  --add-data "hallucinate/themes:hallucinate/themes" \
  --collect-all PySide6.QtQml \
  --collect-all PySide6.QtQuick \
  --collect-all PySide6.QtQuickControls2 \
  --collect-all PySide6.QtMultimedia \
  --collect-submodules keyring.backends \
  --exclude-module PySide6.QtWebEngineCore \
  --exclude-module PySide6.QtWebEngineWidgets \
  --exclude-module PySide6.Qt3DCore \
  --exclude-module PySide6.QtDBus \
  packaging/windows/run_hallucinate.py

arch="$(uname -m)"
archive="$repo/dist/hallucinate-${version}-macos-${arch}.zip"
ditto -c -k --sequesterRsrc --keepParent dist/Hallucinate.app "$archive"
printf 'Created %s\n' "$archive"
