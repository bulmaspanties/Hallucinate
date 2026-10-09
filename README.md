# Music Player

A fast, modern desktop music player (PySide6 + QML) with a Spotify-style
search-and-browse experience. Not playlist-driven: type to find, click to play.

## Features
- Scans folders (mutagen tags + embedded/folder cover art) into SQLite with FTS5 instant search; incremental rescans (mtime/size), background scanning, file watching, and removal of moved/deleted paths.
- Formats: FLAC, MP3, OGG/Vorbis, Opus, WAV, AAC/M4A, ALAC, WMA, APE, WavPack, AIFF and more (anything Qt's FFmpeg backend decodes). WAV/AIFF RIFF/FORM text tags are read; missing tags fall back to the filename and unknown values.
- Global search grouped into Artists / Albums / Songs; Home, Albums, Artists, Songs browse views; album and artist pages; editable queue; shuffle/repeat; seek; volume. Queue, current position, shuffle, repeat, and volume are restored after restart; missing queue files are discarded.
- MPRIS2 controls and media keys on Linux.
- Optional Last.fm account linking, now-playing updates, 50%-or-four-minutes
  scrobbling, secure system-keyring credentials, and a persistent offline retry queue.
- Dark, keyboard-friendly UI.

## Install
### Arch Linux
```sh
sudo pacman -S pyside6 python-mutagen python-keyring qt6-multimedia-ffmpeg
git clone <this repo> && cd music-player
cd packaging/arch && makepkg -si      # or run from source (below)
```
### pip (any OS)
```sh
python -m venv .venv && . .venv/bin/activate
pip install -e '.[test]'
```
Note: a distro `pyside6` must match the installed Qt version; if you see
`undefined symbol` import errors, use an isolated venv (no system site packages)
so pip installs the PySide6 wheel.

## Run
```sh
musicplayer                 # uses ~/Music on first run
musicplayer ~/Music /mnt/flac   # add folders
python -m musicplayer ~/Music
```
Folders can also be managed in Settings. Data lives in `~/.local/share/musicplayer`
(override with `MUSICPLAYER_DATA`).

## Last.fm
In Settings, enter the API key and secret for a Last.fm API application (create
one at [last.fm/api/account/create](https://www.last.fm/api/account/create)).
Credentials and the resulting account session are saved only through the system
keyring; the pending scrobble queue contains track metadata only. Connect, open
the authorization page in your browser, and confirm authorization in Settings.
Scrobbles are queued while offline and retried with backoff when connected.
On headless Linux, install and unlock a Secret Service-compatible keyring before
connecting. The app does not fall back to plaintext credential storage.

## Shortcuts
Space play/pause · ←/→ seek · ↑/↓ volume · N/P next/previous · S shuffle · R repeat ·
Q queue · `/`, Ctrl+F or Ctrl+K search · Alt+← back · Ctrl+Q quit.

## Tests
```sh
pytest                      # core tests; the app smoke test runs offscreen
QT_QPA_PLATFORM=offscreen musicplayer ~/Music --quit-after 3000
```
Format and playback tests generate real files through `ffmpeg` (including seeking,
queue transitions and repeat/shuffle). A synthetic APE header tests Mutagen tag
and duration extraction only; it is not valid APE audio. For release qualification,
complete the [manual QA checklist](docs/manual-qa.md) with representative files
from your playback backend and device.

## Limitations
- Track transitions use two pre-rolled Qt players and switch just before the current
  track ends. To avoid backend end-of-stream stalls, the final ~250 ms may be cut
  off rather than waiting for end-of-media. Verify the transition on each target
  Qt/FFmpeg and audio-device combination.
