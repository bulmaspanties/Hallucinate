"""Guard against PySide6 builds whose Signal.emit() leaks a reference to True (PySide6 6.12.0).

Below Python 3.12 True is a normal refcounted object, so each leaked reference brings the interpreter closer to
freeing True and crashing; pyproject.toml keeps those Pythons on an unaffected PySide6."""
import sys

from PySide6.QtCore import QObject, Signal


class _Emitter(QObject):
    fired = Signal()


def test_signal_emit_keeps_true_alive(qapp):
    emitter = _Emitter()
    emitter.fired.emit()
    before = sys.getrefcount(True)
    for _ in range(1000):
        emitter.fired.emit()
    # Immortal True (3.12+) reports a constant count; otherwise it must not shrink by one per emit.
    assert sys.getrefcount(True) - before > -100
