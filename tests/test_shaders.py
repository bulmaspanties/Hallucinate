"""The visualizer shaders: every source has a compiled .qsb next to the QML, and the sources still compile."""
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SOURCES = sorted((ROOT / "hallucinate" / "shaders").glob("*.frag"))
sys.path.insert(0, str(ROOT / "scripts"))
import build_shaders  # noqa: E402


def test_every_shader_is_compiled_and_packaged():
    from hallucinate.shell import VISUALIZER_STYLES

    names = {p.stem for p in SOURCES}
    assert names == set(VISUALIZER_STYLES) - {"bars"}
    for source in SOURCES:
        assert (ROOT / "hallucinate" / "qml" / "shaders" / (source.name + ".qsb")).stat().st_size > 1000
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert '"qml/shaders/*"' in pyproject


@pytest.mark.skipif(not (shutil.which("pyside6-qsb") or shutil.which("qsb")), reason="needs pyside6-qsb")
@pytest.mark.parametrize("source", SOURCES, ids=lambda p: p.stem)
def test_shader_sources_compile(source, tmp_path):
    out = build_shaders.build(source, out_dir=tmp_path)
    assert out.stat().st_size > 1000


def test_includes_are_expanded():
    text = build_shaders.expand(ROOT / "hallucinate" / "shaders" / "liquid.frag")
    assert "#include" not in text and "float fbm(" in text and text.startswith("#version 440")
