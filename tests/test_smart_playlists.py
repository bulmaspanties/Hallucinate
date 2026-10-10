"""Smart playlists: the rules engine, its use by radio, and the UserLibrary API."""
import json
import random

import pytest
from conftest import wait_for
from PySide6.QtCore import QObject, Signal

from hallucinate.core import rules as R
from hallucinate.core.radio import radio_tracks

NOW = 10_000_000.0
DAY = 86_400


def add(db, path, artist, genre="", year=0, title=None, codec="FLAC", duration=200, added=NOW - 400 * DAY):
    db.upsert_track({
        "path": path, "mtime": 0, "size": 1, "title": title or path.rsplit("/", 1)[1], "artist": artist,
        "album_artist": artist, "aa_tag": 1, "album": f"{artist} LP", "album_key": f"{artist}|lp", "track_no": 0,
        "disc_no": 0, "year": year, "genre": genre, "duration": duration, "fmt": codec, "codec": codec,
        "bitrate": 320_000, "sample_rate": 44100,
    })
    db.conn.execute("UPDATE tracks SET added=? WHERE path=?", (added, path))


@pytest.fixture
def lib(db):
    add(db, "/m/blue", "Miles Davis", "Jazz", 1959, "Blue in Green")
    add(db, "/m/giant", "John Coltrane", "Jazz; Hard Bop", 1960, "Giant Steps", codec="MP3")
    add(db, "/m/modern", "Kamasi Washington", "Jazz", 2015, "Change of the Guard", duration=750)
    add(db, "/m/cafe", "Stéphane Grappelli", "Jazz", 1937, "Café")
    add(db, "/m/metal", "Iron Lung", "Metal", 1999, "Noise", added=NOW - DAY)
    for path in ("/m/blue", "/m/modern", "/m/metal"):
        db.set_liked(path, True)
    db.record_play("/m/blue", NOW - 100 * DAY)
    db.record_play("/m/modern", NOW - 5 * DAY)
    for _ in range(3):
        db.record_play("/m/metal", NOW - 2 * DAY)
    db.commit()
    return db


def paths(rows):
    return [r["path"] for r in rows]


def rule(field, op, value=None):
    return {"field": field, "op": op, "value": value}


def test_liked_and_not_played_recently(lib):
    rules = {"rules": [rule("liked", "is_true"), rule("last_played", "not_in_last", 60)], "sort": "title"}
    assert paths(R.matching_tracks(lib, rules, NOW)) == ["/m/blue"]
    assert R.describe(rules) == "Liked is yes and Last played not in the last 60 days · title"


def test_jazz_before_1970_and_never_played_counts_as_not_recent(lib):
    jazz = {"rules": [rule("genre", "contains", "jazz"), rule("year", "lt", 1970)], "sort": "year_asc"}
    assert paths(R.matching_tracks(lib, jazz, NOW)) == ["/m/cafe", "/m/blue", "/m/giant"]
    stale = {"rules": [rule("last_played", "not_in_last", 30)], "sort": "title"}
    assert set(paths(R.matching_tracks(lib, stale, NOW))) == {"/m/blue", "/m/giant", "/m/cafe"}
    never = {"rules": [rule("last_played", "never")]}
    assert set(paths(R.matching_tracks(lib, never, NOW))) == {"/m/giant", "/m/cafe"}


def test_text_numbers_dates_and_any(lib):
    def match(*rs, mode="all", **extra):
        return set(paths(R.matching_tracks(lib, {"match": mode, "rules": list(rs), **extra}, NOW)))

    assert match(rule("artist", "is", "stephane grappelli")) == {"/m/cafe"}  # accent and case insensitive
    assert match(rule("title", "starts_with", "blue")) == {"/m/blue"}
    assert match(rule("title", "ends_with", "STEPS")) == {"/m/giant"}
    assert match(rule("genre", "not_contains", "jazz")) == {"/m/metal"}
    assert match(rule("format", "is_not", "flac")) == {"/m/giant"}
    assert match(rule("title", "contains", "%")) == set()  # wildcards are literal
    assert match(rule("duration", "gt", 10)) == {"/m/modern"}  # minutes
    assert match(rule("year", "between", [1990, 1958])) == {"/m/blue", "/m/giant"}
    assert match(rule("plays", "ge", 2)) == {"/m/metal"}
    assert match(rule("added", "in_last", 7)) == {"/m/metal"}
    assert match(rule("liked", "is_false")) == {"/m/giant", "/m/cafe"}
    assert match(rule("genre", "is", "metal"), rule("year", "lt", 1950), mode="any") == {"/m/metal", "/m/cafe"}
    assert match() == {"/m/blue", "/m/giant", "/m/modern", "/m/cafe", "/m/metal"}


def test_sort_limit_and_count(lib):
    rules = {"rules": [], "sort": "plays_desc", "limit": 2}
    assert paths(R.matching_tracks(lib, rules, NOW))[0] == "/m/metal"
    assert len(R.matching_tracks(lib, rules, NOW)) == 2
    assert R.count_matching(lib, rules, NOW) == 2
    assert R.count_matching(lib, {"rules": []}, NOW) == 5
    assert R.describe({"rules": [], "sort": "random", "limit": 25}) == "All songs · random · up to 25 songs"


@pytest.mark.parametrize("bad", [
    "not json", [], {"match": "most"}, {"rules": [rule("path; DROP TABLE tracks", "is", "x")]},
    {"rules": [rule("title", "gt", 3)]}, {"rules": [rule("year", "between", [1])]},
    {"rules": [rule("year", "eq", "nineteen")]}, {"rules": [rule("added", "never")]},
    {"sort": "t.path; DROP"}, {"limit": "lots"}, {"rules": [rule("year", "gt", float("nan"))]},
])
def test_malformed_rules_are_rejected(bad):
    with pytest.raises(ValueError):
        R.normalize(bad)


def test_normalize_accepts_json_and_clamps_limit():
    assert R.normalize(json.dumps({"rules": [rule("year", "eq", "1959")], "limit": 10**9})) == {
        "match": "all", "rules": [rule("year", "eq", 1959.0)], "sort": "artist", "limit": R.MAX_LIMIT}
    assert R.normalize("") == {"match": "all", "rules": [], "sort": "artist", "limit": 0}


def test_schema_lists_every_field_and_sort():
    schema = R.schema()
    assert {f["key"] for f in schema["fields"]} == set(R.FIELDS)
    assert {s["key"] for s in schema["sorts"]} == set(R.SORTS)


def test_radio_respects_smart_playlist_rules(lib):
    rules = {"rules": [rule("year", "lt", 1970)]}
    for seed in range(10):
        picked = paths(radio_tracks(lib, ["/m/blue"], limit=5, rng=random.Random(seed), now=NOW, rules=rules))
        assert picked and set(picked) <= {"/m/giant", "/m/cafe"}


# --- UserLibrary -----------------------------------------------------------------------------------------
class FakePlayer(QObject):
    played = Signal(object)

    def __init__(self):
        super().__init__()
        self.calls = []

    def playList(self, tracks, index, radio_rules=None):
        self.calls.append(([t["path"] for t in tracks], index, radio_rules))

    def setShuffle(self, on):
        self.calls.append(("shuffle", on))


def test_user_library_smart_playlists(qapp, tmp_path, lib):
    from hallucinate.userlib import UserLibrary

    player = FakePlayer()
    ul = UserLibrary(lib.conn.execute("PRAGMA database_list").fetchone()["file"], player)
    try:
        assert ul.createSmartPlaylist("Bad", '{"rules": [{"field": "nope"}]}') == -1
        assert ul.createSmartPlaylist("  ", "{}") == -1
        assert ul.countRules("not json") == -1
        liked = json.dumps({"rules": [rule("liked", "is_true")], "sort": "title"})
        assert ul.countRules(liked) == 3
        sid = ul.createSmartPlaylist("Loved", liked)
        assert sid >= 0
        assert wait_for(lambda: ul.smartPlaylists.count == 1)
        info = ul.smartInfo(sid)
        assert info["name"] == "Loved" and info["n"] == 3 and info["summary"].startswith("Liked is yes")
        assert json.loads(ul.smartRules(sid))["rules"] == [rule("liked", "is_true")]

        ul.openSmartPlaylist(sid)
        assert wait_for(lambda: ul.smartTracks.count == 3)
        ul.toggleLike("/m/cafe")  # live: liking a song adds it to the open smart playlist
        assert wait_for(lambda: ul.smartTracks.count == 4)
        assert wait_for(lambda: ul.smartInfo(sid)["n"] == 4)

        ul.playSmartPlaylist(1, False)
        tracks, index, radio_rules = player.calls[-1]
        assert index == 1 and len(tracks) == 4 and radio_rules["rules"] == [rule("liked", "is_true")]

        assert ul.updateSmartPlaylist(sid, "Old jazz", json.dumps({"rules": [rule("year", "lt", 1950)]}))
        assert not ul.updateSmartPlaylist(sid, "Old jazz", "{bad")
        assert wait_for(lambda: ul.smartTracks.count == 1 and ul.smartInfo(sid)["name"] == "Old jazz")

        ul.deleteSmartPlaylist(sid)
        assert wait_for(lambda: ul.smartPlaylists.count == 0)
        assert ul.smartTracks.count == 0
    finally:
        ul.shutdown()
