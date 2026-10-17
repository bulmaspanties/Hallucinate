"""Songs from a music server (Subsonic and, later, Jellyfin), kept in the library beside your own files.

Such a song's path is `subsonic://<server>/<song id>`: an address only Hallucinate understands, with no login
in it, so the library, the session, backups and media controls never hold a password or token. It becomes a
link to stream only when it's about to play (`stream_url`), from whichever server is registered for it, and
`available` says whether that server can be reached right now (offline mode and a server that didn't answer
make its songs unavailable, and the player moves past them)."""
import threading
import urllib.parse

SCHEMES = ("subsonic", "jellyfin")
# In SQL: a row that's a file on this computer (not a server's song). Local paths never start "word://".
SQL_LOCAL = "path NOT GLOB '[a-z]*://*'"

_lock = threading.Lock()
_servers = {}  # (scheme, server id) -> object with stream_url(item id); set by the Servers service
_down = set()  # (scheme, server id) that didn't answer last time


def is_remote(path):
    return isinstance(path, str) and path.split("://", 1)[0] in SCHEMES and "://" in path


def make_path(scheme, server_id, item_id):
    return f"{scheme}://{server_id}/{urllib.parse.quote(str(item_id), safe='')}"


def parse(path):
    """(scheme, server id, item id) of a server song's path, or None."""
    if not is_remote(path):
        return None
    scheme, rest = path.split("://", 1)
    server_id, _, item = rest.partition("/")
    if not server_id or not item:
        return None
    return scheme, server_id, urllib.parse.unquote(item)


def prefix(scheme, server_id):
    """What every path of one server's songs starts with."""
    return f"{scheme}://{server_id}/"


def register(scheme, server_id, server):
    with _lock:
        _servers[(scheme, server_id)] = server


def forget(scheme, server_id):
    with _lock:
        _servers.pop((scheme, server_id), None)
        _down.discard((scheme, server_id))


def set_reachable(scheme, server_id, ok):
    with _lock:
        (_down.discard if ok else _down.add)((scheme, server_id))


def available(path):
    """Whether a server song can be played now: its server is set up, answered last time, and Hallucinate
    isn't in offline mode."""
    from . import net

    parts = parse(path)
    if parts is None or net.is_offline():
        return False
    key = parts[:2]
    with _lock:
        return key in _servers and key not in _down


def stream_url(path):
    """The link to play a server song from (with this request's login in it), or "" if it can't be played."""
    parts = parse(path)
    if parts is None or not available(path):
        return ""
    with _lock:
        server = _servers.get(parts[:2])
    try:
        return server.stream_url(parts[2]) if server is not None else ""
    except Exception:  # noqa: BLE001 - a server that can't make a link is just unavailable
        return ""


def host(path):
    """The host name a server song streams from (for checking it resolves before playing), or ""."""
    parts = parse(path)
    if parts is None:
        return ""
    with _lock:
        server = _servers.get(parts[:2])
    base = getattr(server, "base", "") if server is not None else ""
    return urllib.parse.urlsplit(base).hostname or "" if base else ""
