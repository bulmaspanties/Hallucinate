import pytest
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtGui import QIcon

from hallucinate.player import Player
from hallucinate.shell import DesktopShell


class FakeWindow:
    def __init__(self):
        self.visible, self.calls = True, []

    def isVisible(self):
        return self.visible

    def show(self):
        self.visible = True
        self.calls.append("show")

    def hide(self):
        self.visible = False
        self.calls.append("hide")

    def raise_(self):
        self.calls.append("raise")

    def requestActivate(self):
        self.calls.append("activate")


@pytest.fixture
def make_shell(qapp, tmp_path, monkeypatch):
    """Build a shell and destroy its Qt objects when the test ends.

    Patch DesktopShell methods on the class, not the instance: undoing an instance patch stores a bound
    method in the instance dict, creating a reference cycle that the garbage collector later frees at an
    arbitrary point (observed as segfaults in unrelated worker-thread tests)."""
    made = []

    def make():
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        player = Player(session_file=tmp_path / "s.json")
        shell = DesktopShell(qapp, player, QIcon())
        shell._settings.clear()
        win = FakeWindow()
        shell.setWindow(win)
        made.append((shell, player))
        return shell, win, player

    yield make
    for shell, player in made:
        shell.shutdown()
        player.shutdown()
        shell.deleteLater()
        player.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_mini_player_toggle_hides_and_restores_main(make_shell):
    shell, win, player = make_shell()
    shell.toggleMini()
    assert shell.miniOpen and not win.visible
    shell.toggleMini()
    assert not shell.miniOpen and win.visible
    shell.toggleMini()
    shell.showMain()
    assert not shell.miniOpen and win.visible


def test_close_without_tray_quits(make_shell):
    shell, win, player = make_shell()
    quits = []
    shell._app = type("A", (), {"quit": lambda self: quits.append(1), "setQuitOnLastWindowClosed": lambda *a: None})()
    shell.setCloseToTray(True)
    assert shell.handleClose() is False and quits  # no tray available offscreen -> plain quit


def test_close_to_tray_hides_window(make_shell, monkeypatch):
    shell, win, player = make_shell()
    shell.setCloseToTray(True)
    monkeypatch.setattr(DesktopShell, "_tray_visible", lambda self: True)
    assert shell.handleClose() is True and not win.visible
    assert shell.closeToTray


def test_desktop_notifications_are_opt_in_and_skip_initial_track(make_shell, monkeypatch):
    shell, _, player = make_shell()
    shown = []
    monkeypatch.setattr(
        DesktopShell, "_send_notification", lambda self, title, artist: shown.append((title, artist))
    )
    shell._player = type(
        "Playback",
        (),
        {"hasTrack": True, "current": {"title": "New song", "artist": "New artist"}},
    )()

    shell._on_track_changed()
    assert shown == []
    shell.setDesktopNotifications(True)
    shell._on_track_changed()
    assert shown == [("New song", "New artist")]
    shell.setDesktopNotifications(False)
    shell._on_track_changed()
    assert len(shown) == 1


def test_sidebar_and_ambient_motion_preferences_persist(make_shell):
    from PySide6.QtCore import QSettings

    shell, _win, _player = make_shell()
    assert shell.sidebarCollapsed is False and shell.ambientMotion is True
    shell.setSidebarCollapsed(True)
    shell.setAmbientMotion(False)
    assert shell.sidebarCollapsed is True and shell.ambientMotion is False
    stored = QSettings("hallucinate", "hallucinate")
    assert stored.value("ui/sidebarCollapsed", type=bool) is True
    assert stored.value("ui/ambientMotion", type=bool) is False


def test_visualizer_style_and_vinyl_preferences_persist(make_shell):
    from PySide6.QtCore import QSettings

    shell, _win, _player = make_shell()
    assert shell.visualizerStyle == "liquid" and shell.nowPlayingVinyl is False
    shell.setVisualizerStyle("aurora")
    shell.setVisualizerStyle("not-a-style")  # ignored
    shell.setNowPlayingVinyl(True)
    assert shell.visualizerStyle == "aurora" and shell.nowPlayingVinyl is True
    stored = QSettings("hallucinate", "hallucinate")
    assert stored.value("ui/visualizerStyle") == "aurora"
    assert stored.value("ui/nowPlayingVinyl", type=bool) is True
