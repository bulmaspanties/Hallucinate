from PySide6.QtCore import QSettings

from hallucinate.models import TRACK_KEYS
from hallucinate.player import Player


def test_track_info_setting_defaults_off_and_persists(qapp):
    settings = QSettings("hallucinate", "hallucinate")
    settings.remove("display/showTrackInfo")
    first = Player(session_file=None)
    second = None
    try:
        assert first.showTrackInfo is False
        first.setShowTrackInfo(True)
        assert first.showTrackInfo is True

        second = Player(session_file=None)
        assert second.showTrackInfo is True
        second.setShowTrackInfo(False)
        assert second.showTrackInfo is False
        assert settings.value("display/showTrackInfo") == "false"
    finally:
        first.shutdown()
        if second is not None:
            second.shutdown()
        settings.remove("display/showTrackInfo")


def test_track_models_expose_bitrate_role():
    assert "fmt" in TRACK_KEYS
    assert "codec" in TRACK_KEYS
    assert "bitrate" in TRACK_KEYS
