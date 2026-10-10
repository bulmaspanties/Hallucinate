"""Windows media controls: Qt glue with a fake backend everywhere, and the real WinRT backend on Windows."""
import sys
import threading

import pytest
from conftest import wait_for
from PySide6.QtCore import QObject, Signal

from hallucinate.smtc import MediaControls


class FakePlayer(QObject):
    trackChanged = Signal()
    stateChanged = Signal()
    queueChanged = Signal()
    durationChanged = Signal()
    seeked = Signal(int)
    shuffleChanged = Signal()
    repeatChanged = Signal()

    def __init__(self):
        super().__init__()
        self.hasTrack = False
        self.current = {}
        self.state = "Stopped"
        self.playing = False
        self.position = 0
        self.duration = 0
        self.shuffle = False
        self.repeat = 0
        self.canPlay = self.canPause = self.canGoNext = self.canGoPrevious = False
        self.actions = []

    def load(self, track, duration=200_000):
        self.hasTrack, self.current, self.duration = True, track, duration
        self.canPlay = self.canPause = self.canGoNext = True
        self.trackChanged.emit()
        self.queueChanged.emit()

    def play(self):
        self.actions.append("play")
        self.state, self.playing = "Playing", True
        self.stateChanged.emit()

    def pause(self):
        self.actions.append("pause")
        self.state, self.playing = "Paused", False
        self.stateChanged.emit()

    def stop(self):
        self.actions.append("stop")

    def next(self):
        self.actions.append("next")

    def previous(self):
        self.actions.append("previous")

    def seek(self, ms):
        self.actions.append(("seek", ms))

    def setShuffle(self, on):
        self.actions.append(("shuffle", on))

    def setRepeat(self, mode):
        self.actions.append(("repeat", mode))


class FakeBackend:
    def __init__(self, controls):
        self.controls = controls
        self.calls = []
        self.closed = False

    def __getattr__(self, name):
        if name.startswith(("set_", "clear_")):
            return lambda **kw: self.calls.append((name, kw))
        raise AttributeError(name)

    def last(self, name):
        return next((kw for n, kw in reversed(self.calls) if n == name), None)

    def close(self):
        self.closed = True


@pytest.fixture
def setup(qapp):
    player = FakePlayer()
    backends = []
    controls = MediaControls(player, lambda c: backends.append(FakeBackend(c)) or backends[-1])
    yield player, controls, backends[0]
    controls.shutdown()


def test_state_metadata_and_buttons_follow_the_player(setup, tmp_path):
    player, controls, backend = setup
    assert backend.last("clear_metadata") == {}
    assert backend.last("set_status") == {"state": "Closed"}
    art = tmp_path / "cover.jpg"
    player.load({"title": "Blue in Green", "artist": "Miles Davis", "album": "Kind of Blue",
                 "album_artist": "Miles Davis", "track_no": 3, "art": str(art)})
    assert backend.last("set_metadata") == {
        "title": "Blue in Green", "artist": "Miles Davis", "album": "Kind of Blue", "album_artist": "Miles Davis",
        "track_number": 3, "art_path": str(art)}
    assert backend.last("set_buttons") == {"play": True, "pause": True, "stop": True, "next": True,
                                           "previous": False}
    player.play()
    assert backend.last("set_status") == {"state": "Playing"}
    assert controls._timeline_timer.isActive()
    player.position = 61_500
    player.seeked.emit(61_500)
    assert backend.last("set_timeline") == {"position_ms": 61_500, "duration_ms": 200_000}
    player.pause()
    assert backend.last("set_status") == {"state": "Paused"} and not controls._timeline_timer.isActive()
    player.shuffle, player.repeat = True, 2
    player.repeatChanged.emit()
    assert backend.last("set_modes") == {"shuffle": True, "repeat": 2}


def test_art_url_is_used_when_there_is_no_art_path(setup, tmp_path):
    player, _controls, backend = setup
    from PySide6.QtCore import QUrl
    art = tmp_path / "folder.png"
    player.load({"title": "T", "artUrl": QUrl.fromLocalFile(str(art)).toString()})
    assert backend.last("set_metadata")["art_path"] == str(art)
    player.load({"title": "No art", "artUrl": ""})
    assert backend.last("set_metadata")["art_path"] is None


def test_requests_from_other_threads_reach_the_player(setup):
    player, controls, backend = setup
    player.load({"title": "T"})

    def press():  # Windows raises these on its own threads
        for name in ("play", "pause", "next", "previous", "stop", "record"):
            controls.on_button(name)
        controls.on_seek(42_000.7)
        controls.on_seek(-5)
        controls.on_shuffle(True)
        controls.on_repeat(1)
        controls.on_repeat(7)

    thread = threading.Thread(target=press)
    thread.start()
    thread.join()
    expected = ["play", "pause", "next", "previous", "stop", ("seek", 42_000), ("seek", 0), ("shuffle", True),
                ("repeat", 1), ("repeat", 0)]
    assert wait_for(lambda: player.actions == expected), player.actions


def test_shutdown_closes_the_backend(qapp):
    player = FakePlayer()
    made = []
    controls = MediaControls(player, lambda c: made.append(FakeBackend(c)) or made[-1])
    controls.shutdown()
    assert made[0].closed


@pytest.mark.skipif(sys.platform != "win32", reason="Windows only")
def test_winrt_backend_updates_the_system_controls(qapp, tmp_path):
    from winrt.windows.media import MediaPlaybackAutoRepeatMode, MediaPlaybackStatus

    from hallucinate.smtc import WinrtBackend

    class Controls:
        def on_button(self, name):
            pass

    backend = WinrtBackend(Controls())
    try:
        smtc = backend.smtc
        assert smtc.is_enabled
        backend.set_metadata(title="Blue in Green", artist="Miles Davis", album="Kind of Blue",
                             album_artist="Miles Davis", track_number=3, art_path=None)
        props = smtc.display_updater.music_properties
        assert (props.title, props.artist, props.album_title, props.track_number) == (
            "Blue in Green", "Miles Davis", "Kind of Blue", 3)
        backend.set_status("Playing")
        assert smtc.playback_status == MediaPlaybackStatus.PLAYING
        backend.set_buttons(play=True, pause=True, stop=True, next=False, previous=True)
        assert (smtc.is_play_enabled, smtc.is_next_enabled, smtc.is_previous_enabled) == (True, False, True)
        backend.set_modes(shuffle=True, repeat=1)
        assert smtc.shuffle_enabled and smtc.auto_repeat_mode == MediaPlaybackAutoRepeatMode.LIST
        backend.set_timeline(position_ms=30_000, duration_ms=120_000)
        art = tmp_path / "cover.png"
        from PySide6.QtGui import QImage
        image = QImage(64, 64, QImage.Format.Format_RGB32)
        image.fill(0x336699)
        image.save(str(art))
        backend.set_metadata(title="With art", artist="", album="", album_artist="", track_number=0,
                             art_path=str(art))
        assert wait_for(lambda: smtc.display_updater.thumbnail is not None, timeout=10)
        backend.clear_metadata()
    finally:
        backend.close()
