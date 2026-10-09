"""GUI-thread responsiveness and incremental-update tests (large synthetic library)."""
import json
import time

import pytest
from conftest import wait_for
from test_library_robust import _bulk

pytest.importorskip("PySide6.QtCore", exc_type=ImportError)

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtGui import QColor, QImage  # noqa: E402

from musicplayer.models import TRACK_KEYS, DictModel, compute_ops  # noqa: E402

# The goal is "never block >~50 ms"; CI machines are noisy, so the assertion has headroom.
MAX_GAP_MS = 120


class Heartbeat:
    """Counts how long the GUI thread went without servicing a 5 ms timer."""

    def __init__(self):
        self.last = time.perf_counter()
        self.worst = 0.0
        self.timer = QTimer()
        self.timer.setInterval(5)
        self.timer.timeout.connect(self._tick)

    def _tick(self):
        now = time.perf_counter()
        self.worst = max(self.worst, (now - self.last) * 1000)
        self.last = now

    def __enter__(self):
        self.last = time.perf_counter()
        self.worst = 0.0
        self.timer.start()
        return self

    def __exit__(self, *exc):
        self.timer.stop()
        self.timer.timeout.disconnect(self._tick)
        self.timer.deleteLater()


def test_compute_ops_roundtrip_and_limits():
    old = ["a", "b", "c", "d"]
    new = ["a", "x", "c", "d", "e"]
    ops = compute_ops(old, new, 10)
    assert ops is not None and all(op[0] != "equal" for op in ops)
    assert compute_ops(list("abcdef"), list("zyxwvu"), 0) is None


def test_update_items_is_incremental(qapp):
    model = DictModel(["id", "title"], key_field="id")
    model.set_items([{"id": i, "title": f"t{i}"} for i in range(10)])
    events = []
    model.modelReset.connect(lambda: events.append("reset"))
    model.rowsInserted.connect(lambda *_: events.append("ins"))
    model.rowsRemoved.connect(lambda *_: events.append("rem"))

    revision, keys = model.snapshot_keys()
    items = [{"id": i, "title": f"t{i}"} for i in range(10) if i != 3] + [{"id": 99, "title": "new"}]
    ops = compute_ops(keys, [i["id"] for i in items], 100)
    model.update_items(items, ops, revision)

    assert "reset" not in events and events
    assert [m["id"] for m in model.items()] == [i["id"] for i in items]
    assert model.count == 10


def test_update_items_falls_back_when_stale(qapp):
    model = DictModel(["id"], key_field="id")
    model.set_items([{"id": 1}, {"id": 2}])
    revision, keys = model.snapshot_keys()
    model.set_items([{"id": 5}])
    model.update_items([{"id": 1}, {"id": 2}, {"id": 3}], compute_ops(keys, [1, 2, 3], 10), revision)
    assert [m["id"] for m in model.items()] == [1, 2, 3]


@pytest.fixture
def big_library(qapp, tmp_path):
    from musicplayer.core.db import Database
    from musicplayer.library import Library

    db_path = tmp_path / "big.db"
    d = Database(db_path)
    _bulk(d, 50_000, aa_tag=0)
    d.finalize()
    d.close()
    art = tmp_path / "art"
    art.mkdir()
    lib = Library(db_path, art)
    yield lib
    lib.shutdown()


def test_50k_reload_search_play_never_block_gui(big_library, tmp_path):
    from musicplayer.player import Player

    lib = big_library
    player = Player(session_file=tmp_path / "session.json")
    lib.setPlayer(player)
    try:
        _run_latency(lib, player)
    finally:
        lib.setPlayer(None)
        player.deleteLater()


def _run_latency(lib, player):
    with Heartbeat() as hb:
        assert wait_for(lambda: lib.ready and lib.trackCount == 50_000, timeout=30)
        load_worst = hb.worst
        hb.worst = 0.0
        for q in ("song", "artist 12", "caf", "album 99"):
            lib.search(q)
            assert wait_for(lambda: lib.searchTracks.count > 0, timeout=10)
        search_worst = hb.worst
        hb.worst = 0.0
        lib.playSongs(1234)
        player.saveSession()
        play_worst = hb.worst
    print(f"GAPS load={load_worst:.0f} search={search_worst:.0f} play={play_worst:.0f} ms")
    assert load_worst < MAX_GAP_MS * 3, f"reload blocked GUI for {load_worst:.0f} ms"
    assert search_worst < MAX_GAP_MS, f"search blocked GUI for {search_worst:.0f} ms"
    assert play_worst < MAX_GAP_MS * 2, f"play/save blocked GUI for {play_worst:.0f} ms"


def test_session_save_is_bounded(qapp, tmp_path):
    from musicplayer.player import SESSION_MAX_TRACKS, Player

    player = Player(session_file=tmp_path / "s.json")
    tracks = [{"id": i, "path": f"/nope/{i}.mp3", "title": f"t{i}"} for i in range(5000)]
    player._queue = tracks
    player._index = 3000
    player.saveSession()
    data = json.loads((tmp_path / "s.json").read_text())
    assert len(data["queue"]) == SESSION_MAX_TRACKS
    assert data["queue"][data["index"]]["id"] == 3000


def test_art_provider_buckets_and_caches(qapp, tmp_path):
    from musicplayer.thumbs import ArtProvider, bucket

    assert [bucket(n) for n in (10, 64, 65, 300, 9999)] == [64, 64, 128, 512, 512]
    src = tmp_path / "we ird #name%.png"
    img = QImage(900, 600, QImage.Format.Format_RGB32)
    img.fill(QColor("red"))
    assert img.save(str(src))
    provider = ArtProvider(tmp_path / "cache")
    from urllib.parse import quote

    ident = "256/" + quote(src.as_uri(), safe="")
    px, path = provider.parse(ident)
    assert px == 256 and path == str(src)
    out = provider.load(path, px)
    assert max(out.width(), out.height()) == 256
    assert list((tmp_path / "cache").glob("*.jpg"))
    assert provider.load(path, px).width() == out.width()
    assert provider.load(str(tmp_path / "missing.png"), 64).isNull()


def test_track_keys_unchanged_for_qml():
    assert "title" in TRACK_KEYS and "artUrl" in TRACK_KEYS
