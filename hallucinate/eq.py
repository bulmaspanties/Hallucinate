"""10-band equalizer.

Qt Multimedia has no audio effects, so when the equalizer is on the decoder output is tapped with a
QAudioBufferOutput (the QMediaPlayer's own output is muted), filtered with a linear-phase FIR in numpy, and
played through a QAudioSink. The DSP part is pure numpy and independent of Qt."""
import logging

try:
    import numpy as np
except ImportError:  # the equalizer is optional
    np = None

from PySide6.QtCore import QObject, QTimer
from PySide6.QtMultimedia import QAudioBufferOutput, QAudioFormat, QAudioSink, QMediaDevices

logger = logging.getLogger(__name__)

BANDS = [31, 62, 125, 250, 500, 1000, 2000, 4000, 8000, 16000]
PRESETS = {
    "Flat": [0] * 10,
    "Bass boost": [6, 5, 4, 2, 0, 0, 0, 0, 0, 0],
    "Treble boost": [0, 0, 0, 0, 0, 1, 2, 4, 5, 6],
    "Vocal": [-2, -2, -1, 1, 3, 3, 2, 1, 0, -1],
    "Rock": [5, 4, 2, 0, -1, -1, 1, 3, 4, 5],
    "Pop": [-1, 1, 3, 4, 3, 0, -1, -1, 1, 2],
    "Jazz": [3, 2, 1, 2, -2, -2, 0, 1, 2, 3],
    "Classical": [4, 3, 3, 2, -1, -1, 0, 2, 3, 4],
    "Electronic": [5, 4, 1, 0, -2, 2, 1, 1, 4, 5],
    "Loudness": [6, 4, 0, 0, -1, 0, -1, 0, 4, 2],
}
MAX_GAIN_DB = 12.0
TAPS = 4097


def available():
    return np is not None


def design_fir(gains_db, rate, taps=TAPS):
    """Linear-phase FIR whose magnitude interpolates the band gains (log-frequency)."""
    n = 16384
    freqs = np.fft.rfftfreq(n, 1.0 / rate)
    logf = np.log10(np.maximum(freqs, 1.0))
    centers = np.log10(np.array(BANDS, dtype=float))
    gains = np.clip(np.array(gains_db, dtype=float), -MAX_GAIN_DB, MAX_GAIN_DB)
    mag_db = np.interp(logf, centers, gains)
    mag = 10 ** (mag_db / 20)
    impulse = np.fft.fftshift(np.fft.irfft(mag, n))
    mid = n // 2
    h = impulse[mid - taps // 2: mid + taps // 2 + 1] * np.hanning(taps)
    return h.astype(np.float32)


class EqProcessor:
    """Streaming overlap-save FIR filter for interleaved PCM."""

    def __init__(self):
        self.gains = [0.0] * 10
        self.rate = 44100
        self.channels = 2
        self._h = None
        self._tail = None
        self._cache = {}

    @property
    def flat(self):
        return not any(abs(g) > 0.01 for g in self.gains)

    def configure(self, rate, channels):
        if (rate, channels) != (self.rate, self.channels):
            self.rate, self.channels = rate, channels
            self._h = None
        self.reset()

    def set_gains(self, gains):
        self.gains = [float(g) for g in gains]
        self._h = None

    def reset(self):
        self._tail = None

    def _kernel(self, nfft):
        if self._h is None:
            self._h = design_fir(self.gains, self.rate)
            self._cache = {}
        spec = self._cache.get(nfft)
        if spec is None:
            spec = np.fft.rfft(self._h, nfft)
            self._cache[nfft] = spec
        return spec

    def process(self, samples):
        """samples: float32 array (frames, channels) in [-1, 1] -> filtered array of the same shape."""
        frames = samples.shape[0]
        if frames == 0:
            return samples
        overlap = TAPS - 1
        if self._tail is None or self._tail.shape[1] != samples.shape[1]:
            self._tail = np.zeros((overlap, samples.shape[1]), dtype=np.float32)
        x = np.concatenate([self._tail, samples], axis=0)
        self._tail = x[-overlap:].copy()
        nfft = 1 << int(np.ceil(np.log2(x.shape[0] + TAPS)))
        spec = self._kernel(nfft)
        y = np.fft.irfft(np.fft.rfft(x, nfft, axis=0) * spec[:, None], nfft, axis=0)
        # Output is delayed by the filter's group delay (TAPS // 2 samples), a constant ~46 ms.
        return y[overlap: overlap + frames].astype(np.float32)


_FORMATS = {
    QAudioFormat.SampleFormat.UInt8: ("u1", lambda a: (a.astype(np.float32) - 128) / 128),
    QAudioFormat.SampleFormat.Int16: ("<i2", lambda a: a.astype(np.float32) / 32768),
    QAudioFormat.SampleFormat.Int32: ("<i4", lambda a: a.astype(np.float32) / 2147483648),
    QAudioFormat.SampleFormat.Float: ("<f4", lambda a: a.astype(np.float32)),
}


class EqTap(QObject):
    """Per-voice tap: receives decoded buffers, filters them and plays them on its own QAudioSink."""

    def __init__(self, processor, parent=None):
        super().__init__(parent)
        self.output = QAudioBufferOutput(self)
        self.output.audioBufferReceived.connect(self._on_buffer)
        self.processor = processor
        self.volume = 1.0
        self.failed = False
        self._sink = None
        self._io = None
        self._fmt = None
        self._pending = bytearray()
        self._suspended = True
        self._timer = QTimer(self)
        self._timer.setInterval(10)
        self._timer.timeout.connect(self._drain)

    def _open(self, rate, channels):
        fmt = QAudioFormat()
        fmt.setSampleRate(rate)
        fmt.setChannelCount(channels)
        fmt.setSampleFormat(QAudioFormat.SampleFormat.Int16)
        device = QMediaDevices.defaultAudioOutput()
        if device.isNull() or not device.isFormatSupported(fmt):
            raise RuntimeError("no usable audio output device")
        self._close()
        self._sink = QAudioSink(device, fmt, self)
        self._sink.setBufferSize(rate * channels * 2 // 4)  # ~250 ms
        self._sink.setVolume(self.volume)
        self._io = self._sink.start()
        self._fmt = (rate, channels)
        self.processor.configure(rate, channels)
        if self._suspended:
            self._sink.suspend()
        self._timer.start()

    def _close(self):
        self._timer.stop()
        if self._sink is not None:
            self._sink.stop()
            self._sink.deleteLater()
        self._sink = self._io = None
        self._pending.clear()

    def _on_buffer(self, buf):
        fmt = buf.format()
        if not buf.isValid() or fmt.channelCount() <= 0 or self.failed:
            return
        spec = _FORMATS.get(fmt.sampleFormat())
        if spec is None:
            return
        try:
            if self._fmt != (fmt.sampleRate(), fmt.channelCount()) or self._sink is None:
                self._open(fmt.sampleRate(), fmt.channelCount())
            raw = np.frombuffer(buf.constData(), dtype=spec[0], count=buf.sampleCount())
            data = spec[1](raw).reshape(-1, fmt.channelCount())
            if not self.processor.flat:
                data = self.processor.process(data)
            out = (np.clip(data, -1.0, 1.0) * 32767).astype("<i2")
        except Exception as exc:  # noqa: BLE001
            logger.warning("Equalizer disabled: %s", exc)
            self.failed = True
            self._close()
            return
        self._pending += out.tobytes()
        self._drain()

    def _drain(self):
        if self._io is None or not self._pending:
            return
        free = self._sink.bytesFree()
        if free > 0:
            n = self._io.write(bytes(self._pending[:free]))
            if n > 0:
                del self._pending[:n]

    def setVolume(self, v):
        self.volume = v
        if self._sink is not None:
            self._sink.setVolume(v)

    def setRunning(self, running):
        self._suspended = not running
        if self._sink is None:
            return
        if running:
            self._sink.resume()
        else:
            self._sink.suspend()

    def reset(self):
        """Drop buffered audio (seek, new source)."""
        self._pending.clear()
        self.processor.reset()
        if self._sink is not None:
            self._sink.reset()
            self._io = self._sink.start()
            if self._suspended:
                self._sink.suspend()

    def close(self):
        self._close()
        self._fmt = None
