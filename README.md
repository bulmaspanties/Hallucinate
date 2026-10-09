# Music Player

A fast, modern desktop music player (PySide6 + QML) with a Spotify-style
search-and-browse experience. Not playlist-driven: type to find, click to play.

## Features
- Scans folders (mutagen tags + embedded/folder cover art) into SQLite with FTS5 instant search; incremental rescans (mtime/size), background scanning, file watching.
- Formats: FLAC, MP3, OGG/Vorbis, Opus, WAV, AAC/M4A, ALAC, WMA, APE, WavPack, AIFF and more (anything Qt's FFmpeg backend decodes).
- Global search grouped into Artists / Albums / Songs; Home, Albums, Artists, Songs browse views; album and artist pages; queue panel; shuffle/repeat; seek; volume.
- MPRIS2 (media keys, desktop widgets) on Linux.
- Dark, keyboard-friendly UI.

## Install
### Arch Linux
```sh
sudo pacman -S pyside6 python-mutagen qt6-multimedia-ffmpeg
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

## Shortcuts
Space play/pause · ←/→ seek · ↑/↓ volume · N/P next/previous · S shuffle · R repeat ·
Q queue · `/`, Ctrl+F or Ctrl+K search · Alt+← back · Ctrl+Q quit.

## Tests
```sh
pytest                      # core tests; the app smoke test runs offscreen
QT_QPA_PLATFORM=offscreen musicplayer ~/Music --quit-after 3000
```

## Limitations
- Gapless playback is not implemented (single QMediaPlayer; small gaps between tracks).
- MPRIS is lightly tested.
