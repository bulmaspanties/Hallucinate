"""The signal path readout: which stages change the sound, and when it is untouched."""
from hallucinate.signalpath import describe

FLAC = {"codec": "FLAC", "sample_rate": 44100, "bitrate": 900_000}


def names(path, active=True):
    return [s["name"] for s in path["stages"] if s["active"] == active]


def test_untouched_when_nothing_processes():
    path = describe(FLAC, device_name="DAC", device_rate=44100)
    assert path["untouched"] and path["summary"] == "Untouched" and names(path) == []
    assert path["stages"][0]["detail"] == "FLAC  ·  44.1 kHz  ·  lossless"
    assert path["stages"][-1]["detail"] == "DAC  ·  44.1 kHz"


def test_each_stage_that_changes_the_sound():
    path = describe(FLAC, rg_factor=0.5, rg_mode="album", volume=0.6, speed=1.25, eq_enabled=True,
                    eq_preset="Bass", crossfade=4, device_name="Speakers", device_rate=48000)
    assert not path["untouched"]
    assert names(path) == ["ReplayGain", "Equalizer", "Speed", "Volume", "Output"]
    details = {s["name"]: s["detail"] for s in path["stages"]}
    assert details["ReplayGain"] == "Album gain -6.0 dB" and details["Equalizer"] == "Bass"
    assert details["Speed"] == "1.25×" and details["Volume"] == "60%" and details["Crossfade"] == "4 s between tracks"
    assert details["Output"] == "Speakers  ·  48 kHz (resampled from 44.1 kHz)"
    assert path["summary"] == "Changed by replaygain, equalizer, speed, volume, resampling"


def test_lossy_source_and_untagged_replaygain():
    path = describe({"codec": "MP3", "sample_rate": 48000, "bitrate": 320_000}, rg_mode="track", device_rate=48000)
    assert path["stages"][0]["detail"] == "MP3  ·  48 kHz  ·  320 kbps"
    assert path["stages"][1]["detail"] == "Track gain: none tagged" and path["untouched"]
    assert describe(None)["stages"] == []


def test_player_exposes_signal_path(qapp, tmp_path):
    from hallucinate.player import Player

    player = Player(session_file=tmp_path / "s.json")
    try:
        assert player.signalPath["stages"] == []
        seen = []
        player.signalPathChanged.connect(lambda: seen.append(1))
        player.setSpeed(1.5)
        assert seen
    finally:
        player.shutdown()
