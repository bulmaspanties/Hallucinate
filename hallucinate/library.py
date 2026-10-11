import logging
import os
import random
import threading
from concurrent.futures import ThreadPoolExecutor

from PySide6.QtCore import Property, QFileSystemWatcher, QObject, QTimer, QUrl, Signal, Slot

from .core import albums as album_views
from .core import health as health_checks
from .core.db import Database, fold
from .core.radio import radio_tracks
from .core.scanner import Scanner
from .core.tags import AUDIO_EXTS, find_folder_art, read_track
from .models import ALBUM_KEYS, ARTIST_KEYS, TRACK_KEYS, DictModel, compute_ops

logger = logging.getLogger(__name__)

MAX_WATCHED_DIRS = 2000
DUPLICATE_KEYS = [*TRACK_KEYS, "duplicateCount"]
WALL_KEYS = [*ALBUM_KEYS, "color"]
MAX_DROPPED_TRACKS = 5000


def _audio_files(folder):
    """Audio files under `folder`, grouped by directory in path order."""
    found = []
    visited = set()
    for root, dirs, files in os.walk(folder, followlinks=True):
        real = os.path.realpath(root)
        if real in visited:
            dirs[:] = []
            continue
        visited.add(real)
        dirs[:] = sorted(d for d in dirs if not d.startswith("."))
        found.extend(
            os.path.join(root, name) for name in sorted(files)
            if not name.startswith(".") and os.path.splitext(name)[1].lower() in AUDIO_EXTS
        )
        if len(found) >= MAX_DROPPED_TRACKS:
            break
    return found


def resolve_dropped(db, paths, limit=MAX_DROPPED_TRACKS):
    """Turn dropped files and folders into playable tracks, in drop order.

    Folder contents are ordered by directory, then disc and track number. Files already in the library use
    their library entry; others are read from their tags so they can be played without being added."""
    tracks = []
    for path in paths:
        if len(tracks) >= limit:
            break
        if os.path.isdir(path):
            group = [t for t in (_dropped_track(db, f) for f in _audio_files(path)) if t]
            group.sort(key=lambda t: (os.path.dirname(t["path"]), t.get("disc_no") or 0, t.get("track_no") or 0,
                                      t["path"]))
            tracks.extend(group)
        elif os.path.isfile(path) and os.path.splitext(path)[1].lower() in AUDIO_EXTS:
            t = _dropped_track(db, path)
            if t:
                tracks.append(t)
    return decorate(tracks[:limit])


def _dropped_track(db, path):
    known = db.track_by_path(path)
    if known:
        return known
    t = read_track(path, art_known=lambda _key: True)
    if t is None:
        return None
    t.pop("_art", None)
    t["id"] = -1
    t["art"] = find_folder_art(os.path.dirname(path))
    return t


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
    _filtered = Signal(object)
    _duplicates_loaded = Signal(object)
    _dropped = Signal(object)
    _wall_loaded = Signal(object)
    _health_loaded = Signal(object)
    healthChanged = Signal()
    timelineChanged = Signal()
    wallChanged = Signal()
    foldersChanged = Signal()
    filtersChanged = Signal()
    duplicatesChanged = Signal()
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
            "filteredTracks": DictModel(TRACK_KEYS, self, "id"),
            "duplicates": DictModel(DUPLICATE_KEYS, self, "id"),
            "wall": DictModel(WALL_KEYS, self, "album_key"),
        }
        self._timeline = []
        self._wall_wanted = False
        self._wall_loading = False
        self._wall_gen = 0
        self._health = {}
        self._health_wanted = False
        self._health_loading = False
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
        self._filter_values = {"genres": [], "years": [], "formats": []}
        self._filters = ("", 0, "")
        self._filter_gen = 0
        self._duplicate_gen = 0
        self._duplicates_loading = False
        self._load_gen = 0
        self._search_gen = 0
        self._bulk = _Reader(self._db_path, "lib-bulk")
        self._quick = _Reader(self._db_path, "lib-search")
        self._loaded.connect(self._apply_load)
        self._searched.connect(self._apply_search)
        self._filtered.connect(self._apply_filtered)
        self._duplicates_loaded.connect(self._apply_duplicates)
        self._dropped.connect(self._apply_dropped)
        self._wall_loaded.connect(self._apply_wall)
        self._health_loaded.connect(self._apply_health)
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
    albumWall = _model_prop("wall")
    recentAlbums = _model_prop("recent")
    artists = _model_prop("artists")
    songs = _model_prop("songs")
    searchTracks = _model_prop("sTracks")
    searchAlbums = _model_prop("sAlbums")
    searchArtists = _model_prop("sArtists")
    filteredTracks = _model_prop("filteredTracks")
    duplicates = _model_prop("duplicates")

    @Property(bool, notify=filtersChanged)
    def filtersActive(self):
        return any(self._filters)

    @Property("QVariantList", notify=filtersChanged)
    def genres(self):
        return list(self._filter_values["genres"])

    @Property("QVariantList", notify=filtersChanged)
    def years(self):
        return list(self._filter_values["years"])

    @Property("QVariantList", notify=filtersChanged)
    def formats(self):
        return list(self._filter_values["formats"])

    @Property(bool, notify=duplicatesChanged)
    def duplicatesLoading(self):
        return self._duplicates_loading

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
        if player is not None and hasattr(player, "setRadioSource"):
            player.setRadioSource(self.radioTracks)

    def radioTracks(self, seeds, exclude, done, rules=None, limit=10):
        """Pick radio tracks on the search worker and pass them to `done` (called on that worker)."""
        def work(db):
            try:
                tracks = decorate(radio_tracks(db, seeds, exclude, limit, rules=rules))
            except Exception:  # noqa: BLE001
                logger.exception("Radio could not pick tracks")
                tracks = []
            done(tracks)

        self._quick.submit(work)

    # --- loading -----------------------------------------------------------
    @staticmethod
    def _load_all(db, snapshots):
        data = {
            "albums": decorate(db.albums()),
            "recent": decorate(db.recent_albums()),
            "artists": decorate(db.artists()),
            "songs": decorate(db.tracks()),
            "counts": db.counts(),
            "filterValues": db.filter_values(),
        }
        data["timeline"] = Library._timeline_rows(data["albums"])
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
        self._timeline = data["timeline"]
        self.timelineChanged.emit()
        if self._wall_wanted:
            self.loadAlbumWall()
        if self._health_wanted:
            self.checkHealth()
        self._counts = data["counts"]
        self._filter_values = data["filterValues"]
        self._artist_index = {fold(a["name"]): a for a in data["artists"]}
        self._detail.clear()
        if not self._ready:
            self._ready = True
            self.readyChanged.emit()
        self.changed.emit()
        self.filtersChanged.emit()
        self.reloaded.emit()
        if any(self._filters):
            self.filterTracks(*self._filters)

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

    @Slot("QVariantList", bool)
    def playDropped(self, urls, enqueue=False):
        """Play (or append to the queue) audio files and folders dropped onto the window."""
        paths = []
        for u in urls:
            url = u if isinstance(u, QUrl) else QUrl(str(u))
            if url.isLocalFile():
                paths.append(os.path.normpath(url.toLocalFile()))
        if not paths:
            return

        def work(db):
            try:
                tracks = resolve_dropped(db, paths)
            except Exception:  # noqa: BLE001
                logger.exception("Could not read dropped files")
                tracks = []
            self._dropped.emit((tracks, enqueue))

        self._quick.submit(work)

    @Slot(object)
    def _apply_dropped(self, payload):
        tracks, enqueue = payload
        if self._player is None or not tracks:
            return
        if enqueue:
            self._player.enqueueAll(tracks)
        else:
            self._player.playList(tracks, 0)

    @Slot(str, result="QVariantMap")
    def randomAlbum(self, avoid=""):
        """A random album from the library (not `avoid` when there is a choice), or {} when it is empty."""
        albums = self._models["albums"].items()
        choices = [a for a in albums if a.get("album_key") != avoid] or albums
        return dict(random.choice(choices)) if choices else {}

    @Slot(int)
    def playSongs(self, index):
        self._play(self._models["songs"].items(), index)

    @Slot(int)
    def playSearchTracks(self, index):
        self._play(self._models["sTracks"].items(), index)

    @Slot(str, int, str)
    def filterTracks(self, genre="", year=0, fmt=""):
        filters = (genre.strip(), int(year or 0), fmt.strip())
        self._filters = filters
        self.filtersChanged.emit()
        self._filter_gen += 1
        gen = self._filter_gen
        if not any(self._filters):
            return
        snapshot = self._models["filteredTracks"].snapshot_keys()

        def work(db):
            try:
                rows = decorate(db.filtered_tracks(*filters))
                ops = compute_ops(snapshot[1], [row["id"] for row in rows])
                self._filtered.emit((gen, rows, ops, snapshot[0], ""))
            except Exception as exc:  # noqa: BLE001
                logger.exception("Library filter query failed")
                self._filtered.emit((gen, [], None, None, str(exc)))

        self._quick.submit(work)

    @Slot(object)
    def _apply_filtered(self, payload):
        gen, rows, ops, revision, error = payload
        if gen != self._filter_gen:
            return
        if error:
            self._set_status("Filter failed: " + error)
            return
        self._models["filteredTracks"].update_items(rows, ops, revision)

    @Slot(int)
    def playFilteredSongs(self, index):
        self._play(self._models["filteredTracks"].items(), index)

    @Slot(int)
    def playDuplicate(self, index):
        self._play(self._models["duplicates"].items(), index)

    @Slot()
    def findDuplicates(self):
        self._duplicate_gen += 1
        gen = self._duplicate_gen
        self._duplicates_loading = True
        self.duplicatesChanged.emit()
        snapshot = self._models["duplicates"].snapshot_keys()

        def work(db):
            try:
                rows = decorate(db.duplicate_tracks())
                ops = compute_ops(snapshot[1], [row["id"] for row in rows])
                error = ""
            except Exception as exc:  # noqa: BLE001
                logger.exception("Duplicate detection failed")
                rows, ops, error = [], None, str(exc)
            self._duplicates_loaded.emit((gen, rows, ops, snapshot[0], error))

        self._quick.submit(work)

    @Slot(object)
    def _apply_duplicates(self, payload):
        gen, rows, ops, revision, error = payload
        if gen != self._duplicate_gen:
            return
        self._duplicates_loading = False
        if not error:
            self._models["duplicates"].update_items(rows, ops, revision)
        if error:
            self._set_status("Duplicate detection failed: " + error)
        self.duplicatesChanged.emit()

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

    # --- album views: liner notes, colour wall, timeline ------------------------------------
    @Slot(str, result="QVariantMap")
    def albumNotes(self, key):
        """Liner notes for an album's page (see core.albums.liner_notes)."""
        try:
            return album_views.liner_notes(self._db, key)
        except Exception:  # noqa: BLE001
            logger.exception("Album notes failed")
            return {}

    @Slot(str, result="QVariantList")
    def albumPalette(self, key):
        """Up to three colours from an album's cover, for tinting its page."""
        from .themes import art_palette

        info = self._db.album(key)
        return [c.name() for c in art_palette(info["art"])] if info and info.get("art") else []

    @Property("QVariantList", notify=timelineChanged)
    def timeline(self):
        """Rows for the timeline view: {"kind": "decade", "label", "count"} then {"kind": "year", "year", "albums"}."""
        return self._timeline

    @staticmethod
    def _timeline_rows(albums):
        rows = []
        for decade in album_views.timeline(albums):
            rows.append({"kind": "decade", "label": decade["decade"], "count": decade["count"]})
            rows.extend({"kind": "year", "year": y["year"], "albums": y["albums"]} for y in decade["years"])
        return rows

    @Property(bool, notify=wallChanged)
    def wallLoading(self):
        return self._wall_loading

    @Slot()
    def loadAlbumWall(self):
        """Order the albums by cover colour; covers not seen before are measured once and cached."""
        from .themes import cover_color

        self._wall_wanted = True
        self._wall_gen += 1
        gen = self._wall_gen
        self._wall_loading = True
        self.wallChanged.emit()

        def work(db):
            try:
                albums = decorate(db.albums())
                cache = album_views.cached_colors(db)
                measured = {}
                for a in albums:
                    art = a.get("art") or ""
                    known = cache.get(a["album_key"])
                    if known and known[0] == art:
                        a["cover"] = known[1]
                    elif art:
                        colour = cover_color(art)
                        if colour:
                            a["cover"] = colour
                            measured[a["album_key"]] = (art, colour)
                if measured:
                    album_views.store_colors(db, measured)
                albums.sort(key=album_views.colour_order)
                for a in albums:
                    a["color"] = a.pop("cover", {}).get("color", "")
            except Exception:  # noqa: BLE001
                logger.exception("Colour wall failed")
                albums = []
            self._wall_loaded.emit((gen, albums))

        self._bulk.submit(work)

    @Slot(object)
    def _apply_wall(self, payload):
        gen, albums = payload
        if gen != self._wall_gen:
            return
        self._models["wall"].set_items(albums)
        self._wall_loading = False
        self.wallChanged.emit()

    # --- library health ----------------------------------------------------------------
    @Property("QVariantMap", notify=healthChanged)
    def health(self):
        """The latest health report (see core.health.report), plus "loading"."""
        return {**self._health, "loading": self._health_loading}

    @Slot()
    def checkHealth(self):
        self._health_wanted = True
        self._health_loading = True
        self.healthChanged.emit()

        def work(db):
            try:
                report = health_checks.report(db)
                for check in report["checks"]:
                    if check["kind"] != "folder":
                        decorate(check["items"])
            except Exception:  # noqa: BLE001
                logger.exception("Library health check failed")
                report = {}
            self._health_loaded.emit(report)

        self._bulk.submit(work)

    @Slot(object)
    def _apply_health(self, report):
        self._health = report
        self._health_loading = False
        self.healthChanged.emit()

    def shutdown(self):
        self._bulk.close()
        self._quick.close()
        self._db.close()
