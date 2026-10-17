"""A Subsonic server's library (Navidrome, Gonic, Airsonic, Ampache and others speak this API).

Only what Hallucinate needs: check the login, read every song, and make the links to stream a song and fetch
its cover. Every request goes through net.urlopen (web links only, offline mode, size limits), and everything
the server sends is checked before it's used: a server is somewhere else, and what it says is just data.

The password never leaves this module in the clear: each request carries a fresh salt and md5(password + salt),
as the API asks. That's a weak hash, so on a plain http:// link anyone on the network could replay a request;
the app says so when you add a server that isn't https."""
import hashlib
import json
import re
import secrets
import urllib.parse
import urllib.request

from . import net

API_VERSION = "1.16.1"
CLIENT = "Hallucinate"
PAGE = 500  # songs asked for at a time
MAX_SONGS = 2_000_000  # a sanity limit, far above any real library
MAX_TEXT = 1000


class SubsonicError(OSError):
    """The server answered but said no (a wrong password, say), in words people can read."""

    MESSAGES = {
        10: "the server says something is missing from the request",
        20: "the server is too old for Hallucinate",
        30: "the server is newer than Hallucinate understands",
        40: "the user name or password is wrong",
        41: "this server needs an API key instead of a password",
        50: "that user isn't allowed to do this",
        60: "the server's trial period is over",
        70: "the server couldn't find it",
    }

    def __init__(self, code, message=""):
        self.code = code
        super().__init__(self.MESSAGES.get(code) or (message or "the server refused")[:200])


def normalise_base(url):
    """The server's base link from what was typed: https://music.example.com, without a trailing /rest."""
    url = (url or "").strip()
    if url and "://" not in url:
        if re.match(r"^[a-z][a-z0-9+.-]*:(?!\d)", url, re.I):  # another kind of link (javascript:, file:)
            raise ValueError("That isn't a web link: it should start with http:// or https://")
        url = "https://" + url  # typed without one: music.example.com, or nas.local:4533
    url = url.rstrip("/")
    if url.lower().endswith("/rest"):
        url = url[:-5]
    if not net.is_web_url(url):
        raise ValueError("That isn't a web link: it should start with http:// or https://")
    parts = urllib.parse.urlsplit(url)
    if parts.username or parts.password or parts.query or parts.fragment:
        raise ValueError("Type the server's link only; the user name and password go in their own boxes")
    return url


def is_private_link(base):
    """Whether the link is https, or plain http to this computer or the home network (where it's common)."""
    parts = urllib.parse.urlsplit(base)
    if parts.scheme == "https":
        return True
    host = (parts.hostname or "").lower()
    if host in ("localhost", "127.0.0.1", "::1") or host.endswith((".local", ".lan", ".home", ".internal")):
        return True
    import ipaddress

    try:
        return ipaddress.ip_address(host).is_private
    except ValueError:
        return False


def _text(value, limit=MAX_TEXT):
    return value[:limit] if isinstance(value, str) else ""


def _int(value, low=0, high=10**12):
    if isinstance(value, bool):
        return low
    if isinstance(value, (int, float)) and value == value:  # not NaN
        return max(low, min(high, int(value)))
    if isinstance(value, str) and value.strip().isdigit():
        return max(low, min(high, int(value.strip())))
    return low


def _gain(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value != value:
        return None
    return value if -60.0 <= value <= 60.0 else None


def song_from(item):
    """A song the server listed, as plain checked values, or None if it isn't one."""
    if not isinstance(item, dict) or item.get("isDir") is True or item.get("isVideo") is True:
        return None
    sid = _text(item.get("id"), 200)
    if not sid:
        return None
    rg = item.get("replayGain") if isinstance(item.get("replayGain"), dict) else {}
    artist = _text(item.get("artist"))
    return {
        "id": sid,
        "title": _text(item.get("title")) or "Unknown title",
        "artist": artist,
        "album_artist": _text(item.get("displayAlbumArtist")) or _text(item.get("albumArtist")) or artist,
        "album": _text(item.get("album")),
        "album_id": _text(item.get("albumId"), 200),
        "track_no": _int(item.get("track"), 0, 9999),
        "disc_no": _int(item.get("discNumber"), 0, 999),
        "year": _int(item.get("year"), 0, 9999),
        "genre": _text(item.get("genre"), 200),
        "duration": float(_int(item.get("duration"), 0, 10**7)),
        "suffix": _text(item.get("suffix"), 16).lower(),
        "bitrate": _int(item.get("bitRate"), 0, 100_000),
        "sample_rate": _int(item.get("samplingRate"), 0, 10**6),
        "size": _int(item.get("size")),
        "cover": _text(item.get("coverArt"), 200),
        "rating": _int(item.get("userRating"), 0, 5),
        "starred": bool(item.get("starred")),
        "rg_track": _gain(rg.get("trackGain")),
        "rg_album": _gain(rg.get("albumGain")),
        "rg_peak": _gain(rg.get("trackPeak")),
        "changed": _text(item.get("created"), 40),
    }


class Server:
    def __init__(self, base, user, password, timeout=20):
        self.base = normalise_base(base)
        self.user = user or ""
        self._password = password or ""
        self.timeout = timeout

    def _auth(self):
        salt = secrets.token_hex(8)
        token = hashlib.md5((self._password + salt).encode("utf-8"), usedforsecurity=False).hexdigest()
        return {"u": self.user, "t": token, "s": salt, "v": API_VERSION, "c": CLIENT}

    def url(self, endpoint, **params):
        """A link to the API (with this request's login in it: never logged or shown)."""
        query = {**self._auth(), **{k: v for k, v in params.items() if v is not None}}
        return f"{self.base}/rest/{endpoint}?{urllib.parse.urlencode(query)}"

    def call(self, endpoint, limit=16 * 1024 * 1024, **params):
        """The API's answer to `endpoint` as a dict. Raises SubsonicError when the server says no, OSError when
        it can't be reached, ValueError when the answer isn't a Subsonic one."""
        request = urllib.request.Request(self.url(endpoint, f="json", **params),
                                         headers={"User-Agent": f"{CLIENT} (+https://github.com/Phosphene-dev/Hallucinate)"})
        with net.urlopen(request, timeout=self.timeout, limit=limit) as resp:
            raw = resp.read()
        try:
            body = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("That doesn't look like a Subsonic server") from exc
        answer = body.get("subsonic-response") if isinstance(body, dict) else None
        if not isinstance(answer, dict):
            raise ValueError("That doesn't look like a Subsonic server")
        if answer.get("status") != "ok":
            err = answer.get("error") if isinstance(answer.get("error"), dict) else {}
            raise SubsonicError(_int(err.get("code")), _text(err.get("message")))
        return answer

    def ping(self):
        """Check the link and login: {"version", "type", "server_version"}."""
        answer = self.call("ping")
        return {"version": _text(answer.get("version"), 20), "type": _text(answer.get("type"), 40),
                "server_version": _text(answer.get("serverVersion"), 40)}

    def pages(self, page=PAGE, should_stop=lambda: False):
        """Every song on the server as lists of checked songs, a page at a time (search3 with an empty query,
        which Navidrome, Gonic and Airsonic all answer with everything; servers that don't are read album by
        album instead). Bounded: it stops when a page brings nothing new, so a server that ignores the offset
        or sends junk can't keep it going."""
        offset, seen = 0, set()
        while len(seen) < MAX_SONGS and offset < MAX_SONGS and not should_stop():
            result = self.call("search3", query="", songCount=page, songOffset=offset, artistCount=0,
                               albumCount=0).get("searchResult3")
            items = result.get("song") if isinstance(result, dict) else None
            if not isinstance(items, list) or not items:
                break
            fresh = [s for s in (song_from(i) for i in items[:page]) if s and s["id"] not in seen]
            if not fresh:
                return  # the same page again, or nothing usable: done
            seen.update(s["id"] for s in fresh)
            yield fresh
            if len(items) < page:
                return
            offset += len(items)
        if offset == 0 and not seen and not should_stop():
            yield from self._pages_by_album(page, should_stop)

    def _pages_by_album(self, page=PAGE, should_stop=lambda: False):
        offset, albums_seen, songs_seen = 0, set(), 0
        while offset < MAX_SONGS and not should_stop():
            result = self.call("getAlbumList2", type="alphabeticalByName", size=page, offset=offset)
            listing = result.get("albumList2") if isinstance(result.get("albumList2"), dict) else {}
            albums = listing.get("album")
            if not isinstance(albums, list) or not albums:
                return
            ids = [a["id"] for a in albums[:page] if isinstance(a, dict) and _text(a.get("id"), 200)]
            new_ids = [i for i in ids if i not in albums_seen]
            if not new_ids:
                return
            albums_seen.update(new_ids)
            for aid in new_ids:
                if should_stop() or songs_seen >= MAX_SONGS:
                    return
                detail = self.call("getAlbum", id=aid).get("album")
                found = [s for s in (song_from(i) for i in ((detail.get("song") if isinstance(detail, dict) else None)
                                                            or [])[:5000]) if s]
                songs_seen += len(found)
                if found:
                    yield found
            if len(albums) < page:
                return
            offset += len(albums)

    def songs(self, page=PAGE):
        for chunk in self.pages(page):
            yield from chunk

    def stream_url(self, song_id):
        """The link a song plays from, as the server stores it (no transcoding)."""
        return self.url("stream", id=song_id, format="raw")

    def cover_url(self, cover_id, size=600):
        return self.url("getCoverArt", id=cover_id, size=size)

    def cover(self, cover_id, size=600):
        """The cover's bytes (a JPEG or PNG), or b"" if the server has none."""
        from .artfetch import MAX_BYTES

        request = urllib.request.Request(self.cover_url(cover_id, size), headers={"User-Agent": CLIENT})
        with net.urlopen(request, timeout=self.timeout, limit=MAX_BYTES) as resp:
            data = resp.read()
        return data if data[:3] == b"\xff\xd8\xff" or data[:8] == b"\x89PNG\r\n\x1a\n" else b""

    def scrobble(self, song_id, when_ms=None, submission=True):
        """Tell the server a song was played (its own play counts), or is playing now (submission=False)."""
        self.call("scrobble", id=song_id, time=when_ms, submission="true" if submission else "false")

    def set_rating(self, song_id, stars):
        self.call("setRating", id=song_id, rating=max(0, min(5, int(stars))))
