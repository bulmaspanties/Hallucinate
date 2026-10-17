"""Per-user local IPC for the CLI controls and single-instance window activation."""
import json
import os
import time

from PySide6.QtCore import QObject, Slot
from PySide6.QtNetwork import QLocalServer, QLocalSocket


def default_server_name(env=None, platform=None):
    """Where the control socket lives. A bare name lands in a shared place (/tmp on Linux, the machine-wide pipe
    namespace on Windows), where another user could take it first and stop Hallucinate starting; so it goes in
    the user's private runtime folder when there is one, and is named after the user otherwise."""
    import getpass
    import sys

    env = os.environ if env is None else env
    platform = platform or sys.platform
    if env.get("HALLUCINATE_CONTROL_SOCKET"):
        return env["HALLUCINATE_CONTROL_SOCKET"]
    runtime = env.get("XDG_RUNTIME_DIR", "")
    if platform.startswith("linux") and runtime and os.path.isdir(runtime) and not env.get("FLATPAK_ID"):
        return os.path.join(runtime, "hallucinate-control")
    if not platform.startswith(("win", "darwin")) and not env.get("FLATPAK_ID") and hasattr(os, "getuid"):
        # No runtime folder (a bare X session, ssh): a folder of our own in the cache, closed to other users.
        # macOS's temp folder and the Flatpak's /tmp are already private; Windows has no folders for pipes.
        home = env.get("HOME") or os.path.expanduser("~")
        folder = os.path.join(env.get("XDG_CACHE_HOME") or os.path.join(home, ".cache"), "hallucinate")
        path = os.path.join(folder, "control")
        if len(path) < 100:  # a Unix socket's path has to fit in 108 bytes
            try:
                os.makedirs(folder, mode=0o700, exist_ok=True)
                st = os.lstat(folder)
                if os.path.isdir(folder) and not os.path.islink(folder) and st.st_uid == os.getuid():
                    os.chmod(folder, 0o700)
                    return path
            except OSError:
                pass
    try:
        user = getpass.getuser()
    except Exception:  # noqa: BLE001 - no login name: fall back to the uid where there is one
        user = str(os.getuid()) if hasattr(os, "getuid") else "user"
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in user)[:40]
    if platform.startswith("win"):
        # Pipe names are machine-wide and a user name is easy to guess: add a random part kept in your own
        # app-data folder, which other accounts can't read, so they can't take the name before you do.
        secret = _private_token(env)
        if secret:
            return f"hallucinate-control-{safe}-{secret}"
    return f"hallucinate-control-{safe}"


def _private_token(env):
    """A random name part kept in the user's own app-data folder (made once), or "" if it can't be kept."""
    import secrets

    base = env.get("APPDATA") or os.path.join(os.path.expanduser("~"), "AppData", "Roaming")
    folder = os.path.join(base, "hallucinate")
    path = os.path.join(folder, "control-name")
    try:
        with open(path, encoding="ascii") as fh:
            token = fh.read().strip()
        if len(token) == 16 and all(c in "0123456789abcdef" for c in token):
            return token
    except (OSError, UnicodeDecodeError):
        pass
    token = secrets.token_hex(8)
    try:
        os.makedirs(folder, exist_ok=True)
        tmp = f"{path}.{os.getpid()}.tmp"
        with open(tmp, "w", encoding="ascii") as fh:
            fh.write(token)
        os.replace(tmp, path)
        with open(path, encoding="ascii") as fh:
            return fh.read().strip() or token  # two first starts at once: both end up with the one kept
    except (OSError, UnicodeDecodeError):
        return ""


SERVER_NAME = default_server_name()
CONNECT_TIMEOUT_MS = 300
RESPONSE_TIMEOUT_MS = 1500


def send_control(command, timeout_ms=CONNECT_TIMEOUT_MS, server_name=SERVER_NAME, **payload):
    """Send one newline-delimited JSON request; return None when no instance responds."""
    socket = QLocalSocket()
    socket.connectToServer(server_name)
    if not socket.waitForConnected(timeout_ms):
        return None
    try:
        request = {"command": command, **payload}
        socket.write(json.dumps(request).encode("utf-8") + b"\n")
        if not socket.waitForBytesWritten(RESPONSE_TIMEOUT_MS):
            return {"ok": False, "error": "Timed out sending the control request"}
        deadline = time.monotonic() + RESPONSE_TIMEOUT_MS / 1000
        response = bytearray()
        while b"\n" not in response:
            remaining = int((deadline - time.monotonic()) * 1000)
            if remaining <= 0 or not socket.waitForReadyRead(remaining):
                return {"ok": False, "error": "The running instance did not respond"}
            response.extend(bytes(socket.readAll()))
        raw = response.partition(b"\n")[0]
        return json.loads(raw.decode("utf-8"))
    except (IndexError, UnicodeDecodeError, json.JSONDecodeError):
        return {"ok": False, "error": "The running instance sent an invalid response"}
    finally:
        socket.disconnectFromServer()


class ControlServer(QObject):
    def __init__(self, player=None, raise_callback=None, parent=None, server_name=SERVER_NAME):
        super().__init__(parent)
        self._player = player
        self._raise_callback = raise_callback
        self._library = None
        self._pending_folders = []
        self._name = server_name
        self._server = QLocalServer(self)
        self._server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
        self._buffers = {}
        self._server.newConnection.connect(self._accept_connections)

    def listen(self):
        if self._server.listen(self._name):
            return True
        if send_control("raise", server_name=self._name) is not None:
            return False
        QLocalServer.removeServer(self._name)
        return self._server.listen(self._name)

    def setPlayer(self, player):
        self._player = player

    def setLibrary(self, library):
        self._library = library
        for folder in self._pending_folders:
            library.addFolder(folder)
        self._pending_folders.clear()

    def setRaiseCallback(self, callback):
        self._raise_callback = callback

    def close(self):
        self._server.close()
        QLocalServer.removeServer(self._name)

    @Slot()
    def _accept_connections(self):
        while self._server.hasPendingConnections():
            socket = self._server.nextPendingConnection()
            self._buffers[socket] = bytearray()
            socket.readyRead.connect(lambda s=socket: self._handle_request(s))
            socket.disconnected.connect(lambda s=socket: self._forget_socket(s))
            if socket.bytesAvailable():
                self._handle_request(socket)

    def _forget_socket(self, socket):
        self._buffers.pop(socket, None)

    def _handle_request(self, socket):
        buffer = self._buffers.get(socket)
        if buffer is None:
            return
        buffer.extend(bytes(socket.readAll()))
        if len(buffer) > 16384:
            socket.write(b'{"ok":false,"error":"Control request too large"}\n')
            socket.disconnectFromServer()
            return
        if b"\n" not in buffer:
            return
        line, _, _remaining = buffer.partition(b"\n")
        try:
            request = json.loads(line.decode("utf-8"))
            if not isinstance(request, dict):
                raise ValueError("request must be an object")
            response = self._dispatch(request.get("command"), request)
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
            response = {"ok": False, "error": "Invalid control request"}
        socket.write(json.dumps(response, ensure_ascii=False).encode("utf-8") + b"\n")
        socket.flush()
        socket.disconnectFromServer()

    def _dispatch(self, command, request):
        if command == "raise":
            if self._raise_callback is not None:
                self._raise_callback()
            return {"ok": True}
        if command == "add-folders":
            folders = request.get("folders")
            if (
                not isinstance(folders, list)
                or len(folders) > 100
                or not all(isinstance(folder, str) for folder in folders)
            ):
                return {"ok": False, "error": "Invalid music-folder request"}
            if self._library is None:
                self._pending_folders.extend(folders)
            else:
                for folder in folders:
                    self._library.addFolder(folder)
            if self._raise_callback is not None:
                self._raise_callback()
            return {"ok": True}
        player = self._player
        if player is None:
            return {"ok": False, "error": "Hallucinate is still starting"}
        if command == "next":
            player.next()
        elif command == "prev":
            player.previous()
        elif command == "play-pause":
            player.toggle()
        elif command == "status":
            current = player.current if player.hasTrack else {}
            return {
                "ok": True,
                "status": {
                    "state": player.state,
                    "current": {
                        key: current.get(key, "")
                        for key in ("title", "artist", "album", "path")
                    } if current else None,
                    "positionMs": player.position,
                    "durationMs": player.duration,
                    "queueLength": player.queueLength,
                },
            }
        else:
            return {"ok": False, "error": "Unknown command"}
        return {"ok": True}
