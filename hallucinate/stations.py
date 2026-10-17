"""Internet radio: the stations you've saved, finding new ones, and what a station is playing right now.

Stations live in streams.db (see core/streams_db.py). Adding one by link checks it first (a .pls or .m3u link
is opened for the stream inside, and the server's name and genre fill in the details). Search uses the Radio
Browser directory. While a station plays, its stream title is read every STREAM_TITLE_EVERY ms over a short
side connection (Qt doesn't pass the titles on) and becomes the playing song's artist and title. Logos are
downloaded once into the cache, so pictures never load from the web while offline mode is on."""
import hashlib
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PySide6.QtCore import Property, QObject, QSettings, QTimer, QUrl, Signal, Slot

from .core import net
from .core import stations as st
from .core.kinds import track_kind
from .core.streams_db import StreamsDB
from .listentime import ListenClock
from .models import DictModel

logger = logging.getLogger(__name__)

STREAM_TITLE_EVERY = 15_000
STATION_KEYS = ["id", "name", "url", "homepage", "tags", "country", "codec", "bitrate", "artUrl", "plays",
                "last_played", "detail"]
RESULT_KEYS = ["row", "name", "url", "homepage", "tags", "country", "codec", "bitrate", "artUrl", "saved", "detail",
               "votes"]
MAX_ICON_BYTES = 1_000_000


def detail(station):
    """One line under a station's name: its genres, country and stream quality."""
    parts = []
    if station.get("tags"):
        parts.append(", ".join(t.strip() for t in station["tags"].split(",")[:3] if t.strip()))
    if station.get("country"):
        parts.append(station["country"])
    quality = " ".join(p for p in (station.get("codec") or "", f"{station['bitrate']} kbps" if station.get("bitrate") else "") if p)
    if quality:
        parts.append(quality)
    return "  ·  ".join(parts)


class Stations(QObject):
    changed = Signal()
    resultsChanged = Signal()
    message = Signal(str)  # something to tell the user (shown as a toast)
    undoable = Signal(str)  # the same, with an Undo button that calls undo()
    logChanged = Signal()  # a song was heard on the radio, or the log was cleared
    listeningChanged = Signal()
    _done = Signal(object)

    def __init__(self, db_path, cache_dir, player, parent=None):
        super().__init__(parent)
        self._db = StreamsDB(db_path)
        self._icons = Path(cache_dir) / "station-icons"
        self._player = player
        self._settings = QSettings("hallucinate", "hallucinate")
        self._scrobble = self._settings.value("stations/scrobble", False, bool)
        self._enabled = True
        self._model = DictModel(STATION_KEYS, self, key_field="id")
        self._results_model = DictModel(RESULT_KEYS, self)
        self._results = []
        self._searching = False
        self._status = ""
        self._busy = False
        self._title_token = 0
        self._pool = ThreadPoolExecutor(max_workers=3, thread_name_prefix="stations")
        self._done.connect(self._apply)
        self._title_timer = QTimer(self)
        self._title_timer.setInterval(STREAM_TITLE_EVERY)
        self._title_timer.timeout.connect(self._poll_title)
        player.trackChanged.connect(self._on_player)
        player.stateChanged.connect(self._on_player)
        player.played.connect(self._on_played)
        self._log_query = ""
        self._clock = ListenClock(player, self._db, "station",
                                  lambda e: ("station", int(e.get("station_id") or 0), e.get("station") or e.get("album") or ""),
                                  self)
        self._clock.counted.connect(self.listeningChanged)
        self.refresh()

    # --- the saved stations ----------------------------------------------------------------------------
    def _icon_file(self, station):
        if not station.get("favicon"):
            return None
        name = hashlib.sha1(station["favicon"].encode("utf-8"), usedforsecurity=False).hexdigest()[:20]
        return self._icons / name

    def _row(self, station):
        icon = self._icon_file(station)
        return {**station, "artUrl": QUrl.fromLocalFile(str(icon)).toString() if icon and icon.exists() else "",
                "detail": detail(station)}

    @Slot()
    def refresh(self):
        rows = self._db.stations()
        self._model.set_items([self._row(s) for s in rows])
        missing = [s for s in rows if s.get("favicon") and not self._icon_file(s).exists()]
        if missing and not net.is_offline():
            self._pool.submit(self._fetch_icons, missing)
        self._mark_saved()
        self.changed.emit()

    def _fetch_icons(self, stations):
        got = False
        for station in stations:
            target = self._icon_file(station)
            try:
                request = st._request(station["favicon"])
                with net.urlopen(request, timeout=8, limit=MAX_ICON_BYTES) as resp:
                    kind = (resp.headers.get("Content-Type") or "").lower()
                    data = resp.read()
                if not kind.startswith("image/") or not data:
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
                got = True
            except (OSError, ValueError) as exc:
                logger.info("No logo for a station: %s", exc)
        if got:
            self._done.emit(("icons", None, None))

    @Property(QObject, constant=True)
    def model(self):
        return self._model

    @Property(int, notify=changed)
    def count(self):
        return self._model.count

    @Property(bool, notify=changed)
    def busy(self):
        return self._busy

    @Slot(str, str)
    def add(self, url, name=""):
        """Save a station from a link (a stream or a .pls/.m3u playlist), checking it plays first."""
        url = (url or "").strip()
        if not st.is_stream_url(url):
            self.message.emit("That isn't a web link: it should start with http:// or https://")
            return
        if net.is_offline():
            self.message.emit("Offline mode is on, so the station can't be checked")
            return
        self._busy = True
        self.changed.emit()

        def work():
            try:
                info = st.resolve(url)
            except Exception as exc:  # noqa: BLE001 - a worker must always report back
                return ("added", None, f"Couldn't add that station: {net.describe(exc)}")
            info["name"] = (name or "").strip() or info.get("name") or urlname(info["url"])
            return ("added", info, "")

        self._pool.submit(lambda: self._done.emit(work()))

    @Slot(int, str)
    def rename(self, station_id, name):
        if name.strip():
            self._db.update_station(station_id, name=name.strip())
            self.refresh()

    @Slot(int)
    def remove(self, station_id):
        station = self._db.station(station_id)
        if station:
            self._db.remove_station(station_id)
            self._undo = station
            self.refresh()
            self.undoable.emit(f"Removed “{station['name']}”")

    @Slot()
    def undo(self):
        """Put back the station removed last."""
        station, self._undo = getattr(self, "_undo", None), None
        if station:
            new_id = self._db.add_station(station)
            self._db.conn.execute("UPDATE stations SET added=?, last_played=?, plays=? WHERE id=?",
                                  (station["added"], station["last_played"], station["plays"], new_id))
            self._db.conn.commit()
            self.refresh()

    @Slot(str, result="QVariantList")
    def find(self, query):
        """Saved stations whose name or genres have every word of `query` (for the top search)."""
        words = [w.casefold() for w in (query or "").split()]
        if not words or not self._enabled:
            return []
        out = []
        for s in self._db.stations():
            hay = f"{s['name']} {s['tags']} {s['country']}".casefold()
            if all(w in hay for w in words):
                out.append(self._row(s))
        return out[:8]

    @Slot(int, result="QVariantMap")
    def station(self, station_id):
        found = self._db.station(int(station_id))
        return self._row(found) if found else {}

    def _entry(self, station):
        """The queue entry that plays a station."""
        row = self._row(station)
        return {"path": station["url"], "kind": "station", "station": station["name"], "title": station["name"],
                "artist": "", "album": station["name"], "album_artist": "", "artUrl": row["artUrl"], "duration": 0,
                "station_id": station["id"], "scrobble": self._scrobble, "fmt": station.get("codec") or "",
                "id": -station["id"]}

    @Slot(int)
    def play(self, station_id):
        """Play a station. Your other stations follow it in the queue, so Next tunes to the next one."""
        stations = self._db.stations()
        index = next((i for i, s in enumerate(stations) if s["id"] == station_id), -1)
        if index < 0:
            return
        if net.is_offline():
            self.message.emit("Offline mode is on, so stations can't play")
            return
        self._player.playList([self._entry(s) for s in stations], index)
        self._db.station_played(station_id)  # kept here: nothing about what you play is sent anywhere
        self.refresh()

    @Slot(int)
    def playNext(self, station_id):
        station = self._db.station(station_id)
        if station:
            self._player.playNext(self._entry(station))
            self.message.emit(f"“{station['name']}” will play next")

    # --- files -------------------------------------------------------------------------------------------
    @Slot(str, result=str)
    def importFile(self, url):
        """Save every station in a .pls, .m3u or .xspf file. Returns what happened, for a toast."""
        path = QUrl(url).toLocalFile() if url.startswith("file:") else url
        try:
            text = Path(path).read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            return f"Couldn't read the file: {exc.strerror or exc}"
        links = st.parse_playlist(text)
        if not links:
            if "#EXT-X-" in text:
                return "That's a stream itself, not a list of stations: add it by its link instead"
            return "No station links in that file"
        titles = st.playlist_titles(text)
        before = len(self._db.stations())
        for link in links:
            self._db.add_station({"url": link, "name": titles.get(link) or urlname(link)})
        added = len(self._db.stations()) - before
        self.refresh()
        return f"Added {added} station{'s' if added != 1 else ''}" if added else "Those stations are already saved"

    @Slot(str, result=str)
    def exportFile(self, url):
        """Write every saved station to an .m3u file other players can open."""
        path = QUrl(url).toLocalFile() if url.startswith("file:") else url
        if not path.lower().endswith((".m3u", ".m3u8")):
            path += ".m3u"
        lines = ["#EXTM3U"]
        for s in self._db.stations():
            lines += [f"#EXTINF:-1,{s['name']}", s["url"]]
        try:
            from .core.atomic import write_text

            write_text(path, "\n".join(lines) + "\n")
        except OSError as exc:
            return f"Couldn't save: {exc.strerror or exc}"
        return f"Saved {len(lines) // 2} stations to {Path(path).name}"

    # --- the directory -------------------------------------------------------------------------------------
    @Property(QObject, constant=True)
    def results(self):
        return self._results_model

    @Property(bool, notify=resultsChanged)
    def searching(self):
        return self._searching

    @Property(str, notify=resultsChanged)
    def status(self):
        return self._status

    @Slot(str)
    def search(self, query):
        query = (query or "").strip()
        if not query:
            self._results = []
            self._status, self._searching = "", False
            self._mark_saved()
            self.resultsChanged.emit()
            return
        if net.is_offline():
            self._status, self._searching = "Offline mode is on, so the directory can't be searched", False
            self.resultsChanged.emit()
            return
        self._searching, self._status = True, ""
        self.resultsChanged.emit()

        def work():
            try:
                return ("results", query, st.search_directory(query))
            except Exception as exc:  # noqa: BLE001 - a worker must always report back
                logger.warning("Radio Browser search failed: %s", exc)
                return ("results", query, None)

        self._pool.submit(lambda: self._done.emit(work()))

    def _mark_saved(self):
        saved = {s["url"] for s in self._db.stations()}
        rows = [{**r, "row": i, "saved": r["url"] in saved, "detail": detail(r), "artUrl": ""}
                for i, r in enumerate(self._results)]
        self._results_model.set_items(rows)

    @Slot(int, result=int)
    def addResult(self, row):
        if 0 <= row < len(self._results):
            station_id = self._db.add_station(self._results[row])
            self.refresh()
            name = self._results[row]["name"]
            self.message.emit(f"Saved “{name}”")
            return station_id
        return -1

    @Slot(int)
    def playResult(self, row):
        """Listen to a station from the search without saving it."""
        if not 0 <= row < len(self._results):
            return
        if net.is_offline():
            self.message.emit("Offline mode is on, so stations can't play")
            return
        found = dict(self._results[row])
        saved = self._db.station_by_url(found["url"])
        entry = self._entry({**found, "id": saved["id"] if saved else 0})
        self._player.playList([entry], 0)

    # --- what's playing ------------------------------------------------------------------------------------
    @Property(bool, notify=changed)
    def scrobble(self):
        """Whether songs heard on the radio count on Last.fm and ListenBrainz."""
        return self._scrobble

    @Slot(bool)
    def setScrobble(self, on):
        self._scrobble = bool(on)
        self._settings.setValue("stations/scrobble", self._scrobble)
        if self._player.hasTrack and track_kind(self._player.current) == "station":
            self._player.current["scrobble"] = self._scrobble
        self.changed.emit()

    def setEnabled(self, on):
        """Settings → Features → Internet radio. Off, nothing is fetched (a station already playing stops)."""
        self._enabled = bool(on)
        if not self._enabled and self._player.hasTrack and track_kind(self._player.current) == "station":
            self._player.stop()
        self._on_player()

    @Slot()
    def _on_player(self):
        playing_station = (self._enabled and self._player.hasTrack and self._player.playing
                           and track_kind(self._player.current) == "station")
        if playing_station and not self._title_timer.isActive():
            self._title_timer.start()
            self._poll_title()
        elif not playing_station:
            self._title_timer.stop()

    def _poll_title(self):
        if net.is_offline() or not self._player.hasTrack:
            return
        current = self._player.current
        url, station = current.get("path", ""), current.get("station", "")
        if not url.startswith(("http://", "https://")) or url.lower().split("?")[0].endswith(".m3u8"):
            return
        self._title_token += 1
        token = self._title_token

        def work():
            try:
                title, _ = st.read_stream_title(url)
            except Exception:  # noqa: BLE001 - a worker must always report back
                return ("title", None, None)
            artist, song = st.split_title(title, station)
            return ("title", (token, url), (artist, song, self._album_in_library(artist, song)))

        self._pool.submit(lambda: self._done.emit(work()))

    @Slot(object)
    def _apply(self, result):
        kind, what, value = result
        if kind == "added":
            self._busy = False
            if what is None:
                self.changed.emit()
                self.message.emit(value)
                return
            existing = self._db.station_by_url(what["url"])
            self._db.add_station(what)
            self.refresh()
            self.message.emit(f"“{existing['name']}” is already saved" if existing else f"Saved “{what['name']}”")
        elif kind == "results":
            self._searching = False
            if value is None:
                self._results, self._status = [], "Couldn't reach the station directory. Check your connection."
            else:
                self._results = value
                self._status = "" if value else f"No stations match “{what}”"
            self._mark_saved()
            self.resultsChanged.emit()
        elif kind == "icons":
            self.refresh()
            self._refresh_playing_art()
        elif kind == "title" and what is not None:
            token, url = what
            if token == self._title_token and self._player.hasTrack and self._player.current.get("path") == url:
                artist, title, album = value
                self._player.setStreamInfo(artist, title)
                if self._player.current.get("title") == (title or self._player.current.get("station")):
                    self._player.current["song_album"] = album  # what a scrobble names as the album

    def setLibraryDb(self, path):
        """The music library's database: a song a station plays that's also in your library is scrobbled with
        your copy's album."""
        self._library_db = str(path) if path else ""

    _library_db = ""

    def _album_in_library(self, artist, title):
        """The album of a library song with this artist and title ("" if none, or more than one album has it,
        since a guess could be wrong). Runs on a worker thread with its own read-only connection."""
        if not (self._library_db and artist and title):
            return ""
        import sqlite3

        from .core.db import fold
        try:
            conn = sqlite3.connect(f"file:{self._library_db}?mode=ro", uri=True, timeout=2)
            try:
                albums = {r[0] for r in conn.execute(
                    "SELECT album FROM tracks WHERE s_artist=? AND s_title=? AND album != '' LIMIT 5",
                    (fold(artist), fold(title)))}
            finally:
                conn.close()
        except sqlite3.Error:
            return ""
        return albums.pop() if len(albums) == 1 else ""

    def _refresh_playing_art(self):
        if self._player.hasTrack and track_kind(self._player.current) == "station":
            sid = self._player.current.get("station_id")
            found = self._db.station(sid) if sid else None
            if found and not self._player.current.get("artUrl"):
                self._player.current["artUrl"] = self._row(found)["artUrl"]

    # --- what you've heard -----------------------------------------------------------------------------------
    def _on_played(self, track):
        """A song a station played for a minute or more goes in the radio log (scrobbled or not)."""
        if track_kind(track) != "station" or not track.get("stream_title"):
            return
        self._db.log_radio_song(int(track.get("station_id") or 0), track.get("station") or track.get("album") or "",
                                track.get("artist") or "", track.get("title") or "")
        self.logChanged.emit()

    @Property("QVariantList", notify=logChanged)
    def radioLog(self):
        """Songs heard on the radio, newest first: [{id, ts, station_id, station, artist, title, day, time}]."""
        out = []
        for r in self._db.radio_log(300, self._log_query):
            when = time.localtime(r["ts"])
            out.append({**r, "day": time.strftime("%Y-%m-%d", when), "time": time.strftime("%H:%M", when)})
        return out

    @Slot(str)
    def setLogQuery(self, text):
        self._log_query = text.strip()
        self.logChanged.emit()

    @Slot(int)
    def removeLogEntry(self, entry_id):
        self._db.remove_radio_log(int(entry_id))
        self.logChanged.emit()

    @Slot()
    def clearLog(self):
        self._db.remove_radio_log()
        self.logChanged.emit()

    @Slot(int, result="QVariantMap")
    def listening(self, days):
        """Radio listening for the last `days` days (0: all time): {hours, songs, top: [{name, hours}]}."""
        self._clock.tick()
        got = self._db.listening("station", days)
        return {"hours": round(got["seconds"] / 3600, 1), "songs": self._db.radio_songs_heard(days),
                "top": [{"id": t["item_id"], "name": t["name"], "hours": round(t["seconds"] / 3600, 1)} for t in got["top"]]}

    def shutdown(self):
        self._clock.stop()
        self._title_timer.stop()
        self._pool.shutdown(wait=False, cancel_futures=True)
        self._db.close()


def urlname(url):
    """A name for a station that came with none: its server's name ("stream.example.com")."""
    from urllib.parse import urlsplit

    host = urlsplit(url).hostname or url
    return host.removeprefix("www.")

