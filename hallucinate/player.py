import json
import logging
import math
import os
import random
import time
from pathlib import Path

from PySide6.QtCore import Property, QObject, QSettings, QTimer, QUrl, Signal, Slot
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer

from . import eq
from .core.tags import is_readable_audio
from .models import TRACK_KEYS, DictModel

REPEAT_OFF, REPEAT_ALL, REPEAT_ONE = 0, 1, 2
PRELOAD_MS = 10_000  # start pre-rolling the next track this long before the end
TRANSITION_MS = 250
SESSION_VERSION = 1
SESSION_MAX_TRACKS = 1000  # bounds the save cost for huge queues (e.g. "play all songs" on 50k tracks)
logger = logging.getLogger(__name__)


class _Voice:
    """A QMediaPlayer + QAudioOutput pair. Two of them alternate for near-gapless playback."""

    def __init__(self, parent):
        self.audio = QAudioOutput(parent)
        self.player = QMediaPlayer(parent)
        self.player.setAudioOutput(self.audio)
        self.index = -1  # queue index the loaded source belongs to
        self.path = ""
        self.fade = 1.0  # crossfade multiplier
        self.tap = None  # equalizer tap, present while the equalizer is on

    def clear(self):
        self.player.stop()
        self.player.setSource(QUrl())
        self.index = -1
        self.path = ""
        self.fade = 1.0
        if self.tap is not None:
            self.tap.reset()


def replaygain_factor(track, mode, preamp_db=0.0):
    """Linear gain for a track under the given ReplayGain mode ("off", "track" or "album")."""
    if mode not in ("track", "album") or not track:
        return 1.0
    keys = ("rg_album", "rg_track") if mode == "album" else ("rg_track", "rg_album")
    gain = next((track[k] for k in keys if isinstance(track.get(k), (int, float))), None)
    if gain is None:
        return 1.0
    factor = 10 ** ((gain + preamp_db) / 20)
    peak = track.get("rg_peak")
    if isinstance(peak, (int, float)) and peak > 0:
        factor = min(factor, 1.0 / peak)
    return factor


class Player(QObject):
    stateChanged = Signal()
    trackChanged = Signal()
    positionChanged = Signal()
    durationChanged = Signal()
    volumeChanged = Signal()
    shuffleChanged = Signal()
    repeatChanged = Signal()
    queueChanged = Signal()
    errorChanged = Signal()
    seeked = Signal(int)
    audioSettingsChanged = Signal()
    speedChanged = Signal()
    sleepChanged = Signal()
    eqChanged = Signal()
    played = Signal("QVariantMap")  # a track was listened to for long enough to count as a play

    def __init__(self, parent=None, session_file=None):
        super().__init__(parent)
        self._session_file = Path(session_file) if session_file else None
        self._restore_pos = 0
        self._next_pick = None
        self.gapless_swaps = 0
        self._queue = []
        self._index = -1
        self._history = []
        self._played = set()
        self._shuffle = False
        self._repeat = REPEAT_OFF
        self._error = ""
        self._error_streak = 0
        self._model = DictModel(TRACK_KEYS, self)

        self._settings = QSettings("hallucinate", "hallucinate")
        try:
            stored_volume = float(self._settings.value("volume", 0.8))
            self._volume = stored_volume if math.isfinite(stored_volume) else 0.8
        except (TypeError, ValueError):
            self._volume = 0.8
        self._rg_mode = str(self._settings.value("replaygain/mode", "off"))
        if self._rg_mode not in ("off", "track", "album"):
            self._rg_mode = "off"
        self._rg_preamp = self._float_setting("replaygain/preamp", 0.0, -15.0, 15.0)
        self._crossfade = int(self._float_setting("crossfade", 0, 0, 12))
        self._speed = self._float_setting("speed", 1.0, 0.5, 2.0)
        self._sleep_left = -1  # seconds until sleep; -1 when no timer is running
        self._sleep_after_track = False
        self._sleep_gain = 1.0
        self._sleep_timer = QTimer(self)
        self._sleep_timer.setInterval(1000)
        self._sleep_timer.timeout.connect(self._sleep_tick)
        self._eq_enabled = False
        self._eq_gains = [0.0] * len(eq.BANDS)
        self._eq_preset = "Flat"
        if eq.available():
            self._eq_enabled = str(self._settings.value("eq/enabled", "false")).lower() == "true"
            try:
                g = json.loads(str(self._settings.value("eq/gains", "[]")))
                if isinstance(g, list) and len(g) == len(eq.BANDS):
                    self._eq_gains = [min(max(float(x), -eq.MAX_GAIN_DB), eq.MAX_GAIN_DB) for x in g]
            except (ValueError, TypeError):
                pass
            self._eq_preset = self._detect_preset()
        self._fading = False
        self._fade_start = 0.0
        self._fade_ms = 0
        self._fade_timer = QTimer(self)
        self._fade_timer.setInterval(40)
        self._fade_timer.timeout.connect(self._fade_tick)
        self._voices = [_Voice(self), _Voice(self)]
        self._cur = 0
        for n, v in enumerate(self._voices):
            v.audio.setVolume(self._volume ** 2)
            p = v.player
            p.playbackStateChanged.connect(lambda *_, n=n: self._if_current(n, self.stateChanged))
            p.positionChanged.connect(lambda *_, n=n: self._on_position(n))
            p.durationChanged.connect(lambda *_, n=n: self._on_duration(n))
            p.mediaStatusChanged.connect(lambda st, n=n: self._on_media_status(n, st))
            p.errorOccurred.connect(lambda err, msg, n=n: self._on_error(n, msg))
            p.playbackStateChanged.connect(lambda st, n=n: self._tap_state(n, st))
        self._apply_speed()
        if self._eq_enabled:
            self._sync_taps()

        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(1000)
        self._save_timer.timeout.connect(self.saveSession)
        self.queueChanged.connect(self._save_timer.start)
        self.trackChanged.connect(self._save_timer.start)
        self.shuffleChanged.connect(self._save_timer.start)
        self.repeatChanged.connect(self._save_timer.start)
        self._last_saved_pos = 0
        self._listened = 0
        self._last_pos = 0
        self._play_counted = False
        self._transitioning = False
        self._ended = False

    def _float_setting(self, key, default, lo, hi):
        try:
            v = float(self._settings.value(key, default))
        except (TypeError, ValueError):
            return default
        return min(max(v, lo), hi) if math.isfinite(v) else default

    # --- ReplayGain / crossfade settings ----------------------------------
    @Property(str, notify=audioSettingsChanged)
    def replayGainMode(self):
        return self._rg_mode

    @Property(float, notify=audioSettingsChanged)
    def replayGainPreamp(self):
        return self._rg_preamp

    @Property(int, notify=audioSettingsChanged)
    def crossfade(self):
        return self._crossfade

    @Slot(str)
    def setReplayGainMode(self, mode):
        if mode in ("off", "track", "album") and mode != self._rg_mode:
            self._rg_mode = mode
            self._settings.setValue("replaygain/mode", mode)
            self._apply_volume()
            self.audioSettingsChanged.emit()

    @Slot(float)
    def setReplayGainPreamp(self, db):
        db = min(max(float(db), -15.0), 15.0)
        if db != self._rg_preamp:
            self._rg_preamp = db
            self._settings.setValue("replaygain/preamp", db)
            self._apply_volume()
            self.audioSettingsChanged.emit()

    @Slot(int)
    def setCrossfade(self, seconds):
        seconds = min(max(int(seconds), 0), 12)
        if seconds != self._crossfade:
            self._crossfade = seconds
            self._settings.setValue("crossfade", seconds)
            self.audioSettingsChanged.emit()

    # --- playback speed and sleep timer -----------------------------------------
    @Property(float, notify=speedChanged)
    def speed(self):
        return self._speed

    @Slot(float)
    def setSpeed(self, rate):
        rate = round(min(max(float(rate), 0.5), 2.0), 2)
        if rate != self._speed:
            self._speed = rate
            self._settings.setValue("speed", rate)
            self._apply_speed()
            self.speedChanged.emit()

    def _apply_speed(self):
        for v in self._voices:
            v.player.setPlaybackRate(self._speed)

    @Property(int, notify=sleepChanged)
    def sleepRemaining(self):
        return self._sleep_left

    @Property(bool, notify=sleepChanged)
    def sleepAfterTrack(self):
        return self._sleep_after_track

    @Slot(int)
    def setSleepMinutes(self, minutes):
        """Pause after `minutes` (fading out over the last 15 s); 0 cancels the timer."""
        self._sleep_after_track = False
        self._sleep_gain = 1.0
        self._apply_volume()
        if minutes > 0:
            self._sleep_left = minutes * 60
            self._sleep_timer.start()
        else:
            self._sleep_left = -1
            self._sleep_timer.stop()
        self.sleepChanged.emit()

    @Slot(bool)
    def setSleepAfterTrack(self, on):
        self._sleep_timer.stop()
        self._sleep_left = -1
        self._sleep_gain = 1.0
        self._apply_volume()
        self._sleep_after_track = on
        self.sleepChanged.emit()

    def _sleep_tick(self):
        self._sleep_left -= 1
        if self._sleep_left <= 0:
            self._sleep_timer.stop()
            self._sleep_left = -1
            self.pause()
            self._sleep_gain = 1.0
            self._apply_volume()
        else:
            self._sleep_gain = min(1.0, self._sleep_left / 15)
            self._apply_volume()
        self.sleepChanged.emit()

    # --- equalizer -----------------------------------------------------------
    def _detect_preset(self):
        for name, gains in eq.PRESETS.items():
            if all(abs(a - b) < 0.05 for a, b in zip(self._eq_gains, gains)):
                return name
        return "Custom"

    @Property(bool, constant=True)
    def eqAvailable(self):
        return eq.available()

    @Property(bool, notify=eqChanged)
    def eqEnabled(self):
        return self._eq_enabled

    @Property("QVariantList", notify=eqChanged)
    def eqGains(self):
        return list(self._eq_gains)

    @Property(str, notify=eqChanged)
    def eqPreset(self):
        return self._eq_preset

    @Property("QVariantList", constant=True)
    def eqPresets(self):
        return list(eq.PRESETS)

    @Property("QVariantList", constant=True)
    def eqBands(self):
        return [f"{b // 1000}k" if b >= 1000 else str(b) for b in eq.BANDS]

    def _save_eq(self):
        self._settings.setValue("eq/enabled", "true" if self._eq_enabled else "false")
        self._settings.setValue("eq/gains", json.dumps(self._eq_gains))
        self._eq_preset = self._detect_preset()
        for voice in self._voices:
            if voice.tap is not None:
                voice.tap.processor.set_gains(self._eq_gains)
        self.eqChanged.emit()

    @Slot(bool)
    def setEqEnabled(self, on):
        if on and not eq.available():
            return
        if on != self._eq_enabled:
            self._eq_enabled = on
            self._sync_taps()
            self._save_eq()

    @Slot(int, float)
    def setEqBand(self, band, db):
        if 0 <= band < len(self._eq_gains):
            self._eq_gains[band] = min(max(float(db), -eq.MAX_GAIN_DB), eq.MAX_GAIN_DB)
            self._save_eq()

    @Slot(str)
    def setEqPreset(self, name):
        if name in eq.PRESETS:
            self._eq_gains = [float(g) for g in eq.PRESETS[name]]
            self._save_eq()

    def _sync_taps(self):
        for voice in self._voices:
            if self._eq_enabled and voice.tap is None:
                tap = eq.EqTap(eq.EqProcessor(), self)
                tap.processor.set_gains(self._eq_gains)
                voice.tap = tap
                voice.player.setAudioBufferOutput(tap.output)
                tap.setRunning(voice.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState)
            elif not self._eq_enabled and voice.tap is not None:
                voice.player.setAudioBufferOutput(None)
                voice.tap.close()
                voice.tap.deleteLater()
                voice.tap = None
        self._apply_volume()

    def _tap_state(self, n, state):
        tap = self._voices[n].tap
        if tap is None:
            return
        running = state == QMediaPlayer.PlaybackState.PlayingState
        if running or n == self._cur:  # a swapped-out voice keeps draining its sink for gapless playback
            tap.setRunning(running)

    def _voice_track(self, voice):
        return self._queue[voice.index] if 0 <= voice.index < len(self._queue) else None

    def _apply_volume(self):
        for voice in self._voices:
            gain = replaygain_factor(self._voice_track(voice), self._rg_mode, self._rg_preamp)
            level = min(1.0, self._volume ** 2 * gain * voice.fade * self._sleep_gain)
            if voice.tap is not None:
                voice.audio.setVolume(0.0)  # still paces the decoder; the tap's sink plays the sound
                voice.tap.setVolume(level)
            else:
                voice.audio.setVolume(level)

    def _start_fade(self, ms):
        self._fading = True
        self._fade_ms = max(ms, 1)
        self._fade_start = time.monotonic()
        self._voice.fade = 0.0
        self._standby.fade = 1.0
        self._fade_timer.start()
        self._apply_volume()

    def _fade_tick(self):
        t = min(1.0, (time.monotonic() - self._fade_start) * 1000 / self._fade_ms)
        self._voice.fade = t
        self._standby.fade = 1.0 - t
        self._apply_volume()
        if t >= 1.0:
            self._end_fade()

    def _end_fade(self):
        if not self._fading:
            return
        self._fading = False
        self._fade_timer.stop()
        old = self._standby
        old.player.pause()
        old.fade = self._voice.fade = 1.0
        self._apply_volume()

    # --- helpers -----------------------------------------------------------
    @property
    def _voice(self):
        return self._voices[self._cur]

    @property
    def _player(self):
        return self._voices[self._cur].player

    @property
    def _standby(self):
        return self._voices[1 - self._cur]

    def _if_current(self, n, signal):
        if n == self._cur:
            signal.emit()

    # --- properties --------------------------------------------------------
    @Property(bool, notify=stateChanged)
    def playing(self):
        return not self._ended and self._player.playbackState() == QMediaPlayer.PlaybackState.PlayingState

    @Property(str, notify=stateChanged)
    def state(self):
        if self._ended:
            return "Stopped"
        return {
            QMediaPlayer.PlaybackState.PlayingState: "Playing",
            QMediaPlayer.PlaybackState.PausedState: "Paused",
        }.get(self._player.playbackState(), "Stopped")

    @Property(bool, notify=trackChanged)
    def hasTrack(self):
        return 0 <= self._index < len(self._queue)

    @Property("QVariantMap", notify=trackChanged)
    def current(self):
        return self._queue[self._index] if self.hasTrack else {}

    @Property(int, notify=trackChanged)
    def currentIndex(self):
        return self._index

    @Property(int, notify=positionChanged)
    def position(self):
        return self._player.position()

    @Property(int, notify=durationChanged)
    def duration(self):
        d = self._player.duration()
        if d <= 0 and self.hasTrack:
            d = int(self._queue[self._index].get("duration", 0) * 1000)
        return max(d, 0)

    @Property(float, notify=volumeChanged)
    def volume(self):
        return self._volume

    @Property(bool, notify=shuffleChanged)
    def shuffle(self):
        return self._shuffle

    @Property(int, notify=repeatChanged)
    def repeat(self):
        return self._repeat

    @Property(QObject, constant=True)
    def queueModel(self):
        return self._model

    @Property(str, notify=errorChanged)
    def error(self):
        return self._error

    @Property(int, notify=queueChanged)
    def queueLength(self):
        return len(self._queue)

    @Property(bool, notify=queueChanged)
    def canGoNext(self):
        return bool(self._queue)

    @Property(bool, notify=queueChanged)
    def canGoPrevious(self):
        return bool(self._queue)

    @Property(bool, notify=queueChanged)
    def canPlay(self):
        return bool(self._queue)

    @Property(bool, notify=trackChanged)
    def canPause(self):
        return self.hasTrack

    @Property(bool, notify=trackChanged)
    def canSeek(self):
        return self.hasTrack and self.duration > 0

    @property
    def queue(self):
        return list(self._queue)

    # --- transport ---------------------------------------------------------
    @Slot()
    def play(self):
        if self.hasTrack:
            if self._ended or self._player.mediaStatus() == QMediaPlayer.MediaStatus.EndOfMedia:
                if self._voice.tap is not None:
                    self._voice.tap.reset()
                self._player.setPosition(0)
            self._ended = False
            self._player.play()
        elif self._queue:
            self._load(0)

    @Slot()
    def pause(self):
        self._ended = False
        self._end_fade()
        self._player.pause()
        self.stateChanged.emit()
        self.saveSession()

    @Slot()
    def stop(self):
        self._ended = False
        self._end_fade()
        self._player.stop()
        self.stateChanged.emit()
        self.saveSession()

    @Slot()
    def toggle(self):
        if self.playing:
            self.pause()
        else:
            self.play()

    @Slot(int)
    def seek(self, ms):
        dur = self.duration
        ms = max(0, int(ms))
        if dur > 0:
            ms = min(ms, max(dur - TRANSITION_MS, 0))
        if self._restore_pos:
            self._restore_pos = 0
        if self._ended:
            self._ended = False
            self.stateChanged.emit()
        if self._voice.tap is not None:
            self._voice.tap.reset()
        self._player.setPosition(ms)
        self.seeked.emit(ms)

    @Slot(int)
    def seekBy(self, delta_ms):
        self.seek(min(self._player.position() + delta_ms, max(self.duration - 1, 0)))

    @Slot(float)
    def setVolume(self, v):
        v = float(v)
        v = min(max(v, 0.0), 1.0) if math.isfinite(v) else 0.0
        self._volume = v
        self._apply_volume()
        self._settings.setValue("volume", v)
        self.volumeChanged.emit()

    @Slot(float)
    def changeVolume(self, delta):
        self.setVolume(self._volume + delta)

    @Slot()
    def toggleShuffle(self):
        self.setShuffle(not self._shuffle)

    @Slot(bool)
    def setShuffle(self, on):
        self._shuffle = bool(on)
        self._played = {self._index} if self.hasTrack else set()
        self._invalidate_next()
        self.shuffleChanged.emit()

    @Slot()
    def cycleRepeat(self):
        self.setRepeat((self._repeat + 1) % 3)

    @Slot(int)
    def setRepeat(self, mode):
        self._repeat = mode if mode in (REPEAT_OFF, REPEAT_ALL, REPEAT_ONE) else REPEAT_OFF
        self._invalidate_next()
        self.repeatChanged.emit()

    @Slot()
    def next(self):
        nxt = self._compute_next(auto=False)
        if nxt is not None:
            self._load(nxt)

    @Slot()
    def previous(self):
        if self._player.position() > 3000 or not self.hasTrack:
            self.seek(0)
        elif self._history:
            self._load(self._history.pop(), record=False)
        elif self._index > 0 and not self._shuffle:
            self._load(self._index - 1, record=False)
        else:
            self.seek(0)

    # --- queue -------------------------------------------------------------
    @Slot("QVariantList", int)
    def playList(self, tracks, index=0):
        """Replace the queue with `tracks` and start playing at `index`."""
        self._queue = list(tracks)  # queue entries are treated as immutable
        self._history.clear()
        self._played.clear()
        self._standby.clear()
        self._sync_queue()
        if self._queue:
            self._load(min(max(index, 0), len(self._queue) - 1), record=False)
        else:
            self._reset_empty()

    @Slot("QVariantMap")
    def playTrack(self, track):
        self.playList([track], 0)

    @Slot("QVariantMap")
    def enqueue(self, track):
        self.enqueueAll([track])

    @Slot("QVariantMap")
    def playNext(self, track):
        self._queue.insert(self._index + 1, dict(track))
        self._shift_indexes_after(self._index + 1, +1)
        self._sync_queue()
        if not self.hasTrack:
            self._load(0, autoplay=False)

    @Slot("QVariantList")
    def enqueueAll(self, tracks):
        for t in tracks:
            self._queue.append(dict(t))
        self._sync_queue()
        if not self.hasTrack and self._queue:
            self._load(0, autoplay=False)

    @Slot(int)
    def playIndex(self, i):
        if 0 <= i < len(self._queue):
            self._load(i)

    @Slot(int)
    def removeAt(self, i):
        if not 0 <= i < len(self._queue):
            return
        del self._queue[i]
        self._history = [h - (h > i) for h in self._history if h != i]
        self._played = {p - (p > i) for p in self._played if p != i}
        self._standby.clear()
        if i == self._index:
            was_playing = self.playing
            self._player.stop()
            if self._queue:
                self._load(min(i, len(self._queue) - 1), autoplay=was_playing, record=False)
            else:
                self._reset_empty()
        elif i < self._index:
            self._index -= 1
            self._voice.index = self._index
            self.trackChanged.emit()
        self._invalidate_next()
        self._sync_queue()

    @Slot(int, int)
    def moveItem(self, src, dst):
        n = len(self._queue)
        if not (0 <= src < n and 0 <= dst < n) or src == dst:
            return
        item = self._queue.pop(src)
        self._queue.insert(dst, item)

        def remap(k):
            if k == src:
                return dst
            if src < dst and src < k <= dst:
                return k - 1
            if dst < src and dst <= k < src:
                return k + 1
            return k

        self._index = remap(self._index)
        self._voice.index = self._index
        self._history = [remap(h) for h in self._history]
        self._played = {remap(p) for p in self._played}
        self._standby.clear()
        self._invalidate_next()
        self._sync_queue()
        self.trackChanged.emit()

    @Slot()
    def clearQueue(self):
        self._queue.clear()
        self._history.clear()
        self._played.clear()
        self._standby.clear()
        self._sync_queue()
        self._reset_empty()

    # --- internals ---------------------------------------------------------
    def _reset_empty(self):
        self._voice.clear()
        self._index = -1
        self._invalidate_next()
        self.trackChanged.emit()
        self.durationChanged.emit()
        self.positionChanged.emit()

    def _shift_indexes_after(self, at, delta):
        self._history = [h + delta if h >= at else h for h in self._history]
        self._played = {p + delta if p >= at else p for p in self._played}
        self._standby.clear()
        self._invalidate_next()

    def _sync_queue(self):
        self._model.set_items(self._queue)
        self._standby_check()
        self.queueChanged.emit()

    def _standby_check(self):
        sb = self._standby
        if sb.index >= len(self._queue) or (sb.index >= 0 and sb.path != self._queue[sb.index]["path"]):
            sb.clear()

    def _invalidate_next(self):
        self._next_pick = None

    def _compute_next(self, auto):
        """Index of the track that follows the current one, or None to stop."""
        n = len(self._queue)
        if n == 0:
            return None
        if auto and self._repeat == REPEAT_ONE:
            return self._index
        if self._shuffle:
            if self._next_pick is not None and self._next_pick < n:
                return self._next_pick
            choices = [i for i in range(n) if i not in self._played]
            if not choices:
                if self._repeat == REPEAT_OFF and auto:
                    return None
                choices = [i for i in range(n) if i != self._index] or [self._index]
            self._next_pick = random.choice(choices)
            return self._next_pick
        nxt = self._index + 1
        if nxt >= n:
            return None if (self._repeat == REPEAT_OFF and auto) else 0
        return nxt

    def _load(self, i, autoplay=True, record=True, fade_ms=0, drain=False):
        if not 0 <= i < len(self._queue):
            return
        if record and self.hasTrack and i != self._index:
            self._history.append(self._index)
            del self._history[:-200]
        path = self._queue[i].get("path", "")
        exists = isinstance(path, str) and os.path.isfile(path)
        if not exists or not is_readable_audio(path):
            self._index = i
            reason = "File not found" if not exists else "Unreadable audio file"
            self._set_error(f"{reason}: {path}")
            candidates = list(range(i + 1, len(self._queue)))
            if self._shuffle:
                candidates = [j for j in range(len(self._queue)) if j != i and j not in self._played]
                random.shuffle(candidates)
            elif self._repeat == REPEAT_ALL:
                candidates += list(range(0, i))
            for candidate in candidates:
                candidate_path = self._queue[candidate].get("path", "")
                if isinstance(candidate_path, str) and os.path.isfile(candidate_path) and is_readable_audio(candidate_path):
                    self._load(candidate, autoplay=autoplay, record=False)
                    return
            self._reset_empty()
            return
        self._end_fade()
        self._index = i
        if self._shuffle and len(self._played) >= len(self._queue):
            self._played.clear()
        self._played.add(i)
        self._invalidate_next()
        self._set_error("")
        self._restore_pos = 0
        self._transitioning = False
        self._ended = False
        self._listened = 0
        self._last_pos = 0
        self._play_counted = False

        sb = self._standby
        if autoplay and sb.index == i and sb.path == path and sb.player.source().isValid():
            # Pause before end-of-stream; Qt's FFmpeg backend can stall on EndOfMedia.
            if not fade_ms:
                self._voice.player.pause()
                if self._voice.tap is not None and not drain:
                    self._voice.tap.reset()
            self._cur = 1 - self._cur
            if self._voice.tap is not None:
                self._voice.tap.reset()
            self._player.setPosition(0)
            self.gapless_swaps += 1
            if fade_ms:
                self._start_fade(fade_ms)
            self._player.play()
        else:
            self._voice.index, self._voice.path = i, path
            if self._voice.tap is not None:
                self._voice.tap.reset()
            self._player.setSource(QUrl.fromLocalFile(path))
            self._player.setPlaybackRate(self._speed)
            if autoplay:
                self._player.play()
            if sb.index not in (-1, i):
                sb.clear()
        self._apply_volume()
        self.trackChanged.emit()
        self.stateChanged.emit()
        self.durationChanged.emit()
        self.positionChanged.emit()

    def _maybe_preload(self):
        if not self.hasTrack or not self.playing or self._fading:
            return
        dur = self._player.duration()
        if dur <= 0 or dur - self._player.position() > PRELOAD_MS + self._crossfade * 1000:
            return
        nxt = self._compute_next(auto=True)
        sb = self._standby
        if nxt is None:
            return
        path = self._queue[nxt]["path"]
        if sb.index == nxt and sb.path == path:
            return
        sb.player.pause()
        sb.index, sb.path = nxt, path
        if sb.tap is not None:
            sb.tap.reset()
        sb.player.setSource(QUrl.fromLocalFile(path))
        sb.player.pause()  # prepare the decoder without taking the audio device
        self._apply_volume()

    def _on_position(self, n):
        if n != self._cur:
            return
        self.positionChanged.emit()
        self._maybe_preload()
        pos = self._player.position()
        dur = self._player.duration()
        self._count_listening(pos, dur)
        if self._try_crossfade(pos, dur):
            return
        if (not self._transitioning and self.playing and dur > 0 and
                dur - pos <= TRANSITION_MS):
            self._transitioning = True
            QTimer.singleShot(0, self._advance_before_end)
        if self.playing and abs(pos - self._last_saved_pos) > 5000:
            self._last_saved_pos = pos
            self.saveSession()

    def _try_crossfade(self, pos, dur):
        xf = self._crossfade * 1000
        if (not xf or self._fading or self._transitioning or not self.playing or self._repeat == REPEAT_ONE
                or self._sleep_after_track):
            return False
        if dur < 2 * xf or dur - pos > xf:
            return False
        nxt = self._compute_next(auto=True)
        sb = self._standby
        if nxt is None or nxt == self._index or sb.index != nxt or not sb.player.source().isValid():
            return False
        self._load(nxt, fade_ms=dur - pos)
        return True

    def _count_listening(self, pos, dur):
        """Count real listening time (ignoring seeks) and emit `played` once per loaded track."""
        step = pos - self._last_pos
        self._last_pos = pos
        if self._play_counted or not self.playing or not 0 < step < 2000:
            return
        self._listened += step
        if self._listened >= min(30_000, max(dur, 1) / 2) and self.hasTrack:
            self._play_counted = True
            self.played.emit(dict(self.current))

    def _advance_before_end(self):
        if not self.hasTrack or not self._transitioning:
            return
        if not self.playing:
            self._transitioning = False
            return
        if self._player.duration() - self._player.position() > TRANSITION_MS:
            self._transitioning = False
            return
        nxt = self._compute_next(auto=True)
        if self._sleep_after_track:
            self._sleep_after_track = False
            self.sleepChanged.emit()
            if nxt is not None:
                self._player.pause()
                self._load(nxt, autoplay=False)
            else:
                self._ended = True
                self._player.pause()
                self.stateChanged.emit()
            self.saveSession()
        elif nxt is not None:
            self._load(nxt, drain=True)
        else:
            self._ended = True
            self._player.pause()
            self.stateChanged.emit()
            self.saveSession()
        self._transitioning = False

    def _on_duration(self, n):
        if n == self._cur:
            self.durationChanged.emit()
            self._maybe_preload()

    def _on_media_status(self, n, status):
        S = QMediaPlayer.MediaStatus
        if n != self._cur:
            return
        if status in (S.LoadedMedia, S.BufferedMedia):
            if status == S.BufferedMedia:
                self._error_streak = 0
                self._set_error("")
            if self._restore_pos:
                pos, self._restore_pos = self._restore_pos, 0
                self._player.setPosition(pos)
                self.positionChanged.emit()

    def _on_error(self, n, message):
        if n != self._cur:
            sb = self._voices[n]
            sb.clear()  # a failed pre-roll just falls back to a normal load later
            return
        self._set_error(message or "Playback error")
        self._error_streak += 1
        if self._error_streak < len(self._queue):
            QTimer.singleShot(300, self._skip_after_error)

    def _skip_after_error(self):
        if not self._error:
            return  # a newer load already cleared the failed track's error
        nxt = self._compute_next(auto=True)
        if nxt is not None and nxt != self._index:
            self._load(nxt)

    def _set_error(self, text):
        if text != self._error:
            self._error = text
            self.errorChanged.emit()

    def shutdown(self):
        self._fade_timer.stop()
        self.saveSession()
        for v in self._voices:
            v.clear()

    # --- session persistence ----------------------------------------------
    @Slot()
    def saveSession(self):
        if not self._session_file:
            return
        queue, index = self._queue, self._index
        if len(queue) > SESSION_MAX_TRACKS:
            start = max(0, min(index, len(queue) - 1) - SESSION_MAX_TRACKS // 5)
            queue = queue[start:start + SESSION_MAX_TRACKS]
            index = index - start if index >= 0 else index
        data = {
            "version": SESSION_VERSION,
            "queue": queue,
            "index": index,
            "position": self._player.position() if self.hasTrack else 0,
            "shuffle": self._shuffle,
            "repeat": self._repeat,
        }
        try:
            tmp = self._session_file.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, self._session_file)
        except (OSError, TypeError, ValueError) as exc:
            logger.warning("Could not save playback session to %s: %s", self._session_file, exc)

    @Slot()
    def restoreSession(self):
        """Bring back the previous queue, position and modes (paused). Missing files are dropped."""
        if not self._session_file or self.hasTrack:
            return False
        try:
            data = json.loads(self._session_file.read_text(encoding="utf-8"))
            if not isinstance(data, dict) or data.get("version") != SESSION_VERSION:
                return False
            queue = [
                t for t in data["queue"]
                if isinstance(t, dict) and isinstance(t.get("path"), str) and os.path.isfile(t["path"])
            ]
            index = int(data.get("index", -1))
            pos = int(data.get("position", 0))
            shuffle, repeat = bool(data.get("shuffle")), int(data.get("repeat", 0))
        except (OSError, ValueError, KeyError, TypeError) as exc:
            logger.warning("Could not restore playback session from %s: %s", self._session_file, exc)
            return False
        if not queue:
            return False
        old = data["queue"]
        if 0 <= index < len(old):
            keep = [i for i, t in enumerate(old) if isinstance(t, dict) and os.path.isfile(t.get("path", ""))]
            index = keep.index(index) if index in keep else min(sum(1 for i in keep if i < index), len(queue) - 1)
        else:
            index, pos = 0, 0
        self._queue = queue
        self._shuffle = shuffle
        self._repeat = repeat if repeat in (0, 1, 2) else 0
        self._sync_queue()
        self.shuffleChanged.emit()
        self.repeatChanged.emit()
        self._load(index, autoplay=False, record=False)
        self._restore_pos = max(pos, 0)
        return True
