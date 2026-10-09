import json
import os
import socket
import struct
import sys
import threading

import pytest
from conftest import wait_for

from hallucinate import discord as dc

TRACK = {"title": "Song", "artist": "Band", "album": "Disc", "duration": 200}
PREFS = {"hidePaused": True, "hideCover": False, "privacy": False}


def test_build_activity():
    a = dc.build_activity(TRACK, 30000, True, PREFS, cover_url="https://x/y.jpg", now=1000)
    assert a["type"] == 2 and a["details"] == "Song" and a["state"] == "Band"
    assert a["timestamps"] == {"start": 970, "end": 1170}
    assert a["assets"]["large_image"] == "https://x/y.jpg" and a["assets"]["large_text"] == "Disc"
    assert dc.build_activity(TRACK, 0, False, PREFS) is None
    paused = dc.build_activity(TRACK, 0, False, dict(PREFS, hidePaused=False))
    assert "timestamps" not in paused and "paused" in paused["state"]
    assert dc.build_activity(TRACK, 0, True, dict(PREFS, hideCover=True), cover_url="u")["assets"] == {
        "large_image": dc.FALLBACK_ASSET}
    priv = dc.build_activity(TRACK, 0, True, dict(PREFS, privacy=True))
    assert "Song" not in json.dumps(priv) and "Band" not in json.dumps(priv)
    short = dc.build_activity({"title": "A", "artist": ""}, 0, True, PREFS)
    assert len(short["details"]) >= 2 and len(short["state"]) >= 2


def test_socket_candidates():
    env = {"XDG_RUNTIME_DIR": "/run/user/1000"}
    c = dc.socket_candidates(env, "linux")
    assert "/run/user/1000/discord-ipc-0" in c
    assert "/run/user/1000/app/com.discordapp.Discord/discord-ipc-0" in c
    assert "/run/user/1000/snap.discord/discord-ipc-0" in c
    assert dc.socket_candidates({}, "win32")[0] == r"\\.\pipe\discord-ipc-0"


class FakeDiscord(threading.Thread):
    def __init__(self, path):
        super().__init__(daemon=True)
        self.path, self.activities, self.handshake = path, [], None
        self.srv = socket.socket(socket.AF_UNIX)
        self.srv.bind(path)
        self.srv.listen(1)
        self.drop_next = False

    def _read(self, c):
        hdr = b""
        while len(hdr) < 8:
            d = c.recv(8 - len(hdr))
            if not d:
                return None
            hdr += d
        op, n = struct.unpack("<II", hdr)
        body = b""
        while len(body) < n:
            body += c.recv(n - len(body))
        return op, json.loads(body)

    def _send(self, c, op, obj):
        b = json.dumps(obj).encode()
        c.sendall(struct.pack("<II", op, len(b)) + b)

    def run(self):
        while True:
            try:
                c, _ = self.srv.accept()
            except OSError:
                return
            while (msg := self._read(c)):
                op, data = msg
                if op == 0:
                    self.handshake = data
                    self._send(c, 1, {"cmd": "DISPATCH", "evt": "READY"})
                else:
                    self.activities.append(data["args"]["activity"])
                    self._send(c, 1, {"cmd": "SET_ACTIVITY", "evt": None})
                    if self.drop_next:
                        self.drop_next = False
                        break
            c.close()


@pytest.mark.skipif(sys.platform == "win32", reason="unix sockets")
def test_worker_connects_updates_and_reconnects(tmp_path):
    path = str(tmp_path / "discord-ipc-0")
    statuses = []
    w = dc._Worker(statuses.append, [path], reconnect=0.2)
    w.start()
    act = {"type": 2, "details": "Song", "state": "Band", "assets": {"large_image": "hallucinate"}}
    w.submit(("set", act, "123", None))  # Discord not running yet
    assert wait_for(lambda: "waiting" in statuses)
    srv = FakeDiscord(path)
    srv.start()
    assert wait_for(lambda: srv.activities)
    assert srv.handshake == {"v": 1, "client_id": "123"} and srv.activities[0]["details"] == "Song"
    srv.drop_next = True
    w.submit(("set", dict(act, details="Two"), "123", None))
    assert wait_for(lambda: any(a["details"] == "Two" for a in srv.activities))
    w.submit(("set", dict(act, details="Three"), "123", None))
    assert wait_for(lambda: any(a["details"] == "Three" for a in srv.activities))
    w.submit(("clear",))
    assert wait_for(lambda: srv.activities[-1] is None)
    w.stop()
    w.join(3)
    srv.srv.close()


class FakePlayer:
    def __init__(self):
        from PySide6.QtCore import QObject, Signal

        class P(QObject):
            trackChanged = Signal()
            stateChanged = Signal()
            seeked = Signal(int)
            current = dict(TRACK)
            hasTrack = True
            position = 5000
            playing = True

        self.p = P()


@pytest.mark.skipif(sys.platform == "win32", reason="unix sockets")
def test_controller_sends_presence_and_respects_privacy(qapp, tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    monkeypatch.setattr(dc.artfetch, "find_release_ids", lambda a, b, limit=3: ["mbid1"])
    path = str(tmp_path / "discord-ipc-0")
    srv = FakeDiscord(path)
    srv.start()
    pl = FakePlayer().p
    ctl = dc.DiscordPresence(pl, [path], 0.2)
    ctl._s.clear()
    ctl._enabled, ctl._app_id = False, ""
    ctl.setAppId("999")
    ctl.setEnabled(True)
    assert wait_for(lambda: srv.activities)
    assert srv.activities[-1]["assets"]["large_image"].startswith("https://coverartarchive.org/release/mbid1/")
    assert ctl.status in ("Connected to Discord", "Starting…")
    ctl.setPref("privacy", True)
    assert wait_for(lambda: srv.activities[-1] and srv.activities[-1]["details"] == "Listening to music")
    ctl.setEnabled(False)
    assert wait_for(lambda: srv.activities[-1] is None)
    ctl._s.clear()
    srv.srv.close()
    assert os.path.exists(path)
