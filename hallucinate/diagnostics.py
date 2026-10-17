"""Debug info for bug reports: versions, platform, display, audio, settings and the recent log.

Personal details are left out on purpose, since the text usually ends up in a public issue: links, song files,
the music folders and the home folder (with the user name) are taken out of every line (`_redact`), and the
lines that would name an album, song or station don't name it in the first place."""
import collections
import logging
import os
import platform
import re
import sys
import time

from . import __version__

LOG_LINES = 200
_log = collections.deque(maxlen=LOG_LINES)
_installed = False


class _RingHandler(logging.Handler):
    def emit(self, record):
        try:
            _log.append(f"{time.strftime('%H:%M:%S', time.localtime(record.created))} "
                        f"{record.levelname[0]} {record.name}: {record.getMessage()}")
        except Exception:  # noqa: BLE001 - logging must never raise
            pass


_private_folders = []  # the music folders: song paths under them say what's in the library
_AUDIO = r"(?:flac|mp3|m4a|m4b|mp4|aac|alac|ogg|oga|opus|wav|wv|aif|aiff|ape|mpc|dsf|dff|wma|cue|lrc|m3u8?|pls)"
_LINK = re.compile(r"\b(?:https?|ftp|file)://[^\s'\"<>]*[^\s'\"<>.,;:!?)\]]", re.I)  # not a trailing comma
# a path to an audio file, spaces and all: from a drive letter or a slash up to the file's extension
_AUDIO_PATH = re.compile(r"(?:[A-Za-z]:[\\/]|[\\/]|~[\\/])[^\n\"'<>|]*?\." + _AUDIO + r"\b(?:#\d+)?", re.I)


def set_private_folders(folders):
    """The music folders, to be hidden in reports along with everything under them."""
    _private_folders[:] = sorted((str(f) for f in folders if f and len(str(f)) > 1), key=len, reverse=True)


def _redact(text):
    """Take out of a log line what could say who you are or what you listen to: links (they can carry names,
    tokens or a station you play), song files and the music folders, and the home folder (the user name)."""
    text = _LINK.sub("<link>", str(text))
    text = _AUDIO_PATH.sub("<song file>", text)
    for folder in _private_folders:
        text = text.replace(folder, "<music folder>")
    home = os.path.expanduser("~")
    return text.replace(home, "~") if home and home not in ("/", "~") else text


def install():
    """Keep the last LOG_LINES log records and Qt/QML warnings in memory for `report()`."""
    global _installed
    if _installed:
        return
    _installed = True
    handler = _RingHandler(logging.INFO)
    logging.getLogger().addHandler(handler)
    if logging.getLogger().level > logging.INFO or logging.getLogger().level == logging.NOTSET:
        logging.getLogger().setLevel(logging.INFO)
    from PySide6.QtCore import QtMsgType, qInstallMessageHandler

    levels = {QtMsgType.QtDebugMsg: "D", QtMsgType.QtInfoMsg: "I", QtMsgType.QtWarningMsg: "W",
              QtMsgType.QtCriticalMsg: "E", QtMsgType.QtFatalMsg: "F"}

    def on_qt_message(kind, _context, message):
        if kind != QtMsgType.QtDebugMsg:
            _log.append(f"{time.strftime('%H:%M:%S')} {levels.get(kind, '?')} qt: {message}")
        if kind == QtMsgType.QtFatalMsg:
            from . import crashlog

            crashlog.record_fatal(message)
        if sys.stderr is not None:  # keep Qt's own output on the console
            print(message, file=sys.stderr)

    qInstallMessageHandler(on_qt_message)


def recent_log():
    return [_redact(line) for line in _log]


def _install_kind():
    if os.environ.get("FLATPAK_ID"):
        return "Flatpak"
    if os.environ.get("APPIMAGE"):
        return "AppImage"
    if getattr(sys, "frozen", False):
        return "Windows build" if sys.platform == "win32" else "macOS app" if sys.platform == "darwin" else "bundle"
    return "Python package"


def _os_name():
    if sys.platform.startswith("linux"):
        try:
            info = platform.freedesktop_os_release()
            return f"{info.get('PRETTY_NAME') or info.get('NAME', 'Linux')} (kernel {platform.release()})"
        except (OSError, AttributeError):
            return f"Linux {platform.release()}"
    if sys.platform == "win32":
        return f"Windows {platform.release()} (build {platform.version()})"
    if sys.platform == "darwin":
        return f"macOS {platform.mac_ver()[0]} ({platform.machine()})"
    return platform.platform()


def report(player=None, library=None, theme_manager=None, window=None):
    """The debug info as plain text, ready to paste into an issue."""
    import PySide6
    from PySide6 import QtCore
    from PySide6.QtGui import QGuiApplication

    lines = [f"Hallucinate {__version__} ({_install_kind()})",
             f"OS: {_os_name()}",
             f"Python {platform.python_version()}, PySide6 {PySide6.__version__}, Qt {QtCore.qVersion()}"]
    app = QGuiApplication.instance()
    if app is not None:
        session = os.environ.get("XDG_CURRENT_DESKTOP") or os.environ.get("DESKTOP_SESSION") or ""
        wayland = " on Wayland" if os.environ.get("WAYLAND_DISPLAY") else ""
        lines.append(f"Display: {app.platformName()}{wayland}" + (f", {session}" if session else ""))
        for screen in app.screens():
            size = screen.size()
            lines.append(f"  Screen {screen.name() or '?'}: {size.width()}x{size.height()} logical, "
                         f"scale {screen.devicePixelRatio():g}")
    if window is not None:
        try:
            from PySide6.QtQuick import QQuickWindow

            api = QQuickWindow.graphicsApi()
            lines.append(f"Window: {window.width()}x{window.height()}, graphics {api.name if hasattr(api, 'name') else api}")
        except Exception:  # noqa: BLE001
            pass
    if player is not None:
        try:
            device = player._output_audio_device()
            fmt = device.preferredFormat()
            lines.append("Audio output: " + ("none" if device.isNull() else
                         f"{device.description()} ({fmt.sampleRate()} Hz, {fmt.channelCount()} ch)")
                         + (" [chosen in Settings]" if player.outputDevice else " [system default]"))
        except Exception:  # noqa: BLE001
            lines.append("Audio output: unknown")
        lines.append(f"Playback: ReplayGain {player.replayGainMode}, crossfade {player.crossfade:g} s, "
                     f"speed {player.speed:g}x, equalizer {'on' if player.eqEnabled else 'off'}"
                     + (f" ({player.eqPreset})" if player.eqEnabled else "")
                     + (f", headphone profile {player.headphoneName}" if player.headphoneName else ""))
        lines.append(f"Visualizer: {'on' if player.visualizerEnabled else 'off'}"
                     f" ({'available' if player.visualizerAvailable else 'unavailable'})")
        if player.error:
            lines.append(f"Player error: {_redact(player.error)}")
    if library is not None:
        lines.append(f"Library: {library.trackCount} songs, {len(library.folders)} folder(s), "
                     f"{len(library.missingFolders)} missing, {library.unreadableFiles} unreadable files")
    if theme_manager is not None:
        lines.append(f"Theme: {theme_manager.currentTheme}"
                     + (", album colours" if theme_manager.albumArtAccent else ""))
    env = [k for k in ("QT_QPA_PLATFORM", "QSG_RHI_BACKEND", "QT_SCALE_FACTOR", "QT_MEDIA_BACKEND") if os.environ.get(k)]
    if env:
        lines.append("Environment: " + ", ".join(f"{k}={os.environ[k]}" for k in env))
    log = recent_log()
    lines.append("")
    lines.append(f"Recent log ({len(log)} lines):" if log else "Recent log: empty")
    lines += log[-80:]
    return "\n".join(lines)
