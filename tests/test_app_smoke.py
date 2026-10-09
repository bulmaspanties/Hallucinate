import os
import subprocess
import sys

import pytest

pytest.importorskip("PySide6.QtQml", exc_type=ImportError)


def test_app_launches_offscreen(tmp_path, music):
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen", MUSICPLAYER_DATA=str(tmp_path / "data"))
    r = subprocess.run(
        [sys.executable, "-m", "musicplayer", str(music), "--quit-after", "2500"],
        env=env, capture_output=True, text=True, timeout=60,
    )
    if "ImportError" in r.stderr and "PySide6" in r.stderr:
        pytest.skip("PySide6 is not usable in this environment")
    assert r.returncode == 0, r.stderr
    errors = [l for l in r.stderr.splitlines()
              if ".qml" in l and "Error decoding" not in l]
    assert not errors, r.stderr
