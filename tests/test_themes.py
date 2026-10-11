import json
from pathlib import Path

import pytest
from conftest import wait_for
from PySide6.QtCore import Q_ARG, QMetaObject, QObject, Qt, QUrl, Signal
from PySide6.QtGui import QColor, QIcon, QImage
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuickControls2 import QQuickStyle

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
        "Catppuccin Latte", "Catppuccin Mocha", "Dark", "Dracula", "Gruvbox",
        "Hallucinate", "Light", "Nord", "Tokyo Night",
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
    assert stored == {"theme": "Dracula", "album_art_accent": True}

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


def test_settings_theme_switcher_updates_the_live_window(qapp, tmp_path, monkeypatch):
    from hallucinate import scrobbling
    from hallucinate.listenbrainz import ListenBrainzScrobbler

    monkeypatch.setattr(scrobbling.keyring, "get_password", lambda *_: None)
    monkeypatch.setattr(scrobbling.keyring, "set_password", lambda *_: None)
    monkeypatch.setattr(scrobbling.keyring, "delete_password", lambda *_: None)
    QQuickStyle.setStyle("Basic")
    old_font = qapp.font()
    config_dir = tmp_path / "config"
    user_themes = config_dir / "themes"
    user_themes.mkdir(parents=True)
    custom_theme = json.loads((BUILTIN_THEME_DIR / "dark.json").read_text(encoding="utf-8"))
    custom_theme["name"] = "Font Test"
    custom_theme["fonts"] = {"family": "DejaVu Sans", "scale": 1.2}
    (user_themes / "font-test.json").write_text(json.dumps(custom_theme), encoding="utf-8")
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
    context.setContextProperty("lyricsCtl", lyrics)
    shell = DesktopShell(qapp, player, QIcon())
    context.setContextProperty("shell", shell)
    discord = DiscordPresence(player)
    context.setContextProperty("discord", discord)
    context.setContextProperty("player", player)
    context.setContextProperty("scrobbler", scrobbler)
    context.setContextProperty("themeManager", manager)
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
    assert QMetaObject.invokeMethod(window, "go", Qt.ConnectionType.DirectConnection, Q_ARG("QVariant", "history"))
    qapp.processEvents()
    for name in ("historyList", "historyHeatmap", "historySummary", "historySearch"):
        assert window.findChild(QObject, name) is not None, name
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
    assert not qml_warnings

    window.close()
    del editor, device_picker, picker_text, picker, window, engine
    qapp.processEvents()
    scrobbler.shutdown()
    listenbrainz.shutdown()
    player.shutdown()
    lyrics.shutdown()
    meta_editor.shutdown()
    user_lib.shutdown()
    library.shutdown()
    qapp.setFont(old_font)
