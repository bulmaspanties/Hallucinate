"""Library health checks."""
from hallucinate.core import health


def add(db, path, album="A", artist="Band", album_artist=None, year=2000, genre="Pop", track=1, art="/c.jpg",
        codec="FLAC", bitrate=900_000, title=None, duration=100.0):
    aa = album_artist or artist
    db.upsert_track({
        "path": path, "mtime": 0, "size": 1, "title": title or path, "artist": artist,
        "album_artist": aa, "aa_tag": 1, "album": album, "album_key": f"{aa}|{album}", "track_no": track,
        "disc_no": 0, "year": year, "genre": genre, "duration": duration, "fmt": codec, "codec": codec,
        "bitrate": bitrate, "sample_rate": 44100, "art": art,
    })


def by_id(report):
    return {c["id"]: c for c in report["checks"]}


def test_healthy_library(db):
    add(db, "/m/a/1", track=1)
    add(db, "/m/a/2", track=2)
    report = health.report(db)
    assert report["issues"] == 0 and report["score"] == 100 and report["albums"] == 1


def test_finds_each_kind_of_problem(db, tmp_path):
    add(db, "/m/nocover/1", album="Bare", art="", year=0, genre="", track=0)
    add(db, "/m/nocover/2", album="Bare", art="", year=0, genre="", track=0)
    add(db, "/m/split/1", album="Split", artist="X", album_artist="X")
    add(db, "/m/split/2", album="Split", artist="X", album_artist="X feat. Y")
    add(db, "/m/u/1", artist="Unknown Artist", album="Unknown Album")
    add(db, "/m/low/1", album="Low", codec="MP3", bitrate=96_000)
    add(db, "/m/dup/1", album="D1", title="Same", duration=200)
    add(db, "/m/dup/2", album="D2", title="Same", duration=200)
    db.add_folder(str(tmp_path / "gone"))
    checks = by_id(health.report(db))
    assert [a["album"] for a in checks["covers"]["items"]] == ["Bare"]
    assert checks["year"]["count"] == 1 and checks["genre"]["count"] == 1 and checks["numbers"]["count"] == 1
    assert checks["split"]["count"] == 1 and checks["split"]["items"][0]["parts"] == 2
    assert checks["untagged"]["count"] == 1 and checks["untagged"]["items"][0]["path"] == "/m/u/1"
    assert [t["path"] for t in checks["bitrate"]["items"]] == ["/m/low/1"]
    assert checks["duplicates"]["count"] == 2
    assert checks["folders"]["items"] == [{"path": str(tmp_path / "gone")}]
    report = health.report(db)
    assert report["score"] <= 60  # a missing folder caps the score
    assert report["checks"][-1]["count"] == 0 or all(c["count"] for c in report["checks"])  # problems first


def test_library_runs_the_report(qapp, tmp_path, db, scan, music):
    from conftest import wait_for

    from hallucinate.library import Library

    scan(music)
    lib = Library(tmp_path / "lib.db", tmp_path / "art")
    try:
        lib.checkHealth()
        assert wait_for(lambda: lib.health.get("checks") and not lib.health["loading"])
        assert {c["id"] for c in lib.health["checks"]} >= {"covers", "duplicates", "folders"}
    finally:
        lib.shutdown()
