"""Debug info for bug reports: what it says, and what it keeps private."""
import logging
import os


def test_report_lists_versions_audio_and_log_without_personal_paths(qapp, tmp_path):
    from hallucinate import __version__, diagnostics
    from hallucinate.player import Player

    diagnostics.install()
    home = os.path.expanduser("~")
    logging.getLogger("hallucinate.test").warning("Could not read %s/Music/secret.flac", home)
    player = Player()
    try:
        text = diagnostics.report(player=player)
    finally:
        player.shutdown()
    assert text.startswith(f"Hallucinate {__version__}")
    for part in ("OS:", "PySide6", "Qt ", "Display:", "Audio output:", "Playback: ReplayGain", "Recent log"):
        assert part in text, part
    assert "secret.flac" not in text and "<song file>" in text and home + "/" not in text


def test_reports_leave_out_songs_folders_and_links():
    from hallucinate import diagnostics

    diagnostics.set_private_folders(["/mnt/Media Drive/Music"])
    try:
        lines = {
            "File not found: /srv/other music/Björk/Homogenic/03 Jóga.mp3": "File not found: <song file>",
            r"Unreadable audio file: D:\Musik\Artist\x y.m4a": "Unreadable audio file: <song file>",
            "Gone: /mnt/Media Drive/Music/a.flac#03 now": "Gone: <song file> now",
            "Scanning /mnt/Media Drive/Music/Live": "Scanning <music folder>/Live",
            "Blocked https://img.example/a.jpg?token=abc, then http://r.example/live":
                "Blocked <link>, then <link>",
        }
        for line, want in lines.items():
            assert diagnostics._redact(line) == want
    finally:
        diagnostics.set_private_folders([])


def test_shell_copies_debug_info(qapp):
    from PySide6.QtGui import QIcon

    from hallucinate.player import Player
    from hallucinate.shell import DesktopShell

    player = Player()
    shell = DesktopShell(qapp, player, QIcon())
    try:
        text = shell.copyDebugInfo()
        assert "Hallucinate" in text and qapp.clipboard().text() == text
        assert shell.appVersion
    finally:
        shell.shutdown()
        player.shutdown()


def test_update_check_is_opt_in_and_compares_versions(qapp):
    from conftest import wait_for
    from PySide6.QtCore import QSettings

    from hallucinate import updates

    assert updates.is_newer("v0.9.0", "0.8.0") and updates.is_newer("1.0", "0.9.9")
    assert not updates.is_newer("0.8.0", "0.8.0") and not updates.is_newer("garbage", "0.8.0")
    assert updates.is_newer("v0.9.6.1", "0.9.6") and updates.is_newer("0.9.7", "0.9.6.1")
    assert not updates.is_newer("0.9.6", "0.9.6.1") and not updates.is_newer("0.9.6.0", "0.9.6")
    QSettings("hallucinate", "hallucinate").remove("updates")
    asked = []

    def fake_fetch():
        asked.append(1)
        return {"version": "99.0.0", "url": "https://example.invalid/release"}

    checker = updates.UpdateChecker(fetch=fake_fetch)
    try:
        assert not checker.enabled and not checker.available and asked == []  # off by default, nothing sent
        checker.setEnabled(True)  # turning it on checks straight away
        assert wait_for(lambda: not checker.busy and asked)
        assert checker.available and checker.latestVersion == "99.0.0"
        assert checker.status == "Hallucinate 99.0.0 is available"
        checker.setEnabled(False)
        assert not checker.enabled
    finally:
        checker.shutdown()
        QSettings("hallucinate", "hallucinate").remove("updates")


def test_update_check_is_off_inside_flatpak(qapp, monkeypatch):
    from hallucinate import updates

    monkeypatch.setenv("FLATPAK_ID", "io.github.phosphene_dev.Hallucinate")
    checker = updates.UpdateChecker(fetch=lambda: {"version": "99.0.0", "url": "x"})
    try:
        assert not checker.supported
        checker.checkNow()
        assert not checker.busy and not checker.available
    finally:
        checker.shutdown()
