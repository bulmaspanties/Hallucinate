import gc
import logging
import os
import random
import threading
from concurrent.futures import ThreadPoolExecutor

from PySide6.QtCore import Property, QFile, QFileSystemWatcher, QObject, QTimer, QUrl, Signal, Slot
from PySide6.QtGui import QDesktopServices

from .core import albums as album_views
from .core import artists as artist_views
from .core import folders as folder_views
from .core import health as health_checks
from .core import remote
from .core.db import Database, fold, group_index, search_groups
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
    """Add the cover URL and duration label QML shows. Each is worked out once per distinct cover or length, and
    the result shared between rows: a big library has far fewer covers and lengths than songs."""
    urls, labels = {}, {}
    for r in rows:
        art = r.get("art")
        if art:
            url = urls.get(art)
            if url is None:
                url = urls[art] = QUrl.fromLocalFile(art).toString()
            r["artUrl"] = url
        else:
            r["artUrl"] = ""
        d = int(round(r.get("duration") or 0))
        label = labels.get(d)
        if label is None:
            label = labels[d] = fmt_duration(d)
        r["durText"] = label
    return rows


# Text fields that repeat across a library's songs (every song of an album shares its album, artist, genre and
# cover); one shared copy each instead of one per song keeps a quarter-million-song list to a sensible size.
SHARED_FIELDS = ("artist", "album", "album_artist", "album_key", "genre", "fmt", "codec", "art", "file")


def share_strings(rows):
    pool = {}
    for r in rows:
        for f in SHARED_FIELDS:
            v = r.get(f)
            if v.__class__ is str:
                r[f] = pool.setdefault(v, v)
    return rows


def _differs(old, new, chunk=2000):
    """old != new, a slice at a time: comparing a quarter-million rows in one go holds the GIL (and so the
    interface) for a fifth of a second."""
    if len(old) != len(new):
        return True
    return any(old[i:i + chunk] != new[i:i + chunk] for i in range(0, len(new), chunk))


def _free(lists, chunk=5000):
    """Let go of big row lists a slice at a time, so freeing them never holds the interface up for long."""
    for rows in lists:
        while rows:
            del rows[-chunk:]


def _strictly_inside(folder, roots):
    """Whether `folder` is below one of the library folders `roots` (and isn't one of them)."""
    folder = os.path.normcase(os.path.realpath(folder))
    for root in roots:
        root = os.path.normcase(os.path.realpath(root))
        try:
            if folder != root and os.path.commonpath([folder, root]) == root:
                return True
        except ValueError:  # different drives on Windows
            continue
    return False


def _only_leftovers(folder):
    """True when a folder has no subfolders and no music left (just covers, logs, playlists and the like)."""
    try:
        with os.scandir(folder) as it:
            for entry in it:
                if entry.is_dir() or os.path.splitext(entry.name)[1].lower() in AUDIO_EXTS:
                    return False
    except OSError:
        return False
    return True


DETAIL_CACHE = 64


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
    albumsRemoved = Signal("QVariantMap")  # {"kind": "hidden"|"trashed", "albums", "songs", "failed"}
    hiddenChanged = Signal()
    detailChanged = Signal()
    _removed = Signal(object)

    def __init__(self, db_path, art_dir, parent=None):
        super().__init__(parent)
        self._scan_stop = threading.Event()  # set to stop a scan between files
        self._purge_after_scan = []  # folders removed while a scan ran
        self._scan_thread = None
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
            # decade and year rows; a year's albums are handed over only when its row is on screen
            "timeline": DictModel(["kind", "label", "count", "year", "albums"], self),
        }
        self._timeline = []
        self._wall_loading = False
        self._wall_gen = 0
        self._health = {}
        self._health_loading = False
        self._detail = {}  # insertion order = least recently used first
        self._detail_revision = 0
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
        self._search_index = None  # folded album/artist names, built with each load
        self._search_results = {"tracks": [], "albums": [], "artists": []}
        self._bulk = _Reader(self._db_path, "lib-bulk")
        self._quick = _Reader(self._db_path, "lib-search")
        self._loaded.connect(self._apply_load)
        self._searched.connect(self._apply_search)
        self._filtered.connect(self._apply_filtered)
        self._duplicates_loaded.connect(self._apply_duplicates)
        self._dropped.connect(self._apply_dropped)
        self._wall_loaded.connect(self._apply_wall)
        self._health_loaded.connect(self._apply_health)
        self._removed.connect(self._apply_removed)
        self._hidden_count = len(self._db.hidden_paths())
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

    @Property("QVariantMap", notify=searchFinished)
    def searchResults(self):
        """The latest results as plain lists ({"tracks", "albums", "artists"}), handed to QML in one go so
        drawing them needs no further calls into Python (see Rows.qml for why that matters)."""
        return self._search_results
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
            "songs": share_strings(decorate(db.song_list())),
            "counts": db.counts(),
            "filterValues": db.filter_values(),
        }
        data["timeline"] = Library._timeline_rows(data["albums"])
        data["artistIndex"] = {fold(a["name"]): a for a in data["artists"]}
        data["searchIndex"] = group_index(data["albums"], data["artists"])
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
        # shallow copies (cheap) so the worker can tell what changed; rows themselves are never edited in place
        current = {n: list(self._models[n].items()) for n in ("albums", "artists", "songs")}
        state = {"timeline": self._timeline, "filterValues": self._filter_values, "counts": dict(self._counts)}

        def work(db):
            try:
                data = self._load_all(db, snapshots)
                data["changed"] = {n: _differs(current[n], data[n]) for n in current}
                data["changed"].update({k: state[k] != data[k] for k in state})
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
        changed = data["changed"]
        garbage = []
        for name in ("albums", "artists", "songs"):
            revision, ops = data["ops"].get(name, (None, None))
            garbage.append(m[name].update_items(data.pop(name), ops, revision, changed[name]))
        self._bulk.submit(lambda _db, g=garbage: _free(g))
        # The library is millions of long-lived objects that hold no reference cycles. Moving them out of the
        # collector's view stops every later full collection from walking all of them while holding the GIL,
        # which froze the window for a fifth of a second at a time on big libraries. They are still freed
        # normally (by reference count) when a reload replaces them. (Collecting first would cost as much as
        # the pauses this avoids; the most it strands is a few stray cycles per reload.)
        gc.freeze()
        if m["recent"].items() != data["recent"]:
            m["recent"].set_items(data["recent"])
        self._timeline = data["timeline"]
        if changed["timeline"]:
            self._models["timeline"].set_items(data["timeline"])
            self.timelineChanged.emit()
        self._counts = data["counts"]
        self._filter_values = data["filterValues"]
        self._artist_index = data["artistIndex"]
        self._search_index = data["searchIndex"]
        self._retire(list(self._detail.values()))
        self._detail.clear()
        self._detail_revision += 1
        self.detailChanged.emit()  # open album/artist pages fetch fresh models now, before the old ones go
        if not self._ready:
            self._ready = True
            self.readyChanged.emit()
        if changed["counts"] or changed["albums"] or changed["artists"] or changed["songs"]:
            self.changed.emit()
        if changed["filterValues"]:
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
            self._search_results = {"tracks": [], "albums": [], "artists": []}
            self.searchFinished.emit()
            return

        index = self._search_index

        def work(db):
            if gen != self._search_gen:  # typing moved on while this waited in the queue: skip it
                return
            try:
                if index is None:  # before the first load
                    r = db.search(query)
                    r = {k: decorate(v) for k, v in r.items()}
                else:
                    r = db.search(query, groups=False)
                    r["tracks"] = decorate(r["tracks"])
                    albums, artists = search_groups(index, query)  # rows already decorated
                    r["albums"], r["artists"] = [dict(a) for a in albums], [dict(a) for a in artists]
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
        self._search_results = r
        self.searchFinished.emit()

    def _cached(self, key, keys, loader):
        """An album's or artist's songs as a model, kept for the most recent DETAIL_CACHE pages visited."""
        if key in self._detail:
            self._detail[key] = self._detail.pop(key)  # most recently used last
            return self._detail[key]
        model = DictModel(keys, self)
        model.set_items(decorate(loader()))
        self._detail[key] = model
        while len(self._detail) > DETAIL_CACHE:
            self._retire([self._detail.pop(next(iter(self._detail)))])
        return model

    def _retire(self, models):
        """Free models no page binds to any more. They are children of the library, so dropping them from the
        cache alone would keep them alive for the whole session; deleting is deferred a moment so anything
        still finishing with one (a page being popped, a rebinding) is done first."""
        if models:
            QTimer.singleShot(2000, lambda ms=models: [m.deleteLater() for m in ms])

    @Property(int, notify=detailChanged)
    def detailRevision(self):
        """Bumped when cached album/artist models are replaced (after a reload): pages bind through it to
        pick up the fresh ones."""
        return self._detail_revision

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

    @Slot(str, result="QVariantList")
    def artistPaths(self, name):
        """Every song path of an artist (as on their page), for queueing, playlists or removal from a menu."""
        return [t["path"] for t in self._db.artist_tracks(name)]

    @Slot(str, result="QVariantList")
    def folderPaths(self, path):
        """Every song path in a folder and the folders below it, in folder order."""
        return [t["path"] for t in folder_views.tracks_below(self._db, path)]

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
        if self._scanning:
            # The scan would carry on through the removed folder and bring its songs back: stop it, purge
            # again once it has stopped, and scan the folders that remain.
            self._scan_stop.set()
            self._purge_after_scan.append(path)
            self._pending = True

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
        self._scan_stop.clear()
        self._scan_thread = threading.Thread(target=self._scan_worker, args=(folders,), daemon=True)
        self._scan_thread.start()

    def _scan_worker(self, folders):
        try:
            db = Database(self._db_path)
            try:
                scanner = Scanner(db, self._art_dir, progress=self.scanProgress.emit,
                                  should_stop=self._scan_stop.is_set)
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
        for path in self._purge_after_scan:
            self._bulk.submit(lambda db, p=path: db.purge_folder(p))
        if self._purge_after_scan:
            self._purge_after_scan = []
            self.reload()
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

    # --- removing albums ---------------------------------------------------------------------
    @Slot("QVariantList", result="QVariantList")
    def albumPaths(self, keys):
        """Every song path of these albums, in album order."""
        return [t["path"] for k in keys for t in self._db.album_tracks(k)]

    @Property(int, notify=hiddenChanged)
    def hiddenCount(self):
        """Files removed from the library with removeAlbums; rescans leave them out until restoreHidden()."""
        return self._hidden_count

    @Slot("QVariantList")
    def removeAlbums(self, keys):
        """Take albums out of the library, leaving their files where they are."""
        self._hide(self.albumPaths(keys), list(keys))

    @Slot("QVariantList")
    def removeSongs(self, paths):
        """Take songs out of the library, leaving their files where they are (Settings → Library brings them back)."""
        self._hide([str(p) for p in paths if p], [])

    def _hide(self, paths, keys):
        def work(db):
            songs = db.hide_paths(paths)
            self._removed.emit({"kind": "hidden", "albums": len(keys), "songs": songs, "failed": 0,
                                "hidden": len(db.hidden_paths()), "keys": keys, "paths": list(paths)})

        self._bulk.submit(work)  # same single worker as reload(), so the refresh sees the rows gone
        self.reload()

    @Slot()
    def removeExtraCopies(self):
        """Keep the best copy of each set of probable duplicates and take the others out of the library (their
        files stay on disk, and Settings → Library brings them back)."""
        def work(db):
            paths = health_checks.extra_copies(db)
            songs = db.hide_paths(paths)
            self._removed.emit({"kind": "hidden", "albums": 0, "songs": songs, "failed": 0,
                                "hidden": len(db.hidden_paths()), "keys": [], "paths": list(paths)})

        self._bulk.submit(work)
        self.reload()

    @Slot("QVariantList")
    def trashAlbums(self, keys):
        """Move albums' files to the system trash (recoverable from there) and take them out of the library.
        A folder left with no other music and no subfolders goes to the trash too, with its cover and logs."""
        self._trash(self.albumPaths(keys), list(keys))

    @Slot("QVariantList")
    def trashSongs(self, paths):
        """Move songs' files to the system trash and take them out of the library. A song of a CUE sheet shares
        its file with the rest of the sheet, so the whole file goes (the page says so before asking)."""
        self._trash([str(p) for p in paths if p], [])

    def _trash(self, paths, keys):
        roots = {os.path.normpath(f) for f in self._db.folders()}

        def work(db):
            # a song on a music server isn't a file here: it can't go in the trash, and mustn't vanish as if it had
            files = list(dict.fromkeys(db.file_of(p) for p in paths if not remote.is_remote(p)))
            done, failed, dirs = set(), 0, set()
            for f in files:
                if not os.path.exists(f) or QFile.moveToTrash(f):
                    done.add(f)
                    dirs.add(os.path.dirname(f))
                else:
                    failed += 1
            for d in dirs:
                # Only an album's own folder inside your music, never a library folder itself or anything
                # outside it: a song dropped in from ~/Downloads mustn't take Downloads with it.
                if _strictly_inside(d, roots) and _only_leftovers(d):
                    QFile.moveToTrash(d)
            gone = [p for p in paths if db.file_of(p) in done]
            db.remove_paths(gone)
            db.commit()
            self._removed.emit({"kind": "trashed", "albums": len(keys), "songs": len(gone), "failed": failed,
                                "keys": keys})

        self._bulk.submit(work)
        self.reload()

    @Slot(str, result="QVariantMap")
    def trackInfo(self, path):
        """What a song's menu needs to know about it: its album, artist and whether it comes from a CUE sheet."""
        row = self._db.track_by_path(path) or {}
        return {"album_key": row.get("album_key") or "", "album": row.get("album") or "",
                "artist": row.get("artist") or "", "album_artist": row.get("album_artist") or "",
                "cue": bool(row.get("file")), "remote": remote.is_remote(path),
                "exists": (not remote.is_remote(path) and os.path.exists(self._db.file_of(path))) if path else False}

    @Slot(str)
    def showInFolder(self, path):
        """Open the folder holding a song (or a folder itself) in the system's file manager."""
        target = self._db.file_of(path) if path else ""
        folder = target if os.path.isdir(target) else os.path.dirname(target)
        if folder and os.path.isdir(folder):
            QDesktopServices.openUrl(QUrl.fromLocalFile(folder))

    @Slot()
    def restoreHidden(self):
        """Bring back everything removed with removeAlbums (on the next scan, which starts now)."""
        self._db.unhide_all()
        self._hidden_count = 0
        self.hiddenChanged.emit()
        self.rescan()

    @Slot("QVariantList")
    def unhidePaths(self, paths):
        """Undo a "Remove from library": let those songs back in (the scan that starts now finds them)."""
        n = self._db.unhide(paths)
        self._hidden_count = max(0, self._hidden_count - n)
        self.hiddenChanged.emit()
        self.rescan()

    @Slot(object)
    def _apply_removed(self, result):
        for key in result.get("keys", []):
            gone = self._detail.pop(("at", key), None)
            if gone is not None:
                self._retire([gone])
        if "hidden" in result:
            self._hidden_count = result.pop("hidden")
            self.hiddenChanged.emit()
        self.albumsRemoved.emit(result)

    # --- album views: liner notes, colour wall, timeline ------------------------------------
    @Slot(str, result="QVariantMap")
    def folderContents(self, path):
        """One folder of the library (see core.folders.contents); "" lists the library folders."""
        try:
            data = folder_views.contents(self._db, path, self._db.folders())
        except Exception:  # noqa: BLE001
            logger.exception("Folder listing failed")
            return {"path": path, "folders": [], "tracks": [], "crumbs": []}
        for f in data["folders"]:
            f["artUrl"] = QUrl.fromLocalFile(f["art"]).toString() if f["art"] else ""
            f["durText"] = fmt_duration(f["duration"])
        decorate(data["tracks"])
        return data

    @Slot(str, bool)
    def playFolder(self, path, shuffle=False):
        """Play a folder and everything below it, folder by folder."""
        tracks = decorate(folder_views.tracks_below(self._db, path))
        if shuffle and tracks and self._player is not None:
            self._player.setShuffle(True)
        self._play(tracks, random.randrange(len(tracks)) if shuffle and tracks else 0)

    @Slot(str)
    def enqueueFolder(self, path):
        if self._player is not None:
            self._player.enqueueAll(decorate(folder_views.tracks_below(self._db, path)))

    @Slot(str, result="QVariantMap")
    def artistProfile(self, name):
        """Facts, your listening, most played songs, discography by year and "appears on" for an artist page."""
        try:
            data = artist_views.profile(self._db, name)
            decorate(data["topTracks"])
            decorate(data["appearsOn"])
            data["discography"] = artist_views.discography(decorate(self._db.artist_albums(name)))
            return data
        except Exception:  # noqa: BLE001
            logger.exception("Artist profile failed")
            return {}

    @Slot(str, result="QVariantList")
    def artistPalette(self, name):
        """Colours from the artist's picture (their first album cover with art)."""
        from .themes import art_palette

        art = (self.artistInfo(name) or {}).get("art") or ""
        return [c.name() for c in art_palette(art)] if art else []

    @Slot(str)
    def startArtistRadio(self, name):
        """Play the artist's most played song with radio on, so similar music follows."""
        if self._player is None:
            return
        top = artist_views.profile(self._db, name, top=1)["topTracks"]
        if top:
            self._player.setRadio(True)
            self._player.playList(decorate(top), 0)

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

    @Property(QObject, constant=True)
    def timeline(self):
        """A model of rows for the timeline view: {"kind": "decade", "label", "count"} then
        {"kind": "year", "year", "albums"}. A model rather than one big list, so opening the view doesn't convert
        every album of a large library at once."""
        return self._models["timeline"]

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

        self._wall_gen += 1
        gen = self._wall_gen
        self._wall_loading = True
        self.wallChanged.emit()

        def work(db):
            try:
                albums = decorate(db.albums())
                cache = album_views.cached_colors(db)
                measured, seen = {}, {}
                for a in albums:
                    art = a.get("art") or ""
                    known = cache.get(a["album_key"])
                    if known and known[0] == art:
                        a["cover"] = known[1]
                    elif art:
                        if art not in seen:  # several albums can share one cover file
                            seen[art] = cover_color(art)
                        colour = seen[art]
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
        self._scan_stop.set()  # a scan stops between files, not half-way through writing a cover
        if self._scan_thread is not None:
            self._scan_thread.join(timeout=5)
        self._bulk.close()
        self._quick.close()
        self._db.close()
