"""Star ratings: storage, tags from other players, smart playlist rules, the UserLibrary API."""
import pytest

from hallucinate.core import rules
from hallucinate.core.tags import read_rating


class Popm:
    def __init__(self, rating):
        self.rating = rating


@pytest.mark.parametrize("tags,stars", [
    ({"POPM:Windows Media Player 9 Series": Popm(1)}, 1),
    ({"POPM:no@email": Popm(64)}, 2),
    ({"POPM:x": Popm(128)}, 3),
    ({"POPM:x": Popm(196)}, 4),
    ({"POPM:x": Popm(255)}, 5),
    ({"POPM:x": Popm(0)}, 0),
    ({"rating": ["80"]}, 4),          # 0–100 (foobar2000, many Vorbis taggers)
    ({"RATING": ["5"]}, 5),           # 1–5
    ({"FMPS_RATING": ["0.6"]}, 3),    # 0.0–1.0
    ({"TXXX:FMPS_Rating": ["1.0"]}, 5),
    ({"title": ["no rating"]}, 0),
    (None, 0),
])
def test_ratings_from_other_players(tags, stars):
    assert read_rating(tags) == stars


def add(db, path, rating=0):
    db.upsert_track({
        "path": path, "mtime": 0, "size": 1, "title": path, "artist": "A", "album_artist": "A", "aa_tag": 1,
        "album": "B", "album_key": "A|B", "track_no": 1, "disc_no": 0, "year": 2000, "genre": "",
        "duration": 100.0, "fmt": "FLAC", "codec": "FLAC", "bitrate": 0, "sample_rate": 44100, "rating": rating,
    })


def test_storage_and_tag_ratings_never_override_yours(db):
    add(db, "/a", rating=3)
    add(db, "/b")
    assert db.ratings() == {"/a": 3}
    db.set_rating("/a", 5)
    add(db, "/a", rating=2)  # a rescan with the old tag keeps your rating
    assert db.ratings()["/a"] == 5
    db.set_rating("/b", 9)
    assert db.ratings()["/b"] == 5
    db.set_rating("/b", 0)
    assert "/b" not in db.ratings()


def test_smart_playlists_use_ratings(db):
    for p, r in (("/one", 1), ("/four", 4), ("/five", 5), ("/none", 0)):
        add(db, p, rating=r)
    four_up = {"match": "all", "rules": [{"field": "rating", "op": "ge", "value": 4}], "sort": "rating_desc", "limit": 0}
    assert [t["path"] for t in rules.matching_tracks(db, four_up)] == ["/five", "/four"]
    unrated = {"match": "all", "rules": [{"field": "rating", "op": "eq", "value": 0}], "sort": "title", "limit": 0}
    assert [t["path"] for t in rules.matching_tracks(db, unrated)] == ["/none"]
    assert rules.describe(four_up).startswith("Rating (stars) is at least 4")


def test_user_library_ratings(qapp, db):
    from conftest import wait_for

    from hallucinate.userlib import UserLibrary

    add(db, "/a")
    db.commit()
    ul = UserLibrary(db.conn.execute("PRAGMA database_list").fetchone()["file"])
    try:
        assert ul.rating("/a") == 0
        rev = ul.likesRevision
        ul.setRating("/a", 4)
        assert ul.rating("/a") == 4 and ul.likesRevision > rev
        assert wait_for(lambda: db.ratings().get("/a") == 4)
        ul.setRating("/a", 4)  # clicking the same rating clears it
        assert ul.rating("/a") == 0
        assert wait_for(lambda: "/a" not in db.ratings())
    finally:
        ul.shutdown()


def test_a_refresh_read_before_a_rating_does_not_undo_it(qapp, db):
    from hallucinate.userlib import UserLibrary

    add(db, "/a")
    db.commit()
    ul = UserLibrary(db.conn.execute("PRAGMA database_list").fetchone()["file"])
    try:
        stale = {"edits": ul._edits, "liked_paths": set(), "ratings": {}, "playlists": [], "liked": [],
                 "mostPlayed": [], "recentPlayed": [], "homeMix": [], "smart": [], "rediscover": [],
                 "onThisDay": [], "home": {}}
        ul.setRating("/a", 5)
        ul.toggleLike("/a")
        ul._apply_refresh(stale)  # read before the writes landed: it must not put the old values back
        assert ul.rating("/a") == 5 and ul.isLiked("/a")
        stale["edits"] = ul._edits
        ul._apply_refresh(stale)  # read after: it's the truth
        assert ul.rating("/a") == 0 and not ul.isLiked("/a")
    finally:
        ul.shutdown()


def test_a_rating_you_cleared_stays_cleared_when_the_file_still_has_one(db):
    add(db, "/a", rating=4)  # another player's rating, in the file
    assert db.ratings()["/a"] == 4
    db.set_rating("/a", 0)
    add(db, "/a", rating=4)  # read again: the file's tags still say 4
    assert "/a" not in db.ratings()
