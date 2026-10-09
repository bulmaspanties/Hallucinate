"""ListenBrainz scrobbling (token in the system keyring, offline queue) and listen-history import."""
import json
import logging
import threading
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import keyring
from PySide6.QtCore import Property, QObject, QTimer, Signal, Slot

DEFAULT_URL = "https://api.listenbrainz.org"
KEYRING_SERVICE = "Music Player ListenBrainz"
MAX_RETRY_SECONDS = 900
logger = logging.getLogger(__name__)


def lb_request(base, path, token=None, payload=None, params=None):
    url = base.rstrip("/") + path + (("?" + urlencode(params)) if params else "")
    headers = {"User-Agent": "MusicPlayer/0.3"}
    data = None
    if token:
        headers["Authorization"] = f"Token {token}"
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    try:
        with urlopen(Request(url, data=data, headers=headers), timeout=20) as r:
            body = r.read().decode("utf-8")
            return json.loads(body) if body else {}
    except HTTPError as exc:
        if exc.code in (400, 401, 403):  # rejected for good, retrying won't help
            raise PermissionError(f"ListenBrainz rejected the request ({exc.code})") from exc
        raise RuntimeError(f"ListenBrainz request failed: {exc}") from exc
    except (URLError, TimeoutError, OSError, ValueError) as exc:
        raise RuntimeError(f"ListenBrainz request failed: {exc}") from exc


def track_metadata(track):
    artist, title = track.get("artist", ""), track.get("title", "")
    if not artist or not title:
        raise ValueError("ListenBrainz requires a track title and artist.")
    info = {"media_player": "Music Player", "submission_client": "Music Player"}
    dur = int(float(track.get("duration", 0) or 0))
    if dur > 0:
        info["duration"] = dur
    if track.get("track_no"):
        info["tracknumber"] = int(track["track_no"])
    meta = {"artist_name": artist, "track_name": title, "additional_info": info}
    if track.get("album"):
        meta["release_name"] = track["album"]
    return meta


def parse_listens(data):
    out = []
    for item in (data.get("payload", {}) or {}).get("listens", []):
        meta = item.get("track_metadata") or {}
        out.append({"ts": item.get("listened_at"), "artist": meta.get("artist_name", ""),
                    "title": meta.get("track_name", ""), "album": meta.get("release_name", "")})
    return out


def parse_lastfm_page(data):
    tracks = (data.get("recenttracks") or {})
    items = tracks.get("track", [])
    if isinstance(items, dict):
        items = [items]
    out = []
    for t in items:
        ts = (t.get("date") or {}).get("uts")  # no date => currently playing
        if not ts:
            continue
        out.append({"ts": int(ts), "artist": (t.get("artist") or {}).get("#text", ""),
                    "title": t.get("name", ""), "album": (t.get("album") or {}).get("#text", "")})
    pages = int(((tracks.get("@attr") or {}).get("totalPages")) or 1)
    return out, pages


def fetch_listenbrainz_history(base, user, token=None, progress=None, limit=100000):
    items, max_ts = [], None
    while len(items) < limit:
        params = {"count": 1000}
        if max_ts:
            params["max_ts"] = max_ts
        page = parse_listens(lb_request(base, f"/1/user/{user}/listens", token, params=params))
        if not page:
            break
        items += page
        max_ts = min(p["ts"] for p in page if p["ts"])
        if progress:
            progress(len(items))
    return items


def fetch_lastfm_history(user, api_key, progress=None, max_pages=500):
    from .scrobbling import API_URL
    items, page, pages = [], 1, 1
    while page <= min(pages, max_pages):
        url = API_URL + "?" + urlencode({"method": "user.getrecenttracks", "user": user, "api_key": api_key,
                                         "format": "json", "limit": 200, "page": page})
        try:
            with urlopen(Request(url, headers={"User-Agent": "MusicPlayer/0.3"}), timeout=20) as r:
                data = json.loads(r.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError, OSError, ValueError) as exc:
            raise RuntimeError(f"Last.fm request failed: {exc}") from exc
        if "error" in data:
            raise RuntimeError(f"Last.fm error {data['error']}: {data.get('message', '')}")
        got, pages = parse_lastfm_page(data)
        items += got
        if progress:
            progress(len(items))
        page += 1
    return items


class ListenBrainzScrobbler(QObject):
    statusChanged = Signal()
    connectionChanged = Signal()
    pendingCountChanged = Signal()
    busyChanged = Signal()
    importChanged = Signal()
    importFinished = Signal(int)  # new listens added
    _jobFinished = Signal(str, object, str)
    _importDone = Signal(object, str)

    def __init__(self, player, data_dir, userlib=None, parent=None):
        super().__init__(parent)
        self.player = player
        self.userlib = userlib
        self._queue_path = Path(data_dir) / "listenbrainz-listens.json"
        self._base = DEFAULT_URL
        self._token = ""
        self._user = ""
        self._status = ""
        self._busy = False
        self._pending = []
        self._retry_at = 0.0
        self._retry_delay = 5.0
        self._now_key = ""
        self._started = int(time.time())
        self._import_status = ""
        self._importing = False
        self._keyring_error = ""
        self._load_keyring()
        self._load_queue()
        self._jobFinished.connect(self._on_job_finished)
        self._importDone.connect(self._on_import_done)
        self._timer = QTimer(self)
        self._timer.setInterval(2000)
        self._timer.timeout.connect(self._flush)
        self._timer.start()
        player.trackChanged.connect(self._on_track_changed)
        player.stateChanged.connect(self._send_now_playing)
        player.played.connect(self._on_played)

    # --- state ---------------------------------------------------------------
    def _load_keyring(self):
        try:
            self._token = keyring.get_password(KEYRING_SERVICE, "token") or ""
            self._user = keyring.get_password(KEYRING_SERVICE, "user") or ""
        except Exception as exc:  # noqa: BLE001
            self._keyring_error = str(exc)
        self._set_status(f"System keyring unavailable: {self._keyring_error}" if self._keyring_error
                         else ("Connected to ListenBrainz" + (f" as {self._user}." if self._user else "."))
                         if self._token else "Not connected to ListenBrainz.")

    def _load_queue(self):
        try:
            data = json.loads(self._queue_path.read_text(encoding="utf-8"))
            self._pending = [i for i in data if isinstance(i, dict) and "listened_at" in i and "track_metadata" in i]
        except FileNotFoundError:
            pass
        except (OSError, ValueError, TypeError) as exc:
            logger.warning("Could not load ListenBrainz queue: %s", exc)

    def _save_queue(self):
        try:
            self._queue_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._queue_path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self._pending, ensure_ascii=False), encoding="utf-8")
            tmp.replace(self._queue_path)
        except OSError as exc:
            logger.warning("Could not persist ListenBrainz queue: %s", exc)

    def _set_status(self, text):
        if text != self._status:
            self._status = text
            self.statusChanged.emit()

    @Property(bool, notify=connectionChanged)
    def connected(self):
        return bool(self._token)

    @Property(str, notify=connectionChanged)
    def username(self):
        return self._user

    @Property(str, notify=statusChanged)
    def status(self):
        return self._status

    @Property(int, notify=pendingCountChanged)
    def pendingCount(self):
        return len(self._pending)

    @Property(bool, notify=busyChanged)
    def busy(self):
        return self._busy

    @Property(str, notify=importChanged)
    def importStatus(self):
        return self._import_status

    @Property(bool, notify=importChanged)
    def importing(self):
        return self._importing

    # --- account ---------------------------------------------------------------
    @Slot(str, str)
    def connectToken(self, token, server=""):
        token = token.strip()
        if not token or self._busy:
            return
        if self._keyring_error:
            self._set_status(f"System keyring is required: {self._keyring_error}")
            return
        self._base = server.strip() or DEFAULT_URL
        self._set_status("Validating token…")
        self._start("validate", lambda: lb_request(self._base, "/1/validate-token", params={"token": token}),
                    item=token)

    @Slot()
    def disconnectAccount(self):
        try:
            for k in ("token", "user"):
                if keyring.get_password(KEYRING_SERVICE, k):
                    keyring.delete_password(KEYRING_SERVICE, k)
        except Exception as exc:  # noqa: BLE001
            self._set_status(f"Could not remove the token from the keyring: {exc}")
            return
        self._token = self._user = ""
        self.connectionChanged.emit()
        self._set_status("Disconnected from ListenBrainz. Pending listens are kept.")

    def _start(self, action, work, item=None):
        if self._busy:
            return False
        self._busy = True
        self.busyChanged.emit()

        def run():
            try:
                self._jobFinished.emit(action, (work(), item), "")
            except PermissionError as exc:
                self._jobFinished.emit(action, (None, item), "!" + str(exc))
            except Exception as exc:  # noqa: BLE001
                self._jobFinished.emit(action, (None, item), str(exc))

        threading.Thread(target=run, name=f"listenbrainz-{action}", daemon=True).start()
        return True

    def _on_job_finished(self, action, payload, error):
        self._busy = False
        self.busyChanged.emit()
        result, item = payload
        if error:
            fatal = error.startswith("!")
            self._set_status(error.lstrip("!"))
            if action == "submit" and fatal and self._pending:
                self._pending.pop(0)  # a listen the server will never accept
                self._save_queue()
                self.pendingCountChanged.emit()
            elif action != "validate":
                self._retry_delay = min(self._retry_delay * 2, MAX_RETRY_SECONDS)
                self._retry_at = time.monotonic() + self._retry_delay
            return
        self._retry_delay, self._retry_at = 5.0, 0.0
        if action == "validate":
            if not result.get("valid"):
                self._set_status("ListenBrainz says that token is not valid.")
                return
            try:
                keyring.set_password(KEYRING_SERVICE, "token", item)
                keyring.set_password(KEYRING_SERVICE, "user", result.get("user_name", ""))
            except Exception as exc:  # noqa: BLE001
                self._set_status(f"Could not store the token securely: {exc}")
                return
            self._token, self._user = item, result.get("user_name", "")
            self.connectionChanged.emit()
            self._set_status(f"Connected to ListenBrainz as {self._user}.")
            self._send_now_playing()
            self._flush()
        elif action == "submit":
            if self._pending and self._pending[0] == item:
                self._pending.pop(0)
                self._save_queue()
                self.pendingCountChanged.emit()
            self._set_status("Listen submitted to ListenBrainz.")
            self._flush()

    # --- scrobbling ------------------------------------------------------------
    def _on_track_changed(self):
        self._started = int(time.time())
        self._now_key = ""
        self._send_now_playing()

    def _send_now_playing(self):
        track = dict(self.player.current or {})
        key = f"{track.get('path')}"
        if not (self.connected and self.player.playing and track and key != self._now_key) or self._busy:
            return
        try:
            meta = track_metadata(track)
        except ValueError:
            return
        self._now_key = key
        payload = {"listen_type": "playing_now", "payload": [{"track_metadata": meta}]}
        base, token = self._base, self._token
        self._start("now", lambda: lb_request(base, "/1/submit-listens", token, payload))

    def _on_played(self, track):
        try:
            meta = track_metadata(dict(track))
        except ValueError:
            return
        self._pending.append({"listened_at": self._started, "track_metadata": meta})
        self._save_queue()
        self.pendingCountChanged.emit()
        self._flush()

    def _flush(self):
        if not self.connected or self._busy or not self._pending or time.monotonic() < self._retry_at:
            return
        item = dict(self._pending[0])
        payload = {"listen_type": "single", "payload": [item]}
        base, token = self._base, self._token
        self._start("submit", lambda: lb_request(base, "/1/submit-listens", token, payload), item=self._pending[0])

    # --- history import ----------------------------------------------------------
    @Slot(str, str)
    def importHistory(self, source, user):
        """Import listens from 'listenbrainz' or 'lastfm' into the local play history."""
        user = user.strip() or (self._user if source == "listenbrainz" else "")
        if self._importing or not user:
            self._import_status = "Enter a username to import from."
            self.importChanged.emit()
            return
        self._importing = True
        self._import_status = "Fetching listens…"
        self.importChanged.emit()
        base, token = self._base, self._token
        ulib = self.userlib

        def progress(n):
            self._importDone.emit({"progress": n}, "")

        def run():
            try:
                if source == "lastfm":
                    from .scrobbling import LastFmScrobbler  # noqa: F401
                    key = _lastfm_key()
                    if not key:
                        raise RuntimeError("Set a Last.fm API key first (Settings → Last.fm).")
                    items = fetch_lastfm_history(user, key, progress)
                else:
                    items = fetch_listenbrainz_history(base, user, token, progress)
                if ulib is None:
                    raise RuntimeError("Library unavailable")
                ulib.importPlays(items, source, lambda res: self._importDone.emit(res, ""))
            except Exception as exc:  # noqa: BLE001
                self._importDone.emit(None, str(exc))

        threading.Thread(target=run, name="history-import", daemon=True).start()

    def _on_import_done(self, result, error):
        if error:
            self._importing = False
            self._import_status = error
        elif "progress" in result:
            self._import_status = f"Fetched {result['progress']} listens…"
        else:
            self._importing = False
            self._import_status = f"Imported {result['added']} new listens ({result['matched']} matched your library)."
            self.importFinished.emit(result["added"])
        self.importChanged.emit()

    @Slot()
    def shutdown(self):
        self._timer.stop()


def _lastfm_key():
    import os
    key = os.environ.get("MUSICPLAYER_LASTFM_API_KEY", "").strip()
    if key:
        return key
    try:
        from .scrobbling import KEYRING_SERVICE as svc
        return keyring.get_password(svc, "api_key") or ""
    except Exception:  # noqa: BLE001
        return ""
