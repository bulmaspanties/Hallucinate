# Changelog

All notable changes to this project are documented here. Format based on
[Keep a Changelog](https://keepachangelog.com/).

## [Unreleased]

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
- Scan progress bar, first-run "Choose music folder" flow, and loading/empty/error states (missing folders, unreadable files).

## [0.1.1] - 2026-10-09

### Added
- Windows build (PyInstaller onedir zip + Inno Setup installer) attached to releases; MPRIS skipped off Linux, Windows icon and config paths.
- AUR packaging (`musicplayer`, `musicplayer-git`) in `packaging/aur/`.
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
