"""The dreamy look: cover palettes for the backdrop, UI preferences, and the bundled display font."""
from pathlib import Path

from PySide6.QtGui import QColor, QFontDatabase, QImage

from hallucinate.themes import art_palette

FONTS = Path(__file__).resolve().parents[1] / "hallucinate" / "assets" / "fonts"


def _cover(path, blocks):
    image = QImage(64, 64, QImage.Format.Format_RGB32)
    for i, color in enumerate(blocks):
        for y in range(64):
            for x in range(i * 64 // len(blocks), (i + 1) * 64 // len(blocks)):
                image.setPixelColor(x, y, QColor(color))
    image.save(str(path))
    return str(path)


def test_art_palette_picks_distinct_dominant_colours(qapp, tmp_path):
    path = _cover(tmp_path / "c.png", ["#d03080", "#d03080", "#2060d0", "#30c060", "#d84090"])
    colors = art_palette(path)
    hues = [round(c.hsvHueF() * 360) for c in colors]
    assert len(colors) == 3
    assert 300 <= hues[0] <= 345  # the dominant magenta first; the similar pink is not picked again
    assert any(200 <= h <= 235 for h in hues[1:]) and any(120 <= h <= 160 for h in hues[1:])


def test_art_palette_ignores_grey_and_missing_images(qapp, tmp_path):
    assert art_palette(_cover(tmp_path / "grey.png", ["#808080", "#202020", "#f0f0f0"])) == []
    assert art_palette(str(tmp_path / "missing.png")) == []


def test_display_font_is_bundled_with_its_licence(qapp):
    for name in ("Unbounded-Bold.ttf", "Unbounded-SemiBold.ttf"):
        font_id = QFontDatabase.addApplicationFont(str(FONTS / name))
        assert font_id >= 0 and "Unbounded" in QFontDatabase.applicationFontFamilies(font_id)
    assert "SIL Open Font License" in (FONTS / "OFL-Unbounded.txt").read_text(encoding="utf-8")
