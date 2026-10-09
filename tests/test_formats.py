import shutil

import pytest
from audio import FFMPEG, FORMATS, encode, make_ape

from musicplayer.core.tags import read_track

needs_ffmpeg = pytest.mark.skipif(not FFMPEG, reason="ffmpeg not installed")

META = dict(title="Tïtle ♪ 日本語", artist="Ärtist", album="Albüm", album_artist="AA", track="3/9",
            date="2019", genre="Rock")
FULL_TAGS = {"opus", "flac", "mp3", "ogg", "m4a", "alac.m4a", "wma", "wv"}


@needs_ffmpeg
@pytest.mark.parametrize("ext", sorted(FORMATS))
def test_reads_every_format(tmp_path, ext):
    p = encode(tmp_path / ("song." + ext.split(".")[-1]), ext, **META)
    t = read_track(str(p))
    assert t is not None, ext
    assert 2.8 < t["duration"] < 3.3
    assert t["sample_rate"] in (44100, 48000)
    assert t["bitrate"] > 0
    if ext in FULL_TAGS:
        assert (t["title"], t["artist"], t["album"], t["album_artist"]) == (
            "Tïtle ♪ 日本語", "Ärtist", "Albüm", "AA")
        assert (t["track_no"], t["year"], t["genre"]) == (3, 2019, "Rock")
    elif ext in ("wav", "aiff"):
        assert t["title"] == "Tïtle ♪ 日本語"  # RIFF INFO / AIFF NAME chunk


@needs_ffmpeg
def test_opus_tags(tmp_path):
    t = read_track(str(encode(tmp_path / "a.opus", "opus", **META)))
    assert t["title"] == "Tïtle ♪ 日本語" and t["album"] == "Albüm"


def test_ape(tmp_path):
    t = read_track(str(make_ape(tmp_path / "a.ape")))
    assert t and t["title"] == "Ape Song" and t["artist"] == "Ape Artist"
    assert 1.9 < t["duration"] < 2.1


@needs_ffmpeg
def test_missing_tags_fall_back_to_filename(tmp_path):
    p = encode(tmp_path / "My Song.flac", "flac")
    t = read_track(str(p))
    assert t["title"] == "My Song"
    assert t["artist"] == "Unknown Artist" and t["album"] == "Unknown Album"
    assert t["track_no"] == 0 and t["year"] == 0


@needs_ffmpeg
@pytest.mark.parametrize("val,expected", [("2019-05-06", 2019), ("May 2001", 2001), ("", 0), ("abcd", 0)])
def test_year_variants(tmp_path, val, expected):
    p = encode(tmp_path / "a.flac", "flac", **({"date": val} if val else {}))
    assert read_track(str(p))["year"] == expected


@needs_ffmpeg
@pytest.mark.parametrize("ext", ["flac", "mp3", "ogg", "m4a", "wav"])
def test_truncated_file_never_crashes(tmp_path, ext):
    p = encode(tmp_path / f"a.{ext}", ext, **META)
    data = p.read_bytes()
    for cut in (0, 1, 10, len(data) // 3):
        p.write_bytes(data[:cut])
        read_track(str(p))  # may return a track or None, but must not raise


def test_garbage_and_wrong_extension(tmp_path):
    for name, data in [("a.mp3", b"\0" * 5000), ("b.flac", b"fLaC" + b"\xff" * 100), ("c.ogg", b"OggS" * 50),
                       ("d.m4a", b"\0\0\0\x18ftypM4A " + b"\xff" * 40), ("e.wav", b"RIFF\xff\xff\xff\xffWAVE"),
                       ("f.wma", b"\x30\x26\xb2\x75" + b"\0" * 200), ("g.mp3", b"ID3\x04\0\0\x7f\x7f\x7f\x7f" + b"x" * 50)]:
        p = tmp_path / name
        p.write_bytes(data)
        assert read_track(str(p)) is None


@needs_ffmpeg
def test_flac_named_mp3_still_reads(tmp_path):
    p = encode(tmp_path / "real.flac", "flac", title="Hello")
    q = tmp_path / "misnamed.mp3"
    shutil.copy(p, q)
    t = read_track(str(q))
    assert t is None


@needs_ffmpeg
def test_corrupt_id3_header_keeps_audio(tmp_path):
    p = encode(tmp_path / "a.mp3", "mp3", title="T")
    data = p.read_bytes()
    p.write_bytes(b"ID3\x04\x00\x00\x00\x00\x00\x05garbage" + data)
    t = read_track(str(p))
    assert t and t["duration"] > 0


@needs_ffmpeg
def test_embedded_art_in_flac_and_m4a(tmp_path):
    import subprocess
    png = tmp_path / "c.png"
    subprocess.run([FFMPEG, "-y", "-loglevel", "error", "-f", "lavfi", "-i", "color=red:s=16x16",
                    "-frames:v", "1", str(png)], check=True)
    for ext in ("flac", "m4a", "mp3"):
        out = tmp_path / f"art.{ext}"
        subprocess.run([FFMPEG, "-y", "-loglevel", "error", "-f", "lavfi", "-i", "sine=duration=1", "-i", str(png),
                        "-map", "0", "-map", "1", "-c:v", "png" if ext != "mp3" else "mjpeg", "-disposition:v", "attached_pic",
                        *(["-c:a", "aac"] if ext == "m4a" else (["-c:a", "libmp3lame"] if ext == "mp3" else [])),
                        str(out)], check=True)
        t = read_track(str(out))
        assert t and t["_art"], ext
