# Changelog

All notable changes to this project are documented here. Format based on
[Keep a Changelog](https://keepachangelog.com/).

## [Unreleased]

### Added
- Optional 24-band audio spectrum visualizer with worker-thread FFT processing, a dedicated UI page, and clean audio-tap shutdown.
- Flatpak manifest, native-architecture macOS release bundle workflow, and documentation of Qt/PipeWire output limitations.
- Queue: drag-to-reorder (grip handle, Alt+Up/Down), speed selector (0.5–2×) and sleep timer (minutes or end of track, with fade-out) from the player bar's ⋯ menu.
- Hallucinate branding, supplied logo and generated platform icons, Hallucinate color theme, `hallucinate` package/CLI, and first-run migration of the previous app's data, settings, cache and Last.fm credentials.
- ListenBrainz token/keyring connection, now-playing and offline listen submissions, plus deduplicated listening-history imports from ListenBrainz and Last.fm.
- Discord Rich Presence (raw IPC, threaded, auto-reconnect; Flatpak/Snap/Windows paths; hide-when-paused, hide-cover and privacy options).
- Statistics for listening periods, top artists/albums/tracks, and estimated listening time; a listening-based personal Home mix; genre/year/format filters; and probable duplicate detection.
- Single-instance local IPC for `hallucinate --next`, `--prev`, `--play-pause`, `--status`, and window activation; optional track-change desktop notifications.
- Tests no longer touch the developer's real QSettings.

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
