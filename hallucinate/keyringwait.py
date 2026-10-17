"""Reading the system keyring without letting it hang the window.

A locked keyring waits for its unlock prompt, and on some desktops (a bare Wayland session without a secret
agent) that prompt never shows, so a read on the window's thread could hang the app at start. Reads here run
on a thread: if they answer quickly (the usual case) the caller gets the values at once; if not, the app
carries on and `late` is called (from that thread) once the keyring answers."""
import threading

WAIT_S = 3.0


def read(get, keys, late=None, timeout=WAIT_S):
    """{"values": {key: value or ""}, "error": ""} from get(key) for each key, or None when the keyring
    didn't answer within `timeout` (then late(result) follows when it does)."""
    result = {}
    done = threading.Event()
    lock = threading.Lock()
    waited_out = []

    def run():
        try:
            values, error = {k: get(k) or "" for k in keys}, ""
        except Exception as exc:  # noqa: BLE001 - no keyring, a locked one refused, a broken backend
            values, error = {}, str(exc) or type(exc).__name__
        with lock:
            result.update(values=values, error=error)
            done.set()
            gave_up = bool(waited_out)
        if gave_up and late is not None:
            late(dict(result))

    threading.Thread(target=run, name="keyring", daemon=True).start()
    done.wait(timeout)
    with lock:
        if done.is_set():
            return dict(result)
        waited_out.append(True)
        return None


WRITE_WAIT_S = 10.0
NO_ANSWER = "the system keyring didn't answer (is it locked?)"


def call(fn, timeout=WRITE_WAIT_S):
    """Run fn() (keyring writes) the same way: "" when it worked, the error's text when it failed, NO_ANSWER
    when the keyring didn't answer in time (it may still finish afterwards)."""
    got = read(lambda _key: fn(), ("call",), timeout=timeout)
    return NO_ANSWER if got is None else got["error"]
