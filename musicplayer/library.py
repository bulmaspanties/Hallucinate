import os
import threading

from PySide6.QtCore import (Property, QFileSystemWatcher, QObject, QTimer, QUrl, Signal, Slot)

from .core.db import Database
from .core.scanner import Scanner
from .models import ALBUM_KEYS, ARTIST_KEYS, TRACK_KEYS, DictModel

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


class Library(QObject):
    changed = Signal()
    foldersChanged = Signal()
    scanningChanged = Signal()
    statusChanged = Signal()
    scanProgress = Signal(str)
    scanFinished = Signal(object)

    def __init__(self, db_path, art_dir, parent=None):
        super().__init__(parent)
        self._db_path = str(db_path)
        self._art_dir = str(art_dir)
        self._db = Database(self._db_path)
        self._models = {
            "albums": DictModel(ALBUM_KEYS, self),
            "recent": DictModel(ALBUM_KEYS, self),
            "artists": DictModel(ARTIST_KEYS, self),
            "songs": DictModel(TRACK_KEYS, self),
            "sTracks": DictModel(TRACK_KEYS, self),
            "sAlbums": DictModel(ALBUM_KEYS, self),
            "sArtists": DictModel(ARTIST_KEYS, self),
        }
        self._detail = {}
        self._counts = {"tracks": 0, "albums": 0, "artists": 0}
        self._scanning = False
        self._pending = False
        self._status = ""
        self._watcher = QFileSystemWatcher(self)
        self._watcher.directoryChanged.connect(self._on_dir_changed)
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(3000)
        self._debounce.timeout.connect(self.rescan)
        self.scanFinished.connect(self._on_scan_finished)
        self.scanProgress.connect(self._set_status)
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

    # --- loading -----------------------------------------------------------
    def reload(self):
        db = self._db
        m = self._models
        m["albums"].set_items(decorate(db.albums()))
        m["recent"].set_items(decorate(db.recent_albums()))
        m["artists"].set_items(decorate(db.artists()))
        m["songs"].set_items(decorate(db.tracks()))
        self._counts = db.counts()
        self._detail.clear()
        self.changed.emit()

    # --- queries used by QML ----------------------------------------------
    @Slot(str)
    def search(self, query):
        r = self._db.search(query)
        self._models["sTracks"].set_items(decorate(r["tracks"]))
        self._models["sAlbums"].set_items(decorate(r["albums"]))
        self._models["sArtists"].set_items(decorate(r["artists"]))

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
        for a in self._db.artists():
            if a["name"].lower() == name.lower():
                return decorate([a])[0]
        return {"name": name, "albums": 0, "tracks": 0, "artUrl": ""}

    @Slot(result="QVariantList")
    def allTracks(self):
        return self._models["songs"].toList()

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
        self._db.remove_folder(path)
        self.foldersChanged.emit()
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
        self.scanningChanged.emit()
        self._set_status("Scanning…")
        threading.Thread(target=self._scan_worker, args=(folders,), daemon=True).start()

    def _scan_worker(self, folders):
        try:
            db = Database(self._db_path)
            try:
                scanner = Scanner(
                    db, self._art_dir, progress=lambda n: self.scanProgress.emit(f"Scanning… {n} files")
                )
                stats = scanner.scan(folders)
            finally:
                db.close()
        except Exception as e:  # keep the UI alive whatever happens
            stats = {"error": str(e), "added": 0, "updated": 0, "removed": 0, "dirs": []}
        self.scanFinished.emit(stats)

    @Slot(str)
    def _set_status(self, text):
        if text != self._status:
            self._status = text
            self.statusChanged.emit()

    @Slot(object)
    def _on_scan_finished(self, stats):
        self._scanning = False
        self.scanningChanged.emit()
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
        self._db.close()
