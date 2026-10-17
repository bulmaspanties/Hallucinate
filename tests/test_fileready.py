import threading
import time

from conftest import wait_for


def test_soon_answers_at_once_when_quick():
    from hallucinate import fileready

    assert fileready.soon(lambda: 42, lambda _v: None, 1.0) == (True, 42)
    assert fileready.soon(lambda: 1 / 0, lambda _v: None, 1.0) == (True, False)


def test_soon_hands_a_late_answer_on():
    from hallucinate import fileready

    gate, late = threading.Event(), []
    started = time.monotonic()
    assert fileready.soon(lambda: gate.wait(5) and "yes", late.append, 0.05) == (False, None)
    assert time.monotonic() - started < 1
    gate.set()
    assert wait_for(lambda: late == ["yes"])


def test_file_ready_answers_on_its_own_thread_and_only_the_latest(qapp, tmp_path):
    from hallucinate.fileready import FileReady

    good = tmp_path / "a.flac"
    good.write_bytes(b"x" * 10)
    ready, got = FileReady(), []
    ready.check(str(tmp_path / "missing.flac"), lambda ok: got.append(("first", ok)))
    ready.check(str(good), lambda ok: got.append(("second", ok)))
    assert wait_for(lambda: got)
    time.sleep(0.1)
    assert got == [("second", True)]
    ready.check(str(tmp_path / "missing.flac"), lambda ok: got.append(("third", ok)))
    assert wait_for(lambda: len(got) == 2) and got[1] == ("third", False)
    ready.check(str(good), lambda ok: got.append(("cancelled", ok)))
    ready.cancel()
    time.sleep(0.2)
    qapp.processEvents()
    assert len(got) == 2 and not ready.waiting
