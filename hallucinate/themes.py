"""File-backed application themes and album-art accent extraction."""
import json
import logging
import math
import os
from collections import Counter
from pathlib import Path

from PySide6.QtCore import Property, QObject, QSize, QUrl, Signal, Slot
from PySide6.QtGui import QColor, QFont, QGuiApplication, QImageReader

logger = logging.getLogger(__name__)
COLOR_KEYS = ("bg", "panel", "surface", "surfaceHi", "border", "text", "textDim", "accent", "error", "onAccent")
BUILTIN_THEME_DIR = Path(__file__).with_name("themes")


DEFAULT_THEME = "Hallucinate"


def art_palette(path, count=3):
    """Up to `count` dominant, reasonably saturated colours of an image, most common first.

    Colours closer than ~40 degrees of hue to an earlier pick are skipped so the palette has some range."""
    reader = QImageReader(path)
    reader.setScaledSize(QSize(32, 32))  # decoders like JPEG downscale while decoding: cheap even for big covers
    image = reader.read()
    if image.isNull():
        return []
    counts = Counter()
    for y in range(image.height()):
        for x in range(image.width()):
            color = image.pixelColor(x, y)
            if color.saturationF() >= 0.28 and 0.18 <= color.valueF() <= 0.98:
                counts[(color.red() // 16, color.green() // 16, color.blue() // 16)] += 1
    picks = []
    for (red, green, blue), _n in counts.most_common():
        color = QColor(min(255, red * 16 + 8), min(255, green * 16 + 8), min(255, blue * 16 + 8))
        hue = color.hsvHueF()
        if all(min(abs(hue - p.hsvHueF()), 1 - abs(hue - p.hsvHueF())) > 0.11 for p in picks):
            picks.append(color)
            if len(picks) == count:
                break
    return picks


class ThemeManager(QObject):
    themeChanged = Signal()
    themesChanged = Signal()
    artColorsChanged = Signal()

    def __init__(self, config_dir, player=None, parent=None):
        super().__init__(parent)
        self._config_dir = Path(config_dir)
        self._user_theme_dir = self._config_dir / "themes"
        self._preferences_path = self._config_dir / "preferences.json"
        self._themes = {}
        self._current_name = DEFAULT_THEME
        self._album_art_accent = False
        self._album_accent = None
        self._art_colors = []
        self._current_art_url = ""
        self._player = player
        app = QGuiApplication.instance()
        self._base_font_size = app.font().pointSizeF() if app is not None else 10.0
        self._load_themes()
        self._load_preferences()
        self._apply_global_font()
        if player is not None:
            player.trackChanged.connect(self._on_track_changed)
            self._on_track_changed()

    def _load_themes(self):
        themes = {}
        for directory, source in ((BUILTIN_THEME_DIR, "built-in"), (self._user_theme_dir, "user")):
            if source == "user":
                try:
                    directory.mkdir(parents=True, exist_ok=True)
                except OSError as exc:
                    logger.warning("Could not create user theme directory %s: %s", directory, exc)
                    continue
            if not directory.is_dir():
                continue
            for path in sorted(directory.glob("*.json")):
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                    name, valid = self._validate(data)
                    if not valid:
                        raise ValueError("theme has invalid fields or color values")
                    if name in themes:
                        logger.warning("Ignoring duplicate %s theme %s from %s", source, name, path)
                        continue
                    themes[name] = data
                except (OSError, UnicodeError, json.JSONDecodeError, ValueError, TypeError) as exc:
                    logger.warning("Ignoring invalid %s theme %s: %s", source, path, exc)
        if "Dark" not in themes:
            raise RuntimeError("The built-in Dark theme is missing or invalid")
        self._themes = themes
        if self._current_name not in themes:
            self._current_name = DEFAULT_THEME if DEFAULT_THEME in themes else "Dark"
        self.themesChanged.emit()
        self.themeChanged.emit()

    @staticmethod
    def _validate(data):
        if not isinstance(data, dict) or not isinstance(data.get("name"), str) or not data["name"].strip():
            return "", False
        colors = data.get("colors")
        if not isinstance(colors, dict) or any(not isinstance(colors.get(k), str) or not QColor(colors[k]).isValid() for k in COLOR_KEYS):
            return data["name"].strip(), False
        radius = data.get("radius")
        fonts = data.get("fonts")
        if type(radius) is not int or not 0 <= radius <= 32 or not isinstance(fonts, dict):
            return data["name"].strip(), False
        family = fonts.get("family")
        scale = fonts.get("scale")
        if (not isinstance(family, str) or not family.strip() or isinstance(scale, bool)
                or not isinstance(scale, (int, float)) or not math.isfinite(scale) or not 0.75 <= scale <= 1.5):
            return data["name"].strip(), False
        return data["name"].strip(), True

    def _load_preferences(self):
        try:
            preferences = json.loads(self._preferences_path.read_text(encoding="utf-8"))
            if not isinstance(preferences, dict):
                raise ValueError("theme preferences must be an object")
            name = preferences.get("theme")
            if isinstance(name, str) and name in self._themes:
                self._current_name = name
            self._album_art_accent = preferences.get("album_art_accent") is True
        except FileNotFoundError:
            return
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
            logger.warning("Could not load theme preferences from %s: %s", self._preferences_path, exc)

    def _save_preferences(self):
        try:
            self._config_dir.mkdir(parents=True, exist_ok=True)
            temporary = self._preferences_path.with_suffix(".tmp")
            temporary.write_text(json.dumps({
                "theme": self._current_name,
                "album_art_accent": self._album_art_accent,
            }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            os.replace(temporary, self._preferences_path)
        except OSError:
            logger.exception("Could not save theme preferences to %s", self._preferences_path)

    def _theme(self):
        return self._themes[self._current_name]

    def _apply_global_font(self):
        app = QGuiApplication.instance()
        if app is not None:
            font = QFont(self.fontFamily)
            font.setPointSizeF(max(1.0, self._base_font_size * self.fontScale))
            app.setFont(font)

    def _on_track_changed(self):
        track = self.sender() or self._player
        if track is None:
            return
        try:
            self._current_art_url = str(track.current.get("artUrl", "") or "")
        except (AttributeError, TypeError):
            self._current_art_url = ""
        self._update_album_accent()

    def _update_album_accent(self):
        url = QUrl(self._current_art_url)
        local_path = url.toLocalFile() if url.isLocalFile() else self._current_art_url
        colors = art_palette(local_path) if local_path else []
        if colors != self._art_colors:
            self._art_colors = colors
            self.artColorsChanged.emit()
        accent = colors[0] if self._album_art_accent and colors else None
        if accent != self._album_accent:
            self._album_accent = accent
            self.themeChanged.emit()

    @Property("QVariantList", notify=artColorsChanged)
    def artColors(self):
        """Dominant colours of the current track's cover (empty without art); drives the ambient backdrop."""
        return list(self._art_colors)

    @Property("QStringList", notify=themesChanged)
    def availableThemes(self):
        return sorted(self._themes, key=str.casefold)

    @Property(str, notify=themeChanged)
    def currentTheme(self):
        return self._current_name

    @Property(bool, notify=themeChanged)
    def albumArtAccent(self):
        return self._album_art_accent

    @Property(str, notify=themeChanged)
    def fontFamily(self):
        return self._theme()["fonts"]["family"]

    @Property(float, notify=themeChanged)
    def fontScale(self):
        return float(self._theme()["fonts"]["scale"])

    @Property(int, notify=themeChanged)
    def radius(self):
        return self._theme()["radius"]

    @Property(str, notify=themesChanged)
    def userThemeDirectory(self):
        return str(self._user_theme_dir)

    @Property(int, notify=themeChanged)
    def sidebarWidth(self):
        return 210

    @Property(int, notify=themeChanged)
    def playerHeight(self):
        return 92

    def _color(self, name):
        if name == "accent" and self._album_accent is not None:
            return self._album_accent
        if name == "accentHi":
            return self._color("accent").lighter(115)
        if name == "onAccent" and self._album_accent is not None:
            color = self._album_accent
            luminance = 0.2126 * color.redF() + 0.7152 * color.greenF() + 0.0722 * color.blueF()
            return QColor("#101014" if luminance > 0.48 else "#ffffff")
        return QColor(self._theme()["colors"][name])

    def _color_property(name, changed):
        return Property(QColor, lambda self: self._color(name), notify=changed)

    bg = _color_property("bg", themeChanged)
    panel = _color_property("panel", themeChanged)
    surface = _color_property("surface", themeChanged)
    surfaceHi = _color_property("surfaceHi", themeChanged)
    border = _color_property("border", themeChanged)
    text = _color_property("text", themeChanged)
    textDim = _color_property("textDim", themeChanged)
    accent = _color_property("accent", themeChanged)
    accentHi = _color_property("accentHi", themeChanged)
    error = _color_property("error", themeChanged)
    onAccent = _color_property("onAccent", themeChanged)

    @Slot(str, result=bool)
    def selectTheme(self, name):
        if name not in self._themes or name == self._current_name:
            return name == self._current_name
        self._current_name = name
        self._album_accent = None
        self._update_album_accent()
        self._apply_global_font()
        self._save_preferences()
        self.themeChanged.emit()
        return True

    @Slot(bool)
    def setAlbumArtAccent(self, enabled):
        enabled = bool(enabled)
        if enabled == self._album_art_accent:
            return
        self._album_art_accent = enabled
        self._update_album_accent()
        self._save_preferences()
        self.themeChanged.emit()

    @Slot()
    def reloadThemes(self):
        previous = self._current_name
        self._load_themes()
        self._apply_global_font()
        if previous != self._current_name:
            self._save_preferences()
