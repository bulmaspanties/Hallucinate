"""Measure ReplayGain for songs whose files carry no gain tags, an album at a time, in the background.

Like the waveform service, decoding uses QAudioDecoder on the GUI thread (it only delivers buffers there), each
file opened on a thread first so a slow disk can't hold the window (fileready.py); the
loudness maths is vectorised (see loudness.py), so the GUI thread only does a little numpy per buffer. Files
are never modified: results go to the database and are used when a file has no tags of its own."""
import logging

from PySide6.QtCore import Property, QObject, QUrl, Signal, Slot
from PySide6.QtMultimedia import QAudioDecoder

from . import loudness
from .core.db import Database
from .core.remote import SQL_LOCAL
from .fileready import FileReady
from .waveform import _SCALE

logger = logging.getLogger(__name__)


def channel_samples(buf):
    """A QAudioBuffer as float (frames, channels), or None for an unsupported format."""
    import numpy as np

    fmt = buf.format()
    spec = _SCALE.get(fmt.sampleFormat())
    channels = fmt.channelCount()
    if spec is None or channels <= 0:
        return None
    raw = spec[1](np.frombuffer(buf.constData(), dtype=spec[0], count=buf.sampleCount()))
    return raw.reshape(-1, channels)


class ReplayGainAnalyzer(QObject):
    """Queue albums with analyse(); progress is exposed for the UI, results are written to the database."""

    changed = Signal()
    finished = Signal()  # a run (everything queued) completed or was cancelled

    def __init__(self, db_path, parent=None):
        super().__init__(parent)
        self._db_path = str(db_path)
        self._db = None
        self._albums = []          # [(album_key, [paths])] still to do
        self._album = None         # (album_key, paths) in progress
        self._results = []         # per path in the current album
        self._index = -1
        self._decoder = None
        self._meter = None
        self._done_tracks = 0
        self._total_tracks = 0
        self._current = ""
        self._failed = 0
        self._ready = FileReady(self)  # each file is opened off this thread first (a slow disk can't hang it)
        from PySide6.QtCore import QSettings

        self._settings = QSettings("hallucinate", "hallucinate")
        self._auto = self._settings.value("replaygain/auto", False, bool)

    def _conn(self):
        if self._db is None:
            self._db = Database(self._db_path)
        return self._db

    # --- what the UI sees ------------------------------------------------------------------
    @Property(bool, notify=changed)
    def busy(self):
        return self._album is not None or bool(self._albums)

    @Property(int, notify=changed)
    def done(self):
        return self._done_tracks

    @Property(int, notify=changed)
    def total(self):
        return self._total_tracks

    @Property(str, notify=changed)
    def current(self):
        return self._current

    @Property(int, notify=changed)
    def failed(self):
        return self._failed

    @Property(bool, notify=changed)
    def auto(self):
        """Measure new music by itself after a scan adds or changes songs."""
        return self._auto

    @Slot(bool)
    def setAuto(self, on):
        self._auto = bool(on)
        self._settings.setValue("replaygain/auto", self._auto)
        self.changed.emit()
        if on and not self.busy:
            self.analyseMissing()

    def after_scan(self, stats):
        """A scan finished: with auto on, measure what it added or changed."""
        if self._auto and not self.busy and isinstance(stats, dict) and (stats.get("added") or stats.get("updated")):
            self.analyseMissing()

    @Slot(result=int)
    def missingCount(self):
        """Songs that have no ReplayGain yet (from tags or analysis)."""
        return self._conn().tracks_without_gain()

    # --- control -------------------------------------------------------------------------------
    @Slot()
    def analyseMissing(self):
        """Analyse every album that has a song without ReplayGain."""
        self.analyse(self._conn().albums_needing_gain())

    @Slot(str)
    def analyseAlbum(self, album_key):
        db = self._conn()
        paths = [r[0] for r in db.conn.execute(
            f"SELECT path FROM tracks WHERE album_key=? AND file IS NULL AND {SQL_LOCAL} "
            "ORDER BY disc_no, track_no, s_title", (album_key,))]
        if paths:
            self.analyse([(album_key, paths)])

    def analyse(self, albums):
        known = {k for k, _ in self._albums} | ({self._album[0]} if self._album else set())
        fresh = [(k, p) for k, p in albums if k not in known and p]
        if not fresh:
            return
        if not self.busy:
            self._done_tracks = self._total_tracks = self._failed = 0
        self._albums.extend(fresh)
        self._total_tracks += sum(len(p) for _, p in fresh)
        self.changed.emit()
        if self._album is None:
            self._next_album()

    @Slot()
    def cancel(self):
        self._albums.clear()
        self._stop_decoder()
        self._album = None
        self._current = ""
        self.changed.emit()
        self.finished.emit()

    def shutdown(self):
        self._albums.clear()
        self._stop_decoder()
        self._album = None
        if self._db is not None:
            self._db.close()
            self._db = None

    # --- work ------------------------------------------------------------------------------------
    def _next_album(self):
        if not self._albums:
            self._album = None
            self._current = ""
            self.changed.emit()
            self.finished.emit()
            return
        self._album = self._albums.pop(0)
        self._results = []
        self._index = -1
        self._next_track()

    def _next_track(self):
        key, paths = self._album
        self._index += 1
        if self._index >= len(paths):
            self._finish_album()
            return
        path = paths[self._index]
        self._current = path
        self.changed.emit()
        self._ready.check(path, self._opened)

    def _opened(self, ok):
        if not ok:
            logger.debug("ReplayGain analysis skipped %s: the file didn't open", self._current)
            self._failed += 1
            self._track_done(None)
            return
        path = self._current
        self._meter = loudness.Meter()
        self._decoder = QAudioDecoder(self)
        self._decoder.bufferReady.connect(self._on_buffer)
        self._decoder.finished.connect(self._on_finished)
        self._decoder.error.connect(self._on_error)
        self._decoder.setSource(QUrl.fromLocalFile(path))
        self._decoder.start()
        self.changed.emit()

    @Slot()
    def _on_buffer(self):
        if self._decoder is None:
            return
        buf = self._decoder.read()
        if not buf.isValid():
            return
        samples = channel_samples(buf)
        if samples is not None and samples.size:
            self._meter.add(samples, buf.format().sampleRate())

    @Slot()
    def _on_finished(self):
        if self._decoder is None:
            return
        self._track_done(loudness.track_result(self._meter))

    @Slot(QAudioDecoder.Error)
    def _on_error(self, _error):
        if self._decoder is None:
            return
        logger.debug("ReplayGain analysis failed for %s: %s", self._current, self._decoder.errorString())
        self._failed += 1
        self._track_done(None)

    def _track_done(self, result):
        self._stop_decoder()
        self._results.append(result)
        self._done_tracks += 1
        self._next_track()

    def _stop_decoder(self):
        self._ready.cancel()
        decoder, self._decoder = self._decoder, None
        if decoder is not None:
            decoder.blockSignals(True)  # stop() would report "finished" again, synchronously
            decoder.stop()
            decoder.deleteLater()

    def _finish_album(self):
        key, paths = self._album
        album = loudness.album_gain(self._results)
        rows = [{"path": p, "track_gain": round(r["gain"], 2), "album_gain": None if album is None else round(album, 2),
                 "peak": round(r["peak"], 6)}
                for p, r in zip(paths, self._results) if r is not None]
        if rows:
            try:
                self._conn().store_loudness(rows)
            except Exception:  # noqa: BLE001
                logger.exception("Could not save ReplayGain for %s", key)
        self._next_album()
