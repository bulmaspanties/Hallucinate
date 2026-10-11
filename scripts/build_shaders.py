"""Compile the visualizer shaders (hallucinate/shaders/*.frag) to Qt's portable .qsb format.

The .qsb files are committed (hallucinate/qml/shaders/), so building and installing Hallucinate needs no shader
tools; run this after editing a shader. `#include "file"` lines are replaced with that file's contents first.

    python scripts/build_shaders.py            # needs pyside6-qsb (ships with PySide6)
"""
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCES = ROOT / "hallucinate" / "shaders"
OUT = ROOT / "hallucinate" / "qml" / "shaders"
# OpenGL (ES 2 / 2.1 / 3.2+), Direct3D 11 and Metal, so every Qt Quick backend can run them
TARGETS = ["--glsl", "100 es,120,150", "--hlsl", "50", "--msl", "12"]


def qsb_tool():
    tool = shutil.which("pyside6-qsb") or shutil.which("qsb")
    if tool is None:
        sys.exit("pyside6-qsb not found (it is installed with PySide6)")
    return tool


def expand(path):
    def include(match):
        return expand(path.parent / match.group(1))

    return re.sub(r'^#include "([^"]+)"$', include, path.read_text(encoding="utf-8"), flags=re.M)


def build(source, out_dir=OUT, tool=None):
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / (source.name + ".qsb")
    with tempfile.TemporaryDirectory() as tmp:
        flat = Path(tmp) / source.name
        flat.write_text(expand(source), encoding="utf-8")
        result = subprocess.run([tool or qsb_tool(), *TARGETS, "-o", str(target), str(flat)],
                                capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"{source.name}: {result.stderr or result.stdout}")
    return target


def main():
    tool = qsb_tool()
    for source in sorted(SOURCES.glob("*.frag")):
        print("built", build(source, tool=tool).relative_to(ROOT))


if __name__ == "__main__":
    main()
