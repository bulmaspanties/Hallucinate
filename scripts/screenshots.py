"""Render README screenshots offscreen from a synthetic demo library.

    QT_QPA_PLATFORM=offscreen python scripts/screenshots.py docs/screenshots [--scale 2]

Needs PySide6, mutagen and numpy; ffmpeg is NOT required (tracks are silent MPEG frames with generated covers).
"""
import argparse
import os
import random
import sys
import tempfile
from pathlib import Path

from mutagen.id3 import APIC, ID3, TALB, TIT2, TPE1, TPE2, TRCK
from PySide6.QtCore import Q_ARG, QBuffer, QByteArray, QIODevice, QMetaObject, Qt, QTimer
from PySide6.QtGui import QBrush, QColor, QImage, QLinearGradient, QPainter

ALBUMS = [
    ("Aurora Vale", "Northern Lights", ["Echoes of Dawn", "Midnight Rain", "Glass Horizon", "Polar Drift"]),
    ("Blue Harbor", "Tidal", ["Salt & Rope", "Lantern Bay", "Low Tide", "Harbor Lights"]),
    ("Cinder Fox", "Ember Season", ["Ash Road", "Slow Burn", "Foxfire", "Kindling"]),
    ("Daydream Atlas", "Cartography", ["Map of Silence", "Longitude", "Meridian", "Compass Rose"]),
    ("Echo Meadow", "Fieldwork", ["Clover", "Dew Point", "Hayloft", "Evening Grass"]),
    ("Fable Quartet", "Folio", ["Prologue", "Marginalia", "Colophon", "Epilogue"]),
    ("Glass Orchard", "Windfall", ["Cider", "Bough", "Orchard Rain", "Harvest Moon"]),
    ("Hollow Pines", "Evergreen", ["Needles", "Understory", "Timberline", "Frost"]),
]


def cover(seed):
    rnd = random.Random(seed)
    img = QImage(500, 500, QImage.Format.Format_RGB32)
    p = QPainter(img)
    g = QLinearGradient(0, 0, 500, 500)
    g.setColorAt(0, QColor.fromHsv(rnd.randrange(360), 180, 220))
    g.setColorAt(1, QColor.fromHsv(rnd.randrange(360), 200, 120))
    p.fillRect(img.rect(), QBrush(g))
    p.setPen(Qt.PenStyle.NoPen)
    for _ in range(5):
        p.setBrush(QColor.fromHsv(rnd.randrange(360), 120, 255, 70))
        p.drawEllipse(rnd.randrange(-100, 400), rnd.randrange(-100, 400), rnd.randrange(120, 400), rnd.randrange(120, 400))
    p.end()
    ba, buf = QByteArray(), None
    buf = QBuffer(ba)
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    img.save(buf, "PNG")
    return bytes(ba)


def build_library(root: Path):
    frame = b"\xff\xfb\x90\x00" + b"\x00" * 413
    for n, (artist, album, tracks) in enumerate(ALBUMS):
        art = cover(n)
        d = root / artist / album
        d.mkdir(parents=True)
        for i, title in enumerate(tracks, 1):
            f = d / f"{i:02d} {title}.mp3"
            f.write_bytes(frame * (400 + 60 * i))
            t = ID3()
            t.add(TIT2(encoding=3, text=title))
            t.add(TPE1(encoding=3, text=artist))
            t.add(TPE2(encoding=3, text=artist))
            t.add(TALB(encoding=3, text=album))
            t.add(TRCK(encoding=3, text=f"{i}/{len(tracks)}"))
            t.add(APIC(encoding=3, mime="image/png", type=3, desc="", data=art))
            t.save(f)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--scale", type=float, default=1.0)
    ap.add_argument("--themes", default="Dark,Light,Catppuccin Mocha,Nord")
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="mp-shots-"))
    os.environ["MUSICPLAYER_DATA"] = str(work / "data")
    os.environ["XDG_CONFIG_HOME"] = str(work / "config")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    os.environ["QT_SCALE_FACTOR"] = str(args.scale)
    build_library(work / "Music")

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    import musicplayer.app as appmod

    managers = []
    orig_tm = appmod.ThemeManager

    class TM(orig_tm):
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            managers.append(self)

    appmod.ThemeManager = TM

    suffix = "" if args.scale == 1 else f"@{args.scale:g}x"
    base = appmod.QApplication

    class Shots(base):
        def exec(self):
            QTimer.singleShot(2500, lambda: self.run_shots())
            return super().exec()

        def run_shots(self):
            win = next(w for w in self.topLevelWindows() if w.title().startswith("Music Player") or w.title())
            win.resize(1280, 800)
            steps = [("home", "dark-home"), ("albums", "dark-albums"), ("songs", "dark-songs"), ("settings", "dark-settings")]
            todo = []
            themes = [t.strip() for t in args.themes.split(",") if t.strip()]
            for page, name in steps:
                todo.append(lambda p=page: QMetaObject.invokeMethod(win, "go", Q_ARG("QVariant", p)))
                todo.append(lambda n=name: win.grabWindow().save(str(out / f"{n}{suffix}.png")))
            todo.append(lambda: QMetaObject.invokeMethod(win, "go", Q_ARG("QVariant", "home")))
            todo.append(lambda: win.setProperty("queueOpen", True))
            todo.append(lambda: win.grabWindow().save(str(out / f"queue{suffix}.png")))
            todo.append(lambda: win.setProperty("queueOpen", False))
            for th in themes[1:]:
                slug = th.lower().replace(" ", "-")
                todo.append(lambda t=th: managers[0].selectTheme(t))
                todo.append(lambda s_=slug: win.grabWindow().save(str(out / f"{s_}-home{suffix}.png")))
            todo.append(lambda: managers[0].selectTheme(themes[0]))

            def next_step():
                if todo:
                    todo.pop(0)()
                    QTimer.singleShot(600, next_step)
                else:
                    self.quit()

            next_step()

    appmod.QApplication = Shots
    sys.exit(appmod.main([str(work / "Music")]))


if __name__ == "__main__":
    main()
