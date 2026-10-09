"""Tag editing and cover art management for QML. All file and network work happens on worker threads."""
import hashlib
import logging
import os
from urllib.parse import unquote, urlparse

from PySide6.QtCore import Property, QObject, Signal, Slot

from .core import artfetch, tagedit
from .core.scanner import Scanner
from .core.tags import _image_ext
from .library import _Reader, decorate

logger = logging.getLogger(__name__)


def _local_path(url):
    if url.startswith("file:"):
        return unquote(urlparse(url).path) if os.name != "nt" else unquote(urlparse(url).path).lstrip("/")
    return url


class MetadataEditor(QObject):
    busyChanged = Signal()
    changed = Signal()  # tracks or art were modified; reload the library
    saved = Signal(int)
    failed = Signal(str)
    coverResult = Signal(bool, str)
    _done = Signal(object)

    def __init__(self, db_path, art_dir, parent=None):
        super().__init__(parent)
        self._reader = _Reader(str(db_path), "metaedit")
        self._art_dir = str(art_dir)
        self._busy = 0
        self._done.connect(self._finish)

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
        row = self._reader.submit(lambda db: db.track_by_path(path)).result(timeout=10)
        return decorate([row])[0] if row else {}

    @Slot("QVariantList", "QVariantMap")
    def saveTags(self, paths, fields):
        paths, fields = list(paths), dict(fields)
        self._run(self._save_tags, paths, fields)

    def _save_tags(self, db, paths, fields):
        errors, ok = [], []
        for path in paths:
            try:
                tagedit.write_tags(path, fields)
                ok.append(path)
            except tagedit.TagWriteError as exc:
                errors.append(f"{os.path.basename(path)}: {exc}")
        if ok:
            Scanner(db, self._art_dir).refresh_files(ok)
        return {"kind": "tags", "saved": len(ok), "errors": errors}

    # --- cover art -----------------------------------------------------------------------
    def _store_cover(self, db, album_key, data, embed):
        if not (data[:8] == b"\x89PNG\r\n\x1a\n" or data[:3] == b"\xff\xd8\xff"):
            raise tagedit.TagWriteError("Not a PNG or JPEG image")
        name = f"{album_key}-{hashlib.sha1(data).hexdigest()[:8]}{_image_ext(data)}"
        path = os.path.join(self._art_dir, name)
        os.makedirs(self._art_dir, exist_ok=True)
        with open(path, "wb") as fh:
            fh.write(data)
        db.set_album_art(album_key, path)
        db.commit()
        problems = []
        if embed:
            for t in db.album_tracks(album_key):
                try:
                    tagedit.embed_cover(t["path"], data)
                except tagedit.TagWriteError as exc:
                    problems.append(f"{os.path.basename(t['path'])}: {exc}")
            Scanner(db, self._art_dir).refresh_files([t["path"] for t in db.album_tracks(album_key)])
        msg = "Cover updated" + (f" (could not embed in: {'; '.join(problems[:2])})" if problems else "")
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
            except OSError as exc:
                return {"kind": "cover", "ok": False, "message": f"Network error: {exc}"}
            if not data:
                return {"kind": "cover", "ok": False, "message": "No cover found online"}
            return self._store_cover(db, key, data, emb)

        self._run(work, album_key, artist, album, embed)

    def shutdown(self):
        self._reader.close()
