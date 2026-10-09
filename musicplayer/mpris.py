"""MPRIS2 (org.mpris.MediaPlayer2) service so media keys and desktop widgets work."""
from PySide6.QtCore import ClassInfo, Property, QObject, QUrl, Slot
from PySide6.QtDBus import (QDBusAbstractAdaptor, QDBusConnection, QDBusMessage, QDBusObjectPath)

SERVICE = "org.mpris.MediaPlayer2.musicplayer"
PATH = "/org/mpris/MediaPlayer2"
ROOT_IFACE = "org.mpris.MediaPlayer2"
PLAYER_IFACE = "org.mpris.MediaPlayer2.Player"
LOOP = {0: "None", 1: "Playlist", 2: "Track"}
LOOP_REV = {v: k for k, v in LOOP.items()}


@ClassInfo(**{"D-Bus Interface": ROOT_IFACE})
class _RootAdaptor(QDBusAbstractAdaptor):
    def __init__(self, parent, raise_cb, quit_cb):
        super().__init__(parent)
        self._raise, self._quit = raise_cb, quit_cb

    CanQuit = Property(bool, lambda self: True, constant=True)
    CanRaise = Property(bool, lambda self: True, constant=True)
    HasTrackList = Property(bool, lambda self: False, constant=True)
    Identity = Property(str, lambda self: "Music Player", constant=True)
    DesktopEntry = Property(str, lambda self: "musicplayer", constant=True)
    SupportedUriSchemes = Property("QStringList", lambda self: ["file"], constant=True)
    SupportedMimeTypes = Property(
        "QStringList",
        lambda self: ["audio/mpeg", "audio/flac", "audio/ogg", "audio/x-wav", "audio/mp4"],
        constant=True,
    )

    @Slot()
    def Raise(self):
        self._raise()

    @Slot()
    def Quit(self):
        self._quit()


@ClassInfo(**{"D-Bus Interface": PLAYER_IFACE})
class _PlayerAdaptor(QDBusAbstractAdaptor):
    def __init__(self, parent, player):
        super().__init__(parent)
        self.p = player

    def _get_status(self):
        return self.p.state

    def _get_loop(self):
        return LOOP[self.p.repeat]

    def _set_loop(self, v):
        self.p.setRepeat(LOOP_REV.get(v, 0))

    def _get_shuffle(self):
        return self.p.shuffle

    def _set_shuffle(self, v):
        self.p.setShuffle(bool(v))

    def _get_volume(self):
        return self.p.volume

    def _set_volume(self, v):
        self.p.setVolume(float(v))

    def _get_meta(self):
        return metadata(self.p)

    def _get_pos(self):
        return int(self.p.position) * 1000

    PlaybackStatus = Property(str, _get_status)
    LoopStatus = Property(str, _get_loop, _set_loop)
    Rate = Property(float, lambda self: 1.0)
    MinimumRate = Property(float, lambda self: 1.0)
    MaximumRate = Property(float, lambda self: 1.0)
    Shuffle = Property(bool, _get_shuffle, _set_shuffle)
    Metadata = Property("QVariantMap", _get_meta)
    Volume = Property(float, _get_volume, _set_volume)
    Position = Property("qlonglong", _get_pos)
    CanGoNext = Property(bool, lambda self: True)
    CanGoPrevious = Property(bool, lambda self: True)
    CanPlay = Property(bool, lambda self: True)
    CanPause = Property(bool, lambda self: True)
    CanSeek = Property(bool, lambda self: True)
    CanControl = Property(bool, lambda self: True)

    @Slot()
    def Next(self):
        self.p.next()

    @Slot()
    def Previous(self):
        self.p.previous()

    @Slot()
    def Pause(self):
        self.p.pause()

    @Slot()
    def PlayPause(self):
        self.p.toggle()

    @Slot()
    def Stop(self):
        self.p.stop()

    @Slot()
    def Play(self):
        self.p.play()

    @Slot("qlonglong")
    def Seek(self, offset_us):
        self.p.seekBy(int(offset_us) // 1000)

    @Slot(QDBusObjectPath, "qlonglong")
    def SetPosition(self, _track, pos_us):
        self.p.seek(int(pos_us) // 1000)


def metadata(player) -> dict:
    t = player.current
    if not t:
        return {"mpris:trackid": QDBusObjectPath("/org/mpris/MediaPlayer2/TrackList/NoTrack")}
    md = {
        "mpris:trackid": QDBusObjectPath(f"/org/musicplayer/track/{t.get('id', 0)}"),
        "mpris:length": int(float(t.get("duration", 0)) * 1_000_000),
        "xesam:title": t.get("title", ""),
        "xesam:artist": [t.get("artist", "")],
        "xesam:album": t.get("album", ""),
        "xesam:url": QUrl.fromLocalFile(t.get("path", "")).toString(),
    }
    if t.get("artUrl"):
        md["mpris:artUrl"] = t["artUrl"]
    return md


class MprisService(QObject):
    def __init__(self, player, raise_cb, quit_cb, parent=None):
        super().__init__(parent)
        self.player = player
        self.ok = False
        self._root = _RootAdaptor(self, raise_cb, quit_cb)
        self._pl = _PlayerAdaptor(self, player)
        bus = QDBusConnection.sessionBus()
        if not bus.isConnected():
            return
        if not bus.registerService(SERVICE):
            return
        self.ok = bus.registerObject(PATH, self, QDBusConnection.RegisterOption.ExportAdaptors)
        if self.ok:
            player.stateChanged.connect(lambda: self._notify("PlaybackStatus"))
            player.trackChanged.connect(lambda: self._notify("Metadata"))
            player.shuffleChanged.connect(lambda: self._notify("Shuffle"))
            player.repeatChanged.connect(lambda: self._notify("LoopStatus"))
            player.volumeChanged.connect(lambda: self._notify("Volume"))

    def _notify(self, name):
        getter = {
            "PlaybackStatus": self._pl._get_status,
            "Metadata": self._pl._get_meta,
            "Shuffle": self._pl._get_shuffle,
            "LoopStatus": self._pl._get_loop,
            "Volume": self._pl._get_volume,
        }[name]
        msg = QDBusMessage.createSignal(PATH, "org.freedesktop.DBus.Properties", "PropertiesChanged")
        msg.setArguments([PLAYER_IFACE, {name: getter()}, []])
        QDBusConnection.sessionBus().send(msg)
