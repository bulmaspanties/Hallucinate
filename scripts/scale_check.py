"""Run the whole app against a big synthetic library and report the worst window freeze for each action.

    python scripts/scale_check.py [--tracks 250000] [--plays 300000] [--dir /tmp/hallucinate-scale]

Builds the library once with bench_library.build (reused when it exists), opens the real window offscreen,
then visits every page, switches album views, opens an album and an artist, types a search, plays and skips,
and rescans. A heartbeat timer on the GUI thread measures the longest gap during each step; anything much over
250 ms is felt as a stall. bench_library.py times the queries themselves; this checks they stay off the window."""
import argparse
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))


def rss_mb():
    try:
        with open("/proc/self/statm") as f:
            return int(f.read().split()[1]) * os.sysconf("SC_PAGE_SIZE") / 1e6
    except OSError:
        return float("nan")


def launch(args):
    """Start the real window on the synthetic library of `args` (tracks, plays, dir) and wait until it's ready.
    Returns what a check drives: app, window, library, player, wait(ms), go(page) and the heartbeat."""
    work = Path(args.dir) / f"n{args.tracks}"
    work.mkdir(parents=True, exist_ok=True)
    for k in ("XDG_DATA_HOME", "XDG_CONFIG_HOME", "XDG_CACHE_HOME"):
        os.environ[k] = str(work / k.lower())
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    from PySide6.QtCore import Q_ARG, QEventLoop, QMetaObject, QObject, Qt, QTimer, QUrl
    from PySide6.QtGui import QIcon
    from PySide6.QtQml import QQmlApplicationEngine
    from PySide6.QtQuickControls2 import QQuickStyle
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication

    app = QApplication(sys.argv[:1])
    sys.setswitchinterval(0.001)  # as the app does
    db_path = work / "library.db"
    if not db_path.exists():
        import bench_library

        print(f"Building {args.tracks} songs and {args.plays} plays…", flush=True)
        bench_library.build(db_path, args.tracks, args.plays, work / "covers")

    from hallucinate import scrobbling
    from hallucinate.app import QML_STYLE
    from hallucinate.discord import DiscordPresence
    from hallucinate.headphones import HeadphoneFinder
    from hallucinate.library import Library
    from hallucinate.listenbrainz import ListenBrainzScrobbler
    from hallucinate.lyricsctl import LyricsController
    from hallucinate.metaedit import MetadataEditor
    from hallucinate.player import Player
    from hallucinate.podcasts import Podcasts
    from hallucinate.replaygain import ReplayGainAnalyzer
    from hallucinate.scrobbling import LastFmScrobbler
    from hallucinate.servers import Servers
    from hallucinate.shell import DesktopShell
    from hallucinate.stations import Stations
    from hallucinate.themes import ThemeManager
    from hallucinate.thumbs import ArtProvider
    from hallucinate.userlib import UserLibrary

    for name in ("get_password", "set_password", "delete_password"):  # keep the probe off the real keyring
        setattr(scrobbling.keyring, name, lambda *_: None)
    QQuickStyle.setStyle(QML_STYLE)

    def wait(ms):
        """Like QTest.qWait, but through QEventLoop.exec, which (like app.exec) lets worker threads run."""
        loop = QEventLoop()
        QTimer.singleShot(ms, loop.quit)
        loop.exec()

    class Beat:
        def __init__(self):
            self.last, self.worst = time.perf_counter(), 0.0
            self.timer = QTimer()
            self.timer.setInterval(5)
            self.timer.timeout.connect(self.tick)
            self.timer.start()

        def tick(self):
            now = time.perf_counter()
            self.worst = max(self.worst, (now - self.last) * 1000)
            self.last = now

        def reset(self):
            self.last, self.worst = time.perf_counter(), 0.0

    beat = Beat()
    started = time.perf_counter()
    library = Library(db_path, work / "art")
    player = Player(session_file=work / "session.json")
    user_lib = UserLibrary(db_path, player)
    library.reloaded.connect(user_lib.refresh)
    engine = QQmlApplicationEngine()
    engine.addImageProvider("art", ArtProvider(work / "thumbs"))
    context = {
        "library": library, "player": player, "userLib": user_lib,
        "scrobbler": LastFmScrobbler(player, work / "data"),
        "listenbrainz": ListenBrainzScrobbler(player, work / "data", user_lib),
        "metaEditor": MetadataEditor(db_path, work / "art"),
        "lyricsCtl": LyricsController(db_path, player),
        "replayGain": ReplayGainAnalyzer(db_path),
        "headphones": HeadphoneFinder(work / "cache", player),
        "shell": DesktopShell(app, player, QIcon()),
        "discord": DiscordPresence(player),
        "themeManager": ThemeManager(work / "config", player),
        "stations": Stations(work / "streams.db", work / "cache", player),
        "servers": Servers(db_path, work / "art", player),
        "podcasts": Podcasts(work / "streams.db", work / "data", work / "cache", player),
    }
    for k, v in context.items():
        engine.rootContext().setContextProperty(k, v)
    qml = ROOT / "hallucinate" / "qml"
    engine.addImportPath(str(qml))
    engine.load(QUrl.fromLocalFile(str(qml / "main.qml")))
    window = engine.rootObjects()[0]
    window.resize(1280, 800)
    deadline = time.time() + 300
    while not library.ready and time.time() < deadline:
        wait(20)
    print(f"{library.trackCount} songs: ready in {time.perf_counter() - started:.1f} s, rss {rss_mb():.0f} MB")
    def go(page):
        QMetaObject.invokeMethod(window, "go", Qt.ConnectionType.DirectConnection, Q_ARG("QVariant", page))

    def call(name, value):
        QMetaObject.invokeMethod(window, name, Qt.ConnectionType.DirectConnection, Q_ARG("QVariant", value))

    from types import SimpleNamespace

    return SimpleNamespace(app=app, window=window, library=library, player=player, user_lib=user_lib, wait=wait,
                           go=go, call=call, beat=beat, engine=engine, context=context, QTest=QTest, QObject=QObject)


def arguments(**defaults):
    ap = argparse.ArgumentParser()
    ap.add_argument("--tracks", type=int, default=defaults.get("tracks", 250_000))
    ap.add_argument("--plays", type=int, default=defaults.get("plays", 300_000))
    ap.add_argument("--dir", default="/tmp/hallucinate-scale")
    for name, value in defaults.items():
        if name not in ("tracks", "plays"):
            ap.add_argument(f"--{name}", type=type(value), default=value)
    return ap.parse_args()


def main():
    run = launch(arguments())
    window, library, player, wait, go, beat = run.window, run.library, run.player, run.wait, run.go, run.beat
    from PySide6.QtCore import Q_ARG, QMetaObject, QObject, Qt
    from PySide6.QtTest import QTest

    wait(1500)
    results = []

    def step(label, action, settle=1500):
        beat.reset()
        action()
        wait(settle)
        results.append((label, beat.worst))

    for page in ("albums", "artists", "songs", "folders", "liked", "stats", "history", "recap", "health", "home"):
        step(page, lambda p=page: go(p))
    for view in ("colour", "timeline"):
        go("albums")
        wait(300)
        page = window.findChild(QObject, "pageStack").property("currentItem")
        step(f"albums: {view}", lambda v=view, p=page: p.setProperty("view", v), 4000 if view == "colour" else 1500)
    album = library.albums.get(0)
    step("album page", lambda: QMetaObject.invokeMethod(
        window, "openAlbum", Qt.ConnectionType.DirectConnection, Q_ARG("QVariant", album["album_key"])))
    step("artist page", lambda: QMetaObject.invokeMethod(
        window, "openArtist", Qt.ConnectionType.DirectConnection, Q_ARG("QVariant", album["album_artist"])))

    def find_search(item):
        for child in item.childItems():
            if "Search" in str(child.property("placeholderText") or ""):
                return child
            found = find_search(child)
            if found is not None:
                return found
        return None

    def type_search():
        find_search(window.contentItem()).forceActiveFocus()
        for ch in "song 12":
            QTest.keyClick(window, ch)
            wait(120)

    step("search typing", type_search)

    def play_and_skip():
        library.playAlbum(album["album_key"], 0)
        for _ in range(5):
            player.next()
            wait(100)

    step("play and skip", play_and_skip, 500)
    beat.reset()
    began, revision = time.perf_counter(), library.detailRevision
    library.reload()
    while library.detailRevision == revision and time.perf_counter() - began < 120:
        wait(20)
    took = time.perf_counter() - began
    wait(1000)
    results.append((f"rescan applied ({took:.1f} s)", beat.worst))
    for label, worst in results:
        print(f"  {label:28s} worst freeze {worst:5.0f} ms{'  <- slow' if worst > 250 else ''}")
    print(f"  rss at end {rss_mb():.0f} MB")
    os._exit(0)  # skip teardown of a quarter-million-row window


if __name__ == "__main__":
    main()
