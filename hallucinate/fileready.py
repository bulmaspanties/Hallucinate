"""Opening a song file for analysis without letting a slow disk hang the window.

QAudioDecoder opens its file on the thread that starts it, and waveforms and ReplayGain have to start it on
the window's thread (see waveform.py). A file on a disk that's spinning up, or on a network share that has
gone away, would hold the window for as long as the open takes. So each file is first opened and read a
little on a thread of its own: once that answers, the disk is awake and the file cached, and the decoder's own
open is quick. A file that doesn't answer in WAIT_MS is skipped (its thread is left to finish by itself)."""
import threading
import weakref

from PySide6.QtCore import QObject, QTimer, Signal, Slot

WAIT_MS = 30_000
READ = 64 * 1024


def _try_open(path):
    try:
        with open(path, "rb") as fh:
            fh.read(READ)
        return True
    except OSError:
        return False


class FileReady(QObject):
    """check(path, then) calls then(ok) on this object's thread once `path` opened (or failed, or timed out).
    Only the latest check counts: starting another, or cancel(), drops an earlier one's answer."""

    _answered = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._token = 0
        self._then = None
        self._answered.connect(self._on_answered)

    def check(self, path, then):
        self._token += 1
        token, self._then = self._token, then
        me = weakref.ref(self)

        def run():
            ok = _try_open(path)
            owner = me()
            try:
                if owner is not None:
                    owner._answered.emit((token, ok))
            except RuntimeError:  # gone meanwhile (the app closed)
                pass

        threading.Thread(target=run, name="file-ready", daemon=True).start()
        QTimer.singleShot(WAIT_MS, self, lambda: me() is not None and me()._on_answered((token, False)))

    def cancel(self):
        self._token += 1
        self._then = None

    @property
    def waiting(self):
        return self._then is not None

    @Slot(object)
    def _on_answered(self, answer):
        token, ok = answer
        if token != self._token or self._then is None:
            return
        then, self._then = self._then, None
        then(ok)


def soon(fn, late, timeout):
    """fn() on a thread of its own. (True, its value) if it answers within `timeout` seconds; otherwise
    (False, None), and late(value) is called from that thread once it does."""
    box = {}
    done = threading.Event()
    lock = threading.Lock()

    def run():
        try:
            value = fn()
        except Exception:  # noqa: BLE001 - a check that broke counts as "no"
            value = False
        with lock:
            box["value"] = value
            done.set()
            gave_up = box.get("gave_up", False)
        if gave_up:
            late(value)

    threading.Thread(target=run, name="file-check", daemon=True).start()
    done.wait(timeout)
    with lock:
        if done.is_set():
            return True, box["value"]
        box["gave_up"] = True
        return False, None
