"""Music servers (Settings → Music servers): your Jellyfin, Navidrome or other Subsonic server's songs in the
library.

Their songs go in the library like your own files (albums, artists, search, playlists, stats), with paths
that hold no login (core/remote.py). The sign-in is kept in the system keyring only (a Subsonic password; for
Jellyfin just the access token it gives), never in settings or the library, and is refused when the keyring
would keep it in a plain file. A sync reads every song the server has, a page at a time, adds what's new,
updates what changed and takes out what the server no longer has; covers are fetched once and kept with the
others. A server that can't be reached makes its songs unavailable (the player moves past them) and is tried
again every few minutes. Switched off in Settings → Features, every server song leaves the library (your
plays, ratings and playlists keep them, and they come back when it's switched on again).

Everything that touches the network or the keyring runs on this service's own worker thread, and nothing
holds the library's write lock while waiting on a server."""
import datetime
import json
import logging
import os
import secrets
import threading
import time

from PySide6.QtCore import Property, QObject, QSettings, QTimer, Signal, Slot

from .core import jellyfin, net, remote, subsonic, tags
from .core.atomic import write_atomic
from .library import _Reader

logger = logging.getLogger(__name__)
KEYRING_SERVICE = "Hallucinate Music servers"
KINDS = ("subsonic", "jellyfin")
RETRY_MS = 5 * 60 * 1000  # a server that didn't answer is tried again this often
SYNC_EVERY_S = 12 * 3600  # synced again when the last sync is older than this
PNG = b"\x89PNG\r\n\x1a\n"


class Stopped(Exception):
    """A sync was told to stop (the app is closing, or the server was removed or switched off)."""


class KeyringUnsafe(Exception):
    pass


def _when(text):
    try:
        return datetime.datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp() if text else 0.0
    except (ValueError, OSError, OverflowError):
        return 0.0


def track_row(server_id, song, kind="subsonic"):
    """A library row for a song a server listed (see subsonic.song_from and jellyfin.song_from)."""
    album_artist = song["album_artist"] or song["artist"]
    # Its own album, not merged with a copy you have as files (or one on another server)
    key_base = f"{album_artist}\x1e{kind}:{server_id}" if album_artist else f"\x1e{kind}:{server_id}:{song['album_id']}"
    fmt = song["suffix"].upper() or "STREAM"
    return {
        "path": remote.make_path(kind, server_id, song["id"]),
        "mtime": _when(song["changed"]), "size": song["size"],
        "title": song["title"], "artist": song["artist"] or album_artist, "album_artist": album_artist,
        "aa_tag": 1 if album_artist else 0, "album": song["album"],
        "album_key": tags.album_key(key_base, song["album"], ""),
        "track_no": song["track_no"], "disc_no": song["disc_no"], "year": song["year"], "genre": song["genre"],
        "duration": song["duration"], "fmt": fmt, "codec": fmt, "bitrate": song["bitrate"],
        "sample_rate": song["sample_rate"], "art": None, "rg_track": song["rg_track"],
        "rg_album": song["rg_album"], "rg_peak": song["rg_peak"], "file": None, "rating": song["rating"],
    }


def _keyring():
    """The system keyring, or KeyringUnsafe when it would keep secrets in a plain file (or nowhere)."""
    import keyring

    backend = keyring.get_keyring()
    name = f"{type(backend).__module__}.{type(backend).__name__}"
    try:
        priority = float(getattr(backend, "priority", 1))
    except Exception:  # noqa: BLE001 - some backends compute it and may fail
        priority = 1
    if name.startswith(("keyrings.alt", "keyring.backends.null", "keyring.backends.fail")) or priority <= 0:
        raise KeyringUnsafe(name)
    return keyring


def _client(entry, secret):
    """The client for a kept server: Subsonic with its password, Jellyfin with its token."""
    if entry.get("kind") == "jellyfin":
        kept = json.loads(secret)
        if not isinstance(kept, dict):
            raise ValueError("The kept sign-in is damaged")
        return jellyfin.Server(entry["base"], kept.get("token", ""), kept.get("user_id", ""),
                               entry.get("device") or "hallucinate")
    return subsonic.Server(entry["base"], entry.get("user", ""), secret)


def _plain(exc):
    if isinstance(exc, (subsonic.SubsonicError, jellyfin.JellyfinError, ValueError)):
        return str(exc)
    return net.describe(exc)


def _quietly(fn, *args):
    try:
        fn(*args)
    except (OSError, ValueError):
        pass


class Servers(QObject):
    changed = Signal()
    message = Signal(str)
    libraryChanged = Signal()  # server songs were added or taken out: reload the library
    _done = Signal(object)

    def __init__(self, db_path, art_dir, player=None, parent=None):
        super().__init__(parent)
        self._settings = QSettings("hallucinate", "hallucinate")
        self._art_dir = str(art_dir)
        self._worker = _Reader(str(db_path), "servers")
        self._enabled = False
        self._applied = False  # the first setEnabled also tidies up after a run that ended with them on
        self._cleared = False  # server songs were taken out (switched off): switching on syncs again
        self._state = {}  # server id -> {"status", "busy", "songs", "error"}
        self._clients = {}  # server id -> client (holding the sign-in, in memory only)
        self._pending = {}  # server id -> (base, user, kind) being added
        self._quit = threading.Event()
        self._cancelled = set()  # server ids whose running sync should stop
        try:
            kept = json.loads(self._settings.value("servers/list", "[]") or "[]")
        except (TypeError, ValueError):
            kept = []
        self._list = [self._tidy(s) for s in kept if isinstance(s, dict) and s.get("id") and s.get("base")]
        self._done.connect(self._finish)
        self._retry = QTimer(self)
        self._retry.setInterval(RETRY_MS)
        self._retry.timeout.connect(self._retry_down)
        self._player = player
        if player is not None and hasattr(player, "played"):
            player.played.connect(self._played)

    @staticmethod
    def _tidy(s):
        """A kept server as checked values (an older or hand-edited list mustn't break anything)."""
        def number(v):
            try:
                return float(v or 0)
            except (TypeError, ValueError):
                return 0.0

        kind = s.get("kind") if s.get("kind") in KINDS else "subsonic"
        return {"id": str(s["id"])[:32], "kind": kind, "base": str(s["base"]), "user": str(s.get("user") or ""),
                "name": str(s.get("name") or "")[:100], "songs": int(number(s.get("songs"))),
                "synced": number(s.get("synced")), "device": str(s.get("device") or "")}

    def _entry(self, sid):
        return next((s for s in self._list if s["id"] == sid), None)

    # --- what Settings shows -------------------------------------------------------------------------------
    @Property("QVariantList", notify=changed)
    def servers(self):
        out = []
        for s in self._list:
            st = self._state.get(s["id"], {})
            out.append({"id": s["id"], "name": s["name"] or s["base"], "base": s["base"], "user": s["user"],
                        "kind": s["kind"], "status": st.get("status", "waiting"), "busy": bool(st.get("busy")),
                        "songs": int(st.get("songs", s["songs"]) or 0), "error": st.get("error", ""),
                        "synced": s["synced"], "secure": subsonic.is_private_link(s["base"])})
        return out

    @Property(bool, notify=changed)
    def busy(self):
        return bool(self._pending) or any(st.get("busy") for st in self._state.values())

    @Slot(str, result=bool)
    def linkIsSecure(self, base):
        """For the add dialog: whether the typed link is https or on your own network."""
        try:
            return subsonic.is_private_link(subsonic.normalise_base(base))
        except ValueError:
            return True  # nothing to warn about yet

    # --- switching on and off ------------------------------------------------------------------------------
    @Slot(bool)
    def setEnabled(self, on):
        on = bool(on)
        if on == self._enabled and self._applied:
            return
        self._applied = True
        self._enabled = on
        if on:
            known = {(s["kind"], s["id"]) for s in self._list}
            self._run(lambda db: self._take_out(db, lambda kind, sid: (kind, sid) not in known))  # removed ones
            for s in self._list:
                self._cancelled.discard(s["id"])
                self._connect(s, sync=self._cleared or time.time() - s["synced"] > SYNC_EVERY_S)
            self._cleared = False
        else:
            self._retry.stop()
            for s in self._list:
                self._cancelled.add(s["id"])
                self._disconnect(s["id"])
            self._cleared = True
            self._run(lambda db: self._take_out(db, None))  # every server song, listed server or not
        self.changed.emit()

    def _connect(self, s, sync=False):
        """Read the sign-in from the keyring and check the server (on the worker), then sync if asked."""
        sid = s["id"]
        self._state[sid] = {**self._state.get(sid, {}), "busy": True, "status": "syncing" if sync else "checking"}
        entry = dict(s)

        def work(db):
            try:
                secret = _keyring().get_password(KEYRING_SERVICE, sid)
            except Exception:  # noqa: BLE001 - KeyringUnsafe, or a keyring that won't open
                secret = None
            if secret is None:
                return {"op": "check", "id": sid, "ok": False, "fatal": True,
                        "error": "The sign-in isn't in the system keyring: remove the server and add it again"}
            try:
                client = _client(entry, secret)
            except (ValueError, KeyError, TypeError) as exc:
                return {"op": "check", "id": sid, "ok": False, "fatal": True, "error": str(exc) or "Damaged sign-in"}
            return self._check_work(db, sid, entry["kind"], client, sync)

        self._run(work)

    def _disconnect(self, sid):
        entry = self._entry(sid)
        remote.forget(entry["kind"] if entry else "subsonic", sid)
        self._clients.pop(sid, None)
        self._state.pop(sid, None)

    # --- adding and removing -------------------------------------------------------------------------------
    @Slot(str, str, str, str)
    @Slot(str, str, str, str, str)
    def addServer(self, base, user, password, name="", kind="subsonic"):
        """Check the link and sign-in, keep the sign-in in the keyring, and read the server's songs. For Subsonic
        that's the password (each request signs in with a one-time code made from it); for Jellyfin, the access
        token the server gives for it (the password isn't kept)."""
        if kind not in KINDS:
            return
        try:
            base = subsonic.normalise_base(base)
        except ValueError as exc:
            self.message.emit(str(exc))
            return
        if not user or not password:
            self.message.emit("Type the user name and password you sign in to the server with")
            return
        taken = [(s["base"], s["user"], s["kind"]) for s in self._list] + list(self._pending.values())
        if (base, user, kind) in taken:
            self.message.emit("That server is already added")
            return
        if net.is_offline():
            self.message.emit("Offline mode is on, so the server can't be checked")
            return
        sid = secrets.token_hex(4)  # never reused: old plays and playlists can't point at another server's songs
        self._pending[sid] = (base, user, kind)
        self.changed.emit()
        entry = {"id": sid, "kind": kind, "base": base, "user": user, "name": (name or "").strip()[:100],
                 "songs": 0, "synced": 0.0, "device": secrets.token_hex(8)}

        def work(_db):
            try:
                if kind == "jellyfin":
                    client, token, user_id = jellyfin.Server.sign_in(base, user, password, entry["device"])
                    info = client.ping()
                    secret = json.dumps({"token": token, "user_id": user_id})
                else:
                    client = subsonic.Server(base, user, password)
                    info = client.ping()
                    secret = password
            except (subsonic.SubsonicError, jellyfin.JellyfinError) as exc:
                return {"op": "add", "id": sid, "error": f"Couldn't sign in: {exc}"}
            except (OSError, ValueError) as exc:
                return {"op": "add", "id": sid, "error": f"Couldn't reach the server: {_plain(exc)}"}
            try:
                _keyring().set_password(KEYRING_SERVICE, sid, secret)
            except Exception:  # noqa: BLE001 - KeyringUnsafe, or a keyring that won't take it
                if isinstance(client, jellyfin.Server):
                    _quietly(client.sign_out)  # don't leave a sign-in on the server that nothing here holds
                return {"op": "add", "id": sid,
                        "error": "There's no safe system keyring to keep the sign-in in, so the server wasn't added"}
            if not entry["name"]:
                entry["name"] = (info.get("type") or kind).title()
            return {"op": "add", "id": sid, "entry": entry}

        self._run(work)

    @Slot(str)
    def removeServer(self, sid):
        """Forget a server: its songs leave the library and its sign-in leaves the keyring (and, for Jellyfin, is
        signed out on the server when it can be reached)."""
        entry = self._entry(sid)
        if entry is None:
            return
        self._cancelled.add(sid)
        self._disconnect(sid)
        self._list = [s for s in self._list if s["id"] != sid]
        self._save_list()

        def work(db):
            try:
                kr = _keyring()
                secret = kr.get_password(KEYRING_SERVICE, sid)
                if entry["kind"] == "jellyfin" and secret:
                    _quietly(_client(entry, secret).sign_out)
                kr.delete_password(KEYRING_SERVICE, sid)
            except Exception:  # noqa: BLE001 - not there, or no keyring: nothing to remove
                pass
            return self._take_out(db, lambda kind, s: s == sid)

        self._run(work)
        self.changed.emit()

    @Slot(str)
    def sync(self, sid):
        entry = self._entry(sid)
        if entry is not None and self._enabled and not self._state.get(sid, {}).get("busy"):
            self._cancelled.discard(sid)
            if sid in self._clients:
                self._check(sid, sync=True)
            else:
                self._connect(entry, sync=True)

    @Slot()
    def syncAll(self):
        for s in self._list:
            self.sync(s["id"])

    @Slot()
    def recheck(self):
        """Offline mode was switched off (or settings changed): try servers that couldn't be reached again."""
        if self._enabled and not net.is_offline():
            self._retry_down()

    # --- the work ------------------------------------------------------------------------------------------
    def _check(self, sid, sync):
        client, entry = self._clients.get(sid), self._entry(sid)
        if client is None or entry is None:
            return
        self._state[sid] = {**self._state.get(sid, {}), "busy": True, "status": "syncing" if sync else "checking"}
        self.changed.emit()
        kind = entry["kind"]
        self._run(lambda db: self._check_work(db, sid, kind, client, sync))

    def _check_work(self, db, sid, kind, client, sync):
        """On the worker: ping the server and, if asked, sync it."""
        try:
            client.ping()
        except net.OfflineError:
            return {"op": "check", "id": sid, "ok": True, "client": client, "kind": kind, "offline": True}
        except (OSError, ValueError) as exc:
            return {"op": "check", "id": sid, "ok": False, "client": client, "kind": kind, "error": _plain(exc)}
        result = {"op": "check", "id": sid, "ok": True, "client": client, "kind": kind}
        if sync:
            try:
                result.update(songs=self._sync(db, sid, kind, client), synced=time.time())
            except Stopped:
                pass
            except (OSError, ValueError) as exc:
                result["error"] = f"The sync stopped: {_plain(exc)}"
        return result

    def _stop_check(self, sid):
        if self._quit.is_set() or sid in self._cancelled:
            raise Stopped()

    def _sync(self, db, sid, kind, client):
        """Bring the library in line with the server. Each page is written in one short transaction, so
        nothing waits on the library while the next page comes over the network."""
        prefix = remote.prefix(kind, sid)
        before = {r[0] for r in db.conn.execute("SELECT path FROM tracks WHERE substr(path, 1, ?) = ?",
                                                (len(prefix), prefix))}
        hidden = db.hidden_paths()
        seen, covers = set(), {}
        for page in client.pages(should_stop=lambda: self._quit.is_set() or sid in self._cancelled):
            self._stop_check(sid)
            for song in page:
                row = track_row(sid, song, kind)
                if row["path"] in hidden:  # you removed it from the library
                    continue
                seen.add(row["path"])
                if song["cover"]:
                    covers.setdefault(row["album_key"], song["cover"])
                db.upsert_track(row)
            db.commit()
        self._stop_check(sid)
        gone = sorted(before - seen)
        if gone and not seen:
            # An empty answer is far more likely a hiccup than a server with no music left: keep what's here.
            raise ValueError("the server listed no songs, so nothing was taken out")
        db.remove_paths(gone)
        db.finalize()
        db.commit()
        self._fetch_covers(db, sid, client, covers)
        return len(seen)

    def _fetch_covers(self, db, sid, client, covers):
        """Each album's cover, fetched once and kept with the others (a cover you chose stays yours). Nothing
        is written while a cover comes over the network; each one is recorded in its own short write."""
        os.makedirs(self._art_dir, exist_ok=True)
        for key, cover_id in covers.items():
            self._stop_check(sid)
            chosen = db.chosen_art(key)
            if chosen and os.path.isfile(chosen):
                path = chosen
            else:
                path = next((p for p in (os.path.join(self._art_dir, key + ext) for ext in (".jpg", ".png"))
                             if os.path.isfile(p)), "")
                if not path:
                    try:
                        data = client.cover(cover_id)
                    except (OSError, ValueError):
                        continue
                    if not data:
                        continue
                    path = os.path.join(self._art_dir, key + (".png" if data[:8] == PNG else ".jpg"))
                    write_atomic(path, lambda fh, d=data: fh.write(d))
            db.set_album_art(key, path)
            db.commit()

    def _take_out(self, db, which):
        """Take server songs out of the library: those whose (kind, server id) `which` says yes to (None: every
        server's)."""
        rows = [r[0] for r in db.conn.execute(f"SELECT path FROM tracks WHERE NOT ({remote.SQL_LOCAL})")]
        paths = []
        for p in rows:
            parts = remote.parse(p)
            if which is None or (parts and which(parts[0], parts[1])):
                paths.append(p)
        if paths:
            db.remove_paths(paths)
            db.commit()
            return {"op": "removed"}
        return {"op": "noop"}

    def _run(self, work):
        def wrapped(db):
            try:
                result = work(db)
            except Exception as exc:  # noqa: BLE001 - a worker must always report back
                logger.exception("Music server work failed")
                result = {"op": "failed", "error": _plain(exc)}
            self._done.emit(result or {"op": "noop"})

        self._worker.submit(wrapped)

    @Slot(object)
    def _finish(self, r):
        op, sid = r.get("op"), r.get("id")
        if op == "removed":
            self.libraryChanged.emit()
            return
        if op == "add":
            self._pending.pop(sid, None)
            if r.get("error"):
                self.message.emit(r["error"])
                self.changed.emit()
                return
            entry = r["entry"]
            self._list.append(entry)
            self._save_list()
            self.message.emit(f"Added {entry['name']}: reading its songs…")
            if self._enabled:
                self._connect(entry, sync=True)
            self.changed.emit()
            return
        if op == "check":
            entry = self._entry(sid)
            if entry is None or not self._enabled:  # removed or switched off meanwhile: nothing to keep
                return
            if r.get("client") is not None and r["ok"]:
                self._clients[sid] = r["client"]
                remote.register(r["kind"], sid, r["client"])
            st = self._state.setdefault(sid, {})
            st["busy"] = False
            if r.get("offline"):
                st["status"], st["error"] = "ok", ""  # offline mode, not the server: its songs wait for that
            else:
                remote.set_reachable(entry["kind"], sid, r["ok"])
                st["status"] = "error" if r.get("fatal") else "ok" if r["ok"] else "down"
                st["error"] = r.get("error", "")
                if not r["ok"] and not r.get("fatal"):
                    self._retry.start()
            if "songs" in r:
                st["songs"] = entry["songs"] = r["songs"]
                entry["synced"] = r["synced"]
                self._save_list()
                self.libraryChanged.emit()
            self.changed.emit()
            return
        if op == "failed":
            for st in self._state.values():
                st["busy"] = False
            self.message.emit(f"Music server: {r['error']}")
            self.changed.emit()

    @Slot()
    def _retry_down(self):
        down = [sid for sid, st in self._state.items() if st.get("status") == "down" and self._entry(sid)]
        if not down:
            self._retry.stop()
        for sid in down:
            entry = self._entry(sid)
            due = time.time() - entry["synced"] > SYNC_EVERY_S  # it may have missed its sync while down
            if sid in self._clients:
                self._check(sid, sync=due)
            else:
                self._connect(entry, sync=due)

    @Slot(object)
    def _played(self, track):
        """A server song you played counts on the server too (its own play counts and history)."""
        parts = remote.parse(track.get("path", "")) if isinstance(track, dict) else None
        client = self._clients.get(parts[1]) if parts else None
        if client is None or not remote.available(track["path"]):
            return
        when = int(time.time() * 1000)

        def work(_db, c=client, i=parts[2]):
            _quietly(c.scrobble, i, when)
            return {"op": "noop"}

        self._run(work)

    # --- keeping things ------------------------------------------------------------------------------------
    def _save_list(self):
        keep = [{k: s[k] for k in ("id", "kind", "base", "user", "name", "songs", "synced", "device")}
                for s in self._list]
        self._settings.setValue("servers/list", json.dumps(keep))

    def shutdown(self):
        self._quit.set()  # a running sync stops at the next page or cover
        self._retry.stop()
        self._worker.close()
