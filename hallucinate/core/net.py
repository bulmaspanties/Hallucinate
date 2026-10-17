"""The one door to the internet. Every request Hallucinate makes goes through `urlopen` here, so offline mode
can close it in one place (tests/test_offline.py checks that nothing else calls urllib directly)."""
import http.client
import threading
import urllib.error
import urllib.parse
import urllib.request

_lock = threading.Lock()
_offline = False


class OfflineError(urllib.error.URLError):
    """Raised instead of connecting while offline mode is on. A URLError (so an OSError), which every caller
    already treats as "no network": nothing is cached as missing and queued scrobbles stay queued."""

    def __init__(self):
        super().__init__("Offline mode is on")

    def __str__(self):
        return "Offline mode is on"


def describe(exc):
    """A network or feed error in plain words, for showing to people instead of urllib's text
    ("<urlopen error [Errno -2] Name or service not known>")."""
    import http.client
    import socket
    import ssl

    if isinstance(exc, OfflineError):
        return "offline mode is on"
    if isinstance(exc, NotWebLink):
        return "that isn't a web link"
    if isinstance(exc, ResponseTooLarge):
        return "the server sent far more than expected"
    if isinstance(exc, urllib.error.HTTPError):
        return {401: "it needs a login", 403: "the server refused", 404: "nothing was found at that link",
                410: "it's gone from that link", 429: "the server is busy; try again later"}.get(
            exc.code, f"the server answered with an error ({exc.code})" if exc.code < 500
            else "the server is having trouble; try again later")
    reason = exc.reason if isinstance(exc, urllib.error.URLError) else exc
    if isinstance(reason, (socket.timeout, TimeoutError)):
        return "the server took too long to answer"
    if isinstance(reason, ssl.SSLError):
        return "the secure connection couldn't be set up"
    if isinstance(reason, socket.gaierror):
        return "the server couldn't be found (check the link and your connection)"
    if isinstance(reason, ConnectionRefusedError):
        return "the server refused the connection"
    if isinstance(reason, (ConnectionError, http.client.HTTPException)):
        return "the connection dropped"
    if type(exc) is OSError and len(exc.args) == 1 and isinstance(exc.args[0], str):
        text = exc.args[0]  # one of ours, already in words
        return text[:1].lower() + text[1:]
    if isinstance(exc, urllib.error.URLError) or isinstance(reason, OSError):
        if "tunnel" in str(reason).lower() or "proxy" in str(reason).lower():
            return "the proxy wouldn't connect"
        return "the server couldn't be reached"
    if isinstance(exc, ValueError):
        text = str(exc).strip()
        return text[:1].lower() + text[1:] if text else "that doesn't look like what was expected"
    return str(exc)


def set_offline(on):
    global _offline
    with _lock:
        _offline = bool(on)


def is_offline():
    return _offline


# No answer Hallucinate expects is anywhere near this; a server sending more is broken or hostile.
MAX_RESPONSE = 32 * 1024 * 1024


class ResponseTooLarge(OSError, ValueError):
    """The server sent more than allowed. Both an OSError and a ValueError, so every caller's existing "bad
    answer" handling catches it."""


SCHEMES = ("http", "https")


class NotWebLink(urllib.error.URLError):
    """A link that isn't http(s): a feed, playlist or server can name file://, ftp:// or data: links, which
    urllib would happily open (a feed's "episode" at file:///home/you/.ssh/id_rsa would be copied into the
    downloads folder). Nothing Hallucinate fetches is anything but a web address."""

    def __init__(self, url):
        super().__init__(f"not a web link ({urllib.parse.urlsplit(url).scheme or 'no scheme'})")


def is_web_url(url):
    return isinstance(url, str) and urllib.parse.urlsplit(url.strip()).scheme.lower() in SCHEMES


class _WebOnlyRedirects(urllib.request.HTTPRedirectHandler):
    """Follow redirects only to other web addresses (urllib already refuses file://, but not ftp://)."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        target = urllib.parse.urljoin(req.full_url, newurl)
        if not is_web_url(target):
            raise NotWebLink(newurl)
        new = super().redirect_request(req, fp, code, msg, headers, newurl)
        old, to = urllib.parse.urlsplit(req.full_url), urllib.parse.urlsplit(target)
        if new is not None and (to.netloc != old.netloc or to.scheme.lower() != old.scheme.lower()):
            # urllib forwards every header: a token meant for one server mustn't reach the next one, nor go
            # out unencrypted when a secure link redirects to a plain one
            for name in list(new.headers):
                if name.lower() in ("authorization", "cookie"):
                    del new.headers[name]
            for name in list(new.unredirected_hdrs):
                if name.lower() in ("authorization", "cookie"):
                    del new.unredirected_hdrs[name]
        return new


urllib.request.install_opener(urllib.request.build_opener(_WebOnlyRedirects))


def _as_url_error(exc):
    """http.client's protocol errors (a cut-off body, a garbled status line, too many headers) aren't
    OSErrors, so callers' "no network" handling would miss them and a worker could die without reporting
    back. They become URLErrors, which every caller already handles."""
    err = urllib.error.URLError(f"the server's answer was broken ({type(exc).__name__})")
    err.__cause__ = exc
    return err


class _Limited:
    """A response that refuses to read past `limit` bytes in total."""

    def __init__(self, resp, limit):
        self._resp, self._left = resp, limit

    def read(self, amt=-1):
        want = self._left + 1 if amt is None or amt < 0 else min(amt, self._left + 1)
        try:
            data = self._resp.read(want)
        except http.client.HTTPException as exc:
            raise _as_url_error(exc) from exc
        self._left -= len(data)
        if self._left < 0:
            raise ResponseTooLarge("The server's answer was too large")
        return data

    def __getattr__(self, name):
        return getattr(self._resp, name)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self._resp.close()
        return False


def urlopen(request, timeout=10, limit=MAX_RESPONSE):
    """Open a URL unless offline mode is on. Reading more than `limit` bytes raises ResponseTooLarge."""
    if _offline:
        raise OfflineError()
    url = request.full_url if isinstance(request, urllib.request.Request) else str(request)
    if not is_web_url(url):
        raise NotWebLink(url)
    try:
        resp = urllib.request.urlopen(request, timeout=timeout)  # noqa: S310 - http(s) only, checked above
    except http.client.HTTPException as exc:
        raise _as_url_error(exc) from exc
    return _Limited(resp, limit)
