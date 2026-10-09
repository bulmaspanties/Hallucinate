import json
import os
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

from PySide6.QtCore import QEventLoop, QTimer

from hallucinate.control import ControlServer, send_control


class FakePlayer:
    def __init__(self):
        self.hasTrack = True
        self.current = {
            "title": "Café",
            "artist": "Aurora",
            "album": "Night",
            "path": "/music/cafe.flac",
        }
        self.state = "Playing"
        self.position = 1250
        self.duration = 30000
        self.queueLength = 4
        self.calls = []

    def next(self):
        self.calls.append("next")

    def previous(self):
        self.calls.append("prev")

    def toggle(self):
        self.calls.append("play-pause")


def test_local_control_commands_and_status(qapp):
    name = "hallucinate-test-" + uuid4().hex
    player = FakePlayer()
    raised = threading.Event()
    server = ControlServer(player, raised.set, server_name=name)
    assert server.listen()
    folders = []
    server.setLibrary(type("MusicLibrary", (), {"addFolder": lambda self, path: folders.append(path)})())

    def request(command, **payload):
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(
                subprocess.run,
                [
                    sys.executable,
                    "-c",
                    "import json,sys; from hallucinate.control import send_control; "
                    "print(json.dumps(send_control(sys.argv[1], 1000, sys.argv[2], "
                    "**json.loads(sys.argv[3]))))",
                    command,
                    name,
                    json.dumps(payload),
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            loop = QEventLoop()
            timer = QTimer()
            timer.setInterval(5)
            timer.timeout.connect(lambda: loop.quit() if future.done() else None)
            QTimer.singleShot(3000, loop.quit)
            timer.start()
            loop.exec()
            timer.stop()
            assert future.done()
            return json.loads(future.result().stdout)

    try:
        for command in ("next", "prev", "play-pause"):
            assert request(command) == {"ok": True}
        assert player.calls == ["next", "prev", "play-pause"]
        status = request("status")
        assert status == {
            "ok": True,
            "status": {
                "state": "Playing",
                "current": {
                    "title": "Café",
                    "artist": "Aurora",
                    "album": "Night",
                    "path": "/music/cafe.flac",
                },
                "positionMs": 1250,
                "durationMs": 30000,
                "queueLength": 4,
            },
        }
        assert request("raise") == {"ok": True}
        assert raised.is_set()
        assert request("add-folders", folders=["/music/One", "/music/Two"]) == {"ok": True}
        assert folders == ["/music/One", "/music/Two"]
        assert request("unknown") == {"ok": False, "error": "Unknown command"}
    finally:
        server.close()


def test_control_client_returns_none_when_no_instance():
    result = send_control("status", timeout_ms=25, server_name="hallucinate-no-server-" + uuid4().hex)
    assert result is None


def test_status_cli_outputs_json(monkeypatch, capsys):
    from hallucinate import app

    monkeypatch.setattr(
        app,
        "send_control",
        lambda command: {"ok": True, "status": {"state": "Paused", "current": None}},
    )
    assert app.main(["--status"]) == 0
    assert '"state": "Paused"' in capsys.readouterr().out


def test_control_cli_reports_missing_instance(monkeypatch, capsys):
    from hallucinate import app

    monkeypatch.setattr(app, "send_control", lambda _command: None)
    assert app.main(["--next"]) == 1
    assert "Hallucinate is not running" in capsys.readouterr().err


def test_cli_controls_live_app_process(tmp_path):
    env = dict(
        os.environ,
        QT_QPA_PLATFORM="offscreen",
        HOME=str(tmp_path),
        XDG_CONFIG_HOME=str(tmp_path / "config"),
        XDG_DATA_HOME=str(tmp_path / "data-home"),
        XDG_CACHE_HOME=str(tmp_path / "cache"),
        HALLUCINATE_DATA=str(tmp_path / "data"),
        HALLUCINATE_DISABLE_LEGACY_MIGRATION="1",
        HALLUCINATE_CONTROL_SOCKET="hallucinate-test-" + uuid4().hex,
    )
    app = subprocess.Popen(
        [sys.executable, "-m", "hallucinate", "--quit-after", "15000"],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        response = None
        deadline = time.monotonic() + 12
        while time.monotonic() < deadline:
            result = subprocess.run(
                [sys.executable, "-m", "hallucinate", "--status"],
                env=env,
                capture_output=True,
                text=True,
                timeout=4,
            )
            if result.returncode == 0:
                response = json.loads(result.stdout)
                break
            if app.poll() is not None:
                stdout, stderr = app.communicate()
                raise AssertionError(f"Hallucinate exited during startup:\n{stdout}\n{stderr}")
            time.sleep(0.1)
        assert response is not None, "The running app did not expose its control socket"
        assert response["state"] == "Stopped"
        assert response["current"] is None
        assert response["queueLength"] == 0
        result = subprocess.run(
            [sys.executable, "-m", "hallucinate", "--next"],
            env=env,
            capture_output=True,
            text=True,
            timeout=4,
        )
        assert result.returncode == 0, result.stderr
    finally:
        app.terminate()
        try:
            app.communicate(timeout=8)
        except subprocess.TimeoutExpired:
            app.kill()
            app.communicate(timeout=5)
