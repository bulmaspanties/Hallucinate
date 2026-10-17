"""User data exposed to QML: liked songs, playlists and play statistics.

Everything is keyed by file path so it survives rescans. Database work runs on a worker thread; the GUI
thread only applies small result sets to models."""
import json
import logging
import os
import random
import sqlite3
import time

from PySide6.QtCore import Property, QObject, QSettings, QUrl, Signal, Slot

from .core import history, insights, player_import, playlist_files, recap
from .core import rules as smart_rules
from .core.db import fold
from .library import _Reader, decorate
from .models import ALBUM_KEYS, ARTIST_KEYS, TRACK_KEYS, DictModel

logger = logging.getLogger(__name__)
PLAYLIST_KEYS = ["id", "name", "n"]
SMART_KEYS = ["id", "name", "n", "summary", "rules"]
REASON_ALBUM_KEYS = [*ALBUM_KEYS, "reason"]
STAT_ARTIST_KEYS = [*ARTIST_KEYS, "plays"]
STAT_ALBUM_KEYS = [*ALBUM_KEYS, "plays"]
STAT_TRACK_KEYS = [*TRACK_KEYS, "plays"]
HISTORY_KEYS = ["id", "ts", "day", "dayLabel", "time", "title", "artist", "album", "album_key", "path", "artUrl", "duration",
                "durText", "source", "available"]
HISTORY_PAGE = 200
HISTORY_WEEKS = 53


def _write_ratings(db, paths, stars):
    """Put a rating in each song's tags. Songs that can't hold one (CUE sheet songs, read-only files, formats
    without rating tags) keep it in the library only, as before."""
    from .core import cue, tagedit

    for path in paths:
        if cue.is_virtual(path) or not os.path.isfile(path):
            continue
        try:
            tagedit.write_rating(path, stars)
            st = os.stat(path)
            # only the rating changed: the library's row, its loudness and waveform stay right for the file
            db.carry_file_caches(path, st.st_mtime, st.st_size)
            db.commit()
        except tagedit.TagWriteError as exc:
            logger.debug("Rating kept in the library only: %s", exc)
        except OSError as exc:
            logger.debug("Rating kept in the library only: %s", exc)


class UserLibrary(QObject):
    likesChanged = Signal()
    likeChanged = Signal(object, bool)  # [(artist, title)] liked or unliked by you (Last.fm loves follow it)
    lovesMatched = Signal(int)  # how many songs a Last.fm loves import liked
    _matched_loves = Signal(object)
    playlistsChanged = Signal()
    statsChanged = Signal()
    playlistOpened = Signal(int)
    smartPlaylistOpened = Signal(int)
    homeChanged = Signal()
    historyChanged = Signal()
    _history_loaded = Signal(object)
    _history_requery = Signal()
    recapChanged = Signal()
    playlistImported = Signal("QVariantMap")
    playerImported = Signal("QVariantMap")
    playerImportBusyChanged = Signal()
    _imported = Signal(object)
    _player_imported = Signal(object)
    _recap_loaded = Signal(object)
    _smart_loaded = Signal(object)
    _refreshed = Signal(object)
    _playlist_loaded = Signal(object)
    _stats_loaded = Signal(object)

    def __init__(self, db_path, player=None, parent=None):
        super().__init__(parent)
        self._reader = _Reader(str(db_path), "userlib")
        # Imports can take minutes (reading every file's tags); they get their own worker, so likes, ratings,
        # playlists and the quick lookups the window waits on never queue behind them.
        self._bulk = _Reader(str(db_path), "userlib-bulk")
        self._player = player
        self._liked = set()
        self._ratings = {}
        self._likes_revision = 0
        # Likes and ratings change here at once and are written behind; a refresh read before such a write
        # would put the old value back, so a refresh only takes them if nothing was changed since it started.
        self._edits = 0
        # Settings → Library: ratings also go in the songs' own tags, so other players (and this one, after a
        # reinstall) see them. Written on the bulk worker; on Windows a playing file waits until it's let go.
        self._ratings_in_files = QSettings("hallucinate", "hallucinate").value("ratings/inFiles", True, type=bool)
        self._waiting_ratings = {}  # path -> stars, for the song that's playing (Windows can't replace it)
        if player is not None and hasattr(player, "trackChanged"):
            player.trackChanged.connect(self._flush_waiting_ratings)
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
            "history": DictModel(HISTORY_KEYS, self),
        }
        self._history_filter = None
        self._history_generation = 0
        self._history_info = {"summary": {}, "days": {}, "heatmap": {}, "hasMore": False, "loading": False}
        self._history_loaded.connect(self._apply_history)
        self._history_requery.connect(self._reload_history)
        self._recap = {}
        self._recap_period = ""
        self._recap_loading = False
        self._recap_loaded.connect(self._apply_recap)
        self._imported.connect(self._apply_import)
        self._player_imported.connect(self._apply_player_import)
        self._player_import_busy = False
        self._refreshed.connect(self._apply_refresh)
        self._playlist_loaded.connect(self._apply_playlist)
        self._smart_loaded.connect(self._apply_smart)
        self._smart_id = -1
        self._smart_rules = None
        self._smart_revision = 0
        self._stats_loaded.connect(self._apply_stats)
        self._matched_loves.connect(self._apply_matched_loves)
        if player is not None:
            player.played.connect(self.recordPlay)
            player.skipped.connect(self.recordSkip)
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
    historyModel = _model_prop("history")

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
        player.skipped.connect(self.recordSkip)

    # --- refresh ------------------------------------------------------------
    def refresh(self):
        edits = self._edits

        def work(db):
            try:
                data = {
                    "edits": edits,
                    "liked_paths": db.liked_paths(),
                    "ratings": db.ratings(),
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
        if data["edits"] == self._edits:
            self._liked = data["liked_paths"]
            self._ratings = data["ratings"]
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

    @Slot(result="QVariantMap")
    def likedLookup(self):
        """{path: True} for every liked song, so a list of rows can check likes without a call each."""
        return dict.fromkeys(self._liked, True)

    def _announce_likes(self, db, paths, liked):
        pairs = []
        for p in paths:
            row = db.track_by_path(p)
            if row and row.get("artist") and row.get("title"):
                pairs.append((row["artist"], row["title"]))
        if pairs:
            self.likeChanged.emit(pairs, liked)

    @Slot(str)
    def toggleLike(self, path):
        if not path:
            return
        liked = path not in self._liked
        (self._liked.add if liked else self._liked.discard)(path)
        self._edits += 1
        self._likes_revision += 1
        self.likesChanged.emit()
        self._write(lambda db, p, v: (db.set_liked(p, v), self._announce_likes(db, [p], v)), path, liked)

    @Slot(str, result=int)
    def rating(self, path):
        """0–5 stars (0 = not rated). Bind through likesRevision to update when ratings change."""
        return self._ratings.get(path, 0)

    @Slot(str, int)
    def setRating(self, path, stars):
        """Rate a song 1–5 stars; 0, or the stars it already has, clears the rating."""
        if not path:
            return
        stars = max(0, min(5, int(stars)))
        if stars == self._ratings.get(path, 0):
            stars = 0
        if stars:
            self._ratings[path] = stars
        else:
            self._ratings.pop(path, None)
        self._edits += 1
        self._likes_revision += 1
        self.likesChanged.emit()
        self._write(lambda db, p, s: db.set_rating(p, s), path, stars, refresh=False)
        self._rating_to_files([path], stars)
        if self._smart_id >= 0:  # an open smart playlist may filter or sort by rating
            sid = self._smart_id
            self._reader.submit(lambda db: self._load_smart(db, sid))

    @Property(bool, notify=likesChanged)
    def ratingsInFiles(self):
        return self._ratings_in_files

    @Slot(bool)
    def setRatingsInFiles(self, on):
        on = bool(on)
        if on != self._ratings_in_files:
            self._ratings_in_files = on
            QSettings("hallucinate", "hallucinate").setValue("ratings/inFiles", on)
            self.likesChanged.emit()

    def _rating_to_files(self, paths, stars):
        if not self._ratings_in_files:
            return
        playing = ""
        if os.name == "nt" and self._player is not None and getattr(self._player, "hasTrack", False):
            playing = (self._player.current or {}).get("path", "")
        now = [p for p in paths if p != playing]
        if playing in paths:
            self._waiting_ratings[playing] = stars
        if now:
            self._bulk.submit(lambda db, ps=now, s=stars: _write_ratings(db, ps, s))

    @Slot()
    def _flush_waiting_ratings(self):
        playing = (self._player.current or {}).get("path", "") if getattr(self._player, "hasTrack", False) else ""
        for path in [p for p in self._waiting_ratings if p != playing]:
            self._rating_to_files([path], self._waiting_ratings.pop(path))

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

    # --- playlist files ------------------------------------------------------------
    @staticmethod
    def _match_entries(db, entries):
        """Library paths for playlist entries: by path, then by artist and title, then by file name."""
        by_path, by_tags, by_name = set(), {}, {}
        for r in db.conn.execute("SELECT path, s_artist, s_title FROM tracks"):
            by_path.add(r["path"])
            by_tags.setdefault((r["s_artist"], r["s_title"]), r["path"])
            by_name.setdefault(os.path.basename(r["path"]).casefold(), r["path"])
        found, missing = [], []
        for e in entries:
            path = e["path"] if e["path"] in by_path else None
            if path is None and e.get("title"):
                path = by_tags.get((fold(e.get("artist") or ""), fold(e["title"])))
            if path is None:
                path = by_name.get(os.path.basename(e["path"]).casefold())
            (found if path else missing).append(path or e["path"])
        return found, missing

    @Slot(str)
    def importPlaylist(self, url):
        """Make a playlist from an M3U/M3U8/PLS file; playlistImported({id, name, added, missing}) reports back."""
        path = QUrl(url).toLocalFile() if url.startswith("file:") else url
        name = os.path.splitext(os.path.basename(path))[0] or "Imported playlist"

        def work(db):
            try:
                entries = playlist_files.read(path)
                found, missing = self._match_entries(db, entries)
                pid = db.create_playlist(name) if found else -1
                if found:
                    db.playlist_add(pid, found)
                result = {"id": pid, "name": name, "added": len(found), "missing": len(missing), "error": ""}
            except (OSError, ValueError) as exc:
                result = {"id": -1, "name": name, "added": 0, "missing": 0, "error": str(exc)}
            except Exception:  # noqa: BLE001
                logger.exception("Playlist import failed")
                result = {"id": -1, "name": name, "added": 0, "missing": 0, "error": "Couldn't read that playlist"}
            self._imported.emit(result)

        self._bulk.submit(work)

    # --- another player's library ---------------------------------------------------------
    @Slot(result="QVariantList")
    def otherPlayerLibraries(self):
        """Other players' libraries found in their usual places: [{name, path}]."""
        return player_import.known_locations()

    @Property(bool, notify=playerImportBusyChanged)
    def playerImportBusy(self):
        return self._player_import_busy

    def _start_player_import(self, read):
        if self._player_import_busy:
            return
        self._player_import_busy = True
        self.playerImportBusyChanged.emit()

        def work(db):
            try:
                result = player_import.merge(db, read(db))
                result["error"] = ""
            except (OSError, ValueError, sqlite3.Error) as exc:
                result = {"error": f"Couldn't read that library: {exc}"}
            except Exception:  # noqa: BLE001
                logger.exception("Importing another player's library failed")
                result = {"error": "Couldn't import that library"}
            self._player_imported.emit(result)

        self._bulk.submit(work)

    @Slot(str)
    def importFromPlayer(self, url):
        """Import play counts, skips, ratings and playlists from Strawberry, Clementine, Rhythmbox, MusicBee or
        iTunes (the file is recognised by its contents); playerImported reports what came over."""
        path = QUrl(url).toLocalFile() if url.startswith("file:") else url
        self._start_player_import(lambda db: player_import.read(path))

    @Slot()
    def importTagStatistics(self):
        """Play counts written into the files' tags (foobar2000's foo_playcount and others)."""
        self._start_player_import(lambda db: player_import.read_tag_statistics(
            [r[0] for r in db.conn.execute("SELECT path FROM tracks WHERE file IS NULL")]))

    @Slot(object)
    def _apply_player_import(self, result):
        self._player_import_busy = False
        self.playerImportBusyChanged.emit()
        self.refresh()
        self.refreshStats()
        self.playerImported.emit(result)

    @Slot(object)
    def _apply_import(self, result):
        self.refresh()
        self.playlistImported.emit(result)

    @Slot(str, str, result=str)
    def exportPlaylist(self, kind, url):
        """Write songs as an M3U8 file: kind is "playlist" (the open one), "smart", "liked" or "queue".
        Returns an error message, or "" on success."""
        path = QUrl(url).toLocalFile() if url.startswith("file:") else url
        if not path:
            return "No file chosen"
        if not os.path.splitext(path)[1]:
            path += ".m3u8"
        if kind == "queue":
            tracks = self._player.queue if self._player is not None else []
        else:
            tracks = self._models.get({"playlist": "playlistTracks", "smart": "smartTracks", "liked": "liked"}.get(kind, ""))
            tracks = tracks.items() if tracks is not None else []
        tracks = [t for t in tracks if t.get("path")]
        if not tracks:
            return "There are no songs to export"
        from .core.atomic import write_atomic

        text = playlist_files.write_m3u(tracks, path).encode("utf-8")  # built first: a failure leaves no empty file
        try:
            write_atomic(path, lambda fh: fh.write(text))
        except OSError as exc:
            return f"Couldn't save the playlist: {exc.strerror or exc}"
        return ""

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

    # --- several songs at once (the selection bar) ---------------------------------
    def _tracks(self, paths):
        """Library tracks for `paths`, in that order (songs no longer in the library are left out)."""
        paths = [p for p in paths if p]

        def load(db):
            return [t for t in (db.track_by_path(p) for p in paths) if t]

        return decorate(self._reader.submit(load).result(timeout=30)) if paths else []

    @Slot("QVariantList")
    def playPaths(self, paths):
        tracks = self._tracks(list(paths))
        if tracks and self._player is not None:
            self._player.playList(tracks, 0)

    @Slot("QVariantList")
    def playNextPaths(self, paths):
        if self._player is not None:
            for t in reversed(self._tracks(list(paths))):  # each goes in right after the current song
                self._player.playNext(t)

    @Slot("QVariantList")
    def enqueuePaths(self, paths):
        tracks = self._tracks(list(paths))
        if tracks and self._player is not None:
            self._player.enqueueAll(tracks)

    @Slot(int, "QVariantList")
    def addPathsToPlaylist(self, pid, paths):
        paths = [p for p in paths if p]
        if paths:
            self._write(lambda db, i, ps: db.playlist_add(i, ps), pid, paths, reload_playlist=True)

    @Slot(str, "QVariantList", result=int)
    def addPathsToNewPlaylist(self, name, paths):
        pid = self.createPlaylist(name)
        self.addPathsToPlaylist(pid, paths)
        return pid

    @Slot("QVariantList", result=bool)
    def allLiked(self, paths):
        return bool(paths) and all(p in self._liked for p in paths)

    @Slot("QVariantList", bool)
    def setLikedPaths(self, paths, liked, announce=True):
        paths = [p for p in paths if p and (p in self._liked) != liked]
        if not paths:
            return
        for p in paths:
            (self._liked.add if liked else self._liked.discard)(p)
        self._edits += 1
        self._likes_revision += 1
        self.likesChanged.emit()

        def write(db, ps, v):
            for p in ps:
                db.set_liked(p, v)
            if announce:
                self._announce_likes(db, ps, v)

        self._write(write, paths, liked)

    @Slot(object)
    def _apply_matched_loves(self, paths):
        new = [p for p in dict.fromkeys(paths) if p not in self._liked]
        self.setLikedPaths(new, True, announce=False)  # they're loved already: nothing to send back
        self.lovesMatched.emit(len(new))

    def likeLoved(self, pairs):
        """Like every library song matching these [(artist, title)] (Last.fm loves, say); lovesMatched(n)
        reports how many were newly liked."""
        from .core.db import fold

        def work(db):
            found = []
            for artist, title in pairs:
                for row in db.conn.execute("SELECT path FROM tracks WHERE s_artist=? AND s_title=?",
                                           (fold(artist), fold(title))):
                    found.append(row[0])
            self._matched_loves.emit(found)

        self._reader.submit(work)

    @Slot("QVariantList", int)
    def setRatingPaths(self, paths, stars):
        """Give every song the same rating (0 clears)."""
        stars = max(0, min(5, int(stars)))
        paths = [p for p in paths if p]
        if not paths:
            return
        for p in paths:
            if stars:
                self._ratings[p] = stars
            else:
                self._ratings.pop(p, None)
        self._edits += 1
        self._likes_revision += 1
        self.likesChanged.emit()
        self._write(lambda db, ps, s: [db.set_rating(p, s) for p in ps], paths, stars, refresh=False)
        self._rating_to_files(paths, stars)
        if self._smart_id >= 0:
            sid = self._smart_id
            self._reader.submit(lambda db: self._load_smart(db, sid))

    # --- play statistics -----------------------------------------------------------
    @Slot("QVariantMap")
    def recordPlay(self, track):
        path = track.get("path") if hasattr(track, "get") else None
        if not path or (track.get("kind") or "music") != "music":
            return  # radio and podcasts stay out of plays, stats and history
        self._write(lambda db, p: db.record_play(p), path)
        self.refreshStats()
        self._reload_history()

    @Slot("QVariantMap")
    def recordSkip(self, track):
        path = track.get("path") if hasattr(track, "get") else None
        if path:
            self._write(lambda db, p: db.record_skip(p), path)

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
            self._history_requery.emit()

        self._bulk.submit(work)

    # --- listening history -------------------------------------------------------
    @Property("QVariantMap", notify=historyChanged)
    def historyInfo(self):
        """For the history page: the filter in use, totals for it (`summary`), plays and seconds per day (`days`),
        a heatmap of the last year, whether more rows can be loaded, and whether a query is running."""
        info = dict(self._history_info)
        info.update(self._history_filter or {})
        return info

    @Slot(str, str, str, str)
    def loadHistory(self, query, period, artist, source):
        """Show listens matching the filters: free text over title/artist/album, a period (see
        core.history.period_range), an exact artist and a source ("local", "imported" or "" for both)."""
        self._history_filter = {"query": query, "period": period or "all", "artist": artist, "source": source}
        self._query_history(0)

    @Slot()
    def loadMoreHistory(self):
        if self._history_filter is not None and self._history_info["hasMore"] and not self._history_info["loading"]:
            self._query_history(self._models["history"].count)

    @Slot()
    def _reload_history(self):
        if self._history_filter is not None:
            self._query_history(0)

    def _query_history(self, offset):
        self._history_generation += 1
        generation, f = self._history_generation, dict(self._history_filter)
        self._history_info["loading"] = True
        self.historyChanged.emit()

        def work(db):
            try:
                start, end = history.period_range(f["period"])
                args = (f["query"], start, end, f["artist"], f["source"])
                rows = history.plays(db, *args, limit=HISTORY_PAGE + 1, offset=offset)
                payload = {"rows": decorate(rows[:HISTORY_PAGE]), "hasMore": len(rows) > HISTORY_PAGE}
                if offset == 0:
                    payload["summary"] = history.summary(db, *args)
                    payload["days"] = history.daily_totals(db, *args)
                    payload["heatmap"] = insights.listening_heatmap(db, weeks=HISTORY_WEEKS)
            except Exception:  # noqa: BLE001
                logger.exception("History query failed")
                payload = {"rows": [], "hasMore": False}
            self._history_loaded.emit((generation, offset, payload))

        self._reader.submit(work)

    @Slot(object)
    def _apply_history(self, result):
        generation, offset, payload = result
        if generation != self._history_generation:
            return
        for row in payload["rows"]:
            row["dayLabel"] = history.day_label(row["day"])
        if offset == 0:
            self._models["history"].set_items(payload["rows"])
            for key in ("summary", "days", "heatmap"):
                if key in payload:
                    self._history_info[key] = payload[key]
        else:
            self._models["history"].append_items(payload["rows"])
        self._history_info["hasMore"] = payload["hasMore"]
        self._history_info["loading"] = False
        self.historyChanged.emit()

    @Slot(int)
    def removeHistoryEntry(self, play_id):
        """Forget one listen (its song's play count drops by one)."""
        self._write(lambda db, i: history.delete_play(db, i), play_id)
        self.refreshStats()
        self._reload_history()

    @Slot(int)
    def playHistoryEntry(self, index):
        row = self._models["history"].get(index)
        t = self._track(row.get("path")) if row.get("path") else None
        if t:
            self._play([t], 0)

    # --- recaps ------------------------------------------------------------------------
    @Property("QVariantMap", notify=recapChanged)
    def recap(self):
        """The loaded recap (see core.recap.recap), plus "loading"."""
        return {**self._recap, "loading": self._recap_loading}

    @Slot(str)
    def loadRecap(self, period):
        """Load a recap: "week", "month" or "year" for the current one, or a full period like "month:2026-09"."""
        if period in recap.KINDS:
            period = recap.current(period)
        try:
            recap.parse(period)
        except ValueError:
            return
        self._recap_period = period
        self._recap_loading = True
        self.recapChanged.emit()

        def work(db):
            try:
                data = recap.recap(db, period)
                for key in ("topArtists", "topAlbums", "topSongs", "discoveries"):
                    decorate(data[key])
            except Exception:  # noqa: BLE001
                logger.exception("Recap failed")
                data = {}
            self._recap_loaded.emit((period, data))

        self._reader.submit(work)

    @Slot(int)
    def stepRecap(self, delta):
        if self._recap_period:
            self.loadRecap(recap.step(self._recap_period, delta))

    @Slot(object)
    def _apply_recap(self, payload):
        period, data = payload
        if period != self._recap_period:
            return
        self._recap = data
        self._recap_loading = False
        self.recapChanged.emit()

    @Slot("QVariant", result=str)
    def saveRecapImage(self, image):
        """Save a rendered recap card under Pictures; returns the file path, or "" when it couldn't be written."""
        import os
        import re

        from PySide6.QtCore import QStandardPaths

        folder = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.PicturesLocation) or os.path.expanduser("~")
        name = re.sub(r'[\\/:*?"<>|]', "-", self._recap.get("title") or "recap")
        period = (self._recap.get("period") or "").replace(":", " ")
        path = os.path.join(folder, f"Hallucinate recap - {name} ({period}).png" if period else f"Hallucinate recap - {name}.png")
        try:
            os.makedirs(folder, exist_ok=True)
        except OSError:
            return ""
        return path if image is not None and not image.isNull() and image.save(path) else ""

    @Slot(int)
    def playRecapSong(self, index):
        songs = self._recap.get("topSongs") or []
        if 0 <= index < len(songs) and songs[index].get("path"):
            t = self._track(songs[index]["path"])
            if t:
                self._play([t], 0)

    def shutdown(self):
        self._bulk.close()
        self._reader.close()
