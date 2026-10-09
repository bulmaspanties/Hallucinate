import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from audio import FFMPEG, encode

DBUS_RUN_SESSION = shutil.which("dbus-run-session")
pytestmark = pytest.mark.skipif(
    not DBUS_RUN_SESSION or not shutil.which("gdbus") or not FFMPEG,
    reason="dbus-run-session, gdbus and ffmpeg are required",
)


def test_mpris_methods_properties_and_media_keys(tmp_path):
    encode(
        tmp_path / "bus.flac", "flac", seconds=30, title="Bus Song",
        artist="Bus Artist", album="Bus Album",
    )
    app_script = tmp_path / "mpris_app.py"
    app_script.write_text(
        """
import sys
from PySide6.QtCore import QTimer
from PySide6.QtGui import QGuiApplication
from musicplayer.mpris import MprisService
from musicplayer.player import Player

app = QGuiApplication([])
player = Player(session_file=None)
player.playList([{"id": 42, "path": sys.argv[1], "title": "Bus Song",
                  "artist": "Bus Artist", "album": "Bus Album", "duration": 30}], 0)
mpris = MprisService(player, lambda: None, app.quit)
QTimer.singleShot(15000, app.quit)
app.exec()
player.shutdown()
""",
        encoding="utf-8",
    )
    script = tmp_path / "mpris.sh"
    script.write_text(
        """#!/bin/sh
set -eu
PYTHONPATH="$3" QT_QPA_PLATFORM=offscreen "$2" "$1/mpris_app.py" "$1/bus.flac" >"$1/app.log" 2>&1 &
pid=$!
trap 'kill "$pid" 2>/dev/null || true' EXIT
for i in 1 2 3 4 5 6 7 8 9 10; do
  if gdbus introspect --session --dest org.mpris.MediaPlayer2.musicplayer \\
       --object-path /org/mpris/MediaPlayer2 >"$1/introspection"; then break; fi
  sleep 0.2
done
gdbus call --session --dest org.mpris.MediaPlayer2.musicplayer --object-path /org/mpris/MediaPlayer2 \\
  --method org.freedesktop.DBus.Properties.Get org.mpris.MediaPlayer2.Player PlaybackStatus >"$1/status-playing"
gdbus call --session --dest org.mpris.MediaPlayer2.musicplayer --object-path /org/mpris/MediaPlayer2 \\
  --method org.freedesktop.DBus.Properties.Get org.mpris.MediaPlayer2.Player Metadata >"$1/metadata"
gdbus call --session --dest org.mpris.MediaPlayer2.musicplayer --object-path /org/mpris/MediaPlayer2 \\
  --method org.mpris.MediaPlayer2.Player.PlayPause
gdbus call --session --dest org.mpris.MediaPlayer2.musicplayer --object-path /org/mpris/MediaPlayer2 \\
  --method org.freedesktop.DBus.Properties.Get org.mpris.MediaPlayer2.Player PlaybackStatus >"$1/status-paused"
gdbus call --session --dest org.mpris.MediaPlayer2.musicplayer --object-path /org/mpris/MediaPlayer2 \\
  --method org.mpris.MediaPlayer2.Player.Play
gdbus call --session --dest org.mpris.MediaPlayer2.musicplayer --object-path /org/mpris/MediaPlayer2 \\
  --method org.freedesktop.DBus.Properties.Set org.mpris.MediaPlayer2.Player LoopStatus '<"Playlist">'
gdbus call --session --dest org.mpris.MediaPlayer2.musicplayer --object-path /org/mpris/MediaPlayer2 \\
  --method org.freedesktop.DBus.Properties.Set org.mpris.MediaPlayer2.Player Shuffle '<true>'
gdbus call --session --dest org.mpris.MediaPlayer2.musicplayer --object-path /org/mpris/MediaPlayer2 \\
  --method org.freedesktop.DBus.Properties.Get org.mpris.MediaPlayer2.Player LoopStatus >"$1/loop"
gdbus call --session --dest org.mpris.MediaPlayer2.musicplayer --object-path /org/mpris/MediaPlayer2 \\
  --method org.freedesktop.DBus.Properties.Get org.mpris.MediaPlayer2.Player Shuffle >"$1/shuffle"
gdbus call --session --dest org.mpris.MediaPlayer2.musicplayer --object-path /org/mpris/MediaPlayer2 \\
  --method org.mpris.MediaPlayer2.Player.Seek 500000
gdbus call --session --dest org.mpris.MediaPlayer2.musicplayer --object-path /org/mpris/MediaPlayer2 \\
  --method org.mpris.MediaPlayer2.Player.Next
gdbus call --session --dest org.mpris.MediaPlayer2.musicplayer --object-path /org/mpris/MediaPlayer2 \\
  --method org.mpris.MediaPlayer2.Quit
wait "$pid"
""",
        encoding="utf-8",
    )
    script.chmod(0o755)
    repo = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [DBUS_RUN_SESSION, "--", str(script), str(tmp_path), sys.executable, str(repo)],
        capture_output=True, text=True, timeout=25,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "PlayPause" in (tmp_path / "introspection").read_text()
    assert "Seeked" in (tmp_path / "introspection").read_text()
    assert "CanPause" in (tmp_path / "introspection").read_text()
    assert "Playing" in (tmp_path / "status-playing").read_text()
    assert "Paused" in (tmp_path / "status-paused").read_text()
    assert "Bus Song" in (tmp_path / "metadata").read_text()
    assert "Playlist" in (tmp_path / "loop").read_text()
    assert "true" in (tmp_path / "shuffle").read_text().lower()
