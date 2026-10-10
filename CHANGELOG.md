# Changelog

All notable changes to this project are documented here. Format based on
[Keep a Changelog](https://keepachangelog.com/).

## [Unreleased]

### Added
- Smart playlists: live rule-based playlists (title, artist, album, album artist, genre, format, path, year, length, bitrate, play count, date added, last played, liked; match all/any; sort; limit), listed under Playlists and re-evaluated as the library, likes and plays change. The rule editor previews the description and the number of matching songs. Rules are validated and compiled to parameterized SQL.
- Radio mode follows a smart playlist's rules when it continues one.
- Radio mode: when the queue is about to end, similar tracks from the local library are appended so playback continues gaplessly. Tracks are scored on listening-session co-plays with the recent tracks, shared and co-played artists, genre, year, likes and play counts, with recently played tracks held back and artists varied. Toggle it with the radio button in the now-playing bar.
- Output device picker in Settings → Playback. The choice persists; while the chosen device is unplugged, playback uses the system default and switches back when it returns. The equalizer follows the chosen device.
- Save the queue as a playlist from the queue panel.
- Drag audio files or folders onto the window to play them, or onto the queue panel to append them. Folders play in directory, disc and track order; files outside the library are read from their tags.

### Fixed
- On Python 3.10 and 3.11, PySide6 6.12.0 drops a reference to `True` on every signal emit, which eventually crashes the interpreter (CI caught it as a crash at exit). Those Pythons now stay on PySide6 6.11; Python 3.12+ is unaffected, as are the AppImage, Windows, macOS, Flatpak and AUR builds. A test guards against affected combinations.

## [0.3.3] - 2026-10-10

### Fixed
- Gapless playback no longer cuts off the end of each track: tracks play to their last sample and the next track starts just in time to join without a gap (within a few milliseconds in tests). The last track of a queue also plays to the end.

### Changed
- CI tests Python 3.10 through 3.14, checks that audio decodes inside the Flatpak, and requires the Flathub linter to pass.

## [0.3.2] - 2026-10-10

### Fixed
- The app could freeze permanently when changing track right after seeking (a deadlock between Qt's FFmpeg audio thread and Python); audio outputs are now created on the C++ side.
- In Flatpak, the window and MPRIS desktop entry now match the installed `.desktop` file, so desktops show the right icon.
- Intermittent CI segfaults and MPRIS test failures; tests now fail if they leave Qt objects in reference cycles.

### Changed
- Flatpak manifest is Flathub-ready: KDE 6.11 runtime with the PySide BaseApp, offline build with pinned Python dependencies, AppStream metainfo, and narrower sandbox permissions (no host config/data/cache access, so locally built Flatpaks start with fresh settings).
- AUR `hallucinate` PKGBUILD now packages 0.3.1 with a correct checksum; CI builds, lints and launches it in an Arch container.
- Minimum versions: PySide6 6.11.2, mutagen 1.48.1, keyring 25.7.0, setuptools 84 (build) and pytest 9.1.1 (tests); CI actions updated to checkout v7, setup-python v7 and upload-artifact v6.

## [0.3.1] - 2026-10-09

### Added
- Optional, theme-aware track format and approximate average-bitrate badges in song rows and now playing; configurable in Settings and off by default.
- Flatpak build and offscreen launch smoke test in CI, plus a stricter AppImage launch smoke test.

### Fixed
- Report detected codecs (including AAC vs ALAC and Vorbis vs Opus) separately from container extensions; legacy libraries are migrated and only ambiguous containers are rescanned.

## [0.3.0] - 2026-10-09

### Added
- Optional 24-band audio spectrum visualizer with worker-thread FFT processing, a dedicated UI page, and clean audio-tap shutdown.
- Flatpak manifest, native-architecture macOS release bundle workflow, and documentation of Qt/PipeWire output limitations.
- Drag-reorderable playback queue, play-next/add-to-queue, sleep timer and playback speed.
- ListenBrainz scrobbling and import of listening history from Last.fm/ListenBrainz.
- Discord Rich Presence with progress, artwork, privacy options and automatic reconnect.
- Listening statistics, a personal Home mix, genre/year/format filters and probable-duplicate detection.
- CLI playback controls, single-instance activation and optional desktop track-change notifications.
- Hallucinate branding, supplied logo and generated platform icons, Hallucinate color theme, `hallucinate` package/CLI, and first-run migration of the previous app's data, settings, cache and Last.fm credentials.
- Tests no longer touch the developer's real QSettings.

### Changed
- Require PySide6/Qt 6.8 or newer for audio-buffer processing.

## [0.2.0] - 2026-10-09

### Changed (performance)
- Library loading, search and model refreshes run on worker threads with their own SQLite connections; browse models update incrementally (row inserts/removes) instead of resetting.
- Play-all/album/artist actions are handled in Python, so large track lists never cross into QML; saved sessions keep a bounded queue window.
- Cover art is decoded and downscaled asynchronously by an `image://art` provider with an on-disk thumbnail cache.
- Artist lookups use an indexed folded-artist column (automatic migration).
- Theme switches cross-fade colors.
- 50k-track test: GUI-thread stalls during load/search stay far below 50 ms-class budgets in CI.

### Added
- Liked Songs and playlists; Recently played / Most played on Home.
- ReplayGain, crossfade and a 10-band FIR equalizer (numpy; audio is routed through a Qt audio tap while it is enabled).
- Tag editor (track/album), cover set/fetch (MusicBrainz + Cover Art Archive, optional embedding), and a synced lyrics panel (embedded, `.lrc`, LRCLIB).
- Mini player window and system tray icon (menu, tooltip, middle-click play/pause, close-to-tray option) in Settings → Desktop.
- Keyboard focus rings and accessible names/roles for buttons, rows and album cards; tooltips on icon buttons.
- `scripts/screenshots.py` renders README screenshots offscreen (also usable at `--scale 2` for HiDPI checks); screenshots and theme GIF in `docs/`.
- Scan progress bar, first-run "Choose music folder" flow, and loading/empty/error states (missing folders, unreadable files).

## [0.1.1] - 2026-10-09

### Added
- Windows build (PyInstaller onedir zip + Inno Setup installer) attached to releases; MPRIS skipped off Linux, Windows icon and config paths.
- AUR packaging (`hallucinate`, `hallucinate-git`) in `packaging/aur/`.
- AppImage build script and a release workflow that attaches it to tagged releases.
- Live-switchable file-backed themes (Dark, Light, Catppuccin Mocha/Latte, Nord,
  Gruvbox, Tokyo Night, Dracula), user themes, optional album-art accent.
- Last.fm scrobbling: keyring-backed auth, now-playing, offline retry queue.
- Format/playback/library hardening, MPRIS tests, manual QA checklist.
- CI (ruff + pytest), issue/PR templates, Dependabot.

## [0.1.0]

### Added
- Initial PySide6/QML music player: library scanning with SQLite FTS5 search,
  Spotify-style browse UI, queue, MPRIS2, Arch PKGBUILD.
