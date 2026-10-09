"""Lyrics for the playing track: DB cache -> embedded/.lrc -> LRCLIB, with synced line tracking."""
import logging

from PySide6.QtCore import Property, QObject, Signal, Slot

from .core import lyrics as lx
from .library import _Reader

logger = logging.getLogger(__name__)


class LyricsController(QObject):
    changed = Signal()
    lineChanged = Signal()
    _loaded = Signal(object)

    def __init__(self, db_path, player, parent=None):
        super().__init__(parent)
        self._reader = _Reader(str(db_path), "lyrics")
        self._player = player
        self._path = ""
        self._lines = []  # [{"t": ms, "text": str}]
        self._times = []
        self._plain = ""
        self._status = "idle"  # idle | loading | found | none | offline
        self._source = ""
        self._line = -1
        self._token = 0
        self._online = True
        self._loaded.connect(self._apply)
        player.trackChanged.connect(self.reload)
        player.positionChanged.connect(self._on_position)
        self.reload()

    @Property("QVariantList", notify=changed)
    def lines(self):
        return self._lines

    @Property(str, notify=changed)
    def plain(self):
        return self._plain

    @Property(bool, notify=changed)
    def synced(self):
        return bool(self._lines)

    @Property(str, notify=changed)
    def status(self):
        return self._status

    @Property(str, notify=changed)
    def source(self):
        return self._source

    @Property(int, notify=lineChanged)
    def currentLine(self):
        return self._line

    @Property(bool, notify=changed)
    def onlineLookup(self):
        return self._online

    @Slot(bool)
    def setOnlineLookup(self, on):
        if on != self._online:
            self._online = on
            self.changed.emit()
            self.reload()

    @Slot()
    def reload(self):
        track = self._player.current if self._player.hasTrack else {}
        path = track.get("path", "")
        if path == self._path and self._status in ("found", "loading"):
            return
        self._path = path
        self._token += 1
        self._lines, self._times, self._plain, self._source = [], [], "", ""
        self._line = -1
        self._status = "loading" if path else "idle"
        self.changed.emit()
        self.lineChanged.emit()
        if not path:
            return
        token, online = self._token, self._online
        info = {k: track.get(k, "") for k in ("artist", "title", "album", "duration")}

        def work(db):
            result = {"token": token, "path": path, "synced": "", "plain": "", "source": "", "status": "none"}
            try:
                cached = db.get_lyrics(path)
                if cached and (cached["synced"] or cached["plain"]):
                    result.update(synced=cached["synced"], plain=cached["plain"], source=cached["source"], status="found")
                    return self._loaded.emit(result)
                text = lx.read_embedded(path)
                if text.strip():
                    synced = text if lx.is_synced(text) else ""
                    result.update(synced=synced, plain=lx.strip_timestamps(text) if synced else text,
                                  source="embedded", status="found")
                    return self._loaded.emit(result)
                if online:
                    try:
                        found = lx.fetch_lrclib(info["artist"], info["title"], info["album"], info["duration"])
                    except OSError:
                        result["status"] = "offline"
                        return self._loaded.emit(result)
                    if found:
                        synced, plain = found
                        db.set_lyrics(path, synced, plain or lx.strip_timestamps(synced), "LRCLIB")
                        result.update(synced=synced, plain=plain or lx.strip_timestamps(synced), source="LRCLIB",
                                      status="found")
            except Exception:  # noqa: BLE001
                logger.exception("Lyrics lookup failed")
            self._loaded.emit(result)

        self._reader.submit(work)

    @Slot(object)
    def _apply(self, r):
        if r["token"] != self._token:
            return
        parsed = lx.parse_lrc(r["synced"]) if r["synced"] else []
        self._times = [t for t, _ in parsed]
        self._lines = [{"t": t, "text": s} for t, s in parsed]
        self._plain = r["plain"]
        self._source = r["source"]
        self._status = r["status"]
        self._line = -1
        self.changed.emit()
        self._on_position()

    def _on_position(self):
        if not self._times:
            return
        line = lx.line_at(self._times, self._player.position)
        if line != self._line:
            self._line = line
            self.lineChanged.emit()

    def shutdown(self):
        self._reader.close()
