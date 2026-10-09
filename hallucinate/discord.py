"""Discord Rich Presence over Discord's local IPC (no third-party dependency).

All socket work happens on a daemon thread: the GUI thread only hands over the latest desired state.
The thread reconnects automatically (Discord started later, restarted, or closed).
"""
import json
import logging
import os
import struct
import sys
import threading
import time

from PySide6.QtCore import Property, QObject, QSettings, QTimer, Signal, Slot

from .core import artfetch

logger = logging.getLogger(__name__)

OP_HANDSHAKE, OP_FRAME, OP_CLOSE = 0, 1, 2
FALLBACK_ASSET = "hallucinate"  # name of the app-icon asset uploaded to the Discord application
RECONNECT_SECONDS = 15


def env_app_id():
    return os.environ.get("HALLUCINATE_DISCORD_APP_ID", "").strip()


def socket_candidates(env=None, platform=None):
    """Possible Discord IPC endpoints, in priority order (native, Flatpak, Snap on Linux; pipes on Windows)."""
    env, platform = os.environ if env is None else env, sys.platform if platform is None else platform
    if platform == "win32":
        return [rf"\\.\pipe\discord-ipc-{i}" for i in range(10)]
    bases = []
    runtime = env.get("XDG_RUNTIME_DIR")
    for var in ("XDG_RUNTIME_DIR", "TMPDIR", "TMP", "TEMP"):
        if env.get(var):
            bases.append(env[var])
    bases.append("/tmp")
    out = []
    for base in dict.fromkeys(bases):
        subdirs = ["", "app/com.discordapp.Discord/", "app/com.discordapp.DiscordCanary/", "snap.discord/",
                   "snap.discord-canary/"] if base == runtime else [""]
        for sub in subdirs:
            out += [os.path.join(base, sub, f"discord-ipc-{i}") for i in range(10)]
    return out


def encode_frame(op, payload):
    data = json.dumps(payload, separators=(",", ":")).encode()
    return struct.pack("<II", op, len(data)) + data


def _clip(text, limit=128):
    text = (text or "").strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


def build_activity(track, position_ms, playing, prefs, cover_url=None, now=None):
    """The activity dict for Discord, or None when presence should be cleared."""
    if not track or (not playing and prefs.get("hidePaused", True)):
        return None
    if prefs.get("privacy"):
        return {"type": 2, "details": "Listening to music", "assets": {"large_image": FALLBACK_ASSET}}
    title, artist, album = _clip(track.get("title")) or "Unknown", _clip(track.get("artist")), _clip(track.get("album"))
    # Discord requires 2+ characters for these fields
    act = {"type": 2, "details": title.ljust(2), "state": (artist or "Unknown artist").ljust(2)}
    image = FALLBACK_ASSET if prefs.get("hideCover") or not cover_url else cover_url
    assets = {"large_image": image}
    if album and not prefs.get("hideCover"):
        assets["large_text"] = album.ljust(2)
    act["assets"] = assets
    now = time.time() if now is None else now
    if playing:
        start = now - position_ms / 1000
        act["timestamps"] = {"start": int(start)}
        dur = track.get("duration") or 0
        if dur:
            act["timestamps"]["end"] = int(start + dur)
    else:
        act["state"] = _clip(f"{artist or 'Unknown artist'} · paused").ljust(2)
    return act


class _Conn:
    """Blocking IPC connection used only from the worker thread."""

    def __init__(self, app_id, candidates):
        self.app_id, self.candidates = app_id, candidates
        self._sock = None
        self._pipe = None

    def connect(self):
        for path in self.candidates:
            try:
                self._open(path)
                self._send(OP_HANDSHAKE, {"v": 1, "client_id": self.app_id})
                op, data = self._recv()
                if op == OP_FRAME and data.get("evt") == "READY":
                    return True
                self.close()
            except OSError:
                self.close()
        return False

    def _open(self, path):
        if sys.platform == "win32":
            self._pipe = open(path, "r+b", buffering=0)  # noqa: SIM115
            return
        import socket
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(3)
        try:
            s.connect(path)
        except OSError:
            s.close()
            raise
        self._sock = s

    def _write(self, data):
        if self._pipe:
            self._pipe.write(data)
        else:
            self._sock.sendall(data)

    def _read(self, n):
        buf = b""
        while len(buf) < n:
            chunk = self._pipe.read(n - len(buf)) if self._pipe else self._sock.recv(n - len(buf))
            if not chunk:
                raise OSError("connection closed")
            buf += chunk
        return buf

    def _send(self, op, payload):
        self._write(encode_frame(op, payload))

    def _recv(self):
        op, length = struct.unpack("<II", self._read(8))
        return op, json.loads(self._read(length).decode() or "{}")

    def set_activity(self, activity):
        self._send(OP_FRAME, {"cmd": "SET_ACTIVITY", "nonce": str(time.time()),
                              "args": {"pid": os.getpid(), "activity": activity}})
        op, data = self._recv()
        if op == OP_CLOSE:
            raise OSError("closed by Discord")
        return data

    def close(self):
        for h in (self._sock, self._pipe):
            try:
                if h:
                    h.close()
            except OSError:
                pass
        self._sock = self._pipe = None


class _Worker(threading.Thread):
    def __init__(self, status_cb, candidates=None, reconnect=RECONNECT_SECONDS):
        super().__init__(daemon=True, name="discord-rpc")
        self._cv = threading.Condition()
        self._want = None  # ("clear",) | ("set", activity, app_id, cover_query)
        self._quit = False
        self._status_cb = status_cb
        self._candidates = candidates
        self._reconnect = reconnect
        self._covers = {}

    def submit(self, want):
        with self._cv:
            self._want = want
            self._cv.notify()

    def stop(self):
        with self._cv:
            self._quit = True
            self._cv.notify()

    def _cover(self, query):
        if not query:
            return None
        if query not in self._covers:
            try:
                ids = artfetch.find_release_ids(*query, limit=3)
                self._covers[query] = f"https://coverartarchive.org/release/{ids[0]}/front-250" if ids else None
            except Exception:  # noqa: BLE001 - lookup is best effort
                return None
        return self._covers[query]

    def run(self):
        conn, applied, app = None, None, None
        while True:
            with self._cv:
                if not self._quit and (self._want is None or self._want == applied) and conn is not None:
                    self._cv.wait(timeout=30)
                if self._quit:
                    break
                want = self._want
            if want is None:
                continue
            app_id = want[2] if want[0] == "set" else app
            if conn is not None and app_id != app and app_id:
                conn.close()
                conn = None
            if want[0] == "clear" and conn is None:
                applied = want
                continue
            if conn is None:
                app = app_id
                conn = _Conn(app, self._candidates or socket_candidates())
                if not conn.connect():
                    conn = None
                    self._status_cb("waiting")
                    with self._cv:
                        self._cv.wait(timeout=self._reconnect)
                    continue
                self._status_cb("connected")
                applied = None
            try:
                if want[0] == "clear":
                    conn.set_activity(None)
                else:
                    activity = dict(want[1])
                    activity["assets"] = dict(activity.get("assets", {}))
                    if activity.get("assets", {}).get("large_image") == "__cover__":
                        activity["assets"]["large_image"] = self._cover(want[3]) or FALLBACK_ASSET
                    conn.set_activity(activity)
                applied = want
            except OSError:
                conn.close()
                conn = None
                applied = None
                self._status_cb("waiting")
                with self._cv:
                    self._cv.wait(timeout=min(self._reconnect, 5))
        if conn:
            try:
                conn.set_activity(None)
            except OSError:
                pass
            conn.close()


class DiscordPresence(QObject):
    changed = Signal()
    _status = Signal(str)

    def __init__(self, player, candidates=None, reconnect=RECONNECT_SECONDS, parent=None):
        super().__init__(parent)
        self._player = player
        self._s = QSettings("hallucinate", "hallucinate")
        self._enabled = self._s.value("discord/enabled", False, bool)
        self._prefs = {"hidePaused": self._s.value("discord/hidePaused", True, bool),
                       "hideCover": self._s.value("discord/hideCover", False, bool),
                       "privacy": self._s.value("discord/privacy", False, bool)}
        self._app_id = str(self._s.value("discord/appId", "")) or env_app_id()
        self._state = "off"
        self._candidates, self._reconnect = candidates, reconnect
        self._worker = None
        self._status.connect(self._set_state)
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(250)
        self._debounce.timeout.connect(self._push)
        for sig in (player.trackChanged, player.stateChanged, player.seeked):
            sig.connect(self._schedule)
        # Timestamps only drift on seek/pause, which signal; no polling needed.
        if self._enabled:
            self._start()

    # --- properties -------------------------------------------------------------------
    @Property(bool, notify=changed)
    def enabled(self):
        return self._enabled

    @Property(bool, notify=changed)
    def hidePaused(self):
        return self._prefs["hidePaused"]

    @Property(bool, notify=changed)
    def hideCover(self):
        return self._prefs["hideCover"]

    @Property(bool, notify=changed)
    def privacy(self):
        return self._prefs["privacy"]

    @Property(str, notify=changed)
    def appId(self):
        return self._app_id

    @Property(str, notify=changed)
    def status(self):
        if not self._enabled:
            return "Off"
        if not self._app_id:
            return "Needs a Discord application ID"
        return {"connected": "Connected to Discord", "waiting": "Waiting for Discord…"}.get(self._state, "Starting…")

    # --- setters ------------------------------------------------------------------------
    def _save(self, key, value):
        self._s.setValue(f"discord/{key}", value)
        self.changed.emit()

    @Slot(bool)
    def setEnabled(self, on):
        self._enabled = on
        self._save("enabled", on)
        if on:
            self._start()
        else:
            self._stop()

    @Slot(str, bool)
    def setPref(self, name, on):
        if name in self._prefs:
            self._prefs[name] = on
            self._save(name, on)
            self._schedule()

    @Slot(str)
    def setAppId(self, value):
        self._app_id = value.strip()
        self._save("appId", self._app_id)
        self._schedule()

    # --- internals ----------------------------------------------------------------------------
    def _start(self):
        if self._worker is None:
            self._state = "starting"
            self._worker = _Worker(self._status.emit, self._candidates, self._reconnect)
            self._worker.start()
        self._schedule()

    def _stop(self):
        if self._worker is not None:
            self._worker.submit(("clear",))
            self._worker.stop()
            self._worker = None
        self._state = "off"
        self.changed.emit()

    def _set_state(self, state):
        if self._worker is not None:
            self._state = state
            self.changed.emit()

    def _schedule(self):
        if self._worker is not None:
            self._debounce.start()

    def _push(self):
        if self._worker is None:
            return
        p = self._player
        if not self._app_id:
            self._worker.submit(("clear",))
            self.changed.emit()
            return
        track = p.current if p.hasTrack else None
        activity = build_activity(track, p.position, p.playing, self._prefs, cover_url="__cover__")
        query = None
        if activity and not self._prefs["privacy"] and not self._prefs["hideCover"] and track:
            query = (track.get("album_artist") or track.get("artist") or "", track.get("album") or "")
            if not query[1]:
                query = None
        self._worker.submit(("set", activity, self._app_id, query) if activity else ("clear",))
        self.changed.emit()

    def shutdown(self):
        if self._worker is not None:
            self._worker.submit(("clear",))
            self._worker.stop()
            self._worker.join(timeout=2)
            self._worker = None
