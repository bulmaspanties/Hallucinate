from conftest import make_mp3, wait_for
from mutagen.id3 import ID3, TXXX
from mutagen.oggopus import OggOpus  # noqa: F401

from musicplayer.core.tags import read_replaygain
from musicplayer.userlib import UserLibrary


def paths(db):
    return [t["path"] for t in db.all_tracks()] if hasattr(db, "all_tracks") else [
        r["path"] for r in db._rows("SELECT path FROM tracks ORDER BY path")]


def test_likes_and_playlists(db, scan, music):
    scan(music)
    p = paths(db)
    db.set_liked(p[0], True)
    db.set_liked(p[1], True)
    db.set_liked(p[0], False)
    assert db.liked_paths() == {p[1]}
    assert [t["path"] for t in db.liked_tracks()] == [p[1]]

    pid = db.create_playlist("Road trip")
    db.playlist_add(pid, [p[0], p[1], p[2]])
    assert [t["path"] for t in db.playlist_tracks(pid)] == p[:3]
    db.playlist_move(pid, 0, 2)
    assert [t["path"] for t in db.playlist_tracks(pid)] == [p[1], p[2], p[0]]
    item = db.playlist_tracks(pid)[0]["item_id"]
    db.playlist_remove_item(item)
    assert len(db.playlist_tracks(pid)) == 2
    db.rename_playlist(pid, "Trip")
    assert db.playlists()[0]["name"] == "Trip" and db.playlists()[0]["n"] == 2
    db.delete_playlist(pid)
    assert db.playlists() == []


def test_play_counts(db, scan, music):
    scan(music)
    p = paths(db)
    for _ in range(3):
        db.record_play(p[0])
    db.record_play(p[1])
    top = db.most_played(5)
    assert top[0]["path"] == p[0]
    assert len(db.recently_played_albums(5)) >= 1


def test_userdata_survives_rescan(db, scan, music):
    scan(music)
    p = paths(db)[0]
    db.set_liked(p, True)
    scan(music)
    assert p in db.liked_paths()


def test_lyrics_cache(db, scan, music):
    scan(music)
    p = paths(db)[0]
    assert db.get_lyrics(p) is None
    db.set_lyrics(p, "[00:01.00]hi", "hi", "lrclib")
    assert db.get_lyrics(p)["synced"] == "[00:01.00]hi"


def test_replaygain_id3(tmp_path):
    f = tmp_path / "a.mp3"
    make_mp3(f, "t", "a", "b")
    tags = ID3(f)
    tags.add(TXXX(encoding=3, desc="REPLAYGAIN_TRACK_GAIN", text="-6.50 dB"))
    tags.add(TXXX(encoding=3, desc="replaygain_album_gain", text="-4.00 dB"))
    tags.add(TXXX(encoding=3, desc="REPLAYGAIN_TRACK_PEAK", text="0.98"))
    tags.save(f)
    assert read_replaygain(ID3(f)) == (-6.5, -4.0, 0.98)


def test_replaygain_vorbis_and_r128():
    assert read_replaygain({"replaygain_track_gain": ["+1.5 dB"]})[0] == 1.5
    t, _, _ = read_replaygain({"r128_track_gain": ["-256"]})
    assert t == 4.0
    assert read_replaygain(None) == (None, None, None)


def test_scan_stores_replaygain(db, scan, tmp_path):
    root = tmp_path / "m"
    root.mkdir()
    f = root / "a.mp3"
    make_mp3(f, "t", "a", "b")
    tags = ID3(f)
    tags.add(TXXX(encoding=3, desc="REPLAYGAIN_TRACK_GAIN", text="-7.0 dB"))
    tags.save(f)
    scan(root)
    assert db._rows("SELECT rg_track FROM tracks")[0]["rg_track"] == -7.0


def test_userlibrary_async(qapp, tmp_path, db, scan, music):
    scan(music)
    p = paths(db)
    ul = UserLibrary(db.path if hasattr(db, "path") else tmp_path / "lib.db")
    try:
        ul.toggleLike(p[0])
        assert ul.isLiked(p[0])
        assert wait_for(lambda: ul.likedTracks.count == 1)
        pid = ul.createPlaylist("Mix")
        ul.addToPlaylist(pid, p[1])
        ul.openPlaylist(pid)
        assert wait_for(lambda: ul.playlistTracks.count == 1)
        ul.recordPlay({"path": p[1]})
        assert wait_for(lambda: ul.mostPlayed.count == 1)
        ul.toggleLike(p[0])
        assert wait_for(lambda: ul.likedTracks.count == 0)
    finally:
        ul.shutdown()
