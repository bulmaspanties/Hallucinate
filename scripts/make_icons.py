"""Generate every icon asset from the single source logo (assets/logo/hallucinate-logo.png).

Usage: python scripts/make_icons.py        (needs Pillow)

To rebrand, replace assets/logo/hallucinate-logo.png (square, mark centred) and adjust MARK_BOX if the
mark moves, then re-run and commit the generated files.
"""
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "assets" / "logo" / "hallucinate-logo.png"
ASSETS = ROOT / "hallucinate" / "assets"
HICOLOR = ROOT / "packaging" / "icons" / "hicolor"
# Square crop around the arched vinyl mark (no wordmark), in source pixels.
MARK_BOX = (235, 130, 1005, 900)
SIZES = (16, 24, 32, 48, 64, 128, 256, 512)
def main():
    src = Image.open(SOURCE).convert("RGB")
    mark = src.crop(MARK_BOX)
    icon = mark.resize((1024, 1024), Image.LANCZOS).convert("RGBA")
    ASSETS.mkdir(parents=True, exist_ok=True)
    icon.resize((512, 512), Image.LANCZOS).save(ASSETS / "hallucinate.png", optimize=True)
    icon.save(ASSETS / "hallucinate-1024.png", optimize=True)
    for size in SIZES:
        d = HICOLOR / f"{size}x{size}" / "apps"
        d.mkdir(parents=True, exist_ok=True)
        icon.resize((size, size), Image.LANCZOS).save(d / "hallucinate.png", optimize=True)
    icon.save(ASSETS / "hallucinate.ico", sizes=[(s, s) for s in (16, 24, 32, 48, 64, 128, 256)])
    # Full logo (with wordmark) for the README header, About page and social preview.
    src.resize((1024, 1024), Image.LANCZOS).save(ASSETS / "logo.png", optimize=True)
    wizard = src.crop((0, 0, src.width, 800)).resize((164, 314), Image.LANCZOS)
    wizard.save(ASSETS / "setup-wizard.bmp")
    social = Image.new("RGB", (1280, 640), (0, 0, 0))
    social.paste(src.resize((640, 640), Image.LANCZOS), (320, 0))
    social.save(ROOT / "assets" / "logo" / "social-preview.png", optimize=True)
    print("icons generated")


if __name__ == "__main__":
    main()
