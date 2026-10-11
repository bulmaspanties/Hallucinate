"""Waveforms for the seek bar: envelope maths, format conversion, decoding real files, caching, the player."""
import subprocess

import numpy as np
import pytest
from audio import FFMPEG, encode
from conftest import wait_for
from PySide6.QtCore import QByteArray
from PySide6.QtMultimedia import QAudioBuffer, QAudioFormat

from hallucinate import waveform as wf

needs_ffmpeg = pytest.mark.skipif(not FFMPEG, reason="ffmpeg not installed")


def test_envelope_follows_loudness():
    t = np.arange(44100 * 4) / 44100
    samples = np.sin(2 * np.pi * 440 * t) * np.where(t < 2, 1.0, 0.1)
    peaks = wf.peaks_from_samples(samples, points=40)
    assert len(peaks) == 40 and max(peaks) == 1.0
    assert min(peaks[:19]) > 0.9 and max(peaks[21:]) < 0.15  # the bucket at the change mixes both
    assert wf.peaks_from_samples(np.zeros(1000)) == [0.0] * wf.POINTS
    assert wf.peaks_from_samples([]) == []


@pytest.mark.parametrize("sample_format, dtype, value, expected", [
    (QAudioFormat.SampleFormat.Int16, np.int16, -16384, 0.5),
    (QAudioFormat.SampleFormat.Int32, np.int32, 1 << 30, 0.5),
    (QAudioFormat.SampleFormat.UInt8, np.uint8, 192, 0.5),
    (QAudioFormat.SampleFormat.Float, np.float32, 0.25, 0.25),
])
def test_mono_samples_converts_formats(qapp, sample_format, dtype, value, expected):
    fmt = QAudioFormat()
    fmt.setSampleRate(8000)
    fmt.setChannelCount(2)
    fmt.setSampleFormat(sample_format)
    silent = 128 if dtype is np.uint8 else 0
    frames = np.array([[value, silent], [silent, value]], dtype=dtype)  # louder channel wins per frame
    buf = QAudioBuffer(QByteArray(frames.tobytes()), fmt)
    assert np.allclose(np.abs(wf.mono_samples(buf)), expected, atol=0.01)


def _half_loud(path):
    """4 s: a tone, then near silence (decoders handle MP3 and FLAC differently, so both are tested)."""
    subprocess.run([FFMPEG, "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                    "aevalsrc='0.8*sin(2*PI*440*t)*if(lt(t,2),1,0.02)':s=44100:d=4", str(path)], check=True)
    return str(path)


@needs_ffmpeg
@pytest.mark.parametrize("ext", ["mp3", "flac"])
def test_service_decodes_caches_and_reuses(qapp, tmp_path, ext):
    clip = _half_loud(tmp_path / f"clip.{ext}")
    service = wf.WaveformService(tmp_path / "cache")
    try:
        assert service.request(clip) is None  # analysed in the background
        assert wait_for(lambda: service.peaks(clip) is not None, 15)
        peaks = service.peaks(clip)
        assert len(peaks) == wf.POINTS
        half = wf.POINTS // 2
        assert np.mean(peaks[20:half - 20]) > 0.8 and np.mean(peaks[half + 20:-20]) < 0.1
        assert len(list((tmp_path / "cache").glob("*.wf"))) == 1
    finally:
        service.shutdown()
    again = wf.WaveformService(tmp_path / "cache")  # a new session reads it from disk
    try:
        cached = again.request(clip)
        assert cached is not None and np.allclose(cached, peaks, atol=1 / 255)
    finally:
        again.shutdown()


@needs_ffmpeg
def test_unreadable_file_gives_an_empty_waveform(qapp, tmp_path):
    bad = tmp_path / "bad.mp3"
    bad.write_bytes(b"not audio at all" * 100)
    service = wf.WaveformService(tmp_path / "cache")
    try:
        service.request(str(bad))
        assert wait_for(lambda: service.peaks(str(bad)) is not None, 15)
        assert service.peaks(str(bad)) == []
    finally:
        service.shutdown()


@needs_ffmpeg
def test_player_waveform_follows_the_current_track(qapp, tmp_path):
    from hallucinate.player import Player

    clips = [encode(tmp_path / f"t{i}.flac", "flac", seconds=1.5) for i in range(2)]
    service = wf.WaveformService(tmp_path / "cache")
    player = Player()
    try:
        player.setWaveformService(service)
        assert player.waveform == []
        player.playList([{"path": str(c), "title": f"T{i}"} for i, c in enumerate(clips)], 0)
        assert wait_for(lambda: len(player.waveform) == wf.POINTS, 15)
        assert wait_for(lambda: service.peaks(str(clips[1])) is not None, 15)  # the next track is prefetched
        player.clearQueue()
        assert player.waveform == []
    finally:
        player.shutdown()
        service.shutdown()
