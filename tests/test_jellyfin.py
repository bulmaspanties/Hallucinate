"""The Jellyfin client and its servers in the app: signing in once for a token, reading every song, and
keeping only the token (never the password)."""
import http.server
import json
import threading
import urllib.parse

import pytest
from test_subsonic import FakeKeyring, _rows

from hallucinate.core import jellyfin

TOKEN = "abc123token"


class FakeJellyfin:
    def __init__(self, songs=(), password="secret"):
        self.songs, self.password, self.seen, self.logged_out = list(songs), password, [], False
        fake = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, code, body):
                data = json.dumps(body).encode() if not isinstance(body, bytes) else body
                self.send_response(code)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def _authed(self):
                return f'Token="{TOKEN}"' in (self.headers.get("Authorization") or "")

            def do_POST(self):
                url = urllib.parse.urlsplit(self.path)
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(length) or b"{}")
                fake.seen.append(("POST", url.path, body, self.headers.get("Authorization")))
                if url.path == "/Users/AuthenticateByName":
                    if body.get("Pw") != fake.password:
                        return self._send(401, {})
                    return self._send(200, {"AccessToken": TOKEN, "User": {"Id": "u1"}})
                if not self._authed():
                    return self._send(401, {})
                if url.path == "/Sessions/Logout":
                    fake.logged_out = True
                return self._send(204, b"")

            def do_GET(self):
                url = urllib.parse.urlsplit(self.path)
                q = dict(urllib.parse.parse_qsl(url.query))
                fake.seen.append(("GET", url.path, q, self.headers.get("Authorization")))
                if not self._authed():
                    return self._send(401, {})
                if url.path == "/System/Info":
                    return self._send(200, {"Version": "10.10.0"})
                if url.path == "/Users/u1/Items":
                    start, n = int(q["StartIndex"]), int(q["Limit"])
                    return self._send(200, {"Items": fake.songs[start:start + n], "TotalRecordCount": len(fake.songs)})
                if url.path.endswith("/Images/Primary"):
                    return self._send(200, b"\xff\xd8\xff" + b"0" * 20)
                return self._send(404, {})

        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.httpd.server_address[1]}"

    def close(self):
        self.httpd.shutdown()


def item(i, album="al1"):
    return {"Id": f"j{i}", "Type": "Audio", "Name": f"Track {i}", "Album": "Record", "AlbumId": album,
            "AlbumArtist": "Band", "Artists": ["Band"], "IndexNumber": i, "ParentIndexNumber": 1,
            "ProductionYear": 2001, "Genres": ["Ambient"], "RunTimeTicks": 2_000_000_000,
            "AlbumPrimaryImageTag": "t", "MediaSources": [{"Container": "flac", "Bitrate": 900_000, "Size": 5000}]}


@pytest.fixture
def server():
    fake = FakeJellyfin([item(i) for i in range(1, 651)])
    yield fake
    fake.close()


def test_signing_in_gives_a_token_and_reads_every_song(server):
    client, token, user_id = jellyfin.Server.sign_in(server.base, "me", "secret", "dev1")
    assert token == TOKEN and user_id == "u1" and client.ping()["server_version"] == "10.10.0"
    songs = list(client.songs(page=500))
    assert len(songs) == 650 and songs[0]["duration"] == 200.0 and songs[0]["bitrate"] == 900
    assert songs[0]["suffix"] == "flac" and songs[0]["genre"] == "Ambient" and songs[0]["cover"] == "al1"
    assert "secret" not in json.dumps([s[2] for s in server.seen if s[1] != "/Users/AuthenticateByName"])
    assert "api_key=" + TOKEN in client.stream_url("j1") and client.cover("al1")[:3] == b"\xff\xd8\xff"


def test_a_wrong_password_says_so(server):
    with pytest.raises(jellyfin.JellyfinError, match="password is wrong"):
        jellyfin.Server.sign_in(server.base, "me", "nope", "dev1")


def test_what_a_server_sends_is_checked():
    assert jellyfin.song_from({"Type": "Folder", "Id": "x"}) is None and jellyfin.song_from({"Name": "no id"}) is None
    s = jellyfin.song_from({"Id": "x", "Name": "t" * 9000, "RunTimeTicks": "lots", "Artists": "not a list",
                            "MediaSources": ["junk"], "NormalizationGain": 500})
    assert len(s["title"]) == 1000 and s["duration"] == 0 and s["artist"] == "" and s["rg_track"] is None
    client = jellyfin.Server("https://h.example", 'tok"\r\nX-Evil: 1', "u", 'dev"1')
    assert "\r" not in client._auth_header() and '"1' not in client._auth_header().split("DeviceId=")[1][:8]


@pytest.fixture
def service(qapp, tmp_path, monkeypatch):
    from PySide6.QtCore import QSettings

    from hallucinate import servers as servers_mod
    from hallucinate.core.db import Database

    keyring = FakeKeyring()
    monkeypatch.setattr(servers_mod, "_keyring", lambda: keyring)
    settings = QSettings("hallucinate", "hallucinate")
    before = settings.value("servers/list")
    settings.remove("servers/list")
    Database(tmp_path / "lib.db").close()
    svc = servers_mod.Servers(tmp_path / "lib.db", tmp_path / "art")
    svc.keyring = keyring
    yield svc
    svc.setEnabled(False)
    svc.shutdown()
    settings.remove("servers/list") if before is None else settings.setValue("servers/list", before)


def test_a_jellyfin_server_keeps_only_its_token(service, server, tmp_path):
    from conftest import wait_for

    from hallucinate.core import remote

    service.setEnabled(True)
    service.addServer(server.base, "me", "secret", "Jelly", "jellyfin")
    assert wait_for(lambda: service.servers and service.servers[0]["songs"] == 650, timeout=30)
    entry = service.servers[0]
    kept = service.keyring.kept[("Hallucinate Music servers", entry["id"])]
    assert "secret" not in kept and json.loads(kept) == {"token": TOKEN, "user_id": "u1"}
    path = remote.make_path("jellyfin", entry["id"], "j3")
    assert path in _rows(tmp_path) and remote.stream_url(path).startswith(server.base + "/Audio/j3/stream")
    service.removeServer(entry["id"])
    assert wait_for(lambda: server.logged_out and not _rows(tmp_path), timeout=10)  # revoked, songs gone
    assert ("Hallucinate Music servers", entry["id"]) not in service.keyring.kept
