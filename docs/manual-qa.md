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
  cut-off or silence at transitions. Play a gapless album (a live album or DJ mix, in
  FLAC and in MP3) and listen for clicks, gaps or doubled audio at each join. Each track
  should play to its end; the next starts ~20 ms early (`HANDOFF_LEAD_MS`) to cover
  its startup on the audio device.
- [ ] Verify repeat off stops, repeat all wraps, repeat one repeats, and shuffle
  visits every queued item before starting a new cycle.
- [ ] Add next, enqueue, reorder, remove current/other items, clear queue, then
  play again. Remove a file during playback and verify the UI reports/skips it.
- [ ] Settings → Playback → Output device: switch between two devices (e.g. speakers and a
  USB DAC or headset) during playback, with the equalizer off and on; audio moves without
  a restart. Unplug the chosen device: playback continues on the default and the picker
  shows it as "not connected"; plug it back in and audio returns to it. Restart and
  verify the choice is kept.
- [ ] Radio: turn on the radio button, play a single song, and verify about ten similar
  songs are appended before it ends and that playback continues without a gap. Let it
  run through a few batches; check that artists vary and that recently heard songs are
  not repeated. Turn repeat on and verify nothing more is added.
- [ ] Smart playlists: create "Liked is yes" + "Last played not in the last 60 days";
  like and play songs and verify the list updates without reopening it. Edit the
  rules (field, operator, between, limit, sort) and check the preview count. Play
  it with radio on and verify added songs still match the rules. Delete it.
- [ ] Drag a folder from the file manager onto the window: it plays in album order.
  Drag files onto the queue panel: they are appended. Drop a file outside the library.
- [ ] Queue panel → Save: the new playlist opens with the queue's tracks in order.
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

## Last.fm integration

- [ ] Enter API credentials in Settings, restart, and verify they remain available
  without appearing in application config files or logs.
- [ ] Connect through the browser authorization flow; verify the username and
  connected state appear, then disconnect and reconnect.
- [ ] Start, pause, resume, seek, and switch tracks; verify now-playing updates
  only for the active track and seeking/paused time does not count toward a
  scrobble.
- [ ] Verify a short track scrobbles after half its duration and a long track
  after four minutes of actual listening; verify each track is submitted once.
- [ ] Disconnect networking during playback; verify a threshold-qualified
  scrobble persists across restart and is retried after network access returns.
- [ ] Disconnect the Last.fm account with queued scrobbles; verify the queue is
  retained and delivered after reconnecting.
- [ ] Test with an unavailable system keyring; verify the UI reports the failure
  and credentials/session keys are never written as plaintext.

## Themes

- [ ] Switch through all built-in themes; verify text, disabled controls, hover,
  selection, error, and accent contrast remain readable in both light and dark
  palettes.
- [ ] Change theme while browsing and while playback is active; verify the
  player, queue, dialogs, sliders, and Settings update immediately.
- [ ] Enable album-art accent mode, switch between albums with different covers,
  then play a track without artwork; verify the accent follows the cover and
  falls back to the selected theme when no art is available.
- [ ] Add a valid custom theme JSON under the displayed user theme directory,
  select **Reload themes**, and verify its colors, radius, family, and font scale
  apply live and persist after restart.
- [ ] Add malformed or incomplete theme JSON, reload, and verify the app logs
  the skipped file while the other themes remain selectable.

## Packages

- [ ] Flatpak: play MP3, AAC/M4A, FLAC and Opus files (codecs come from the runtime); add a folder outside
  `~/Music` through the folder picker; connect Last.fm or ListenBrainz with the desktop keyring; check that
  media keys, notifications and Discord Rich Presence (native and Flatpak Discord) work; the window and
  MPRIS controls show the Hallucinate icon.
- [ ] AUR: install `hallucinate` and `hallucinate-git` on a clean Arch system with `makepkg -si`; launch from
  the application menu and check playback.

## Automated coverage

The automated suite covers real FFmpeg-generated FLAC, MP3, Vorbis, Opus, AAC,
ALAC, WAV, WMA, WavPack, and AIFF playback/seek files, common tag/fallback/corrupt
inputs, player queue/session behavior, a D-Bus MPRIS session, and 50,000-row
database query performance, plus mocked Last.fm signing, authorization, listen
thresholds, and offline queue/retry behavior. Theme tests cover built-in/custom
theme loading, persistence, album-art accent selection, and live QML color/font
updates. It does not replace testing actual device media keys, live Last.fm
authorization, all user-supplied codec variants, or real APE decoding on the
target system.

## Desktop integration (0.2.0)
- [ ] Tray icon appears (KDE/GNOME with AppIndicator extension/Windows); left-click toggles the window, middle-click toggles playback, menu actions work.
- [ ] Settings → Desktop: disabling the tray makes closing the window quit; "keep playing in the tray" hides the window instead.
- [ ] `Ctrl+M` opens the mini player (main window hides); Esc / expand button restores it; closing the mini window restores the main window.
- [ ] Tab moves keyboard focus through sidebar, transport buttons, rows and album cards with a visible ring; Enter/Space activates.
- [ ] Orca (Linux) / Narrator (Windows) announce button names (Play, Next, Queue, Lyrics…).
- [ ] HiDPI: at 150%/200% scaling covers and text are sharp and nothing clips (also `QT_SCALE_FACTOR=2`).
