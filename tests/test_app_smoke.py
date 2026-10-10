import os
import subprocess
import sys
from uuid import uuid4

import pytest

pytest.importorskip("PySide6.QtQml", exc_type=ImportError)


def test_app_launches_offscreen(tmp_path, music):
    env = dict(
        os.environ,
        QT_QPA_PLATFORM="offscreen",
        HALLUCINATE_DATA=str(tmp_path / "data"),
        HALLUCINATE_DISABLE_LEGACY_MIGRATION="1",
        HALLUCINATE_CONTROL_SOCKET="hallucinate-smoke-" + uuid4().hex,
    )
    r = subprocess.run(
        [sys.executable, "-m", "hallucinate", str(music), "--quit-after", "2500"],
        env=env, capture_output=True, text=True, timeout=60,
    )
    if "ImportError" in r.stderr and "PySide6" in r.stderr:
        pytest.skip("PySide6 is not usable in this environment")
    assert r.returncode == 0, r.stderr
    errors = [l for l in r.stderr.splitlines()
              if ".qml" in l and "Error decoding" not in l]
    assert not errors, r.stderr
    assert "media controls unavailable" not in r.stderr  # Windows: SMTC must come up


def test_legacy_module_name_remains_a_working_cli_shim():
    result = subprocess.run(
        [sys.executable, "-m", "musicplayer", "--version"],
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0
    assert result.stdout.strip()
