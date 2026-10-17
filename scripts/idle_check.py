"""Measure how much CPU Hallucinate uses while it sits there: paused, playing, unfocused, hidden in the tray.

    DISPLAY=:77 QT_QPA_PLATFORM=xcb QSG_RHI_BACKEND=opengl python scripts/idle_check.py [--seconds 6]

Starts the real window (on an X server, so drawing costs what it would on a desktop; Xvfb works) on a small
library with a two-minute tone, playing into a private PulseAudio null sink when pulseaudio is installed. For
each state it waits for things to settle, then reports the process's CPU time over a few seconds as a
percentage of one core. A player that's hidden or paused should cost next to nothing."""
import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def start_pulse(tmp):
    if not shutil.which("pulseaudio"):
        return None
    runtime = tmp / "pulse-run"
    runtime.mkdir(mode=0o700)
    os.environ["XDG_RUNTIME_DIR"] = str(runtime)
    os.environ.pop("PULSE_SERVER", None)
    r = subprocess.run(["pulseaudio", "--daemonize", "--exit-idle-time=-1", "-n",
                        "--load=module-native-protocol-unix", "--load=module-null-sink sink_name=speakers"],
                       capture_output=True, text=True, timeout=30)
    return r.returncode == 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seconds", type=float, default=6.0, help="measuring time per state")
    args = ap.parse_args()
    tmp = Path(tempfile.mkdtemp(prefix="hallucinate-idle-"))
    for k in ("XDG_DATA_HOME", "XDG_CONFIG_HOME", "XDG_CACHE_HOME"):
        os.environ[k] = str(tmp / k.lower())
    pulse = start_pulse(tmp)
    music = tmp / "music" / "Artist" / "Album"
    music.mkdir(parents=True)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "sine=frequency=220:duration=120",
                    "-metadata", "title=Tone", "-metadata", "artist=Artist", "-metadata", "album=Album",
                    str(music / "01 Tone.flac")], check=True)

    from PySide6.QtCore import QEventLoop, QObject, QTimer, QUrl
    from PySide6.QtGui import QIcon, QWindow
    from PySide6.QtQml import QQmlApplicationEngine
    from PySide6.QtQuickControls2 import QQuickStyle
    from PySide6.QtWidgets import QApplication

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
    app = QApplication(sys.argv[:1])

    def wait(ms):
        loop = QEventLoop()
        QTimer.singleShot(int(ms), loop.quit)
        loop.exec()

    db = tmp / "library.db"
    library = Library(db, tmp / "art")
    player = Player(session_file=tmp / "session.json")
    user_lib = UserLibrary(db, player)
    library.reloaded.connect(user_lib.refresh)
    shell = DesktopShell(app, player, QIcon())
    context = {
        "library": library, "player": player, "userLib": user_lib, "shell": shell,
        "scrobbler": LastFmScrobbler(player, tmp / "data"),
        "listenbrainz": ListenBrainzScrobbler(player, tmp / "data", user_lib),
        "metaEditor": MetadataEditor(db, tmp / "art"), "lyricsCtl": LyricsController(db, player),
        "replayGain": ReplayGainAnalyzer(db), "headphones": HeadphoneFinder(tmp / "cache", player),
        "discord": DiscordPresence(player), "themeManager": ThemeManager(tmp / "config", player),
        "stations": Stations(tmp / "streams.db", tmp / "cache", player),
        "servers": Servers(db, tmp / "art", player),
        "podcasts": Podcasts(tmp / "streams.db", tmp / "data", tmp / "cache", player),
    }
    engine = QQmlApplicationEngine()
    engine.addImageProvider("art", ArtProvider(tmp / "thumbs"))
    for k, v in context.items():
        engine.rootContext().setContextProperty(k, v)
    engine.addImportPath(str(ROOT / "hallucinate" / "qml"))
    engine.load(QUrl.fromLocalFile(str(ROOT / "hallucinate" / "qml" / "main.qml")))
    window = engine.rootObjects()[0]
    shell.setWindow(window)
    window.resize(1280, 800)
    library.addFolder(str(tmp / "music"))
    library.rescan()
    deadline = time.time() + 60
    while library.trackCount < 1 and time.time() < deadline:
        wait(100)
    now_playing = window.findChild(QObject, "nowPlayingView")
    other = QWindow()  # something else to take the focus
    other.resize(200, 200)

    def focus(on):
        if on:
            window.show()
            window.requestActivate()
        else:
            other.show()
            other.requestActivate()

    def state(play=False, focused=True, hidden=False, np=False):
        def apply():
            if play and not player.playing:
                if not player.hasTrack:
                    player.playList(library.allTracks(), 0)
                else:
                    player.play()
            if not play and player.playing:
                player.pause()
            if now_playing is not None:
                now_playing.setProperty("open", np)
            if hidden:
                window.hide()
            else:
                focus(focused)
        return apply

    states = [
        ("paused, window in focus", state()),
        ("paused, another window in focus", state(focused=False)),
        ("paused, hidden in the tray", state(hidden=True)),
        ("playing, window in focus", state(play=True)),
        ("playing, another window in focus", state(play=True, focused=False)),
        ("playing, hidden in the tray", state(play=True, hidden=True)),
        ("playing, Now Playing open, in focus", state(play=True, np=True)),
        ("playing, Now Playing open, unfocused", state(play=True, np=True, focused=False)),
        ("playing, Now Playing open, hidden", state(play=True, np=True, hidden=True)),
        ("paused, Now Playing open, in focus", state(np=True)),
    ]
    print(f"Audio: {'PulseAudio null sink' if pulse else 'no audio server (playback may stop at once)'};"
          f" platform {app.platformName()}")
    for label, apply in states:
        apply()
        wait(2000)
        cpu0, wall0 = time.process_time(), time.perf_counter()
        wait(args.seconds * 1000)
        cpu = (time.process_time() - cpu0) / (time.perf_counter() - wall0) * 100
        print(f"  {label:40s} {cpu:5.1f}% of a core  (active={window.property('active')},"
              f" playing={player.playing})", flush=True)
    if pulse:
        subprocess.run(["pulseaudio", "--kill"], capture_output=True)
    os._exit(0)


if __name__ == "__main__":
    main()
