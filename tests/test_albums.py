"""Album views: liner notes, the colour wall's order and cache, and the timeline."""
from hallucinate.core import albums as album_views


def add(db, path, album, year=2000, artist="Band", codec="FLAC", disc=0, genre="Dream Pop", size=1000, rate=44100):
    db.upsert_track({
        "path": path, "mtime": 0, "size": size, "title": path.rsplit("/", 1)[1], "artist": artist,
        "album_artist": artist, "aa_tag": 1, "album": album, "album_key": f"{artist}|{album}", "track_no": 1,
        "disc_no": disc, "year": year, "genre": genre, "duration": 100.0, "fmt": codec, "codec": codec,
        "bitrate": 900_000, "sample_rate": rate,
    })


def test_liner_notes(db):
    add(db, "/m/a1", "Sleeve", disc=1, genre="Dream Pop; Shoegaze")
    add(db, "/m/a2", "Sleeve", disc=2, rate=96000)
    db.record_play("/m/a1", 1_000)
    db.record_play("/m/a1", 2_000)
    db.record_play("/m/a2", 1_500)
    db.set_liked("/m/a2", True)
    db.commit()
    notes = album_views.liner_notes(db, "Band|Sleeve")
    assert notes["genres"] == ["Dream Pop", "Shoegaze"] and notes["discs"] == 2
    assert notes["formats"] == ["FLAC"] and notes["lossless"] and notes["sampleRates"] == [44100, 96000]
    assert notes["bytes"] == 2000 and notes["plays"] == 3 and notes["liked"] == 1
    assert notes["firstPlayed"] == 1_000 and notes["lastPlayed"] == 2_000
    assert notes["trackPlays"] == {"/m/a1": 2, "/m/a2": 1}
    assert album_views.liner_notes(db, "nope") == {}


def colour(hue, sat=0.8, val=0.8):
    return {"color": "#000000", "hue": hue, "sat": sat, "val": val}


def test_colour_order():
    albums = [
        {"album": "none"},
        {"album": "white", "cover": colour(0.0, 0.05, 0.95)},
        {"album": "blue", "cover": colour(0.62)},
        {"album": "black", "cover": colour(0.5, 0.6, 0.05)},
        {"album": "red", "cover": colour(0.01)},
        {"album": "dark red", "cover": colour(0.02, 0.8, 0.4)},
        {"album": "green", "cover": colour(0.33)},
    ]
    ordered = [a["album"] for a in sorted(albums, key=album_views.colour_order)]
    assert ordered == ["red", "dark red", "green", "blue", "white", "black", "none"]


def test_colour_cache_round_trip(db):
    add(db, "/m/a", "Kept")
    album_views.store_colors(db, {"Band|Kept": ("/art/k.jpg", colour(0.5)), "Band|Gone": ("/art/g.jpg", colour(0.1))})
    cached = album_views.cached_colors(db)
    assert set(cached) == {"Band|Kept"}  # colours of albums no longer in the library are dropped
    assert cached["Band|Kept"][0] == "/art/k.jpg" and cached["Band|Kept"][1]["hue"] == 0.5


def test_timeline_groups_by_decade_and_year():
    albums = [{"album": "B", "album_artist": "y", "year": 1994}, {"album": "A", "album_artist": "x", "year": 1994},
              {"album": "C", "album_artist": "x", "year": 2003}, {"album": "D", "album_artist": "x", "year": 0},
              {"album": "E", "album_artist": "x", "year": 1999}]
    out = album_views.timeline(albums)
    assert [d["decade"] for d in out] == ["1990s", "2000s", "Unknown year"]
    assert out[0]["count"] == 3 and [y["year"] for y in out[0]["years"]] == [1994, 1999]
    assert [a["album"] for a in out[0]["years"][0]["albums"]] == ["A", "B"]


def test_library_wall_timeline_and_notes(qapp, tmp_path, db, scan, music):
    from conftest import wait_for

    from hallucinate.library import Library

    from PySide6.QtGui import QColor, QImage

    scan(music)
    arts = {r[0] for r in db.conn.execute("SELECT DISTINCT art FROM tracks WHERE art != ''")}
    assert arts
    red = QImage(32, 32, QImage.Format.Format_RGB32)
    red.fill(QColor("#c02828"))
    for art in arts:  # the fixture's cover is a stub; give it real pixels to measure
        assert red.save(art, "PNG")
    lib = Library(tmp_path / "lib.db", tmp_path / "art")
    try:
        assert wait_for(lambda: lib.albumCount >= 2 and lib.timeline)
        kinds = [r["kind"] for r in lib.timeline]
        assert kinds[0] == "decade" and "year" in kinds
        lib.loadAlbumWall()
        assert wait_for(lambda: lib.albumWall.count == lib.albums.count and not lib.wallLoading)
        with_art = [lib.albumWall.get(i) for i in range(lib.albumWall.count) if lib.albumWall.get(i)["artUrl"]]
        assert with_art and all(a["color"] == "#c02828" for a in with_art)
        assert lib.albumWall.get(lib.albumWall.count - 1)["color"] == ""  # no cover: last
        key = with_art[0]["album_key"]
        assert lib.albumNotes(key)["formats"] and len(lib.albumPalette(key)) >= 0
        lib.loadAlbumWall()  # the second time the colours come from the cache
        assert wait_for(lambda: not lib.wallLoading)
        assert lib.albumWall.get(0)["color"] == with_art[0]["color"]
    finally:
        lib.shutdown()
