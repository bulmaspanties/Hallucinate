import io
import json
import subprocess
import urllib.error

import mutagen
import pytest
from audio import FFMPEG, encode
from conftest import PNG, make_mp3, wait_for
from PySide6.QtCore import QObject, QSettings, Signal

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


def http_error(url, code):
    return urllib.error.HTTPError(url, code, "err", {}, None)


def test_fetch_cover(monkeypatch):
    monkeypatch.setattr(artfetch, "find_releases", lambda a, b, sleep=None: [("x", "gx"), ("y", "gy")])

    def get(url, timeout=10):
        if "/x/" in url:
            raise http_error(url, 404)
        return PNG

    monkeypatch.setattr(artfetch, "_get", get)
    assert artfetch.fetch_cover("a", "b") == PNG
    monkeypatch.setattr(artfetch, "find_releases", lambda a, b, sleep=None: [])
    assert artfetch.fetch_cover("a", "b") is None


def test_fetch_cover_gets_past_a_failing_image(monkeypatch):
    """archive.org failing one image (HTTP 500) moves on to a smaller size, the next release and the release
    group's cover, instead of ending the search."""
    monkeypatch.setattr(artfetch, "find_releases", lambda a, b, sleep=None: [("x", "g"), ("y", "g")])
    asked = []

    def get(url, timeout=10):
        asked.append(url.removeprefix(artfetch.CAA))
        if url.endswith("release-group/g/front-500"):
            return PNG
        raise http_error(url, 500 if "/x/" in url else 404)

    monkeypatch.setattr(artfetch, "_get", get)
    assert artfetch.fetch_cover("a", "b") == PNG
    assert asked == ["release/x/front-500", "release/x/front-250", "release/y/front-500", "release/y/front-250",
                     "release-group/g/front-500"]


def test_fetch_cover_explains_server_trouble(monkeypatch):
    monkeypatch.setattr(artfetch, "find_releases", lambda a, b, sleep=None: [("x", "")])
    monkeypatch.setattr(artfetch, "_get", lambda url, timeout=10: (_ for _ in ()).throw(http_error(url, 500)))
    with pytest.raises(artfetch.ServiceError, match="Cover Art Archive is having trouble"):
        artfetch.fetch_cover("a", "b")
    # a mix of "no art" and server errors still says it was the server, since a cover may exist
    monkeypatch.setattr(artfetch, "find_releases", lambda a, b, sleep=None: [("x", ""), ("y", "")])
    monkeypatch.setattr(artfetch, "_get", lambda url, timeout=10: (_ for _ in ()).throw(
        http_error(url, 503 if "/x/" in url else 404)))
    with pytest.raises(artfetch.ServiceError):
        artfetch.fetch_cover("a", "b")


def test_musicbrainz_server_error_is_retried_once(monkeypatch):
    calls, slept = [], []
    body = json.dumps({"releases": [{"id": "r1", "release-group": {"id": "g1"}}]}).encode()

    def get(url, timeout=10):
        calls.append(url)
        if len(calls) == 1:
            raise http_error(url, 503)
        return body

    monkeypatch.setattr(artfetch, "_get", get)
    assert artfetch.find_releases("Artist", "Album", sleep=slept.append) == [("r1", "g1")]
    assert len(calls) == 2 and slept == [1.1]
    calls.clear()
    monkeypatch.setattr(artfetch, "_get", lambda url, timeout=10: (_ for _ in ()).throw(http_error(url, 500)))
    with pytest.raises(artfetch.ServiceError, match="MusicBrainz is having trouble"):
        artfetch.find_releases("Artist", "Album", sleep=lambda s: None)


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


@pytest.fixture(autouse=True)
def _lyrics_online_setting():
    """The online-lyrics switch is saved; put back what was there."""
    settings = QSettings("hallucinate", "hallucinate")
    before = settings.value("lyrics/online")
    yield
    if before is None:
        settings.remove("lyrics/online")
    else:
        settings.setValue("lyrics/online", before)


def test_finding_lyrics_online_can_be_switched_off_and_stays_off(qapp, lib, monkeypatch):
    tmp, root = lib
    calls = []
    monkeypatch.setattr(lyrics, "fetch_lrclib", lambda *a, **k: calls.append(a) or ("", "words"))
    pl = FakePlayer()
    ctl = LyricsController(tmp / "lib.db", pl)
    assert ctl.onlineLookup  # on unless switched off
    ctl.setOnlineLookup(False)
    ctl.shutdown()
    ctl = LyricsController(tmp / "lib.db", pl)
    try:
        assert not ctl.onlineLookup  # remembered
        pl.current = {"path": str(root / "02.mp3"), "artist": "Band", "title": "Two", "album": "Disc", "duration": 3}
        pl.trackChanged.emit()
        assert wait_for(lambda: ctl.status == "none")
        assert calls == []  # nothing was sent
    finally:
        ctl.shutdown()


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


def test_lyrics_switched_off_reads_nothing(qapp, lib):
    """Settings → Features → Lyrics off: no file is read and nothing is looked up; back on, it loads again."""
    tmp, root = lib
    (root / "01.lrc").write_text("[00:01.00]first", encoding="utf-8")
    pl = FakePlayer()
    ctl = LyricsController(tmp / "lib.db", pl)
    ctl.setOnlineLookup(False)
    ctl.setEnabled(False)
    pl.current = {"path": str(root / "01.mp3"), "artist": "Band", "title": "One", "album": "Disc", "duration": 3}
    pl.trackChanged.emit()
    assert ctl.status == "idle" and not ctl.lines
    ctl.setEnabled(True)
    assert wait_for(lambda: ctl.status == "found")
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


def test_find_all_missing_covers(qapp, tmp_path, monkeypatch):
    from conftest import wait_for

    from hallucinate import metaedit
    from hallucinate.core.db import Database

    db = Database(tmp_path / "lib.db")
    for album, art in (("Has Cover", "/art/x.jpg"), ("First", None), ("Second", None), ("Unknown Album", None)):
        db.upsert_track({
            "path": f"/m/{album}.flac", "mtime": 0, "size": 1, "title": album, "artist": "A", "album_artist": "A",
            "aa_tag": 1, "album": album, "album_key": f"A|{album}", "track_no": 1, "disc_no": 0, "year": 2000,
            "genre": "", "duration": 60.0, "fmt": "FLAC", "codec": "FLAC", "bitrate": 0, "sample_rate": 44100,
            "art": art,
        })
    db.commit()
    asked, slept = [], []
    png = b"\x89PNG\r\n\x1a\n" + b"0" * 32

    def fake_fetch(artist, album):
        asked.append(album)
        return png if album == "Second" else None

    monkeypatch.setattr(metaedit.artfetch, "fetch_cover", fake_fetch)
    monkeypatch.setattr(metaedit.time, "sleep", lambda s: slept.append(s))
    editor = metaedit.MetadataEditor(tmp_path / "lib.db", tmp_path / "art")
    results = []
    editor.coverResult.connect(lambda ok, msg: results.append(msg))
    try:
        editor.fetchMissingCovers()
        assert wait_for(lambda: results, 10)
        assert asked == ["First", "Second"]  # "Unknown Album" isn't worth asking about
        assert editor.coversDone == 2 and editor.coversFound == 1 and editor.coversTotal == 2
        assert not editor.coversBusy and results == ["Found 1 of 2 covers"]
        assert all(s <= metaedit.MUSICBRAINZ_INTERVAL for s in slept) and len(slept) >= 1  # paced for MusicBrainz
        art = db.conn.execute("SELECT art FROM tracks WHERE album='Second'").fetchone()[0]
        assert art and art.endswith(".png")
    finally:
        editor.shutdown()
        db.close()


def test_lrc_offset_and_formatting():
    from hallucinate.core import lyrics

    assert lyrics.parse_lrc("[offset:+500]\n[00:01.00]one\n[00:02.50]two") == [(500, "one"), (2000, "two")]
    assert lyrics.parse_lrc("[offset:-250]\n[00:01.00]one") == [(1250, "one")]
    text = lyrics.format_lrc([(1000, "one"), (62_500, "two")], offset_ms=500)
    assert text == "[00:00.50]one\n[01:02.00]two\n"
    assert lyrics.parse_lrc(text) == [(500, "one"), (62_000, "two")]
    assert lyrics.sidecar_path("/m/song.flac") == "/m/song.lrc"
    assert lyrics.sidecar_path("/m/live.flac#03") is None or not lyrics.sidecar_path("/m/live.flac#03")


class _LyricsPlayer(QObject):
    trackChanged = Signal()
    positionChanged = Signal()
    hasTrack = True

    def __init__(self, current, position):
        super().__init__()
        self.current, self.position = current, position


def test_lyrics_offset_is_saved_next_to_the_song(qapp, tmp_path):
    from conftest import wait_for

    from hallucinate.core.db import Database
    from hallucinate.lyricsctl import LyricsController

    song = tmp_path / "song.flac"
    song.write_bytes(b"")
    (tmp_path / "song.lrc").write_text("[00:01.00]one\n[00:03.00]two\n[00:05.00]three\n", encoding="utf-8")
    Database(tmp_path / "lib.db").close()

    player = _LyricsPlayer({"path": str(song), "artist": "A", "title": "T", "album": "", "duration": 9}, 2_600)
    ctl = LyricsController(tmp_path / "lib.db", player)
    try:
        ctl.setOnlineLookup(False)
        assert wait_for(lambda: ctl.status == "found" and ctl.synced)
        assert ctl.currentLine == 0  # 2.6 s: still on "one"
        ctl.nudge(250)  # the lyrics were late: show them 0.25 s earlier
        assert ctl.offset == 250 and ctl.currentLine == 1
        assert ctl.saveTiming() == "Saved song.lrc"
        assert (tmp_path / "song.lrc").read_text(encoding="utf-8").splitlines()[:2] == ["[00:00.75]one", "[00:02.75]two"]
        assert ctl.offset == 0 and ctl.currentLine == 1 and ctl.source == "lrc file"
    finally:
        ctl.shutdown()


def test_genres_found_for_albums_without_one_are_saved_only_when_kept(qapp, lib, monkeypatch):
    from hallucinate.core import musicbrainz

    tmp, root = lib
    asked = []

    def fake(artist, album, cache=None):
        asked.append((artist, album))
        return {"genre": "Dream Pop", "genres": ["Dream Pop", "Shoegaze"], "source": "album", "release": album}

    monkeypatch.setattr(musicbrainz, "find_genre", fake)
    ed = MetadataEditor(tmp / "lib.db", tmp / "art")
    done, changed = [], []
    ed.genresFinished.connect(done.append)
    ed.changed.connect(lambda: changed.append(1))
    try:
        ed.findMissingGenres()
        assert wait_for(lambda: done, 10)
        assert asked == [("Band", "Disc")] and done[0].startswith("Found genres for 1 of 1 albums")
        proposals = ed.genreProposals
        assert [(p["album"], p["genre"], p["genres"], p["songs"]) for p in proposals] == \
            [("Disc", "Dream Pop", ["Dream Pop", "Shoegaze"], 2)]
        assert ed.trackInfo(str(root / "01.mp3"))["genre"] == ""  # nothing written yet
        ed.saveGenres([{"album_key": proposals[0]["album_key"], "genre": "Shoegaze"}])
        assert wait_for(lambda: changed)
        assert {ed.trackInfo(str(root / n))["genre"] for n in ("01.mp3", "02.mp3")} == {"Shoegaze"}
        assert ed.genreProposals == []
    finally:
        ed.shutdown()


def test_one_albums_genre_is_found_without_writing(qapp, lib, monkeypatch):
    from hallucinate.core import musicbrainz, net

    tmp, root = lib
    monkeypatch.setattr(musicbrainz, "find_genre", lambda artist, album, cache=None: None)
    ed = MetadataEditor(tmp / "lib.db", tmp / "art")
    got = []
    ed.genreFound.connect(lambda r: got.append(dict(r)))
    try:
        ed.findGenre("Band", "Disc")
        assert wait_for(lambda: got, 10) and got[0]["error"] == "MusicBrainz has no genre for this album"
        net.set_offline(True)
        ed.findGenre("Band", "Disc")
        assert got[1]["error"].startswith("Offline mode is on")
    finally:
        net.set_offline(False)
        ed.shutdown()


@needs_ffmpeg
def test_a_failed_tag_save_leaves_the_song_untouched(tmp_path, monkeypatch):
    import mutagen.flac

    src = encode(tmp_path / "a.flac", "flac", seconds=0.5)
    before = src.read_bytes()

    def broken_save(self, *a, **k):
        raise OSError("No space left on device")

    monkeypatch.setattr(mutagen.flac.FLAC, "save", broken_save)
    with pytest.raises(tagedit.TagWriteError):
        tagedit.write_tags(str(src), {"title": "New"})
    assert src.read_bytes() == before
    assert [p.name for p in tmp_path.iterdir()] == ["a.flac"]  # no leftover copy


def test_lyrics_found_nowhere_are_not_looked_up_every_time(qapp, lib, monkeypatch):
    tmp, root = lib
    calls = []
    monkeypatch.setattr(lyrics, "fetch_lrclib", lambda a, t, *rest, **k: calls.append(t))  # nothing found
    pl = FakePlayer()
    ctl = LyricsController(tmp / "lib.db", pl)
    try:
        ctl.setOnlineLookup(True)
        song = {"path": str(root / "01.mp3"), "artist": "Band", "title": "One", "album": "Disc", "duration": 3}
        for other in ("02.mp3", "01.mp3"):
            pl.current = dict(song)
            pl.trackChanged.emit()
            assert wait_for(lambda: ctl.status == "none")
            pl.current = {**song, "path": str(root / other), "title": other}
            pl.trackChanged.emit()
            assert wait_for(lambda: ctl.status == "none")
        assert calls.count("One") == 1  # asked once, remembered for a month
    finally:
        ctl.shutdown()


def test_your_own_lrc_beats_lyrics_found_online_earlier(qapp, lib, monkeypatch):
    tmp, root = lib
    monkeypatch.setattr(lyrics, "fetch_lrclib", lambda *a, **k: ("", "words from online"))
    pl = FakePlayer()
    ctl = LyricsController(tmp / "lib.db", pl)
    try:
        ctl.setOnlineLookup(True)
        song = {"path": str(root / "01.mp3"), "artist": "Band", "title": "One", "album": "Disc", "duration": 3}
        pl.current = song
        pl.trackChanged.emit()
        assert wait_for(lambda: ctl.status == "found") and ctl.plain == "words from online"
        (root / "01.lrc").write_text("[00:01.00]my own words", encoding="utf-8")
        pl.current = {**song, "path": str(root / "02.mp3")}  # play something else, then come back
        pl.trackChanged.emit()
        assert wait_for(lambda: ctl.status != "loading")
        pl.current = song
        pl.trackChanged.emit()
        assert wait_for(lambda: ctl.status == "found" and ctl.source != "LRCLIB")
        assert [ln["text"] for ln in ctl.lines] == ["my own words"]
    finally:
        ctl.shutdown()
