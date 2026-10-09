import random

from PySide6.QtCore import Property, QObject, QSettings, QTimer, QUrl, Signal, Slot
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer

from .models import TRACK_KEYS, DictModel

REPEAT_OFF, REPEAT_ALL, REPEAT_ONE = 0, 1, 2


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

    def __init__(self, parent=None):
        super().__init__(parent)
        self._queue = []
        self._index = -1
        self._history = []
        self._played = set()
        self._shuffle = False
        self._repeat = REPEAT_OFF
        self._error = ""
        self._error_streak = 0
        self._model = DictModel(TRACK_KEYS, self)

        self._settings = QSettings("musicplayer", "musicplayer")
        self._volume = float(self._settings.value("volume", 0.8))
        self._audio = QAudioOutput(self)
        self._audio.setVolume(self._volume ** 2)
        self._player = QMediaPlayer(self)
        self._player.setAudioOutput(self._audio)
        self._player.playbackStateChanged.connect(lambda *_: self.stateChanged.emit())
        self._player.positionChanged.connect(lambda *_: self.positionChanged.emit())
        self._player.durationChanged.connect(lambda *_: self.durationChanged.emit())
        self._player.mediaStatusChanged.connect(self._on_media_status)
        self._player.errorOccurred.connect(self._on_error)

    # --- properties --------------------------------------------------------
    @Property(bool, notify=stateChanged)
    def playing(self):
        return self._player.playbackState() == QMediaPlayer.PlaybackState.PlayingState

    @Property(str, notify=stateChanged)
    def state(self):
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

    # --- transport ---------------------------------------------------------
    @Slot()
    def play(self):
        if self.hasTrack:
            self._player.play()
        elif self._queue:
            self._load(0)

    @Slot()
    def pause(self):
        self._player.pause()

    @Slot()
    def stop(self):
        self._player.stop()

    @Slot()
    def toggle(self):
        if self.playing:
            self._player.pause()
        else:
            self.play()

    @Slot(int)
    def seek(self, ms):
        self._player.setPosition(max(0, int(ms)))
        self.seeked.emit(int(ms))

    @Slot(int)
    def seekBy(self, delta_ms):
        self.seek(min(self._player.position() + delta_ms, max(self.duration - 1, 0)))

    @Slot(float)
    def setVolume(self, v):
        v = min(max(float(v), 0.0), 1.0)
        self._volume = v
        self._audio.setVolume(v * v)
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
        self.shuffleChanged.emit()

    @Slot()
    def cycleRepeat(self):
        self.setRepeat((self._repeat + 1) % 3)

    @Slot(int)
    def setRepeat(self, mode):
        self._repeat = mode
        self.repeatChanged.emit()

    @Slot()
    def next(self):
        self._advance(auto=False)

    @Slot()
    def previous(self):
        if self._player.position() > 3000 or not self.hasTrack:
            self.seek(0)
        elif self._history:
            self._load(self._history.pop(), record=False)
        elif self._index > 0:
            self._load(self._index - 1, record=False)
        else:
            self.seek(0)

    # --- queue -------------------------------------------------------------
    @Slot("QVariantList", int)
    def playList(self, tracks, index=0):
        """Replace the queue with `tracks` and start playing at `index`."""
        self._queue = [dict(t) for t in tracks]
        self._history.clear()
        self._played.clear()
        self._sync_queue()
        if self._queue:
            self._load(min(max(index, 0), len(self._queue) - 1), record=False)

    @Slot("QVariantMap")
    def playTrack(self, track):
        self.playList([track], 0)

    @Slot("QVariantMap")
    def enqueue(self, track):
        self._queue.append(dict(track))
        self._sync_queue()
        if not self.hasTrack:
            self._load(len(self._queue) - 1, autoplay=False)

    @Slot("QVariantMap")
    def playNext(self, track):
        self._queue.insert(self._index + 1, dict(track))
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
        self._history.clear()
        if i == self._index:
            self._player.stop()
            if self._queue:
                self._load(min(i, len(self._queue) - 1), record=False)
            else:
                self._index = -1
                self._player.setSource(QUrl())
                self.trackChanged.emit()
        elif i < self._index:
            self._index -= 1
            self.trackChanged.emit()
        self._played = {self._index}
        self._sync_queue()

    @Slot()
    def clearQueue(self):
        self._player.stop()
        self._player.setSource(QUrl())
        self._queue.clear()
        self._history.clear()
        self._played.clear()
        self._index = -1
        self._sync_queue()
        self.trackChanged.emit()

    # --- internals ---------------------------------------------------------
    def _sync_queue(self):
        self._model.set_items(self._queue)
        self.queueChanged.emit()

    def _load(self, i, autoplay=True, record=True):
        if record and self.hasTrack and i != self._index:
            self._history.append(self._index)
        self._index = i
        self._played.add(i)
        self._set_error("")
        self._player.setSource(QUrl.fromLocalFile(self._queue[i]["path"]))
        self.trackChanged.emit()
        self.durationChanged.emit()
        if autoplay:
            self._player.play()

    def _advance(self, auto):
        n = len(self._queue)
        if n == 0:
            return
        if auto and self._repeat == REPEAT_ONE:
            self.seek(0)
            self._player.play()
            return
        if self._shuffle:
            choices = [i for i in range(n) if i not in self._played]
            if not choices:
                if self._repeat == REPEAT_OFF and auto:
                    self._player.stop()
                    return
                self._played = {self._index}
                choices = [i for i in range(n) if i != self._index] or [self._index]
            nxt = random.choice(choices)
        else:
            nxt = self._index + 1
            if nxt >= n:
                if self._repeat == REPEAT_OFF and auto:
                    self._player.stop()
                    return
                nxt = 0
        self._load(nxt)

    def _on_media_status(self, status):
        S = QMediaPlayer.MediaStatus
        if status == S.EndOfMedia:
            self._advance(auto=True)
        elif status in (S.LoadedMedia, S.BufferedMedia):
            self._error_streak = 0

    def _on_error(self, _err, message):
        self._set_error(message or "Playback error")
        self._error_streak += 1
        if self._error_streak < len(self._queue):
            QTimer.singleShot(300, lambda: self._advance(auto=True))

    def _set_error(self, text):
        if text != self._error:
            self._error = text
            self.errorChanged.emit()
