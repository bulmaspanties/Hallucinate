import argparse
import os
import signal
import sys
from pathlib import Path

from PySide6.QtCore import QTimer, QUrl
from PySide6.QtGui import QGuiApplication, QIcon
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuickControls2 import QQuickStyle

from . import __version__
from .core import paths
from .library import Library
from .player import Player

HERE = Path(__file__).resolve().parent


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="musicplayer", description="Modern desktop music player")
    ap.add_argument("folders", nargs="*", help="music folders to add to the library")
    ap.add_argument("--quit-after", type=int, metavar="MS", help=argparse.SUPPRESS)
    ap.add_argument("--version", action="version", version=__version__)
    args, qt_args = ap.parse_known_args(argv if argv is not None else sys.argv[1:])

    QQuickStyle.setStyle("Basic")
    app = QGuiApplication([sys.argv[0], *qt_args])
    app.setApplicationName("musicplayer")
    app.setOrganizationName("musicplayer")
    app.setApplicationDisplayName("Music Player")
    app.setDesktopFileName("musicplayer")
    icon = HERE / "assets" / "musicplayer.svg"
    if icon.exists():
        app.setWindowIcon(QIcon(str(icon)))

    library = Library(paths.db_path(), paths.art_dir())
    player = Player(session_file=paths.data_dir() / "session.json")

    for f in args.folders:
        library.addFolder(f)
    if not library.folders:
        music = Path.home() / "Music"
        if music.is_dir():
            library.addFolder(str(music))
    QTimer.singleShot(0, library.rescan)
    player.restoreSession()

    engine = QQmlApplicationEngine()
    ctx = engine.rootContext()
    ctx.setContextProperty("library", library)
    ctx.setContextProperty("player", player)
    engine.addImportPath(str(HERE / "qml"))
    engine.load(QUrl.fromLocalFile(str(HERE / "qml" / "main.qml")))
    if not engine.rootObjects():
        return 1

    mpris = None
    try:
        from .mpris import MprisService

        window = engine.rootObjects()[0]
        mpris = MprisService(player, lambda: (window.show(), window.raise_()), app.quit)
    except Exception as e:  # MPRIS is optional
        print(f"MPRIS unavailable: {e}", file=sys.stderr)

    signal.signal(signal.SIGINT, lambda *_: app.quit())
    if args.quit_after is not None:
        QTimer.singleShot(args.quit_after, app.quit)
    # Python needs to wake up periodically to handle SIGINT.
    tick = QTimer()
    tick.start(500)
    tick.timeout.connect(lambda: None)

    code = app.exec()
    del engine
    player.shutdown()
    library.shutdown()
    del mpris
    return code


if __name__ == "__main__":
    sys.exit(main())
