"""Read metadata and cover art from audio files via mutagen."""
import base64
import hashlib
import os
import re
from typing import Callable, Optional

import mutagen
from mutagen.flac import Picture

AUDIO_EXTS = {
    ".mp3", ".flac", ".ogg", ".oga", ".opus", ".wav", ".wave", ".m4a", ".m4b", ".mp4",
    ".aac", ".alac", ".wma", ".ape", ".wv", ".aiff", ".aif", ".aifc", ".mpc", ".tta",
    ".dsf", ".dff", ".mka", ".spx",
}

COVER_NAMES = ("cover", "folder", "front", "albumart", "album")
COVER_EXTS = (".jpg", ".jpeg", ".png", ".webp")

# Candidate keys per field: ID3, Vorbis/APE, MP4, ASF (WMA)
KEYS = {
    "title": ("TIT2", "title", "Title", "\xa9nam"),
    "artist": ("TPE1", "artist", "Artist", "\xa9ART", "Author"),
    "album_artist": ("TPE2", "albumartist", "album artist", "Album Artist", "aART", "WM/AlbumArtist"),
    "album": ("TALB", "album", "Album", "\xa9alb", "WM/AlbumTitle"),
    "track": ("TRCK", "tracknumber", "Track", "trkn", "WM/TrackNumber"),
    "disc": ("TPOS", "discnumber", "Disc", "disk", "WM/PartOfSet"),
    "year": ("TDRC", "TYER", "date", "year", "Year", "\xa9day", "WM/Year"),
    "genre": ("TCON", "genre", "Genre", "\xa9gen", "WM/Genre"),
}


def _strs(v) -> list:
    if v is None:
        return []
    if hasattr(v, "text"):
        v = v.text
    if not isinstance(v, (list, tuple)) or (isinstance(v, tuple) and v and isinstance(v[0], int)):
        v = [v]
    out = []
    for x in v:
        if isinstance(x, tuple):
            x = "/".join(str(i) for i in x)
        if hasattr(x, "value"):
            x = x.value
        if isinstance(x, bytes):
            x = x.decode("utf-8", "replace")
        out.append(str(x))
    return out


def _get(tags, field: str) -> str:
    if tags is None:
        return ""
    for key in KEYS[field]:
        try:
            s = _strs(tags.get(key))
        except Exception:
            continue
        if s and s[0].strip():
            return s[0].strip()
    return ""


def _num(s: str) -> int:
    m = re.match(r"\s*(\d+)", s or "")
    return int(m.group(1)) if m else 0


def album_key(album_artist: str, album: str, directory: str) -> str:
    base = album_artist.lower() if album_artist else directory
    return hashlib.sha1(f"{base}\x1f{album.lower()}".encode("utf-8", "replace")).hexdigest()[:16]


def _image_ext(data: bytes) -> str:
    return ".png" if data[:8] == b"\x89PNG\r\n\x1a\n" else ".jpg"


def extract_embedded_art(f) -> Optional[bytes]:
    try:
        pics = getattr(f, "pictures", None)
        if pics:
            return bytes(pics[0].data)
        tags = f.tags
        if tags is None:
            return None
        if hasattr(tags, "getall"):
            apic = tags.getall("APIC")
            if apic:
                return bytes(apic[0].data)
        covr = tags.get("covr") if hasattr(tags, "get") else None
        if covr:
            return bytes(covr[0])
        mbp = tags.get("metadata_block_picture") if hasattr(tags, "get") else None
        if mbp:
            return bytes(Picture(base64.b64decode(mbp[0])).data)
    except Exception:
        return None
    return None


def find_folder_art(directory: str) -> Optional[str]:
    try:
        names = {n.lower(): n for n in os.listdir(directory)}
    except OSError:
        return None
    for base in COVER_NAMES:
        for ext in COVER_EXTS:
            if base + ext in names:
                return os.path.join(directory, names[base + ext])
    return None


def read_track(path: str, art_known: Optional[Callable[[str], bool]] = None) -> Optional[dict]:
    """Return a track dict, or None if the file isn't readable audio.

    `_art` holds embedded cover bytes unless `art_known(album_key)` says we
    already have art for that album.
    """
    try:
        f = mutagen.File(path)
    except Exception:
        return None
    if f is None or getattr(f, "info", None) is None:
        return None
    st = os.stat(path)
    tags = f.tags
    directory = os.path.dirname(path)
    stem = os.path.splitext(os.path.basename(path))[0]

    title = _get(tags, "title") or stem
    artist = _get(tags, "artist") or _get(tags, "album_artist") or "Unknown Artist"
    album_artist = _get(tags, "album_artist")
    album = _get(tags, "album")
    key = album_key(album_artist, album, directory)
    info = f.info
    t = {
        "path": path,
        "mtime": st.st_mtime,
        "size": st.st_size,
        "title": title,
        "artist": artist,
        "album_artist": album_artist or artist,
        "aa_tag": 1 if album_artist else 0,
        "album": album or "Unknown Album",
        "album_key": key,
        "track_no": _num(_get(tags, "track")),
        "disc_no": _num(_get(tags, "disc")),
        "year": _num(re.sub(r"^\D*", "", _get(tags, "year"))),
        "genre": _get(tags, "genre"),
        "duration": float(getattr(info, "length", 0) or 0),
        "fmt": os.path.splitext(path)[1].lstrip(".").upper(),
        "bitrate": int(getattr(info, "bitrate", 0) or 0),
        "sample_rate": int(getattr(info, "sample_rate", 0) or 0),
        "art": None,
        "_art": None,
    }
    if art_known is None or not art_known(key):
        t["_art"] = extract_embedded_art(f)
    return t
