"""User data exposed to QML: liked songs, playlists and play statistics.

Everything is keyed by file path so it survives rescans. Database work runs on a worker thread; the GUI
thread only applies small result sets to models."""
import json
import logging
import random
import time

from PySide6.QtCore import Property, QObject, Signal, Slot

from .core import insights
from .core import rules as smart_rules
from .library import _Reader, decorate
from .models import ALBUM_KEYS, ARTIST_KEYS, TRACK_KEYS, DictModel

logger = logging.getLogger(__name__)
PLAYLIST_KEYS = ["id", "name", "n"]
SMART_KEYS = ["id", "name", "n", "summary", "rules"]
REASON_ALBUM_KEYS = [*ALBUM_KEYS, "reason"]
STAT_ARTIST_KEYS = [*ARTIST_KEYS, "plays"]
STAT_ALBUM_KEYS = [*ALBUM_KEYS, "plays"]
STAT_TRACK_KEYS = [*TRACK_KEYS, "plays"]


class UserLibrary(QObject):
    likesChanged = Signal()
    playlistsChanged = Signal()
    statsChanged = Signal()
    playlistOpened = Signal(int)
    smartPlaylistOpened = Signal(int)
    homeChanged = Signal()
    _smart_loaded = Signal(object)
    _refreshed = Signal(object)
    _playlist_loaded = Signal(object)
    _stats_loaded = Signal(object)

    def __init__(self, db_path, player=None, parent=None):
        super().__init__(parent)
        self._reader = _Reader(str(db_path), "userlib")
        self._player = player
        self._liked = set()
        self._likes_revision = 0
        self._playlist_id = -1
        self._playlist_items = []
        self._stats_period = "all"
        self._stats_summary = {"listens": 0, "listeningSeconds": 0}
        self._home = {"facts": {}, "heatmap": {}, "topArtists": []}
        self._models = {
            "playlists": DictModel(PLAYLIST_KEYS, self, "id"),
            "liked": DictModel(TRACK_KEYS, self),
            "mostPlayed": DictModel(TRACK_KEYS, self),
            "recentPlayed": DictModel(ALBUM_KEYS, self),
            "playlistTracks": DictModel(TRACK_KEYS, self),
            "smartPlaylists": DictModel(SMART_KEYS, self, "id"),
            "rediscover": DictModel(REASON_ALBUM_KEYS, self),
            "onThisDay": DictModel(REASON_ALBUM_KEYS, self),
            "smartTracks": DictModel(TRACK_KEYS, self),
            "homeMix": DictModel(TRACK_KEYS, self),
            "topArtists": DictModel(STAT_ARTIST_KEYS, self),
            "topAlbums": DictModel(STAT_ALBUM_KEYS, self),
            "topTracks": DictModel(STAT_TRACK_KEYS, self),
        }
        self._refreshed.connect(self._apply_refresh)
        self._playlist_loaded.connect(self._apply_playlist)
        self._smart_loaded.connect(self._apply_smart)
        self._smart_id = -1
        self._smart_rules = None
        self._smart_revision = 0
        self._stats_loaded.connect(self._apply_stats)
        if player is not None:
            player.played.connect(self.recordPlay)
        self.refresh()
        self.refreshStats()

    def _model_prop(name):  # noqa: N805
        return Property(QObject, lambda self: self._models[name], constant=True)

    playlists = _model_prop("playlists")
    smartPlaylists = _model_prop("smartPlaylists")
    rediscover = _model_prop("rediscover")
    onThisDay = _model_prop("onThisDay")
    smartTracks = _model_prop("smartTracks")
    likedTracks = _model_prop("liked")
    mostPlayed = _model_prop("mostPlayed")
    recentPlayed = _model_prop("recentPlayed")
    playlistTracks = _model_prop("playlistTracks")
    homeMix = _model_prop("homeMix")
    topArtists = _model_prop("topArtists")
    topAlbums = _model_prop("topAlbums")
    topTracks = _model_prop("topTracks")

    @Property(str, notify=statsChanged)
    def statsPeriod(self):
        return self._stats_period

    @Property("QVariantMap", notify=statsChanged)
    def statsSummary(self):
        return dict(self._stats_summary)

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
                    "homeMix": decorate(db.home_mix(40)),
                    "smart": self._smart_summaries(db),
                    "rediscover": decorate(insights.rediscover_albums(db)),
                    "onThisDay": decorate(insights.on_this_day(db)),
                    "home": {
                        "facts": insights.library_facts(db),
                        "heatmap": insights.listening_heatmap(db),
                        "topArtists": decorate(insights.top_artists(db)),
                    },
                }
            except Exception:  # noqa: BLE001
                logger.exception("User library refresh failed")
                return
            self._refreshed.emit(data)
            if self._smart_id >= 0:
                self._load_smart(db, self._smart_id)  # smart playlists are live: re-evaluate the open one

        self._reader.submit(work)

    @Slot(object)
    def _apply_refresh(self, data):
        self._liked = data["liked_paths"]
        m = self._models
        m["playlists"].set_items(data["playlists"])
        m["liked"].set_items(data["liked"])
        m["mostPlayed"].set_items(data["mostPlayed"])
        m["recentPlayed"].set_items(data["recentPlayed"])
        m["homeMix"].set_items(data["homeMix"])
        m["smartPlaylists"].set_items(data["smart"])
        m["rediscover"].set_items(data["rediscover"])
        m["onThisDay"].set_items(data["onThisDay"])
        self._home = data["home"]
        self.homeChanged.emit()
        self._smart_revision += 1
        self._likes_revision += 1
        self.likesChanged.emit()
        self.playlistsChanged.emit()

    @Slot(str)
    def setStatsPeriod(self, period):
        if period not in ("all", "7d", "30d", "365d"):
            return
        if period == self._stats_period:
            return
        self._stats_period = period
        self.statsChanged.emit()
        self.refreshStats()

    @Slot()
    def refreshStats(self):
        period = self._stats_period
        starts = {"all": None, "7d": 7, "30d": 30, "365d": 365}
        days = starts[period]
        period_start = None if days is None else time.time() - days * 86400

        def work(db):
            try:
                result = db.listening_stats(period_start)
                payload = (
                    period,
                    result,
                    decorate(result["artists"]),
                    decorate(result["albums"]),
                    decorate(result["tracks"]),
                )
            except Exception:  # noqa: BLE001
                logger.exception("Listening statistics query failed")
                return
            self._stats_loaded.emit(payload)

        self._reader.submit(work)

    @Slot(object)
    def _apply_stats(self, payload):
        period, result, artists, albums, tracks = payload
        if period != self._stats_period:
            return
        self._stats_summary = {
            "listens": int(result["listens"]),
            "listeningSeconds": int(result["listeningSeconds"]),
        }
        self._models["topArtists"].set_items(artists)
        self._models["topAlbums"].set_items(albums)
        self._models["topTracks"].set_items(tracks)
        self.statsChanged.emit()

    @Slot(int)
    def playHomeMix(self, index):
        self._play(self._models["homeMix"].items(), index)

    @Slot(int)
    def playTopTrack(self, index):
        self._play(self._models["topTracks"].items(), index)

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

    @Slot(str, result=int)
    def saveQueueAsPlaylist(self, name):
        """Create a playlist holding the current queue in order; returns its id, or -1 if the queue is empty."""
        paths = [t.get("path") for t in self._player.queue] if self._player is not None else []
        paths = [p for p in paths if p]
        if not name.strip() or not paths:
            return -1
        pid = self.createPlaylist(name.strip())
        self._write(lambda db, i, ps: db.playlist_add(i, ps), pid, paths, reload_playlist=True)
        return pid

    # --- smart playlists ---------------------------------------------------------
    @Property("QVariantMap", constant=True)
    def smartRuleSchema(self):
        return smart_rules.schema()

    @staticmethod
    def _smart_summaries(db):
        out = []
        for row in db.smart_playlists():
            try:
                n = smart_rules.count_matching(db, row["rules"])
                summary = smart_rules.describe(row["rules"])
            except ValueError:
                n, summary = 0, "These rules can no longer be read"
            out.append({**row, "n": n, "summary": summary})
        return out

    @Slot(str, result=str)
    def describeRules(self, rules_json):
        try:
            return smart_rules.describe(rules_json)
        except ValueError as exc:
            return f"Invalid rules: {exc}"

    @Slot(str, result=int)
    def countRules(self, rules_json):
        """How many songs a rule set matches now, or -1 if it is invalid (used for the editor's preview)."""
        try:
            rules = smart_rules.normalize(rules_json)
        except ValueError:
            return -1
        return self._reader.submit(lambda db: smart_rules.count_matching(db, rules)).result(timeout=10)

    @Slot(str, str, result=int)
    def createSmartPlaylist(self, name, rules_json):
        """Returns the new id, or -1 if the name is empty or the rules are invalid."""
        try:
            rules = json.dumps(smart_rules.normalize(rules_json))
        except ValueError:
            return -1
        if not name.strip():
            return -1
        sid = self._reader.submit(lambda db: db.create_smart_playlist(name.strip(), rules)).result(timeout=10)
        self.refresh()
        return sid

    @Slot(int, str, str, result=bool)
    def updateSmartPlaylist(self, sid, name, rules_json):
        try:
            rules = json.dumps(smart_rules.normalize(rules_json))
        except ValueError:
            return False
        if not name.strip():
            return False
        self._write(lambda db, i, n, r: db.update_smart_playlist(i, n, r), sid, name.strip(), rules)
        return True

    @Slot(int)
    def deleteSmartPlaylist(self, sid):
        if sid == self._smart_id:
            self._smart_id = -1
            self._models["smartTracks"].set_items([])
        self._write(lambda db, i: db.delete_smart_playlist(i), sid)

    @Property("QVariantMap", notify=homeChanged)
    def home(self):
        """Library facts, the listening heatmap and this month's top artists for Home."""
        return self._home

    @Property(int, notify=playlistsChanged)
    def smartRevision(self):
        return self._smart_revision

    @Slot(int, result="QVariantMap")
    def smartInfo(self, sid):
        for item in self._models["smartPlaylists"].items():
            if item["id"] == sid:
                return item
        return {"id": sid, "name": "", "n": 0, "summary": "", "rules": ""}

    @Slot(int, result=str)
    def smartRules(self, sid):
        for item in self._models["smartPlaylists"].items():
            if item["id"] == sid:
                return item["rules"]
        return ""

    @Slot(int)
    def openSmartPlaylist(self, sid):
        self._smart_id = sid
        self._reader.submit(lambda db: self._load_smart(db, sid))

    def _load_smart(self, db, sid):
        row = db.smart_playlist(sid)
        rules, tracks = None, []
        if row:
            try:
                rules = smart_rules.normalize(row["rules"])
                tracks = decorate(smart_rules.matching_tracks(db, rules))
            except ValueError:
                logger.warning("Smart playlist %s has invalid rules", sid)
            except Exception:  # noqa: BLE001
                logger.exception("Smart playlist load failed")
        self._smart_loaded.emit((sid, rules, tracks))

    @Slot(object)
    def _apply_smart(self, payload):
        sid, rules, tracks = payload
        if sid != self._smart_id:
            return
        self._smart_rules = rules
        self._models["smartTracks"].set_items(tracks)
        self.smartPlaylistOpened.emit(sid)

    @Slot(int, bool)
    def playSmartPlaylist(self, index, shuffle=False):
        tracks = self._models["smartTracks"].items()
        if not tracks or self._player is None:
            return
        if shuffle:
            index = random.randrange(len(tracks))
            self._player.setShuffle(True)
        # Radio picks stay within the playlist's rules once it runs out.
        self._player.playList(list(tracks), index, radio_rules=self._smart_rules)

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
        self.refreshStats()

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
