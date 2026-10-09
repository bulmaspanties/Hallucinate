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
    "album_artist": ("TPE2", "albumartist", "album_artist", "album artist", "Album Artist", "aART", "WM/AlbumArtist"),
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


def _rg_value(text: str) -> Optional[float]:
    m = re.search(r"[-+]?\d+(?:\.\d+)?", text or "")
    return float(m.group()) if m else None


def _rg_lookup(tags, name: str) -> Optional[float]:
    """ReplayGain value from ID3 TXXX, Vorbis/APE, or MP4 freeform atoms (case-insensitive)."""
    if tags is None:
        return None
    wanted = name.lower()
    try:
        items = list(tags.items()) if hasattr(tags, "items") else []
    except Exception:
        return None
    for key, value in items:
        k = str(key).lower()
        if k == wanted or k == "txxx:" + wanted or k.endswith(":" + wanted):
            strs = _strs(value)
            if strs:
                v = _rg_value(strs[0])
                if v is not None:
                    return v
    return None


def read_replaygain(tags) -> tuple:
    """(track gain dB, album gain dB, track peak) relative to the ReplayGain 2.0 -18 LUFS reference."""
    track = _rg_lookup(tags, "replaygain_track_gain")
    album = _rg_lookup(tags, "replaygain_album_gain")
    peak = _rg_lookup(tags, "replaygain_track_peak")
    if track is None and album is None:
        # Opus stores Q7.8 gain relative to -23 LUFS; convert to the -18 LUFS reference.
        r128_t, r128_a = _rg_lookup(tags, "r128_track_gain"), _rg_lookup(tags, "r128_album_gain")
        track = r128_t / 256 + 5 if r128_t is not None else None
        album = r128_a / 256 + 5 if r128_a is not None else None
    return track, album, peak


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


_RIFF_INFO = {b"INAM": "title", b"IART": "artist", b"IPRD": "album", b"ITRK": "track",
              b"ICRD": "year", b"IGNR": "genre", b"IPRT": "track"}
_AIFF_TEXT = {b"NAME": "title", b"AUTH": "artist"}


def _chunk_text(raw: bytes) -> str:
    return raw.split(b"\0", 1)[0].decode("utf-8", "replace").strip()


def _plain_tags(path: str, ext: str) -> dict:
    """Fallback tags for RIFF INFO (WAV) and AIFF text chunks, which mutagen ignores."""
    import struct

    out = {}
    try:
        with open(path, "rb") as fh:
            head = fh.read(12)
            if len(head) < 12:
                return out
            big = head[:4] == b"FORM"
            if head[:4] not in (b"RIFF", b"FORM"):
                return out
            end = min(8 + struct.unpack(">I" if big else "<I", head[4:8])[0], os.fstat(fh.fileno()).st_size)
            while fh.tell() + 8 <= end:
                cid, size = struct.unpack("4sI", fh.read(8)) if not big else (
                    fh.read(4), struct.unpack(">I", fh.read(4))[0])
                body = fh.tell()
                if big and cid in _AIFF_TEXT:
                    out[_AIFF_TEXT[cid]] = _chunk_text(fh.read(min(size, 4096)))
                elif not big and cid == b"LIST":
                    if fh.read(4) == b"INFO":
                        stop = body + size
                        while fh.tell() + 8 <= stop:
                            sid, ssz = struct.unpack("<4sI", fh.read(8))
                            data = fh.read(min(ssz, 4096))
                            if ssz > 4096:
                                fh.seek(ssz - 4096, 1)
                            if sid in _RIFF_INFO and data:
                                out.setdefault(_RIFF_INFO[sid], _chunk_text(data))
                            if ssz & 1:
                                fh.seek(1, 1)
                fh.seek(body + size + (size & 1))
    except (OSError, struct.error):
        pass
    return {k: v for k, v in out.items() if v}


def read_track(path: str, art_known: Optional[Callable[[str], bool]] = None) -> Optional[dict]:
    """Return a track dict, or None if the file isn't readable audio.

    `_art` holds embedded cover bytes unless `art_known(album_key)` says we
    already have art for that album.
    """
    try:
        return _read_track(path, art_known)
    except Exception:
        return None  # corrupt or unsupported file; never let it break a scan


def is_readable_audio(path: str) -> bool:
    """Cheap header/info check used just before starting a track."""
    try:
        f = mutagen.File(path)
        return f is not None and getattr(f, "info", None) is not None
    except Exception:
        return False


def audio_codec(f, ext: str) -> str:
    """Identify the encoded audio stream where Mutagen exposes it; otherwise use a format label."""
    info = getattr(f, "info", None)
    codec = str(getattr(info, "codec", "") or "").lower()
    if codec == "alac":
        return "ALAC"
    if codec.startswith("mp4a."):
        return "AAC"
    module = type(f).__module__.rsplit(".", 1)[-1].lower()
    return {
        "mp3": "MP3",
        "flac": "FLAC",
        "oggflac": "FLAC",
        "oggopus": "OPUS",
        "oggvorbis": "VORBIS",
        "wave": "WAV",
        "aiff": "AIFF",
        "asf": "WMA",
        "wavpack": "WAVPACK",
        "monkeysaudio": "APE",
        "tta": "TTA",
        "mpc": "MPC",
        "dsf": "DSD",
        "dff": "DSD",
    }.get(module, ext.lstrip(".").upper())


def _open(path: str):
    try:
        return mutagen.File(path)
    except Exception:
        pass
    if path.lower().endswith((".mp3", ".mp2")):
        # Damaged ID3 header: the audio frames may still be fine.
        from mutagen.mp3 import MP3
        try:
            f = MP3(path, ID3=lambda *a, **k: (_ for _ in ()).throw(Exception()))
        except Exception:
            f = None
        if f is not None:
            return f
    return None


def _read_track(path, art_known):
    f = _open(path)
    if f is None or getattr(f, "info", None) is None:
        return None
    st = os.stat(path)
    if st.st_size == 0:
        return None
    tags = f.tags
    ext = os.path.splitext(path)[1].lower()
    extra = _plain_tags(path, ext) if ext in (".wav", ".wave", ".aif", ".aiff", ".aifc") and not tags else {}
    directory = os.path.dirname(path)
    stem = os.path.splitext(os.path.basename(path))[0]

    title = _get(tags, "title") or extra.get("title") or stem
    artist = _get(tags, "artist") or extra.get("artist") or _get(tags, "album_artist") or "Unknown Artist"
    album_artist = _get(tags, "album_artist")
    album = _get(tags, "album") or extra.get("album", "")
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
        "track_no": _num(_get(tags, "track") or extra.get("track", "")),
        "disc_no": _num(_get(tags, "disc")),
        "year": _num(re.sub(r"^\D*", "", _get(tags, "year") or extra.get("year", ""))),
        "genre": _get(tags, "genre") or extra.get("genre", ""),
        "duration": float(getattr(info, "length", 0) or 0),
        "fmt": os.path.splitext(path)[1].lstrip(".").upper(),
        "codec": audio_codec(f, ext),
        "bitrate": int(getattr(info, "bitrate", 0) or 0) or (
            int(st.st_size * 8 / info.length) if getattr(info, "length", 0) else 0),
        "sample_rate": int(getattr(info, "sample_rate", 0) or 0) or (48000 if ext == ".opus" else 0),
        "art": None,
        "_art": None,
    }
    t["rg_track"], t["rg_album"], t["rg_peak"] = read_replaygain(tags)
    if art_known is None or not art_known(key):
        t["_art"] = extract_embedded_art(f)
    return t
