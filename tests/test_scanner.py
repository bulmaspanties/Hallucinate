import shutil

from conftest import make_mp3, touch_newer


def test_initial_scan(db, scan, music):
    stats = scan(music)
    assert stats["added"] == 4
    assert stats["errors"] == 1  # junk.mp3
    assert db.counts() == {"tracks": 4, "albums": 3, "artists": 3}


def test_tags_and_albums(db, scan, music):
    scan(music)
    albums = {a["album"]: a for a in db.albums()}
    nl = albums["Northern Lights"]
    assert nl["n"] == 2 and nl["album_artist"] == "Aurora Vale"
    assert nl["art"] and nl["art"].endswith(".png")
    tracks = db.album_tracks(nl["album_key"])
    assert [t["title"] for t in tracks] == ["Echoes of Dawn", "Midnight Rain"]
    assert tracks[0]["track_no"] == 1 and tracks[0]["duration"] > 0
    assert tracks[1]["art"] == nl["art"]
    assert albums["Tidal"]["n"] == 1  # WAV with ID3 tags
    loose = albums["Unknown Album"]
    assert db.album_tracks(loose["album_key"])[0]["title"] == "loose"


def test_incremental_rescan_skips_unchanged(db, scan, music):
    scan(music)
    stats = scan(music)
    assert (stats["added"], stats["updated"], stats["removed"]) == (0, 0, 0)
    assert stats["unchanged"] == 4


def test_modified_and_removed(db, scan, music):
    scan(music)
    p = music / "Aurora Vale" / "Northern Lights" / "02.mp3"
    make_mp3(p, "Sunrise Static", "Aurora Vale", "Northern Lights", "Aurora Vale", "2/2")
    touch_newer(p)
    assert scan(music)["updated"] == 1
    assert db.search("sunrise")["tracks"] and not db.search("midnight")["tracks"]

    p.unlink()
    assert scan(music)["removed"] == 1
    assert not db.search("sunrise")["tracks"]


def test_missing_folder_keeps_library(db, scan, music, tmp_path):
    scan(music)
    moved = tmp_path / "gone"
    shutil.move(str(music), str(moved))
    stats = scan(music)
    assert stats["removed"] == 0 and db.counts()["tracks"] == 4


def test_various_artists(db, scan, tmp_path):
    d = tmp_path / "comp"
    d.mkdir()
    make_mp3(d / "1.mp3", "One", "Alpha", "Mix")
    make_mp3(d / "2.mp3", "Two", "Beta", "Mix")
    scan(d)
    assert db.albums()[0]["album_artist"] == "Various Artists"


def test_remove_folder(db, scan, music):
    scan(music)
    db.add_folder(str(music))
    db.remove_folder(str(music))
    assert db.counts()["tracks"] == 0 and db.folders() == []
