def test_prefix_and_multi_token(db, scan, music):
    scan(music)
    assert [t["title"] for t in db.search("mid")["tracks"]] == ["Midnight Rain"]
    assert [t["title"] for t in db.search("rain aurora")["tracks"]] == ["Midnight Rain"]
    assert db.search("zzz") == {"tracks": [], "albums": [], "artists": []}
    assert db.search("   ")["tracks"] == []


def test_diacritics_insensitive(db, scan, music):
    scan(music)
    assert db.search("cafe")["tracks"][0]["title"] == "Café Noir"


def test_grouped_results(db, scan, music):
    scan(music)
    r = db.search("aur")
    assert [a["name"] for a in r["artists"]] == ["Aurora Vale"]
    assert [a["album"] for a in r["albums"]] == ["Northern Lights"]  # via album artist
    assert len(r["tracks"]) == 2
    r = db.search("tidal")
    assert r["albums"][0]["album"] == "Tidal" and r["tracks"][0]["album"] == "Tidal"


def test_special_characters_are_safe(db, scan, music):
    scan(music)
    for q in ['"', "*", "50%", "a_b", "AND OR NOT", "(", "'; DROP TABLE tracks;--"]:
        db.search(q)
    assert db.counts()["tracks"] == 4


def test_artist_pages(db, scan, music):
    scan(music)
    assert [a["album"] for a in db.artist_albums("aurora vale")] == ["Northern Lights"]
    assert len(db.artist_tracks("Aurora Vale")) == 2
    assert [a["name"] for a in db.artists()][:2] == ["Aurora Vale", "Blue Harbor"]
