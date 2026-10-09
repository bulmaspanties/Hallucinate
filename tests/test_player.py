import json
import time

import pytest
from audio import FFMPEG, FORMATS, encode
from conftest import wait_for

pytestmark = pytest.mark.skipif(not FFMPEG, reason="ffmpeg not installed")


def track(path, i=0, dur=1.5):
    return {"id": i, "path": str(path), "title": f"T{i}", "artist": "A", "album": "B", "duration": dur,
            "artUrl": ""}


@pytest.fixture
def make_player(qapp, tmp_path):
    made = []

    def make(session=True):
        from musicplayer.player import Player
        p = Player(session_file=(tmp_path / "session.json") if session else None)
        made.append(p)
        return p

    yield make
    for p in made:
        p.shutdown()


@pytest.fixture(scope="module")
def clips(tmp_path_factory):
    d = tmp_path_factory.mktemp("clips")
    return [track(encode(d / f"c{i}.flac", "flac", seconds=1.2, title=f"C{i}"), i, 1.2) for i in range(6)]


def is_playing(p):
    return p.state == "Playing"


@pytest.mark.parametrize("ext", sorted(FORMATS))
def test_plays_and_seeks_every_format(make_player, tmp_path, ext):
    path = encode(tmp_path / ("a." + ext.split(".")[-1]), ext, seconds=3, title="x")
    p = make_player(session=False)
    p.playList([track(path, 1, 3)], 0)
    assert wait_for(lambda: is_playing(p) and p.position > 100), p.error
    assert p.error == ""
    assert 2500 < p.duration < 3500
    p.seek(2000)
    assert wait_for(lambda: p.position >= 1900), (ext, p.position)
    p.pause()
    assert p.state == "Paused"
    p.seek(500)
    assert wait_for(lambda: 400 <= p.position <= 900), (ext, p.position)
    p.seek(10**9)  # clamps
    assert p.position <= p.duration
    p.seek(-5)
    assert wait_for(lambda: p.position < 200)


def test_end_of_queue_stops(make_player, clips):
    p = make_player(session=False)
    p.playList(clips[:2], 0)
    assert wait_for(lambda: p.currentIndex == 1, 6)
    assert wait_for(lambda: p.state == "Stopped", 6)
    assert p.currentIndex == 1


def test_repeat_all_wraps(make_player, clips):
    p = make_player(session=False)
    p.setRepeat(1)
    p.playList(clips[:2], 0)
    assert wait_for(lambda: p.currentIndex == 1, 5)
    assert wait_for(lambda: p.currentIndex == 0 and is_playing(p), 5)


def test_repeat_one_loops(make_player, clips):
    p = make_player(session=False)
    p.setRepeat(2)
    p.playList(clips[:2], 0)
    time.sleep(0)
    assert wait_for(lambda: p.position > 800, 5)
    assert wait_for(lambda: p.position < 600 and is_playing(p), 5)
    assert p.currentIndex == 0


def test_manual_next_wraps_and_previous(make_player, clips):
    p = make_player(session=False)
    p.playList(clips[:3], 2)
    p.next()
    assert p.currentIndex == 0
    p.next()
    assert p.currentIndex == 1
    assert wait_for(lambda: is_playing(p))
    p.previous()  # position < 3s -> goes back
    assert p.currentIndex == 0
    p.previous()  # history remembers the previous manual wrap
    assert p.currentIndex == 2


def test_gapless_swaps_preloaded_voice(make_player, clips):
    p = make_player(session=False)
    t0 = time.monotonic()
    p.playList(clips[:3], 0)
    assert wait_for(lambda: p.currentIndex == 2 and p.state == "Playing", 8)
    assert wait_for(lambda: p.state == "Stopped", 6)
    elapsed = time.monotonic() - t0
    assert p.gapless_swaps == 2, p.gapless_swaps
    # 3 x 1.2s of audio; all transitions together may add at most a short pause.
    assert elapsed < 3.6 + 1.2, elapsed
    assert p.error == ""


def test_shuffle_visits_everything_once(make_player, clips):
    p = make_player(session=False)
    p.setShuffle(True)
    p.playList(clips, 0)
    seen = [p.currentIndex]
    for _ in range(5):
        peek = p._compute_next(auto=False)
        p.next()
        assert p.currentIndex == peek
        seen.append(p.currentIndex)
    assert sorted(seen) == list(range(6))
    assert p._compute_next(auto=True) is None  # shuffle exhausted, repeat off
    p.setRepeat(1)
    assert p._compute_next(auto=True) not in (None, p.currentIndex)


def test_shuffle_toggle_midway_keeps_current(make_player, clips):
    p = make_player(session=False)
    p.playList(clips, 3)
    p.toggleShuffle()
    assert p.shuffle and p.currentIndex == 3
    assert p._compute_next(auto=False) != 3
    p.toggleShuffle()
    assert p._compute_next(auto=False) == 4


def test_queue_operations(make_player, clips):
    p = make_player(session=False)
    p.playList(clips[:3], 1)
    p.enqueue(clips[3])
    p.playNext(clips[4])
    assert [t["title"] for t in p.queue] == ["T0", "T1", "T4", "T2", "T3"]
    assert p.currentIndex == 1
    p.removeAt(0)
    assert p.currentIndex == 0 and p.current["title"] == "T1"
    p.moveItem(3, 0)
    assert p.currentIndex == 1 and p.current["title"] == "T1"
    assert [t["title"] for t in p.queue] == ["T3", "T1", "T4", "T2"]
    p.removeAt(1)  # remove current
    assert p.current["title"] == "T4"
    p.removeAt(99)
    p.clearQueue()
    assert not p.hasTrack and p.currentIndex == -1 and p.queueLength == 0
    p.next()
    p.previous()
    p.play()
    p.seek(100)  # no crash on an empty queue


def test_enqueue_on_empty_loads_without_playing(make_player, clips):
    p = make_player(session=False)
    p.enqueue(clips[0])
    assert p.hasTrack and p.state != "Playing"
    p.play()
    assert wait_for(lambda: is_playing(p))


def test_missing_track_skips_to_next(make_player, clips, tmp_path):
    p = make_player(session=False)
    p.playList([track(tmp_path / "missing.flac", 9), track(tmp_path / "also-missing.mp3", 8), clips[0]], 0)
    assert p.currentIndex == 2 and p.current["title"] == "T0"
    assert wait_for(lambda: is_playing(p))


def test_corrupt_track_skips_to_next(make_player, clips, tmp_path):
    corrupt = tmp_path / "broken.flac"
    corrupt.write_bytes(b"fLaC" + b"\xff" * 100)
    p = make_player(session=False)
    p.playList([track(corrupt, 9), clips[0]], 0)
    assert p.currentIndex == 1 and p.current["title"] == "T0"
    assert wait_for(lambda: is_playing(p))


def test_decoder_error_skips_to_next(make_player, clips, qapp):
    p = make_player(session=False)
    p.playList(clips[:2], 0)
    assert wait_for(lambda: is_playing(p))
    p._on_error(0, "decoder failure")
    assert wait_for(lambda: p.currentIndex == 1 and is_playing(p), timeout=4)


def test_all_missing_tracks_fail_cleanly(make_player, tmp_path):
    p = make_player(session=False)
    tracks = [track(tmp_path / f"missing{i}.mp3", i) for i in range(3)]
    p.playList(tracks, 0)
    assert not p.hasTrack and p.state == "Stopped" and "File not found" in p.error


def test_volume_clamped_and_persisted(make_player):
    p = make_player(session=False)
    p.setVolume(5)
    assert p.volume == 1.0
    p.setVolume(-1)
    assert p.volume == 0.0
    p.setVolume(0.37)
    assert make_player(session=False).volume == pytest.approx(0.37)


# ---- session restore ------------------------------------------------------
def test_session_roundtrip(make_player, clips, tmp_path):
    p = make_player()
    p.setRepeat(1)
    p.setShuffle(True)
    p.playList(clips[:4], 2)
    assert wait_for(lambda: p.position > 100)
    p.seek(700)
    assert wait_for(lambda: p.position >= 650)
    p.pause()
    saved_pos = p.position
    p.saveSession()
    p.shutdown()

    q = make_player()
    assert q.restoreSession()
    assert q.currentIndex == 2 and q.queueLength == 4
    assert q.shuffle and q.repeat == 1
    assert q.state != "Playing"
    assert wait_for(lambda: abs(q.position - saved_pos) < 250), (q.position, saved_pos)
    q.play()
    assert wait_for(lambda: is_playing(q))


def test_session_drops_missing_files_and_remaps_index(make_player, clips, tmp_path):
    import shutil
    d = tmp_path / "gone"
    d.mkdir()
    gone = [track(shutil.copy(c["path"], d / f"{i}.flac"), i) for i, c in enumerate(clips[:3])]
    p = make_player()
    p.playList(gone + clips[3:5], 3)
    p.pause()
    p.saveSession()
    (d / "0.flac").unlink()
    (d / "2.flac").unlink()
    q = make_player()
    assert q.restoreSession()
    assert q.queueLength == 3
    assert q.current["title"] == "T3" and q.currentIndex == 1


def test_session_current_track_deleted(make_player, clips, tmp_path):
    import shutil
    f = shutil.copy(clips[0]["path"], tmp_path / "x.flac")
    p = make_player()
    p.playList([track(f, 0), clips[1]], 0)
    p.pause()
    p.saveSession()
    (tmp_path / "x.flac").unlink()
    q = make_player()
    assert q.restoreSession() and q.current["title"] == "T1"


@pytest.mark.parametrize("content", ["", "{", "[]", '{"queue": 5}', '{"queue": [1, "a", null]}',
                                     '{"queue": [], "index": 0}', "\x00\x01"])
def test_corrupt_session_file_is_ignored(make_player, tmp_path, content):
    (tmp_path / "session.json").write_text(content)
    p = make_player()
    assert p.restoreSession() is False
    assert not p.hasTrack


def test_no_session_file(make_player):
    assert make_player().restoreSession() is False


def test_session_file_is_valid_json(make_player, clips, tmp_path):
    p = make_player()
    p.playList(clips[:2], 0)
    p.saveSession()
    data = json.loads((tmp_path / "session.json").read_text())
    assert data["index"] == 0 and len(data["queue"]) == 2


def test_played_signal_after_half(make_player, tmp_path):
    p = make_player()
    f = encode(tmp_path / "x.wav", "wav", seconds=2.0)
    got = []
    p.played.connect(got.append)
    p.playList([track(f, 1, 2.0)], 0)
    assert wait_for(lambda: got, timeout=8)
    assert got[0]["path"] == str(f)
    time.sleep(0.5)
    assert len(got) == 1


def test_replaygain_factor():
    from musicplayer.player import replaygain_factor
    t = {"rg_track": -6.0, "rg_album": -3.0, "rg_peak": 0.5}
    assert replaygain_factor(t, "off") == 1.0
    assert replaygain_factor(None, "track") == 1.0
    assert abs(replaygain_factor({"rg_track": -6.0}, "track") - 0.501) < 0.01
    assert abs(replaygain_factor({"rg_track": -6.0, "rg_album": -3.0}, "album") - 0.708) < 0.01
    assert abs(replaygain_factor({"rg_track": -6.0}, "album") - 0.501) < 0.01  # falls back
    assert replaygain_factor({"rg_track": 12.0, "rg_peak": 0.5}, "track") == 2.0  # peak clamp
    assert replaygain_factor({"rg_track": -6.0}, "track", preamp_db=6.0) == pytest.approx(1.0)
    assert replaygain_factor({"rg_track": None}, "track") == 1.0


def test_replaygain_sets_output_volume(make_player, tmp_path):
    p = make_player(session=False)
    p.setVolume(1.0)
    f = encode(tmp_path / "g.wav", "wav", seconds=2.0)
    t = track(f, 1, 2.0)
    t["rg_track"] = -6.0
    p.setReplayGainMode("track")
    p.playList([t], 0)
    assert abs(p._voice.audio.volume() - 0.501) < 0.01
    p.setReplayGainMode("off")
    assert p._voice.audio.volume() == pytest.approx(1.0)
    p.setReplayGainMode("off")


def test_crossfade_overlaps_tracks(make_player, tmp_path):
    p = make_player(session=False)
    p.setVolume(1.0)
    p.setCrossfade(1)
    tracks = [track(encode(tmp_path / f"x{i}.flac", "flac", seconds=4, title=f"x{i}"), i, 4) for i in range(2)]
    p.playList(tracks, 0)
    assert wait_for(lambda: is_playing(p) and p.position > 100)
    p.seek(2500)
    assert wait_for(lambda: p._fading, timeout=6)
    assert p.currentIndex == 1
    old = p._standby
    assert old.player.playbackState().name == "PlayingState"
    assert wait_for(lambda: not p._fading, timeout=4)
    assert old.player.playbackState().name != "PlayingState"
    assert p._voice.audio.volume() == pytest.approx(1.0)
    p.setCrossfade(0)


def test_eq_enabled_plays_and_seeks(make_player, tmp_path):
    from PySide6.QtMultimedia import QMediaDevices
    if QMediaDevices.defaultAudioOutput().isNull():
        pytest.skip("no audio output device")
    p = make_player(session=False)
    f = encode(tmp_path / "eq.flac", "flac", seconds=3)
    p.setEqPreset("Rock")
    p.setEqEnabled(True)
    assert p.eqEnabled and p.eqPreset == "Rock"
    p.playList([track(f, 1, 3)], 0)
    assert wait_for(lambda: is_playing(p) and p.position > 300), p.error
    assert p._voice.tap is not None and not p._voice.tap.failed
    p.pause()
    assert p.state == "Paused"
    p.seek(1500)
    p.play()
    assert wait_for(lambda: p.position > 1700)
    p.setEqEnabled(False)
    assert p._voice.tap is None and p._voice.audio.volume() > 0
    assert wait_for(lambda: p.position > 1900)
    assert p.error == ""


def test_speed_persists_and_applies(make_player):
    p = make_player()
    p.setSpeed(1.5)
    assert p.speed == 1.5 and all(v.player.playbackRate() == 1.5 for v in p._voices)
    p.setSpeed(9)
    assert p.speed == 2.0
    p.setSpeed(1.0)
    assert p.speed == 1.0


def test_sleep_timer_pauses_and_fades(make_player):
    p = make_player(session=False)
    p.setSleepMinutes(1)
    assert p.sleepRemaining == 60
    p._sleep_left = 8
    p._sleep_tick()
    assert p.sleepRemaining == 7 and 0 < p._sleep_gain < 1
    p._sleep_left = 1
    p._sleep_tick()
    assert p.sleepRemaining == -1 and p._sleep_gain == 1.0 and not p._sleep_timer.isActive()
    p.setSleepMinutes(5)
    p.setSleepMinutes(0)
    assert p.sleepRemaining == -1
    p.setSleepAfterTrack(True)
    assert p.sleepAfterTrack


def test_sleep_after_track_pauses_on_next_track(make_player, clips):
    p = make_player(session=False)
    p.setSleepAfterTrack(True)
    p.playList(clips[:3], 0)
    assert wait_for(lambda: is_playing(p) and p.currentIndex == 0)
    assert wait_for(lambda: not p.sleepAfterTrack, timeout=8)
    assert p.currentIndex == 1 and wait_for(lambda: not is_playing(p))


def test_move_item_tracks_current(make_player, clips):
    p = make_player(session=False)
    p.setQueue(clips[:4], 1) if hasattr(p, "setQueue") else p.playList(clips[:4], 1)
    cur = p.currentIndex
    p.moveItem(cur, 3)
    assert p.currentIndex == 3
    p.moveItem(0, 3)
    assert p.currentIndex == 2
