import os
import shutil
import time

import pytest
from conftest import make_mp3

from musicplayer.core.db import Database


def mk(path, title, artist="Art", album="Alb", aa=None, track=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    make_mp3(path, title, artist, album, aa, track)
    return path


def test_rename_and_move_are_tracked(db, scan, tmp_path):
    root = tmp_path / "lib"
    p = mk(root / "A" / "x.mp3", "Song X")
    scan(root)
    p.rename(root / "A" / "renamed.mp3")
    st = scan(root)
    assert (st["added"], st["removed"]) == (1, 1)
    assert db.counts()["tracks"] == 1
    shutil.move(str(root / "A"), str(root / "B"))
    st = scan(root)
    assert (st["added"], st["removed"]) == (1, 1)
    assert db.search("song")["tracks"][0]["path"].startswith(str(root / "B"))


def test_delete_everything_then_restore(db, scan, tmp_path):
    root = tmp_path / "lib"
    mk(root / "a.mp3", "One")
    mk(root / "b.mp3", "Two")
    scan(root)
    for f in root.glob("*.mp3"):
        f.unlink()
    assert scan(root)["removed"] == 2
    assert db.counts() == {"tracks": 0, "albums": 0, "artists": 0}
    assert db.search("one")["tracks"] == []


def test_non_ascii_paths_and_search(db, scan, tmp_path):
    root = tmp_path / "Музыка"
    mk(root / "日本語のアーティスト" / "アルバム" / "01 – Ünïcödé ♪.mp3", "Ünïcödé ♪ Tïtle", "Björk", "Homogénic")
    mk(root / "Русская" / "1.mp3", "Привет мир", "Кино", "Группа крови")
    mk(root / "emoji" / "1.mp3", "🔥 Fire 🔥", "DJ 😀", "Hot")
    scan(root)
    assert db.counts()["tracks"] == 3
    assert db.search("bjork")["tracks"], "diacritics folded"
    assert db.search("bjork")["artists"], "artist results fold accents"
    assert db.search("HOMOGENIC")["albums"]
    assert db.search("привет")["tracks"] and db.search("ПРИВ")["tracks"]
    assert db.search("кино")["artists"]
    assert db.search("fire")["tracks"]
    t = db.search("unicode")["tracks"] or db.search("ünï")["tracks"]
    assert t and os.path.exists(t[0]["path"])


@pytest.mark.parametrize("q", ['AC/DC', '"', "*", "-", "(", ")", "a b c d e f g", "'; DROP TABLE tracks;--", "NEAR", "AND", "OR",
                                "title:foo", "%", "_", "\\", "   ", "\x00", "é" * 500])
def test_hostile_queries_do_not_crash(db, scan, tmp_path, q):
    mk(tmp_path / "l" / "a.mp3", "AC/DC Thunder", "AC/DC", "Back in Black")
    scan(tmp_path / "l")
    r = db.search(q)
    assert set(r) == {"tracks", "albums", "artists"}
    assert db.counts()["tracks"] == 1


def test_acdc_found(db, scan, tmp_path):
    mk(tmp_path / "l" / "a.mp3", "Thunderstruck", "AC/DC", "The Razors Edge")
    scan(tmp_path / "l")
    assert db.search("ac/dc")["artists"] and db.search("ac/dc")["tracks"]
    assert not db.search("acdc")["tracks"]  # slash is a token boundary
    assert db.search("razors")["albums"]


def test_symlink_loop_terminates(db, scan, tmp_path):
    root = tmp_path / "l"
    mk(root / "sub" / "a.mp3", "Looped")
    os.symlink(root, root / "sub" / "loop")
    t0 = time.time()
    scan(root)
    assert time.time() - t0 < 10
    assert db.counts()["tracks"] == 1


def test_hidden_dirs_skipped_and_case_insensitive_ext(db, scan, tmp_path):
    root = tmp_path / "l"
    mk(root / ".hidden" / "a.mp3", "Hidden")
    p = mk(root / "b.mp3", "Loud Ext")
    p.rename(root / "B.MP3")
    scan(root)
    assert [t["title"] for t in db.tracks()] == ["Loud Ext"]


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores permissions")
def test_unreadable_file_and_dir(db, scan, tmp_path):
    root = tmp_path / "l"
    ok = mk(root / "ok.mp3", "Fine")
    bad = mk(root / "bad.mp3", "Nope")
    locked = mk(root / "locked" / "x.mp3", "Locked")
    os.chmod(bad, 0)
    os.chmod(locked.parent, 0)
    try:
        st = scan(root)
        assert st["added"] == 1 and st["errors"] >= 1
    finally:
        os.chmod(bad, 0o644)
        os.chmod(locked.parent, 0o755)
    st = scan(root)  # permissions restored: picked up on next scan
    assert db.counts()["tracks"] == 3


def test_file_removed_during_scan_is_ignored(db, tmp_path, monkeypatch):
    from musicplayer.core import tags
    from musicplayer.core.scanner import Scanner
    root = tmp_path / "l"
    a = mk(root / "a.mp3", "A")
    b = mk(root / "b.mp3", "B")
    real = tags.read_track

    def racy(path, art_known=None):
        if path.endswith("a.mp3"):
            os.unlink(b)
        return real(path, art_known)

    monkeypatch.setattr(tags, "read_track", racy)
    st = Scanner(db, tmp_path).scan([str(root)])
    assert st["added"] >= 1


def test_stop_request_halts_scan(db, tmp_path):
    from musicplayer.core.scanner import Scanner
    root = tmp_path / "l"
    for i in range(5):
        mk(root / f"{i}.mp3", f"T{i}")
    Scanner(db, tmp_path, should_stop=lambda: True).scan([str(root)])
    assert db.counts()["tracks"] == 0


def test_modified_art_and_folder_cover(db, scan, tmp_path):
    root = tmp_path / "l"
    mk(root / "alb" / "1.mp3", "One", "Art", "Alb")
    (root / "alb" / "Folder.JPG").write_bytes(b"\xff\xd8\xff\xe0jpeg")
    scan(root)
    assert db.albums()[0]["art"].endswith("Folder.JPG")


def test_removing_folder_removes_tracks(db, scan, tmp_path):
    root = tmp_path / "l"
    mk(root / "a.mp3", "A")
    db.add_folder(str(root))
    scan(root)
    db.remove_folder(str(root))
    assert db.counts()["tracks"] == 0 and db.folders() == []


def test_sibling_prefix_folders_not_confused(db, scan, tmp_path):
    a, b = tmp_path / "Music", tmp_path / "Music2"
    mk(a / "a.mp3", "A")
    mk(b / "b.mp3", "B")
    scan(a)
    scan(b)
    shutil.rmtree(a)
    mk(a / "c.mp3", "C")
    scan(a)
    assert sorted(t["title"] for t in db.tracks()) == ["B", "C"]


# ---- scale ----------------------------------------------------------------
def _bulk(d, n, aa_tag=1):
    for i in range(n):
        a = i // 12
        ar = a // 8
        d.upsert_track(dict(
            path=f"/m/Artist {ar}/Album {a}/{i % 12:02d} Song {i}.flac", mtime=1.0, size=5,
            title=f"Song number {i} café", artist=f"Artist {ar}", album_artist=f"Artist {ar}", aa_tag=aa_tag,
            album=f"Album {a}", album_key=f"k{a}", track_no=i % 12, disc_no=1, year=2000 + a % 20, genre="x",
            duration=200.0, fmt="FLAC", bitrate=900000, sample_rate=44100, art=None))
    d.commit()


@pytest.fixture(scope="module")
def big(tmp_path_factory):
    d = Database(tmp_path_factory.mktemp("big") / "big.db")
    _bulk(d, 50_000, aa_tag=0)
    t0 = time.time()
    d.finalize()
    d.finalize_time = time.time() - t0
    yield d
    d.close()


def test_50k_finalize_is_fast(big):
    assert big.finalize_time < 5
    assert big.counts()["tracks"] == 50_000


@pytest.mark.parametrize("q", ["s", "so", "song", "song number 4", "caf", "artist 12", "album 99", "zzz", "123"])
def test_50k_search_is_instant(big, q):
    t0 = time.perf_counter()
    r = big.search(q)
    assert time.perf_counter() - t0 < 0.4, q
    if q in ("song", "caf"):
        assert len(r["tracks"]) == 30


def test_50k_browse_queries(big):
    for fn in (big.albums, big.artists, big.recent_albums):
        t0 = time.perf_counter()
        fn()
        assert time.perf_counter() - t0 < 1.0
    t0 = time.perf_counter()
    assert len(big.album_tracks("k5")) == 12
    assert time.perf_counter() - t0 < 0.05


def test_50k_incremental_rescan_does_not_reparse(big, tmp_path):
    t0 = time.perf_counter()
    assert len(big.paths_under("/m")) == 50_000
    assert time.perf_counter() - t0 < 1.0


def test_old_database_is_migrated(tmp_path):
    import sqlite3
    path = tmp_path / "old.db"
    c = sqlite3.connect(path)
    c.executescript("""CREATE TABLE tracks(id INTEGER PRIMARY KEY, path TEXT NOT NULL UNIQUE, mtime REAL NOT NULL,
      size INTEGER NOT NULL, title TEXT NOT NULL, artist TEXT NOT NULL, album_artist TEXT NOT NULL,
      aa_tag INTEGER NOT NULL DEFAULT 0, album TEXT NOT NULL, album_key TEXT NOT NULL, track_no INTEGER NOT NULL DEFAULT 0,
      disc_no INTEGER NOT NULL DEFAULT 0, year INTEGER NOT NULL DEFAULT 0, genre TEXT NOT NULL DEFAULT '',
      duration REAL NOT NULL DEFAULT 0, fmt TEXT NOT NULL DEFAULT '', bitrate INTEGER NOT NULL DEFAULT 0,
      sample_rate INTEGER NOT NULL DEFAULT 0, art TEXT, added REAL NOT NULL);
      INSERT INTO tracks(path,mtime,size,title,artist,album_artist,album,album_key,added)
      VALUES('/x/a.mp3',1,1,'Ünï','Bjørk','Bjørk','Hömogenic','k',1);""")
    c.commit()
    c.close()
    d = Database(path)
    assert d.search("homogenic")["albums"] and d.artists()[0]["name"] == "Bjørk"
    d.close()


def test_artist_grouping_is_case_and_accent_insensitive(db, scan, tmp_path):
    root = tmp_path / "l"
    mk(root / "1.mp3", "A", "КИНО", "X", "КИНО")
    mk(root / "2.mp3", "B", "кино", "Y", "кино")
    mk(root / "3.mp3", "C", "Beyoncé", "Z", "Beyoncé")
    mk(root / "4.mp3", "D", "BEYONCE", "W", "BEYONCE")
    scan(root)
    assert len(db.artists()) == 2
    assert len(db.artist_albums("кино")) == 2
