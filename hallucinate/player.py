import json
import logging
import math
import os
import random
import time
import weakref
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PySide6.QtCore import Property, QCoreApplication, QEvent, QObject, QSettings, Qt, QTimer, QUrl, Signal, Slot
from PySide6.QtMultimedia import (
    QAudioBufferOutput,
    QAudioDevice,
    QAudioFormat,
    QAudioOutput,
    QMediaDevices,
    QMediaPlayer,
)
from PySide6.QtQml import QQmlComponent, QQmlEngine

from . import eq, fileready, signalpath
from .core import net, remote
from .core.kinds import counts_for_scrobbling, is_url, track_kind  # noqa: F401 - re-exported
from .core.tags import is_readable_audio
from .models import TRACK_KEYS, DictModel

REPEAT_OFF, REPEAT_ALL, REPEAT_ONE = 0, 1, 2
PRELOAD_MS = 10_000  # start pre-rolling the next track this long before the end
TRANSITION_MS = 250  # seeks stop this far before the end, so the next track still gets started
HANDOFF_WINDOW_MS = 400  # positions arrive every ~100 ms; within this window the exact handoff is scheduled
HANDOFF_LEAD_MS = 20  # start the next track this early to cover its startup (~16 ms measured on Qt 6.11)
FINISH_GRACE_MS = 1000
UNDO_STEPS = 20  # queue changes that can be undone
SKIP_MIN_MS = 1500  # moving on sooner than this is browsing the queue, not a skip
RADIO_LOW_WATER = 2  # ask for more radio tracks once fewer than this many are left to play
RADIO_SEEDS = 5  # recently played tracks the next radio batch is based on  # stop a track left to finish this long after its expected end, in case it stalls
STREAM_SONG_MS = 60_000  # a song heard this long on internet radio counts for scrobbling
STREAM_QUIET_MS = 15_000  # a station "playing" whose position hasn't moved this long has gone silent
STREAM_RETRIES = 5  # reconnect a dropped station this many times (2, 4, 8… s apart) before giving up
SESSION_VERSION = 1
SESSION_MAX_TRACKS = 1000  # bounds the save cost for huge queues (e.g. "play all songs" on 50k tracks)
VISUALIZER_BARS = 24
logger = logging.getLogger(__name__)


_audio_output_engine = None
_audio_output_component = None


def _new_audio_output(parent):
    """Create a QAudioOutput on the C++ side rather than as a Python wrapper.

    Qt's FFmpeg backend connects its audio renderer, which lives on its own thread, to the output's signals.
    Destroying the renderer calls disconnectNotify() on the output while holding Qt's signal-slot lock; for a
    Python-created output PySide then waits for the GIL. If the GUI thread holds the GIL and is waiting for
    the same lock (e.g. setSource() right after a seek), the app deadlocks. A C++-created output has no Python
    overrides, so disconnectNotify() never needs the GIL. Falls back to a Python-created output if the
    QtMultimedia QML module is unavailable."""
    global _audio_output_engine, _audio_output_component
    if _audio_output_component is None:
        _audio_output_engine = QQmlEngine(QCoreApplication.instance())
        _audio_output_component = QQmlComponent(_audio_output_engine)
        _audio_output_component.setData(b"import QtMultimedia\nAudioOutput {}", QUrl())
    audio = _audio_output_component.create()
    if not isinstance(audio, QAudioOutput):
        logger.warning("QtMultimedia QML module unavailable (%s); using a Python audio output",
                       _audio_output_component.errorString().strip())
        return QAudioOutput(parent)
    QQmlEngine.setObjectOwnership(audio, QQmlEngine.ObjectOwnership.CppOwnership)
    audio.setParent(parent)
    return audio


def device_key(device):
    """Stable string id for a QAudioDevice, suitable for QSettings and QML."""
    return bytes(device.id()).hex()


def pick_output_device(devices, key):
    """The device in `devices` whose key is `key`, or None to use the system default."""
    if key:
        for device in devices:
            if device_key(device) == key:
                return device
    return None


RESOLVE_FRESH_S = 10  # a host name looked up this recently is taken as answering (FFmpeg looks it up again)
RESOLVE_TIMEOUT_MS = 15_000  # a lookup that hasn't answered by then counts as failed
FILE_WAIT_S = 0.25  # a song file that hasn't answered by then is waited for in the background
FILE_TIMEOUT_MS = 15_000
_resolved_hosts = {}  # host -> when it last resolved


def _net_host(path):
    """The host a network source would connect to, if its name needs looking up first ("" otherwise: a local
    file, or an address given as numbers)."""
    import ipaddress
    import urllib.parse

    if is_url(path):
        name = urllib.parse.urlsplit(path).hostname or ""
    elif remote.is_remote(path):
        name = remote.host(path)
    else:
        return ""
    try:
        ipaddress.ip_address(name)
        return ""
    except ValueError:
        return name


def _host_ready(name):
    return not name or time.monotonic() - _resolved_hosts.get(name, -1e9) < RESOLVE_FRESH_S


def _resolve(name):
    """Look a host name up (on a worker thread). Qt's player looks it up again itself, on the window's thread
    for a stream it's switching away from, and that lookup can't be interrupted: so a stream is only handed
    over once its name has just answered, and a server that can't be found says so instead of freezing."""
    import socket

    try:
        socket.getaddrinfo(name, None)
    except (OSError, UnicodeError):
        return False
    _resolved_hosts[name] = time.monotonic()
    return True


def _is_network(path):
    return is_url(path) or remote.is_remote(path)


def _resolve_in_background(name, done=None):
    """Look `name` up on a thread of its own (a stuck lookup holds nothing else up, nor the app closing), and
    call done(ok) from that thread."""
    import threading

    def run():
        ok = _resolve(name)
        if done is not None:
            done(ok)

    threading.Thread(target=run, name="resolve", daemon=True).start()


# Players set aside while they were still opening a stream or file (see _Voice._set_aside_if_loading): stopping or
# switching one then makes the window wait for the lookup or slow disk inside it, so it's left to finish and
# deleted after.
_set_aside = []


def _reap_set_aside():
    for item in list(_set_aside):
        player = item[0]
        try:
            loading = player.mediaStatus() == QMediaPlayer.MediaStatus.LoadingMedia
        except RuntimeError:  # already gone
            _set_aside.remove(item)
            continue
        if not loading:
            _set_aside.remove(item)
            for obj in item:
                if obj is not None:
                    obj.deleteLater()


def still_opening():
    """Whether a set-aside player is still opening its source (quitting would then wait on it)."""
    _reap_set_aside()
    return bool(_set_aside)


def _playable(path):
    """Whether a queue entry's audio can be opened now: a stream, a server song whose server can be reached,
    or a readable audio file."""
    if is_url(path):
        return True
    if remote.is_remote(path):
        return remote.available(path)
    return isinstance(path, str) and os.path.isfile(path) and is_readable_audio(path)


def track_file(track):
    """The audio file a queue entry plays: its own path, or for a CUE sheet song the album's file."""
    return track.get("file") or track.get("path", "")


def track_window(track):
    """(start, end) of a queue entry in its file, in ms; end 0 means the end of the file."""
    if not track.get("file"):
        return 0, 0
    return int(round((track.get("cue_start") or 0) * 1000)), int(round((track.get("cue_end") or 0) * 1000))


class _Voice:
    """A QMediaPlayer + QAudioOutput pair. Two of them alternate for near-gapless playback.

    A voice can play just a stretch of its file (a CUE sheet song): positions and durations it reports are
    then relative to `start`, and `end` (0: the end of the file) is where the song stops."""

    def __init__(self, parent):
        import weakref

        self._parent = weakref.ref(parent)  # not a strong reference: the Player owns its voices
        self.audio = _new_audio_output(parent)
        self.player = QMediaPlayer(parent)
        self.player.setAudioOutput(self.audio)
        self.on_new_player = None  # set by the Player: wires a replacement player up like the first
        self.visual_output = None
        self.index = -1  # queue index the loaded source belongs to
        self.path = ""  # the file loaded
        self.start = 0  # the song's stretch of the file, in ms (see track_window)
        self.end = 0
        self.seek_on_load = -1  # where to go once the file is loaded (a CUE song not at the start)
        self.play_on_load = False
        self.fade = 1.0  # crossfade multiplier
        self.tap = None  # equalizer tap, present while the equalizer is on
        self.tap_visual_connected = False
        self.finishing = False  # still playing its last moments after the next track took over
        self.finish_by = 0.0

    def _set_aside_if_loading(self):
        """A player still opening its source can't be stopped or pointed elsewhere without the window waiting
        on it (FFmpeg's address lookup, or a file on a disk waking up, can't be interrupted): leave it to
        finish on its own, and carry on with a new one. True when it did."""
        try:
            loading = self.player.mediaStatus() == QMediaPlayer.MediaStatus.LoadingMedia
        except RuntimeError:
            return False
        if not loading:
            return False
        old = (self.player, self.audio, self.tap, self.visual_output)
        self.player.blockSignals(True)
        if self.tap is not None:
            self.tap.close()
        _set_aside.append(old)
        parent = self._parent()
        self.audio = _new_audio_output(parent)
        self.player = QMediaPlayer(parent)
        self.player.setAudioOutput(self.audio)
        self.tap = None
        self.tap_visual_connected = False
        self.visual_output = None
        if self.on_new_player is not None:
            self.on_new_player(self)
        return True

    def clear(self):
        self.finishing = False
        if not self._set_aside_if_loading():
            self.player.stop()
            self.player.setSource(QUrl())
        self.index = -1
        self.path = ""
        self.start = self.end = 0
        self.seek_on_load = -1
        self.play_on_load = False
        self.fade = 1.0
        if self.tap is not None:
            self.tap.reset()

    def load(self, index, track):
        """Point this voice at a queue entry: its file and, for a CUE song, its stretch of it."""
        self._set_aside_if_loading()  # still opening a stream: don't wait for it, use a new player
        self.index, self.path = index, track_file(track)
        self.start, self.end = track_window(track)
        resume = int(track.get("resume_ms") or 0)  # a podcast episode picks up where it was left
        if track_kind(track) == "music":
            track.pop("resume_ms", None)  # a song's (a parked stream's) is used once
        self.seek_on_load = self.start + resume if self.start or resume else -1
        if self.tap is not None:
            self.tap.reset()
        if remote.is_remote(self.path):  # a song on a music server: its stream link, made now, login and all
            url = QUrl(remote.stream_url(self.path))
        else:
            url = QUrl(self.path) if is_url(self.path) else QUrl.fromLocalFile(self.path)
        if (self.seek_on_load >= 0 or is_url(self.path)) and self.player.source() == url:
            # the same file again: reload it, so it reports loaded and seeks; the same stream again (a
            # reconnect): drop the old connection, which Qt would otherwise keep
            self.player.setSource(QUrl())
        self.player.setSource(url)

    def holds(self, index, track):
        return self.index == index and self.path == track_file(track) and (self.start, self.end) == track_window(track)

    def position(self):
        return max(0, self.player.position() - self.start)

    def duration(self):
        end = self.end or self.player.duration()
        return max(0, end - self.start) if end > 0 else 0

    def set_position(self, ms):
        self.player.setPosition(self.start + max(0, int(ms)))


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
    undoChanged = Signal()
    errorChanged = Signal()
    seeked = Signal(int)
    audioSettingsChanged = Signal()
    speedChanged = Signal()
    sleepChanged = Signal()
    eqChanged = Signal()
    showSpeedChanged = Signal(int, float)  # a podcast show's own speed was changed while one of its episodes played
    _host_looked_up = Signal(object)
    _file_checked = Signal(object)
    played = Signal("QVariantMap")  # a track was listened to for long enough to count as a play
    skipped = Signal("QVariantMap")  # the listener moved on from a playing track before it counted as played
    visualizerChanged = Signal()
    outputDevicesChanged = Signal()
    signalPathChanged = Signal()
    waveformChanged = Signal()
    radioChanged = Signal()
    _radio_ready = Signal(object)
    _visual_levels_ready = Signal(object)

    def __init__(self, parent=None, session_file=None):
        super().__init__(parent)
        self._session_file = Path(session_file) if session_file else None
        self._restore_pos = 0
        self._parked = False  # a station shown but not connected (see _park_station)
        self._outputs_changed = False  # sound devices changed while nothing played (applied on play)
        self._host_wait = 0
        self._looking_up = set()
        self._host_looked_up.connect(self._on_host_looked_up)
        self._file_checked.connect(self._on_file_checked)
        self._next_pick = None
        self.gapless_swaps = 0
        self._queue = []
        self._index = -1
        self._history = []
        self._played = set()
        self._undo = []  # earlier queues, newest last (see _remember_queue)
        self._shuffle = False
        self._repeat = REPEAT_OFF
        self._error = ""
        self._error_streak = 0
        self._stream_retries = 0
        self._model = DictModel(TRACK_KEYS, self)
        self._visualizer_enabled = False
        self._visualizer_levels = [0.0] * VISUALIZER_BARS
        self._visualizer_generation = 0
        self._visualizer_pending = False
        self._visualizer_pool = None
        self._visual_levels_ready.connect(self._apply_visualizer_levels)
        for changed in (self.trackChanged, self.volumeChanged, self.audioSettingsChanged, self.speedChanged,
                        self.eqChanged, self.outputDevicesChanged):
            changed.connect(self.signalPathChanged)

        self._settings = QSettings("hallucinate", "hallucinate")
        self._show_track_info = str(self._settings.value("display/showTrackInfo", "false")).lower() == "true"
        try:
            stored_volume = float(self._settings.value("volume", 0.8))
            self._volume = stored_volume if math.isfinite(stored_volume) else 0.8
        except (TypeError, ValueError):
            self._volume = 0.8
        self._visualizer_enabled = (
            str(self._settings.value("visualizer/enabled", "false")).lower() == "true" and eq.available()
        )
        if self._visualizer_enabled:
            self._visualizer_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="hallucinate-spectrum")
        self._rg_mode = str(self._settings.value("replaygain/mode", "off"))
        if self._rg_mode not in ("off", "track", "album"):
            self._rg_mode = "off"
        self._rg_preamp = self._float_setting("replaygain/preamp", 0.0, -15.0, 15.0)
        self._crossfade = int(self._float_setting("crossfade", 0, 0, 12))
        self._speed = self._float_setting("speed", 1.0, 0.5, 2.0)
        self._podcast_speed = self._float_setting("podcastSpeed", 1.0, 0.5, 3.0)  # podcasts keep their own
        self._sleep_left = -1  # seconds until sleep; -1 when no timer is running
        self._sleep_after_track = False
        self._sleep_gain = 1.0
        self._sleep_timer = QTimer(self)
        self._sleep_timer.setInterval(1000)
        self._sleep_timer.timeout.connect(self._sleep_tick)
        self._eq_enabled = False
        self._eq_gains = [0.0] * len(eq.BANDS)
        self._eq_preset = "Flat"
        self._headphone = {"name": "", "curve": None}
        self._crossfeed = str(self._settings.value("audio/crossfeed", "off"))
        if self._crossfeed not in eq.CROSSFEED:
            self._crossfeed = "off"
        try:
            stored = json.loads(str(self._settings.value("eq/headphone", "{}")))
            if stored.get("name") and stored.get("curve"):
                self._headphone = {"name": str(stored["name"]), "curve": stored["curve"]}
        except (TypeError, ValueError):
            pass
        if eq.available():
            self._eq_enabled = str(self._settings.value("eq/enabled", "false")).lower() == "true"
            try:
                g = json.loads(str(self._settings.value("eq/gains", "[]")))
                if isinstance(g, list) and len(g) == len(eq.BANDS):
                    self._eq_gains = [min(max(float(x), -eq.MAX_GAIN_DB), eq.MAX_GAIN_DB) for x in g]
            except (ValueError, TypeError):
                pass
            self._eq_preset = self._detect_preset()
        self._radio = str(self._settings.value("playback/radio", "false")).lower() == "true"
        self._radio_source = None
        self._radio_rules = None
        self._waveforms = None
        self._waveform = []
        self._radio_pending = False
        self._radio_ready.connect(self._apply_radio)
        self._output_key = str(self._settings.value("audio/outputDevice", "") or "")
        self._output_name = str(self._settings.value("audio/outputDeviceName", "") or "")
        self._eq_per_device = self._settings.value("eq/perDevice", False, bool)
        self._eq_device = ""  # the device whose equalizer is in use (set once the outputs are known)
        self._media_devices = QMediaDevices(self)
        self._media_devices.audioOutputsChanged.connect(self._on_audio_outputs_changed)
        self._fading = False
        self._fade_start = 0.0
        self._fade_ms = 0
        self._handoff_timer = QTimer(self)
        self._handoff_timer.setSingleShot(True)
        self._handoff_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._handoff_timer.timeout.connect(self._advance_before_end)
        self._fade_timer = QTimer(self)
        self._fade_timer.setInterval(40)
        self._fade_timer.timeout.connect(self._fade_tick)
        self._voices = [_Voice(self), _Voice(self)]
        self._cur = 0
        for n, v in enumerate(self._voices):
            v.audio.setVolume(self._volume ** 2)
            self._connect_voice(n)
            v.on_new_player = lambda _v, n=n, me=weakref.ref(self): me() is not None and me()._rewire_voice(n)
        self._reap_timer = QTimer(self)
        self._reap_timer.setInterval(1000)
        self._reap_timer.timeout.connect(_reap_set_aside)
        self._reap_timer.start()
        self._apply_speed()
        self._apply_output_device()
        self._eq_device = self._current_device_key()
        if self._dsp_on():
            self._sync_taps()
        elif self._visualizer_enabled:
            self._sync_audio_buffer_outputs()
        self.trackChanged.connect(self._clear_visualizer)
        self.trackChanged.connect(self._maybe_extend_radio)
        self.trackChanged.connect(self._update_waveform)
        self.trackChanged.connect(self._apply_speed)
        self.trackChanged.connect(self.speedChanged)
        self.queueChanged.connect(self._maybe_extend_radio)
        self.repeatChanged.connect(self._maybe_extend_radio)
        self.shuffleChanged.connect(self._maybe_extend_radio)
        self.stateChanged.connect(self._clear_visualizer)

        # A station can go silent without closing the connection: nothing errors and nothing ends, the
        # position just stops. Notice that and reconnect, as for a dropped stream.
        self._quiet_timer = QTimer(self)
        self._quiet_timer.setInterval(5000)
        self._quiet_timer.timeout.connect(self._check_stream_quiet)
        self._stream_pos, self._stream_moved = -1, 0.0
        # One reconnect waits at a time: a drop can be reported twice (an error and an end), and the silence
        # check can fire while a retry is pending; a stray second retry would tear down a stream that's back.
        self._retry_timer = QTimer(self)
        self._retry_timer.setSingleShot(True)
        self._retry_timer.timeout.connect(self._retry_stream_now)
        self._retry_index = -1
        self.stateChanged.connect(self._watch_stream)
        self.trackChanged.connect(self._watch_stream)

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

    @Property(bool, notify=audioSettingsChanged)
    def showTrackInfo(self):
        return self._show_track_info

    @Slot(bool)
    def setShowTrackInfo(self, enabled):
        enabled = bool(enabled)
        if enabled != self._show_track_info:
            self._show_track_info = enabled
            self._settings.setValue("display/showTrackInfo", "true" if enabled else "false")
            self.audioSettingsChanged.emit()

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
        return self._rate()

    def _episode_now(self):
        return self.hasTrack and track_kind(self.current) == "episode"

    def _rate(self):
        if self._episode_now():
            return float(self.current.get("speed") or 0) or self._podcast_speed  # a show can keep its own
        return self._speed

    @Property(float, notify=speedChanged)
    def podcastSpeed(self):
        return self._podcast_speed

    @Slot(float)
    def setSpeed(self, rate):
        """The playback speed of what's playing. Podcasts keep a speed of their own (up to 3×), so speeding
        up talk doesn't speed up the music after it."""
        if self._episode_now():
            rate = round(min(max(float(rate), 0.5), 3.0), 2)
            if self.current.get("speed"):  # this show has a speed of its own: that's what changes
                if rate == self.current["speed"]:
                    return
                self.current["speed"] = rate
                self.showSpeedChanged.emit(int(self.current.get("podcast_id") or 0), rate)
            elif rate == self._podcast_speed:
                return
            else:
                self._podcast_speed = rate
                self._settings.setValue("podcastSpeed", rate)
        else:
            rate = round(min(max(float(rate), 0.5), 2.0), 2)
            if rate == self._speed:
                return
            self._speed = rate
            self._settings.setValue("speed", rate)
        self._apply_speed()
        self.speedChanged.emit()

    @Slot()
    def _connect_voice(self, n):
        p = self._voices[n].player
        p.playbackStateChanged.connect(lambda *_, n=n: self._if_current(n, self.stateChanged))
        p.positionChanged.connect(lambda *_, n=n: self._on_position(n))
        p.durationChanged.connect(lambda *_, n=n: self._on_duration(n))
        p.mediaStatusChanged.connect(lambda st, n=n: self._on_media_status(n, st))
        p.errorOccurred.connect(lambda err, msg, n=n: self._on_error(n, msg))
        p.playbackStateChanged.connect(lambda st, n=n: self._tap_state(n, st))

    def _rewire_voice(self, n):
        """A voice got a new player (its old one was still opening a stream): set it up like the old one."""
        self._connect_voice(n)
        self._apply_speed()
        self._apply_output_device()
        if self._dsp_on():
            self._sync_taps()
        elif self._visualizer_enabled:
            self._sync_audio_buffer_outputs()
        self._apply_volume()

    def _apply_speed(self):
        rate = self._rate()
        for v in self._voices:
            if v.player.playbackRate() != rate:
                v.player.setPlaybackRate(rate)

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

    # --- the equalizer for each output device -------------------------------------------------------------
    @Property(bool, notify=eqChanged)
    def eqPerDevice(self):
        """Keep separate equalizer settings (bands, headphone correction, crossfeed) for each output device,
        switching when the sound moves to another one (headphones plugged in, say)."""
        return self._eq_per_device

    @Slot(bool)
    def setEqPerDevice(self, on):
        self._eq_per_device = bool(on)
        self._settings.setValue("eq/perDevice", self._eq_per_device)
        self._eq_device = self._current_device_key()
        if on:
            self._save_eq()  # what's set now becomes this device's
        self.eqChanged.emit()

    @Property(str, notify=eqChanged)
    def eqDeviceName(self):
        device = self._output_audio_device()
        return "" if device.isNull() else device.description()

    def _current_device_key(self):
        device = self._output_audio_device()
        return "" if device.isNull() else device_key(device)

    def _switch_device_eq(self):
        """The sound moved to another device: bring back that device's equalizer, if it has one."""
        if not self._eq_per_device:
            return
        key = self._current_device_key()
        if key == self._eq_device:
            return
        self._eq_device = key
        try:
            stored = json.loads(str(self._settings.value(f"eq/device/{key}", "") or "null"))
        except ValueError:
            stored = None
        if not isinstance(stored, dict):
            self._save_eq()  # a new device starts from what was in use
            return
        gains = stored.get("gains")
        if isinstance(gains, list) and len(gains) == len(self._eq_gains):
            self._eq_gains = [min(max(float(g), -eq.MAX_GAIN_DB), eq.MAX_GAIN_DB) for g in gains]
        self._eq_enabled = bool(stored.get("enabled")) and eq.available()
        hp = stored.get("headphone")
        self._headphone = hp if isinstance(hp, dict) and "name" in hp else {"name": "", "curve": None}
        cf = stored.get("crossfeed", "off")
        self._crossfeed = cf if cf in eq.CROSSFEED else "off"
        self._sync_taps()
        self._save_eq()

    def _save_eq(self):
        if getattr(self, "_eq_per_device", False):
            self._settings.setValue(f"eq/device/{self._eq_device}", json.dumps({
                "enabled": self._eq_enabled, "gains": self._eq_gains, "headphone": self._headphone,
                "crossfeed": self._crossfeed}))
        self._settings.setValue("eq/enabled", "true" if self._eq_enabled else "false")
        self._settings.setValue("eq/gains", json.dumps(self._eq_gains))
        self._settings.setValue("eq/headphone", json.dumps(self._headphone))
        self._eq_preset = self._detect_preset()
        for voice in self._voices:
            if voice.tap is not None:
                self._configure_processor(voice.tap.processor)
        self.eqChanged.emit()
        self.signalPathChanged.emit()

    def _configure_processor(self, processor):
        processor.eq_on = self._eq_enabled
        processor.set_gains(self._eq_gains)
        processor.set_curve(self._headphone["curve"])
        processor.set_crossfeed(self._crossfeed)

    def _dsp_on(self):
        """Whether the audio runs through our own processing (equalizer and/or crossfeed)."""
        return eq.available() and (self._eq_enabled or self._crossfeed in eq.CROSSFEED)

    @Property(str, notify=eqChanged)
    def crossfeed(self):
        return self._crossfeed

    @Property("QStringList", constant=True)
    def crossfeedPresets(self):
        return ["off", *eq.CROSSFEED]

    @Slot(str)
    def setCrossfeed(self, preset):
        """Headphone crossfeed: "off", "light", "medium" or "strong"."""
        preset = preset if preset in eq.CROSSFEED else "off"
        if preset == "off" or eq.available():
            if preset != self._crossfeed:
                self._crossfeed = preset
                self._settings.setValue("audio/crossfeed", preset)
                self._sync_taps()
                self._save_eq()

    @Property(str, notify=eqChanged)
    def headphoneName(self):
        """The headphone being corrected for (AutoEQ profile), or ""."""
        return self._headphone["name"]

    @Property("QVariantList", notify=eqChanged)
    def headphoneCurve(self):
        return list(self._headphone["curve"] or [])

    @Slot(str, str)
    def setHeadphoneProfile(self, name, curve_json):
        """Correct for a headphone: `curve_json` is [[freq, dB], ...] (see headphones.parse). Turns the EQ on."""
        try:
            curve = [[float(f), float(g)] for f, g in json.loads(curve_json)]
        except (TypeError, ValueError):
            return
        if len(curve) < 2 or not name.strip() or not all(math.isfinite(f) and math.isfinite(g) for f, g in curve):
            return  # nan or inf would make the filter (and the sound) garbage
        self._headphone = {"name": name.strip(), "curve": curve}
        if not self._eq_enabled and eq.available():
            self._eq_enabled = True
            self._sync_taps()
        self._save_eq()

    @Slot()
    def clearHeadphone(self):
        self._headphone = {"name": "", "curve": None}
        self._save_eq()

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

    # --- waveform --------------------------------------------------------------
    @Property("QVariantList", notify=waveformChanged)
    def waveform(self):
        """Loudness envelope of the current track (0..1 values), or empty while it is being analysed."""
        return self._waveform

    def setWaveformService(self, service):
        self._waveforms = service
        service.ready.connect(self._on_waveform_ready)
        self._update_waveform()

    @Slot()
    def _update_waveform(self):
        current = self._queue[self._index] if self.hasTrack else {}
        peaks = self._request_waveform(current) if self._waveforms is not None and current else None
        self._set_waveform(peaks or [])
        nxt = self._index + 1
        if self._waveforms is not None and 0 <= nxt < len(self._queue):
            self._request_waveform(self._queue[nxt], urgent=False)  # ready when it starts

    def _request_waveform(self, track, urgent=True):
        path = track.get("path", "")
        if not path or is_url(path) or remote.is_remote(path) or track_kind(track) != "music":
            return None  # streams and server songs: no file to read a waveform from
        if track.get("file"):  # a CUE sheet song: its stretch of the album's file
            return self._waveforms.request_window(path, track["file"], track.get("cue_start") or 0.0,
                                                  track.get("cue_end") or 0.0, urgent)
        return self._waveforms.request(path, urgent)

    @Slot(str)
    def _on_waveform_ready(self, path):
        if self.hasTrack and self._queue[self._index].get("path") == path:
            self._set_waveform(self._waveforms.peaks(path) or [])

    def _set_waveform(self, peaks):
        if peaks != self._waveform:
            self._waveform = list(peaks)
            self.waveformChanged.emit()

    # --- radio ----------------------------------------------------------------
    @Property(bool, notify=radioChanged)
    def radio(self):
        return self._radio

    @Slot(bool)
    def setRadio(self, on):
        on = bool(on)
        if on == self._radio:
            return
        self._radio = on
        self._settings.setValue("playback/radio", "true" if on else "false")
        self.radioChanged.emit()
        self._maybe_extend_radio()

    def setRadioSource(self, source):
        """`source(seeds, exclude, done, rules)` finds tracks to follow `seeds` (paths, most recent last),
        skipping `exclude` and limited to smart playlist `rules` (or None), and calls `done(tracks)` from any
        thread."""
        self._radio_source = source
        self._maybe_extend_radio()

    def _tracks_left(self):
        if not self.hasTrack:
            return 0
        if self._shuffle:
            return sum(1 for i in range(len(self._queue)) if i not in self._played)
        return len(self._queue) - self._index - 1

    @Slot()
    def _maybe_extend_radio(self):
        if (not self._radio or self._radio_source is None or self._radio_pending or not self.hasTrack
                or self._repeat != REPEAT_OFF or self._tracks_left() >= RADIO_LOW_WATER
                or track_kind(self.current) != "music"):
            return
        recent = [i for i in self._history if 0 <= i < len(self._queue)][-(RADIO_SEEDS - 1):] + [self._index]
        seeds = [self._queue[i].get("path", "") for i in recent]
        anchor = seeds[-1]
        if anchor == getattr(self, "_radio_exhausted", None):
            return  # nothing more to add for this song (asked already); a new song asks again
        self._radio_pending = True
        self._radio_source(seeds, [t.get("path", "") for t in self._queue],
                           lambda tracks: self._radio_ready.emit((anchor, tracks)), self._radio_rules)

    @Slot(object)
    def _apply_radio(self, payload):
        anchor, tracks = payload
        self._radio_pending = False
        # Drop stale results: radio was switched off, or the queue was replaced while they were being picked.
        if not self._radio or not any(t.get("path") == anchor for t in self._queue):
            self._maybe_extend_radio()  # e.g. the queue was replaced: ask again for the new one
            return
        if not tracks:
            # Nothing similar left (everything's queued, the song isn't in the library, a smart playlist's
            # rules match nothing new): don't ask again for this song, or it would ask in a tight loop.
            self._radio_exhausted = anchor
            return
        start = len(self._queue)
        ended = self._ended
        self.enqueueAll(tracks)
        if ended:
            self._load(start)  # the queue ran out while this batch was being picked

    # --- output device -------------------------------------------------------
    @Property("QVariantList", notify=outputDevicesChanged)
    def outputDevices(self):
        """[{key, name}] for the Settings picker; key "" follows the system default."""
        devices = QMediaDevices.audioOutputs()
        default = QMediaDevices.defaultAudioOutput()
        label = f"System default ({default.description()})" if not default.isNull() else "System default"
        items = [{"key": "", "name": label}]
        items += [{"key": device_key(d), "name": d.description()} for d in devices]
        if self._output_key and pick_output_device(devices, self._output_key) is None:
            items.append({"key": self._output_key, "name": f"{self._output_name or 'Saved device'} (not connected)"})
        return items

    @Property(str, notify=outputDevicesChanged)
    def outputDevice(self):
        return self._output_key

    @Slot(str)
    def setOutputDevice(self, key):
        key = key or ""
        device = pick_output_device(QMediaDevices.audioOutputs(), key)
        if key and device is None and key != self._output_key:
            return  # unknown device; keep the current choice
        self._output_key = key
        if device is not None:
            self._output_name = device.description()
        self._settings.setValue("audio/outputDevice", self._output_key)
        self._settings.setValue("audio/outputDeviceName", self._output_name if key else "")
        self._apply_output_device()
        self._switch_device_eq()
        self.outputDevicesChanged.emit()

    @Property("QVariantMap", notify=signalPathChanged)
    def signalPath(self):
        """The current track's way from file to speakers (see signalpath.describe)."""
        track = self._queue[self._index] if self.hasTrack else None
        device = self._output_audio_device()
        return signalpath.describe(
            track,
            rg_factor=replaygain_factor(track, self._rg_mode, self._rg_preamp),
            rg_mode=self._rg_mode,
            volume=self._volume,
            speed=self._rate(),
            eq_enabled=self._eq_enabled,
            eq_preset=self._eq_preset + (f" + {self._headphone['name']}" if self._headphone["name"] else ""),
            crossfeed=self._crossfeed if self._crossfeed in eq.CROSSFEED and eq.available() else "",
            crossfade=self._crossfade,
            device_name="" if device.isNull() else device.description(),
            device_rate=0 if device.isNull() else device.preferredFormat().sampleRate(),
        )

    def _output_audio_device(self):
        """The chosen device while it is connected, otherwise the current system default."""
        device = pick_output_device(QMediaDevices.audioOutputs(), self._output_key)
        return QMediaDevices.defaultAudioOutput() if device is None else device

    def _apply_output_device(self, reattach=False):
        device = self._output_audio_device()
        for voice in self._voices:
            if reattach and voice.audio.device() == device:
                voice.audio.setDevice(QAudioDevice())
            if voice.audio.device() != device:
                voice.audio.setDevice(device)
            if voice.tap is not None:
                voice.tap.setDevice(device, force=reattach)

    @Slot()
    def _on_audio_outputs_changed(self):
        if not self.playing:
            # Nothing's playing (a monitor going to sleep takes its HDMI sound with it, for one): don't touch
            # the sound system now; play sets the output up first.
            self._outputs_changed = True
            self.outputDevicesChanged.emit()
            return
        self._outputs_changed = False
        self._reapply_outputs()

    def _reapply_outputs(self):
        # Re-resolve: the saved device may have been plugged in or removed, or the default may have moved.
        # Some backends (PulseAudio on Qt 6.11) report a device coming back but not it going away, so its entry
        # looks unchanged while the sound server has moved our stream elsewhere; re-attach to the chosen device.
        chosen = pick_output_device(QMediaDevices.audioOutputs(), self._output_key) is not None
        self._apply_output_device(reattach=chosen)
        self._switch_device_eq()
        self.outputDevicesChanged.emit()

    def _sync_taps(self):
        for n, voice in enumerate(self._voices):
            if self._dsp_on() and voice.tap is None:
                tap = eq.EqTap(eq.EqProcessor(), self)
                self._configure_processor(tap.processor)
                tap.setDevice(self._output_audio_device())
                voice.tap = tap
                tap.setRunning(voice.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState)
            elif not self._dsp_on() and voice.tap is not None:
                voice.player.setAudioBufferOutput(None)
                tap = voice.tap
                tap.close()
                voice.tap = None
                voice.tap_visual_connected = False
                tap.deleteLater()
                QCoreApplication.sendPostedEvents(tap, QEvent.Type.DeferredDelete)
        self._sync_audio_buffer_outputs()
        self._apply_volume()

    def _sync_audio_buffer_outputs(self):
        for n, voice in enumerate(self._voices):
            if voice.tap is not None:
                if self._visualizer_enabled and not voice.tap_visual_connected:
                    voice.tap.output.audioBufferReceived.connect(
                        lambda buf, n=n: self._on_visualizer_buffer(n, buf)
                    )
                    voice.tap_visual_connected = True
                output = voice.tap.output
            elif self._visualizer_enabled:
                if voice.visual_output is None:
                    voice.visual_output = QAudioBufferOutput(voice.player)
                    voice.visual_output.audioBufferReceived.connect(
                        lambda buf, n=n: self._on_visualizer_buffer(n, buf)
                    )
                output = voice.visual_output
            else:
                output = None
            voice.player.setAudioBufferOutput(output)

    @Property(bool, constant=True)
    def visualizerAvailable(self):
        return eq.available()

    @Property(bool, notify=visualizerChanged)
    def visualizerEnabled(self):
        return self._visualizer_enabled

    @Property("QVariantList", notify=visualizerChanged)
    def visualizerLevels(self):
        return list(self._visualizer_levels)

    @Slot(bool)
    def setVisualizerEnabled(self, enabled):
        enabled = bool(enabled) and eq.available()
        if enabled == self._visualizer_enabled:
            return
        if enabled and self._visualizer_pool is None:
            self._visualizer_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="hallucinate-spectrum")
        self._visualizer_enabled = enabled
        self._settings.setValue("visualizer/enabled", "true" if enabled else "false")
        self._visualizer_generation += 1
        self._visualizer_pending = False
        self._visualizer_levels = [0.0] * VISUALIZER_BARS
        self._sync_audio_buffer_outputs()
        self.visualizerChanged.emit()

    def _on_visualizer_buffer(self, voice_index, buffer):
        if (
            not self._visualizer_enabled
            or not self.playing
            or voice_index != self._cur
            or self._visualizer_pending
        ):
            return
        fmt = buffer.format()
        channels = fmt.channelCount()
        if not buffer.isValid() or channels <= 0:
            return
        raw = bytes(buffer.constData())
        if not raw or self._visualizer_pool is None:
            return
        self._visualizer_pending = True
        generation = self._visualizer_generation
        future = self._visualizer_pool.submit(
            self._spectrum_levels, raw, fmt.sampleFormat(), channels
        )

        def done(result):
            try:
                levels = result.result()
                error = ""
            except Exception as exc:  # noqa: BLE001
                logger.warning("Visualizer buffer analysis failed: %s", exc)
                levels, error = [], str(exc)
            self._visual_levels_ready.emit((generation, levels, error))

        future.add_done_callback(done)

    @staticmethod
    def _spectrum_levels(raw, sample_format, channels):
        np = eq.np
        formats = {
            QAudioFormat.SampleFormat.UInt8: ("u1", lambda a: (a.astype(np.float32) - 128) / 128),
            QAudioFormat.SampleFormat.Int16: ("<i2", lambda a: a.astype(np.float32) / 32768),
            QAudioFormat.SampleFormat.Int32: ("<i4", lambda a: a.astype(np.float32) / 2147483648),
            QAudioFormat.SampleFormat.Float: ("<f4", lambda a: a.astype(np.float32)),
        }
        spec = formats.get(sample_format)
        if np is None or spec is None:
            return [0.0] * VISUALIZER_BARS
        samples = np.frombuffer(raw, dtype=spec[0])
        usable = samples.size - samples.size % channels
        if usable < channels * 256:
            return [0.0] * VISUALIZER_BARS
        mono = spec[1](samples[:usable]).reshape(-1, channels).mean(axis=1)
        mono = mono[-2048:]
        size = mono.size
        spectrum = np.abs(np.fft.rfft(mono * np.hanning(size)))
        edges = np.geomspace(1, len(spectrum), VISUALIZER_BARS + 1).astype(int)
        levels = []
        for low, high in zip(edges[:-1], edges[1:]):
            high = max(high, low + 1)
            band = spectrum[low:high]
            value = float(np.sqrt(np.mean(np.square(band))) / (size / 2) * 4)
            levels.append(min(1.0, max(0.0, value)))
        return levels

    @Slot(object)
    def _apply_visualizer_levels(self, payload):
        generation, levels, error = payload
        if generation != self._visualizer_generation:
            return
        self._visualizer_pending = False
        if error:
            self._visualizer_enabled = False
            self._visualizer_levels = [0.0] * VISUALIZER_BARS
            self._settings.setValue("visualizer/enabled", "false")
            self._sync_audio_buffer_outputs()
            logger.warning("Spectrum visualizer disabled after analysis failure")
        else:
            self._visualizer_levels = levels
        self.visualizerChanged.emit()

    @Slot()
    def _clear_visualizer(self):
        if not self._visualizer_enabled or self.playing:
            return
        self._visualizer_generation += 1
        self._visualizer_pending = False
        if any(self._visualizer_levels):
            self._visualizer_levels = [0.0] * VISUALIZER_BARS
            self.visualizerChanged.emit()

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
        return self._voice.position()

    @Property(int, notify=durationChanged)
    def duration(self):
        d = self._voice.duration()
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
        if self._outputs_changed:  # the sound devices changed while nothing played
            self._outputs_changed = False
            self._reapply_outputs()
        if self.hasTrack and self._parked:
            self._load(self._index, record=False)  # a stream that was only shown: connect to it now
            return
        if self.hasTrack:
            if self._ended or self._player.mediaStatus() == QMediaPlayer.MediaStatus.EndOfMedia:
                if self._voice.tap is not None:
                    self._voice.tap.reset()
                self._voice.set_position(0)
            self._ended = False
            self._player.play()
        elif self._queue:
            self._load(0)

    @Slot()
    def pause(self):
        if self.hasTrack and track_kind(self.current) == "station":
            # Live radio can't be paused: hang up, and play connects again (to what's on now). A paused
            # connection only gets dropped by the station and reconnected for nothing.
            self._park_station(self._index)
            self.saveSession()
            return
        self._ended = False
        self._end_fade()
        self._player.pause()
        self.stateChanged.emit()
        self.saveSession()

    @Slot()
    def stop(self):
        if self.hasTrack and track_kind(self.current) == "station":
            self._park_station(self._index)
            self.saveSession()
            return
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
        self._voice.set_position(ms)
        self.seeked.emit(ms)

    @Slot(int)
    def seekBy(self, delta_ms):
        self.seek(min(self._voice.position() + delta_ms, max(self.duration - 1, 0)))

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
            self._note_skip(nxt)
            self._load(nxt)

    def _note_skip(self, target):
        """Moving on by hand from a song that is playing and hasn't counted as a play yet is a skip."""
        if (self.hasTrack and target != self._index and self.playing and not self._play_counted
                and self._voice.position() >= SKIP_MIN_MS and track_kind(self.current) == "music"):
            self.skipped.emit(dict(self.current))

    @Slot()
    def previous(self):
        if self.hasTrack and track_kind(self.current) == "station":
            if self._history:
                self._load(self._history.pop(), record=False)
            elif self._index > 0:
                self._load(self._index - 1, record=False)
            return
        if self._voice.position() > 3000 or not self.hasTrack:
            self.seek(0)
        elif self._history:
            self._load(self._history.pop(), record=False)
        elif self._index > 0 and not self._shuffle:
            self._load(self._index - 1, record=False)
        else:
            self.seek(0)

    # --- queue -------------------------------------------------------------
    @Slot("QVariantList", int)
    def playList(self, tracks, index=0, radio_rules=None):
        """Replace the queue with `tracks` and start playing at `index`.

        `radio_rules` (a smart playlist rule set) keeps radio picks within the playlist's rules."""
        self._radio_rules = radio_rules
        new = list(tracks)
        if [t.get("path") for t in new] != [t.get("path") for t in self._queue]:
            self._remember_queue("Queue replaced")
        self._queue = new  # queue entries are treated as immutable
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
            self._note_skip(i)
            self._load(i)

    @Slot(int)
    def removeAt(self, i):
        if not 0 <= i < len(self._queue):
            return
        self._remember_queue("Song removed")
        del self._queue[i]
        self._history = [h - (h > i) for h in self._history if h != i]
        self._played = {p - (p > i) for p in self._played if p != i}
        self._drop_standby()
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
        self._remember_queue("Song moved")
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
        self._drop_standby()
        self._invalidate_next()
        self._sync_queue()
        self.trackChanged.emit()

    @Slot()
    def clearQueue(self):
        if not self._queue:
            return
        self._remember_queue("Queue cleared")
        self._queue.clear()
        self._history.clear()
        self._played.clear()
        self._standby.clear()
        self._sync_queue()
        self._reset_empty()

    # --- undo ----------------------------------------------------------------
    def _remember_queue(self, label):
        """Keep the queue as it is now, so the change about to happen can be undone."""
        if not self._queue:
            return
        self._undo.append({
            "label": label, "queue": list(self._queue), "index": self._index, "history": list(self._history),
            "played": set(self._played), "position": self._voice.position() if self.hasTrack else 0,
            "playing": self.playing, "radio_rules": self._radio_rules,
        })
        del self._undo[:-UNDO_STEPS]
        self.undoChanged.emit()

    @Property(bool, notify=undoChanged)
    def canUndoQueue(self):
        return bool(self._undo)

    @Property(str, notify=undoChanged)
    def undoLabel(self):
        return self._undo[-1]["label"] if self._undo else ""

    @Slot(result=str)
    def undoQueue(self):
        """Put the queue back as it was before the last change; returns what was undone ("" if nothing)."""
        if not self._undo:
            return ""
        snap = self._undo.pop()
        current = self._queue[self._index] if self.hasTrack else None
        target = snap["queue"][snap["index"]] if 0 <= snap["index"] < len(snap["queue"]) else None
        self._queue = snap["queue"]
        self._history = snap["history"]
        self._played = snap["played"]
        self._radio_rules = snap["radio_rules"]
        self._standby.clear()
        self._invalidate_next()
        self._sync_queue()
        if target is not None and current is not None and self._voice.holds(self._index, current) \
                and current.get("path") == target.get("path") and track_window(current) == track_window(target):
            # the same song is still loaded: carry on without a break
            self._index = self._voice.index = snap["index"]
            self.trackChanged.emit()
        elif target is not None:
            self._load(snap["index"], autoplay=snap["playing"] or self.playing, record=False)  # keep the music going
            if snap["position"] > 0:
                self._restore_pos = snap["position"]
                if self._player.mediaStatus() in (QMediaPlayer.MediaStatus.LoadedMedia,
                                                  QMediaPlayer.MediaStatus.BufferedMedia):
                    self._voice.set_position(snap["position"])
                    self._restore_pos = 0
        else:
            self._reset_empty()
        self.undoChanged.emit()
        self.saveSession()
        return snap["label"]

    # --- internals ---------------------------------------------------------
    def _reset_empty(self):
        self._host_wait += 1  # nothing to play: a lookup still in flight must not start anything
        self._voice.clear()
        self._index = -1
        self._invalidate_next()
        self.trackChanged.emit()
        self.durationChanged.emit()
        self.positionChanged.emit()

    def _shift_indexes_after(self, at, delta):
        self._history = [h + delta if h >= at else h for h in self._history]
        self._played = {p + delta if p >= at else p for p in self._played}
        self._drop_standby()
        self._invalidate_next()

    def _sync_queue(self):
        self._model.set_items(self._queue)
        self._standby_check()
        self.queueChanged.emit()

    def _standby_check(self):
        sb = self._standby
        if sb.index >= len(self._queue) or (sb.index >= 0 and not sb.holds(sb.index, self._queue[sb.index])):
            self._drop_standby()

    def _drop_standby(self):
        """Forget the pre-loaded next song after a queue edit. During a crossfade or a gapless tail the other
        voice is still playing out the previous song: let it finish instead of cutting it off mid-note."""
        sb = self._standby
        if self._fading or sb.finishing:
            sb.index = -1  # no longer anyone's next song; it stops by itself when it's done
        else:
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
        track = self._queue[i]
        path = track_file(track)
        self._host_wait += 1  # whatever was being looked up for an earlier choice no longer counts
        if _is_network(path) and not autoplay:
            self._park(i)  # not listening: don't connect to a stream until play
            return
        self._parked = False
        if i != self._index:
            self._stream_retries = 0
            self._retry_timer.stop()  # moving on: a reconnect for the old station isn't wanted
        if is_url(path) and net.is_offline():
            self._end_fade()
            for v in self._voices:
                v.clear()
            self._index = i
            self._set_error("Offline mode is on, so streams can't play")
            self.trackChanged.emit()
            self.stateChanged.emit()
            return
        if track_kind(track) == "station" and track.get("station"):
            track.update(title=track["station"], artist="", stream_title="")  # the song it said last is over
        if not is_url(path) and not remote.is_remote(path):
            answered, ok = self._check_file(path, i, autoplay, fade_ms, drain)
            if not answered:
                return  # a slow disk: it carries on once the file has answered
        else:
            ok = _playable(path)
        if not ok:
            self._index = i
            if remote.is_remote(path):
                self._set_error("Offline mode is on" if net.is_offline() else "The music server can't be reached")
            else:
                exists = isinstance(path, str) and os.path.isfile(path)
                self._set_error(f"{'Unreadable audio file' if exists else 'File not found'}: {path}")
            candidates = list(range(i + 1, len(self._queue)))
            if self._shuffle:
                candidates = [j for j in range(len(self._queue)) if j != i and j not in self._played]
                random.shuffle(candidates)
            elif self._repeat == REPEAT_ALL:
                candidates += list(range(0, i))
            for candidate in candidates:  # the next one that can play: songs on a server that's down are passed
                if self._maybe_playable(track_file(self._queue[candidate])):
                    self._load(candidate, autoplay=autoplay, record=False)
                    return
            self._reset_empty()
            return
        name = _net_host(path)
        if not _host_ready(name):
            self._await_host(name, i, autoplay, fade_ms, drain)
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
        self._handoff_timer.stop()
        self._ended = False
        self._listened = 0
        self._last_pos = 0
        self._play_counted = False

        sb = self._standby
        cur = self._voice
        if (track.get("file") and cur.path == path and cur.index >= 0 and cur.player.source().isValid()
                and not cur.finishing):
            # Another song of the CUE sheet this voice is playing: carry on in the same file. Straight after
            # the previous song that needs no seek at all, so the album plays exactly as one piece.
            start, end = track_window(track)
            contiguous = drain and cur.end and abs(start - cur.end) <= 5
            cur.index, cur.start, cur.end = i, start, end
            if cur.seek_on_load >= 0:  # the file is still loading: go to this song once it has
                cur.seek_on_load, cur.play_on_load = start, autoplay
            elif not contiguous:
                if cur.tap is not None:
                    cur.tap.reset()
                cur.set_position(0)
            self._player.setPlaybackRate(self._rate())
            if cur.seek_on_load >= 0:
                pass
            elif autoplay:
                self._player.play()
            else:
                self._player.pause()
            if sb.index not in (-1, i):
                sb.clear()
        elif autoplay and sb.holds(i, track) and sb.player.source().isValid():
            if drain:
                self._let_finish(self._voice)  # gapless: the old track plays out while the new one starts
            elif not fade_ms:
                self._voice.player.pause()
                if self._voice.tap is not None:
                    self._voice.tap.reset()
            self._cur = 1 - self._cur
            if self._voice.tap is not None:
                self._voice.tap.reset()
            self._voice.set_position(int(track.get("resume_ms") or 0))
            self.gapless_swaps += 1
            if fade_ms:
                self._start_fade(fade_ms)
            self._player.play()
        else:
            self._voice.load(i, track)
            self._player.setPlaybackRate(self._rate())
            if autoplay and self._voice.seek_on_load >= 0:
                self._voice.play_on_load = True  # start where the song starts, not at the top of the file
            elif autoplay:
                self._player.play()
            if sb.index not in (-1, i):
                sb.clear()
        self._apply_volume()
        self.trackChanged.emit()
        self.stateChanged.emit()
        self.durationChanged.emit()
        self.positionChanged.emit()

    def _check_file(self, path, i, autoplay, fade_ms, drain):
        """(answered, playable) for a song file, checked on a thread so a disk waking up or a network share
        that's gone away can't hold the window. Not answered quickly: "Opening…" shows and the song loads
        once it does (or, after FILE_TIMEOUT_MS, says it couldn't be opened)."""
        token = self._host_wait
        me = weakref.ref(self)

        def late(ok):
            owner = me()
            try:
                if owner is not None:
                    owner._file_checked.emit((token, ok, path, i, autoplay, fade_ms, drain))
            except RuntimeError:  # the player is gone (the app closed meanwhile)
                pass

        answered, ok = fileready.soon(lambda: _playable(path), late, FILE_WAIT_S)
        if answered:
            return True, ok
        self._set_error("Opening…")
        QTimer.singleShot(FILE_TIMEOUT_MS, self, lambda: me() is not None and me()._on_file_checked(
            (token, None, path, i, autoplay, fade_ms, drain)))
        return False, False

    @Slot(object)
    def _on_file_checked(self, r):
        token, ok, path, i, autoplay, fade_ms, drain = r
        if token != self._host_wait or not 0 <= i < len(self._queue):
            return  # something else was chosen meanwhile (or this check already answered, or timed out)
        self._host_wait += 1
        if ok is None:  # still not answered: don't wait on it again, nor on the songs after it
            self._end_fade()
            for v in self._voices:
                v.clear()
            self._index = i
            self._set_error(f"The file didn't open (is its disk or network share there?): {path}")
            self.trackChanged.emit()
            self.stateChanged.emit()
            return
        self._load(i, autoplay=autoplay, record=False, fade_ms=fade_ms, drain=drain)

    def _maybe_playable(self, path):
        """For passing over songs that can't play: True unless it surely can't (a slow file counts as maybe,
        and is then loaded the careful way)."""
        if is_url(path) or remote.is_remote(path):
            return _playable(path)
        answered, ok = fileready.soon(lambda: _playable(path), lambda _ok: None, FILE_WAIT_S)
        return ok or not answered

    def _await_host(self, name, i, autoplay, fade_ms, drain):
        """Look a stream's host up in the background, then load it (see _resolve). A lookup that doesn't
        answer in RESOLVE_TIMEOUT_MS counts as failed."""
        token = self._host_wait
        self._set_error("Connecting…")

        signal_owner = weakref.ref(self)

        def done(ok):
            owner = signal_owner()
            try:
                if owner is not None:
                    owner._host_looked_up.emit((token, ok, name, i, autoplay, fade_ms, drain))
            except RuntimeError:  # the player is gone (the app closed meanwhile)
                pass

        _resolve_in_background(name, done)
        me = weakref.ref(self)
        QTimer.singleShot(RESOLVE_TIMEOUT_MS, self, lambda: me() is not None and me()._on_host_looked_up(
            (token, False, name, i, autoplay, fade_ms, drain)))

    @Slot(object)
    def _on_host_looked_up(self, r):
        token, ok, name, i, autoplay, fade_ms, drain = r
        if token != self._host_wait or not 0 <= i < len(self._queue):
            return  # something else was chosen meanwhile (or this lookup already answered, or timed out)
        self._host_wait += 1  # answered: its timeout (or a late answer) does nothing
        if ok:
            self._load(i, autoplay=autoplay, record=False, fade_ms=fade_ms, drain=drain)
            return
        self._index = i
        kind = track_kind(self._queue[i])
        self._set_error(f"Couldn't find {'the station' if kind == 'station' else 'the server'} ({name}): "
                        "check your connection")
        self.trackChanged.emit()
        self.stateChanged.emit()
        if kind == "music" and autoplay:  # a server song: move on, as for any song that can't play
            self._error_streak += 1
            if self._error_streak < len(self._queue):
                QTimer.singleShot(300, self._skip_after_error)

    def _maybe_preload(self):
        if not self.hasTrack or not self.playing or self._fading:
            return
        dur = self._voice.duration()
        if dur <= 0 or dur - self._voice.position() > PRELOAD_MS + self._crossfade * 1000:
            return
        nxt = self._compute_next(auto=True)
        sb = self._standby
        if nxt is None or sb.finishing:
            return
        track = self._queue[nxt]
        if sb.holds(nxt, track):
            return
        if track.get("file") and track_file(track) == self._voice.path:
            return  # the next song of the same CUE sheet: this voice carries on into it
        name = _net_host(track_file(track))
        if not _host_ready(name):
            if name not in self._looking_up:  # once, not on every position tick
                self._looking_up.add(name)
                _resolve_in_background(name, lambda _ok, n=name: self._looking_up.discard(n))
            return  # ready by the time it's due, or loaded the careful way then
        sb.player.pause()
        sb.load(nxt, track)
        sb.player.pause()  # prepare the decoder without taking the audio device
        self._apply_volume()

    def _on_position(self, n):
        if n != self._cur:
            return
        self.positionChanged.emit()
        self._maybe_preload()
        pos = self._voice.position()
        dur = self._voice.duration()
        self._count_listening(pos, dur)
        if self._try_crossfade(pos, dur):
            return
        if (not self._transitioning and self.playing and dur > 0 and
                dur - pos <= HANDOFF_WINDOW_MS):
            # Start the next track just before this one ends, so the two meet without a gap or a cut.
            self._transitioning = True
            self._handoff_timer.start(max(0, dur - pos - HANDOFF_LEAD_MS))
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
        kind = track_kind(self.current) if self.hasTrack else "music"
        if kind == "episode":
            # podcasts keep their own place (see podcasts.py) and are never plays; one that's scrobbled counts
            # for that after half of it or four minutes, like a song
            if (self.current.get("scrobble") and self._listened >= min(240_000, max(dur, 1) / 2)):
                self._play_counted = True
                self.played.emit(dict(self.current))
            return
        if kind == "station":
            # a song on the radio, once its title is known, counts for scrobbling after a minute
            if self._listened >= STREAM_SONG_MS and self.current.get("artist") and self.current.get("stream_title"):
                self._play_counted = True
                self.played.emit(dict(self.current))
            return
        if dur <= 0:  # Qt hasn't said how long it is (yet): fall back to what the scan found, else 30 s
            dur = int(float(self.current.get("duration") or 0) * 1000) if self.hasTrack else 0
        if self._listened >= (min(30_000, dur / 2) if dur > 0 else 30_000) and self.hasTrack:
            self._play_counted = True
            self.played.emit(dict(self.current))

    def _advance_before_end(self):
        if not self.hasTrack or not self._transitioning:
            return
        if not self.playing:
            self._transitioning = False
            return
        if self._voice.duration() - self._voice.position() > HANDOFF_WINDOW_MS:
            self._transitioning = False  # seeked away from the end while waiting
            return
        self._advance_at_end()

    def _advance_at_end(self):
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
        elif self._player.mediaStatus() == QMediaPlayer.MediaStatus.EndOfMedia or self._voice.end:
            self._finish_queue()  # (a CUE song ends mid-file: stop there rather than play into the next one)
        else:
            # Let the last track play out; end-of-media finishes the queue, or the watchdog if it stalls.
            remaining = max(0, self._voice.duration() - self._voice.position())
            QTimer.singleShot(remaining + FINISH_GRACE_MS, self._finish_stalled_queue)
        self._transitioning = False

    def _finish_queue(self):
        if self._ended or not self.hasTrack:
            return
        self._ended = True
        if self._player.mediaStatus() != QMediaPlayer.MediaStatus.EndOfMedia:
            self._player.pause()
        self.stateChanged.emit()
        self.saveSession()

    def _finish_stalled_queue(self):
        # Still at the end of the last track (not seeked away or replaced): Qt never reported end-of-media.
        near_end = self._voice.duration() - self._voice.position() <= HANDOFF_WINDOW_MS
        if self.hasTrack and near_end and self._compute_next(auto=True) is None:
            self._finish_queue()

    def _let_finish(self, voice):
        if (voice.player.mediaStatus() == QMediaPlayer.MediaStatus.EndOfMedia
                or voice.player.playbackState() != QMediaPlayer.PlaybackState.PlayingState):
            return  # already over (e.g. the handoff ran from end-of-media)
        remaining = max(0, voice.duration() - voice.position())
        grace = 0 if voice.end else FINISH_GRACE_MS  # a CUE song mid-file has no end-of-stream to wait for
        voice.finishing = True
        voice.finish_by = time.monotonic() + (remaining + grace) / 1000
        QTimer.singleShot(remaining + grace, self._stop_finished)

    def _stop_finished(self):
        for voice in self._voices:
            if voice.finishing and voice is not self._voice and time.monotonic() >= voice.finish_by:
                voice.finishing = False
                voice.player.pause()  # no-op after a normal end; stops a stalled end-of-stream

    def _on_duration(self, n):
        if n == self._cur:
            self.durationChanged.emit()
            self._maybe_preload()

    def _on_media_status(self, n, status):
        S = QMediaPlayer.MediaStatus
        voice = self._voices[n]
        if status in (S.LoadedMedia, S.BufferedMedia) and voice.seek_on_load >= 0:
            voice.player.setPosition(voice.seek_on_load)
            voice.seek_on_load = -1
            if voice.play_on_load:
                voice.play_on_load = False
                voice.player.play()
        if n != self._cur:
            if status == S.EndOfMedia:
                self._voices[n].finishing = False
            return
        if status == S.EndOfMedia and self.hasTrack and track_kind(self.current) == "station":
            self._reconnect_stream("The station stopped sending")  # a live stream has no end: it dropped
            return
        if status in (S.BufferedMedia,) and self.hasTrack and is_url(self.current.get("path")):
            self._stream_retries = 0
            self._retry_timer.stop()  # it's back: a pending reconnect would only interrupt it
        if status == S.EndOfMedia and not self._ended and not self._fading:
            # Normally the next track has already taken over; this covers a handoff that never got scheduled.
            self._transitioning = False
            self._advance_at_end()
            return
        if status in (S.LoadedMedia, S.BufferedMedia):
            if status == S.BufferedMedia:
                self._error_streak = 0
                self._set_error("")
            if self._restore_pos:
                pos, self._restore_pos = self._restore_pos, 0
                self._voice.set_position(pos)
                self.positionChanged.emit()

    def _on_error(self, n, message):
        if n != self._cur:
            sb = self._voices[n]
            sb.clear()  # a failed pre-roll just falls back to a normal load later
            return
        if self._reconnect_stream(message):
            return
        if self.hasTrack and not self.playing and not self._voice.play_on_load and _is_network(self._voice.path):
            # a paused stream whose connection went away: hang up; play connects again where it was
            self._park(self._index, self._voice.position())
            return
        if self.hasTrack and remote.is_remote(self._queue[self._index].get("path")):
            # the backend's words for a server stream can include its link, sign-in and all: say it plainly
            message = "The music server couldn't play this song"
        self._set_error(message or "Playback error")
        self._error_streak += 1
        if self._error_streak < len(self._queue):
            QTimer.singleShot(300, self._skip_after_error)

    def _reconnect_stream(self, message):
        """A station that drops or errors is reconnected a few times, further apart each time. True if a
        reconnect was scheduled. Only while you're listening: a station that's only shown is never connected."""
        if not self.hasTrack or track_kind(self.current) != "station" or net.is_offline():
            return False
        if self._parked:
            return True  # nothing to reconnect; the error is the old connection going away
        if self._retry_timer.isActive():
            return True  # a reconnect is already on its way
        if self._stream_retries >= STREAM_RETRIES:
            logger.info("Station gave up after %d tries: %s", self._stream_retries, message)
            self._set_error("The station isn't answering. Try again later, or check its link.")
            return True
        self._stream_retries += 1
        delay = 1000 * 2 ** self._stream_retries
        logger.info("Station dropped (%s); reconnecting", message)
        self._set_error("Lost the station, reconnecting…")
        self._retry_index = self._index
        self._retry_timer.start(delay)
        return True

    def _park_station(self, index):
        self._park(index)

    def _park(self, index, position=0):
        """Show a stream (a station, a streamed episode, a server's song) without connecting to it: restored
        at start, a station paused, or a paused stream whose connection dropped. Nothing is fetched until you
        press play, which picks up where it was (live radio: what's on now)."""
        self._retry_timer.stop()
        self._quiet_timer.stop()
        self._end_fade()
        self._host_wait += 1
        self._index = index
        self._parked = True
        self._ended = False
        self._stream_retries = 0
        for v in self._voices:
            v.clear()
        entry = self._queue[index]
        if entry.get("station"):
            entry.update(title=entry["station"], artist="", stream_title="")  # the song it said last is over
        elif position > 0:
            entry["resume_ms"] = int(position)  # play picks up here (it's how a voice starts mid-way)
        self._set_error("")
        self.trackChanged.emit()
        self.stateChanged.emit()

    def _retry_stream_now(self):
        self._retry_stream(self._retry_index)

    def _watch_stream(self):
        on = self.playing and self.hasTrack and track_kind(self.current) == "station"
        if on and not self._quiet_timer.isActive():
            self._stream_pos, self._stream_moved = -1, time.monotonic()
            self._quiet_timer.start()
        elif not on:
            self._quiet_timer.stop()

    def _check_stream_quiet(self, now=None):
        if not (self.playing and self.hasTrack and track_kind(self.current) == "station"):
            self._quiet_timer.stop()
            return
        now = time.monotonic() if now is None else now
        pos = self._voice.player.position()
        if pos != self._stream_pos or self._retry_timer.isActive():
            self._stream_pos, self._stream_moved = pos, now
        elif (now - self._stream_moved) * 1000 >= STREAM_QUIET_MS:
            self._stream_moved = now  # one reconnect per silence; the retry restarts the count
            self._reconnect_stream("The station went quiet")

    def _retry_stream(self, index):
        if index == self._index and self.hasTrack and track_kind(self.current) == "station" and not self._parked:
            retries = self._stream_retries
            import urllib.parse

            _resolved_hosts.pop(urllib.parse.urlsplit(track_file(self.current)).hostname or "", None)  # afresh
            self._load(index, record=False)
            self._stream_retries = retries

    @Slot(str, str)
    def setStreamInfo(self, artist, title):
        """What a station says is playing now (from its stream titles). It becomes the current entry's artist
        and title, with the station's name kept as the album, so everything that shows the playing song
        (the bar, Now Playing, the tray, media keys, Discord, scrobbling) follows the radio."""
        if not self.hasTrack or track_kind(self.current) != "station":
            return
        entry = self._queue[self._index]
        station = entry.get("station") or entry.get("album") or entry.get("title", "")
        new_title = title or station
        if entry.get("title") == new_title and entry.get("artist", "") == artist:
            return
        entry.update(title=new_title, artist=artist, station=station, album=station,
                     stream_title=f"{artist} - {title}" if artist else title)
        self._listened, self._play_counted = 0, False
        self._model.set_items(self._queue)
        self.trackChanged.emit()

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
        self._host_wait += 1
        self._reap_timer.stop()
        self._fade_timer.stop()
        self._handoff_timer.stop()
        self._visualizer_generation += 1
        self._visualizer_enabled = False
        if self._visualizer_pool is not None:
            self._visualizer_pool.shutdown(wait=True, cancel_futures=True)
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
            "position": self._voice.position() if self.hasTrack else 0,
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
                if isinstance(t, dict) and isinstance(t.get("path"), str)
                and (is_url(t["path"]) or remote.is_remote(t["path"]) or os.path.isfile(track_file(t)))
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
            keep = [i for i, t in enumerate(old) if isinstance(t, dict)
                    and (is_url(t.get("path")) or remote.is_remote(t.get("path")) or os.path.isfile(track_file(t)))]
            if index in keep:
                index = keep.index(index)
            else:  # the song that was playing is gone: start the one after it from the beginning
                index, pos = min(sum(1 for i in keep if i < index), len(queue) - 1), 0
        else:
            index, pos = 0, 0
        self._queue = queue
        self._shuffle = shuffle
        self._repeat = repeat if repeat in (0, 1, 2) else 0
        self._sync_queue()
        self.shuffleChanged.emit()
        self.repeatChanged.emit()
        self._load(index, autoplay=False, record=False)
        if self._parked:  # a stream, only shown: play connects and picks up where it was
            if pos > 0 and track_kind(self._queue[index]) != "station":
                self._queue[index]["resume_ms"] = int(pos)
            self._restore_pos = 0
        else:
            self._restore_pos = max(pos, 0) if track_kind(self._queue[index]) != "station" else 0
        return True
