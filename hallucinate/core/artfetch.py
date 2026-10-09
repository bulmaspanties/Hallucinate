"""Find missing cover art on MusicBrainz / Cover Art Archive."""
import json
import urllib.error
import urllib.parse
import urllib.request

from .lyrics import USER_AGENT

MAX_BYTES = 8_000_000


def _get(url, timeout=10):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "*/*"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - fixed https endpoints
        return resp.read(MAX_BYTES)


def _quote(s):
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def find_release_ids(artist, album, limit=5):
    query = f"release:{_quote(album)}"
    if artist and artist.lower() not in ("unknown artist", "various artists"):
        query += f" AND artist:{_quote(artist)}"
    url = "https://musicbrainz.org/ws/2/release/?" + urllib.parse.urlencode(
        {"query": query, "fmt": "json", "limit": limit})
    data = json.loads(_get(url))
    return [r["id"] for r in data.get("releases", []) if r.get("id")]


def fetch_cover(artist, album):
    """Image bytes of the best matching front cover, or None. Raises OSError on network trouble."""
    try:
        for mbid in find_release_ids(artist, album):
            try:
                data = _get(f"https://coverartarchive.org/release/{mbid}/front-500")
            except urllib.error.HTTPError as exc:
                if exc.code in (404, 400):
                    continue
                raise
            if data[:8] == b"\x89PNG\r\n\x1a\n" or data[:3] == b"\xff\xd8\xff":
                return data
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        raise OSError(str(exc)) from exc
    return None
