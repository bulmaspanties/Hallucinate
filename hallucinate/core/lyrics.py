"""Lyrics: embedded tags, sidecar .lrc files, LRCLIB lookup, and LRC parsing."""
import bisect
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request

import mutagen

USER_AGENT = "hallucinate (https://github.com/bulmaspanties/Hallucinate)"
_TS = re.compile(r"\[(\d{1,3}):(\d{1,2})(?:[.:](\d{1,3}))?\]")


def parse_lrc(text):
    """Parse LRC text into [(milliseconds, line)] sorted by time. Returns [] when there are no timestamps."""
    out = []
    for raw in (text or "").splitlines():
        stamps = list(_TS.finditer(raw))
        if not stamps:
            continue
        line = raw[stamps[-1].end():].strip()
        for m in stamps:
            frac = (m.group(3) or "0").ljust(3, "0")[:3]
            out.append((int(m.group(1)) * 60_000 + int(m.group(2)) * 1000 + int(frac), line))
    out.sort(key=lambda x: x[0])
    return out


def line_at(times, position_ms):
    """Index of the line being sung at position_ms (-1 before the first line)."""
    return bisect.bisect_right(times, position_ms + 150) - 1


def is_synced(text):
    return bool(parse_lrc(text))


def strip_timestamps(text):
    return "\n".join(_TS.sub("", ln).strip() for ln in (text or "").splitlines()).strip()


def _first(v):
    if v is None:
        return ""
    if hasattr(v, "text"):
        v = v.text
    if isinstance(v, (list, tuple)):
        v = v[0] if v else ""
    if isinstance(v, bytes):
        v = v.decode("utf-8", "replace")
    return str(v)


def read_embedded(path):
    """Lyrics text from tags (USLT, LYRICS, \xa9lyr) or a sidecar .lrc/.txt file; "" if none."""
    stem = os.path.splitext(path)[0]
    for ext in (".lrc", ".LRC", ".txt"):
        side = stem + ext
        if os.path.isfile(side):
            try:
                with open(side, "rb") as fh:
                    data = fh.read(512_000)
                for enc in ("utf-8-sig", "utf-16", "latin-1"):
                    try:
                        text = data.decode(enc)
                        if text.strip():
                            return text
                        break
                    except UnicodeError:
                        continue
            except OSError:
                pass
    try:
        f = mutagen.File(path)
    except Exception:  # noqa: BLE001
        return ""
    tags = getattr(f, "tags", None)
    if not tags:
        return ""
    try:
        if hasattr(tags, "getall"):
            for frame in tags.getall("USLT"):
                if _first(frame).strip():
                    return _first(frame)
            for frame in tags.getall("SYLT"):
                items = getattr(frame, "text", [])
                if items:
                    return "\n".join(f"[{ms // 60000:02d}:{ms % 60000 / 1000:05.2f}]{t.strip()}" for t, ms in items)
        for key in ("lyrics", "LYRICS", "unsyncedlyrics", "UNSYNCEDLYRICS", "\xa9lyr", "WM/Lyrics", "Lyrics"):
            if key in tags and _first(tags[key]).strip():
                return _first(tags[key])
    except Exception:  # noqa: BLE001
        return ""
    return ""


def fetch_lrclib(artist, title, album="", duration=0, timeout=8):
    """(synced, plain) from LRCLIB, or None when nothing is found. Raises OSError on network trouble."""
    params = {"artist_name": artist, "track_name": title}
    if album:
        params["album_name"] = album
    if duration:
        params["duration"] = str(int(round(duration)))
    url = "https://lrclib.net/api/get?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - fixed https endpoint
            data = json.load(resp)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise OSError(f"LRCLIB error {exc.code}") from exc
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        raise OSError(str(exc)) from exc
    synced, plain = data.get("syncedLyrics") or "", data.get("plainLyrics") or ""
    return (synced, plain) if (synced or plain) else None
