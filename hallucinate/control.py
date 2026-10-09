"""Per-user local IPC for the CLI controls and single-instance window activation."""
import json
import os
import time

from PySide6.QtCore import QObject, Slot
from PySide6.QtNetwork import QLocalServer, QLocalSocket

SERVER_NAME = os.environ.get("HALLUCINATE_CONTROL_SOCKET", "hallucinate-control")
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
