"""User data exposed to QML: liked songs, playlists and play statistics.

Everything is keyed by file path so it survives rescans. Database work runs on a worker thread; the GUI
thread only applies small result sets to models."""
import logging
import random

from PySide6.QtCore import Property, QObject, Signal, Slot

from .library import _Reader, decorate
from .models import ALBUM_KEYS, TRACK_KEYS, DictModel

logger = logging.getLogger(__name__)
PLAYLIST_KEYS = ["id", "name", "n"]


class UserLibrary(QObject):
    likesChanged = Signal()
    playlistsChanged = Signal()
    playlistOpened = Signal(int)
    _refreshed = Signal(object)
    _playlist_loaded = Signal(object)

    def __init__(self, db_path, player=None, parent=None):
        super().__init__(parent)
        self._reader = _Reader(str(db_path), "userlib")
        self._player = player
        self._liked = set()
        self._likes_revision = 0
        self._playlist_id = -1
        self._playlist_items = []
        self._models = {
            "playlists": DictModel(PLAYLIST_KEYS, self, "id"),
            "liked": DictModel(TRACK_KEYS, self),
            "mostPlayed": DictModel(TRACK_KEYS, self),
            "recentPlayed": DictModel(ALBUM_KEYS, self),
            "playlistTracks": DictModel(TRACK_KEYS, self),
        }
        self._refreshed.connect(self._apply_refresh)
        self._playlist_loaded.connect(self._apply_playlist)
        if player is not None:
            player.played.connect(self.recordPlay)
        self.refresh()

    def _model_prop(name):  # noqa: N805
        return Property(QObject, lambda self: self._models[name], constant=True)

    playlists = _model_prop("playlists")
    likedTracks = _model_prop("liked")
    mostPlayed = _model_prop("mostPlayed")
    recentPlayed = _model_prop("recentPlayed")
    playlistTracks = _model_prop("playlistTracks")

    @Property(int, notify=likesChanged)
    def likesRevision(self):
        return self._likes_revision

    @Property(int, notify=playlistsChanged)
    def currentPlaylist(self):
        return self._playlist_id

    def setPlayer(self, player):
        self._player = player
        player.played.connect(self.recordPlay)

    # --- refresh ------------------------------------------------------------
    def refresh(self):
        def work(db):
            try:
                data = {
                    "liked_paths": db.liked_paths(),
                    "playlists": db.playlists(),
                    "liked": decorate(db.liked_tracks()),
                    "mostPlayed": decorate(db.most_played(10)),
                    "recentPlayed": decorate(db.recently_played_albums(12)),
                }
            except Exception:  # noqa: BLE001
                logger.exception("User library refresh failed")
                return
            self._refreshed.emit(data)

        self._reader.submit(work)

    @Slot(object)
    def _apply_refresh(self, data):
        self._liked = data["liked_paths"]
        m = self._models
        m["playlists"].set_items(data["playlists"])
        m["liked"].set_items(data["liked"])
        m["mostPlayed"].set_items(data["mostPlayed"])
        m["recentPlayed"].set_items(data["recentPlayed"])
        self._likes_revision += 1
        self.likesChanged.emit()
        self.playlistsChanged.emit()

    def _write(self, fn, *args, refresh=True, reload_playlist=False):
        def work(db):
            try:
                fn(db, *args)
            except Exception:  # noqa: BLE001
                logger.exception("User library write failed")
                return
            if reload_playlist and self._playlist_id >= 0:
                self._load_playlist(db, self._playlist_id)

        self._reader.submit(work)
        if refresh:
            self.refresh()

    # --- likes ---------------------------------------------------------------
    @Slot(str, result=bool)
    def isLiked(self, path):
        return path in self._liked

    @Slot(str)
    def toggleLike(self, path):
        if not path:
            return
        liked = path not in self._liked
        (self._liked.add if liked else self._liked.discard)(path)
        self._likes_revision += 1
        self.likesChanged.emit()
        self._write(lambda db, p, v: db.set_liked(p, v), path, liked)

    @Slot(int)
    def playLiked(self, index):
        self._play(self._models["liked"].items(), index)

    @Slot(int)
    def playMostPlayed(self, index):
        self._play(self._models["mostPlayed"].items(), index)

    # --- playlists -------------------------------------------------------------
    @Slot(str, result=int)
    def createPlaylist(self, name):
        """Returns the new id; a single tiny INSERT, so waiting on the worker is imperceptible."""
        pid = self._reader.submit(lambda db: db.create_playlist(name)).result(timeout=10)
        self.refresh()
        return pid

    @Slot(int, str)
    def renamePlaylist(self, pid, name):
        self._write(lambda db, i, n: db.rename_playlist(i, n), pid, name)

    @Slot(int)
    def deletePlaylist(self, pid):
        if pid == self._playlist_id:
            self._playlist_id = -1
            self._models["playlistTracks"].set_items([])
        self._write(lambda db, i: db.delete_playlist(i), pid)

    @Slot(int, str)
    def addToPlaylist(self, pid, path):
        if path:
            self._write(lambda db, i, p: db.playlist_add(i, [p]), pid, path, reload_playlist=True)

    @Slot(int, str)
    def addAlbumToPlaylist(self, pid, album_key):
        def add(db, i, key):
            db.playlist_add(i, [t["path"] for t in db.album_tracks(key)])

        self._write(add, pid, album_key, reload_playlist=True)

    @Slot(str, str, result=int)
    def addToNewPlaylist(self, name, path):
        pid = self.createPlaylist(name)
        self.addToPlaylist(pid, path)
        return pid

    @Slot(int)
    def openPlaylist(self, pid):
        self._playlist_id = pid
        self.playlistsChanged.emit()
        self._reader.submit(lambda db: self._load_playlist(db, pid))

    def _load_playlist(self, db, pid):
        try:
            rows = db.playlist_tracks(pid)
        except Exception:  # noqa: BLE001
            logger.exception("Playlist load failed")
            return
        self._playlist_loaded.emit((pid, decorate(rows)))

    @Slot(object)
    def _apply_playlist(self, payload):
        pid, rows = payload
        if pid != self._playlist_id:
            return
        self._playlist_items = [r.get("item_id") for r in rows]
        self._models["playlistTracks"].set_items(rows)
        self.playlistOpened.emit(pid)

    @Slot(int)
    def removeFromPlaylist(self, index):
        if 0 <= index < len(self._playlist_items):
            item = self._playlist_items[index]
            self._write(lambda db, i: db.playlist_remove_item(i), item, reload_playlist=True)

    @Slot(int, int)
    def moveInPlaylist(self, src, dst):
        pid = self._playlist_id
        if pid >= 0:
            self._write(lambda db, p, a, b: db.playlist_move(p, a, b), pid, src, dst, reload_playlist=True)

    @Slot(int, bool)
    def playPlaylist(self, index, shuffle=False):
        tracks = self._models["playlistTracks"].items()
        if shuffle and tracks:
            index = random.randrange(len(tracks))
            if self._player is not None:
                self._player.setShuffle(True)
        self._play(tracks, index)

    def _play(self, tracks, index=0):
        if self._player is not None and tracks:
            self._player.playList(list(tracks), index)

    # --- per-track actions used by the context menu --------------------------------
    def _track(self, path):
        rows = self._reader.submit(lambda db: db.track_by_path(path)).result(timeout=10)
        return decorate([rows])[0] if rows else None

    @Slot(str)
    def enqueuePath(self, path):
        t = self._track(path)
        if t and self._player is not None:
            self._player.enqueue(t)

    @Slot(str)
    def playNextPath(self, path):
        t = self._track(path)
        if t and self._player is not None:
            self._player.playNext(t)

    # --- play statistics -----------------------------------------------------------
    @Slot("QVariantMap")
    def recordPlay(self, track):
        path = track.get("path") if hasattr(track, "get") else None
        if not path:
            return
        self._write(lambda db, p: db.record_play(p), path)

    def importPlays(self, items, source, done):
        """Merge external listens on the worker thread; call `done(result, error)` when finished."""
        def work(db):
            try:
                res = db.import_plays(items, source)
            except Exception:  # noqa: BLE001
                logger.exception("History import failed")
                done(None, "Could not save imported listening history.")
                return
            done(res, "")
            self.refresh()

        self._reader.submit(work)

    def shutdown(self):
        self._reader.close()
