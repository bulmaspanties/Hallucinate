"""Windows System Media Transport Controls: the media overlay, lock screen and media keys.

`MediaControls` mirrors the player's state, metadata and timeline into a small backend and turns button presses
back into player actions; it is plain Qt and is tested on every platform with a fake backend. `WinrtBackend`
is the real backend (pywinrt). A desktop app has no CoreWindow, so it borrows the SMTC of a Windows.Media
MediaPlayer whose own command handling is switched off; that MediaPlayer never plays anything."""
import asyncio
import datetime
import logging
import os
import threading

from PySide6.QtCore import QObject, QTimer, Signal, Slot

logger = logging.getLogger(__name__)

TIMELINE_INTERVAL_MS = 5000  # Windows extrapolates the position between updates while playing
BUTTONS = ("play", "pause", "stop", "next", "previous")


class MediaControls(QObject):
    """Keeps a backend in sync with the player. Backend callbacks may arrive on any thread."""

    _button = Signal(str)
    _seek = Signal(int)
    _shuffle = Signal(bool)
    _repeat = Signal(int)

    def __init__(self, player, backend_factory, parent=None):
        super().__init__(parent)
        self._player = player
        self._art_path = None
        self._backend = backend_factory(self)  # receives this object for on_button/on_seek/... callbacks
        self._button.connect(self._handle_button)
        self._seek.connect(lambda ms: self._player.seek(ms))
        self._shuffle.connect(lambda on: self._player.setShuffle(on))
        self._repeat.connect(lambda mode: self._player.setRepeat(mode))
        self._timeline_timer = QTimer(self)
        self._timeline_timer.setInterval(TIMELINE_INTERVAL_MS)
        self._timeline_timer.timeout.connect(self._sync_timeline)
        player.trackChanged.connect(self._sync_track)
        player.stateChanged.connect(self._sync_state)
        player.queueChanged.connect(self._sync_buttons)
        player.durationChanged.connect(self._sync_timeline)
        player.seeked.connect(lambda _ms: self._sync_timeline())
        player.shuffleChanged.connect(self._sync_modes)
        player.repeatChanged.connect(self._sync_modes)
        self._sync_track()
        self._sync_modes()

    # --- called by the backend, from any thread ------------------------------------------------------------
    def on_button(self, name):
        if name in BUTTONS:
            self._button.emit(name)

    def on_seek(self, ms):
        self._seek.emit(max(0, int(ms)))

    def on_shuffle(self, on):
        self._shuffle.emit(bool(on))

    def on_repeat(self, mode):
        self._repeat.emit(int(mode) if mode in (0, 1, 2) else 0)

    # --- player -> backend --------------------------------------------------------------------------------
    @Slot(str)
    def _handle_button(self, name):
        p = self._player
        if name == "play":
            p.play()
        elif name == "pause":
            p.pause()
        elif name == "stop":
            p.stop()
        elif name == "next":
            p.next()
        elif name == "previous":
            p.previous()

    @Slot()
    def _sync_track(self):
        p = self._player
        if p.hasTrack:
            t = p.current
            art = t.get("art") or ""
            if not art and t.get("artUrl", "").startswith("file:"):
                from PySide6.QtCore import QUrl
                art = QUrl(t["artUrl"]).toLocalFile()
            art = os.path.normpath(art) if art else ""  # StorageFile needs native separators on Windows
            self._backend.set_metadata(
                title=t.get("title") or "", artist=t.get("artist") or "", album=t.get("album") or "",
                album_artist=t.get("album_artist") or "", track_number=int(t.get("track_no") or 0),
                art_path=art or None,
            )
        else:
            self._backend.clear_metadata()
        self._sync_state()

    @Slot()
    def _sync_state(self):
        p = self._player
        self._backend.set_status(state=p.state if p.hasTrack else "Closed")
        self._sync_buttons()
        self._sync_timeline()
        if p.playing:
            self._timeline_timer.start()
        else:
            self._timeline_timer.stop()

    @Slot()
    def _sync_buttons(self):
        p = self._player
        self._backend.set_buttons(
            play=p.canPlay, pause=p.canPause, stop=p.hasTrack, next=p.canGoNext, previous=p.canGoPrevious,
        )

    @Slot()
    def _sync_timeline(self):
        p = self._player
        if p.hasTrack:
            self._backend.set_timeline(position_ms=p.position, duration_ms=max(p.duration, 0))

    @Slot()
    def _sync_modes(self):
        self._backend.set_modes(shuffle=self._player.shuffle, repeat=self._player.repeat)

    def shutdown(self):
        self._timeline_timer.stop()
        self._backend.close()


class WinrtBackend:
    """SystemMediaTransportControls through pywinrt (Windows 10 1607 or newer)."""

    def __init__(self, controls):
        from winrt.windows.media import (
            MediaPlaybackAutoRepeatMode,
            MediaPlaybackStatus,
            MediaPlaybackType,
            SystemMediaTransportControlsButton,
            SystemMediaTransportControlsTimelineProperties,
        )
        from winrt.windows.media.playback import MediaPlayer

        self._m = {
            "status": {
                "Playing": MediaPlaybackStatus.PLAYING, "Paused": MediaPlaybackStatus.PAUSED,
                "Stopped": MediaPlaybackStatus.STOPPED, "Closed": MediaPlaybackStatus.CLOSED,
            },
            "repeat": {0: MediaPlaybackAutoRepeatMode.NONE, 1: MediaPlaybackAutoRepeatMode.LIST,
                       2: MediaPlaybackAutoRepeatMode.TRACK},
        }
        self._timeline_cls = SystemMediaTransportControlsTimelineProperties
        self._music = MediaPlaybackType.MUSIC
        self._lock = threading.Lock()
        self._art_generation = 0
        self._media_player = MediaPlayer()
        self._media_player.command_manager.is_enabled = False  # we handle the buttons, not this player
        self.smtc = self._media_player.system_media_transport_controls
        self.smtc.is_enabled = True
        names = {
            SystemMediaTransportControlsButton.PLAY: "play", SystemMediaTransportControlsButton.PAUSE: "pause",
            SystemMediaTransportControlsButton.STOP: "stop", SystemMediaTransportControlsButton.NEXT: "next",
            SystemMediaTransportControlsButton.PREVIOUS: "previous",
        }
        repeat_back = {v: k for k, v in self._m["repeat"].items()}
        self._tokens = [
            (self.smtc.remove_button_pressed,
             self.smtc.add_button_pressed(lambda _s, args: controls.on_button(names.get(args.button, "")))),
            (self.smtc.remove_playback_position_change_requested,
             self.smtc.add_playback_position_change_requested(
                 lambda _s, args: controls.on_seek(args.requested_playback_position.total_seconds() * 1000))),
            (self.smtc.remove_shuffle_enabled_change_requested,
             self.smtc.add_shuffle_enabled_change_requested(
                 lambda _s, args: controls.on_shuffle(args.requested_shuffle_enabled))),
            (self.smtc.remove_auto_repeat_mode_change_requested,
             self.smtc.add_auto_repeat_mode_change_requested(
                 lambda _s, args: controls.on_repeat(repeat_back.get(args.requested_auto_repeat_mode, 0)))),
        ]

    def set_status(self, state):
        self.smtc.playback_status = self._m["status"].get(state, self._m["status"]["Stopped"])

    def set_buttons(self, play, pause, stop, next, previous):  # noqa: A002 - mirrors the SMTC names
        s = self.smtc
        s.is_play_enabled, s.is_pause_enabled, s.is_stop_enabled = play, pause, stop
        s.is_next_enabled, s.is_previous_enabled = next, previous

    def set_modes(self, shuffle, repeat):
        self.smtc.shuffle_enabled = bool(shuffle)
        self.smtc.auto_repeat_mode = self._m["repeat"].get(repeat, self._m["repeat"][0])

    def set_metadata(self, title, artist, album, album_artist, track_number, art_path):
        with self._lock:
            self._art_generation += 1
            generation = self._art_generation
            updater = self.smtc.display_updater
            updater.clear_all()  # also drops the previous track's artwork
            updater.type = self._music
            props = updater.music_properties
            props.title, props.artist, props.album_title, props.album_artist = title, artist, album, album_artist
            props.track_number = max(0, track_number)
            updater.update()
        if art_path:
            # Loading a StorageFile is asynchronous; do it off the GUI thread and drop it if the track changed.
            threading.Thread(target=self._load_art, args=(art_path, generation), daemon=True,
                             name="hallucinate-smtc-art").start()

    def _load_art(self, path, generation):
        try:
            from winrt.windows.storage import StorageFile
            from winrt.windows.storage.streams import RandomAccessStreamReference

            async def load():
                return await StorageFile.get_file_from_path_async(path)

            ref = RandomAccessStreamReference.create_from_file(asyncio.run(load()))
        except Exception as exc:  # noqa: BLE001 - artwork is optional
            logger.debug("SMTC artwork unavailable for %s: %s", path, exc)
            return
        with self._lock:
            if generation == self._art_generation:
                self.smtc.display_updater.thumbnail = ref
                self.smtc.display_updater.update()

    def clear_metadata(self):
        with self._lock:
            self._art_generation += 1
            self.smtc.display_updater.clear_all()
            self.smtc.display_updater.update()

    def set_timeline(self, position_ms, duration_ms):
        timeline = self._timeline_cls()
        end = datetime.timedelta(milliseconds=duration_ms)
        timeline.start_time = timeline.min_seek_time = datetime.timedelta(0)
        timeline.end_time = timeline.max_seek_time = end
        timeline.position = min(datetime.timedelta(milliseconds=max(position_ms, 0)), end)
        self.smtc.update_timeline_properties(timeline)

    def close(self):
        for remove, token in self._tokens:
            try:
                remove(token)
            except Exception:  # noqa: BLE001
                pass
        self._tokens = []
        self.smtc.is_enabled = False
        self._media_player.close()


def create(player, parent=None):
    """MediaControls on Windows, or None when the WinRT bindings are unavailable."""
    try:
        return MediaControls(player, WinrtBackend, parent)
    except Exception as exc:  # noqa: BLE001 - desktop integration is optional
        logger.warning("Windows media controls unavailable: %s", exc)
        return None
