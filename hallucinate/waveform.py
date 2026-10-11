"""Waveforms for the seek bar: each track is decoded once, in the background, into POINTS loudness values.

QAudioDecoder decodes on FFmpeg's own thread but only delivers buffers to a thread with the GUI event loop
(created on a QThread it never reports anything), so the service lives on the GUI thread; it only receives
small 8 kHz mono buffers there, roughly a third of a second of work for a five-minute track in all.
Results are cached on disk (one small file per track, keyed by path, size and modification time, so edited
files are analysed again) and in memory for the session."""
import hashlib
import logging
import os
from collections import OrderedDict
from pathlib import Path

import numpy as np
from PySide6.QtCore import QObject, QUrl, Signal, Slot
from PySide6.QtMultimedia import QAudioDecoder, QAudioFormat

logger = logging.getLogger(__name__)
POINTS = 600
MEMORY_ITEMS = 64


BLOCK = 512  # frames summarised together as each buffer arrives


def blocks_from_samples(samples, block=BLOCK):
    """(mean square, peak) of each `block`-frame slice of mono float samples."""
    samples = np.abs(np.asarray(samples, dtype=np.float32))
    if samples.size == 0:
        return np.zeros(0, np.float32), np.zeros(0, np.float32)
    pad = (-samples.size) % block
    if pad:
        samples = np.concatenate([samples, np.zeros(pad, np.float32)])
    frames = samples.reshape(-1, block)
    return (frames * frames).mean(axis=1), frames.max(axis=1)


def peaks_from_blocks(mean_square, peak, points=POINTS):
    """Loudness envelope as `points` values in 0..1 (the loudest point is 1).

    RMS (body) and peak (transients) are blended so quiet passages still show some texture."""
    n = len(mean_square)
    if n == 0:
        return []
    edges = np.linspace(0, n, points + 1).astype(np.int64)
    out = np.zeros(points, dtype=np.float32)
    for i in range(points):
        lo, hi = edges[i], max(edges[i + 1], edges[i] + 1)
        if lo < n:
            out[i] = 0.7 * float(np.sqrt(mean_square[lo:hi].mean())) * 1.414 + 0.3 * float(peak[lo:hi].max())
    top = float(out.max())
    if top <= 1e-6:
        return [0.0] * points
    return [round(float(v), 4) for v in np.clip(out / top, 0.0, 1.0)]


def peaks_from_samples(samples, points=POINTS):
    return peaks_from_blocks(*blocks_from_samples(samples), points)


_SCALE = {
    QAudioFormat.SampleFormat.UInt8: (np.uint8, lambda x: (x.astype(np.float32) - 128.0) / 128.0),
    QAudioFormat.SampleFormat.Int16: (np.int16, lambda x: x.astype(np.float32) / 32768.0),
    QAudioFormat.SampleFormat.Int32: (np.int32, lambda x: x.astype(np.float32) / 2147483648.0),
    QAudioFormat.SampleFormat.Float: (np.float32, lambda x: x),
}


def mono_samples(buf):
    """A QAudioBuffer as mono float samples (the louder channel at each frame), or None if unsupported."""
    fmt = buf.format()
    spec = _SCALE.get(fmt.sampleFormat())
    channels = fmt.channelCount()
    if spec is None or channels <= 0:
        return None
    raw = spec[1](np.frombuffer(buf.constData(), dtype=spec[0], count=buf.sampleCount()))
    return np.abs(raw.reshape(-1, channels)).max(axis=1) if channels > 1 else raw


def cache_name(path):
    try:
        st = os.stat(path)
    except OSError:
        return None
    key = f"{path}|{st.st_size}|{st.st_mtime_ns}".encode("utf-8", "surrogatepass")
    return hashlib.sha1(key).hexdigest() + ".wf"


class _Worker(QObject):
    """Decodes one track at a time."""

    done = Signal(str, object)

    def __init__(self, cache_dir, parent=None):
        super().__init__(parent)
        self._cache_dir = Path(cache_dir)
        self._queue = []
        self._decoder = None
        self._path = ""
        self._ms = []
        self._peak = []

    @Slot(str, bool)
    def enqueue(self, path, urgent):
        if path == self._path or path in self._queue:
            if urgent and path in self._queue:
                self._queue.remove(path)
                self._queue.insert(0, path)
            return
        self._queue.insert(0, path) if urgent else self._queue.append(path)
        self._next()

    def _next(self):
        if self._decoder is not None or not self._queue:
            return
        self._path = self._queue.pop(0)
        self._ms, self._peak = [], []
        # Decode in the file's own format: asking QAudioDecoder to resample stalls on some files (MP3).
        self._decoder = QAudioDecoder(self)
        self._decoder.bufferReady.connect(self._on_buffer)
        self._decoder.finished.connect(self._on_finished)
        self._decoder.error.connect(self._on_error)
        self._decoder.setSource(QUrl.fromLocalFile(self._path))
        self._decoder.start()

    @Slot()
    def _on_buffer(self):
        if self._decoder is None:
            return
        buf = self._decoder.read()
        samples = mono_samples(buf) if buf.isValid() else None
        if samples is not None and samples.size:
            ms, peak = blocks_from_samples(samples)
            self._ms.append(ms)
            self._peak.append(peak)

    @Slot()
    def _on_finished(self):
        if self._decoder is None:
            return
        peaks = peaks_from_blocks(np.concatenate(self._ms), np.concatenate(self._peak)) if self._ms else []
        name = cache_name(self._path)
        if peaks and name:
            try:
                self._cache_dir.mkdir(parents=True, exist_ok=True)
                (self._cache_dir / name).write_bytes(bytes(int(round(v * 255)) for v in peaks))
            except OSError as exc:
                logger.debug("Could not cache waveform: %s", exc)
        self._finish(peaks)

    @Slot(QAudioDecoder.Error)
    def _on_error(self, _error):
        if self._decoder is None:
            return
        logger.debug("Waveform unavailable for %s: %s", self._path, self._decoder.errorString())
        self._finish([])

    def _finish(self, peaks):
        path, decoder = self._path, self._decoder
        self._decoder, self._path, self._ms, self._peak = None, "", [], []
        decoder.blockSignals(True)  # stop() would report "finished" again, synchronously
        decoder.stop()
        decoder.deleteLater()
        self.done.emit(path, peaks)
        self._next()

    @Slot()
    def stop(self):
        self._queue.clear()
        if self._decoder is not None:
            self._decoder.blockSignals(True)
            self._decoder.stop()
            self._decoder = None


class WaveformService(QObject):
    """Ask for a track's waveform; `ready(path)` fires when `peaks(path)` has it."""

    ready = Signal(str)

    def __init__(self, cache_dir, parent=None):
        super().__init__(parent)
        self._cache_dir = Path(cache_dir)
        self._memory = OrderedDict()
        self._worker = _Worker(cache_dir, self)
        self._worker.done.connect(self._on_done)

    def peaks(self, path):
        """The waveform if known (memory or disk), else None."""
        if path in self._memory:
            self._memory.move_to_end(path)
            return self._memory[path]
        name = cache_name(path)
        if name:
            try:
                data = (self._cache_dir / name).read_bytes()
            except OSError:
                data = b""
            if len(data) == POINTS:
                return self._remember(path, [b / 255 for b in data])
        return None

    def request(self, path, urgent=True):
        """Analyse `path` unless the waveform is already known; returns it when it is."""
        if not path:
            return None
        known = self.peaks(path)
        if known is None:
            self._worker.enqueue(path, urgent)
        return known

    def _remember(self, path, peaks):
        self._memory[path] = peaks
        self._memory.move_to_end(path)
        while len(self._memory) > MEMORY_ITEMS:
            self._memory.popitem(last=False)
        return peaks

    @Slot(str, object)
    def _on_done(self, path, peaks):
        self._remember(path, list(peaks))
        self.ready.emit(path)

    def shutdown(self):
        self._worker.stop()
