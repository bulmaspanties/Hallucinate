"""Check that Qt Multimedia can decode audio files: python3 decode_check.py FILE...

CI runs this inside the built Flatpak, where codec support comes from the runtime rather than from
PySide6's bundled FFmpeg. Each file passes once at least half a second of PCM has been decoded."""
import sys

from PySide6.QtCore import QCoreApplication, QElapsedTimer, QUrl
from PySide6.QtGui import QGuiApplication
from PySide6.QtMultimedia import QAudioBufferOutput, QMediaPlayer

NEEDED_SECONDS = 0.5
TIMEOUT_MS = 15_000


def decoded_seconds(path):
    player = QMediaPlayer()
    output = QAudioBufferOutput()
    player.setAudioBufferOutput(output)
    decoded = {"seconds": 0.0}
    errors = []

    def on_buffer(buffer):
        rate = buffer.format().sampleRate()
        if rate > 0:
            decoded["seconds"] += buffer.frameCount() / rate

    output.audioBufferReceived.connect(on_buffer)
    player.errorOccurred.connect(lambda _error, text: errors.append(text))
    player.setSource(QUrl.fromLocalFile(path))
    player.play()
    timer = QElapsedTimer()
    timer.start()
    while decoded["seconds"] < NEEDED_SECONDS and not errors and timer.elapsed() < TIMEOUT_MS:
        QCoreApplication.processEvents()
        QCoreApplication.instance().thread().msleep(10)
    player.stop()
    return decoded["seconds"], "; ".join(errors)


def main(paths):
    app = QGuiApplication([sys.argv[0]])  # noqa: F841 - keeps the application alive
    failed = False
    for path in paths:
        seconds, error = decoded_seconds(path)
        ok = seconds >= NEEDED_SECONDS
        failed |= not ok
        detail = f"error: {error}" if error else f"{seconds:.2f} s decoded"
        print(f"{'ok  ' if ok else 'FAIL'} {path}: {detail}", flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
