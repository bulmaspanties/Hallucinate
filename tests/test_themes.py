import json
from pathlib import Path

import pytest
from conftest import wait_for
from PySide6.QtCore import Q_ARG, QMetaObject, QObject, Qt, QUrl, Signal
from PySide6.QtGui import QColor, QIcon, QImage
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuickControls2 import QQuickStyle

from hallucinate.app import QML_STYLE
from hallucinate.core.db import Database
from hallucinate.discord import DiscordPresence
from hallucinate.library import Library
from hallucinate.lyricsctl import LyricsController
from hallucinate.metaedit import MetadataEditor
from hallucinate.player import Player
from hallucinate.scrobbling import LastFmScrobbler
from hallucinate.shell import DesktopShell
from hallucinate.themes import BUILTIN_THEME_DIR, ThemeManager
from hallucinate.userlib import UserLibrary


class FakePlayer(QObject):
    trackChanged = Signal()

    def __init__(self):
        super().__init__()
        self.current = {}

    def set_art(self, url):
        self.current = {"artUrl": url}
        self.trackChanged.emit()


@pytest.fixture
def manager_factory(qapp, tmp_path):
    old_font = qapp.font()
    instances = []

    def make(config_dir=None, player=None):
        manager = ThemeManager(config_dir or (tmp_path / "config"), player)
        instances.append(manager)
        return manager

    yield make
    for manager in instances:
        manager.deleteLater()
    qapp.setFont(old_font)


def test_builtin_themes_are_complete_and_switch_live(manager_factory):
    manager = manager_factory()
    assert manager.availableThemes == [
        "Ace Pride", "Bi Pride", "Catppuccin Latte", "Catppuccin Mocha", "Dark", "Dracula", "Gruvbox",
        "Hallucinate", "Lesbian Pride", "Light", "Nonbinary Pride", "Nord", "Pan Pride", "Pride", "Ribbon", "Tokyo Night",
        "Trans Pride", "Trans Pride Light",
    ]
    original = manager.bg
    assert manager.selectTheme("Nord")
    assert manager.currentTheme == "Nord"
    assert manager.bg != original
    assert manager.accent == QColor("#88c0d0")
    assert manager.selectTheme("Dark")
    assert manager.bg != original
    assert manager.bg == QColor("#0b0b10")
    for theme_file in BUILTIN_THEME_DIR.glob("*.json"):
        data = json.loads(theme_file.read_text(encoding="utf-8"))
        assert ThemeManager._validate(data)[1]


def test_selection_and_album_accent_preferences_persist(manager_factory, tmp_path):
    config = tmp_path / "preferences"
    manager = manager_factory(config)
    manager.selectTheme("Dracula")
    manager.setAlbumArtAccent(True)
    stored = json.loads((config / "preferences.json").read_text(encoding="utf-8"))
    assert {k: stored[k] for k in ("theme", "album_art_accent")} == {"theme": "Dracula", "album_art_accent": True}

    restored = manager_factory(config)
    assert restored.currentTheme == "Dracula"
    assert restored.albumArtAccent


def test_custom_themes_reload_and_invalid_files_are_ignored(manager_factory, tmp_path):
    config = tmp_path / "config"
    custom_dir = config / "themes"
    custom_dir.mkdir(parents=True)
    custom = json.loads((BUILTIN_THEME_DIR / "dark.json").read_text(encoding="utf-8"))
    custom["name"] = "User Plum"
    custom["colors"]["accent"] = "#b455dd"
    (custom_dir / "plum.json").write_text(json.dumps(custom), encoding="utf-8")
    (custom_dir / "broken.json").write_text("{not json", encoding="utf-8")

    manager = manager_factory(config)
    assert "User Plum" in manager.availableThemes
    assert manager.selectTheme("User Plum")
    assert manager.accent == QColor("#b455dd")
    (custom_dir / "plum.json").unlink()
    manager.reloadThemes()
    assert manager.currentTheme == "Hallucinate"
    assert "User Plum" not in manager.availableThemes


def test_album_art_accent_tracks_current_cover(manager_factory, tmp_path):
    image_path = tmp_path / "cover.png"
    image = QImage(16, 16, QImage.Format.Format_RGB32)
    image.fill(QColor("#ed294a"))
    assert image.save(str(image_path))
    player = FakePlayer()
    player.set_art(image_path.as_uri())
    manager = manager_factory(player=player)
    base_accent = manager.accent
    manager.setAlbumArtAccent(True)
    assert manager.accent != base_accent
    assert manager.accent.red() > 200
    assert manager.accent.blue() > 40
    manager.setAlbumArtAccent(False)
    assert manager.accent == base_accent

    player.set_art("")
    manager.setAlbumArtAccent(True)
    assert manager.accent == base_accent


PRIDE_THEMES = ("Pride", "Trans Pride", "Trans Pride Light", "Bi Pride", "Lesbian Pride", "Nonbinary Pride",
                "Pan Pride", "Ace Pride")


def test_pride_themes_are_readable(manager_factory):
    from hallucinate.themes import contrast

    manager = manager_factory()
    for name in PRIDE_THEMES:
        assert name in manager.availableThemes, name
        assert manager.selectTheme(name)
        assert len(manager.themePalette) >= 3, name
        assert contrast(manager.text, manager.bg) >= 7, name
        for colour in (manager.textDim, manager.accent, manager.error):
            assert contrast(colour, manager.bg) >= 4.5, (name, colour.name())
        assert contrast(manager.textDim, manager.surface) >= 4.5, name
        assert contrast(manager.accent, manager.surface) >= 4.5, name
        assert contrast(manager.onAccent, manager.accent) >= 4.5, name


def test_flag_colours_drive_the_backdrop(manager_factory):
    from hallucinate.themes import contrast

    manager = manager_factory()
    assert manager.selectTheme("Trans Pride")
    def hues():
        return [round(c.hslHueF() * 360) for c in manager.ambientColors]

    assert hues() == [197, 348, 197]  # blue, pink, blue: the white stripe doesn't glow on a dark backdrop
    assert all(contrast(c, QColor("#000000")) < 8.5 for c in manager.ambientColors)  # toned, not glaring
    assert manager.selectTheme("Nonbinary Pride")
    assert hues() == [274, 58, 274]  # purple twice, the bright yellow once
    assert manager.selectTheme("Ace Pride")
    assert {c.name() for c in manager.ambientColors} == {"#800080"}  # black, grey and white are left out
    assert manager.paletteOf("Lesbian Pride")[0] == "#D52D00"
    manager.setAlbumArtAccent(True)  # album colours: the backdrop follows the cover again
    assert manager.ambientColors == []
    manager.setAlbumArtAccent(False)
    assert manager.selectTheme("Dark")
    assert manager.themePalette == [] and manager.ambientColors == []


def test_invalid_palettes_are_rejected(manager_factory, tmp_path):
    from hallucinate.themes import ThemeManager

    base = json.loads((BUILTIN_THEME_DIR / "dark.json").read_text(encoding="utf-8"))
    assert ThemeManager._validate({**base, "palette": ["#ff0000", "#00ff00"]})[1]
    assert not ThemeManager._validate({**base, "palette": "#ff0000"})[1]
    assert not ThemeManager._validate({**base, "palette": ["not a colour"]})[1]
    assert not ThemeManager._validate({**base, "palette": ["#fff"] * 9})[1]


def test_accent_from_a_dark_cover_stays_readable(manager_factory, tmp_path):
    from hallucinate.themes import contrast

    image_path = tmp_path / "dark.png"
    image = QImage(16, 16, QImage.Format.Format_RGB32)
    image.fill(QColor("#3c0b14"))  # a nearly black red sleeve: saturated enough to be picked
    assert image.save(str(image_path))
    player = FakePlayer()
    player.set_art(image_path.as_uri())
    manager = manager_factory(player=player)
    manager.setAlbumArtAccent(True)
    for theme in ("Hallucinate", "Light"):
        assert manager.selectTheme(theme)
        assert manager.accent.red() > manager.accent.blue()  # still the cover's colour
        assert contrast(manager.accent, manager.bg) >= 4.5, (theme, manager.accent.name())


def test_settings_theme_switcher_updates_the_live_window(qapp, tmp_path, monkeypatch):
    from hallucinate import scrobbling
    from hallucinate.listenbrainz import ListenBrainzScrobbler

    monkeypatch.setattr(scrobbling.keyring, "get_password", lambda *_: None)
    monkeypatch.setattr(scrobbling.keyring, "set_password", lambda *_: None)
    monkeypatch.setattr(scrobbling.keyring, "delete_password", lambda *_: None)
    QQuickStyle.setStyle(QML_STYLE)
    old_font = qapp.font()
    config_dir = tmp_path / "config"
    user_themes = config_dir / "themes"
    user_themes.mkdir(parents=True)
    custom_theme = json.loads((BUILTIN_THEME_DIR / "dark.json").read_text(encoding="utf-8"))
    custom_theme["name"] = "Font Test"
    custom_theme["fonts"] = {"family": "DejaVu Sans", "scale": 1.2}
    (user_themes / "font-test.json").write_text(json.dumps(custom_theme), encoding="utf-8")
    # A song with plays, so the Stats page has top artists and albums to draw
    seed = Database(tmp_path / "library.db")
    seed.upsert_track({
        "path": str(tmp_path / "song.flac"), "mtime": 0, "size": 1, "title": "Song", "artist": "Seeded Artist",
        "album_artist": "Seeded Artist", "aa_tag": 1, "album": "Seeded Album", "album_key": "seeded", "track_no": 1,
        "disc_no": 0, "year": 2000, "genre": "", "duration": 200.0, "fmt": "FLAC", "codec": "FLAC", "bitrate": 0,
        "sample_rate": 44100,
    })
    seed.commit()
    for _ in range(3):
        seed.record_play(str(tmp_path / "song.flac"))
    seed.close()
    library = Library(tmp_path / "library.db", tmp_path / "art")
    player = Player(session_file=tmp_path / "session.json")
    scrobbler = LastFmScrobbler(player, tmp_path / "data")
    manager = ThemeManager(config_dir, player)
    engine = QQmlApplicationEngine()
    context = engine.rootContext()
    context.setContextProperty("library", library)
    user_lib = UserLibrary(tmp_path / "library.db", player)
    context.setContextProperty("userLib", user_lib)
    listenbrainz = ListenBrainzScrobbler(player, tmp_path / "data", user_lib)
    context.setContextProperty("listenbrainz", listenbrainz)
    meta_editor = MetadataEditor(tmp_path / "library.db", tmp_path / "art")
    lyrics = LyricsController(tmp_path / "library.db", player)
    context.setContextProperty("metaEditor", meta_editor)
    from hallucinate.replaygain import ReplayGainAnalyzer

    replay_gain = ReplayGainAnalyzer(tmp_path / "library.db")
    context.setContextProperty("replayGain", replay_gain)
    from hallucinate.headphones import HeadphoneFinder

    headphone_finder = HeadphoneFinder(tmp_path / "cache", player)
    context.setContextProperty("headphones", headphone_finder)
    context.setContextProperty("lyricsCtl", lyrics)
    shell = DesktopShell(qapp, player, QIcon())
    context.setContextProperty("shell", shell)
    discord = DiscordPresence(player)
    context.setContextProperty("discord", discord)
    context.setContextProperty("player", player)
    context.setContextProperty("scrobbler", scrobbler)
    context.setContextProperty("themeManager", manager)
    from hallucinate.stations import Stations

    stations = Stations(tmp_path / "streams.db", tmp_path / "cache", player)
    context.setContextProperty("stations", stations)
    from hallucinate.podcasts import Podcasts

    podcasts = Podcasts(tmp_path / "streams.db", tmp_path / "data", tmp_path / "cache", player)
    context.setContextProperty("podcasts", podcasts)
    from hallucinate.servers import Servers

    servers = Servers(tmp_path / "lib.db", tmp_path / "art", player)
    context.setContextProperty("servers", servers)
    qml_dir = Path(__file__).parents[1] / "hallucinate" / "qml"
    engine.addImportPath(str(qml_dir))
    qml_warnings = []
    engine.warnings.connect(lambda warnings: qml_warnings.extend(str(warning) for warning in warnings))
    engine.load(QUrl.fromLocalFile(str(qml_dir / "main.qml")))
    assert engine.rootObjects()
    window = engine.rootObjects()[0]
    assert QMetaObject.invokeMethod(window, "go", Qt.ConnectionType.DirectConnection, Q_ARG("QVariant", "settings"))
    qapp.processEvents()
    picker = window.findChild(QObject, "themePicker")
    picker_text = window.findChild(QObject, "themePickerText")
    assert picker is not None
    assert picker_text is not None
    device_picker = window.findChild(QObject, "outputDevice")
    assert device_picker is not None
    assert device_picker.property("count") == len(player.outputDevices)
    assert device_picker.property("currentIndex") == 0
    # Settings search: only sections with a match stay
    settings_search = window.findChild(QObject, "settingsSearch")
    sound, appearance = window.findChild(QObject, "settings_sound"), window.findChild(QObject, "settings_appearance")
    assert sound.property("visible") and appearance.property("visible")
    settings_search.setProperty("text", "crossfeed")
    qapp.processEvents()
    assert sound.property("visible") and not appearance.property("visible")
    settings_search.setProperty("text", "musicbee")  # matched by the text of a control, not just keywords
    qapp.processEvents()
    assert window.findChild(QObject, "settings_library").property("visible") and not sound.property("visible")
    settings_search.setProperty("text", "")
    qapp.processEvents()
    assert sound.property("visible") and appearance.property("visible")
    del settings_search, sound, appearance

    assert manager.selectTheme("Font Test")
    from PySide6.QtTest import QTest

    QTest.qWait(300)
    assert window.property("color") == manager.bg
    assert picker.property("currentText") == "Font Test"
    assert picker.property("currentIndex") == manager.availableThemes.index("Font Test")
    assert picker_text.property("font").family() == "DejaVu Sans"
    assert picker_text.property("font").pixelSize() == 17

    for section in ("home", "albums", "artists", "songs", "stats", "history", "visualizer", "settings"):
        assert QMetaObject.invokeMethod(window, "go", Qt.ConnectionType.DirectConnection, Q_ARG("QVariant", section))
        qapp.processEvents()
    # Stats: the top artist and album rows are themed (a broken binding leaves them white)
    assert QMetaObject.invokeMethod(window, "go", Qt.ConnectionType.DirectConnection, Q_ARG("QVariant", "stats"))
    assert wait_for(lambda: user_lib.topArtists.count > 0 and user_lib.topAlbums.count > 0)
    qapp.processEvents()
    stats_page = window.findChild(QObject, "stats")

    def item_named(item, name):  # Repeater rows are only reachable through the visual tree
        if item.objectName() == name:
            return item
        return next((found for child in item.childItems() if (found := item_named(child, name))), None)

    for name in ("statsTopArtist", "statsTopAlbum"):
        row = item_named(stats_page, name)
        assert row is not None, name
        assert row.property("color") == manager.surface, (name, row.property("color"))
    del row, stats_page
    # Multi-select: Ctrl+click a song, the selection bar appears and acts on it; Esc clears it
    from PySide6.QtCore import QPoint
    from PySide6.QtTest import QTest

    assert QMetaObject.invokeMethod(window, "go", Qt.ConnectionType.DirectConnection, Q_ARG("QVariant", "songs"))
    def visible_row(item):
        if not item.isVisible():
            return None
        if item.objectName() == "trackRow" and item.width() > 0:
            return item
        return next((found for child in item.childItems() if (found := visible_row(child))), None)

    song_row = wait_for(lambda content=window.contentItem(): visible_row(content))
    assert song_row is not None
    selection_bar = window.findChild(QObject, "selectionBar")
    assert not selection_bar.property("shown")
    centre = song_row.mapToScene(song_row.boundingRect().center())
    QTest.mouseClick(window, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.ControlModifier,
                     QPoint(int(centre.x()), int(centre.y())))
    assert wait_for(lambda bar=selection_bar: bar.property("shown"))
    assert song_row.property("selected")
    assert item_named(selection_bar, "selectionCount").property("text") == "1 song selected"
    QTest.keyClick(window, Qt.Key.Key_Escape)
    assert wait_for(lambda bar=selection_bar: not bar.property("shown"))
    del song_row, selection_bar
    assert QMetaObject.invokeMethod(window, "go", Qt.ConnectionType.DirectConnection, Q_ARG("QVariant", "history"))
    qapp.processEvents()
    for name in ("historyList", "historyHeatmap", "historySummary", "historySearch"):
        assert window.findChild(QObject, name) is not None, name
    assert QMetaObject.invokeMethod(window, "openArtist", Qt.ConnectionType.DirectConnection, Q_ARG("QVariant", "Someone"))
    qapp.processEvents()
    assert window.findChild(QObject, "artistListening") is not None
    assert QMetaObject.invokeMethod(window, "go", Qt.ConnectionType.DirectConnection, Q_ARG("QVariant", "recap"))
    qapp.processEvents()
    assert window.findChild(QObject, "recapCard") is not None
    assert QMetaObject.invokeMethod(window, "go", Qt.ConnectionType.DirectConnection, Q_ARG("QVariant", "folders"))
    qapp.processEvents()
    assert window.findChild(QObject, "folders") is not None
    # Library health and the command palette
    assert QMetaObject.invokeMethod(window, "go", Qt.ConnectionType.DirectConnection, Q_ARG("QVariant", "health"))
    qapp.processEvents()
    assert window.findChild(QObject, "healthScore") is not None
    palette = window.findChild(QObject, "commandPalette")
    assert QMetaObject.invokeMethod(palette, "show")
    qapp.processEvents()
    field = window.findChild(QObject, "paletteField")
    field.setProperty("text", "hist")
    assert QMetaObject.invokeMethod(palette, "rebuild")
    results = palette.property("results").toVariant()
    assert results and results[0]["t"] == "History"
    assert QMetaObject.invokeMethod(palette, "runCurrent")
    qapp.processEvents()
    assert window.property("section") == "history"
    # Albums three ways, and an album's sleeve page
    for view in ("colour", "timeline", "grid"):
        shell.setUiValue("albumsView", view)
        assert QMetaObject.invokeMethod(window, "go", Qt.ConnectionType.DirectConnection, Q_ARG("QVariant", "albums"))
        qapp.processEvents()
    assert QMetaObject.invokeMethod(window, "openAlbum", Qt.ConnectionType.DirectConnection, Q_ARG("QVariant", "x|y"))
    qapp.processEvents()
    # Visualizer: with the software renderer the shader styles fall back to bars
    assert QMetaObject.invokeMethod(window, "go", Qt.ConnectionType.DirectConnection, Q_ARG("QVariant", "visualizer"))
    qapp.processEvents()
    for style in ("aurora", "bars", "liquid"):
        shell.setVisualizerStyle(style)
        qapp.processEvents()
        page_vis = window.findChild(QObject, "pageVisualizer")
        assert page_vis.property("style") == style and not page_vis.property("shaderStyle")
        assert page_vis.findChild(QObject, "visualizerShader") is None  # no shader under the software renderer
    # Now Playing opens over everything and closes again
    now_playing = window.findChild(QObject, "nowPlayingView")
    assert not now_playing.property("open")
    window.findChild(QObject, "openNowPlaying").clicked.emit()
    qapp.processEvents()
    assert now_playing.property("open")
    now_playing.setProperty("lyricsMode", True)
    # the view fades in, and its children count as visible from the first animation tick
    lyrics_box = window.findChild(QObject, "nowPlayingLyrics")
    assert wait_for(lambda: lyrics_box.property("visible"))
    now_playing.setProperty("lyricsMode", False)
    shell.setNowPlayingVinyl(True)
    qapp.processEvents()
    assert window.findChild(QObject, "vinylRecord").property("x") >= 0
    shell.setNowPlayingVinyl(False)
    window.findChild(QObject, "closeNowPlaying").clicked.emit()
    qapp.processEvents()
    assert not now_playing.property("open")
    assert QMetaObject.invokeMethod(window, "go", Qt.ConnectionType.DirectConnection, Q_ARG("QVariant", "settings"))
    qapp.processEvents()
    window.setProperty("queueOpen", True)
    qapp.processEvents()
    assert window.findChild(QObject, "saveQueue") is not None
    assert window.findChild(QObject, "sidebarToggle") is not None
    for name in ("randomAlbum", "listeningCard", "formatsTile", "librarySummary"):
        assert window.findChild(QObject, name) is not None, name
    shell.setSidebarCollapsed(True)  # icon rail with the playlists menu
    qapp.processEvents()
    shell.setSidebarCollapsed(False)
    qapp.processEvents()

    # Smart playlist editor: create one from the default rule, then reopen it for editing.
    editor = window.findChild(QObject, "smartEditor")
    assert QMetaObject.invokeMethod(editor, "openNew", Qt.ConnectionType.DirectConnection)
    qapp.processEvents()
    window.findChild(QObject, "smartName").setProperty("text", "Loved")
    assert window.findChild(QObject, "smartPreview").property("text").startswith("Liked is yes")
    assert QMetaObject.invokeMethod(editor, "accept", Qt.ConnectionType.DirectConnection)
    assert wait_for(lambda: user_lib.smartPlaylists.count == 1)
    smart_id = user_lib.smartPlaylists.get(0)["id"]
    qapp.processEvents()
    assert window.property("section") == f"smart{smart_id}"
    assert QMetaObject.invokeMethod(editor, "openEdit", Qt.ConnectionType.DirectConnection,
                                    Q_ARG("QVariant", smart_id), Q_ARG("QVariant", "Loved"))
    qapp.processEvents()
    assert window.findChild(QObject, "smartName").property("text") == "Loved"
    assert QMetaObject.invokeMethod(editor, "reject", Qt.ConnectionType.DirectConnection)
    qapp.processEvents()
    assert QMetaObject.invokeMethod(window, "showSearch", Qt.ConnectionType.DirectConnection)
    qapp.processEvents()
    # First-run welcome: closed unless the app marked this a fresh install; three steps, then home
    welcome = window.findChild(QObject, "welcome")
    assert not welcome.property("open")
    shell.setUiValue("welcome", "1")
    welcome.setProperty("open", True)
    welcome_next = window.findChild(QObject, "welcomeNext")
    for step in (1, 2):
        welcome_next.clicked.emit()
        qapp.processEvents()
        assert welcome.property("step") == step
    theme_tiles = window.findChild(QObject, "welcomeThemes")
    assert theme_tiles is not None and theme_tiles.property("columns") == 3
    welcome_next.clicked.emit()
    qapp.processEvents()
    assert not welcome.property("open") and shell.uiValue("welcome", "") == "0"
    assert window.property("section") == "home"
    del welcome, welcome_next, theme_tiles
    assert not qml_warnings

    window.close()
    del editor, device_picker, picker_text, picker, window, engine
    qapp.processEvents()
    scrobbler.shutdown()
    listenbrainz.shutdown()
    player.shutdown()
    lyrics.shutdown()
    stations.shutdown()
    podcasts.shutdown()
    meta_editor.shutdown()
    replay_gain.shutdown()
    headphone_finder.shutdown()
    user_lib.shutdown()
    library.shutdown()
    qapp.setFont(old_font)


def test_your_own_accent_system_mode_and_themes(manager_factory, tmp_path, monkeypatch):
    from hallucinate.themes import contrast

    manager = manager_factory()
    assert "Ribbon" in manager.availableThemes
    assert manager.selectTheme("Ribbon")
    assert contrast(manager.accent, manager.bg) >= 4.5 and contrast(manager.onAccent, manager.accent) >= 4.5
    # an accent of your own, over any theme, kept readable
    manager.setAccentOverride("#2ec4b6")
    assert manager.accentOverride == "#2ec4b6" and contrast(manager.accent, manager.bg) >= 4.5
    manager.setAccentOverride("not a colour")
    assert manager.accentOverride == "#2ec4b6"
    again = manager_factory(tmp_path / "config")
    assert again.accentOverride == "#2ec4b6"  # remembered
    manager.setAccentOverride("")
    assert manager.accent == QColor(json.loads((BUILTIN_THEME_DIR / "ribbon.json").read_text())["colors"]["accent"])

    # light and dark following the system
    monkeypatch.setattr(ThemeManager, "system_is_dark", lambda self: False)
    manager.setSystemThemes("Light", "Nord")
    manager.setFollowSystem(True)
    assert manager.currentTheme == "Light"
    monkeypatch.setattr(ThemeManager, "system_is_dark", lambda self: True)
    manager._apply_system_scheme()
    assert manager.currentTheme == "Nord"
    manager.setFollowSystem(False)

    # a theme of your own
    assert manager.saveCustomTheme("Hallucinate", {}) != ""  # a built-in's name
    assert manager.saveCustomTheme("Late Night", {"accent": "#ff9f43", "bg": "#050507"}) == ""
    assert manager.currentTheme == "Late Night" and manager.bg == QColor("#050507")
    saved = json.loads((tmp_path / "config" / "themes" / "late-night.json").read_text())
    assert saved["name"] == "Late Night" and saved["colors"]["accent"] == "#ff9f43"
