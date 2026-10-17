#!/usr/bin/env bash
# Build and zip a self-contained macOS .app for the host architecture.
set -euo pipefail
repo="$(cd "$(dirname "$0")/../.." && pwd)"
version="${1:-$(sed -n 's/^version = "\(.*\)"/\1/p' "$repo/pyproject.toml" | head -n1)}"
cd "$repo"

python3 -m pip install --require-hashes -r packaging/build-requirements.txt
python3 -m pip install --no-deps --no-build-isolation .
mkdir -p build/macos
sips -s format icns hallucinate/assets/hallucinate.png --out build/macos/hallucinate.icns >/dev/null

python3 -m PyInstaller \
  --noconfirm --clean --windowed --onedir \
  --name Hallucinate \
  --osx-bundle-identifier io.github.phosphene_dev.Hallucinate \
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

# Drop the parts of Qt the app never uses, then sign the bundle again (ad hoc, as PyInstaller did): Apple
# silicon refuses to run a bundle whose signature no longer matches its files.
python3 packaging/qt_prune.py dist/Hallucinate.app
codesign --force --deep --sign - dist/Hallucinate.app

arch="$(uname -m)"
archive="$repo/dist/hallucinate-${version}-macos-${arch}.zip"
ditto -c -k --sequesterRsrc --keepParent dist/Hallucinate.app "$archive"
printf 'Created %s\n' "$archive"
