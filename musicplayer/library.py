import logging
import os
import threading
from concurrent.futures import ThreadPoolExecutor

from PySide6.QtCore import Property, QFileSystemWatcher, QObject, QTimer, QUrl, Signal, Slot

from .core.db import Database, fold
from .core.scanner import Scanner
from .models import ALBUM_KEYS, ARTIST_KEYS, TRACK_KEYS, DictModel, compute_ops

logger = logging.getLogger(__name__)

MAX_WATCHED_DIRS = 2000


def fmt_duration(seconds) -> str:
    s = int(round(seconds or 0))
    h, rem = divmod(s, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def decorate(rows):
    for r in rows:
        art = r.get("art")
        r["artUrl"] = QUrl.fromLocalFile(art).toString() if art else ""
        r["durText"] = fmt_duration(r.get("duration"))
    return rows


class _Reader:
    """A single worker thread with its own SQLite connection for read queries.

    Keeping reads off the GUI thread is what keeps the UI responsive on very large libraries."""

    def __init__(self, db_path, name):
        self._path = db_path
        self._db = None
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix=name)

    def _conn(self):
        if self._db is None:
            self._db = Database(self._path)
        return self._db

    def submit(self, fn, *args):
        return self._pool.submit(lambda: fn(self._conn(), *args))

    def close(self):
        done = self._pool.submit(lambda: self._db.close() if self._db else None)
        try:
            done.result(timeout=10)
        except Exception:  # noqa: BLE001 - shutting down regardless
            pass
        self._pool.shutdown(wait=False, cancel_futures=True)


class Library(QObject):
    changed = Signal()
    reloaded = Signal()
    searchFinished = Signal()
    readyChanged = Signal()
    scanProgressChanged = Signal()
    scanIssuesChanged = Signal()
    _loaded = Signal(object)
    _searched = Signal(object)
    foldersChanged = Signal()
    scanningChanged = Signal()
    statusChanged = Signal()
    scanProgress = Signal(int)
    scanFinished = Signal(object)

    def __init__(self, db_path, art_dir, parent=None):
        super().__init__(parent)
        self._db_path = str(db_path)
        self._art_dir = str(art_dir)
        self._db = Database(self._db_path)
        self._models = {
            "albums": DictModel(ALBUM_KEYS, self, "album_key"),
            "recent": DictModel(ALBUM_KEYS, self),
            "artists": DictModel(ARTIST_KEYS, self, "name"),
            "songs": DictModel(TRACK_KEYS, self, "id"),
            "sTracks": DictModel(TRACK_KEYS, self),
            "sAlbums": DictModel(ALBUM_KEYS, self),
            "sArtists": DictModel(ARTIST_KEYS, self),
        }
        self._detail = {}
        self._counts = {"tracks": 0, "albums": 0, "artists": 0}
        self._scanning = False
        self._pending = False
        self._status = ""
        self._ready = False
        self._scan_seen = 0
        self._scan_hint = 0
        self._scan_errors = 0
        self._missing = []
        self._player = None
        self._artist_index = {}
        self._load_gen = 0
        self._search_gen = 0
        self._bulk = _Reader(self._db_path, "lib-bulk")
        self._quick = _Reader(self._db_path, "lib-search")
        self._loaded.connect(self._apply_load)
        self._searched.connect(self._apply_search)
        self._watcher = QFileSystemWatcher(self)
        self._watcher.directoryChanged.connect(self._on_dir_changed)
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(3000)
        self._debounce.timeout.connect(self.rescan)
        self.scanFinished.connect(self._on_scan_finished)
        self.scanProgress.connect(self._on_progress)
        self.reload()

    # --- model properties -------------------------------------------------
    def _model_prop(name):  # noqa: N805
        return Property(QObject, lambda self: self._models[name], constant=True)

    albums = _model_prop("albums")
    recentAlbums = _model_prop("recent")
    artists = _model_prop("artists")
    songs = _model_prop("songs")
    searchTracks = _model_prop("sTracks")
    searchAlbums = _model_prop("sAlbums")
    searchArtists = _model_prop("sArtists")

    @Property("QVariantList", notify=foldersChanged)
    def folders(self):
        return self._db.folders()

    @Property(int, notify=changed)
    def trackCount(self):
        return self._counts["tracks"]

    @Property(int, notify=changed)
    def albumCount(self):
        return self._counts["albums"]

    @Property(int, notify=changed)
    def artistCount(self):
        return self._counts["artists"]

    @Property(bool, notify=scanningChanged)
    def scanning(self):
        return self._scanning

    @Property(str, notify=statusChanged)
    def status(self):
        return self._status

    @Property(bool, notify=readyChanged)
    def ready(self):
        """True once the first load from the database has been applied."""
        return self._ready

    @Property(int, notify=scanProgressChanged)
    def scanSeen(self):
        return self._scan_seen

    @Property(int, notify=scanProgressChanged)
    def scanHint(self):
        """Expected number of files (from the previous scan); 0 when unknown."""
        return self._scan_hint

    @Property(float, notify=scanProgressChanged)
    def scanFraction(self):
        return min(1.0, self._scan_seen / self._scan_hint) if self._scan_hint > 0 else -1.0

    @Property("QVariantList", notify=scanIssuesChanged)
    def missingFolders(self):
        return list(self._missing)

    @Property(int, notify=scanIssuesChanged)
    def unreadableFiles(self):
        return self._scan_errors

    @Property(bool, notify=foldersChanged)
    def hasFolders(self):
        return bool(self._db.folders())

    def setPlayer(self, player):
        self._player = player

    # --- loading -----------------------------------------------------------
    @staticmethod
    def _load_all(db, snapshots):
        data = {
            "albums": decorate(db.albums()),
            "recent": decorate(db.recent_albums()),
            "artists": decorate(db.artists()),
            "songs": decorate(db.tracks()),
            "counts": db.counts(),
        }
        data["ops"] = {}
        for name, snap in snapshots.items():
            if snap is None:
                continue
            revision, keys = snap
            field = {"albums": "album_key", "artists": "name", "songs": "id"}[name]
            data["ops"][name] = (revision, compute_ops(keys, [r[field] for r in data[name]]))
        return data

    def reload(self):
        """Refresh all browse models from the database without blocking the GUI thread."""
        self._load_gen += 1
        gen = self._load_gen
        snapshots = {n: self._models[n].snapshot_keys() for n in ("albums", "artists", "songs")}

        def work(db):
            try:
                data = self._load_all(db, snapshots)
            except Exception:  # noqa: BLE001
                logger.exception("Library load failed")
                data = None
            self._loaded.emit((gen, data))

        self._bulk.submit(work)

    @Slot(object)
    def _apply_load(self, payload):
        gen, data = payload
        if data is None or gen != self._load_gen:
            return
        m = self._models
        for name in ("albums", "artists", "songs"):
            revision, ops = data["ops"].get(name, (None, None))
            m[name].update_items(data[name], ops, revision)
        m["recent"].set_items(data["recent"])
        self._counts = data["counts"]
        self._artist_index = {fold(a["name"]): a for a in data["artists"]}
        self._detail.clear()
        if not self._ready:
            self._ready = True
            self.readyChanged.emit()
        self.changed.emit()
        self.reloaded.emit()

    # --- queries used by QML ----------------------------------------------
    @Slot(str)
    def search(self, query):
        """Debounced by the caller; runs on a worker thread and only the latest query is applied."""
        self._search_gen += 1
        gen = self._search_gen
        if not query.strip():
            for n in ("sTracks", "sAlbums", "sArtists"):
                self._models[n].set_items([])
            self.searchFinished.emit()
            return

        def work(db):
            try:
                r = db.search(query)
                r = {k: decorate(v) for k, v in r.items()}
            except Exception:  # noqa: BLE001
                logger.exception("Search failed")
                r = {"tracks": [], "albums": [], "artists": []}
            self._searched.emit((gen, r))

        self._quick.submit(work)

    @Slot(object)
    def _apply_search(self, payload):
        gen, r = payload
        if gen != self._search_gen:
            return
        self._models["sTracks"].set_items(r["tracks"])
        self._models["sAlbums"].set_items(r["albums"])
        self._models["sArtists"].set_items(r["artists"])
        self.searchFinished.emit()

    def _cached(self, key, keys, loader):
        if key not in self._detail:
            model = DictModel(keys, self)
            model.set_items(decorate(loader()))
            self._detail[key] = model
        return self._detail[key]

    @Slot(str, result=QObject)
    def albumTracksModel(self, key):
        return self._cached(("at", key), TRACK_KEYS, lambda: self._db.album_tracks(key))

    @Slot(str, result=QObject)
    def artistAlbumsModel(self, name):
        return self._cached(("aa", name), ALBUM_KEYS, lambda: self._db.artist_albums(name))

    @Slot(str, result=QObject)
    def artistTracksModel(self, name):
        return self._cached(("atr", name), TRACK_KEYS, lambda: self._db.artist_tracks(name, 100))

    @Slot(str, result="QVariantList")
    def albumTracks(self, key):
        return self.albumTracksModel(key).toList()

    @Slot(str, result="QVariantList")
    def artistAllTracks(self, name):
        return decorate(self._db.artist_tracks(name))

    @Slot(str, result="QVariantMap")
    def albumInfo(self, key):
        a = self._db.album(key)
        return decorate([a])[0] if a else {}

    @Slot(str, result="QVariantMap")
    def artistInfo(self, name):
        a = self._artist_index.get(fold(name))
        return dict(a) if a else {"name": name, "albums": 0, "tracks": 0, "artUrl": ""}

    @Slot(result="QVariantList")
    def allTracks(self):
        return self._models["songs"].toList()

    # --- playback entry points (lists stay in Python; converting 50k tracks through QML is slow) ----
    def _play(self, tracks, index=0):
        if self._player is not None and tracks:
            self._player.playList(tracks, index)

    @Slot(int)
    def playSongs(self, index):
        self._play(self._models["songs"].items(), index)

    @Slot(int)
    def playSearchTracks(self, index):
        self._play(self._models["sTracks"].items(), index)

    @Slot(str, int)
    def playAlbum(self, key, index=0):
        self._play(decorate(self._db.album_tracks(key)), index)

    @Slot(str)
    def enqueueAlbum(self, key):
        if self._player is not None:
            self._player.enqueueAll(decorate(self._db.album_tracks(key)))

    @Slot(str, bool)
    def playArtist(self, name, shuffle=False):
        import random

        tracks = decorate(self._db.artist_tracks(name))
        self._play(tracks, random.randrange(len(tracks)) if shuffle and tracks else 0)

    # --- folders & scanning ------------------------------------------------
    @Slot(str)
    def addFolder(self, path):
        if path.startswith("file:"):
            path = QUrl(path).toLocalFile()
        path = os.path.abspath(os.path.expanduser(path.strip()))
        if os.path.isdir(path):
            self._db.add_folder(path)
            self.foldersChanged.emit()
            self.rescan()

    @Slot(str)
    def removeFolder(self, path):
        self._db.forget_folder(path)
        self.foldersChanged.emit()

        def purge(db):
            db.purge_folder(path)

        # Same single worker as reload(), so the refresh runs after the rows are gone.
        self._bulk.submit(purge)
        self.reload()

    @Slot()
    def rescan(self):
        if self._scanning:
            self._pending = True
            return
        folders = self._db.folders()
        if not folders:
            return
        self._scanning = True
        self._scan_seen = 0
        self._scan_hint = self._counts["tracks"]
        self.scanProgressChanged.emit()
        self.scanningChanged.emit()
        self._set_status("Scanning…")
        threading.Thread(target=self._scan_worker, args=(folders,), daemon=True).start()

    def _scan_worker(self, folders):
        try:
            db = Database(self._db_path)
            try:
                scanner = Scanner(db, self._art_dir, progress=self.scanProgress.emit)
                stats = scanner.scan(folders)
            finally:
                db.close()
        except Exception as e:  # keep the UI alive whatever happens
            stats = {"error": str(e), "added": 0, "updated": 0, "removed": 0, "dirs": []}
        self.scanFinished.emit(stats)

    @Slot(int)
    def _on_progress(self, seen):
        self._scan_seen = seen
        self.scanProgressChanged.emit()
        self._set_status(f"Scanning… {seen:,} files")

    def _set_status(self, text):
        if text != self._status:
            self._status = text
            self.statusChanged.emit()

    @Slot(object)
    def _on_scan_finished(self, stats):
        self._scanning = False
        self.scanningChanged.emit()
        self._scan_errors = stats.get("errors", 0)
        self._missing = [f for f in self._db.folders() if not os.path.isdir(f)]
        self.scanIssuesChanged.emit()
        if stats.get("error"):
            self._set_status("Scan failed: " + stats["error"])
        else:
            self._set_status("")
        if stats.get("added") or stats.get("updated") or stats.get("removed") or not self._counts["tracks"]:
            self.reload()
        old = self._watcher.directories()
        if old:
            self._watcher.removePaths(old)
        dirs = stats.get("dirs", [])[:MAX_WATCHED_DIRS]
        if dirs:
            self._watcher.addPaths(dirs)
        if self._pending:
            self._pending = False
            self.rescan()

    def _on_dir_changed(self, _path):
        self._debounce.start()

    def shutdown(self):
        self._bulk.close()
        self._quick.close()
        self._db.close()
