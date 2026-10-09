# Manual QA checklist

Use representative files from a library you are permitted to test. Record the
OS, Qt/PySide6 version, FFmpeg backend version, audio device, sample filename,
and result for each run. For codec checks, verify both imported metadata and
actual audible playback in this app; successful scanning alone is not proof a
codec decodes.

## Formats, tags, and playback

- [ ] FLAC: tagged file, cover art, play, pause, seek forward/backward, next.
- [ ] MP3: ID3v2 tags/art, VBR file, playback and seeking.
- [ ] OGG/Vorbis: tags/art, playback and seeking.
- [ ] Opus: tags/art, playback and seeking.
- [ ] M4A/AAC: tags/art, playback and seeking.
- [ ] M4A/ALAC: lossless playback and seeking.
- [ ] WAV: RIFF INFO tags, ID3-tagged WAV, untagged filename fallback, seeking.
- [ ] APE: real APE audio file, APEv2 tags, playback and seeking. Automated tests
  currently exercise APE metadata using a synthetic header only, not a decoder.
- [ ] WMA: tags, playback and seeking.
- [ ] WavPack and AIFF: playback, seeking, and tag fallback.
- [ ] Missing tags, Unicode tags/paths, multi-disc/track numbers, and embedded art.
- [ ] Zero-byte, truncated, malformed-tag, and random-byte files: scans complete,
  invalid files are counted/ignored, and valid neighboring files remain usable.
- [ ] Seek to start, middle, and near end; pause/resume after each seek.
- [ ] Change volume repeatedly; verify it persists after restart.
- [ ] Play a queue through multiple transitions, including short tracks; listen for
  cut-off or silence at transitions. The transition is intentionally initiated
  about 250 ms before end to avoid Qt FFmpeg end-of-stream stalls.
- [ ] Verify repeat off stops, repeat all wraps, repeat one repeats, and shuffle
  visits every queued item before starting a new cycle.
- [ ] Add next, enqueue, reorder, remove current/other items, clear queue, then
  play again. Remove a file during playback and verify the UI reports/skips it.
- [ ] Restart the app with a non-empty queue; verify queue, current track, position,
  shuffle, and repeat restore paused. Delete a queued file before restart and
  verify it is dropped without losing the remaining queue.

## Library and search

- [ ] Add one folder, scan it, then rescan unchanged: no duplicate tracks or
  unnecessary metadata updates.
- [ ] Modify a tag and file size/mtime; verify metadata/search updates.
- [ ] Rename and move a track within the watched root; verify old path is removed
  and new path appears.
- [ ] Delete a track and a whole subfolder; verify stale search and browse results
  disappear. Disconnect/move the entire root and verify the library is retained
  until the root is available or explicitly removed.
- [ ] Add/remove a folder in Settings; verify its contents and counts update.
- [ ] Search mixed case, diacritics, non-Latin text, punctuation, slash-containing
  artist names, and multi-token artist/album/title queries.
- [ ] Run against a 50,000+ track library; search, browse, open an album, and
  compare first display latency to the automated query thresholds in
  `tests/test_library_robust.py`.
- [ ] Restart with the large library; verify startup does not reparse unchanged files.

## Linux desktop integration

- [ ] In a graphical Arch-based desktop session, verify `org.mpris.MediaPlayer2`
  appears on D-Bus with correct metadata, playback state, position, repeat, shuffle,
  and volume.
- [ ] Test desktop media-key Play/Pause, Next, Previous, and Stop while the player
  is focused and unfocused; confirm competing players do not consume the keys.
- [ ] Test MPRIS calls from a desktop widget or `playerctl`, including seeking and
  changing repeat/shuffle.
- [ ] Confirm the desktop entry launches the installed app and the icon resolves.
- [ ] Test the installed Arch package on a clean machine/container and verify the
  Qt FFmpeg plugin and codecs are present.

## Automated coverage

The automated suite covers real FFmpeg-generated FLAC, MP3, Vorbis, Opus, AAC,
ALAC, WAV, WMA, WavPack, and AIFF playback/seek files, common tag/fallback/corrupt
inputs, player queue/session behavior, a D-Bus MPRIS session, and 50,000-row
database query performance. It does not replace testing actual device media keys,
all user-supplied codec variants, or real APE decoding on the target system.
