"""Switch output devices on a real PulseAudio server with two null sinks (skipped without PulseAudio).

Runs in a subprocess because Qt connects to the sound server once per process."""
import json
import os
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest
from audio import FFMPEG, encode

pytestmark = pytest.mark.skipif(
    not sys.platform.startswith("linux") or not (shutil.which("pulseaudio") and shutil.which("pactl") and FFMPEG),
    reason="needs PulseAudio and ffmpeg",
)

SCRIPT = textwrap.dedent("""
    import json, subprocess, sys
    from PySide6.QtCore import QCoreApplication, QElapsedTimer
    from PySide6.QtGui import QGuiApplication
    from hallucinate.player import Player

    app = QGuiApplication([])

    def spin(ms):
        t = QElapsedTimer()
        t.start()
        while t.elapsed() < ms:
            QCoreApplication.processEvents()
            QCoreApplication.instance().thread().msleep(10)

    def pactl(*args):
        return subprocess.run(["pactl", *args], capture_output=True, text=True, check=True).stdout

    def sinks_in_use():
        names = {line.split()[0]: line.split()[1] for line in pactl("list", "short", "sinks").splitlines()}
        return sorted({names.get(line.split(":")[1].strip(), "?")
                       for line in pactl("list", "sink-inputs").splitlines() if line.strip().startswith("Sink:")})

    def wait_sinks(expected, ms=5000):
        t = QElapsedTimer()
        t.start()
        while t.elapsed() < ms and sinks_in_use() != expected:
            spin(50)
        return sinks_in_use()

    result = {}
    player = Player()
    player.setEqEnabled(sys.argv[2] == "eq")
    key = {d["name"]: d["key"] for d in player.outputDevices}["DAC"]
    player.playList([{"path": sys.argv[1], "title": "t", "artist": "a", "album": "b", "duration": 20}], 0)
    result["default"] = wait_sinks(["speakers"])
    player.setOutputDevice(key)
    result["chosen"] = wait_sinks(["dac"])
    module = [line.split()[0] for line in pactl("list", "short", "modules").splitlines() if "sink_name=dac" in line]
    pactl("unload-module", module[0])
    result["unplugged"] = wait_sinks(["speakers"])
    result["state_unplugged"] = player.state
    pactl("load-module", "module-null-sink", "sink_name=dac", "sink_properties=device.description=DAC")
    result["replugged"] = wait_sinks(["dac"])
    result["state"] = player.state
    player.setOutputDevice("")
    result["back"] = wait_sinks(["speakers"])
    player.setEqEnabled(False)
    player.shutdown()
    print("RESULT " + json.dumps(result), flush=True)
""")


@pytest.fixture
def pulse(tmp_path):
    runtime = tmp_path / "run"
    runtime.mkdir(mode=0o700)
    env = {**os.environ, "XDG_RUNTIME_DIR": str(runtime), "HOME": str(tmp_path)}
    env.pop("PULSE_SERVER", None)
    started = subprocess.run(
        ["pulseaudio", "--daemonize", "--exit-idle-time=-1", "-n", "--load=module-native-protocol-unix",
         "--load=module-null-sink sink_name=speakers sink_properties=device.description=Speakers",
         "--load=module-null-sink sink_name=dac sink_properties=device.description=DAC"],
        env=env, capture_output=True, text=True, timeout=30,
    )
    if started.returncode != 0:
        pytest.skip(f"PulseAudio did not start: {started.stderr.strip()[-300:]}")
    yield env
    subprocess.run(["pulseaudio", "--kill"], env=env, capture_output=True, timeout=30)


@pytest.mark.parametrize("mode", ["direct", "eq"])
def test_output_device_switch_unplug_and_replug(pulse, tmp_path, mode):
    clip = encode(tmp_path / "tone.flac", "flac", seconds=20)
    env = {**pulse, "QT_QPA_PLATFORM": "offscreen", "PYTHONPATH": str(Path(__file__).parents[1])}
    run = subprocess.run([sys.executable, "-c", SCRIPT, str(clip), mode], env=env, capture_output=True, text=True,
                         timeout=120)
    lines = [line for line in run.stdout.splitlines() if line.startswith("RESULT ")]
    assert lines, run.stdout[-2000:] + run.stderr[-2000:]
    result = json.loads(lines[0][len("RESULT "):])
    assert result == {
        "default": ["speakers"],
        "chosen": ["dac"],
        "unplugged": ["speakers"],
        "state_unplugged": "Playing",
        "replugged": ["dac"],
        "state": "Playing",
        "back": ["speakers"],
    }, run.stderr[-2000:]
