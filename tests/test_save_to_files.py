"""What you change in the app reaching the files: star ratings in the songs' tags, covers as cover.jpg in the
album's folder, and a cover you chose staying chosen."""
import os

import mutagen
import pytest
from audio import FFMPEG, encode
from conftest import make_mp3, wait_for
from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QSettings
from PySide6.QtGui import QImage

from hallucinate.core import tagedit
from hallucinate.core.db import Database
from hallucinate.core.scanner import Scanner
from hallucinate.core.tags import read_rating

needs_ffmpeg = pytest.mark.skipif(not FFMPEG, reason="ffmpeg not installed")


def _image(fmt, color=0xFF3366):
    img = QImage(8, 8, QImage.Format.Format_RGB32)
    img.fill(color)
    out = QByteArray()
    buf = QBuffer(out)
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    img.save(buf, fmt)
    return bytes(out.data())


@pytest.fixture(autouse=True)
def _restore_settings():
    settings = QSettings("hallucinate", "hallucinate")
    keys = ("ratings/inFiles", "covers/toFolder", "covers/embed")
    before = {k: settings.value(k) for k in keys}
    yield
    for k, v in before.items():
        settings.remove(k) if v is None else settings.setValue(k, v)


@pytest.mark.parametrize("ext", ["mp3", "flac", "ogg", "opus", "m4a", "wma", "wv"])
@needs_ffmpeg
def test_a_rating_round_trips_through_the_files_tags(tmp_path, ext):
    path = encode(tmp_path / f"song.{ext}", ext, seconds=0.5, title="Song")
    for stars in (1, 3, 5):
        tagedit.write_rating(path, stars)
        assert read_rating(mutagen.File(path).tags) == stars, (ext, stars)
    tagedit.write_rating(path, 0)
    assert read_rating(mutagen.File(path).tags) == 0  # cleared in the app: gone from the file too
    assert not [n for n in os.listdir(tmp_path) if n.endswith(".hallucinate-tmp")]


def test_a_plain_one_in_rating_is_one_star_not_five():
    assert read_rating({"RATING": ["1"]}) == 1  # foobar2000 writes 1-5
    assert read_rating({"RATING": ["1.0"]}) == 5  # a fraction
    assert read_rating({"FMPS_RATING": ["0.2"]}) == 1
    assert read_rating({"RATING": ["80"]}) == 4


def test_mp3_ratings_keep_the_play_count_other_players_stored(tmp_path):
    from mutagen import id3

    path = tmp_path / "a.mp3"
    make_mp3(path, "A", "B", "C")
    f = mutagen.File(path)
    f.tags.add(id3.POPM(email="foo@bar", rating=128, count=42))
    f.save()
    tagedit.write_rating(path, 5)
    frames = mutagen.File(path).tags.getall("POPM")
    assert len(frames) == 1 and frames[0].rating == 255 and frames[0].count == 42


def test_rating_in_the_app_reaches_the_file_unless_switched_off(qapp, tmp_path):
    from hallucinate.userlib import UserLibrary

    root = tmp_path / "Music"
    root.mkdir()
    song = root / "a.mp3"
    make_mp3(song, "A", "B", "C")
    db = Database(tmp_path / "lib.db")
    Scanner(db, tmp_path / "art").scan([str(root)])
    db.close()
    ul = UserLibrary(tmp_path / "lib.db")
    try:
        ul.setRatingsInFiles(True)
        ul.setRating(str(song), 4)
        assert wait_for(lambda: read_rating(mutagen.File(song).tags) == 4)
        ul.setRatingsInFiles(False)
        ul.setRating(str(song), 2)
        assert wait_for(lambda: ul.rating(str(song)) == 2)
        ul._bulk.submit(lambda _db: None)  # let anything queued finish
        assert read_rating(mutagen.File(song).tags) == 4  # left alone
    finally:
        ul.shutdown()


def _album(tmp_path, name, album, n=2, folder=None):
    folder = folder or tmp_path / "Music" / name
    folder.mkdir(parents=True, exist_ok=True)
    for i in range(n):
        make_mp3(folder / f"{album}-{i}.mp3", f"T{i}", "Artist", album, "Artist", str(i + 1))
    return folder


def _editor(tmp_path):
    from hallucinate.metaedit import MetadataEditor

    db = Database(tmp_path / "lib.db")
    Scanner(db, tmp_path / "art").scan([str(tmp_path / "Music")])
    keys = {r["album"]: r["album_key"] for r in db._rows("SELECT DISTINCT album, album_key FROM tracks")}
    db.close()
    return MetadataEditor(tmp_path / "lib.db", tmp_path / "art"), keys


def test_a_cover_you_add_is_saved_as_cover_jpg_in_its_own_folder(qapp, tmp_path):
    from hallucinate.metaedit import save_folder_cover

    folder = _album(tmp_path, "One", "One")
    ed, keys = _editor(tmp_path)
    try:
        db = Database(tmp_path / "lib.db")
        files = [r["path"] for r in db.album_tracks(keys["One"])]
        assert save_folder_cover(db, keys["One"], files, _image("PNG")) == str(folder)
        data = (folder / "cover.jpg").read_bytes()
        assert data[:3] == b"\xff\xd8\xff"  # a PNG is saved as a real JPEG
        db.close()
    finally:
        ed.shutdown()


def test_a_folder_shared_by_several_albums_gets_no_cover_jpg(qapp, tmp_path):
    from hallucinate.metaedit import save_folder_cover

    shared = tmp_path / "Music" / "Singles"
    _album(tmp_path, "Singles", "First", folder=shared)
    _album(tmp_path, "Singles", "Second", folder=shared)
    ed, keys = _editor(tmp_path)
    try:
        db = Database(tmp_path / "lib.db")
        files = [r["path"] for r in db.album_tracks(keys["First"])]
        assert save_folder_cover(db, keys["First"], files, _image("JPEG")) == ""
        assert not (shared / "cover.jpg").exists()  # it would have become every single's cover
        db.close()
    finally:
        ed.shutdown()


def test_a_chosen_cover_stays_when_the_songs_are_read_again(qapp, tmp_path):
    root = tmp_path / "Music"
    folder = _album(tmp_path, "Album", "Album")
    for p in folder.iterdir():
        tagedit.embed_cover(p, _image("JPEG", 0x00FF00))  # the files' own picture
    ed, keys = _editor(tmp_path)
    try:
        ed.setCoversToFolder(False)
        ed.setCoverFromFile(keys["Album"], str(_write(tmp_path / "pick.png", _image("PNG"))), False)
        db = Database(tmp_path / "lib.db")
        assert wait_for(lambda: db.chosen_art(keys["Album"]) is not None)
        chosen = db.chosen_art(keys["Album"])
        for p in folder.iterdir():
            os.utime(p, None)
            st = os.stat(p)
            os.utime(p, ns=(st.st_atime_ns, st.st_mtime_ns + 5_000_000_000))  # changed: read again
        Scanner(db, tmp_path / "art").scan([str(root)])
        arts = {r["art"] for r in db.album_tracks(keys["Album"])}
        assert arts == {chosen}  # not swapped back for the embedded one
        db.close()
    finally:
        ed.shutdown()


def _write(path, data):
    path.write_bytes(data)
    return path


@needs_ffmpeg
def test_clearing_a_field_in_a_wma_file_saves(tmp_path):
    path = encode(tmp_path / "a.wma", "wma", seconds=0.5, title="Song", genre="Rock")
    tagedit.write_tags(path, {"genre": "", "title": "New"})
    tags = mutagen.File(path).tags
    assert "WM/Genre" not in tags and str(tags["Title"][0]) == "New"
