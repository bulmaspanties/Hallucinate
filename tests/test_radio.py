"""Radio mode: the track picker and how the player keeps the queue going."""
import random

import pytest
from audio import FFMPEG, encode
from conftest import wait_for

from hallucinate.core.radio import genres, radio_tracks


def add_track(db, path, artist, genre="", year=0, title=None):
    db.upsert_track({
        "path": path, "mtime": 0, "size": 1, "title": title or path, "artist": artist, "album_artist": artist,
        "aa_tag": 1, "album": f"{artist} LP", "album_key": f"{artist}|lp", "track_no": 0, "disc_no": 0,
        "year": year, "genre": genre, "duration": 200, "fmt": "FLAC", "codec": "FLAC", "bitrate": 900_000,
        "sample_rate": 44100,
    })


@pytest.fixture
def station(db):
    """A small library: jazz and metal, plus a pair of tracks always played together."""
    for i in range(6):
        add_track(db, f"/m/jazz{i}", f"Jazz Artist {i % 3}", "Jazz", 1960 + i)
        add_track(db, f"/m/metal{i}", f"Metal Band {i % 3}", "Metal", 1990 + i)
    add_track(db, "/m/seed", "Jazz Artist 0", "Jazz; Bebop", 1961)
    add_track(db, "/m/companion", "Someone Else", "Ambient", 2015)
    for day in range(5):  # the seed and the companion are heard in the same sessions
        db.record_play("/m/seed", 1_000_000 + day * 86_400)
        db.record_play("/m/companion", 1_000_000 + day * 86_400 + 240)
    db.commit()
    return db


def test_genres_are_split_and_folded():
    assert genres("Rock; Indie/Pop, Électro") == {"rock", "indie", "pop", "electro"}
    assert genres("") == set()


def test_radio_prefers_coplayed_and_similar_tracks(station):
    hits = {"companion": 0, "jazz": 0, "metal": 0}
    for seed in range(20):
        picked = radio_tracks(station, ["/m/seed"], limit=4, rng=random.Random(seed), now=2_000_000)
        assert len(picked) == 4
        for t in picked:
            name = t["path"].rsplit("/", 1)[1]
            key = "companion" if name == "companion" else "jazz" if name.startswith("jazz") else "metal"
            hits[key] += 1
    assert hits["companion"] >= 15  # co-played in every session: nearly always picked
    assert hits["jazz"] > 4 * hits["metal"]


def test_radio_excludes_queue_and_varies_artists(station):
    exclude = [f"/m/jazz{i}" for i in range(3)]
    for seed in range(10):
        picked = radio_tracks(station, ["/m/seed"], exclude, limit=8, rng=random.Random(seed), now=2_000_000)
        paths = [t["path"] for t in picked]
        assert "/m/seed" not in paths and not set(paths) & set(exclude)
        artists = [t["artist"] for t in picked]
        assert all(artists.count(a) <= 2 for a in artists)
        assert all(a != b for a, b in zip(["Jazz Artist 0", *artists], artists))


def test_radio_holds_back_recent_plays(station):
    def first_picks():
        return [radio_tracks(station, ["/m/seed"], limit=1, rng=random.Random(seed), now=2_000_000)[0]["path"]
                for seed in range(30)]

    assert first_picks().count("/m/companion") >= 20
    station.record_play("/m/companion", 2_000_000 - 60)  # just heard it: no longer the obvious next track
    assert first_picks().count("/m/companion") <= 15


def test_radio_without_seeds_or_library(db):
    assert radio_tracks(db, []) == []
    assert radio_tracks(db, ["/not/in/library"]) == []


# --- player -----------------------------------------------------------------------------------------------
needs_ffmpeg = pytest.mark.skipif(not FFMPEG, reason="ffmpeg not installed")


def track(path, i):
    return {"id": i, "path": str(path), "title": f"R{i}", "artist": "A", "album": "B", "duration": 1.0, "artUrl": ""}


@pytest.fixture(scope="module")
def radio_clips(tmp_path_factory):
    d = tmp_path_factory.mktemp("radio")
    return [track(encode(d / f"r{i}.flac", "flac", seconds=1.0, title=f"R{i}"), i) for i in range(4)]


class Source:
    def __init__(self):
        self.calls = []

    def __call__(self, seeds, exclude, done):
        self.calls.append((seeds, exclude, done))


@pytest.fixture
def radio_player(qapp):
    from hallucinate.player import Player
    p = Player()
    yield p
    p.setRadio(False)
    p.shutdown()


@needs_ffmpeg
def test_radio_extends_queue_before_it_runs_out(qapp, radio_player, radio_clips):
    p = radio_player
    source = Source()
    p.setRadioSource(source)
    p.playList(radio_clips[:2], 0)
    assert source.calls == []  # radio is off
    p.setRadio(True)
    assert len(source.calls) == 1
    seeds, exclude, done = source.calls[0]
    assert seeds == [radio_clips[0]["path"]]
    assert exclude == [c["path"] for c in radio_clips[:2]]
    done(radio_clips[2:])
    assert wait_for(lambda: p.queueLength == 4)
    assert len(source.calls) == 1  # enough left; no new request
    p.setRepeat(1)
    p.playIndex(3)
    assert len(source.calls) == 1  # repeat all: the queue never ends, so no radio


@needs_ffmpeg
def test_radio_resumes_after_queue_ended(qapp, radio_player, radio_clips):
    p = radio_player
    source = Source()
    p.setRadioSource(source)
    p.setRadio(True)
    p.playList(radio_clips[:1], 0)
    assert len(source.calls) == 1
    assert wait_for(lambda: p.state == "Stopped", 10)  # the batch is still being picked when the queue ends
    source.calls[0][2](radio_clips[1:2])
    assert wait_for(lambda: p.current.get("path") == radio_clips[1]["path"] and p.playing)


@needs_ffmpeg
def test_stale_radio_results_are_dropped(qapp, radio_player, radio_clips):
    p = radio_player
    source = Source()
    p.setRadioSource(source)
    p.setRadio(True)
    p.playList(radio_clips[:1], 0)
    p.playList(radio_clips[3:4], 0)  # the queue was replaced while the first batch was being picked
    source.calls[0][2](radio_clips[1:3])
    qapp.processEvents()
    assert p.queueLength == 1
    assert len(source.calls) == 2 and source.calls[1][0] == [radio_clips[3]["path"]]  # asked again
    p.setRadio(False)
    source.calls = []
    p.playList(radio_clips[:1], 0)
    assert source.calls == []


def test_library_radio_source_runs_on_worker(qapp, tmp_path, db, scan, music):
    from hallucinate.library import Library

    scan(music)
    seed = str(music / "Aurora Vale" / "Northern Lights" / "01.mp3")
    lib = Library(tmp_path / "lib.db", tmp_path / "art")
    got = []
    try:
        lib.radioTracks([seed], [seed], got.append)
        assert wait_for(lambda: got)
        paths = [t["path"] for t in got[0]]
        assert paths and seed not in paths
        assert all("durText" in t and "artUrl" in t for t in got[0])
    finally:
        lib.shutdown()
