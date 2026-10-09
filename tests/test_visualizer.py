import numpy as np
from PySide6.QtMultimedia import QAudioFormat

from hallucinate.player import Player


def test_spectrum_returns_normalized_bands_for_pcm_sine():
    rate = 44100
    samples = np.arange(4096)
    signal = (np.sin(2 * np.pi * 440 * samples / rate) * 12000).astype("<i2")

    levels = Player._spectrum_levels(signal.tobytes(), QAudioFormat.SampleFormat.Int16, 1)

    assert len(levels) == 24
    assert all(0.0 <= level <= 1.0 for level in levels)
    assert max(levels) > 0.01


def test_spectrum_silence_and_unsupported_format_are_zero():
    silence = bytes(4096 * 2)
    levels = Player._spectrum_levels(silence, QAudioFormat.SampleFormat.Int16, 2)
    unsupported = Player._spectrum_levels(silence, QAudioFormat.SampleFormat.Unknown, 2)

    assert levels == [0.0] * 24
    assert unsupported == [0.0] * 24


def test_visualizer_can_be_toggled_without_playback(qapp):
    player = Player(session_file=None)
    try:
        assert player.visualizerAvailable
        player.setVisualizerEnabled(True)
        assert player.visualizerEnabled
        assert player._settings.value("visualizer/enabled") == "true"
        assert all(voice.player.audioBufferOutput() == voice.visual_output for voice in player._voices)

        player.setVisualizerEnabled(False)
        assert not player.visualizerEnabled
        assert player._settings.value("visualizer/enabled") == "false"
        assert all(voice.player.audioBufferOutput() is None for voice in player._voices)
    finally:
        player.shutdown()
