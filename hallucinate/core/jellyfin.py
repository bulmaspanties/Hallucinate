"""A Jellyfin server's music library, read the same way as a Subsonic one (see core/subsonic.py).

Signing in sends the password once, to get an access token; only the token is kept (in the system keyring),
and the server's dashboard can revoke it like any other device. Every request goes through net.urlopen, and
everything the server sends is checked before it's used."""
import json
import urllib.error
import urllib.parse
import urllib.request

from . import net
from .subsonic import MAX_SONGS, PAGE, SubsonicError, _gain, _int, _text, is_private_link, normalise_base  # noqa: F401

CLIENT = "Hallucinate"
TICKS_PER_SECOND = 10_000_000


class JellyfinError(OSError):
    """The server answered but said no, in words people can read."""


def _ascii(value):
    """Safe inside the Authorization header's quoted values."""
    return "".join(c for c in str(value) if c.isalnum() or c in " .-_")[:64]


def song_from(item):
    """A song the server listed, as plain checked values (the same shape as subsonic.song_from), or None."""
    if not isinstance(item, dict) or item.get("Type") not in (None, "Audio"):
        return None
    sid = _text(item.get("Id"), 200)
    if not sid:
        return None
    artists = [a for a in item.get("Artists") or [] if isinstance(a, str)] if isinstance(item.get("Artists"), list) else []
    artist = _text(" / ".join(artists)) or _text(item.get("AlbumArtist"))
    genres = item.get("Genres") if isinstance(item.get("Genres"), list) else []
    source = (item.get("MediaSources") or [{}])[0] if isinstance(item.get("MediaSources"), list) else {}
    source = source if isinstance(source, dict) else {}
    ticks = _int(item.get("RunTimeTicks"), 0, 10**15)
    user = item.get("UserData") if isinstance(item.get("UserData"), dict) else {}
    album_id = _text(item.get("AlbumId"), 200)
    has_cover = bool(item.get("AlbumPrimaryImageTag")) or bool((item.get("ImageTags") or {}).get("Primary")
                                                                if isinstance(item.get("ImageTags"), dict) else False)
    gain = _gain(item.get("NormalizationGain"))
    return {
        "id": sid,
        "title": _text(item.get("Name")) or "Unknown title",
        "artist": artist,
        "album_artist": _text(item.get("AlbumArtist")) or artist,
        "album": _text(item.get("Album")),
        "album_id": album_id,
        "track_no": _int(item.get("IndexNumber"), 0, 9999),
        "disc_no": _int(item.get("ParentIndexNumber"), 0, 999),
        "year": _int(item.get("ProductionYear"), 0, 9999),
        "genre": _text(next((g for g in genres if isinstance(g, str)), ""), 200),
        "duration": round(ticks / TICKS_PER_SECOND, 3),
        "suffix": _text(source.get("Container") or item.get("Container"), 16).lower(),
        "bitrate": _int(source.get("Bitrate"), 0, 10**9) // 1000,
        "sample_rate": 0,
        "size": _int(source.get("Size")),
        "cover": (album_id or sid) if has_cover else "",
        "rating": 0,
        "starred": bool(user.get("IsFavorite")),
        "rg_track": gain, "rg_album": None, "rg_peak": None,
        "changed": _text(item.get("DateCreated"), 40),
    }


class Server:
    """A signed-in Jellyfin user. Make one with `sign_in`; later, from the kept token and user id."""

    def __init__(self, base, token, user_id, device_id, timeout=20):
        self.base = normalise_base(base)
        self._token = "".join(c for c in (token or "") if c.isalnum())
        self.user_id = _text(user_id, 64)
        self.device_id = _ascii(device_id)
        self.timeout = timeout

    @classmethod
    def sign_in(cls, base, user, password, device_id, timeout=20):
        """Sign in with the user name and password; returns (server, token, user id). The password is sent once,
        to the server only, and not kept."""
        server = cls(base, "", "", device_id, timeout)
        answer = server._request("POST", "/Users/AuthenticateByName", {"Username": user, "Pw": password})
        token = "".join(c for c in _text(answer.get("AccessToken"), 200) if c.isalnum())  # it goes in a header
        user_id = _text((answer.get("User") or {}).get("Id") if isinstance(answer.get("User"), dict) else "", 64)
        if not token or not user_id:
            raise ValueError("That doesn't look like a Jellyfin server")
        server._token, server.user_id = token, user_id
        return server, token, user_id

    def _auth_header(self):
        from .. import __version__

        value = (f'MediaBrowser Client="{CLIENT}", Device="{CLIENT}", DeviceId="{self.device_id}", '
                 f'Version="{_ascii(__version__)}"')
        return value + (f', Token="{self._token}"' if self._token else "")

    def _request(self, method, path, body=None, limit=64 * 1024 * 1024, **params):
        query = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
        url = f"{self.base}{path}" + (f"?{query}" if query else "")
        data = json.dumps(body).encode("utf-8") if body is not None else None
        request = urllib.request.Request(url, data=data, method=method, headers={
            "Authorization": self._auth_header(), "Accept": "application/json",
            **({"Content-Type": "application/json"} if data is not None else {})})
        try:
            with net.urlopen(request, timeout=self.timeout, limit=limit) as resp:
                raw = resp.read()
        except urllib.error.HTTPError as exc:
            if exc.code == 401:
                raise JellyfinError("the user name or password is wrong, or the sign-in was revoked") from exc
            raise
        if not raw.strip():
            return {}
        try:
            answer = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("That doesn't look like a Jellyfin server") from exc
        if not isinstance(answer, dict):
            raise ValueError("That doesn't look like a Jellyfin server")
        return answer

    def ping(self):
        """Check the link and the sign-in: {"version", "type", "server_version"}."""
        info = self._request("GET", "/System/Info")
        return {"version": "", "type": "jellyfin", "server_version": _text(info.get("Version"), 40)}

    def pages(self, page=PAGE, should_stop=lambda: False):
        """Every song as lists of checked songs, a page at a time; stops when a page brings nothing new."""
        start, seen = 0, set()
        while start < MAX_SONGS and not should_stop():
            answer = self._request("GET", f"/Users/{urllib.parse.quote(self.user_id)}/Items", limit=32 * 1024 * 1024,
                                   IncludeItemTypes="Audio", Recursive="true", StartIndex=start, Limit=page,
                                   Fields="MediaSources,DateCreated,Genres,ProductionYear,ParentIndexNumber",
                                   # SortName last: a fixed order, so pages don't skip or repeat songs
                                   SortBy="AlbumArtist,Album,ParentIndexNumber,IndexNumber,SortName",
                                   EnableImageTypes="Primary", EnableUserData="true")
            items = answer.get("Items")
            if not isinstance(items, list) or not items:
                return
            fresh = [s for s in (song_from(i) for i in items[:page]) if s and s["id"] not in seen]
            if not fresh:
                return
            seen.update(s["id"] for s in fresh)
            yield fresh
            if len(items) < page:
                return
            start += len(items)

    def songs(self, page=PAGE):
        for chunk in self.pages(page):
            yield from chunk

    def stream_url(self, song_id):
        """The link a song plays from, as the server stores it (no transcoding)."""
        query = urllib.parse.urlencode({"static": "true", "api_key": self._token, "DeviceId": self.device_id})
        return f"{self.base}/Audio/{urllib.parse.quote(song_id, safe='')}/stream?{query}"

    def cover(self, item_id, size=600):
        from .artfetch import MAX_BYTES

        url = (f"{self.base}/Items/{urllib.parse.quote(item_id, safe='')}/Images/Primary?"
               + urllib.parse.urlencode({"maxWidth": size, "quality": 90, "format": "Jpg"}))
        request = urllib.request.Request(url, headers={"Authorization": self._auth_header()})
        with net.urlopen(request, timeout=self.timeout, limit=MAX_BYTES) as resp:
            data = resp.read()
        return data if data[:3] == b"\xff\xd8\xff" or data[:8] == b"\x89PNG\r\n\x1a\n" else b""

    def scrobble(self, song_id, when_ms=None, submission=True):
        if submission:
            self._request("POST", f"/Users/{urllib.parse.quote(self.user_id)}/PlayedItems/"
                                  f"{urllib.parse.quote(song_id, safe='')}", body={})

    def sign_out(self):
        """Revoke this sign-in on the server (when the server is removed here)."""
        self._request("POST", "/Sessions/Logout", body={})
