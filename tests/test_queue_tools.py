"""Output device selection, saving the queue as a playlist and dropping files to play."""
from conftest import make_mp3, wait_for
from PySide6.QtCore import QObject, QSettings, QUrl, Signal

from hallucinate.library import Library, resolve_dropped
from hallucinate.player import Player, device_key, pick_output_device
from hallucinate.userlib import UserLibrary


class FakeDevice:
    def __init__(self, raw, name):
        self._raw = raw
        self._name = name

    def id(self):
        return self._raw

    def description(self):
        return self._name


class FakePlayer(QObject):
    played = Signal(object)

    def __init__(self, queue=()):
        super().__init__()
        self.queue = list(queue)
        self.calls = []

    def playList(self, tracks, index):
        self.calls.append(("play", [t["path"] for t in tracks], index))

    def enqueueAll(self, tracks):
        self.calls.append(("enqueue", [t["path"] for t in tracks]))


def test_pick_output_device_matches_by_key():
    usb = FakeDevice(b"alsa_output.usb", "USB DAC")
    hdmi = FakeDevice(b"alsa_output.hdmi", "HDMI")
    assert device_key(usb) == b"alsa_output.usb".hex()
    assert pick_output_device([usb, hdmi], device_key(hdmi)) is hdmi
    assert pick_output_device([usb, hdmi], "") is None
    assert pick_output_device([usb, hdmi], "00ff") is None


def test_output_device_choice_is_persisted_and_survives_unplugging(qapp):
    settings = QSettings("hallucinate", "hallucinate")
    settings.setValue("audio/outputDevice", "00ff")
    settings.setValue("audio/outputDeviceName", "USB DAC")
    player = Player()
    try:
        devices = player.outputDevices
        assert devices[0]["key"] == "" and devices[0]["name"].startswith("System default")
        # The saved device is not connected: keep the choice, show it, and play on the default meanwhile.
        assert player.outputDevice == "00ff"
        assert devices[-1] == {"key": "00ff", "name": "USB DAC (not connected)"}
        default = player._output_audio_device()
        assert all(v.audio.device() == default for v in player._voices)
        player.setOutputDevice("abcd")  # unknown and not the saved one: ignored
        assert player.outputDevice == "00ff"
        player.setOutputDevice("")
        assert player.outputDevice == ""
        assert settings.value("audio/outputDevice") == ""
        assert [d["key"] for d in player.outputDevices].count("00ff") == 0
    finally:
        player.shutdown()
        settings.remove("audio")


def test_save_queue_as_playlist(qapp, tmp_path, db, scan, music):
    scan(music)
    paths = [r["path"] for r in db._rows("SELECT path FROM tracks ORDER BY path DESC")]
    player = FakePlayer([{"path": p} for p in paths])
    ul = UserLibrary(tmp_path / "lib.db", player)
    try:
        assert ul.saveQueueAsPlaylist("   ") == -1
        pid = ul.saveQueueAsPlaylist(" Queue snapshot ")
        assert pid >= 0
        ul.openPlaylist(pid)
        assert wait_for(lambda: ul.playlistTracks.count == len(paths))
        assert [ul.playlistTracks.get(i)["path"] for i in range(len(paths))] == paths
        assert wait_for(lambda: any(p["name"] == "Queue snapshot" for p in ul.playlists.items()))
        player.queue = []
        assert ul.saveQueueAsPlaylist("Empty") == -1
    finally:
        ul.shutdown()


def test_resolve_dropped_orders_folders_and_reads_unknown_files(tmp_path, db, scan, music):
    scan(music)
    outside = tmp_path / "Downloads" / "Album"
    (outside / "CD2").mkdir(parents=True)
    make_mp3(outside / "b.mp3", "Second", "X", "Drop", track="2")
    make_mp3(outside / "a.mp3", "Third", "X", "Drop", track="3")
    make_mp3(outside / "z.mp3", "First", "X", "Drop", track="1")
    make_mp3(outside / "CD2" / "01.mp3", "Disc two", "X", "Drop", track="1")
    (outside / "cover.jpg").write_bytes(b"jpg")
    (outside / "notes.txt").write_text("hi")
    single = music / "Aurora Vale" / "Northern Lights" / "02.mp3"

    tracks = resolve_dropped(db, [str(single), str(outside), str(tmp_path / "missing.mp3")])
    assert [t["title"] for t in tracks] == ["Midnight Rain", "First", "Second", "Third", "Disc two"]
    assert tracks[0]["id"] > 0  # library entry reused
    assert tracks[1]["id"] == -1 and tracks[1]["artUrl"].endswith("cover.jpg")
    assert all(t["durText"] for t in tracks)
    assert len(resolve_dropped(db, [str(outside)], limit=2)) == 2


def test_play_dropped_urls(qapp, tmp_path, music):
    lib = Library(tmp_path / "drop.db", tmp_path / "art")
    player = FakePlayer()
    lib.setPlayer(player)
    try:
        a = music / "Aurora Vale" / "Northern Lights"
        lib.playDropped([QUrl.fromLocalFile(str(a)), "https://example.com/x.mp3"], False)
        assert wait_for(lambda: player.calls)
        assert player.calls[0] == ("play", [str(a / "01.mp3"), str(a / "02.mp3")], 0)
        lib.playDropped([QUrl.fromLocalFile(str(music / "loose.mp3")).toString()], True)
        assert wait_for(lambda: len(player.calls) == 2)
        assert player.calls[1] == ("enqueue", [str(music / "loose.mp3")])
    finally:
        lib.shutdown()
