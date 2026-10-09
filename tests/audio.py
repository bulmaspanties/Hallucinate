"""Helpers that synthesise real audio files in many formats with ffmpeg."""
import shutil
import struct
import subprocess

FFMPEG = shutil.which("ffmpeg")

# extension -> extra ffmpeg args
FORMATS = {
    "flac": [],
    "mp3": ["-c:a", "libmp3lame"],
    "ogg": ["-c:a", "libvorbis"],
    "opus": ["-c:a", "libopus", "-ar", "48000"],
    "m4a": ["-c:a", "aac"],
    "alac.m4a": ["-c:a", "alac"],
    "wav": [],
    "wma": ["-c:a", "wmav2"],
    "wv": ["-c:a", "wavpack"],
    "aiff": [],
}


def encode(path, ext, seconds=3.0, **meta):
    """Create `path` as `ext` (a key of FORMATS) with a sine tone and tags."""
    args = [FFMPEG, "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}",
            "-ac", "2"]
    if "-ar" not in FORMATS[ext]:
        args += ["-ar", "44100"]
    for k, v in meta.items():
        args += ["-metadata", f"{k}={v}"]
    args += FORMATS[ext] + [str(path)]
    subprocess.run(args, check=True)
    return path


def make_ape(path, title="Ape Song", artist="Ape Artist", album="Ape Album", seconds=2):
    """A minimal Monkey's Audio header (version 3.99) plus an APEv2 tag.

    There's no APE encoder available, so this isn't decodable audio, but it is
    enough for the tag/duration reader, which is what the library needs.
    """
    rate = 44100
    blocks_per_frame = 73728
    total_blocks = rate * seconds
    frames = -(-total_blocks // blocks_per_frame)
    final = total_blocks - (frames - 1) * blocks_per_frame
    header = bytearray(b"MAC " + struct.pack("<H", 3990) + b"\0" * 50)
    header += struct.pack("<IIIHHI", blocks_per_frame, final, frames, 16, 2, rate)
    items = {"Title": title, "Artist": artist, "Album": album}
    body = b""
    for k, v in items.items():
        data = v.encode()
        body += struct.pack("<II", len(data), 0) + k.encode() + b"\0" + data
    footer_fields = struct.pack("<IIII", 2000, 32 + len(body), len(items), 0x80000000 | (1 << 29))
    footer = b"APETAGEX" + footer_fields + b"\0" * 8
    with open(path, "wb") as f:
        f.write(bytes(header) + b"\0" * 2000 + body + footer)
    return path
