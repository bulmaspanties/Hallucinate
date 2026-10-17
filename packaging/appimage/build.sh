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
# The same versions as the Windows and macOS builds (python-appimage's own pip can't check hashes here)
pin() { grep -io "^$1==[^ ;]*" "$repo/packaging/build-requirements.txt"; }
printf '%s\n' "$(pin pyside6)" "$(pin mutagen)" "$(pin keyring)" "$(pin numpy)" "$repo" > "$work/appdir/requirements.txt"

python3 -m venv "$work/venv"
"$work/venv/bin/pip" install -q python-appimage
# A fixed release of appimagetool, checked against its checksum: the "continuous" build changes under us.
tool_version=1.9.0
case "$(uname -m)" in
  x86_64) tool_sha=46fdd785094c7f6e545b61afcfb0f3d98d8eab243f644b4b17698c01d06083d1 ;;
  aarch64) tool_sha=04f45ea45b5aa07bb2b071aed9dbf7a5185d3953b11b47358c1311f11ea94a96 ;;
  *) echo "No pinned appimagetool for $(uname -m)" >&2; exit 1 ;;
esac
curl -fsSL -o "$work/appimagetool" \
  "https://github.com/AppImage/appimagetool/releases/download/$tool_version/appimagetool-$(uname -m).AppImage"
echo "$tool_sha  $work/appimagetool" | sha256sum -c --quiet -
chmod +x "$work/appimagetool"

(cd "$work" && "$work/venv/bin/python-appimage" build app -p "${PYTHON_VERSION:-3.12}" --no-packaging appdir)
# python-appimage names the AppDir after the desktop entry's Name field.
mv "$work"/Hallucinate*-"$(uname -m)" "$work/AppDir"
python3 "$repo/packaging/qt_prune.py" "$work/AppDir"  # drop the parts of Qt the app never uses
ARCH="$(uname -m)" "$work/appimagetool" --appimage-extract-and-run --no-appstream "$work/AppDir" "$out"
ls -lh "$out"
