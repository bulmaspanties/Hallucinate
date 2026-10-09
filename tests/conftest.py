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

from musicplayer.core.db import Database
from musicplayer.core.scanner import Scanner

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
    from PySide6.QtGui import QGuiApplication
    app = QGuiApplication.instance() or QGuiApplication([])
    yield app


def wait_for(cond, timeout=8.0, step=20):
    """Spin the Qt event loop until cond() is truthy; returns its last value."""
    import time

    from PySide6.QtTest import QTest
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        v = cond()
        if v:
            return v
        QTest.qWait(step)
    return cond()
