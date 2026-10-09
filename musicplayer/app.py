import argparse
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
from .scrobbling import LastFmScrobbler
from .themes import ThemeManager
from .thumbs import ArtProvider
from .userlib import UserLibrary

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
    if sys.platform == "win32":
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("musicplayer.MusicPlayer")
    icon = HERE / "assets" / ("musicplayer.ico" if sys.platform == "win32" else "musicplayer.svg")
    if icon.exists():
        app.setWindowIcon(QIcon(str(icon)))

    # A short GIL switch interval keeps the GUI thread responsive while worker threads parse tags.
    sys.setswitchinterval(0.001)
    library = Library(paths.db_path(), paths.art_dir())
    player = Player(session_file=paths.data_dir() / "session.json")
    library.setPlayer(player)
    user_lib = UserLibrary(paths.db_path(), player)
    library.reloaded.connect(user_lib.refresh)
    scrobbler = LastFmScrobbler(player, paths.data_dir())
    theme_manager = ThemeManager(paths.config_dir(), player)

    for f in args.folders:
        library.addFolder(f)
    if not library.folders:
        music = Path.home() / "Music"
        if music.is_dir():
            library.addFolder(str(music))
    QTimer.singleShot(0, library.rescan)
    player.restoreSession()

    engine = QQmlApplicationEngine()
    engine.addImageProvider("art", ArtProvider(paths.data_dir() / "thumbs"))
    ctx = engine.rootContext()
    ctx.setContextProperty("library", library)
    ctx.setContextProperty("player", player)
    ctx.setContextProperty("userLib", user_lib)
    ctx.setContextProperty("scrobbler", scrobbler)
    ctx.setContextProperty("themeManager", theme_manager)
    engine.addImportPath(str(HERE / "qml"))
    engine.load(QUrl.fromLocalFile(str(HERE / "qml" / "main.qml")))
    if not engine.rootObjects():
        return 1

    mpris = None
    try:
        if not sys.platform.startswith("linux"):
            raise RuntimeError("only available on Linux")
        from .mpris import MprisService

        window = engine.rootObjects()[0]
        mpris = MprisService(player, lambda: (window.show(), window.raise_()), app.quit)
    except Exception as e:  # MPRIS is optional
        if sys.stderr is not None:
            print(f"MPRIS unavailable: {e}", file=sys.stderr)

    signal.signal(signal.SIGINT, lambda *_: app.quit())  # also valid on Windows
    if args.quit_after is not None:
        QTimer.singleShot(args.quit_after, app.quit)
    # Python needs to wake up periodically to handle SIGINT.
    tick = QTimer()
    tick.start(500)
    tick.timeout.connect(lambda: None)

    code = app.exec()
    del engine
    scrobbler.shutdown()
    del theme_manager
    player.shutdown()
    user_lib.shutdown()
    library.shutdown()
    del scrobbler
    del mpris
    return code


if __name__ == "__main__":
    sys.exit(main())
