"""Desktop integration: system tray icon, close-to-tray and the mini player window."""
from PySide6.QtCore import Property, QObject, QSettings, Signal, Slot
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import QMenu, QSystemTrayIcon


class DesktopShell(QObject):
    miniChanged = Signal()
    settingsChanged = Signal()

    def __init__(self, app, player, icon: QIcon, parent=None):
        super().__init__(parent)
        self._app = app
        self._player = player
        self._window = None
        self._mini = False
        self._settings = QSettings("musicplayer", "musicplayer")
        self._tray_pref = self._settings.value("shell/tray", True, bool)
        self._close_to_tray = self._settings.value("shell/closeToTray", False, bool)
        self._tray = None
        self._menu = None
        self._icon = icon
        self._build_tray()
        player.stateChanged.connect(self._refresh)
        player.trackChanged.connect(self._refresh)

    # --- tray -------------------------------------------------------------------------
    def _build_tray(self):
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        self._tray = QSystemTrayIcon(self._icon, self)
        menu = QMenu()
        self._act_toggle = QAction("Play", menu)
        self._act_toggle.triggered.connect(self._player.toggle)
        prev, nxt = QAction("Previous", menu), QAction("Next", menu)
        prev.triggered.connect(self._player.previous)
        nxt.triggered.connect(self._player.next)
        show, mini, quit_ = QAction("Show Music Player", menu), QAction("Mini player", menu), QAction("Quit", menu)
        show.triggered.connect(self.showMain)
        mini.triggered.connect(self.toggleMini)
        quit_.triggered.connect(self._app.quit)
        for a in (show, mini, None, self._act_toggle, prev, nxt, None, quit_):
            menu.addSeparator() if a is None else menu.addAction(a)
        self._menu = menu  # keep alive
        self._tray.setContextMenu(menu)
        self._tray.activated.connect(self._on_activated)
        self._tray.setVisible(self._tray_pref)
        self._refresh()
        self._sync_quit_policy()

    def _on_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            if self._window is not None and self._window.isVisible() and not self._mini:
                self._window.hide()
            else:
                self.showMain()
        elif reason == QSystemTrayIcon.ActivationReason.MiddleClick:
            self._player.toggle()

    def _refresh(self):
        if self._tray is None:
            return
        self._act_toggle.setText("Pause" if self._player.playing else "Play")
        cur = self._player.current if self._player.hasTrack else {}
        self._tray.setToolTip(f"{cur['title']} — {cur['artist']}" if cur else "Music Player")

    def _tray_visible(self):
        return self._tray is not None and self._tray.isVisible()

    def _sync_quit_policy(self):
        self._app.setQuitOnLastWindowClosed(not self._tray_visible())

    def setWindow(self, window):
        self._window = window

    # --- properties ---------------------------------------------------------------------
    @Property(bool, constant=True)
    def trayAvailable(self):
        return self._tray is not None

    @Property(bool, notify=settingsChanged)
    def trayEnabled(self):
        return self._tray_pref

    @Property(bool, notify=settingsChanged)
    def closeToTray(self):
        return self._close_to_tray

    @Property(bool, notify=miniChanged)
    def miniOpen(self):
        return self._mini

    @Slot(bool)
    def setTrayEnabled(self, on):
        self._tray_pref = on
        self._settings.setValue("shell/tray", on)
        if self._tray is not None:
            self._tray.setVisible(on)
        self._sync_quit_policy()
        self.settingsChanged.emit()

    @Slot(bool)
    def setCloseToTray(self, on):
        self._close_to_tray = on
        self._settings.setValue("shell/closeToTray", on)
        self.settingsChanged.emit()

    # --- windows --------------------------------------------------------------------------
    @Slot()
    def showMain(self):
        if self._mini:
            self._mini = False
            self.miniChanged.emit()
        if self._window is not None:
            self._window.show()
            self._window.raise_()
            self._window.requestActivate()

    @Slot()
    def toggleMini(self):
        if self._mini:
            self.showMain()
            return
        self._mini = True
        self.miniChanged.emit()
        if self._window is not None:
            self._window.hide()

    @Slot(result=bool)
    def handleClose(self):
        """Called when the main window is closed; True when the window should only be hidden."""
        if self._close_to_tray and self._tray_visible():
            if self._window is not None:
                self._window.hide()
            return True
        self._app.quit()
        return False

    @Slot()
    def quit(self):
        self._app.quit()

    def shutdown(self):
        if self._tray is not None:
            self._tray.hide()

