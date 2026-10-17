"""Crash records: what a run leaves behind when it crashes or hits an unhandled error, and the offer to copy it."""
import os
import subprocess
import sys
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(folder, body):
    """Run `body` in a fresh interpreter with crash recording installed in `folder`."""
    script = textwrap.dedent(f"""
        import sys
        sys.path.insert(0, {str(ROOT)!r})
        from hallucinate import crashlog
        crashlog.install({str(folder)!r})
    """) + textwrap.dedent(body)
    return subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, timeout=60)


def test_nothing_to_report_after_a_clean_exit(tmp_path):
    from hallucinate import crashlog

    assert crashlog.take_previous(tmp_path) == ("", False)
    r = run(tmp_path, "crashlog.finish()")
    assert r.returncode == 0, r.stderr
    assert crashlog.take_previous(tmp_path) == ("", False)


def test_a_native_crash_is_recorded_with_the_stack(tmp_path):
    from hallucinate import crashlog

    r = run(tmp_path, """
        import faulthandler
        def deep_in_the_player():
            faulthandler._sigsegv()
        deep_in_the_player()
    """)
    assert r.returncode != 0
    report, crashed = crashlog.take_previous(tmp_path)
    assert crashed
    assert "Fatal Python error" in report and "deep_in_the_player" in report
    assert crashlog.take_previous(tmp_path) == ("", False)  # offered once


def test_a_killed_run_is_not_reported_as_a_crash(tmp_path):
    """Killed or powered off: the log has only its start line, which says nothing about a fault."""
    from hallucinate import crashlog

    r = run(tmp_path, "import os, signal; os.kill(os.getpid(), signal.SIGKILL)")
    assert r.returncode != 0
    assert (tmp_path / "native.log").exists()
    assert crashlog.take_previous(tmp_path) == ("", False)


def test_unhandled_errors_are_recorded_without_home_paths_or_song_files(tmp_path):
    from hallucinate import crashlog

    home = os.path.expanduser("~")
    r = run(tmp_path, f"""
        import threading
        def scan():
            raise ValueError("bad tag in " + {home!r} + "/Music/song.flac")
        t = threading.Thread(target=scan, name="scanner"); t.start(); t.join()

        from PySide6.QtCore import QCoreApplication, QTimer
        app = QCoreApplication([])
        def slot():
            raise RuntimeError("slot failed")
        QTimer.singleShot(0, slot)
        QTimer.singleShot(50, app.quit)
        app.exec()
        crashlog.finish()
    """)
    assert r.returncode == 0, r.stderr
    report, crashed = crashlog.take_previous(tmp_path)
    assert not crashed
    assert "ValueError: bad tag in <song file>" in report and "thread scanner" in report
    assert "RuntimeError: slot failed" in report  # an exception in a Qt slot goes through sys.excepthook
    if home not in ("/", "~"):
        assert home not in report


def test_the_error_log_is_capped(tmp_path):
    from hallucinate import crashlog

    r = run(tmp_path, """
        import threading
        def fail():
            raise ValueError("x" * 5000)
        for _ in range(40):
            t = threading.Thread(target=fail); t.start(); t.join()
        crashlog.finish()
    """)
    assert r.returncode == 0, r.stderr
    assert (tmp_path / "python.log").stat().st_size < crashlog.MAX_BYTES + 20_000


def test_a_freeze_is_recorded_with_what_was_busy_and_when_it_came_back(qapp, tmp_path):
    from conftest import wait_for

    from hallucinate import crashlog

    assert crashlog.install(tmp_path)
    now = [1000.0]
    crashlog.watch_freezes(threshold=20, clock=lambda: now[0], interval=0.05, context=lambda: "window hidden")
    try:
        assert wait_for(lambda: crashlog._state["context"] == "window hidden")
        crashlog._state["beat"] = now[0]
        timer = crashlog._state["watch"][0]
        timer.stop()  # the window "stops responding": no more beats
        for _ in range(5):  # time passes in small steps, so it isn't taken for a sleeping computer
            now[0] += 5
            import time
            time.sleep(0.1)
        assert wait_for(lambda: (tmp_path / "freeze.log").exists())
        text = (tmp_path / "freeze.log").read_text()
        assert "stopped responding" in text and "Just before: window hidden" in text
        crashlog._state["beat"] = now[0]  # it beats again
        assert wait_for(lambda: "came back" in (tmp_path / "freeze.log").read_text())
    finally:
        crashlog.finish()
    report, crashed = crashlog.take_previous(tmp_path)
    assert report.startswith("Stopped responding:") and not crashed
    assert not (tmp_path / "freeze.log").exists()


def test_a_sleeping_computer_is_not_a_freeze(qapp, tmp_path):
    import time

    from hallucinate import crashlog

    assert crashlog.install(tmp_path)
    now = [1000.0]
    crashlog.watch_freezes(threshold=20, clock=lambda: now[0], interval=0.05)
    try:
        crashlog._state["watch"][0].stop()
        now[0] += 3600  # one jump: the whole process was paused
        time.sleep(0.3)
    finally:
        crashlog.finish()
    assert not (tmp_path / "freeze.log").exists()


def test_a_freeze_with_the_gui_thread_stuck_is_still_recorded(qapp, tmp_path):
    """faulthandler's own native thread writes the stacks even if no Python thread can run."""
    import time

    from conftest import wait_for

    from hallucinate import crashlog

    assert crashlog.install(tmp_path)
    crashlog.watch_freezes(threshold=0.3)
    try:
        crashlog._state["watch"][0].stop()  # no more beats
        stacks = tmp_path / "freeze-stacks.log"
        time.sleep(0.6)  # the GUI thread "stuck" for twice the threshold
        assert wait_for(lambda: stacks.exists() and "Thread" in stacks.read_text() or "thread" in stacks.read_text())
    finally:
        crashlog.finish()
    report, crashed = crashlog.take_previous(tmp_path)
    assert report.startswith("Stopped responding:") and "est_crashlog" in report and not crashed


def test_a_clean_run_leaves_no_freeze_record(qapp, tmp_path):
    from hallucinate import crashlog

    assert crashlog.install(tmp_path)
    crashlog.watch_freezes(threshold=30)
    crashlog.stop_watching()
    crashlog.finish()
    assert crashlog.take_previous(tmp_path) == ("", False)
