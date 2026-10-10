import gc
import os
import struct
import sys
import tempfile
import wave

sys.path.insert(0, os.path.dirname(__file__))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
# Keep QSettings (volume etc.) out of the real user config.
os.environ["XDG_CONFIG_HOME"] = tempfile.mkdtemp(prefix="mp-test-config-")

import pytest
from mutagen.id3 import APIC, ID3, TALB, TIT2, TPE1, TPE2, TRCK
from mutagen.wave import WAVE

from hallucinate.core.db import Database
from hallucinate.core.scanner import Scanner

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


def make_mp3(path, title=None, artist=None, album=None, album_artist=None, track=None, art=None):
    frame = b"\xff\xfb\x90\x00" + b"\x00" * 413  # MPEG1 L3 128kbps 44.1kHz
    with open(path, "wb") as f:
        f.write(frame * 40)
    tags = ID3()
    if title:
        tags.add(TIT2(encoding=3, text=title))
    if artist:
        tags.add(TPE1(encoding=3, text=artist))
    if album:
        tags.add(TALB(encoding=3, text=album))
    if album_artist:
        tags.add(TPE2(encoding=3, text=album_artist))
    if track:
        tags.add(TRCK(encoding=3, text=track))
    if art:
        tags.add(APIC(encoding=3, mime="image/png", type=3, desc="", data=art))
    if len(tags):
        tags.save(path)


def make_wav(path, title, artist, album):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(8000)
        w.writeframes(struct.pack("<h", 0) * 4000)
    f = WAVE(str(path))
    f.add_tags()
    f.tags.add(TIT2(encoding=3, text=title))
    f.tags.add(TPE1(encoding=3, text=artist))
    f.tags.add(TALB(encoding=3, text=album))
    f.save()


@pytest.fixture
def music(tmp_path):
    root = tmp_path / "Music"
    a = root / "Aurora Vale" / "Northern Lights"
    b = root / "Blue Harbor" / "Tidal"
    a.mkdir(parents=True)
    b.mkdir(parents=True)
    make_mp3(a / "01.mp3", "Echoes of Dawn", "Aurora Vale", "Northern Lights", "Aurora Vale", "1/2", art=PNG)
    make_mp3(a / "02.mp3", "Midnight Rain", "Aurora Vale", "Northern Lights", "Aurora Vale", "2/2")
    make_wav(b / "01.wav", "Café Noir", "Blue Harbor", "Tidal")
    make_mp3(root / "loose.mp3")
    (root / "junk.mp3").write_text("not audio")
    (root / "notes.txt").write_text("hi")
    return root


@pytest.fixture
def db(tmp_path):
    d = Database(tmp_path / "lib.db")
    yield d
    d.close()


@pytest.fixture
def scan(db, tmp_path):
    art = tmp_path / "art"
    art.mkdir()

    def run(folder):
        return Scanner(db, art).scan([str(folder)])

    return run


def touch_newer(path):
    st = os.stat(path)
    os.utime(path, (st.st_atime, st.st_mtime + 10))


@pytest.fixture(scope="session")
def qapp():
    pytest.importorskip("PySide6.QtMultimedia", exc_type=ImportError)
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    yield app


def wait_for(cond, timeout=8.0, step=20):
    """Spin the Qt event loop until cond() is truthy; returns its last value."""
    import time

    from PySide6.QtCore import QCoreApplication
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        v = cond()
        if v:
            return v
        # QTest.qWait keeps the GIL while it waits, starving worker threads; sleep() releases it.
        QCoreApplication.processEvents()
        time.sleep(step / 1000)
    return cond()


def pytest_unconfigure(config):
    # PySide6 on Python 3.11 can abort during interpreter finalization (GC of Qt-owned objects) after
    # all tests passed; exit directly with the real status once reporting is done.
    import sys

    status = getattr(config, "_exit_status", None)
    if status is not None and sys.version_info[:2] == (3, 11):
        sys.stdout.flush()
        sys.stderr.flush()
        os._exit(int(status))


def pytest_sessionfinish(session, exitstatus):
    session.config._exit_status = int(exitstatus)


_LEAKED_QOBJECTS = []


@pytest.fixture(autouse=True)
def _no_cyclic_qobjects():
    """Fail the test that leaves a QObject in a reference cycle.

    The cycle collector would otherwise destroy it later at an arbitrary point, often in the middle of an
    unrelated test with worker threads running, which crashed CI with segfaults. Leaked objects are kept
    alive here instead, since leaking is harmless but collecting them is not."""
    yield
    from PySide6.QtCore import QObject

    gc.set_debug(gc.DEBUG_SAVEALL)
    try:
        gc.collect()
        leaked = [o for o in gc.garbage if isinstance(o, QObject)]
    finally:
        gc.set_debug(0)
        _LEAKED_QOBJECTS.extend(gc.garbage)
        gc.garbage.clear()
    if leaked:
        pytest.fail(
            "QObjects left in reference cycles: " + ", ".join(sorted({type(o).__name__ for o in leaked}))
        )


@pytest.fixture(scope="session", autouse=True)
def _isolated_qsettings(tmp_path_factory):
    """Never let tests read or clear the developer's real QSettings."""
    from PySide6.QtCore import QSettings

    root = str(tmp_path_factory.mktemp("qsettings"))
    for scope in (QSettings.Scope.UserScope, QSettings.Scope.SystemScope):
        QSettings.setPath(QSettings.Format.NativeFormat, scope, root)
        QSettings.setPath(QSettings.Format.IniFormat, scope, root)
    yield
