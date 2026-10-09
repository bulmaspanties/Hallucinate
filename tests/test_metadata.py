import io
import json
import subprocess
import urllib.error

import mutagen
import pytest
from audio import FFMPEG, encode
from conftest import PNG, make_mp3, wait_for
from PySide6.QtCore import QObject, Signal

from hallucinate.core import artfetch, lyrics, tagedit
from hallucinate.core.db import Database
from hallucinate.core.scanner import Scanner
from hallucinate.core.tags import read_track
from hallucinate.lyricsctl import LyricsController
from hallucinate.metaedit import MetadataEditor

needs_ffmpeg = pytest.mark.skipif(not FFMPEG, reason="ffmpeg not available")
FIELDS = {"title": "Nouveau Titre é", "artist": "Artiste", "album": "Album Ü", "album_artist": "AA",
          "track_no": "3", "disc_no": "2", "year": "1999", "genre": "Jazz"}


def easy(path):
    return mutagen.File(path, easy=True)


def test_write_tags_mp3_roundtrip(tmp_path):
    p = tmp_path / "a.mp3"
    make_mp3(p, "Old", "Someone", "Rec")
    tagedit.write_tags(str(p), FIELDS)
    t = easy(str(p))
    assert t["title"] == ["Nouveau Titre é"] and t["genre"] == ["Jazz"] and t["date"] == ["1999"]
    tagedit.write_tags(str(p), {"genre": ""})
    assert "genre" not in easy(str(p))


@needs_ffmpeg
@pytest.mark.parametrize("ext", ["flac", "ogg", "opus", "m4a", "wav"])
def test_write_tags_formats(tmp_path, ext):
    p = tmp_path / f"a.{ext}"
    encode(p, ext, 1, title="Old")
    tagedit.write_tags(str(p), {"title": "New é", "artist": "Art", "album": "Alb", "year": "2001"})
    tags = read_track(str(p))
    assert (tags["title"], tags["artist"], tags["album"]) == ("New é", "Art", "Alb")


@needs_ffmpeg
@pytest.mark.parametrize(("ext", "codec"), [
    ("flac", "FLAC"), ("mp3", "MP3"), ("ogg", "VORBIS"), ("opus", "OPUS"),
    ("m4a", "AAC"), ("alac.m4a", "ALAC"), ("wav", "WAV"), ("wma", "WMA"),
    ("wv", "WAVPACK"), ("aiff", "AIFF"),
])
def test_read_audio_codec_and_bitrate(tmp_path, ext, codec):
    path = encode(tmp_path / f"audio.{ext.split('.')[-1]}", ext, seconds=0.8)

    track = read_track(str(path))

    assert track["codec"] == codec
    assert track["fmt"] == ext.split(".")[-1].upper()
    assert track["bitrate"] > 0


@needs_ffmpeg
def test_read_vbr_bitrate_is_close_to_file_average(tmp_path):
    path = tmp_path / "vbr.mp3"
    subprocess.run([
        FFMPEG, "-y", "-loglevel", "error", "-f", "lavfi", "-i",
        "sine=frequency=440:duration=4", "-q:a", "2", str(path),
    ], check=True)

    track = read_track(str(path))
    expected_average = path.stat().st_size * 8 / track["duration"]

    assert track["codec"] == "MP3"
    assert track["bitrate"] == pytest.approx(expected_average, rel=0.1)


def test_write_tags_rejects_bad_files(tmp_path):
    p = tmp_path / "bad.mp3"
    p.write_bytes(b"not audio")
    with pytest.raises(tagedit.TagWriteError):
        tagedit.write_tags(str(p), {"title": "x"})
    with pytest.raises(tagedit.TagWriteError):
        tagedit.write_tags(str(tmp_path / "missing.mp3"), {"title": "x"})


def test_embed_cover(tmp_path):
    p = tmp_path / "a.mp3"
    make_mp3(p, "T", "A", "B")
    tagedit.embed_cover(str(p), PNG)
    assert mutagen.File(str(p)).tags.getall("APIC")


def test_parse_lrc_and_line_at():
    parsed = lyrics.parse_lrc("[ar:x]\n[00:01.50]one\n[00:03.5][00:10.00]two\n[01:00]end")
    assert parsed == [(1500, "one"), (3500, "two"), (10000, "two"), (60000, "end")]
    times = [t for t, _ in parsed]
    assert lyrics.line_at(times, 0) == -1
    assert lyrics.line_at(times, 1500) == 0
    assert lyrics.line_at(times, 9000) == 1
    assert lyrics.line_at(times, 99999) == 3
    assert lyrics.parse_lrc("plain text only") == []
    assert lyrics.is_synced("[00:01.00]x") and not lyrics.is_synced("x")
    assert lyrics.strip_timestamps("[00:01.00]hello") == "hello"


def test_read_embedded_sidecar_and_uslt(tmp_path):
    p = tmp_path / "a.mp3"
    make_mp3(p, "T", "A", "B")
    assert lyrics.read_embedded(str(p)) == ""
    (tmp_path / "a.lrc").write_text("[00:01.00]side", encoding="utf-8")
    assert "side" in lyrics.read_embedded(str(p))
    (tmp_path / "a.lrc").unlink()
    from mutagen.id3 import ID3, USLT
    tags = ID3(str(p))
    tags.add(USLT(encoding=3, lang="eng", desc="", text="embedded words"))
    tags.save(str(p))
    assert lyrics.read_embedded(str(p)) == "embedded words"


class FakeResp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


def test_fetch_lrclib(monkeypatch):
    body = json.dumps({"syncedLyrics": "[00:01.00]hi", "plainLyrics": "hi"}).encode()
    monkeypatch.setattr(lyrics.urllib.request, "urlopen", lambda req, timeout=0: FakeResp(body))
    assert lyrics.fetch_lrclib("a", "t", "al", 100) == ("[00:01.00]hi", "hi")

    def nf(req, timeout=0):
        raise urllib.error.HTTPError(req.full_url, 404, "nf", {}, None)

    monkeypatch.setattr(lyrics.urllib.request, "urlopen", nf)
    assert lyrics.fetch_lrclib("a", "t") is None

    def down(req, timeout=0):
        raise urllib.error.URLError("offline")

    monkeypatch.setattr(lyrics.urllib.request, "urlopen", down)
    with pytest.raises(OSError):
        lyrics.fetch_lrclib("a", "t")


def test_fetch_cover(monkeypatch):
    monkeypatch.setattr(artfetch, "find_release_ids", lambda a, b: ["x", "y"])

    def get(url, timeout=10):
        if "/x/" in url:
            raise urllib.error.HTTPError(url, 404, "nf", {}, None)
        return PNG

    monkeypatch.setattr(artfetch, "_get", get)
    assert artfetch.fetch_cover("a", "b") == PNG
    monkeypatch.setattr(artfetch, "find_release_ids", lambda a, b: [])
    assert artfetch.fetch_cover("a", "b") is None


@pytest.fixture
def lib(tmp_path):
    root = tmp_path / "Music"
    root.mkdir()
    make_mp3(root / "01.mp3", "One", "Band", "Disc", "Band", "1/2")
    make_mp3(root / "02.mp3", "Two", "Band", "Disc", "Band", "2/2")
    d = Database(tmp_path / "lib.db")
    Scanner(d, tmp_path / "art").scan([str(root)])
    d.close()
    return tmp_path, root


def test_metadata_editor_saves_and_rescans(qapp, lib):
    tmp, root = lib
    ed = MetadataEditor(tmp / "lib.db", tmp / "art")
    changed = []
    ed.changed.connect(lambda: changed.append(1))
    path = str(root / "01.mp3")
    assert ed.trackInfo(path)["title"] == "One"
    ed.saveTags([path], {"title": "Uno", "genre": "Pop"})
    assert wait_for(lambda: changed)
    info = ed.trackInfo(path)
    assert info["title"] == "Uno" and info["genre"] == "Pop"
    ed.shutdown()


def test_metadata_editor_reports_failure(qapp, lib):
    tmp, root = lib
    ed = MetadataEditor(tmp / "lib.db", tmp / "art")
    errors = []
    ed.failed.connect(errors.append)
    ed.saveTags([str(root / "nope.mp3")], {"title": "x"})
    assert wait_for(lambda: errors)
    ed.shutdown()


def test_metadata_editor_cover(qapp, lib, monkeypatch):
    tmp, root = lib
    ed = MetadataEditor(tmp / "lib.db", tmp / "art")
    key = ed.trackInfo(str(root / "01.mp3"))["album_key"]
    img = tmp / "cover.png"
    img.write_bytes(PNG)
    results = []
    ed.coverResult.connect(lambda ok, msg: results.append((ok, msg)))
    ed.setCoverFromFile(key, img.as_uri(), True)
    assert wait_for(lambda: results) and results[0][0]
    assert mutagen.File(str(root / "01.mp3")).tags.getall("APIC")

    bad = tmp / "bad.png"
    bad.write_bytes(b"nope")
    results.clear()
    ed.setCoverFromFile(key, bad.as_uri(), False)
    assert wait_for(lambda: results) and not results[0][0]

    results.clear()
    monkeypatch.setattr(artfetch, "fetch_cover", lambda a, b: None)
    ed.fetchCover(key, "Band", "Disc", False)
    assert wait_for(lambda: results) and not results[0][0]
    ed.shutdown()


class FakePlayer(QObject):
    trackChanged = Signal()
    positionChanged = Signal()

    def __init__(self):
        super().__init__()
        self.current, self.position = {}, 0

    @property
    def hasTrack(self):
        return bool(self.current)


def test_lyrics_controller_sidecar_and_sync(qapp, lib):
    tmp, root = lib
    (root / "01.lrc").write_text("[00:01.00]first\n[00:05.00]second", encoding="utf-8")
    pl = FakePlayer()
    ctl = LyricsController(tmp / "lib.db", pl)
    ctl.setOnlineLookup(False)
    pl.current = {"path": str(root / "01.mp3"), "artist": "Band", "title": "One", "album": "Disc", "duration": 3}
    pl.trackChanged.emit()
    assert wait_for(lambda: ctl.status == "found")
    assert ctl.synced and [ln["text"] for ln in ctl.lines] == ["first", "second"]
    pl.position = 6000
    pl.positionChanged.emit()
    assert ctl.currentLine == 1
    pl.current = {"path": str(root / "02.mp3"), "artist": "Band", "title": "Two", "album": "Disc", "duration": 3}
    pl.trackChanged.emit()
    assert wait_for(lambda: ctl.status == "none")
    ctl.shutdown()


def test_lyrics_controller_lrclib_cached_and_offline(qapp, lib, monkeypatch):
    tmp, root = lib
    calls = []

    def fake(artist, title, album="", duration=0, timeout=8):
        calls.append(title)
        return ("", "plain words")

    monkeypatch.setattr(lyrics, "fetch_lrclib", fake)
    pl = FakePlayer()
    ctl = LyricsController(tmp / "lib.db", pl)
    pl.current = {"path": str(root / "02.mp3"), "artist": "Band", "title": "Two", "album": "Disc", "duration": 3}
    pl.trackChanged.emit()
    assert wait_for(lambda: ctl.status == "found")
    assert ctl.plain == "plain words" and ctl.source == "LRCLIB" and not ctl.synced
    ctl.reload()
    pl.current = {"path": str(root / "01.mp3"), "artist": "Band", "title": "One", "album": "Disc", "duration": 3}
    monkeypatch.setattr(lyrics, "fetch_lrclib", lambda *a, **k: (_ for _ in ()).throw(OSError("down")))
    pl.trackChanged.emit()
    assert wait_for(lambda: ctl.status == "offline")
    pl.current = {"path": str(root / "02.mp3"), "artist": "Band", "title": "Two", "album": "Disc", "duration": 3}
    pl.trackChanged.emit()
    assert wait_for(lambda: ctl.status == "found") and calls == ["Two"]
    ctl.shutdown()
