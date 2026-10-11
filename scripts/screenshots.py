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

from mutagen.id3 import APIC, ID3, TALB, TCON, TDRC, TIT2, TPE1, TPE2, TRCK
from PySide6.QtCore import Q_ARG, QBuffer, QByteArray, QIODevice, QMetaObject, Qt, QTimer
from PySide6.QtGui import QBrush, QColor, QImage, QLinearGradient, QPainter

GENRES = ["Dream Pop", "Indie Folk", "Synthwave", "Ambient", "Folk", "Chamber Jazz", "Indie Folk", "Post-Rock"]
YEARS = [2019, 2014, 1986, 2021, 2009, 1998, 2016, 2023]
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


def _render_tone(path, seed, seconds):
    """Audible demo track with a varied loudness shape (so waveforms look real); needs ffmpeg."""
    import shutil
    import subprocess
    if not shutil.which("ffmpeg"):
        return False
    rnd = random.Random(seed)
    f1, f2, slow, beat = rnd.choice([196, 220, 247, 262, 294]), rnd.choice([330, 392, 440]), rnd.uniform(9, 23), rnd.uniform(0.45, 0.9)
    expr = (f"(0.55*sin(2*PI*{f1}*t)+0.25*sin(2*PI*{f2}*t))"
            f"*(0.35+0.65*abs(sin(PI*t/{slow:.2f})))*(0.55+0.45*abs(sin(2*PI*t/{beat:.2f})))"
            f"*min(1,t/3)*min(1,({seconds}-t)/4)")
    result = subprocess.run(
        ["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", f"aevalsrc='{expr}':s=22050:d={seconds}",
         "-ac", "1", "-b:a", "48k", str(path)], capture_output=True)
    return result.returncode == 0


def build_library(root: Path):
    frame = b"\xff\xfb\x90\x00" + b"\x00" * 413
    for n, (artist, album, tracks) in enumerate(ALBUMS):
        art = cover(n)
        d = root / artist / album
        d.mkdir(parents=True)
        for i, title in enumerate(tracks, 1):
            f = d / f"{i:02d} {title}.mp3"
            if not _render_tone(f, seed=n * 10 + i, seconds=40 + 9 * i):
                f.write_bytes(frame * (400 + 60 * i))
            t = ID3()
            t.add(TIT2(encoding=3, text=title))
            t.add(TPE1(encoding=3, text=artist))
            t.add(TPE2(encoding=3, text=artist))
            t.add(TALB(encoding=3, text=album))
            t.add(TRCK(encoding=3, text=f"{i}/{len(tracks)}"))
            t.add(TCON(encoding=3, text=GENRES[n]))
            t.add(TDRC(encoding=3, text=str(YEARS[n])))
            t.add(APIC(encoding=3, mime="image/png", type=3, desc="", data=art))
            t.save(f)


def make_gif(out, frames, target):
    """Theme cross-section for the README (needs Pillow; skipped without it)."""
    try:
        from PIL import Image
    except ImportError:
        print("Pillow not installed; skipping", target.name)
        return
    images = [Image.open(out / f).convert("RGB").resize((800, 500), Image.LANCZOS) for f in frames]
    images[0].save(target, save_all=True, append_images=images[1:], duration=1400, loop=0, optimize=True)
    for f in frames:  # the GIF replaces the individual theme frames
        (out / f).unlink()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--scale", type=float, default=1.0)
    ap.add_argument("--themes", default="Hallucinate,Dark,Light,Catppuccin Mocha,Nord")
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="mp-shots-"))
    os.environ["HALLUCINATE_DATA"] = str(work / "data")
    os.environ["HALLUCINATE_DISABLE_LEGACY_MIGRATION"] = "1"
    os.environ["XDG_CONFIG_HOME"] = str(work / "config")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    os.environ["QT_SCALE_FACTOR"] = str(args.scale)
    build_library(work / "Music")

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    import hallucinate.app as appmod

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
            from PySide6.QtQml import QQmlEngine

            win = next(w for w in self.topLevelWindows() if w.title())
            win.resize(1280, 800)
            ctx = QQmlEngine.contextForObject(win)
            library, player, user_lib = (ctx.contextProperty(n) for n in ("library", "player", "userLib"))
            themes = [t.strip() for t in args.themes.split(",") if t.strip()]
            todo = []

            def shot(name):
                return lambda: win.grabWindow().save(str(out / f"{name}{suffix}.png"))

            def go(page):
                return lambda: QMetaObject.invokeMethod(win, "go", Q_ARG("QVariant", page))

            def seed():
                # A little listening history so Home, Stats and radio have something to show.
                tracks = library.allTracks()
                rnd = random.Random(7)
                for t in tracks:
                    for _ in range(rnd.choice([0, 0, 1, 2, 4])):
                        user_lib.recordPlay({"path": t["path"]})
                for t in rnd.sample(tracks, 8):
                    user_lib.toggleLike(t["path"])
                state["smart"] = user_lib.createSmartPlaylist("Late-night dreams", (
                    '{"match": "any", "rules": [{"field": "genre", "op": "contains", "value": "dream"},'
                    ' {"field": "genre", "op": "contains", "value": "ambient"}], "sort": "year_desc", "limit": 0}'))
                user_lib.refresh()

            def play():
                tracks = library.allTracks()
                player.setRadio(True)
                player.playList(tracks[4:6], 0)

            def pause():
                player.pause()
                player.seek(int(player.duration * 0.4))

            def open_smart():
                QMetaObject.invokeMethod(win, "openSmartPlaylist", Q_ARG("QVariant", state["smart"]),
                                         Q_ARG("QVariant", "Late-night dreams"))

            def editor(method, *values):
                def call():
                    from PySide6.QtCore import QObject
                    smart_editor = win.findChild(QObject, "smartEditor")
                    QMetaObject.invokeMethod(smart_editor, method,
                                             *[Q_ARG("QVariant", v() if callable(v) else v) for v in values])
                return call

            state = {}
            todo += [seed, play, pause]
            for page in ("home", "albums", "songs", "settings"):
                todo += [go(page), shot(page)]
            todo += [go("home"), lambda: win.setProperty("queueOpen", True), shot("queue"),
                     lambda: win.setProperty("queueOpen", False)]
            todo += [open_smart, shot("smart-playlist"),
                     editor("openEdit", lambda: state["smart"], "Late-night dreams")]
            todo += [shot("smart-editor"), editor("reject"), go("home")]
            for th in themes:
                slug = th.lower().replace(" ", "-")
                todo += [lambda t=th: managers[0].selectTheme(t), shot(f"theme-{slug}")]
            todo.append(lambda: managers[0].selectTheme(themes[0]))
            todo.append(lambda: player.setRadio(False))
            todo.append(lambda: make_gif(out, [f"theme-{t.lower().replace(' ', '-')}{suffix}.png" for t in themes],
                                         out / f"themes{suffix}.gif"))

            def next_step():
                if todo:
                    todo.pop(0)()
                    QTimer.singleShot(900, next_step)
                else:
                    self.quit()

            next_step()

    appmod.QApplication = Shots
    sys.exit(appmod.main([str(work / "Music")]))


if __name__ == "__main__":
    main()
