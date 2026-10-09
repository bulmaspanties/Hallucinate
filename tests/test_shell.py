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


def make_shell(qapp, tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    player = Player(session_file=tmp_path / "s.json")
    shell = DesktopShell(qapp, player, QIcon())
    shell._settings.clear()
    win = FakeWindow()
    shell.setWindow(win)
    return shell, win, player


def test_mini_player_toggle_hides_and_restores_main(qapp, tmp_path, monkeypatch):
    shell, win, player = make_shell(qapp, tmp_path, monkeypatch)
    shell.toggleMini()
    assert shell.miniOpen and not win.visible
    shell.toggleMini()
    assert not shell.miniOpen and win.visible
    shell.toggleMini()
    shell.showMain()
    assert not shell.miniOpen and win.visible
    player.shutdown()


def test_close_without_tray_quits(qapp, tmp_path, monkeypatch):
    shell, win, player = make_shell(qapp, tmp_path, monkeypatch)
    quits = []
    shell._app = type("A", (), {"quit": lambda self: quits.append(1), "setQuitOnLastWindowClosed": lambda *a: None})()
    shell.setCloseToTray(True)
    assert shell.handleClose() is False and quits  # no tray available offscreen -> plain quit
    player.shutdown()


def test_close_to_tray_hides_window(qapp, tmp_path, monkeypatch):
    shell, win, player = make_shell(qapp, tmp_path, monkeypatch)
    shell.setCloseToTray(True)
    monkeypatch.setattr(shell, "_tray_visible", lambda: True)
    assert shell.handleClose() is True and not win.visible
    assert shell.closeToTray
    player.shutdown()
