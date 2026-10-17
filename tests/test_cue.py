"""CUE sheets: parsing, turning one big file into songs at scan time, and playing those songs."""
import os
import time

import pytest
from audio import FFMPEG, encode
from conftest import touch_newer, wait_for

from hallucinate.core import cue
from hallucinate.core.scanner import Scanner

needs_ffmpeg = pytest.mark.skipif(not FFMPEG, reason="ffmpeg not installed")

SHEET = '''\ufeffREM GENRE "Ambient"
REM DATE 1998
REM DISCNUMBER 2
REM REPLAYGAIN_ALBUM_GAIN -7.50 dB
PERFORMER "Aurora Vale"
TITLE "Live at the Lighthouse"
FILE "live.wav" WAVE
  TRACK 01 AUDIO
    TITLE "Opening"
    INDEX 01 00:00:00
  TRACK 02 AUDIO
    TITLE "Harbour Lights"
    PERFORMER "Aurora Vale & Blue Harbor"
    REM REPLAYGAIN_TRACK_GAIN -6.25 dB
    INDEX 00 00:01:50
    INDEX 01 00:02:00
  TRACK 03 AUDIO
    TITLE "Encore"
    INDEX 01 00:04:37
'''


def test_parse_sheet():
    sheet = cue.parse(SHEET)
    assert (sheet["title"], sheet["performer"], sheet["genre"], sheet["date"], sheet["disc"]) == (
        "Live at the Lighthouse", "Aurora Vale", "Ambient", "1998", 2)
    assert sheet["rg_album"] == -7.5
    (f,) = sheet["files"]
    assert f["name"] == "live.wav" and [t["number"] for t in f["tracks"]] == [1, 2, 3]
    assert [t["start"] for t in f["tracks"]] == [0, 2, pytest.approx(4 + 37 / 75)]  # INDEX 01, not the pregap
    assert f["tracks"][1]["performer"] == "Aurora Vale & Blue Harbor" and f["tracks"][1]["rg_track"] == -6.25
    assert f["tracks"][0]["performer"] == ""


def test_data_tracks_and_one_song_per_file_are_left_alone(tmp_path):
    text = 'FILE "a.flac" WAVE\n TRACK 01 AUDIO\n  INDEX 01 00:00:00\nFILE "b.flac" WAVE\n TRACK 02 AUDIO\n' \
           '  INDEX 01 00:00:00\n TRACK 03 MODE1/2352\n  INDEX 01 00:09:00\n'
    sheet = cue.parse(text)
    assert [len(f["tracks"]) for f in sheet["files"]] == [1, 1]
    (tmp_path / "x.cue").write_text(text)
    assert cue.split_files(str(tmp_path / "x.cue"), ["a.flac", "b.flac"]) == {}


def test_file_names_from_the_rip_still_match(tmp_path):
    sheet = str(tmp_path / "Album.cue")
    d = str(tmp_path)
    assert cue.resolve_file("live.wav", sheet, ["Live.wav"]) == os.path.join(d, "Live.wav")
    assert cue.resolve_file("live.wav", sheet, ["live.flac", "other.flac"]) == os.path.join(d, "live.flac")
    assert cue.resolve_file("C:\\rips\\live.wav", sheet, ["live.flac"]) == os.path.join(d, "live.flac")
    assert cue.resolve_file("gone.wav", sheet, ["Album.flac"]) == os.path.join(d, "Album.flac")
    assert cue.resolve_file("gone.wav", sheet, ["x.flac"]) is None


def test_songs_from_a_sheet():
    sheet = cue.parse(SHEET)
    whole = {"path": "/m/live.flac", "mtime": 5.0, "size": 100, "title": "live", "artist": "", "album_artist": "",
             "aa_tag": 0, "album": "", "album_key": "k", "track_no": 0, "disc_no": 0, "year": 0, "genre": "",
             "duration": 10.0, "fmt": "FLAC", "rg_album": None, "rating": 4}
    rows = cue.tracks(whole, sheet, sheet["files"][0], cue_mtime=9.0)
    assert [r["path"] for r in rows] == ["/m/live.flac#01", "/m/live.flac#02", "/m/live.flac#03"]
    assert [r["duration"] for r in rows] == [2.0, pytest.approx(37 / 75 + 2, abs=1e-3), pytest.approx(5.507, abs=1e-3)]
    assert [(r["cue_start"], r["cue_end"]) for r in rows][1:] == [(2.0, pytest.approx(4.4933, abs=1e-3)),
                                                                 (pytest.approx(4.4933, abs=1e-3), 0.0)]
    assert {r["file"] for r in rows} == {"/m/live.flac"} and {r["mtime"] for r in rows} == {9.0}
    assert rows[1]["artist"] == "Aurora Vale & Blue Harbor" and rows[0]["artist"] == "Aurora Vale"
    assert {(r["album"], r["album_artist"], r["year"], r["genre"], r["disc_no"]) for r in rows} == {
        ("Live at the Lighthouse", "Aurora Vale", 1998, "Ambient", 2)}
    assert len({r["album_key"] for r in rows}) == 1 and rows[0]["rating"] == 0
    assert (rows[0]["rg_track"], rows[1]["rg_track"], rows[1]["rg_album"]) == (-7.5, -6.25, -7.5)


def _album(folder, seconds=6.0):
    """One FLAC holding three songs (0–2 s, 2–4 s, 4 s–end) and its sheet, which names a WAV."""
    folder.mkdir(parents=True, exist_ok=True)
    audio = encode(folder / "live.flac", "flac", seconds=seconds, title="whole file", artist="Aurora Vale")
    (folder / "live.cue").write_text(SHEET.replace("00:04:37", "00:04:00"), encoding="utf-8")
    return str(audio)


@needs_ffmpeg
def test_scanner_splits_the_file_and_follows_changes(db, tmp_path):
    folder = tmp_path / "Music" / "Live"
    audio = _album(folder)
    encode(folder.parent / "single.flac", "flac", seconds=1, title="Single")
    art = tmp_path / "art"
    art.mkdir()

    def scan():
        return Scanner(db, art).scan([str(folder.parent)])

    stats = scan()
    assert stats["added"] == 4
    rows = {r["path"]: r for r in db._rows("SELECT * FROM tracks")}
    assert audio not in rows and f"{audio}#02" in rows
    song = rows[f"{audio}#02"]
    assert (song["title"], song["file"], song["cue_start"], song["cue_end"]) == ("Harbour Lights", audio, 2.0, 4.0)
    assert rows[f"{audio}#03"]["duration"] == pytest.approx(2.0, abs=0.05)
    assert rows[str(folder.parent / "single.flac")]["file"] is None

    assert scan()["unchanged"] == 4  # nothing changed: nothing is read again
    text = (folder / "live.cue").read_text(encoding="utf-8").replace('"Encore"', '"Last Song"')
    (folder / "live.cue").write_text(text, encoding="utf-8")
    touch_newer(folder / "live.cue")
    assert scan()["updated"] == 3
    assert db._rows("SELECT title FROM tracks WHERE path=?", (f"{audio}#03",))[0]["title"] == "Last Song"

    os.remove(folder / "live.cue")  # without the sheet it is one long song again
    stats = scan()
    assert stats["added"] == 1 and stats["removed"] == 3
    assert [r["path"] for r in db._rows("SELECT path FROM tracks WHERE path LIKE ?", (str(folder) + "%",))] == [audio]


@needs_ffmpeg
def test_cue_songs_are_not_offered_for_replaygain_analysis(db, tmp_path):
    folder = tmp_path / "Music" / "Live"
    _album(folder)
    (folder / "live.cue").write_text(SHEET.replace("REM REPLAYGAIN_ALBUM_GAIN -7.50 dB\n", "")
                                     .replace("    REM REPLAYGAIN_TRACK_GAIN -6.25 dB\n", ""), encoding="utf-8")
    art = tmp_path / "art"
    art.mkdir()
    Scanner(db, art).scan([str(folder)])
    assert db._rows("SELECT COUNT(*) AS n FROM tracks WHERE rg_track IS NULL")[0]["n"] == 3
    assert db.tracks_without_gain() == 0 and db.albums_needing_gain() == []


# --- playback ----------------------------------------------------------------------------------------------
@pytest.fixture
def cue_songs(db, tmp_path):
    folder = tmp_path / "Music" / "Live"
    _album(folder)
    art = tmp_path / "art"
    art.mkdir()
    Scanner(db, art).scan([str(folder)])
    return db._rows("SELECT * FROM tracks ORDER BY track_no")


@pytest.fixture
def player(qapp):
    from hallucinate.player import Player

    p = Player()
    yield p
    p.shutdown()


@needs_ffmpeg
def test_a_song_in_the_middle_plays_just_its_stretch(player, cue_songs):
    player.playList([cue_songs[1]], 0)
    assert wait_for(lambda: player.state == "Playing" and player.position > 200), player.error
    assert player.duration == 2000
    assert 1900 < player._voice.player.position() < 3500  # really playing seconds 2–4 of the file
    player.seek(1500)
    assert wait_for(lambda: player.position >= 1450)
    assert wait_for(lambda: player.state == "Stopped", 5)  # stops where the song ends, not at the end of the file
    assert player._voice.player.position() < 4600


@needs_ffmpeg
def test_an_album_plays_through_as_one_piece(player, cue_songs):
    t0 = time.monotonic()
    player.playList(cue_songs, 0)
    assert wait_for(lambda: player.currentIndex == 1, 5)
    assert player.position < 600
    assert wait_for(lambda: player.currentIndex == 2, 5)
    assert wait_for(lambda: player.state == "Stopped", 5)
    assert player.gapless_swaps == 0  # one file, one voice, no reloading between songs
    assert time.monotonic() - t0 < 6.0 + 1.5
    assert player.error == ""


@needs_ffmpeg
def test_jumping_between_songs_of_a_sheet(player, cue_songs):
    player.playList(cue_songs, 2)
    assert wait_for(lambda: player.state == "Playing" and player.position > 100)
    assert player._voice.player.position() >= 4000
    player.previous()  # less than 3 s in: the song before
    assert player.currentIndex == 1
    assert wait_for(lambda: 2000 <= player._voice.player.position() < 3500)
    assert player.current["title"] == "Harbour Lights"


def test_virtual_paths_are_not_edited_or_searched_for_lyrics(tmp_path):
    from hallucinate.core import lyrics, tagedit

    audio = tmp_path / "live.flac"
    audio.write_bytes(b"")
    (tmp_path / "live.lrc").write_text("[00:01.00]whole album")
    song = cue.virtual_path(str(audio), 2)
    assert cue.is_virtual(song) and not cue.is_virtual(str(audio))
    assert lyrics.read_embedded(song) == ""
    with pytest.raises(tagedit.TagWriteError, match="CUE sheet"):
        tagedit._writable(song)


def test_native_flac_cuesheet_block_becomes_a_sheet():
    from types import SimpleNamespace as NS

    from hallucinate.core.tags import embedded_cuesheet

    def track(n, start, index_offset=0):
        return NS(track_number=n, start_offset=start, indexes=[NS(index_number=1, index_offset=index_offset)])

    f = NS(tags=None, info=NS(sample_rate=44100),
           cuesheet=NS(tracks=[track(1, 0), track(2, 44100 * 125), track(3, 44100 * 200, 588), track(170, 44100 * 300)]))
    sheet = cue.parse(embedded_cuesheet(f, "album.flac"))
    (entry,) = sheet["files"]
    assert entry["name"] == "album.flac"
    assert [t["number"] for t in entry["tracks"]] == [1, 2, 3]  # the lead-out (170) is not a song
    assert [round(t["start"], 3) for t in entry["tracks"]] == [0, 125, round(200 + 1 / 75, 3)]
    assert embedded_cuesheet(NS(tags=None, info=NS(sample_rate=44100), cuesheet=None), "x.flac") == ""


@needs_ffmpeg
def test_cue_sheet_embedded_in_the_file(db, tmp_path):
    import mutagen

    folder = tmp_path / "Music" / "Rip"
    folder.mkdir(parents=True)
    audio = str(encode(folder / "rip.flac", "flac", seconds=6, title="whole", artist="Aurora Vale"))
    f = mutagen.File(audio)
    f["CUESHEET"] = SHEET.replace("00:04:37", "00:04:00").replace("live.wav", "rip.wav")
    f.save()
    art = tmp_path / "art"
    art.mkdir()

    def scan():
        return Scanner(db, art).scan([str(folder)])

    assert scan()["added"] == 3
    rows = {r["path"]: r for r in db._rows("SELECT * FROM tracks")}
    assert set(rows) == {f"{audio}#01", f"{audio}#02", f"{audio}#03"}
    assert rows[f"{audio}#02"]["title"] == "Harbour Lights" and rows[f"{audio}#02"]["cue_start"] == 2.0
    assert scan()["unchanged"] == 3  # an unchanged file isn't read again
    f = mutagen.File(audio)
    del f["CUESHEET"]
    f.save()
    touch_newer(folder / "rip.flac")
    stats = scan()
    assert stats["added"] == 1 and stats["removed"] == 3


@needs_ffmpeg
def test_cue_songs_get_their_own_waveform(qapp, tmp_path):
    import subprocess

    from hallucinate import waveform as wf

    audio = tmp_path / "steps.flac"  # quiet for 2 s, then loud: the two halves look different
    subprocess.run([FFMPEG, "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                    "aevalsrc='if(lt(t,2),0.05,0.9)*sin(2*PI*440*t)':s=44100:d=4", str(audio)], check=True)
    service = wf.WaveformService(tmp_path / "cache")
    ready = []
    service.ready.connect(ready.append)
    try:
        assert service.request_window("steps#01", str(audio), 0.0, 2.0) is None
        assert service.request_window("steps#02", str(audio), 2.0, 0.0) is None
        assert wait_for(lambda: "steps#01" in ready and "steps#02" in ready, 15)
        quiet, loud = service.peaks("steps#01"), service.peaks("steps#02")
        assert len(quiet) == len(loud) == wf.POINTS
        assert max(quiet) == 1.0 and max(loud) == 1.0  # each is scaled to its own loudest point
        assert (tmp_path / "cache").glob("*.env.npz")
    finally:
        service.shutdown()
    again = wf.WaveformService(tmp_path / "cache")  # a new session cuts it from the cached envelope
    try:
        assert len(again.request_window("steps#02", str(audio), 2.0, 0.0)) == wf.POINTS
    finally:
        again.shutdown()


@needs_ffmpeg
def test_a_last_song_past_the_end_of_the_file_is_not_read_on_every_scan(db, tmp_path):
    folder = tmp_path / "Music" / "Short"
    _album(folder, seconds=3.0)  # the sheet's third song starts at 4 s: past the end, so it has no length
    art = tmp_path / "art"
    art.mkdir()

    def scan():
        return Scanner(db, art).scan([str(folder.parent)])

    assert scan()["added"] == 2
    again = scan()
    assert again["unchanged"] == 2 and again["updated"] == 0 and again["added"] == 0
