import hashlib
import json
import time
from urllib.parse import parse_qs

import pytest
from conftest import wait_for
from PySide6.QtCore import QObject, Signal

import hallucinate.scrobbling as scrobbling


class FakePlayer(QObject):
    trackChanged = Signal()
    stateChanged = Signal()
    positionChanged = Signal()
    seeked = Signal(int)

    def __init__(self):
        super().__init__()
        self.current = {}
        self.position = 0
        self.duration = 0
        self.playing = False

    def set_track(self, track, duration_ms, playing=True):
        self.current = dict(track)
        self.duration = duration_ms
        self.position = 0
        self.playing = playing
        self.trackChanged.emit()
        self.stateChanged.emit()

    def advance(self, ms):
        self.position += ms
        self.positionChanged.emit()

    def set_playing(self, playing):
        self.playing = playing
        self.stateChanged.emit()

    def seek(self, ms):
        self.position = ms
        self.seeked.emit(ms)


@pytest.fixture
def memory_keyring(monkeypatch):
    store = {}
    monkeypatch.setattr(scrobbling.keyring, "get_password", lambda service, name: store.get(name))
    monkeypatch.setattr(scrobbling.keyring, "set_password", lambda service, name, value: store.__setitem__(name, value))
    monkeypatch.setattr(scrobbling.keyring, "delete_password", lambda service, name: store.pop(name, None))
    return store


@pytest.fixture
def make_scrobbler(qapp, tmp_path, memory_keyring, monkeypatch):
    monkeypatch.delenv("HALLUCINATE_LASTFM_API_KEY", raising=False)
    monkeypatch.delenv("HALLUCINATE_LASTFM_API_SECRET", raising=False)
    player = FakePlayer()
    instances = []

    def make():
        result = scrobbling.LastFmScrobbler(player, tmp_path)
        instances.append(result)
        return result

    yield player, make
    for result in instances:
        result.shutdown()


def test_api_signature_is_sorted_and_excludes_format():
    values = {"z": "last", "api_key": "key", "method": "test", "a": "first", "format": "json"}
    expected = hashlib.md5(b"afirstapi_keykeymethodtestzlastsecret").hexdigest()
    assert scrobbling.api_signature(values, "secret") == expected


def test_api_request_posts_signed_utf8_form(monkeypatch):
    captured = {}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def read(self):
            return b'{"ok": true}'

    def fake_urlopen(request, timeout):
        captured["request"] = request
        captured["timeout"] = timeout
        return Response()

    monkeypatch.setattr(scrobbling, "urlopen", fake_urlopen)
    assert scrobbling.api_request(
        "track.updateNowPlaying", {"track": "Café", "artist": "Björk"},
        "public-key", "private-secret", "session",
    ) == {"ok": True}
    req = captured["request"]
    values = parse_qs(req.data.decode())
    assert values["track"] == ["Café"]
    assert values["sk"] == ["session"] and values["format"] == ["json"]
    fields = {k: values[k][0] for k in values if k not in {"format", "api_sig"}}
    assert values["api_sig"] == [scrobbling.api_signature(fields, "private-secret")]
    assert captured["timeout"] == 15


def test_api_errors_are_not_success_shaped(monkeypatch):
    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def read(self):
            return b'{"error": 9, "message": "Invalid session key"}'

    monkeypatch.setattr(scrobbling, "urlopen", lambda *_args, **_kwargs: Response())
    with pytest.raises(RuntimeError, match="Invalid session key"):
        scrobbling.api_request("track.scrobble", {}, "key", "secret", "bad-session")


@pytest.mark.parametrize(
    "duration,expected",
    [(30_000, 15_000), (240_000, 120_000), (600_000, 240_000), (0, 240_000)],
)
def test_lastfm_scrobble_threshold(duration, expected):
    assert scrobbling.scrobble_threshold(duration) == expected


def test_auth_flow_stores_session_only_in_keyring(make_scrobbler, monkeypatch):
    import hallucinate.scrobbling as module

    _player, make = make_scrobbler
    calls = []

    def fake_api(method, *_args, **_kwargs):
        calls.append(method)
        if method == "auth.getToken":
            return {"token": "a-token"}
        if method == "auth.getSession":
            return {"session": {"key": "secure-session", "name": "Ada"}}
        raise AssertionError(method)

    monkeypatch.setattr(module, "api_request", fake_api)
    s = make()
    s.setApiCredentials("app-key", "app-secret")
    assert s.configured
    s.connectAccount()
    assert wait_for(lambda: s.authorizationUrl != "", timeout=4)
    assert "a-token" in s.authorizationUrl and s.status.startswith("Authorize")
    s.completeAuthorization()
    assert wait_for(lambda: s.connected, timeout=4)
    assert s.status == "Connected to Last.fm as Ada."
    assert scrobbling.keyring.get_password(scrobbling.KEYRING_SERVICE, "session") == "secure-session"
    s.disconnectAccount()
    assert not s.connected
    assert scrobbling.keyring.get_password(scrobbling.KEYRING_SERVICE, "session") is None
    assert calls == ["auth.getToken", "auth.getSession"]


def test_missing_credentials_are_explained(make_scrobbler):
    _player, make = make_scrobbler
    s = make()
    s.connectAccount()
    assert not s.busy
    assert "API key and secret" in s.status


def test_nowplaying_and_scrobble_at_listen_threshold(make_scrobbler, memory_keyring, monkeypatch):
    player, make = make_scrobbler
    memory_keyring["session"] = "session"
    calls = []

    def fake_api(method, fields, *_args, **_kwargs):
        calls.append((method, dict(fields)))
        if method == "track.scrobble":
            return {"scrobbles": {"@attr": {"accepted": "1"}}}
        return {"nowplaying": {}}

    monkeypatch.setattr(scrobbling, "api_request", fake_api)
    s = make()
    player.set_track(
        {"path": "/music/song.flac", "title": "Song", "artist": "Artist", "album": "Album", "track_no": 4},
        4000,
    )
    assert wait_for(lambda: any(m == "track.updateNowPlaying" for m, _ in calls))

    player.advance(1500)
    s._last_tick = time.monotonic() - 1.1
    s._last_position = 0
    s._tick()
    assert s._listened_ms >= 1000
    assert s.pendingCount == 0

    player.advance(1500)
    s._last_tick = time.monotonic() - 1.1
    s._last_position = 1500
    s._tick()
    assert wait_for(lambda: s.pendingCount == 0 and any(m == "track.scrobble" for m, _ in calls))
    sent = [fields for method, fields in calls if method == "track.scrobble"]
    assert sent[0]["track"] == "Song" and sent[0]["artist"] == "Artist"
    assert sent[0]["trackNumber"] == 4 and sent[0]["timestamp"] > 0


def test_pauses_and_seeks_do_not_count_as_listened_time(make_scrobbler, memory_keyring, monkeypatch):
    player, make = make_scrobbler
    memory_keyring["session"] = "session"
    monkeypatch.setattr(scrobbling, "api_request", lambda *_a, **_k: {"nowplaying": {}})
    s = make()
    player.set_track({"path": "/song", "title": "Song", "artist": "Artist"}, 10_000)
    player.set_playing(False)
    s._listened_ms = 4000
    s._last_tick = time.monotonic() - 2
    player.advance(9000)
    s._tick()
    assert s._listened_ms == 4000
    player.seek(1000)
    assert s._last_position == 1000


def test_failed_scrobbles_remain_queued_and_retry(make_scrobbler, memory_keyring, monkeypatch, tmp_path):
    _player, make = make_scrobbler
    memory_keyring["session"] = "session"
    calls = []

    def flaky_api(method, *_args, **_kwargs):
        calls.append(method)
        if len(calls) == 1:
            raise RuntimeError("offline")
        return {"scrobbles": {"@attr": {"accepted": "1"}}}

    monkeypatch.setattr(scrobbling, "api_request", flaky_api)
    s = make()
    s._queue_scrobble({"title": "Offline", "artist": "Artist", "album": "Album"}, 1234)
    assert wait_for(lambda: "offline" in s.status.lower(), timeout=4)
    assert s.pendingCount == 1
    assert json.loads((tmp_path / "lastfm-scrobbles.json").read_text())[0]["track"] == "Offline"

    s._retry_at = 0
    s._send_pending()
    assert wait_for(lambda: s.pendingCount == 0, timeout=4)
    assert json.loads((tmp_path / "lastfm-scrobbles.json").read_text()) == []


def test_offline_queue_survives_restart(make_scrobbler, memory_keyring, monkeypatch, tmp_path):
    _player, make = make_scrobbler
    memory_keyring["session"] = "session"
    monkeypatch.setattr(scrobbling, "api_request", lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("offline")))
    first = make()
    first._queue_scrobble({"title": "Queued", "artist": "Artist"}, 456)
    assert wait_for(lambda: "offline" in first.status.lower(), timeout=4)
    first.shutdown()
    second = make()
    assert second.pendingCount == 1
    assert second._pending[0]["timestamp"] == 456


def test_api_credentials_and_session_never_enter_queue_file(make_scrobbler, memory_keyring, tmp_path):
    _player, make = make_scrobbler
    s = make()
    s.setApiCredentials("secret-app-key", "secret-app-secret")
    s._queue_scrobble({"title": "Song", "artist": "Artist"}, 1)
    content = (tmp_path / "lastfm-scrobbles.json").read_text()
    assert "secret-app" not in content and "session" not in content
