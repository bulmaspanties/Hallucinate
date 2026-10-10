import argparse
import json
import logging
import os
import signal
import sys
from pathlib import Path

from PySide6.QtCore import QTimer, QUrl
from PySide6.QtGui import QIcon
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtWidgets import QApplication

from . import __version__
from .control import ControlServer, send_control
from .core import paths
from .discord import DiscordPresence
from .library import Library
from .listenbrainz import ListenBrainzScrobbler
from .lyricsctl import LyricsController
from .metaedit import MetadataEditor
from .player import Player
from .scrobbling import LastFmScrobbler
from .shell import DesktopShell
from .themes import ThemeManager
from .thumbs import ArtProvider
from .userlib import UserLibrary

HERE = Path(__file__).resolve().parent


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="hallucinate", description="Modern desktop music player")
    ap.add_argument("folders", nargs="*", help="music folders to add to the library")
    controls = ap.add_mutually_exclusive_group()
    controls.add_argument("--next", dest="control", action="store_const", const="next", help="skip to the next track")
    controls.add_argument("--prev", dest="control", action="store_const", const="prev", help="play the previous track")
    controls.add_argument("--play-pause", dest="control", action="store_const", const="play-pause", help="toggle playback")
    controls.add_argument("--status", dest="control", action="store_const", const="status", help="print current playback status as JSON")
    ap.add_argument("--quit-after", type=int, metavar="MS", help=argparse.SUPPRESS)
    ap.add_argument("--version", action="version", version=__version__)
    args, qt_args = ap.parse_known_args(argv if argv is not None else sys.argv[1:])

    if args.control:
        response = send_control(args.control)
        if response is None:
            print("Hallucinate is not running; start it before using playback controls.", file=sys.stderr)
            return 1
        if not response.get("ok"):
            print(response.get("error", "Playback control failed."), file=sys.stderr)
            return 1
        if args.control == "status":
            print(json.dumps(response["status"], ensure_ascii=False))
        return 0

    existing = (
        send_control("add-folders", folders=args.folders)
        if args.folders
        else send_control("raise")
    )
    if existing is not None and existing.get("ok"):
        return 0

    QQuickStyle.setStyle("Basic")
    app = QApplication([sys.argv[0], *qt_args])
    app.setApplicationName("Hallucinate")
    app.setOrganizationName("hallucinate")
    app.setApplicationDisplayName("Hallucinate")
    app.setDesktopFileName(os.environ.get("FLATPAK_ID", "hallucinate"))  # must match the installed .desktop
    if sys.platform == "win32":
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("io.github.bulmaspanties.Hallucinate")
    icon = HERE / "assets" / ("hallucinate.ico" if sys.platform == "win32" else "hallucinate.png")
    if icon.exists():
        app.setWindowIcon(QIcon(str(icon)))

    control = ControlServer()
    if not control.listen():
        return 0

    from PySide6.QtCore import QSettings

    from .migrate import migrate_legacy
    try:
        migrate_legacy(
            paths.data_dir(), paths.config_dir(), paths.legacy_locations(),
            QSettings("hallucinate", "hallucinate"), paths.cache_dir(),
        )
    except Exception:  # noqa: BLE001
        logging.getLogger(__name__).exception("Legacy data migration failed")

    # A short GIL switch interval keeps the GUI thread responsive while worker threads parse tags.
    sys.setswitchinterval(0.001)
    library = Library(paths.db_path(), paths.art_dir())
    control.setLibrary(library)
    player = Player(session_file=paths.data_dir() / "session.json")
    control.setPlayer(player)
    library.setPlayer(player)
    user_lib = UserLibrary(paths.db_path(), player)
    library.reloaded.connect(user_lib.refresh)
    meta_editor = MetadataEditor(paths.db_path(), paths.art_dir())
    meta_editor.changed.connect(library.reload)
    lyrics = LyricsController(paths.db_path(), player)
    scrobbler = LastFmScrobbler(player, paths.data_dir())
    listenbrainz = ListenBrainzScrobbler(player, paths.data_dir(), user_lib)
    theme_manager = ThemeManager(paths.config_dir(), player)

    discord = DiscordPresence(player)
    shell = DesktopShell(app, player, app.windowIcon())

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
    ctx.setContextProperty("metaEditor", meta_editor)
    ctx.setContextProperty("lyricsCtl", lyrics)
    ctx.setContextProperty("scrobbler", scrobbler)
    ctx.setContextProperty("listenbrainz", listenbrainz)
    ctx.setContextProperty("shell", shell)
    ctx.setContextProperty("discord", discord)
    ctx.setContextProperty("themeManager", theme_manager)
    engine.addImportPath(str(HERE / "qml"))
    engine.load(QUrl.fromLocalFile(str(HERE / "qml" / "main.qml")))
    if not engine.rootObjects():
        control.close()
        return 1

    shell.setWindow(engine.rootObjects()[0])
    control.setRaiseCallback(shell.showMain)
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
    control.close()
    del engine
    discord.shutdown()
    shell.shutdown()
    scrobbler.shutdown()
    listenbrainz.shutdown()
    del theme_manager
    player.shutdown()
    lyrics.shutdown()
    meta_editor.shutdown()
    user_lib.shutdown()
    library.shutdown()
    del scrobbler, listenbrainz
    del mpris
    return code


if __name__ == "__main__":
    sys.exit(main())
