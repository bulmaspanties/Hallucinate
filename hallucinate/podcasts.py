"""Podcasts: the shows you follow (RSS feeds, or folders of episodes on disk), their episodes, where you
stopped in each, and downloads.

Shows and episodes live in streams.db (see core/streams_db.py), never in the music library: episodes don't
count as plays and stay out of stats, history and recap. While an episode plays, the place you're at is
saved every few seconds, so it picks up there next time; one heard to (almost) the end is marked played.
Feeds are checked when the app starts and every few hours after, through the network gate (offline mode stops
it), and new episodes download by themselves for shows set to."""
import hashlib
import logging
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PySide6.QtCore import Property, QObject, QSettings, QTimer, QUrl, Signal, Slot

from .core import net
from .core import podcasts as pc
from .core.kinds import track_kind
from .core.streams_db import StreamsDB
from .listentime import ListenClock
from .models import DictModel

logger = logging.getLogger(__name__)

SAVE_EVERY_MS = 5_000
REFRESH_EVERY_MS = 4 * 3600 * 1000
FIRST_REFRESH_MS = 20_000
PLAYED_REMAINING_S = 45  # stop this close to the end of a long episode (or past 97%) and it counts as played
# Settings → Podcasts, with their defaults
DEFAULTS = {
    "skipBack": 15, "skipForward": 30,  # seconds
    "refreshHours": 4,  # 0: only when you ask
    "newShowDownloads": 0,  # how many of a newly followed show's latest episodes download by themselves
    "keep": "played",  # downloads: "played" (removed once played), "latest" (the newest keepCount per show), "forever"
    "keepCount": 3,
    "playedWindow": PLAYED_REMAINING_S,  # seconds before the end of a long episode that count as the end
    "afterEpisode": "next",  # "next": the show's next unplayed episode follows; "stop": just the one
    "notifyNew": 0,  # 1: a desktop notification when a show you follow has a new episode
}
CHOICES = {"skipBack": (5, 10, 15, 30, 45, 60), "skipForward": (10, 15, 30, 45, 60, 90),
           "refreshHours": (0, 1, 2, 4, 8, 12, 24), "newShowDownloads": (0, 1, 2, 3, 5),
           "keep": ("played", "latest", "forever"), "keepCount": (1, 2, 3, 5, 10),
           "playedWindow": (10, 30, 45, 60, 120, 300), "afterEpisode": ("next", "stop"), "notifyNew": (0, 1)}


def near_end(pos, dur, window=PLAYED_REMAINING_S):
    return bool(dur and pos) and (pos / dur >= 0.97 or (dur > 600 and dur - pos <= window))
SHOW_KEYS = ["id", "title", "author", "artUrl", "unplayed", "episodes", "latest", "feed_url", "folder", "error",
             "newest_first", "hide_played", "speed", "skip_intro", "skip_outro",
             "auto_download", "description", "link", "detail"]
EPISODE_KEYS = ["id", "podcast_id", "title", "podcast", "description", "published", "duration", "position",
                "played", "downloaded", "progress", "artUrl", "detail", "url", "local", "downloading", "status",
                "up_next"]
RESULT_KEYS = ["row", "title", "author", "genre", "artUrl", "followed", "feed_url"]
MAX_IMAGE_BYTES = 4_000_000


def nice_date(ts):
    if not ts:
        return ""
    lt, now = time.localtime(ts), time.localtime()
    days = int((time.time() - ts) // 86400)
    if days < 1 and lt.tm_mday == now.tm_mday:
        return "Today"
    if days < 2:
        return "Yesterday"
    if days < 7:
        return time.strftime("%A", lt)
    month = time.strftime("%b", lt)
    return f"{lt.tm_mday} {month}" if lt.tm_year == now.tm_year else f"{lt.tm_mday} {month} {lt.tm_year}"


def nice_length(seconds):
    seconds = int(seconds or 0)
    if seconds <= 0:
        return ""
    h, m = divmod(seconds // 60, 60)
    return f"{h} h {m} min" if h else f"{max(1, m)} min"


class Podcasts(QObject):
    changed = Signal()  # the shows
    episodesChanged = Signal()  # the open show's episodes, the new and in-progress lists
    resultsChanged = Signal()
    chaptersChanged = Signal()
    message = Signal(str)
    listeningChanged = Signal()  # listening time grew, or the scrobble switch changed
    newEpisodes = Signal(str, str)  # (show, latest episode title) when a check finds something new, if asked to tell
    undoable = Signal(str)  # a toast with an Undo button that calls undo()
    _done = Signal(object)

    def __init__(self, db_path, data_dir, cache_dir, player, parent=None):
        super().__init__(parent)
        self._db = StreamsDB(db_path)
        self._downloads = Path(data_dir) / "podcasts"
        self._images = Path(cache_dir) / "podcast-art"
        self._player = player
        self._settings = QSettings("hallucinate", "hallucinate")
        legacy_keep = "played" if self._settings.value("podcasts/deletePlayed", True, bool) else "forever"
        self._options = {}
        for key, default in DEFAULTS.items():
            value = self._settings.value(f"podcasts/{key}", legacy_keep if key == "keep" else default)
            try:
                value = type(default)(value)
            except (TypeError, ValueError):
                value = default
            self._options[key] = value if value in CHOICES[key] else default
        self._filter = ""
        self._enabled = True
        self._shows = DictModel(SHOW_KEYS, self, key_field="id")
        self._episodes = DictModel(EPISODE_KEYS, self, key_field="id")
        self._latest = DictModel(EPISODE_KEYS, self, key_field="id")
        self._continue = DictModel(EPISODE_KEYS, self, key_field="id")
        self._up_next = DictModel(EPISODE_KEYS, self, key_field="id")
        self._results_model = DictModel(RESULT_KEYS, self)
        self._results = []
        self._searching = False
        self._status = ""
        self._busy = 0
        self._open_id = 0
        self._downloading = {}  # episode id -> fraction done (0..1)
        self._cancel = set()
        self._lock = threading.Lock()
        self._chapters = []
        self._chapters_for = 0
        self._playing_id = 0
        self._pool = ThreadPoolExecutor(max_workers=3, thread_name_prefix="podcasts")
        self._done.connect(self._apply)
        self._save_timer = QTimer(self)
        self._save_timer.setInterval(SAVE_EVERY_MS)
        self._save_timer.timeout.connect(self._save_position)
        self._scrobble = self._settings.value("podcasts/scrobble", False, bool)
        self._clock = ListenClock(player, self._db, "episode",
                                  lambda e: ("podcast", int(e.get("podcast_id") or 0), e.get("album") or ""), self)
        self._clock.counted.connect(self.listeningChanged)
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setInterval(max(1, self._options["refreshHours"]) * 3600 * 1000)
        self._refresh_timer.timeout.connect(self.refreshAll)
        self._reload_timer = QTimer(self)  # quiet refreshes of every show reload the lists once, not per show
        self._reload_timer.setSingleShot(True)
        self._reload_timer.setInterval(300)
        self._reload_timer.timeout.connect(self.reload)
        self._progress_timer = QTimer(self)
        self._progress_timer.setInterval(500)
        self._progress_timer.timeout.connect(self._reload_episodes)
        player.trackChanged.connect(self._on_track)
        player.stateChanged.connect(self._on_state)
        player.seeked.connect(lambda *_: self._save_position())
        player.positionChanged.connect(self._note_position)
        if hasattr(player, "showSpeedChanged"):
            player.showSpeedChanged.connect(lambda pid, rate: (self._db.update_podcast(pid, speed=rate), self.reload()))
        self.reload()

    # --- switching on and off ------------------------------------------------------------------------------
    def setEnabled(self, on):
        """Settings → Features → Podcasts. Off: no feed checks or downloads (an episode playing stops)."""
        self._enabled = bool(on)
        if self._enabled:
            if not self._refresh_timer.isActive() and self._options["refreshHours"]:
                self._refresh_timer.start()
                QTimer.singleShot(FIRST_REFRESH_MS, self.refreshAll)
        else:
            self._refresh_timer.stop()
            with self._lock:
                self._cancel.update(self._downloading)
            if self._player.hasTrack and track_kind(self._player.current) == "episode":
                self._save_position()
                self._player.stop()

    # --- lists ----------------------------------------------------------------------------------------------
    def _image_file(self, url):
        if not url:
            return None
        if not url.startswith(("http://", "https://")):
            return Path(url) if os.path.isfile(url) else None
        return self._images / hashlib.sha1(url.encode("utf-8"), usedforsecurity=False).hexdigest()[:24]

    def _art(self, url):
        f = self._image_file(url)
        return QUrl.fromLocalFile(str(f)).toString() if f and f.exists() else ""

    def _show_row(self, p):
        bits = [p["author"]] if p.get("author") else []
        bits.append(f"{p['unplayed']} new" if p.get("unplayed") else "All played" if p.get("episodes") else "No episodes yet")
        return {**p, "artUrl": self._art(p.get("image")), "detail": "  ·  ".join(bits), "latest": p.get("latest") or 0}

    def _episode_row(self, e):
        local = bool(e.get("local_path")) and os.path.isfile(e["local_path"])
        progress = (e["position"] / e["duration"]) if e.get("duration") and e.get("position") else 0.0
        with self._lock:
            fraction = self._downloading.get(e["id"])
        bits = [nice_date(e.get("published"))]
        if e.get("played"):
            bits.append("Played")
        elif e.get("position") and e.get("duration"):
            bits.append(f"{nice_length(e['duration'] - e['position'])} left")
        elif e.get("duration"):
            bits.append(nice_length(e["duration"]))
        if fraction is not None:
            status = f"Downloading {int(fraction * 100)}%"
        elif local and e.get("url"):
            status = "Downloaded"
        else:
            status = ""
        if status:
            bits.append(status)
        return {**e, "artUrl": self._art(e.get("image")) or self._art(e.get("podcast_image")),
                "local": local, "downloaded": local and bool(e.get("url")), "progress": min(1.0, progress),
                "downloading": fraction is not None, "status": status,
                "detail": "  ·  ".join(b for b in bits if b), "played": bool(e.get("played"))}

    @Slot()
    def reload(self):
        shows = self._db.podcasts()
        self._shows.set_items([self._show_row(p) for p in shows])
        self._latest.set_items([self._episode_row(e) for e in self._db.episodes(unplayed_only=True, limit=12)])
        self._continue.set_items([self._episode_row(e) for e in self._db.in_progress(8)])
        self._up_next.set_items([self._episode_row(e) for e in self._db.up_next()])
        self._reload_episodes()
        missing = [p["image"] for p in shows if p.get("image", "").startswith("http") and not self._image_file(p["image"]).exists()]
        if missing and not net.is_offline() and self._enabled:
            self._pool.submit(self._fetch_images, missing)
        self.changed.emit()

    def _reload_episodes(self):
        if self._open_id:
            show = self._db.podcast(self._open_id) or {}
            rows = self._db.episodes(self._open_id, unplayed_only=bool(show.get("hide_played")),
                                     oldest_first=not show.get("newest_first", 1), text=self._filter)
            self._episodes.set_items([self._episode_row(e) for e in rows])
        with self._lock:
            active = bool(self._downloading)
        if not active:
            self._progress_timer.stop()
        self.episodesChanged.emit()

    def _fetch_images(self, urls):
        got = False
        for url in urls:
            target = self._image_file(url)
            try:
                with net.urlopen(pc._request(url), timeout=15, limit=MAX_IMAGE_BYTES) as resp:
                    kind = (resp.headers.get("Content-Type") or "").lower()
                    data = resp.read()
                if data and (kind.startswith("image/") or data[:4] in (b"\x89PNG", b"\xff\xd8\xff\xe0", b"\xff\xd8\xff\xe1")):
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(data)
                    got = True
            except (OSError, ValueError) as exc:
                logger.info("No cover for a podcast: %s", exc)
        if got:
            self._done.emit(("images", None, None))

    @Property(QObject, constant=True)
    def shows(self):
        return self._shows

    @Property(QObject, constant=True)
    def episodes(self):
        """The episodes of the show opened with openShow()."""
        return self._episodes

    @Property(QObject, constant=True)
    def latest(self):
        """New episodes across every show, newest first."""
        return self._latest

    @Property(QObject, constant=True)
    def inProgress(self):
        """Episodes started and not finished: "Continue listening"."""
        return self._continue

    @Property(QObject, constant=True)
    def upNext(self):
        """Episodes lined up to hear next, across shows, in order."""
        return self._up_next

    @Slot(int, bool)
    def addUpNext(self, episode_id, first=False):
        e = self._db.episode(episode_id)
        if e:
            self._db.set_up_next(episode_id, True, first)
            self.reload()
            self.message.emit(f"“{e['title']}” is {'first in' if first else 'in'} Up next")

    @Slot(int)
    def removeUpNext(self, episode_id):
        self._db.set_up_next(episode_id, False)
        self.reload()

    @Slot(int)
    def playUpNext(self, episode_id):
        """Play Up next from this episode on, in its order."""
        items = self._db.up_next()
        start = next((i for i, e in enumerate(items) if e["id"] == episode_id), 0)
        items = items[start:]
        if not items:
            return
        if not (items[0].get("local_path") and os.path.isfile(items[0]["local_path"])) and net.is_offline():
            self.message.emit("Offline mode is on: download episodes to listen to them offline")
            return
        self._player.playList([self._entry(e) for e in items], 0)

    @Property(int, notify=changed)
    def count(self):
        return self._shows.count

    @Property(bool, notify=changed)
    def busy(self):
        return self._busy > 0

    @Slot(int, result="QVariantMap")
    def show(self, podcast_id):
        p = next((r for r in self._db.podcasts() if r["id"] == podcast_id), None)
        return self._show_row(p) if p else {}

    @Slot(str, result="QVariantMap")
    def find(self, query):
        """Shows and episodes matching `query`, for the top search: {"shows": [...], "episodes": [...]}."""
        words = [w.casefold() for w in (query or "").split()]
        if not words or not self._enabled:
            return {"shows": [], "episodes": []}
        matched = [r["id"] for r in self._db.conn.execute("SELECT id, title, author FROM podcasts")
                   if all(w in f"{r['title']} {r['author']}".casefold() for w in words)][:6]
        shows = [self._show_row(p) for p in self._db.podcasts() if p["id"] in matched] if matched else []
        episodes = [self._episode_row(e) for e in self._db.episodes(text=query, limit=8, titles_only=True)]
        return {"shows": shows, "episodes": episodes}

    @Slot(str, result=bool)
    def isEpisode(self, path):
        """Whether a queue entry's path is a podcast episode (a stream or a downloaded file)."""
        row = self._db.conn.execute("SELECT 1 FROM episodes WHERE local_path=? OR url=? LIMIT 1",
                                    (path, path)).fetchone()
        return row is not None

    @Slot(int)
    def openShow(self, podcast_id):
        self._open_id = podcast_id
        self._filter = ""
        self._reload_episodes()

    @Slot(str)
    def setEpisodeFilter(self, text):
        """Only the open show's episodes whose title or notes have these words."""
        if text != self._filter:
            self._filter = text
            self._reload_episodes()

    # per-show settings
    SHOW_OPTIONS = {"newest_first": (0, 1), "hide_played": (0, 1), "speed": (0, 0.75, 1, 1.25, 1.5, 1.75, 2, 2.5, 3),
                    "skip_intro": (0, 15, 30, 45, 60, 90, 120), "skip_outro": (0, 15, 30, 45, 60, 90, 120),
                    "auto_download": (0, 1, 2, 3, 5)}

    @Slot(int, str, "QVariant")
    def setShowOption(self, podcast_id, key, value):
        """A show's own settings: newest or oldest first, hide played, its speed (0 = your podcast speed),
        seconds of intro and outro to skip, and how many of its latest episodes download by themselves."""
        allowed = self.SHOW_OPTIONS.get(key)
        if allowed is None:
            return
        value = float(value) if key == "speed" else int(value)
        if value not in allowed:
            return
        self._db.update_podcast(podcast_id, **{key: value})
        if key == "speed" and self._player.hasTrack and self._player.current.get("podcast_id") == podcast_id:
            self._player.current["speed"] = value
            self._player._apply_speed()
            self._player.speedChanged.emit()
        self.reload()
        if key == "auto_download" and value:
            self._download_new(podcast_id, value)

    # app-wide settings
    @Property("QVariantMap", notify=changed)
    def options(self):
        return dict(self._options)

    @Property("QVariantMap", constant=True)
    def optionChoices(self):
        return {k: list(v) for k, v in CHOICES.items()}

    @Slot(str, "QVariant")
    def setOption(self, key, value):
        if key not in DEFAULTS:
            return
        try:
            value = type(DEFAULTS[key])(value)
        except (TypeError, ValueError):
            return
        if value not in CHOICES[key] or value == self._options[key]:
            return
        self._options[key] = value
        self._settings.setValue(f"podcasts/{key}", value)
        if key == "refreshHours":
            self._refresh_timer.stop()
            if value and self._enabled:
                self._refresh_timer.setInterval(value * 3600 * 1000)
                self._refresh_timer.start()
        if key in ("keep", "keepCount"):
            self._enforce_keep()
        self.changed.emit()

    @Property(float, notify=changed)
    def downloadsSize(self):
        """Bytes the downloaded episodes take."""
        total = 0
        for e in self._db.downloaded():
            if e.get("url"):
                try:
                    total += os.path.getsize(e["local_path"])
                except OSError:
                    pass
        return float(total)

    @Slot()
    def removeAllDownloads(self):
        n = 0
        for e in self._db.downloaded():
            if e.get("url") and not (self._player.playing and self._player.current.get("episode_id") == e["id"]):
                if self._remove_file(e["local_path"]):
                    self._db.set_local_path(e["id"], "")
                    n += 1
        self.reload()
        self.message.emit(f"Removed {n} download{'s' if n != 1 else ''}" if n else "No downloads to remove")

    def _enforce_keep(self, podcast_id=None):
        """Apply the keep setting to downloads: once played, the newest few per show, or all of them."""
        policy = self._options["keep"]
        if policy == "forever":
            return
        shows = [podcast_id] if podcast_id else [p["id"] for p in self._db.podcasts()]
        playing = self._player.current.get("episode_id") if self._player.hasTrack and self._player.playing else None
        for show in shows:
            downloads = sorted((e for e in self._db.downloaded(show) if e.get("url")),
                               key=lambda e: e["published"], reverse=True)
            if policy == "played":
                doomed = [e for e in downloads if e["played"]]
            else:
                doomed = downloads[self._options["keepCount"]:]
            for e in doomed:
                if e["id"] != playing and self._remove_file(e["local_path"]):
                    self._db.set_local_path(e["id"], "")

    # --- following ---------------------------------------------------------------------------------------
    @Slot(str)
    def follow(self, url):
        """Follow a show by its feed link."""
        url = (url or "").strip()
        if not url:
            return
        existing = self._db.podcast_by(feed_url=url)
        if existing:
            self.message.emit(f"You already follow “{existing['title']}”")
            return
        if net.is_offline():
            self.message.emit("Offline mode is on, so the feed can't be fetched")
            return
        self._start_busy()

        def work():
            try:
                podcast, episodes, final = pc.fetch_feed(url)
            except Exception as exc:  # noqa: BLE001 - a worker must always report back
                return ("followed", None, f"Couldn't follow that: {net.describe(exc)}")
            return ("followed", (podcast, episodes, final), "")

        self._pool.submit(lambda: self._done.emit(work()))

    @Slot(str)
    def addFolder(self, url):
        """A folder of episode files on disk becomes a show (it's read again on every refresh)."""
        path = QUrl(url).toLocalFile() if url.startswith("file:") else url
        self._start_busy()

        def work():
            try:
                podcast, episodes = pc.scan_folder(path)
            except Exception as exc:  # noqa: BLE001 - a worker must always report back
                return ("folder", None, str(exc))
            return ("folder", (podcast, episodes), "")

        self._pool.submit(lambda: self._done.emit(work()))

    @Slot(int, bool)
    def unfollow(self, podcast_id, delete_downloads=True):
        p = self._db.podcast(podcast_id)
        if not p:
            return
        if delete_downloads and not p.get("folder"):
            for e in self._db.downloaded(podcast_id):
                self._remove_file(e["local_path"])
        if self._open_id == podcast_id:
            self._open_id = 0
        self._db.remove_podcast(podcast_id)
        self.reload()
        self.message.emit(f"Unfollowed “{p['title']}”")

    @Slot(int, bool)
    def setAutoDownload(self, podcast_id, on):
        self.setShowOption(podcast_id, "auto_download", 1 if on else 0)

    # --- refreshing ---------------------------------------------------------------------------------------
    @Slot()
    def refreshAll(self):
        if not self._enabled:
            return
        for p in self._db.podcasts():
            self.refresh(p["id"], quiet=True)

    @Slot(int)
    def refresh(self, podcast_id, quiet=False):
        p = self._db.podcast(podcast_id)
        if not p or (not p.get("folder") and net.is_offline()):
            if not quiet and p:
                self.message.emit("Offline mode is on, so feeds can't be checked")
            return
        self._start_busy()

        def work():
            try:
                if p.get("folder"):
                    _info, episodes = pc.scan_folder(p["folder"])
                    return ("refreshed", (p["id"], None, episodes, quiet), "")
                info, episodes, final = pc.fetch_feed(p["feed_url"])
                info["feed_url"] = final
                return ("refreshed", (p["id"], info, episodes, quiet), "")
            except Exception as exc:  # noqa: BLE001 - a worker must always report back
                return ("refreshed", (p["id"], None, None, quiet), net.describe(exc))

        self._pool.submit(lambda: self._done.emit(work()))

    def _start_busy(self):
        self._busy += 1
        self.changed.emit()

    # --- episodes ----------------------------------------------------------------------------------------
    def _entry(self, e):
        """The queue entry that plays an episode: its downloaded file if there is one, else its stream."""
        local = e.get("local_path") if e.get("local_path") and os.path.isfile(e["local_path"]) else ""
        show = self._db.podcast(e["podcast_id"]) or {}
        resume = 0 if e.get("played") else int((e.get("position") or 0) * 1000)
        if e.get("duration") and resume > (e["duration"] - 5) * 1000:
            resume = 0
        if not resume and show.get("skip_intro"):
            resume = int(show["skip_intro"]) * 1000  # starts after the show's intro
        return {"path": local or e["url"], "kind": "episode", "episode_id": e["id"], "podcast_id": e["podcast_id"],
                "title": e["title"], "artist": e.get("podcast") or "", "album": e.get("podcast") or "",
                "album_artist": "", "artUrl": self._art(e.get("image")) or self._art(e.get("podcast_image")),
                "duration": e.get("duration") or 0, "resume_ms": resume, "id": -1_000_000 - e["id"],
                "speed": float(show.get("speed") or 0), "skip_outro": int(show.get("skip_outro") or 0),
                "scrobble": self._scrobble}

    @Slot(int)
    def play(self, episode_id):
        """Play an episode from where you stopped; the newer unplayed ones of the same show don't follow it,
        the older ones do (so a series plays on in order)."""
        e = self._db.episode(episode_id)
        if not e:
            return
        if not (e.get("local_path") and os.path.isfile(e["local_path"])) and net.is_offline():
            self.message.emit("Offline mode is on: download episodes to listen to them offline")
            return
        later = [x for x in reversed(self._db.episodes(e["podcast_id"]))
                 if x["published"] > e["published"] and not x["played"]][:20]
        if self._options["afterEpisode"] == "stop":
            later = []
        self._player.playList([self._entry(e)] + [self._entry(x) for x in later], 0)

    @Slot(int)
    def playLatest(self, podcast_id):
        """The show's newest episode you haven't played (or simply its newest)."""
        episodes = self._db.episodes(podcast_id)
        pick = next((e for e in episodes if not e["played"]), episodes[0] if episodes else None)
        if pick:
            self.play(pick["id"])

    @Slot(int)
    def playNext(self, episode_id):
        e = self._db.episode(episode_id)
        if e:
            self._player.playNext(self._entry(e))
            self.message.emit(f"“{e['title']}” will play next")

    @Slot(int)
    def enqueue(self, episode_id):
        e = self._db.episode(episode_id)
        if e:
            self._player.enqueue(self._entry(e))
            self.message.emit(f"“{e['title']}” added to the queue")

    @Slot(int, bool)
    def markPlayed(self, episode_id, played=True):
        self._db.set_played([episode_id], played)
        if played:
            self._after_played(episode_id)
        self.reload()

    @Slot(int)
    def markAllPlayed(self, podcast_id):
        episodes = self._db.episodes(podcast_id, unplayed_only=True)
        ids = [e["id"] for e in episodes]
        self._undo = [(e["id"], e["position"]) for e in episodes]
        self._db.set_played(ids, True)
        for i in ids:
            self._after_played(i)
        self.reload()
        if ids:
            self.undoable.emit(f"Marked {len(ids)} episode{'s' if len(ids) != 1 else ''} played")

    @Slot()
    def undo(self):
        """Mark the episodes marked played by "Mark all played" unplayed again, where you'd got to included.
        (Downloads already removed stay removed.)"""
        marks, self._undo = getattr(self, "_undo", None), None
        if marks:
            self._db.set_played([i for i, _ in marks], False)
            for episode_id, pos in marks:
                if pos:
                    self._db.set_position(episode_id, pos)
            self.reload()

    def _after_played(self, episode_id):
        if self._options["keep"] != "played":
            return
        e = self._db.episode(episode_id)
        playing = (self._player.playing and self._player.hasTrack
                   and self._player.current.get("episode_id") == episode_id)
        if e and e.get("url") and e.get("local_path") and not playing and self._remove_file(e["local_path"]):
            self._db.set_local_path(episode_id, "")

    # --- downloads -----------------------------------------------------------------------------------------
    @Slot(int)
    def download(self, episode_id):
        e = self._db.episode(episode_id)
        if not e or not e.get("url"):
            return
        with self._lock:
            if episode_id in self._downloading:
                return
            self._downloading[episode_id] = 0.0
            self._cancel.discard(episode_id)
        if net.is_offline():
            with self._lock:
                self._downloading.pop(episode_id, None)
            self.message.emit("Offline mode is on, so episodes can't download")
            return
        target = self._downloads / str(e["podcast_id"]) / f"{e['id']}{pc.extension_for(e['url'], e.get('mime', ''))}"
        self._progress_timer.start()
        self._reload_episodes()

        def progress(done, total):
            with self._lock:
                self._downloading[episode_id] = done / total if total else 0.0

        def work():
            try:
                path = pc.download(e["url"], target, progress, lambda: episode_id in self._cancel)
                return ("downloaded", episode_id, path)
            except InterruptedError:
                return ("downloaded", episode_id, None)
            except Exception as exc:  # noqa: BLE001 - a worker must always report back
                logger.warning("Episode download failed: %s", exc)
                return ("downloaded", episode_id, OSError(str(exc)))

        self._pool.submit(lambda: self._done.emit(work()))

    @Slot(int)
    def cancelDownload(self, episode_id):
        with self._lock:
            self._cancel.add(episode_id)

    @Slot(int)
    def removeDownload(self, episode_id):
        e = self._db.episode(episode_id)
        if e and e.get("url") and e.get("local_path"):  # a show from a folder: its files are yours, never deleted
            if self._remove_file(e["local_path"]):
                self._db.set_local_path(episode_id, "")
            else:
                self.message.emit("Couldn't remove the download while it's playing")
            self.reload()

    def _remove_file(self, path):
        """Delete a downloaded episode (only ever inside the downloads folder). True if it's gone."""
        try:
            if path and Path(path).resolve().is_relative_to(self._downloads.resolve()):
                os.remove(path)
                return True
        except FileNotFoundError:
            return True
        except OSError:
            pass
        return False

    def _download_new(self, podcast_id, how_many):
        p = self._db.podcast(podcast_id)
        if not p or not p.get("auto_download") or p.get("folder"):
            return
        for e in self._db.episodes(podcast_id, unplayed_only=True)[:min(how_many, int(p["auto_download"]))]:
            if not e.get("local_path"):
                self.download(e["id"])

    # --- files -----------------------------------------------------------------------------------------------
    @Slot(str, result=str)
    def importOpml(self, url):
        path = QUrl(url).toLocalFile() if url.startswith("file:") else url
        try:
            feeds = pc.parse_opml(Path(path).read_text(encoding="utf-8", errors="replace"))
        except (OSError, ValueError) as exc:
            return f"Couldn't read the file: {exc}"
        new = [f for f in feeds if not self._db.podcast_by(feed_url=f["feed_url"])]
        for f in new:
            self._db.add_podcast({"title": f["title"] or f["feed_url"], "feed_url": f["feed_url"]})
        self.reload()
        if new and not net.is_offline():
            for p in self._db.podcasts():
                if p["feed_url"] in {f["feed_url"] for f in new}:
                    self.refresh(p["id"], quiet=True)
        if not feeds:
            return "No podcasts in that file"
        return f"Following {len(new)} new show{'s' if len(new) != 1 else ''}" if new else "You already follow those shows"

    @Slot(str, result=str)
    def exportOpml(self, url):
        path = QUrl(url).toLocalFile() if url.startswith("file:") else url
        if not path.lower().endswith((".opml", ".xml")):
            path += ".opml"
        shows = [p for p in self._db.podcasts() if p.get("feed_url")]
        try:
            from .core.atomic import write_text

            write_text(path, pc.make_opml(shows))
        except OSError as exc:
            return f"Couldn't save: {exc.strerror or exc}"
        return f"Saved {len(shows)} show{'s' if len(shows) != 1 else ''} to {Path(path).name}"

    # --- directory ---------------------------------------------------------------------------------------
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
            self._results, self._status, self._searching = [], "", False
            self._mark_followed()
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
                return ("results", query, pc.search_directory(query))
            except Exception as exc:  # noqa: BLE001 - a worker must always report back
                logger.warning("Podcast search failed: %s", exc)
                return ("results", query, None)

        self._pool.submit(lambda: self._done.emit(work()))

    def _mark_followed(self):
        followed = {p["feed_url"] for p in self._db.podcasts()}
        self._results_model.set_items([{**r, "row": i, "followed": r["feed_url"] in followed, "artUrl": ""}
                                       for i, r in enumerate(self._results)])

    @Slot(int)
    def followResult(self, row):
        if 0 <= row < len(self._results):
            self.follow(self._results[row]["feed_url"])

    # --- what's playing ------------------------------------------------------------------------------------
    def _current_episode(self):
        if self._player.hasTrack and track_kind(self._player.current) == "episode":
            return self._player.current.get("episode_id") or 0
        return 0

    @Slot()
    def _on_track(self):
        if self._playing_id and self._playing_id != self._current_episode():
            self._finish(self._playing_id, self._last_pos, self._last_dur)
        self._playing_id = self._current_episode()
        self._last_pos, self._last_dur = 0, 0
        if self._playing_id:
            self._load_chapters(self._playing_id)
        elif self._chapters:
            self._chapters, self._chapters_for = [], 0
            self.chaptersChanged.emit()
        self._on_state()

    @Slot()
    def _on_state(self):
        if self._playing_id and self._player.playing:
            if not self._save_timer.isActive():
                self._save_timer.start()
        else:
            self._save_timer.stop()
            self._save_position()

    _last_pos = 0
    _last_dur = 0

    @Slot()
    def _note_position(self):
        """Where the playing episode is, kept in memory between saves: when it ends and the next one starts,
        this is how far it got."""
        if self._playing_id and self._player.hasTrack and self._player.current.get("episode_id") == self._playing_id:
            self._last_pos, self._last_dur = self._player.position / 1000.0, self._player.duration / 1000.0
            outro = self._player.current.get("skip_outro") or 0
            if outro and self._player.playing and self._last_dur > outro * 2 and self._last_pos >= self._last_dur - outro:
                self._finish(self._playing_id, self._last_dur, self._last_dur)  # the outro is skipped: it's played
                self._player.next()

    def _save_position(self):
        episode_id = self._current_episode()
        if not episode_id:
            return
        pos, dur = self._player.position / 1000.0, self._player.duration / 1000.0
        self._last_pos, self._last_dur = pos, dur
        if pos <= 1:
            return
        if near_end(pos, dur, self._options["playedWindow"]):
            self._finish(episode_id, pos, dur)
            return
        self._db.set_position(episode_id, pos)

    def _finish(self, episode_id, pos, dur):
        """Leaving an episode: near its end it's played, otherwise where you stopped is kept."""
        e = self._db.episode(episode_id)
        if not e:
            return
        dur = dur or e.get("duration") or 0
        if near_end(pos, dur, self._options["playedWindow"]):
            if not e["played"]:
                self._db.set_played([episode_id], True)
                self._after_played(episode_id)
                self.reload()
        elif pos > 1:
            self._db.set_position(episode_id, pos)
            self.reload()

    # chapters
    def _load_chapters(self, episode_id):
        e = self._db.episode(episode_id)
        self._chapters, self._chapters_for = [], episode_id
        self.chaptersChanged.emit()
        if not e:
            return
        local = e.get("local_path") if e.get("local_path") and os.path.isfile(e["local_path"]) else ""

        def work():
            chapters = pc.file_chapters(local) if local else []
            if not chapters and e.get("chapters_url") and not net.is_offline():
                try:
                    chapters = pc.fetch_chapters(e["chapters_url"])
                except Exception:  # noqa: BLE001 - a worker must always report back
                    chapters = []
            return ("chapters", episode_id, chapters)

        self._pool.submit(lambda: self._done.emit(work()))

    @Property("QVariantList", notify=chaptersChanged)
    def chapters(self):
        """The playing episode's chapters: [{start (ms), title}]."""
        return [{"start": int(c["start"] * 1000), "title": c["title"]} for c in self._chapters]

    @Slot(int)
    def seekChapter(self, index):
        if 0 <= index < len(self._chapters):
            self._player.seek(int(self._chapters[index]["start"] * 1000))

    # --- results from the workers --------------------------------------------------------------------------
    @Slot(object)
    def _apply(self, result):
        kind, what, value = result
        if kind in ("followed", "folder"):
            self._busy = max(0, self._busy - 1)
            if what is None:
                self.changed.emit()
                self.message.emit(value)
                return
            if kind == "followed":
                podcast, episodes, final = what
                podcast["feed_url"] = final
            else:
                podcast, episodes = what
            existing = self._db.podcast_by(podcast.get("feed_url", ""), podcast.get("folder", ""))
            podcast_id = self._db.add_podcast(podcast)
            self._db.merge_episodes(podcast_id, episodes)
            if not existing and self._options["newShowDownloads"] and not podcast.get("folder"):
                self._db.update_podcast(podcast_id, auto_download=self._options["newShowDownloads"])
                self._download_new(podcast_id, self._options["newShowDownloads"])
            self._db.update_podcast(podcast_id, checked=time.time(), error="")
            self.reload()
            self._mark_followed()
            self.resultsChanged.emit()
            self.message.emit(f"You already follow “{existing['title']}”" if existing
                              else f"Following “{podcast['title']}”")
        elif kind == "refreshed":
            self._busy = max(0, self._busy - 1)
            podcast_id, info, episodes, quiet = what
            if episodes is None:
                self._db.update_podcast(podcast_id, error=value, checked=time.time())
                if not quiet:
                    self.message.emit(f"Couldn't check for new episodes: {value}")
                    self.reload()
                else:
                    self._reload_timer.start()
                return
            if info:
                self._db.update_podcast(podcast_id, **{k: v for k, v in info.items() if v and k != "folder"})
            new = self._db.merge_episodes(podcast_id, episodes)
            self._db.update_podcast(podcast_id, checked=time.time(), error="")
            if quiet:
                self._reload_timer.start()
            else:
                self.reload()
            if new and self._options["notifyNew"]:
                show = self._db.podcast(podcast_id) or {}
                latest = self._db.episode(new[0]) or {}
                more = f" and {len(new) - 1} more" if len(new) > 1 else ""
                self.newEpisodes.emit(show.get("title", "A show you follow"), (latest.get("title") or "New episode") + more)
            if new:
                self._download_new(podcast_id, min(len(new), 3))
            if not quiet:
                self.message.emit(f"{len(new)} new episode{'s' if len(new) != 1 else ''}" if new else "No new episodes")
        elif kind == "results":
            self._searching = False
            if value is None:
                self._results, self._status = [], "Couldn't reach the podcast directory. Check your connection."
            else:
                self._results = value
                self._status = "" if value else f"No podcasts match “{what}”"
            self._mark_followed()
            self.resultsChanged.emit()
        elif kind == "downloaded":
            episode_id, path = what, value
            with self._lock:
                self._downloading.pop(episode_id, None)
                self._cancel.discard(episode_id)
            if isinstance(path, str):
                self._db.set_local_path(episode_id, path)
                if self._options["keep"] == "latest":
                    e = self._db.episode(episode_id)
                    if e:
                        self._enforce_keep(e["podcast_id"])
            elif isinstance(path, OSError):
                self.message.emit(f"Download failed: {path}")
            self.reload()
        elif kind == "images":
            self.reload()
        elif kind == "chapters":
            if what == self._chapters_for:
                self._chapters = value
                self.chaptersChanged.emit()

    # --- scrobbling and your listening -------------------------------------------------------------------
    @Property(bool, notify=listeningChanged)
    def scrobble(self):
        """Whether episodes count on Last.fm and ListenBrainz (as the show and the episode's title). Off unless
        you turn it on."""
        return self._scrobble

    @Slot(bool)
    def setScrobble(self, on):
        self._scrobble = bool(on)
        self._settings.setValue("podcasts/scrobble", self._scrobble)
        if self._player.hasTrack and track_kind(self._player.current) == "episode":
            self._player.current["scrobble"] = self._scrobble
        self.listeningChanged.emit()

    @Slot(int, result="QVariantMap")
    def listening(self, days):
        """Podcast listening for the last `days` days (0: all time): {hours, finished, top: [{id, name, hours}]}."""
        self._clock.tick()
        got = self._db.listening("podcast", days)
        return {"hours": round(got["seconds"] / 3600, 1), "finished": self._db.episodes_finished(days),
                "top": [{"id": t["item_id"], "name": t["name"], "hours": round(t["seconds"] / 3600, 1)} for t in got["top"]]}

    def shutdown(self):
        self._clock.stop()
        self._save_position()
        self._save_timer.stop()
        self._refresh_timer.stop()
        self._reload_timer.stop()
        self._progress_timer.stop()
        with self._lock:
            self._cancel.update(self._downloading)
        self._pool.shutdown(wait=False, cancel_futures=True)
        self._db.close()
