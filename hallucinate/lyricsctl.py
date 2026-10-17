"""Lyrics for the playing track: DB cache -> embedded/.lrc -> LRCLIB, with synced line tracking."""
import logging
import os
import time

from PySide6.QtCore import Property, QObject, QSettings, Signal, Slot

from .core import lyrics as lx
from .library import _Reader

logger = logging.getLogger(__name__)
NOT_FOUND = "none"  # remembered when LRCLIB has no lyrics for a song
RETRY_MISSING_S = 30 * 86400  # ...and asked again after a month, in case someone has added them


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
        self._settings = QSettings("hallucinate", "hallucinate")
        # Settings → Internet & sharing: look up songs with no lyrics of their own on LRCLIB (artist, title, album
        # and length are sent; no account, nothing else)
        self._online = self._settings.value("lyrics/online", True, type=bool)
        self._enabled = True  # Settings → Features; off, nothing is read or looked up
        self._offset = 0  # ms; positive shows lines earlier (as LRC's [offset:])
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

    @Property(int, notify=lineChanged)
    def offset(self):
        return self._offset

    @Slot(int)
    def nudge(self, ms):
        """Shift the synced lines `ms` earlier (negative: later) while listening."""
        if self._lines:
            self._offset = max(-60_000, min(60_000, self._offset + int(ms)))
            self._line = -2  # force an update
            self._on_position()
            self.lineChanged.emit()

    @Slot()
    def resetOffset(self):
        self.nudge(-self._offset)

    @Slot(result=str)
    def saveTiming(self):
        """Write the lines with the current offset to an .lrc file next to the song (and the lyrics cache)."""
        if not self._lines or not self._path:
            return "No synced lyrics to save"
        target = lx.sidecar_path(self._path)
        if target is None:
            return "Lyrics for songs from a CUE sheet can't be saved next to the file"
        text = lx.format_lrc([(ln["t"], ln["text"]) for ln in self._lines], self._offset)
        from .core.atomic import write_text

        try:
            write_text(target, text)  # your own .lrc is replaced whole or not at all
        except OSError as exc:
            return f"Couldn't save {os.path.basename(target)}: {exc.strerror or exc}"
        path, plain = self._path, self._plain
        self._reader.submit(lambda db: db.set_lyrics(path, text, plain, "lrc file"))
        parsed = lx.parse_lrc(text)
        self._times = [t for t, _ in parsed]
        self._lines = [{"t": t, "text": s} for t, s in parsed]
        self._offset = 0
        self._source = "lrc file"
        self.changed.emit()
        self.lineChanged.emit()
        return f"Saved {os.path.basename(target)}"

    @Property(bool, notify=changed)
    def onlineLookup(self):
        return self._online

    @Slot(bool)
    def setOnlineLookup(self, on):
        on = bool(on)
        if on != self._online:
            self._online = on
            self._settings.setValue("lyrics/online", on)
            self.changed.emit()
            self.reload()

    @Slot(bool)
    def setEnabled(self, on):
        if bool(on) != self._enabled:
            self._enabled = bool(on)
            self._path = ""
            self.reload()

    @Slot()
    def reload(self):
        track = self._player.current if self._player.hasTrack and self._enabled else {}
        if (track.get("kind") or "music") != "music":
            track = {}  # radio and podcasts have no lyrics to find
        path = track.get("path", "")
        if path == self._path and self._status in ("found", "loading"):
            return
        self._path = path
        self._token += 1
        self._lines, self._times, self._plain, self._source = [], [], "", ""
        self._line = -1
        self._offset = 0
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
                # Lyrics of your own (in the file's tags or an .lrc beside it) come first, even when they were
                # added after lyrics were found online
                text = lx.read_embedded(path)
                if text.strip():
                    synced = text if lx.is_synced(text) else ""
                    result.update(synced=synced, plain=lx.strip_timestamps(text) if synced else text,
                                  source="embedded", status="found")
                    return self._loaded.emit(result)
                if cached and (cached["synced"] or cached["plain"]):
                    result.update(synced=cached["synced"], plain=cached["plain"], source=cached["source"], status="found")
                    return self._loaded.emit(result)
                # LRCLIB had nothing last time: ask again only after a while, not every time the song plays
                recently_missed = (cached and cached["source"] == NOT_FOUND
                                   and time.time() - (cached["fetched"] or 0) < RETRY_MISSING_S)
                if online and not recently_missed:
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
                    else:
                        db.set_lyrics(path, "", "", NOT_FOUND)
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
        line = lx.line_at(self._times, self._player.position + self._offset)
        if line != self._line:
            self._line = line
            self.lineChanged.emit()

    def shutdown(self):
        self._reader.close()
