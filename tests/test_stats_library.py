import sqlite3
import time

from conftest import wait_for

from hallucinate.core.db import Database
from hallucinate.library import Library
from hallucinate.userlib import UserLibrary


def test_listening_stats_periods_and_imported_history(db, scan, music):
    scan(music)
    tracks = db._rows("SELECT * FROM tracks ORDER BY path")
    first, second = tracks[:2]
    now = time.time()
    db.record_play(first["path"], now - 20)
    db.record_play(first["path"], now - 10)
    db.record_play(second["path"], now - 8 * 86400)
    db.import_plays(
        [{"ts": now - 5, "artist": "Unknown Artist", "title": "Unmatched song",
          "album": "Unreleased", "duration": 210}],
        "listenbrainz",
    )

    all_time = db.listening_stats()
    assert all_time["listens"] == 3
    assert all_time["tracks"][0]["path"] == first["path"]
    assert all_time["tracks"][0]["plays"] == 2
    assert abs(all_time["listeningSeconds"] - (first["duration"] * 2 + second["duration"])) < 1e-6

    recent = db.listening_stats(now - 7 * 86400)
    assert recent["listens"] == 3  # Includes the unmatched imported listen.
    assert {row["path"] for row in recent["tracks"]} == {first["path"]}
    assert recent["listeningSeconds"] >= first["duration"] * 2 + 210
    assert any(row["name"] == "Unknown Artist" for row in recent["artists"])
    assert any(row["album"] == "Unreleased" for row in recent["albums"])


def test_home_mix_uses_likes_and_plays_with_artist_variety(db, scan, music):
    scan(music)
    tracks = db._rows("SELECT * FROM tracks ORDER BY path")
    db.record_play(tracks[0]["path"])
    db.record_play(tracks[1]["path"])
    db.record_play(tracks[2]["path"])
    db.set_liked(tracks[3]["path"], True)

    mix = db.home_mix(10)
    paths = [track["path"] for track in mix]
    assert set(paths) == {track["path"] for track in tracks}
    assert len(paths) == len(set(paths))
    assert tracks[3]["path"] in paths  # Liked tracks are included even without play counts.
    assert mix[0]["artist"] != mix[1]["artist"]  # Artist round-robin prevents clumping.


def test_filter_values_filtered_tracks_and_duplicate_detection(db, scan, music):
    scan(music)
    rows = db._rows("SELECT * FROM tracks ORDER BY path")
    first = dict(rows[0])
    for row in rows:
        db.conn.execute(
            "UPDATE tracks SET genre=?, year=?, fmt=? WHERE id=?",
            ("Ambient", 2024, "MP3" if row["path"].endswith(".mp3") else "WAV", row["id"]),
        )
    duplicate = dict(first)
    duplicate.update(path=first["path"] + ".copy", mtime=1, size=first["size"] + 1)
    db.upsert_track(duplicate)
    db.conn.commit()

    values = db.filter_values()
    assert values == {
        "genres": ["Ambient"],
        "years": [2024],
        "formats": ["MP3", "WAV"],
    }
    assert all(row["genre"] == "Ambient" for row in db.filtered_tracks("Ambient"))
    assert all(row["year"] == 2024 for row in db.filtered_tracks(year=2024))
    assert all(row["fmt"] == "MP3" for row in db.filtered_tracks(fmt="MP3"))
    duplicates = db.duplicate_tracks()
    assert len(duplicates) == 2
    assert {row["duplicate_count"] for row in duplicates} == {2}


def test_play_log_duration_column_migrates(tmp_path):
    path = tmp_path / "legacy.db"
    conn = sqlite3.connect(path)
    conn.execute(
        """CREATE TABLE play_log(
             id INTEGER PRIMARY KEY, ts REAL NOT NULL, path TEXT, artist TEXT NOT NULL DEFAULT '',
             title TEXT NOT NULL DEFAULT '', album TEXT NOT NULL DEFAULT '',
             source TEXT NOT NULL DEFAULT 'local', UNIQUE(ts, artist, title))"""
    )
    conn.commit()
    conn.close()

    db = Database(path)
    try:
        columns = {row["name"] for row in db.conn.execute("PRAGMA table_info(play_log)")}
        assert "duration" in columns
        assert db.conn.execute(
            "SELECT dflt_value FROM pragma_table_info('play_log') WHERE name='duration'"
        ).fetchone()[0] == "0"
    finally:
        db.close()


def test_library_filters_and_duplicate_results_are_worker_backed(
    qapp, tmp_path, db, scan, music
):
    scan(music)
    rows = db._rows("SELECT * FROM tracks ORDER BY path")
    for row in rows:
        db.conn.execute(
            "UPDATE tracks SET genre='Ambient', year=2024, fmt='MP3' WHERE id=?",
            (row["id"],),
        )
    duplicate = dict(rows[0])
    duplicate.update(
        path=duplicate["path"] + ".copy",
        mtime=1,
        size=duplicate["size"] + 1,
        genre="Ambient",
        year=2024,
        fmt="MP3",
    )
    db.upsert_track(duplicate)
    db.conn.commit()

    library = Library(db.conn.execute("PRAGMA database_list").fetchone()["file"], tmp_path / "art")
    try:
        assert wait_for(lambda: library.ready)
        assert library.genres == ["Ambient"]
        library.filterTracks("Ambient", 2024, "MP3")
        assert wait_for(lambda: library.filteredTracks.count == len(rows) + 1)
        library.findDuplicates()
        assert wait_for(lambda: not library.duplicatesLoading)
        assert library.duplicates.count == 2
    finally:
        library.shutdown()


def test_user_library_stats_refresh_asynchronously(tmp_path, db, scan, music, qapp):
    scan(music)
    tracks = db._rows("SELECT * FROM tracks ORDER BY path")
    now = time.time()
    db.record_play(tracks[0]["path"], now - 10)
    db.record_play(tracks[0]["path"], now - 5)

    user_library = UserLibrary(tmp_path / "lib.db")
    try:
        assert wait_for(lambda: user_library.topTracks.count == 1)
        assert user_library.topTracks.get(0)["plays"] == 2
        user_library.setStatsPeriod("7d")
        assert wait_for(lambda: user_library.statsSummary["listens"] == 2)
        assert user_library.statsSummary["listeningSeconds"] > 0
    finally:
        user_library.shutdown()
