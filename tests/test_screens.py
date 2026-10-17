"""Every page and overlay, in every theme: no QML warnings, and in dark themes no glaring unthemed white blocks.

This catches bugs like the Stats rows that fell back to white when their colour binding failed. Rendering uses
Qt's software renderer, so shader effects are left out, but every control, colour and layout is drawn."""
import numpy as np
import pytest
from PySide6.QtCore import Q_ARG, Q_RETURN_ARG, QMetaObject, QObject, QPointF, Qt, QUrl
from PySide6.QtGui import QIcon, QImage
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuickControls2 import QQuickStyle

from hallucinate.app import QML_STYLE
from hallucinate.core.db import Database

PAGES = ("home", "albums", "artists", "songs", "folders", "liked", "stats", "history", "recap", "health",
         "visualizer", "settings")
BLOCK = 24


def white_blocks(image, threshold=0.92, share=0.95):
    """(x, y) of BLOCK-pixel squares that are nearly all near-white."""
    img = image.convertToFormat(QImage.Format.Format_RGB32)
    w, h = img.width(), img.height()
    arr = np.frombuffer(img.constBits(), np.uint8, img.bytesPerLine() * h).reshape(h, img.bytesPerLine())
    px = arr[:, : w * 4].reshape(h, w, 4)[:, :, :3].astype(np.float32) / 255  # BGRA in memory
    lum = 0.0722 * px[:, :, 0] + 0.7152 * px[:, :, 1] + 0.2126 * px[:, :, 2]
    bright = lum > threshold
    hb, wb = h // BLOCK, w // BLOCK
    blocks = bright[: hb * BLOCK, : wb * BLOCK].reshape(hb, BLOCK, wb, BLOCK).mean(axis=(1, 3))
    ys, xs = np.nonzero(blocks >= share)
    return [(int(x) * BLOCK, int(y) * BLOCK) for y, x in zip(ys, xs)]


def plain(value):
    """A QML `var` property as Python data: older PySide6 hands back a QJSValue."""
    return value.toVariant() if hasattr(value, "toVariant") else value


def seed(tmp_path):
    """A small library: two albums with plays, a like, a rating, a playlist and a smart playlist."""
    music = tmp_path / "Music"
    db = Database(tmp_path / "library.db")
    for n, (artist, album) in enumerate((("Aurora Vale", "Northern Lights"), ("Blue Harbor", "Tidal"))):
        for i in range(4):
            path = str(music / artist / album / f"{i + 1:02d}.flac")
            db.upsert_track({
                "path": path, "mtime": 0, "size": 1, "title": f"Song {n}{i}", "artist": artist, "album_artist": artist,
                "aa_tag": 1, "album": album, "album_key": f"k{n}", "track_no": i + 1, "disc_no": 0, "year": 2000 + n,
                "genre": "Dream Pop", "duration": 180.0 + i, "fmt": "FLAC", "codec": "FLAC", "bitrate": 900_000,
                "sample_rate": 44100,
            })
            for _ in range(i + 1):
                db.record_play(path)
    db.add_folder(str(music))
    db.set_liked(str(music / "Aurora Vale" / "Northern Lights" / "01.flac"), True)
    db.set_rating(str(music / "Blue Harbor" / "Tidal" / "02.flac"), 4)
    pid = db.create_playlist("Evening")
    db.playlist_add(pid, [str(music / "Aurora Vale" / "Northern Lights" / "02.flac")])
    db.commit()
    db.close()


def seed_varied(tmp_path):
    """More of a real collection on top of seed(): five formats and artists with long names, all played this
    month, so legends and rows have something to wrap and crowd."""
    music = tmp_path / "Music"
    db = Database(tmp_path / "library.db")
    names = ("The Extraordinarily Long Named Orchestra", "Midnight Cathedral Choir", "Sunset Boulevard Ensemble",
             "Quiet Static", "Lowercase Afternoon Radio")
    for n, (artist, fmt) in enumerate(zip(names, ("MP3", "M4A", "AAC", "OGG", "OPUS"))):
        for i in range(3):
            path = str(music / artist / "Album" / f"{i + 1:02d}.{fmt.lower()}")
            db.upsert_track({
                "path": path, "mtime": 0, "size": 1, "title": f"Track {n}{i}", "artist": artist,
                "album_artist": artist, "aa_tag": 1, "album": f"Album of {artist}", "album_key": f"v{n}",
                "track_no": i + 1, "disc_no": 0, "year": 2010 + n, "genre": "Ambient", "duration": 200.0 + i,
                "fmt": fmt, "codec": fmt, "bitrate": 256_000, "sample_rate": 44100,
            })
            for _ in range(5 + n):
                db.record_play(path)
    db.commit()
    db.close()


@pytest.fixture
def app_window(qapp, tmp_path, monkeypatch, request):
    """The whole window over the seeded library (or, parametrized with "empty", none: a first start), with page
    transitions off."""
    from conftest import wait_for

    empty = getattr(request, "param", None) == "empty"
    varied = getattr(request, "param", None) == "varied"

    from hallucinate import scrobbling
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
    from hallucinate.userlib import UserLibrary

    for name in ("get_password", "set_password", "delete_password"):
        monkeypatch.setattr(scrobbling.keyring, name, lambda *_: None)
    QQuickStyle.setStyle(QML_STYLE)
    if not empty:
        seed(tmp_path)
    if varied:
        seed_varied(tmp_path)
    db_path = tmp_path / "library.db"
    library = Library(db_path, tmp_path / "art")
    player = Player(session_file=tmp_path / "session.json")
    user_lib = UserLibrary(db_path, player)
    objects = {
        "library": library, "player": player, "userLib": user_lib,
        "scrobbler": LastFmScrobbler(player, tmp_path / "data"),
        "listenbrainz": ListenBrainzScrobbler(player, tmp_path / "data", user_lib),
        "metaEditor": MetadataEditor(db_path, tmp_path / "art"),
        "lyricsCtl": LyricsController(db_path, player),
        "replayGain": ReplayGainAnalyzer(db_path),
        "headphones": HeadphoneFinder(tmp_path / "cache", player),
        "shell": DesktopShell(qapp, player, QIcon()),
        "discord": DiscordPresence(player),
        "themeManager": ThemeManager(tmp_path / "config", player),
        "stations": Stations(tmp_path / "streams.db", tmp_path / "cache", player),
        "servers": Servers(db_path, tmp_path / "art", player),
        "podcasts": Podcasts(tmp_path / "streams.db", tmp_path / "data", tmp_path / "cache", player),
    }
    engine = QQmlApplicationEngine()
    for key, value in objects.items():
        engine.rootContext().setContextProperty(key, value)
    from pathlib import Path

    qml_dir = Path(__file__).parents[1] / "hallucinate" / "qml"
    engine.addImportPath(str(qml_dir))
    warnings = []
    engine.warnings.connect(lambda ws: warnings.extend(str(w) for w in ws))
    engine.load(QUrl.fromLocalFile(str(qml_dir / "main.qml")))
    window = engine.rootObjects()[0]
    window.resize(1100, 1600)  # tall, so long pages are drawn further down
    stack = window.findChild(QObject, "pageStack")
    for transition in ("pushEnter", "pushExit", "popEnter", "popExit", "replaceEnter", "replaceExit"):
        stack.setProperty(transition, None)  # pages appear at once, so each is drawn settled
    if empty:
        assert wait_for(lambda: library.ready)
    else:
        assert wait_for(lambda: library.trackCount == (23 if varied else 8) and user_lib.topArtists.count > 0)
        player.playList(library.allTracks()[:3], 0)
        player.pause()

    yield window, objects, warnings
    window.close()
    del stack
    qapp.processEvents()
    for obj in objects.values():
        if hasattr(obj, "shutdown"):
            obj.shutdown()


def test_every_page_in_every_theme(qapp, app_window):
    window, objects, warnings = app_window
    manager = objects["themeManager"]

    def invoke(method, *args):
        assert QMetaObject.invokeMethod(window, method, Qt.ConnectionType.DirectConnection,
                                        *[Q_ARG("QVariant", a) for a in args]), method

    def settle():
        for _ in range(3):
            qapp.processEvents()

    def screens():
        for page in PAGES:
            invoke("go", page)
            settle()
            yield page
        invoke("go", "albums")
        invoke("openAlbum", "k0")
        settle()
        yield "album"
        invoke("openArtist", "Aurora Vale")
        settle()
        yield "artist"
        invoke("go", "home")
        window.setProperty("queueOpen", True)
        settle()
        yield "queue"
        window.setProperty("queueOpen", False)
        now_playing = window.findChild(QObject, "nowPlayingView")
        now_playing.setProperty("open", True)
        now_playing.setProperty("lyricsMode", True)
        settle()
        yield "now playing"
        now_playing.setProperty("open", False)
        now_playing.setProperty("lyricsMode", False)
        welcome = window.findChild(QObject, "welcome")
        for step in (0, 1, 2):
            welcome.setProperty("open", True)
            welcome.setProperty("step", step)
            settle()
            yield f"welcome {step + 1}"
        welcome.setProperty("open", False)
        settle()
        dialog = window.findChild(QObject, "updateDialog")
        QMetaObject.invokeMethod(dialog, "open")
        settle()
        yield "update dialog"
        QMetaObject.invokeMethod(dialog, "close")
        settle()
        dialog = window.findChild(QObject, "closeDialog")
        QMetaObject.invokeMethod(dialog, "open")
        settle()
        yield "close dialog"
        QMetaObject.invokeMethod(dialog, "close")
        settle()
        # a menu with a row under the pointer: that row was drawn white on white in dark themes
        menu = window.findChild(QObject, "albumMenu")
        QMetaObject.invokeMethod(menu, "show", Q_ARG("QVariant", ["k0"]), Q_ARG("QVariant", "Northern Lights"),
                                 Q_ARG("QVariant", "Aurora Vale"))
        menu.setProperty("x", 300)
        menu.setProperty("y", 120)
        menu.setProperty("currentIndex", 1)
        settle()
        yield "album menu"
        QMetaObject.invokeMethod(menu, "close")
        settle()
        editor = window.findChild(QObject, "tagEditor")
        QMetaObject.invokeMethod(editor, "editAlbum", Q_ARG("QVariant", "k0"))
        settle()
        yield "edit album"
        QMetaObject.invokeMethod(editor, "reject")
        settle()
        dialog = window.findChild(QObject, "trashAlbumsDialog")
        dialog.setProperty("what", "“Northern Lights”")
        QMetaObject.invokeMethod(dialog, "open")
        settle()
        yield "trash dialog"
        QMetaObject.invokeMethod(dialog, "close")
        settle()

    problems = []
    for theme in manager.availableThemes:
        assert manager.selectTheme(theme)
        from PySide6.QtTest import QTest

        QTest.qWait(260)  # theme colours fade over ~220 ms
        dark = manager.bg.lightnessF() < 0.5
        for screen in screens():
            QTest.qWait(40 if screen.startswith(("now", "welcome")) else 0)
            if dark and screen != "welcome 2":  # the theme picker shows light themes' tiles on purpose
                blocks = white_blocks(window.grabWindow())
                if blocks:
                    problems.append(f"{theme} / {screen}: {len(blocks)} white blocks, first at {blocks[0]}")
            if warnings:
                problems.append(f"{theme} / {screen}: {warnings[:2]}")
                warnings.clear()
    assert not problems, "\n".join(problems[:20])


def test_search_results_draw_without_per_row_python_reads(qapp, app_window, monkeypatch):
    """Each read from Python while drawing waits for any worker thread busy in Python, so search results (rebuilt
    on every keystroke) must come over as one plain list, with likes and the playing song looked up once."""
    from conftest import wait_for

    from hallucinate.models import DictModel

    window, objects, warnings = app_window
    library = objects["library"]
    reads = []
    original = DictModel.data
    monkeypatch.setattr(DictModel, "data", lambda self, index, role=0: reads.append(role) or original(self, index, role))

    def items():  # every item in the window, walked without a recursive closure (cycles hold QObjects)
        stack = [window.contentItem()]
        while stack:
            item = stack.pop()
            yield item
            stack.extend(item.childItems())

    def visible_rows():
        return [i for i in items() if i.objectName() == "trackRow" and i.isVisible()]

    field = next(i for i in items() if "Search" in str(i.property("placeholderText") or ""))
    field.setProperty("text", "song")
    assert wait_for(lambda: len(library.searchResults["tracks"]) == 8 and len(visible_rows()) == 8)
    for _ in range(5):
        qapp.processEvents()
    assert reads == []  # nothing per row from the Python models
    liked = {r.property("title"): r.property("liked") for r in visible_rows()}
    assert liked["Song 00"] and not liked["Song 01"]  # likes still shown (seed() likes Song 00)
    player = objects["player"]
    playing = player.current.get("path") if player.hasTrack else None
    assert [r.property("path") for r in visible_rows() if r.property("current")] == ([playing] if playing else [])
    assert not warnings, warnings[:3]
    del field


def test_albums_select_menu_and_remove(qapp, app_window):
    """Ctrl+click selects albums, the bar counts them, right-click opens the album menu, and removing goes
    through its confirmation."""
    from conftest import wait_for
    from PySide6.QtCore import QPoint
    from PySide6.QtTest import QTest

    window, objects, warnings = app_window
    library = objects["library"]
    QMetaObject.invokeMethod(window, "go", Qt.ConnectionType.DirectConnection, Q_ARG("QVariant", "albums"))

    def items():
        stack = [window.contentItem()]
        while stack:
            item = stack.pop()
            yield item
            stack.extend(item.childItems())

    def named(name):
        return [i for i in items() if i.objectName() == name and i.isVisible()]

    assert wait_for(lambda: len(named("albumCard")) == 2)
    cards = sorted(named("albumCard"), key=lambda c: c.mapToScene(c.position()).x())

    def click(card, button=Qt.MouseButton.LeftButton, mods=Qt.KeyboardModifier.NoModifier):
        p = card.mapToScene(card.position())
        QTest.mouseClick(window, button, mods, QPoint(int(p.x() + 40), int(p.y() + 40)))

    for card in cards:
        click(card, mods=Qt.KeyboardModifier.ControlModifier)
    bar = named("albumBar")
    assert wait_for(lambda b=bar[0]: b.property("shown"))
    assert next(i for i in items() if i.objectName() == "albumSelectionCount").property("text") == "2 albums selected"

    click(cards[0], Qt.MouseButton.RightButton)
    menu = window.findChild(QObject, "albumMenu")
    assert wait_for(lambda m=menu: m.property("visible"))
    keys = menu.property("keys").toVariant()
    assert len(keys) == 2  # right-clicking a selected album acts on the whole selection
    QMetaObject.invokeMethod(menu, "close")

    dialog = window.findChild(QObject, "removeAlbumsDialog")
    dialog.setProperty("keys", keys)
    QMetaObject.invokeMethod(dialog, "accept")
    assert wait_for(lambda: library.trackCount == 0 and library.hiddenCount == 8, timeout=5)
    for _ in range(5):
        qapp.processEvents()
    assert not warnings, warnings[:3]
    del bar, cards, menu, dialog


def test_timeline_year_shows_two_lines_until_asked(qapp, app_window, tmp_path):
    """A year with many albums shows two lines of covers and a "Show all" button for the rest."""
    from conftest import wait_for
    from PySide6.QtCore import QPointF
    from PySide6.QtTest import QTest

    window, objects, warnings = app_window
    library = objects["library"]
    db = Database(tmp_path / "library.db")
    for i in range(40):
        db.upsert_track({
            "path": str(tmp_path / "Music" / "Busy" / f"{i}.flac"), "mtime": 0, "size": 1, "title": f"B{i}",
            "artist": "Busy", "album_artist": "Busy", "aa_tag": 1, "album": f"Busy {i:02d}", "album_key": f"busy{i}",
            "track_no": 1, "disc_no": 0, "year": 2001, "genre": "", "duration": 100.0, "fmt": "FLAC",
            "codec": "FLAC", "bitrate": 900_000, "sample_rate": 44100,
        })
    db.commit()
    db.close()
    library.reload()
    assert wait_for(lambda: library.albumCount == 42)

    def visible(name):
        stack, found = [window.contentItem()], []
        while stack:
            item = stack.pop()
            if item.objectName() == name and item.isVisible():
                found.append(item)
            stack.extend(item.childItems())
        return found

    QMetaObject.invokeMethod(window, "go", Qt.ConnectionType.DirectConnection, Q_ARG("QVariant", "albums"))
    assert wait_for(lambda: len(visible("albumCard")) > 2)  # the grid has finished building before switching
    window.findChild(QObject, "pageStack").property("currentItem").setProperty("view", "timeline")
    assert wait_for(lambda: len(visible("timelineMore")) == 1)  # 2001 (41 albums) is busy; 2000 (one) isn't
    button = visible("timelineMore")[0]
    assert button.property("text") == "Show all 41"
    p = button.mapToScene(QPointF(button.width() / 2, button.height() / 2))
    QTest.mouseClick(window, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, p.toPoint())
    assert wait_for(lambda: not visible("timelineMore"))
    assert not warnings, warnings[:3]
    del button


def test_track_info_badges_never_draw_empty(qapp, app_window):
    """With "Show track info" on, a list that doesn't know a song's format (the artist page's Most played did
    not) must not draw an empty pill after the title."""
    from conftest import wait_for

    window, objects, warnings = app_window
    player = objects["player"]
    player.setShowTrackInfo(True)
    try:
        QMetaObject.invokeMethod(window, "openArtist", Qt.ConnectionType.DirectConnection,
                                 Q_ARG("QVariant", "Aurora Vale"))

        def badges():
            stack, found = [window.contentItem()], []
            while stack:
                item = stack.pop()
                if item.property("formatName") is not None and item.property("spokenLabel") is not None \
                        and item.isVisible():
                    found.append(item)
                stack.extend(item.childItems())
            return found

        assert wait_for(lambda: len(badges()) >= 4)
        assert all(b.property("label") for b in badges()), [b.property("label") for b in badges()]
        assert any("FLAC" in b.property("label") for b in badges())
        assert not warnings, warnings[:3]
    finally:
        player.setShowTrackInfo(False)


@pytest.mark.parametrize("app_window", ["empty"], indirect=True)
def test_first_start_pages_explain_themselves(qapp, app_window):
    """With no music yet, every page still draws cleanly, and the library pages say what to do."""
    window, objects, warnings = app_window
    manager = objects["themeManager"]

    def visible_named(name):
        stack, found = [window.contentItem()], []
        while stack:
            item = stack.pop()
            if item.objectName() == name and item.isVisible():
                found.append(item)
            stack.extend(item.childItems())
        return found

    for theme in ("Hallucinate", "Light"):
        assert manager.selectTheme(theme)
        for page in PAGES:
            QMetaObject.invokeMethod(window, "go", Qt.ConnectionType.DirectConnection, Q_ARG("QVariant", page))
            for _ in range(3):
                qapp.processEvents()
            if page in ("albums", "artists", "songs"):
                found = visible_named("noMusic")
                assert found, page
                assert found[0].property("actionText") == "Open Settings"
    assert not warnings, warnings[:3]


def test_a_crash_last_time_is_offered_as_a_report(qapp, app_window):
    from conftest import wait_for

    window, objects, warnings = app_window
    shell = objects["shell"]
    shell.setCrashReport("Crash:\nFatal Python error: Segmentation fault\n  File \"player.py\", line 1", True)
    dlg = window.findChild(QObject, "crashDialog")
    assert wait_for(lambda: dlg.property("opened"))
    assert dlg.property("title") == "Hallucinate closed unexpectedly"
    QMetaObject.invokeMethod(dlg, "accept")
    assert wait_for(lambda: shell.crashReport == "")
    copied = qapp.clipboard().text()
    assert copied.startswith("Hallucinate ") and "Previous run" in copied and "Segmentation fault" in copied
    assert not [w for w in warnings if "ConfirmDialog" in w or "main.qml" in w], warnings


def test_nothing_is_drawn_under_now_playing(qapp, app_window):
    """Once Now Playing has faded in, the window under it is hidden and the backdrop stops drifting, so an
    open Now Playing costs only itself (and nothing at all while paused)."""
    from conftest import wait_for

    window, objects, warnings = app_window
    view = window.findChild(QObject, "nowPlayingView")
    ambience = window.findChild(QObject, "ambience")
    page = window.findChild(QObject, "pageStack")
    assert ambience.property("visible") and page.property("visible")
    view.setProperty("open", True)
    assert wait_for(lambda: view.property("covering"))
    assert not ambience.property("visible") and not ambience.property("animated")
    assert not page.property("visible")
    view.setProperty("open", False)
    assert wait_for(lambda: page.property("visible") and ambience.property("visible"))


def test_everything_clickable_has_a_name_for_screen_readers(qapp, app_window):
    """Walk every page the way a screen reader sees it: anything that can be clicked, typed into or slid must
    be (or sit within three levels of) an element with a role and a spoken name."""
    from PySide6.QtGui import QAccessible
    from PySide6.QtQml import QQmlEngine

    window, objects, warnings = app_window
    QAccessible.setActive(True)
    role = QAccessible.Role
    spoken = {role.Button, role.CheckBox, role.RadioButton, role.ComboBox, role.Slider, role.EditableText,
              role.Link, role.ListItem, role.Cell, role.MenuItem, role.PageTab, role.Row, role.SpinBox,
              role.ProgressBar, role.ScrollBar, role.StaticText, role.Graphic, role.Pane, role.Grouping, role.List}

    def named(item):
        for _ in range(4):
            if item is None:
                return False
            iface = QAccessible.queryAccessibleInterface(item)
            if iface and iface.role() in spoken and (
                    iface.text(QAccessible.Text.Name) or iface.text(QAccessible.Text.Description)):
                return True  # (Qt withholds a password field's name, so those carry it as the description)
            item = item.parentItem()
        return False

    missing = set()

    def walk(item, where):
        for child in item.childItems():
            if not child.isVisible():
                continue
            cls = child.metaObject().className()
            interactive = (cls.startswith("QQuickMouseArea") and child.isEnabled()) or child.property("activeFocusOnTab") \
                or any(k in cls for k in ("TextField", "Slider", "ComboBox", "Switch", "CheckBox"))
            if interactive and not named(child):
                ctx = QQmlEngine.contextForObject(child) or QQmlEngine.contextForObject(child.parentItem())
                parent = child.parentItem()
                missing.add(f"{where}: {ctx.baseUrl().fileName() if ctx else '?'} "
                            f"{cls.split('_QML')[0]} in {parent.metaObject().className().split('_QML')[0]}")
            walk(child, where)

    def invoke(method, *args):
        QMetaObject.invokeMethod(window, method, Qt.ConnectionType.DirectConnection,
                                 *[Q_ARG("QVariant", a) for a in args])

    def visit(where):
        for _ in range(4):
            qapp.processEvents()
        walk(window.contentItem(), where)

    for page in PAGES:
        invoke("go", page)
        visit(page)
    def dialog(name, where, opener=None):
        dlg = window.findChild(QObject, name)
        assert dlg is not None, name
        if opener:
            opener(dlg)
        else:
            QMetaObject.invokeMethod(dlg, "open")
        from conftest import wait_for
        assert wait_for(lambda: dlg.property("opened")), name
        visit(where)
        QMetaObject.invokeMethod(dlg, "close")
        assert wait_for(lambda: not dlg.property("visible")), name

    with listening_extras(objects):
        stations = objects["stations"]
        stations._db.log_radio_song(stations._db.stations()[0]["id"], "FM", "Enduser", "Death Vest")
        stations.logChanged.emit()
        for page, dlg in (("stations", "addStationDialog"), ("podcasts", "followDialog")):
            invoke("go", page)
            visit(page)
            dialog(dlg, dlg)
        invoke("openPodcast", 1)
        visit("podcast")
        dialog("showSettings", "show settings")
    editor, library = objects["metaEditor"], objects["library"]
    album = library.albums.get(0)
    editor._genres["proposals"] = [{"album_key": album["album_key"], "album": album["album"], "artist": "A",
                                    "genre": "IDM", "genres": ["IDM", "Ambient"], "source": "artist", "songs": 2}]
    editor.genresChanged.emit()
    invoke("go", "health")
    visit("health")
    dialog("genreReview", "genre review")
    editor.clearGenreProposals()
    dialog("tagEditor", "edit album", lambda d: QMetaObject.invokeMethod(d, "editAlbum", Q_ARG("QVariant", album["album_key"])))
    invoke("go", "settings")
    dialog("themeEditor", "theme editor")
    dialog("whatsNewDialog", "what's new")
    shell = objects["shell"]
    shell._whats_new_dismissed = False
    invoke("go", "albums")
    albums = window.findChild(QObject, "pageStack").property("currentItem")
    for view in ("grid", "colour", "timeline"):
        albums.setProperty("view", view)
        visit(f"albums ({view})")
    albums.setProperty("view", "grid")
    invoke("openAlbum", "k0")
    visit("album")
    invoke("openArtist", "Aurora Vale")
    visit("artist")
    window.setProperty("queueOpen", True)
    visit("queue")
    window.setProperty("queueOpen", False)
    from conftest import wait_for

    now_playing = window.findChild(QObject, "nowPlayingView")
    now_playing.setProperty("open", True)
    assert wait_for(lambda: now_playing.property("covering"))
    visit("now playing")
    assert not missing, "\n".join(sorted(missing))


def test_library_health_items_open_their_usual_menus(qapp, app_window):
    from conftest import wait_for

    window, objects, warnings = app_window
    QMetaObject.invokeMethod(window, "go", Qt.ConnectionType.DirectConnection, Q_ARG("QVariant", "health"))
    qapp.processEvents()
    page = window.findChild(QObject, "pageStack").property("currentItem")
    album_menu = window.findChild(QObject, "albumMenu")
    track_menu = window.findChild(QObject, "trackMenu")
    track = objects["library"].allTracks()[0]

    QMetaObject.invokeMethod(page, "menuFor", Qt.ConnectionType.DirectConnection,
                             Q_ARG("QVariant", {"kind": "album"}),
                             Q_ARG("QVariant", {"album_key": track["album_key"], "album": track["album"],
                                                "album_artist": track["album_artist"]}))
    assert wait_for(lambda: album_menu.property("opened"))
    assert plain(album_menu.property("keys")) == [track["album_key"]]
    QMetaObject.invokeMethod(album_menu, "close")
    assert wait_for(lambda: not album_menu.property("opened"))

    QMetaObject.invokeMethod(page, "menuFor", Qt.ConnectionType.DirectConnection,
                             Q_ARG("QVariant", {"kind": "track"}),
                             Q_ARG("QVariant", {"path": track["path"], "title": track["title"]}))
    assert wait_for(lambda: track_menu.property("opened"))
    assert track_menu.property("path") == track["path"]
    assert plain(track_menu.property("info"))["album_key"] == track["album_key"]
    remove = window.findChild(QObject, "trackRemove")
    assert remove.property("enabled")
    QMetaObject.invokeMethod(track_menu, "close")
    assert not [w for w in warnings if "HealthPage" in w or "TrackMenu" in w], warnings


def test_an_artists_menu_removes_their_songs_after_asking(qapp, app_window):
    from conftest import wait_for

    window, objects, warnings = app_window
    library = objects["library"]
    track = library.allTracks()[0]
    artist = track["album_artist"]
    theirs = library.artistPaths(artist)
    before = library.trackCount
    assert theirs and track["path"] in theirs and len(theirs) < before

    menu = window.findChild(QObject, "collectionMenu")
    QMetaObject.invokeMethod(menu, "showArtist", Qt.ConnectionType.DirectConnection, Q_ARG("QVariant", artist))
    assert wait_for(lambda: menu.property("opened"))
    QMetaObject.invokeMethod(window.findChild(QObject, "collectionRemove"), "triggered")
    dialog = window.findChild(QObject, "removeAlbumsDialog")
    assert wait_for(lambda: dialog.property("opened"))
    assert dialog.property("songs") is True and artist in dialog.property("what")
    QMetaObject.invokeMethod(dialog, "accept")
    assert wait_for(lambda: library.trackCount == before - len(theirs), timeout=10)
    assert library.hiddenCount == len(theirs)
    assert not [w for w in warnings if "CollectionMenu" in w or "main.qml" in w], warnings


def test_back_and_forward_like_a_browser(qapp, app_window):
    """Back and Forward walk the pages visited, across sections too; Back reuses the page underneath."""

    window, objects, warnings = app_window
    stack = window.findChild(QObject, "pageStack")
    track = objects["library"].allTracks()[0]

    def call(name, *args):
        QMetaObject.invokeMethod(window, name, Qt.ConnectionType.DirectConnection,
                                 *[Q_ARG("QVariant", a) for a in args])
        for _ in range(3):
            qapp.processEvents()

    def where():
        item = stack.property("currentItem")
        return item.property("albumKey") or item.property("artistName") or window.property("section")

    call("go", "albums")
    call("openAlbum", track["album_key"])
    call("go", "stats")
    call("openArtist", track["album_artist"])
    assert where() == track["album_artist"]
    call("goBack")
    assert where() == "stats"
    call("goBack")
    assert where() == track["album_key"]
    album_page = stack.property("currentItem")
    call("goBack")
    assert where() == "albums"
    call("goForward")
    assert where() == track["album_key"]
    call("goForward")
    call("goForward")
    assert where() == track["album_artist"]
    call("goForward")  # nothing further: stays
    assert where() == track["album_artist"]
    call("openAlbum", track["album_key"])  # a new visit drops what was ahead
    assert window.property("forwardRoutes").toVariant() == []
    assert album_page is not None
    call("openAlbum", track["album_key"])
    under = stack.property("currentItem")
    call("openArtist", track["album_artist"])
    before = under.property("revision")
    objects["library"]._detail_revision += 1
    objects["library"].detailChanged.emit()  # a reload: only the page on screen reads again now
    for _ in range(3):
        qapp.processEvents()
    assert under.property("revision") == before
    call("goBack")
    assert stack.property("currentItem") == under and under.property("revision") == before + 1  # caught up
    call("openPlaylist", 7, "Gone soon")
    call("go", "stats")
    call("forgetRoute", "playlist", 7)  # deleted: Back skips it
    call("goBack")
    assert where() == track["album_key"]
    assert not [w for w in warnings if "main.qml" in w], warnings


def test_mouse_side_buttons_navigate_and_other_clicks_pass_through(qapp, app_window):
    from PySide6.QtCore import QPoint, QPointF
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtTest import QTest

    window, objects, warnings = app_window
    stack = window.findChild(QObject, "pageStack")
    track = objects["library"].allTracks()[0]
    QMetaObject.invokeMethod(window, "go", Qt.ConnectionType.DirectConnection, Q_ARG("QVariant", "home"))
    QMetaObject.invokeMethod(window, "openAlbum", Qt.ConnectionType.DirectConnection, Q_ARG("QVariant", track["album_key"]))
    qapp.processEvents()

    def side_button(button):
        pos = QPointF(window.width() / 2, window.height() / 2)
        for kind in (QMouseEvent.Type.MouseButtonPress, QMouseEvent.Type.MouseButtonRelease):
            qapp.sendEvent(window, QMouseEvent(kind, pos, pos, button, button if kind == QMouseEvent.Type.MouseButtonPress
                                               else Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier))
        for _ in range(3):
            qapp.processEvents()

    side_button(Qt.MouseButton.BackButton)
    assert window.property("section") == "home" and stack.property("depth") == 1
    side_button(Qt.MouseButton.ForwardButton)
    assert stack.property("currentItem").property("albumKey") == track["album_key"]

    # an ordinary click still reaches the page: the sidebar's Settings entry opens Settings
    settings = next(o for o in window.findChildren(QObject) if o.property("text") == "Settings"
                    and o.metaObject().className().startswith("RailButton"))
    centre = settings.mapToScene(QPointF(settings.width() / 2, settings.height() / 2))
    QTest.mouseClick(window, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(int(centre.x()), int(centre.y())))
    for _ in range(3):
        qapp.processEvents()
    assert window.property("section") == "settings"


import contextlib  # noqa: E402


@contextlib.contextmanager
def listening_extras(objects):
    """Internet radio and podcasts switched on, with a station and a show (long names included) to draw."""
    shell, stations, podcasts = objects["shell"], objects["stations"], objects["podcasts"]
    stations._db.add_station({"name": "A Station With An Exceedingly Long Name For Testing", "url": "http://127.0.0.1:9/s",
                              "tags": "ambient, chill, downtempo, electronic", "country": "Iceland", "codec": "MP3",
                              "bitrate": 128})
    stations.refresh()
    pid = podcasts._db.add_podcast({"title": "A Podcast Whose Title Goes On For Quite Some Time", "author": "Host",
                                    "feed_url": "https://x/feed", "description": "Notes " * 80})
    podcasts._db.merge_episodes(pid, [{"guid": str(i), "title": f"Episode {i} with a long and winding title " * 2,
                                       "url": f"https://x/{i}.mp3", "published": 1_900_000_000 + i, "duration": 1800}
                                      for i in range(3)])
    podcasts._db.set_position(1, 300)
    podcasts.reload()
    shell.setFeature("stations", True)
    shell.setFeature("podcasts", True)
    try:
        yield
    finally:
        shell.setFeature("stations", False)
        shell.setFeature("podcasts", False)


def overflowing(root):
    """What spills out of a card: visible things inside a GlassPanel that reach past its edges, unless something
    between them clips (a scrolling list, say) or they belong to a popup."""
    from PySide6.QtCore import QRectF
    from PySide6.QtQuick import QQuickItem

    found = []

    def name(item):
        return item.objectName() or item.metaObject().className().split("_QML")[0]

    def walk(item, panel, clipped):
        if not item.isVisible() or item.opacity() == 0:
            return
        cls = item.metaObject().className()
        if cls.startswith("GlassPanel"):
            panel, clipped = item, False
        elif panel is not None and not clipped and item.width() > 0 and item.height() > 0 \
                and not cls.startswith(("QQuickItem", "QQuickRepeater")):
            box = item.mapRectToItem(panel, QRectF(0, 0, item.width(), item.height()))
            if box.left() < -1 or box.top() < -1 or box.right() > panel.width() + 1 \
                    or box.bottom() > panel.height() + 1:
                text = item.property("text")
                found.append(f"{name(item)}{' “' + text + '”' if isinstance(text, str) and text else ''}"
                             f" spills out of {name(panel)} ({box.left():.0f},{box.top():.0f} "
                             f"{box.width():.0f}×{box.height():.0f} in {panel.width():.0f}×{panel.height():.0f})")
        if item.clip() or cls.startswith(("QQuickListView", "QQuickGridView", "QQuickFlickable", "QQuickPopupItem")):
            clipped = True
        for child in item.childItems():
            walk(child, panel, clipped)

    walk(root if isinstance(root, QQuickItem) else root.contentItem(), None, False)
    return found


@pytest.mark.parametrize("app_window", ["varied"], indirect=True)
@pytest.mark.parametrize("width", [760, 900, 1100, 1500])
def test_nothing_spills_out_of_its_card_at_any_width(qapp, app_window, width):
    """Tiled and half-screen windows: every card's contents stay inside the card on every page."""
    window, objects, warnings = app_window
    window.resize(width, 900)
    problems = []
    with listening_extras(objects):
        for page in PAGES + ("stations", "podcasts"):
            assert QMetaObject.invokeMethod(window, "go", Qt.ConnectionType.DirectConnection, Q_ARG("QVariant", page))
            for _ in range(4):
                qapp.processEvents()
            problems += [f"{page}: {p}" for p in overflowing(window)]
    assert not problems, "\n".join(problems[:25])


def past_the_edge(window):
    """Visible, unclipped things that reach past the window's right edge. Walked in QML: walking the item tree
    from Python can be handed a stale wrapper when many items come and go."""
    found = QMetaObject.invokeMethod(window, "pastTheEdge", Qt.ConnectionType.DirectConnection,
                                     Q_RETURN_ARG("QVariant"), Q_ARG("QVariant", None), Q_ARG("QVariant", False))
    return plain(found) or []


@pytest.mark.parametrize("app_window", ["varied"], indirect=True)
@pytest.mark.parametrize("width", [760, 900])
def test_nothing_runs_off_a_narrow_window(qapp, app_window, width):
    window, objects, warnings = app_window
    window.resize(width, 700)

    def invoke(method, *args):
        assert QMetaObject.invokeMethod(window, method, Qt.ConnectionType.DirectConnection,
                                        *[Q_ARG("QVariant", a) for a in args]), method

    def screens():
        for page in PAGES + ("stations", "podcasts"):
            invoke("go", page)
            yield page
        invoke("openPodcast", 1)
        yield "podcast"
        invoke("openAlbum", "v0")
        yield "album"
        invoke("openArtist", "The Extraordinarily Long Named Orchestra")
        yield "artist"
        invoke("go", "home")
        window.setProperty("queueOpen", True)
        yield "queue"
        window.setProperty("queueOpen", False)

    problems = []
    with listening_extras(objects):
        for screen in screens():
            for _ in range(4):
                qapp.processEvents()
            problems += [f"{screen}: {p}" for p in past_the_edge(window)]
    assert not problems, "\n".join(problems[:25])


def test_features_switched_off_disappear_everywhere(qapp, app_window):
    """Settings → Features: a page that's off leaves the sidebar and Ctrl+K, can't be reached, and is left if
    it was showing; Home's cards and the lyrics button go too. Radio and podcasts start off."""
    window, objects, warnings = app_window
    shell = objects["shell"]
    assert shell.features["stations"] is False and shell.features["podcasts"] is False

    def invoke(method, *args):
        assert QMetaObject.invokeMethod(window, method, Qt.ConnectionType.DirectConnection,
                                        *[Q_ARG("QVariant", a) for a in args]), method
        for _ in range(3):
            qapp.processEvents()

    names = {"rail_stats": "Stats", "rail_recap": "Recap"}

    def rail_labels():
        return {names.get(n, n) for n in visible_names(window, "rail_")}

    palette = window.findChild(QObject, "commandPalette")

    def palette_titles():
        out = QMetaObject.invokeMethod(palette, "commands", Qt.ConnectionType.DirectConnection,
                                       Q_RETURN_ARG("QVariant"))
        return {c["t"] for c in plain(out)}

    turned_off = ("stats", "recap", "lyrics", "homeListening", "health")
    try:
        invoke("go", "stats")
        assert "Stats" in rail_labels() and "Stats" in palette_titles()
        for name in turned_off:
            shell.setFeature(name, False)
        for _ in range(3):
            qapp.processEvents()
        assert window.property("section") == "home", "the page being shown was switched off"
        assert not {"Stats", "Recap"} & rail_labels()
        assert not {"Stats", "Recap", "Lyrics", "Library health"} & palette_titles()
        invoke("go", "recap")
        assert window.property("section") == "home"
        assert not window.findChild(QObject, "listeningCard").property("visible")
        assert not window.findChild(QObject, "homeHealthLink").property("visible")
        assert not window.findChild(QObject, "lyricsToggle").property("visible")
        invoke("go", "settings")
        check = find_item(window, "feature_stats")
        assert check is not None and check.property("checked") is False
    finally:
        for name in turned_off:
            shell.setFeature(name, True)
    for _ in range(3):
        qapp.processEvents()
    assert "Stats" in rail_labels()
    assert not warnings, warnings[:3]


def find_item(window, name):
    """An item by objectName anywhere in the window, Repeater rows included (they aren't QObject children).
    Looked up in QML: walking the item tree from Python leaves PySide wrappers behind."""
    found = QMetaObject.invokeMethod(window, "findItem", Qt.ConnectionType.DirectConnection, Q_RETURN_ARG("QVariant"),
                                     Q_ARG("QVariant", name), Q_ARG("QVariant", None))
    return found if isinstance(found, QObject) else None


def visible_names(window, prefix):
    names = QMetaObject.invokeMethod(window, "visibleNames", Qt.ConnectionType.DirectConnection,
                                     Q_RETURN_ARG("QVariant"), Q_ARG("QVariant", prefix), Q_ARG("QVariant", None))
    return set(plain(names) or [])


def test_internet_radio_page(qapp, app_window):
    """Switched on in Settings, Internet radio gets a sidebar entry and a page listing your stations, each with
    a menu; switched off, it's gone."""
    window, objects, warnings = app_window
    shell, stations = objects["shell"], objects["stations"]
    stations._db.add_station({"name": "Test FM", "url": "http://127.0.0.1:9/live", "tags": "ambient, chill",
                              "country": "Iceland", "codec": "MP3", "bitrate": 128})
    stations.refresh()

    def go(page):
        QMetaObject.invokeMethod(window, "go", Qt.ConnectionType.DirectConnection, Q_ARG("QVariant", page))
        for _ in range(3):
            qapp.processEvents()

    go("stations")
    assert window.property("section") == "home", "radio starts switched off"
    shell.setFeature("stations", True)
    try:
        go("stations")
        assert window.property("section") == "stations"
        saved = find_item(window, "savedStations")
        assert saved is not None and saved.property("height") > 40
        menu = window.findChild(QObject, "stationMenu") or find_item(window, "stationMenu")
        page = window.findChild(QObject, "pageStack").property("currentItem")
        QMetaObject.invokeMethod(page, "showMenu", Qt.ConnectionType.DirectConnection,
                                 Q_ARG("QVariant", {"id": 1, "name": "Test FM", "url": "http://x", "homepage": ""}))
        from conftest import wait_for

        assert menu is not None and wait_for(lambda: menu.property("opened"), timeout=2)
        QMetaObject.invokeMethod(menu, "close")
        add = window.findChild(QObject, "addStationDialog")
        QMetaObject.invokeMethod(add, "open")
        assert wait_for(lambda: add.property("opened"), timeout=2)
        assert add.property("linkOk") is False  # OK waits for a web link
        url = window.findChild(QObject, "stationUrl")
        url.setProperty("text", "  https://example.com/live  ")
        assert add.property("linkOk") is True
        url.setProperty("text", "file:///etc/passwd")
        assert add.property("linkOk") is False
        QMetaObject.invokeMethod(add, "close")
        assert not warnings, warnings[:3]
    finally:
        shell.setFeature("stations", False)
    for _ in range(3):
        qapp.processEvents()
    assert window.property("section") == "home"


def test_text_fields_use_the_themed_editing_menu(qapp, app_window):
    """Right-click in a text field opens the app's own menu; Qt's stock one is native and ignores the theme."""
    window, objects, warnings = app_window
    QMetaObject.invokeMethod(window, "go", Qt.ConnectionType.DirectConnection, Q_ARG("QVariant", "settings"))
    for _ in range(3):
        qapp.processEvents()
    field = find_item(window, "settingsSearch")
    assert field.property("editMenuName") == "textEditMenu"
    del field
    assert not warnings, warnings[:3]


def test_podcast_pages(qapp, app_window):
    """Switched on, Podcasts lists your shows and new episodes; a show opens on its own page with its
    episodes and their menus, and Back returns."""
    from conftest import wait_for

    window, objects, warnings = app_window
    shell, podcasts = objects["shell"], objects["podcasts"]
    pid = podcasts._db.add_podcast({"title": "Test Talk", "author": "Host", "feed_url": "https://x/feed"})
    podcasts._db.merge_episodes(pid, [
        {"guid": "2", "title": "Episode Two", "url": "https://x/2.mp3", "published": 2_000_000_000, "duration": 1800},
        {"guid": "1", "title": "Episode One", "url": "https://x/1.mp3", "published": 1_900_000_000, "duration": 1200}])
    podcasts.reload()

    def invoke(method, *args):
        assert QMetaObject.invokeMethod(window, method, Qt.ConnectionType.DirectConnection,
                                        *[Q_ARG("QVariant", a) for a in args]), method
        for _ in range(3):
            qapp.processEvents()

    invoke("go", "podcasts")
    assert window.property("section") == "home", "podcasts start switched off"
    shell.setFeature("podcasts", True)
    try:
        invoke("go", "podcasts")
        assert window.property("section") == "podcasts"
        assert find_item(window, "followedShows").property("height") > 100
        assert find_item(window, "latestEpisodes").property("visible")
        invoke("openPodcast", pid)
        page = window.findChild(QObject, "pageStack").property("currentItem")
        assert page.property("podcastId") == pid
        assert wait_for(lambda: find_item(window, "episodeList").property("count") == 2)
        menu = page.findChild(QObject, "episodeMenu")
        QMetaObject.invokeMethod(menu, "showFor", Qt.ConnectionType.DirectConnection,
                                 Q_ARG("QVariant", podcasts.episodes._items[0]), Q_ARG("QVariant", False))
        assert wait_for(lambda: menu.property("opened"), timeout=2)
        QMetaObject.invokeMethod(menu, "close")
        for name in ("showSettings",):
            dialog = page.findChild(QObject, name)
            QMetaObject.invokeMethod(dialog, "open")
            assert wait_for(lambda: dialog.property("opened"), timeout=2)
            QMetaObject.invokeMethod(dialog, "close")
        notes = menu.findChild(QObject, "episodeNotesDialog")
        QMetaObject.invokeMethod(notes, "open")
        assert wait_for(lambda: notes.property("opened"), timeout=2)
        QMetaObject.invokeMethod(notes, "close")
        invoke("goBack")
        assert window.findChild(QObject, "pageStack").property("currentItem").objectName() == "podcasts"
        invoke("go", "settings")
        assert window.findChild(QObject, "settings_podcasts").property("visible")
        assert not warnings, warnings[:3]
    finally:
        shell.setFeature("podcasts", False)


def test_song_lists_work_from_the_keyboard(qapp, app_window):
    """Up and Down move between songs (not the volume), Enter plays, the Menu key opens the song's menu."""
    from conftest import wait_for
    from PySide6.QtTest import QTest

    window, objects, warnings = app_window
    player = objects["player"]
    QMetaObject.invokeMethod(window, "go", Qt.ConnectionType.DirectConnection, Q_ARG("QVariant", "songs"))
    for _ in range(4):
        qapp.processEvents()
    window.show()
    window.requestActivate()
    QTest.qWait(50)
    page = window.findChild(QObject, "pageStack").property("currentItem")
    first = find_item(window, "trackRow")
    assert first is not None
    QMetaObject.invokeMethod(first, "forceActiveFocus")
    start = first.property("rowIndex")
    volume = player.volume
    QTest.keyClick(window, Qt.Key.Key_Down)
    QTest.keyClick(window, Qt.Key.Key_Down)
    assert window.property("activeFocusItem").property("rowIndex") == start + 2
    assert player.volume == volume
    QTest.keyClick(window, Qt.Key.Key_Up)
    assert window.property("activeFocusItem").property("rowIndex") == start + 1
    QTest.keyClick(window, Qt.Key.Key_Menu)
    menu = window.findChild(QObject, "trackMenu")
    assert wait_for(lambda: menu.property("opened"), timeout=2)
    QMetaObject.invokeMethod(menu, "close")
    QTest.qWait(50)
    del page
    assert not warnings, warnings[:3]


def test_toast_undo_playlist_names_and_going_to_whats_playing(qapp, app_window):
    from conftest import wait_for

    window, objects, warnings = app_window
    player, user_lib = objects["player"], objects["userLib"]

    def invoke(method, *args):
        QMetaObject.invokeMethod(window, method, Qt.ConnectionType.DirectConnection,
                                 *[Q_ARG("QVariant", a) for a in args])
        for _ in range(3):
            qapp.processEvents()

    # a toast with Undo: clearing the queue can be taken back from it
    toast = window.findChild(QObject, "toast")
    length = player.queueLength
    player.clearQueue()
    QMetaObject.invokeMethod(toast, "show", Q_ARG("QVariant", "Queue cleared"), Q_ARG("QVariant", 0),
                             Q_ARG("QVariant", "Undo"), Q_ARG("QVariant", None))
    assert player.queueLength == 0
    assert player.undoQueue() and player.queueLength == length

    # the open playlist's heading follows a rename made elsewhere
    pid = user_lib.playlists.get(0)["id"]
    invoke("openPlaylist", pid, user_lib.playlists.get(0)["name"])
    page = window.findChild(QObject, "pageStack").property("currentItem")
    user_lib.renamePlaylist(pid, "Late Evening")
    assert wait_for(lambda: page.property("playlistName") == "Late Evening")
    user_lib.renamePlaylist(pid, "Evening")

    # the playing bar's cover leads to what's playing: here a station, to the radio page
    from PySide6.QtCore import QPoint, QPointF
    from PySide6.QtTest import QTest

    with listening_extras(objects):
        invoke("go", "home")
        stations = objects["stations"]
        player.playList([stations._entry(stations._db.stations()[0])], 0)
        title = find_item(window, "barCover")
        centre = title.mapToScene(QPointF(title.width() / 2, title.height() / 2))
        QTest.mouseClick(window, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                         QPoint(int(centre.x()), int(centre.y())))
        assert wait_for(lambda: window.property("section") == "stations")
        player.stop()
        player.clearQueue()
    del title
    assert not warnings, warnings[:3]


def test_search_finds_stations_and_shows_and_pages_remember_their_scroll(qapp, app_window):
    from conftest import wait_for

    window, objects, warnings = app_window
    with listening_extras(objects):
        search = find_item(window, "searchField")
        search.setProperty("text", "Exceedingly")
        assert wait_for(lambda: window.findChild(QObject, "pageStack").property("currentItem").objectName() == "search")
        page = window.findChild(QObject, "pageStack").property("currentItem")
        assert wait_for(lambda: len(plain(page.property("stationHits"))) == 1)
        search.setProperty("text", "Quite Some Time")
        assert wait_for(lambda: len(plain(page.property("podcastHits"))["shows"]) == 1)
        search.setProperty("text", "")
    # scroll memory: back on a page, it's where it was
    window.resize(1100, 520)
    QMetaObject.invokeMethod(window, "go", Qt.ConnectionType.DirectConnection, Q_ARG("QVariant", "settings"))
    for _ in range(4):
        qapp.processEvents()
    flick = QMetaObject.invokeMethod(window, "flickOf", Qt.ConnectionType.DirectConnection, Q_RETURN_ARG("QVariant"),
                                     Q_ARG("QVariant", window.findChild(QObject, "pageStack").property("currentItem")),
                                     Q_ARG("QVariant", 0))
    flick.setProperty("contentY", 400)
    QMetaObject.invokeMethod(window, "go", Qt.ConnectionType.DirectConnection, Q_ARG("QVariant", "home"))
    QMetaObject.invokeMethod(window, "goBack", Qt.ConnectionType.DirectConnection)

    def scrolled():
        f = QMetaObject.invokeMethod(window, "flickOf", Qt.ConnectionType.DirectConnection, Q_RETURN_ARG("QVariant"),
                                     Q_ARG("QVariant", window.findChild(QObject, "pageStack").property("currentItem")),
                                     Q_ARG("QVariant", 0))
        return f is not None and abs(f.property("contentY") - 400) < 2
    assert wait_for(scrolled, timeout=3)
    window.resize(1100, 1600)
    assert not warnings, warnings[:3]


def test_whats_new_fits_a_short_window(qapp, app_window):
    from conftest import wait_for

    window, objects, warnings = app_window
    shell = objects["shell"]
    old = shell._settings.value("ui/lastVersion", "")
    shell._settings.setValue("ui/lastVersion", "0.0.1")
    try:
        window.resize(900, 520)
        shell.whatsNewChanged.emit()
        dlg = window.findChild(QObject, "whatsNewDialog")
        QMetaObject.invokeMethod(dlg, "open")
        assert wait_for(lambda: dlg.property("opened"))
        assert dlg.property("height") <= window.height()
        QMetaObject.invokeMethod(dlg, "close")
        assert wait_for(lambda: shell.whatsNew == [])
    finally:
        shell._settings.setValue("ui/lastVersion", old)
        shell._whats_new_dismissed = False
    assert not [w for w in warnings if "main.qml" in w], warnings


def test_genres_found_online_are_reviewed_before_saving(qapp, app_window):
    from conftest import wait_for

    window, objects, warnings = app_window
    library, editor = objects["library"], objects["metaEditor"]
    albums = [library.albums.get(i) for i in range(2)]
    editor._genres["proposals"] = [
        {"album_key": a["album_key"], "album": a["album"], "artist": a["album_artist"], "genre": g,
         "genres": [g, "Ambient"], "source": src, "songs": 2}
        for a, g, src in zip(albums, ("Shoegaze", "Folk"), ("album", "artist"))]
    editor.genresChanged.emit()
    QMetaObject.invokeMethod(window, "go", Q_ARG("QVariant", "health"))
    assert wait_for(lambda: window.findChild(QObject, "genreReview") is not None)
    dlg = window.findChild(QObject, "genreReview")
    QMetaObject.invokeMethod(dlg, "open")
    assert wait_for(lambda: dlg.property("opened"))
    assert dlg.property("kept") == 1  # the artist's genre is a guess, so it starts unticked
    saved = []
    editor._run = lambda fn, items: saved.append(items)  # the seeded songs aren't real files to write to
    try:
        QMetaObject.invokeMethod(dlg, "accept")
        assert wait_for(lambda: saved)
    finally:
        del editor._run
    assert saved == [[(albums[0]["album_key"], "Shoegaze")]]
    assert plain(editor.genreProposals) == []
    assert not [w for w in warnings if "GenreReview" in w or "HealthPage" in w], warnings


FEATURE_LABELS = {"liked": "Liked Songs", "folders": "Folders", "stats": "Stats", "history": "History",
                  "recap": "Recap", "visualizer": "Visualizer", "health": "Library health", "lyrics": "Lyrics",
                  "stations": "Internet radio", "podcasts": "Podcasts"}
# Words that only describe something (Settings' notes about offline mode or backups), not a way into the feature.
FEATURE_PROSE = ("folders that can't be found", "folders are scanned", "import history", "import listening history",
                 "no lyrics or cover lookups", "playlists, history, stations", "music's stats")


def visible_texts(window):
    texts = QMetaObject.invokeMethod(window, "visibleTexts", Qt.ConnectionType.DirectConnection,
                                     Q_RETURN_ARG("QVariant"), Q_ARG("QVariant", None))
    return plain(texts) or []


def test_a_switched_off_feature_is_gone_from_every_page(qapp, app_window):
    """Settings → Features promises a switched-off feature "disappears everywhere": no page, link, button or
    heading names it any more."""
    window, objects, warnings = app_window
    shell = objects["shell"]
    pages = ["home", "albums", "artists", "songs", "settings", *FEATURE_LABELS]
    with listening_extras(objects):
        leaks = []
        for feature, label in FEATURE_LABELS.items():
            shell.setFeature(feature, False)
            try:
                for page in pages:
                    QMetaObject.invokeMethod(window, "go", Q_ARG("QVariant", page))
                    for _ in range(20):
                        qapp.processEvents()
                    leaks += [(feature, page, t[:80]) for t in visible_texts(window)
                              if label.lower() in t.lower() and not any(p in t.lower() for p in FEATURE_PROSE)]
            finally:
                shell.setFeature(feature, True)
    assert leaks == []
    assert not [w for w in warnings if "main.qml" in w], warnings


def test_sidebar_entries_are_dragged_into_a_new_order(qapp, app_window):
    from conftest import wait_for
    from PySide6.QtCore import QPoint
    from PySide6.QtTest import QTest

    window, objects, warnings = app_window
    shell = objects["shell"]
    try:
        songs, home = find_item(window, "rail_songs"), find_item(window, "rail_home")
        start = songs.mapToScene(songs.boundingRect().center())
        end = home.mapToScene(home.boundingRect().center())
        x, y0, y1 = int(start.x()), int(start.y()), int(end.y())
        QTest.mousePress(window, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(x, y0))
        for i in range(1, 13):
            QTest.mouseMove(window, QPoint(x, y0 + (y1 - y0) * i // 12), 10)
        QTest.mouseRelease(window, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(x, y1), 10)
        assert wait_for(lambda: shell.sidebarOrder[0] == "songs")
        assert wait_for(lambda: find_item(window, "rail_songs").mapToScene(QPointF(0, 0)).y()
                        < find_item(window, "rail_home").mapToScene(QPointF(0, 0)).y())
        # and the same order is listed in Settings, where it can be reset
        QMetaObject.invokeMethod(window, "go", Q_ARG("QVariant", "settings"))
        assert wait_for(lambda: find_item(window, "sidebarOrder_songs") is not None)
        find_item(window, "resetSidebarOrder").clicked.emit()
        assert wait_for(lambda: shell.sidebarOrder[0] == "home")
    finally:
        shell.resetSidebarOrder()
    assert not [w for w in warnings if "Sidebar" in w or "SettingsPage" in w], warnings


def test_music_servers_section_and_its_add_dialog(qapp, app_window):
    """Switched on, Settings gets a Music servers section; adding one warns about a link that isn't secure."""
    window, objects, warnings = app_window
    shell = objects["shell"]
    from conftest import wait_for

    def go(page):
        QMetaObject.invokeMethod(window, "go", Qt.ConnectionType.DirectConnection, Q_ARG("QVariant", page))
        for _ in range(3):
            qapp.processEvents()

    go("settings")
    assert "settings_servers" not in visible_names(window, "settings_servers")  # off to begin with
    shell.setFeature("servers", True)
    try:
        for _ in range(3):
            qapp.processEvents()
        assert visible_names(window, "settings_servers") and find_item(window, "addServer") is not None
        dlg = window.findChild(QObject, "addServerDialog")
        QMetaObject.invokeMethod(dlg, "open")
        assert wait_for(lambda: dlg.property("opened"), timeout=2)
        assert dlg.property("ready") is False  # OK waits for a link, a user name and a password
        window.findChild(QObject, "serverLink").setProperty("text", "http://music.example.com")
        window.findChild(QObject, "serverUser").setProperty("text", "me")
        window.findChild(QObject, "serverPassword").setProperty("text", "pw")
        assert dlg.property("ready") is True
        assert objects["servers"].linkIsSecure("http://music.example.com") is False
        assert objects["servers"].linkIsSecure("http://192.168.1.4:4533") is True
        QMetaObject.invokeMethod(dlg, "close")
        assert not [w for w in warnings if "SettingsPage" in w or "main.qml" in w], warnings[:3]
    finally:
        shell.setFeature("servers", False)
