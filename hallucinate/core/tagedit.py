"""Write tags and cover art back to audio files (FLAC, MP3, Ogg/Opus, M4A, WAV/AIFF, APE/WMA)."""
import base64
import os

import mutagen
from mutagen import id3
from mutagen.flac import FLAC, Picture
from mutagen.mp4 import MP4, MP4Cover

FIELDS = ("title", "artist", "album_artist", "album", "track_no", "disc_no", "year", "genre")

_ID3 = {
    "title": id3.TIT2, "artist": id3.TPE1, "album_artist": id3.TPE2, "album": id3.TALB,
    "track_no": id3.TRCK, "disc_no": id3.TPOS, "year": id3.TDRC, "genre": id3.TCON,
}
_VORBIS = {
    "title": "title", "artist": "artist", "album_artist": "albumartist", "album": "album",
    "track_no": "tracknumber", "disc_no": "discnumber", "year": "date", "genre": "genre",
}
_MP4 = {
    "title": "\xa9nam", "artist": "\xa9ART", "album_artist": "aART", "album": "\xa9alb",
    "year": "\xa9day", "genre": "\xa9gen",
}
_APE = {
    "title": "Title", "artist": "Artist", "album_artist": "Album Artist", "album": "Album",
    "track_no": "Track", "disc_no": "Disc", "year": "Year", "genre": "Genre",
}
_ASF = {
    "title": "Title", "artist": "Author", "album_artist": "WM/AlbumArtist", "album": "WM/AlbumTitle",
    "track_no": "WM/TrackNumber", "disc_no": "WM/PartOfSet", "year": "WM/Year", "genre": "WM/Genre",
}


class TagWriteError(Exception):
    pass


def _clean(fields):
    out = {}
    for k in FIELDS:
        if k in fields and fields[k] is not None:
            v = str(fields[k]).strip()
            out[k] = "" if v == "0" and k in ("track_no", "disc_no", "year") else v
    return out


def _writable(path):
    if not os.path.isfile(path):
        raise TagWriteError("File not found")
    if not os.access(path, os.W_OK):
        raise TagWriteError("File is read-only")


def _open(path):
    try:
        f = mutagen.File(path)
    except Exception as exc:  # noqa: BLE001
        raise TagWriteError(f"Cannot read file: {exc}") from exc
    if f is None:
        raise TagWriteError("Unsupported file type")
    return f


def _kind(f):
    name = type(f).__name__
    if isinstance(f, (FLAC,)) or name in ("OggVorbis", "OggOpus", "OggFlac", "OggSpeex", "OggTheora"):
        return "vorbis"
    if isinstance(f, MP4):
        return "mp4"
    if name in ("MP3", "MP2", "WAVE", "AIFF", "TrueAudio", "DSF", "DSDIFF") or isinstance(f.tags, id3.ID3):
        return "id3"
    if name == "ASF":
        return "asf"
    if name in ("APEv2File", "WavPack", "Musepack", "MonkeysAudio", "OptimFROG"):
        return "ape"
    return None


def write_tags(path, fields):
    """Write the given fields ("" removes a tag). Raises TagWriteError."""
    fields = _clean(fields)
    _writable(path)
    f = _open(path)
    kind = _kind(f)
    if kind is None:
        raise TagWriteError(f"Tag writing is not supported for {type(f).__name__}")
    try:
        if f.tags is None:
            f.add_tags()
    except Exception:  # noqa: BLE001 - APE and friends create tags on save
        pass
    try:
        {"id3": _w_id3, "vorbis": _w_vorbis, "mp4": _w_mp4, "asf": _w_asf, "ape": _w_ape}[kind](f, fields)
        f.save()
    except TagWriteError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise TagWriteError(f"Could not write tags: {exc}") from exc


def _w_id3(f, fields):
    for k, v in fields.items():
        frame = _ID3[k]
        f.tags.delall(frame.__name__)
        if v:
            f.tags.add(frame(encoding=3, text=[v]))


def _w_vorbis(f, fields):
    for k, v in fields.items():
        key = _VORBIS[k]
        if v:
            f.tags[key] = [v]
        elif key in f.tags:
            del f.tags[key]


def _w_mp4(f, fields):
    tags = f.tags
    for k, v in fields.items():
        if k in ("track_no", "disc_no"):
            key = "trkn" if k == "track_no" else "disk"
            n = int(v.split("/")[0]) if v.split("/")[0].isdigit() else 0
            total = tags.get(key, [(0, 0)])[0][1] if tags.get(key) else 0
            if n:
                tags[key] = [(n, total)]
            else:
                tags.pop(key, None)
        elif v:
            tags[_MP4[k]] = [v]
        else:
            tags.pop(_MP4[k], None)


def _w_asf(f, fields):
    for k, v in fields.items():
        if v:
            f.tags[_ASF[k]] = [v]
        else:
            f.tags.pop(_ASF[k], None)


def _w_ape(f, fields):
    for k, v in fields.items():
        if v:
            f.tags[_APE[k]] = v
        elif _APE[k] in f.tags:
            del f.tags[_APE[k]]


def _mime(data):
    return "image/png" if data[:8] == b"\x89PNG\r\n\x1a\n" else "image/jpeg"


def embed_cover(path, data):
    """Replace the front cover embedded in the file."""
    _writable(path)
    f = _open(path)
    kind = _kind(f)
    mime = _mime(data)
    try:
        if kind == "id3":
            if f.tags is None:
                f.add_tags()
            f.tags.delall("APIC")
            f.tags.add(id3.APIC(encoding=3, mime=mime, type=3, desc="Cover", data=data))
        elif isinstance(f, FLAC):
            pic = Picture()
            pic.type, pic.mime, pic.data = 3, mime, data
            f.clear_pictures()
            f.add_picture(pic)
        elif kind == "vorbis":
            pic = Picture()
            pic.type, pic.mime, pic.data = 3, mime, data
            f["metadata_block_picture"] = [base64.b64encode(pic.write()).decode("ascii")]
        elif kind == "mp4":
            fmt = MP4Cover.FORMAT_PNG if mime == "image/png" else MP4Cover.FORMAT_JPEG
            f.tags["covr"] = [MP4Cover(data, imageformat=fmt)]
        else:
            raise TagWriteError(f"Embedding cover art is not supported for {type(f).__name__}")
        f.save()
    except TagWriteError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise TagWriteError(f"Could not embed cover: {exc}") from exc
