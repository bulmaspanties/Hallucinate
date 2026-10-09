"""Last.fm authentication, now-playing updates, and offline scrobble delivery."""
import hashlib
import json
import logging
import os
import threading
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import keyring
from PySide6.QtCore import Property, QObject, QTimer, QUrl, Signal, Slot
from PySide6.QtGui import QDesktopServices

API_URL = "https://ws.audioscrobbler.com/2.0/"
AUTH_URL = "https://www.last.fm/api/auth/"
KEYRING_SERVICE = "Music Player Last.fm"
MAX_RETRY_SECONDS = 900
logger = logging.getLogger(__name__)


def api_signature(params: dict, secret: str) -> str:
    payload = "".join(f"{key}{params[key]}" for key in sorted(params) if key not in {"format", "callback"})
    return hashlib.md5((payload + secret).encode("utf-8")).hexdigest()


def scrobble_threshold(duration_ms: int) -> int:
    """Last.fm's listen rule: half the duration, or four minutes, whichever is shorter."""
    return min(duration_ms // 2, 240_000) if duration_ms > 0 else 240_000


def api_request(method, params, api_key, api_secret, session_key=None, signed=True):
    fields = {"method": method, "api_key": api_key, **params}
    if session_key:
        fields["sk"] = session_key
    if signed:
        fields["api_sig"] = api_signature(fields, api_secret)
    fields["format"] = "json"
    req = Request(API_URL, data=urlencode(fields).encode("utf-8"), headers={
        "User-Agent": "MusicPlayer/0.1",
        "Content-Type": "application/x-www-form-urlencoded",
    })
    try:
        with urlopen(req, timeout=15) as response:
            data = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, OSError, ValueError) as exc:
        raise RuntimeError(f"Last.fm request failed: {exc}") from exc
    if not isinstance(data, dict):
        raise RuntimeError("Last.fm returned an invalid response")
    if "error" in data:
        raise RuntimeError(f"Last.fm error {data['error']}: {data.get('message', 'request rejected')}")
    return data


class LastFmScrobbler(QObject):
    statusChanged = Signal()
    connectionChanged = Signal()
    authorizationUrlChanged = Signal()
    pendingCountChanged = Signal()
    busyChanged = Signal()
    _jobFinished = Signal(str, object, str)

    def __init__(self, player, data_dir, parent=None):
        super().__init__(parent)
        self.player = player
        self._data_dir = Path(data_dir)
        self._queue_path = self._data_dir / "lastfm-scrobbles.json"
        self._api_key = os.environ.get("MUSICPLAYER_LASTFM_API_KEY", "").strip()
        self._api_secret = os.environ.get("MUSICPLAYER_LASTFM_API_SECRET", "").strip()
        self._session_key = ""
        self._auth_token = ""
        self._authorization_url = ""
        self._status = ""
        self._busy = False
        self._pending = []
        self._retry_at = 0.0
        self._retry_delay = 5.0
        self._pending_nowplaying = None
        self._sent_nowplaying_key = ""
        self._attempted_nowplaying_key = ""
        self._current_key = ""
        self._current_track = {}
        self._listened_ms = 0
        self._started_at = int(time.time())
        self._has_started_playback = False
        self._last_tick = time.monotonic()
        self._last_position = 0
        self._scrobbled_key = ""
        self._keyring_error = ""
        self._load_keyring()
        self._load_queue()

        self._jobFinished.connect(self._on_job_finished)
        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._tick)
        self._timer.start()
        self.player.trackChanged.connect(self._on_track_changed)
        self.player.stateChanged.connect(self._on_state_changed)
        self.player.seeked.connect(self._on_seeked)
        self._on_track_changed()

    def _load_keyring(self):
        try:
            if not self._api_key:
                self._api_key = keyring.get_password(KEYRING_SERVICE, "api_key") or ""
            if not self._api_secret:
                self._api_secret = keyring.get_password(KEYRING_SERVICE, "api_secret") or ""
            self._session_key = keyring.get_password(KEYRING_SERVICE, "session") or ""
        except Exception as exc:
            self._keyring_error = str(exc)
            logger.warning("Last.fm system keyring unavailable: %s", exc)
        self._set_status(self._initial_status())

    def _load_queue(self):
        try:
            data = json.loads(self._queue_path.read_text(encoding="utf-8"))
            if isinstance(data, list):
                self._pending = [
                    item for item in data
                    if isinstance(item, dict) and isinstance(item.get("track"), str)
                    and isinstance(item.get("artist"), str) and isinstance(item.get("timestamp"), int)
                ]
            else:
                raise ValueError("scrobble queue must be a list")
        except FileNotFoundError:
            return
        except (OSError, ValueError, TypeError) as exc:
            logger.warning("Could not load Last.fm offline queue %s: %s", self._queue_path, exc)
            self._set_status(f"Could not load queued scrobbles: {exc}")
        self.pendingCountChanged.emit()

    def _initial_status(self):
        if self._keyring_error:
            return f"System keyring unavailable: {self._keyring_error}"
        if not (self._api_key and self._api_secret):
            return "Add Last.fm API key and secret to connect."
        return "Connected to Last.fm." if self._session_key else "Not connected to Last.fm."

    @Property(bool, notify=connectionChanged)
    def connected(self):
        return bool(self._session_key)

    @Property(bool, notify=statusChanged)
    def configured(self):
        return bool(self._api_key and self._api_secret)

    @Property(str, notify=statusChanged)
    def status(self):
        return self._status

    @Property(str, notify=authorizationUrlChanged)
    def authorizationUrl(self):
        return self._authorization_url

    @Property(int, notify=pendingCountChanged)
    def pendingCount(self):
        return len(self._pending)

    @Property(bool, notify=busyChanged)
    def busy(self):
        return self._busy

    def _set_status(self, text):
        if text != self._status:
            self._status = text
            self.statusChanged.emit()

    def _set_authorization_url(self, url):
        if url != self._authorization_url:
            self._authorization_url = url
            self.authorizationUrlChanged.emit()

    @Slot(str, str)
    def setApiCredentials(self, api_key, api_secret):
        api_key, api_secret = api_key.strip(), api_secret.strip()
        if not api_key or not api_secret:
            self._set_status("Both the Last.fm API key and secret are required.")
            return
        if self._keyring_error:
            self._set_status(f"Cannot store API credentials securely: {self._keyring_error}")
            return
        try:
            keyring.set_password(KEYRING_SERVICE, "api_key", api_key)
            keyring.set_password(KEYRING_SERVICE, "api_secret", api_secret)
        except Exception as exc:
            self._set_status(f"Could not save API credentials to the system keyring: {exc}")
            return
        self._api_key, self._api_secret = api_key, api_secret
        self.statusChanged.emit()
        self._set_status("Last.fm API credentials saved securely.")

    @Slot()
    def connectAccount(self):
        if self._busy:
            return
        if not self.configured:
            self._set_status("Add Last.fm API key and secret before connecting.")
            return
        if self._keyring_error:
            self._set_status(f"System keyring is required: {self._keyring_error}")
            return
        self._set_authorization_url("")
        self._set_status("Requesting Last.fm authorization token…")
        api_key, secret = self._api_key, self._api_secret
        self._start_job(
            "token",
            lambda: api_request("auth.getToken", {}, api_key, secret, signed=False),
        )

    @Slot()
    def openAuthorizationUrl(self):
        if self._authorization_url and not QDesktopServices.openUrl(QUrl(self._authorization_url)):
            self._set_status("Could not open the Last.fm authorization page in a browser.")

    @Slot()
    def completeAuthorization(self):
        if self._busy or not self._auth_token:
            return
        token = self._auth_token
        api_key, secret = self._api_key, self._api_secret
        self._set_status("Completing Last.fm authorization…")
        self._start_job(
            "session",
            lambda: api_request("auth.getSession", {"token": token}, api_key, secret),
        )

    @Slot()
    def disconnectAccount(self):
        if self._busy:
            self._set_status("Wait for the current Last.fm request to finish before disconnecting.")
            return
        try:
            if keyring.get_password(KEYRING_SERVICE, "session"):
                keyring.delete_password(KEYRING_SERVICE, "session")
        except Exception as exc:
            self._set_status(f"Could not remove the Last.fm session from the system keyring: {exc}")
            return
        self._session_key = ""
        self._auth_token = ""
        self._sent_nowplaying_key = ""
        self._attempted_nowplaying_key = ""
        self.connectionChanged.emit()
        self._set_authorization_url("")
        self._set_status("Disconnected from Last.fm. Pending scrobbles are kept.")

    def _start_job(self, action, work, item=None):
        if self._busy:
            return False
        self._busy = True
        self.busyChanged.emit()

        def run():
            try:
                result = work()
                self._jobFinished.emit(action, (result, item), "")
            except Exception as exc:
                self._jobFinished.emit(action, (None, item), str(exc))

        threading.Thread(target=run, name=f"lastfm-{action}", daemon=True).start()
        return True

    def _on_job_finished(self, action, payload, error):
        self._busy = False
        self.busyChanged.emit()
        result, item = payload
        if error:
            self._set_status(error)
            self._retry_delay = min(self._retry_delay * 2, MAX_RETRY_SECONDS)
            self._retry_at = time.monotonic() + self._retry_delay
            if action == "nowplaying":
                self._attempted_nowplaying_key = ""
            return
        self._retry_delay = 5.0
        self._retry_at = 0.0
        if action == "token":
            token = result.get("token")
            if not token:
                self._set_status("Last.fm did not return an authorization token.")
                return
            self._auth_token = token
            self._set_authorization_url(f"{AUTH_URL}?{urlencode({'api_key': self._api_key, 'token': token})}")
            self._set_status("Authorize Music Player on Last.fm, then confirm here.")
        elif action == "session":
            try:
                session_key = result["session"]["key"]
                username = result["session"].get("name", "")
                keyring.set_password(KEYRING_SERVICE, "session", session_key)
            except Exception as exc:
                self._set_status(f"Could not store Last.fm session securely: {exc}")
                return
            self._session_key = session_key
            self._auth_token = ""
            self._set_authorization_url("")
            self.connectionChanged.emit()
            self._set_status(f"Connected to Last.fm{f' as {username}' if username else ''}.")
            self._ensure_nowplaying()
            self._send_pending()
        elif action == "nowplaying":
            self._sent_nowplaying_key = item
            self._attempted_nowplaying_key = item
            self._pending_nowplaying = None
            self._set_status("Last.fm now-playing updated.")
        elif action == "scrobble":
            if self._pending and self._pending[0] == item:
                self._pending.pop(0)
                self._save_queue()
                self.pendingCountChanged.emit()
            self._set_status(f"Scrobbled {item.get('artist', '')} — {item.get('track', '')}.")
            self._send_pending()

    @Slot()
    def _on_track_changed(self):
        track = dict(self.player.current or {})
        key = self._track_key(track)
        if key != self._current_key:
            self._current_key = key
            self._current_track = track
            self._listened_ms = 0
            self._scrobbled_key = ""
            self._started_at = int(time.time())
            self._has_started_playback = bool(self.player.playing)
            self._sent_nowplaying_key = ""
            self._attempted_nowplaying_key = ""
            self._pending_nowplaying = None
            self._last_tick = time.monotonic()
            self._last_position = self.player.position
        self._ensure_nowplaying()

    @Slot()
    def _on_state_changed(self):
        self._last_tick = time.monotonic()
        self._last_position = self.player.position
        if self.player.playing and not self._has_started_playback:
            self._started_at = int(time.time())
            self._has_started_playback = True
        self._ensure_nowplaying()

    @Slot(int)
    def _on_seeked(self, position):
        self._last_tick = time.monotonic()
        self._last_position = position

    def _track_key(self, track):
        return "\x1f".join(str(track.get(k, "")) for k in ("path", "title", "artist", "album"))

    def _ensure_nowplaying(self):
        if not self.connected or not self.player.playing or not self._current_track:
            return
        key = self._track_key(self._current_track)
        if key == self._sent_nowplaying_key or key == self._attempted_nowplaying_key:
            return
        self._pending_nowplaying = dict(self._current_track)
        self._send_nowplaying()

    def _send_nowplaying(self):
        track = self._pending_nowplaying
        if not self.connected or not track or self._busy or time.monotonic() < self._retry_at:
            return
        key = self._track_key(track)
        self._attempted_nowplaying_key = key
        try:
            fields = self._api_track_fields(track)
        except (TypeError, ValueError) as exc:
            self._set_status(str(exc))
            return
        self._start_job(
            "nowplaying",
            lambda: api_request("track.updateNowPlaying", fields, self._api_key, self._api_secret, self._session_key),
            item=key,
        )

    def _tick(self):
        now = time.monotonic()
        track = dict(self.player.current or {})
        key = self._track_key(track)
        if key != self._current_key:
            self._on_track_changed()
        if self.connected and self.player.playing and self._current_track:
            position = self.player.position
            elapsed = max(0.0, min(now - self._last_tick, 2.0))
            advance = position - self._last_position
            if 0 < advance <= elapsed * 2000 + 250:
                self._listened_ms += min(int(elapsed * 1000), 1500)
            duration = int(self.player.duration or float(self._current_track.get("duration", 0)) * 1000)
            threshold = scrobble_threshold(duration)
            key = self._track_key(self._current_track)
            if key != self._scrobbled_key and threshold > 0 and self._listened_ms >= threshold:
                self._scrobbled_key = key
                self._queue_scrobble(self._current_track, self._started_at)
        self._last_tick = now
        self._last_position = self.player.position
        if self.connected:
            if self._pending_nowplaying and time.monotonic() >= self._retry_at:
                self._send_nowplaying()
            self._send_pending()

    def _api_track_fields(self, track):
        artist = track.get("artist", "")
        title = track.get("title", "")
        if not artist or not title:
            raise ValueError("Last.fm requires a track title and artist.")
        fields = {"artist": artist, "track": title}
        if track.get("album"):
            fields["album"] = track["album"]
        duration = int(float(track.get("duration", 0) or 0))
        if duration > 0:
            fields["duration"] = duration
        if track.get("track_no"):
            fields["trackNumber"] = int(track["track_no"])
        return fields

    def _queue_scrobble(self, track, timestamp):
        try:
            item = {
                **self._api_track_fields(track),
                "timestamp": int(timestamp),
            }
        except (TypeError, ValueError) as exc:
            self._set_status(str(exc))
            return
        self._pending.append(item)
        self._save_queue()
        self.pendingCountChanged.emit()
        if self.connected:
            self._send_pending()

    def _send_pending(self):
        if not self.connected or self._busy or not self._pending or time.monotonic() < self._retry_at:
            return
        item = dict(self._pending[0])

        def submit():
            result = api_request(
                "track.scrobble", item, self._api_key, self._api_secret, self._session_key
            )
            accepted = result.get("scrobbles", {}).get("@attr", {}).get("accepted")
            if str(accepted) != "1":
                raise RuntimeError("Last.fm did not accept the queued scrobble.")
            return result

        self._start_job(
            "scrobble",
            submit,
            item=item,
        )

    def _save_queue(self):
        try:
            self._data_dir.mkdir(parents=True, exist_ok=True)
            temporary = self._queue_path.with_suffix(".tmp")
            temporary.write_text(json.dumps(self._pending, ensure_ascii=False), encoding="utf-8")
            os.replace(temporary, self._queue_path)
        except (OSError, TypeError, ValueError) as exc:
            logger.warning("Could not persist Last.fm offline queue to %s: %s", self._queue_path, exc)
            self._set_status(f"Could not persist offline scrobbles: {exc}")

    @Slot()
    def shutdown(self):
        self._timer.stop()
