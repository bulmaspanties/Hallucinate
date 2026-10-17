"""Tag editing and cover art management for QML. All file and network work happens on worker threads."""
import hashlib
import logging
import os
import threading
import time
from urllib.parse import unquote, urlparse

from PySide6.QtCore import Property, QObject, QSettings, Signal, Slot

from .core import artfetch, health, net, tagedit
from .core.atomic import write_atomic
from .core.db import Database
from .core.scanner import Scanner
from .core.tags import _image_ext
from .library import _Reader, decorate

logger = logging.getLogger(__name__)


def _local_path(url):
    if url.startswith("file:"):
        return unquote(urlparse(url).path) if os.name != "nt" else unquote(urlparse(url).path).lstrip("/")
    return url


MUSICBRAINZ_INTERVAL = 1.1  # MusicBrainz asks for at most one request per second
FOLDER_COVER = "cover.jpg"  # the name nearly every player looks for


def _carry(db, path):
    """After this app rewrote `path`'s tags: keep its loudness measurement (the audio is the same)."""
    try:
        st = os.stat(path)
    except OSError:
        return
    db.carry_file_caches(path, st.st_mtime, st.st_size)


def _inside(path, folder):
    try:
        return os.path.commonpath([os.path.realpath(path), os.path.realpath(folder)]) == os.path.realpath(folder)
    except ValueError:  # another drive
        return False


def _as_jpeg(data):
    """JPEG bytes for a cover.jpg: a PNG is converted (Qt does it; the app has no other image library)."""
    if data[:3] == b"\xff\xd8\xff":
        return data
    from PySide6.QtCore import QBuffer, QByteArray, QIODevice
    from PySide6.QtGui import QImage

    image = QImage.fromData(data)
    if image.isNull():
        raise OSError("the picture couldn't be read")
    if image.hasAlphaChannel():  # JPEG has no transparency: put it on white rather than black
        flat = QImage(image.size(), QImage.Format.Format_RGB32)
        flat.fill(0xFFFFFF)
        from PySide6.QtGui import QPainter

        painter = QPainter(flat)
        painter.drawImage(0, 0, image)
        painter.end()
        image = flat
    out = QByteArray()
    buf = QBuffer(out)
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    if not image.save(buf, "JPEG", 92):
        raise OSError("the picture couldn't be saved as JPEG")
    return bytes(out.data())


def save_folder_cover(db, album_key, files, data):
    """Save the cover as cover.jpg in the album's folder, for other players and file managers. Only when the
    album has a folder of its own: one shared with other albums (a folder of singles, say) would give them all
    this cover. Returns the folder, or "" when it was left alone. Raises OSError when it can't be written."""
    folders = {os.path.dirname(f) for f in files if f}
    if len(folders) != 1:
        return ""
    folder = folders.pop()
    if not os.path.isabs(folder) or not os.path.isdir(folder):
        return ""  # songs on a music server (or a folder that's gone): no folder here to save it in
    # another album's song directly in this folder (not in a folder below it); "!" escapes LIKE's wildcards,
    # since "\\" is Windows' separator
    base = folder.replace("!", "!!").replace("%", "!%").replace("_", "!_") + os.sep
    shared = db.conn.execute("SELECT 1 FROM tracks WHERE album_key != ? AND path LIKE ? ESCAPE '!' "
                             "AND path NOT LIKE ? ESCAPE '!' LIMIT 1",
                             (album_key, base + "%", base + "%" + os.sep + "%")).fetchone()
    if shared:
        return ""
    target = os.path.join(folder, FOLDER_COVER)
    jpeg = _as_jpeg(data)
    try:
        with open(target, "rb") as fh:
            if fh.read(len(jpeg) + 1) == jpeg:
                return folder  # already there
    except OSError:
        pass
    write_atomic(target, lambda fh: fh.write(jpeg))
    return folder


class MetadataEditor(QObject):
    busyChanged = Signal()
    prefsChanged = Signal()
    coversChanged = Signal()
    _covers_progress = Signal(object)
    changed = Signal()  # tracks or art were modified; reload the library
    saved = Signal(int)
    failed = Signal(str)
    coverResult = Signal(bool, str)
    lookupResults = Signal("QVariantList", str)  # MusicBrainz releases matching an album, or [] and why
    releaseReady = Signal("QVariantMap")  # a chosen release: {fields, tracks, matched, error}
    _mb_done = Signal(object)
    genreFound = Signal("QVariantMap")  # one album's genre from findGenre(): {genre, genres, source} or {error}
    genresChanged = Signal()
    genresFinished = Signal(str)  # the "find all" summary, for a toast
    _genres_progress = Signal(object)
    _done = Signal(object)

    def __init__(self, db_path, art_dir, parent=None):
        super().__init__(parent)
        self._reader = _Reader(str(db_path), "metaedit")
        # The editor waits on these lookups; tag writing (hundreds of files for a bulk genre save) mustn't
        # make it wait, so they have their own worker.
        self._lookup = _Reader(str(db_path), "metaedit-lookup")
        self._art_dir = str(art_dir)
        self._busy = 0
        self._done.connect(self._finish)
        self._db_path = str(db_path)
        self._covers = {"busy": False, "done": 0, "total": 0, "found": 0, "current": ""}
        self._covers_stop = threading.Event()
        self._mb_done.connect(self._on_mb_done)
        self._covers_thread = None
        self._covers_progress.connect(self._apply_covers_progress)
        self._genres = {"busy": False, "done": 0, "total": 0, "found": 0, "current": "", "proposals": []}
        self._genres_stop = threading.Event()
        self._genres_thread = None
        self._genres_progress.connect(self._apply_genres_progress)
        settings = QSettings("hallucinate", "hallucinate")
        # Settings → Library: a cover you set is also saved as cover.jpg in the album's folder (on unless switched
        # off) and embedded in the songs if you ask (remembered from the last time)
        self._covers_to_folder = settings.value("covers/toFolder", True, type=bool)
        self._embed_covers = settings.value("covers/embed", False, type=bool)

    @Property(bool, notify=prefsChanged)
    def coversToFolder(self):
        return self._covers_to_folder

    @Slot(bool)
    def setCoversToFolder(self, on):
        self._covers_to_folder = bool(on)
        QSettings("hallucinate", "hallucinate").setValue("covers/toFolder", self._covers_to_folder)
        self.prefsChanged.emit()

    @Property(bool, notify=prefsChanged)
    def embedCovers(self):
        return self._embed_covers

    @Slot(bool)
    def setEmbedCovers(self, on):
        self._embed_covers = bool(on)
        QSettings("hallucinate", "hallucinate").setValue("covers/embed", self._embed_covers)
        self.prefsChanged.emit()

    @Property(bool, notify=busyChanged)
    def busy(self):
        return self._busy > 0

    def _run(self, fn, *args):
        self._busy += 1
        self.busyChanged.emit()

        def work(db):
            try:
                result = fn(db, *args)
            except tagedit.TagWriteError as exc:
                result = {"error": str(exc)}
            except OSError as exc:
                result = {"error": f"{exc.strerror or exc}"}
            except Exception as exc:  # noqa: BLE001
                logger.exception("Metadata operation failed")
                result = {"error": str(exc)}
            self._done.emit(result)

        self._reader.submit(work)

    @Slot(object)
    def _finish(self, result):
        self._busy -= 1
        self.busyChanged.emit()
        kind = result.get("kind")
        if kind == "tags":
            if result.get("errors"):
                self.failed.emit("; ".join(result["errors"][:3]))
            if result.get("saved"):
                self.saved.emit(result["saved"])
                self.changed.emit()
        elif kind == "cover":
            self.coverResult.emit(result["ok"], result["message"])
            if result["ok"]:
                self.changed.emit()
        elif "error" in result:
            self.failed.emit(result["error"])
            self.coverResult.emit(False, result["error"])

    # --- tag editing -----------------------------------------------------------------
    @Slot(str, result="QVariantMap")
    def trackInfo(self, path):
        row = self._lookup.submit(lambda db: db.track_by_path(path)).result(timeout=10)
        return decorate([row])[0] if row else {}

    # --- MusicBrainz -------------------------------------------------------------------------------------
    @Slot(str, str)
    def lookupAlbum(self, artist, album):
        """Find releases matching an album on MusicBrainz; lookupResults() reports back."""
        from .core import musicbrainz, net

        if net.is_offline():
            self.lookupResults.emit([], "Offline mode is on, so MusicBrainz can't be searched")
            return
        if not (album or "").strip():
            self.lookupResults.emit([], "The album needs a name to look it up")
            return

        def work():
            try:
                found = musicbrainz.search_releases(artist, album)
                self._mb_done.emit(("results", found, "" if found else "MusicBrainz has no album by that name"))
            except (OSError, ValueError, KeyError) as exc:
                self._mb_done.emit(("results", [], f"Couldn't reach MusicBrainz: {net.describe(exc)}"))

        threading.Thread(target=work, name="musicbrainz", daemon=True).start()

    @Slot(str, str)
    def chooseRelease(self, release_id, album_key):
        """Fetch a release and pair its tracks with the album's songs (by disc and track order, when the
        counts agree); releaseReady() hands over what to fill in."""
        from .core import musicbrainz

        songs = self._lookup.submit(lambda db: db.album_tracks(album_key)).result(timeout=10) if album_key else []

        def work():
            try:
                rel = musicbrainz.release(release_id)
            except (OSError, ValueError, KeyError) as exc:
                self._mb_done.emit(("release", {"error": f"Couldn't fetch that release: {net.describe(exc)}"}, ""))
                return
            pairs = musicbrainz.match_tracks([dict(s) for s in songs], rel["tracks"])
            self._mb_done.emit(("release", {
                "fields": {"album": rel["title"], "album_artist": rel["artist"], "year": rel["year"], "genre": rel["genre"]},
                "tracks": [{"path": p, "title": t["title"], "track_no": t["number"],
                            "disc_no": t["disc"] if rel["discs"] > 1 else 0, "artist": t["artist"]} for p, t in pairs],
                "matched": len(pairs), "songs": len(songs), "releaseTracks": len(rel["tracks"]), "error": "",
            }, ""))

        threading.Thread(target=work, name="musicbrainz", daemon=True).start()

    @Slot(object)
    def _on_mb_done(self, result):
        kind, value, message = result
        if kind == "results":
            self.lookupResults.emit(value, message)
        elif kind == "genre":
            self.genreFound.emit(value)
        else:
            self.releaseReady.emit(value)

    @Slot("QVariantList")
    def saveTrackTags(self, items):
        """Write each song its own tags: [{path, title, track_no, disc_no, artist}] (from a MusicBrainz match)."""
        items = [dict(i) for i in items]

        def save_each(db, rows):
            total = {"kind": "tags", "saved": 0, "errors": []}
            for row in rows:
                path = row.pop("path")
                fields = {k: str(v) for k, v in row.items() if v not in (None, "", 0)}
                result = self._save_tags(db, [path], fields)
                total["saved"] += result["saved"]
                total["errors"] += result["errors"]
            return total

        self._run(save_each, items)

    @Slot("QVariantList", "QVariantMap")
    def saveTags(self, paths, fields):
        paths, fields = list(paths), dict(fields)
        self._run(self._save_tags, paths, fields)

    def _save_tags(self, db, paths, fields):
        errors, ok = [], []
        for path in paths:
            try:
                tagedit.write_tags(path, fields)
                _carry(db, path)
                ok.append(path)
            except tagedit.TagWriteError as exc:
                errors.append(f"{os.path.basename(path)}: {exc}")
        if ok:
            Scanner(db, self._art_dir).refresh_files(ok)
        return {"kind": "tags", "saved": len(ok), "errors": errors}

    # --- cover art -----------------------------------------------------------------------
    def _store_cover(self, db, album_key, data, embed, to_folder=None):
        if not (data[:8] == b"\x89PNG\r\n\x1a\n" or data[:3] == b"\xff\xd8\xff"):
            raise tagedit.TagWriteError("Not a PNG or JPEG image")
        to_folder = self._covers_to_folder if to_folder is None else to_folder
        name = f"{album_key}-{hashlib.sha1(data, usedforsecurity=False).hexdigest()[:8]}{_image_ext(data)}"
        path = os.path.join(self._art_dir, name)
        os.makedirs(self._art_dir, exist_ok=True)
        write_atomic(path, lambda fh: fh.write(data))
        before = db.chosen_art(album_key)
        db.set_chosen_art(album_key, path)  # the scanner keeps it from now on
        db.commit()
        if before and before != path and _inside(before, self._art_dir) and not db.art_in_use(before):
            try:
                os.unlink(before)  # the cover it replaces, if nothing else shows it
            except OSError:
                pass
        problems = []
        saved_in = ""
        if to_folder:
            try:
                saved_in = save_folder_cover(db, album_key,
                                             [t.get("file") or t["path"] for t in db.album_tracks(album_key)], data)
            except OSError as exc:
                problems.append(f"cover.jpg: {exc.strerror or exc}")
        if embed:
            for t in db.album_tracks(album_key):
                try:
                    tagedit.embed_cover(t["path"], data)
                    _carry(db, t["path"])
                except tagedit.TagWriteError as exc:
                    problems.append(f"{os.path.basename(t['path'])}: {exc}")
            Scanner(db, self._art_dir).refresh_files([t["path"] for t in db.album_tracks(album_key)])
        msg = "Cover updated" + (" and saved as cover.jpg in the album's folder" if saved_in else "")
        msg += f" (couldn't save it in: {'; '.join(problems[:2])})" if problems else ""
        return {"kind": "cover", "ok": True, "message": msg}

    @Slot(str, str, bool)
    def setCoverFromFile(self, album_key, url, embed):
        self._run(lambda db, k, u, e: self._store_cover(db, k, open(_local_path(u), "rb").read(artfetch.MAX_BYTES), e),
                  album_key, url, embed)

    @Slot(str, str, str, bool)
    def fetchCover(self, album_key, artist, album, embed):
        def work(db, key, art, alb, emb):
            try:
                data = artfetch.fetch_cover(art, alb)
            except artfetch.ServiceError as exc:  # their servers, already worded for people
                return {"kind": "cover", "ok": False, "message": str(exc)}
            except OSError as exc:
                return {"kind": "cover", "ok": False, "message": f"Couldn't fetch the cover: {net.describe(exc)}"}
            if not data:
                return {"kind": "cover", "ok": False, "message": "No cover found online"}
            return self._store_cover(db, key, data, emb)

        self._run(work, album_key, artist, album, embed)

    # --- every missing cover at once ---------------------------------------------------
    @Property(bool, notify=coversChanged)
    def coversBusy(self):
        return self._covers["busy"]

    @Property(int, notify=coversChanged)
    def coversDone(self):
        return self._covers["done"]

    @Property(int, notify=coversChanged)
    def coversTotal(self):
        return self._covers["total"]

    @Property(int, notify=coversChanged)
    def coversFound(self):
        return self._covers["found"]

    @Property(str, notify=coversChanged)
    def coversCurrent(self):
        return self._covers["current"]

    @Slot()
    def fetchMissingCovers(self):
        """Look up every album without a cover online, one by one (MusicBrainz allows a request a second)."""
        if self._covers["busy"]:
            return
        self._covers_stop.clear()
        self._covers = {"busy": True, "done": 0, "total": 0, "found": 0, "current": ""}
        self.coversChanged.emit()
        self._covers_thread = threading.Thread(target=self._fetch_covers, name="covers", daemon=True)
        self._covers_thread.start()

    @Slot()
    def cancelCovers(self):
        self._covers_stop.set()

    def _fetch_covers(self, sleep=time.sleep):
        db = Database(self._db_path)
        found = done = 0
        try:
            albums = [a for a in health.missing_covers_all(db)
                      if (a.get("album") or "").strip() and a.get("album") != health.UNKNOWN_ALBUM]
            self._covers_progress.emit({"total": len(albums)})
            last = 0.0
            for album in albums:
                if self._covers_stop.is_set() or net.is_offline():
                    break
                self._covers_progress.emit({"current": album["album"]})
                wait = MUSICBRAINZ_INTERVAL - (time.monotonic() - last)
                if wait > 0:
                    sleep(wait)
                last = time.monotonic()
                try:
                    data = artfetch.fetch_cover(album.get("album_artist") or "", album["album"])
                    if data:
                        self._store_cover(db, album["album_key"], data, False)
                        found += 1
                except (OSError, tagedit.TagWriteError) as exc:
                    logger.info("No cover found for an album: %s", exc)
                done += 1
                self._covers_progress.emit({"done": done, "found": found, "reload": bool(found) and found % 10 == 0})
        except Exception:  # noqa: BLE001
            logger.exception("Fetching covers failed")
        finally:
            db.close()
            self._covers_progress.emit({"busy": False, "current": "", "reload": found > 0, "finished": True})

    @Slot(object)
    def _apply_covers_progress(self, update):
        reload_ = update.pop("reload", False)
        finished = update.pop("finished", False)
        self._covers.update(update)
        self.coversChanged.emit()
        if reload_:
            self.changed.emit()
        if finished:
            self.coverResult.emit(True, f"Found {self._covers['found']} of {self._covers['done']} covers")

    # --- genres from MusicBrainz -------------------------------------------------------------------------
    @Slot(str, str)
    def findGenre(self, artist, album):
        """Look up one album's genre; genreFound() reports back. Nothing is written: the editor fills its
        Genre field and you save as usual."""
        from .core import musicbrainz

        if net.is_offline():
            self.genreFound.emit({"error": "Offline mode is on, so MusicBrainz can't be searched"})
            return
        if not (album or "").strip():
            self.genreFound.emit({"error": "The song needs an album name to look up its genre"})
            return

        def work():
            try:
                found = musicbrainz.find_genre(artist, album)
                self._mb_done.emit(("genre", found or {"error": "MusicBrainz has no genre for this album"}, ""))
            except (OSError, ValueError, KeyError) as exc:
                self._mb_done.emit(("genre", {"error": f"Couldn't reach MusicBrainz: {net.describe(exc)}"}, ""))

        threading.Thread(target=work, name="musicbrainz-genre", daemon=True).start()

    @Property(bool, notify=genresChanged)
    def genresBusy(self):
        return self._genres["busy"]

    @Property(int, notify=genresChanged)
    def genresDone(self):
        return self._genres["done"]

    @Property(int, notify=genresChanged)
    def genresTotal(self):
        return self._genres["total"]

    @Property(int, notify=genresChanged)
    def genresFound(self):
        return self._genres["found"]

    @Property(str, notify=genresChanged)
    def genresCurrent(self):
        return self._genres["current"]

    @Property("QVariantList", notify=genresChanged)
    def genreProposals(self):
        """What the last "find all" turned up, waiting to be checked and saved:
        [{album_key, album, artist, genre, genres, source, songs}]."""
        return list(self._genres["proposals"])

    @Slot()
    def findMissingGenres(self):
        """Look up a genre for every album without one, about one request a second. Nothing is written until
        saveGenres() is called with the ones you keep."""
        if self._genres["busy"]:
            return
        self._genres_stop.clear()
        self._genres = {"busy": True, "done": 0, "total": 0, "found": 0, "current": "", "proposals": []}
        self.genresChanged.emit()
        self._genres_thread = threading.Thread(target=self._fetch_genres, name="genres", daemon=True)
        self._genres_thread.start()

    @Slot()
    def cancelGenres(self):
        self._genres_stop.set()

    @Slot()
    def clearGenreProposals(self):
        self._genres["proposals"] = []
        self.genresChanged.emit()

    def _fetch_genres(self):
        from .core import musicbrainz

        db = Database(self._db_path)
        found, proposals, artists = 0, [], {}
        try:
            albums = [a for a in health.missing_genre_all(db)
                      if (a.get("album") or "").strip() and a.get("album") != health.UNKNOWN_ALBUM]
            self._genres_progress.emit({"total": len(albums)})
            for done, album in enumerate(albums, start=1):
                if self._genres_stop.is_set() or net.is_offline():
                    break
                self._genres_progress.emit({"current": album["album"]})
                artist = album.get("album_artist") or ""
                if artist == health.UNKNOWN_ARTIST:
                    artist = ""
                try:
                    hit = musicbrainz.find_genre(artist, album["album"], artists)
                except (OSError, ValueError, KeyError) as exc:
                    logger.info("No genre found for an album: %s", exc)
                    hit = None
                if hit:
                    found += 1
                    proposals.append({"album_key": album["album_key"], "album": album["album"], "artist": artist,
                                      "genre": hit["genre"], "genres": hit["genres"], "source": hit["source"],
                                      "songs": int(album.get("n") or 0)})
                self._genres_progress.emit({"done": done, "found": found})
        except Exception:  # noqa: BLE001
            logger.exception("Finding genres failed")
        finally:
            db.close()
            self._genres_progress.emit({"busy": False, "current": "", "proposals": proposals, "finished": True})

    @Slot(object)
    def _apply_genres_progress(self, update):
        finished = update.pop("finished", False)
        self._genres.update(update)
        self.genresChanged.emit()
        if finished:
            g = self._genres
            stopped = g["done"] < g["total"]
            self.genresFinished.emit(f"Found genres for {g['found']} of {g['done']} albums"
                                        + (" (stopped early)" if stopped else "") + ". Check them, then save.")

    @Slot("QVariantList")
    def saveGenres(self, items):
        """Write each album's chosen genre to its songs: [{album_key, genre}]."""
        items = [(str(i["album_key"]), str(i["genre"]).strip()) for i in items if str(i.get("genre") or "").strip()]

        def save_all(db, pairs):
            total = {"kind": "tags", "saved": 0, "errors": []}
            for key, genre in pairs:
                paths = [t["path"] for t in db.album_tracks(key)]
                result = self._save_tags(db, paths, {"genre": genre})
                total["saved"] += result["saved"]
                total["errors"] += result["errors"]
            return total

        if items:
            self._run(save_all, items)
        self._genres["proposals"] = []
        self.genresChanged.emit()

    def shutdown(self):
        self._covers_stop.set()
        self._genres_stop.set()
        if self._covers_thread is not None:
            self._covers_thread.join(timeout=2)
        if self._genres_thread is not None:
            self._genres_thread.join(timeout=2)
        self._lookup.close()
        self._reader.close()
