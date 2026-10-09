#!/usr/bin/env bash
# Build an AppImage bundling Python, PySide6 (incl. Qt Multimedia FFmpeg backend,
# QML modules), the app, its icon and desktop file.
# Usage: packaging/appimage/build.sh  ->  ./hallucinate-x86_64.AppImage
# Env: PYTHON_VERSION (default 3.12), OUT (default ./hallucinate-x86_64.AppImage)
set -euo pipefail
repo="$(cd "$(dirname "$0")/../.." && pwd)"
out="$(realpath -m "${OUT:-./hallucinate-$(uname -m).AppImage}")"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

cp -r "$repo/packaging/appimage/appdir" "$work/appdir"
cp "$repo/hallucinate/assets/hallucinate.png" "$work/appdir/hallucinate.png"
for s in 16 24 32 48 64 128 256 512; do
  mkdir -p "$work/appdir/usr/share/icons/hicolor/${s}x${s}/apps"
  cp "$repo/packaging/icons/hicolor/${s}x${s}/apps/hallucinate.png" \
    "$work/appdir/usr/share/icons/hicolor/${s}x${s}/apps/hallucinate.png"
done
printf 'PySide6>=6.5\nmutagen>=1.46\nkeyring>=24\nnumpy>=1.24\n%s\n' "$repo" > "$work/appdir/requirements.txt"

python3 -m venv "$work/venv"
"$work/venv/bin/pip" install -q python-appimage
curl -fsSL -o "$work/appimagetool" \
  "https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-$(uname -m).AppImage"
chmod +x "$work/appimagetool"

(cd "$work" && "$work/venv/bin/python-appimage" build app -p "${PYTHON_VERSION:-3.12}" --no-packaging appdir)
# python-appimage names the AppDir after the desktop entry's Name field.
mv "$work"/Hallucinate*-"$(uname -m)" "$work/AppDir"
ARCH="$(uname -m)" "$work/appimagetool" --appimage-extract-and-run --no-appstream "$work/AppDir" "$out"
ls -lh "$out"
