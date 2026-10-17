# Changelog

All notable changes to this project are documented here. Format based on
[Keep a Changelog](https://keepachangelog.com/).

## [Unreleased]

## [0.9.9.4] - 2026-10-17

Music servers, your choices saved into the files, and a fix for the window freezing while left idle.

### Added
- Music servers: songs on your Jellyfin server, or your Navidrome, Gonic, Airsonic or other Subsonic server,
  join your library and play like your own files, in albums, artists, search, playlists, smart playlists, stats and history. Switch
  it on in Settings → Features, then add a server in Settings → Music servers.
  - Your sign-in is kept in your system keyring. For Subsonic it's the password, which is never sent: each
    request carries a one-time code. For Jellyfin it's only the access token the server gives; the password
    isn't kept, and removing the server signs it out there.
  - The app warns about a link that isn't secure and isn't on your home network.
  - Each server's albums are its own, so they don't merge with copies you have as files, and duplicate
    checks keep your own file.
  - A sync adds, updates and takes out songs to match the server, keeps songs you removed out, and fetches
    each album's cover once.
  - Songs from a server that can't be reached, or while offline mode is on, are skipped. The server is tried
    again every few minutes.
  - Plays count on the server too.
  - Server songs can't be put in the trash, and their tags are edited on the server.
- Star ratings are saved in the songs' own tags too, so other players (foobar2000, MusicBee, Strawberry,
  Windows) see them. On by default; switch it off in Settings → Library.
- A cover you add is also saved as cover.jpg in the album's folder (not in a folder shared with other
  albums, where it would become all of theirs). "Also embed in the audio files" is remembered, and both are
  in Settings → Library.
- MP4 and WMA ratings from other players are read too.

### Fixed
- The window could stop responding while sitting idle with a radio station restored from last time. A
  station was connected (paused) at start; when the station dropped that idle connection, Hallucinate
  reconnected over and over in the background, and a reconnect that got stuck looking up the station's
  address froze the window. Now:
  - A station is connected only while you listen. Restored at start, it's only shown, and pausing hangs up
    (live radio can't be paused). Play connects again, to what's on now.
  - Nothing reconnects in the background while you're not listening.
  - Before any stream is handed to the player (a station, a podcast stream, a music server's song), its
    server's address is looked up in the background, so a slow or broken lookup can't freeze the window.
    One that fails says "Couldn't find the station" instead.
  - A stream that's still opening when you pause, stop or switch is set aside to finish on its own, instead
    of the window waiting for it.
  - Sound devices appearing or going away while nothing plays (a headset sleeping, a monitor's speakers)
    are picked up when you press play, instead of reopening the player each time.
- A system keyring that's locked or slow to answer no longer holds up the window at start: Last.fm and
  ListenBrainz say "Waiting for the system keyring to unlock…" and sign in once it answers.
- A library scan that's slow reading a file (a network share, a drive waking up) no longer keeps the
  library locked while it waits, so the rest of the app carries on.
- A song on a disk that's waking up, or on a network share that has gone away, no longer freezes the window:
  - Playing it shows "Opening…" and starts once the disk answers, or says the file didn't open.
  - Switching away from a song that's still opening doesn't wait for it.
  - Waveforms and ReplayGain measuring open each file in the background first.
  - Quitting doesn't leave the app running in the background, waiting on a file or stream that won't open.
- Saving or removing a Last.fm or ListenBrainz sign-in can't hang the window on a keyring that doesn't
  answer, and neither can moving sign-ins over from an old version at start.
- Checking podcasts for new episodes is lighter: only episodes the feed changed are written, and the lists
  refresh once after every show is checked instead of after each one.
- Last.fm and ListenBrainz errors are in plain words ("Couldn't reach Last.fm: the server is having trouble;
  try again later" rather than "HTTP Error 500: Internal Server Error"), and their requests carry the real
  version.
- What you choose stays chosen:
  - A cover you picked is no longer replaced by the songs' own picture when the files are read again.
  - A rating you cleared no longer comes back from the file's tags at the next scan.
  - Lyrics of your own (embedded, or an .lrc beside the song) now win over lyrics found online earlier.
- Nothing is looked up again for no reason:
  - When LRCLIB has no lyrics for a song, that's remembered for a month instead of asked again every play.
  - Saving tags or a rating into a song no longer makes the app measure its loudness or draw its waveform
    again (the audio is the same).
- A rating of one star written as RATING=1 (foobar2000) was read as five stars.
- Clearing a field in a WMA file's tags failed to save.
- The cover saved for an album is written whole or not at all, and the one it replaces is removed instead of
  piling up.
- Two saves of the same song at once (a tag edit and a rating) can't undo each other.
- A full rescan no longer waits on album and artist pages kept underneath for Back: they catch up when you
  go back to them.
- A CUE sheet whose last song starts past the end of its file is no longer read again on every library scan.
- A star rating or like you just set no longer flips back for a moment when the lists refresh.
- Without a private runtime folder (some X sessions, ssh), the control socket lives in a folder of its own
  that other users can't use, instead of a shared name another user could take first.
- On Windows, the control connection's name has a random part kept in your own app-data folder, so another
  account on the same PC can't take it first and stop Hallucinate starting.
- Debug info and crash reports now leave out song files, music folders and links, as well as the home
  folder. Log lines no longer name the album or station they're about.

### Changed
- Finding lyrics online (LRCLIB) has its own switch in Settings → Internet & sharing.
- Playing a station from the Radio Browser directory no longer tells Radio Browser you played it.
- The README has a Privacy section: what goes online, when, and what's sent.
- Release builds install exact versions of every package, checked against their checksums, and a fixed
  release of appimagetool, also checked: a build gets the same files every time.

## [0.9.9.3] - 2026-10-17

Hardening on the way to 1.0, plus a few things asked for while testing.

### Added
- Rearrange the sidebar: drag an entry up or down, right-click it for Move up and Move down, press Alt+Up or
  Alt+Down on it, or use the list in Settings → Features (with Reset).
- Find genres online. In Edit album (or Edit tags), **Find online** next to Genre asks MusicBrainz and offers
  its other suggestions to pick from. In Library health, each album without a genre has **Find genre**, and
  **Find all online** looks them all up, then shows what it found to tick, change or pick another before
  anything is written. Genres come from the album where MusicBrainz has one, else from the artist (those start
  unticked).
- Heard on the radio: the Internet radio page lists every song a station played while you listened for a
  minute or more, by day, with search, Find in your library, Copy and Remove.
- Your listening on the Internet radio and Podcasts pages: hours this week, this month or all time, songs heard
  or episodes finished, and your top stations or shows. Kept apart from the music's stats.
- Podcast episodes can count on Last.fm and ListenBrainz, as the show and the episode's title (Settings →
  Internet & sharing; off unless you turn it on).
- Backups include the radio log and listening time.
- A song heard on the radio that's also in your library is scrobbled with your copy's album.
- If the window stops responding for 20 seconds, what Hallucinate was doing is recorded, and the next start
  offers it as a report to copy (like a crash report), with what the window and player were doing just
  before. A computer going to sleep doesn't count.

### Changed
- Switching off Liked Songs also hides the heart buttons, the menu item and the Last.fm loves options. A test
  now checks every page with each feature switched off.
- Search everywhere and the Podcasts page stay quick with tens of thousands of episodes.

### Fixed
- Songs scrobbled from internet radio no longer have the station's name as their album: they're the song and
  its artist (and its album, if it's in your library).
- The fields in Edit album and Edit tags have names for screen readers.
- A station that goes silent without closing the connection is noticed after 15 seconds and reconnected
  (it used to look like it was still playing, forever).
- Reconnecting to a station that dropped now really opens a new connection (it could carry on waiting on the
  old one).
- A full code review for bugs and safety. Among the fixes:
  - Links from stations, podcast feeds and online lookups must be web links (http or https), redirects
    included, and saved passwords are never sent on to another site.
  - Files and settings are written whole or not at all, so a crash or full disk can't leave half a file.
    Your data folders are private to your account.
  - An update is checked against its published checksum again just before it's installed.
  - Backups are checked before restoring.
  - A tag edit can't damage a song if saving fails.
  - Several dialogs no longer accept an empty name or a link that isn't a web link.
  - Space and Enter on a focused button press that button instead of play/pause.
  - Radio stations and podcast episodes can't be given star ratings.
  - Back and Forward skip a playlist or show you've deleted.
  - Long playlist names and artist lists are shortened instead of running off the page.
  - The queue's Clear button is greyed out when the queue is empty, and Enter saves in Edit tags.

## [0.9.9.2] - 2026-10-16

Polish everywhere, podcasts done properly, and your own touches on the look.

### Added
- Ribbon, a new theme in deep red.
- Two new visualizer styles: Halo (a ring of light that swells with the spectrum and sends out ripples on the beat) and Waves (layered waves of light whose heights follow the music).
- Pick an accent colour of your own for any theme (it's kept readable), follow the system's light or dark mode with a theme for each, or make your own theme from the current one (Settings → Appearance).
- Reduce motion (Settings → Appearance): no page transitions, zooms, spinning record, growing buttons or drifting backdrop.
- A show's page glows in its cover's colours, like an album's.
- Podcasts have their own section in Settings: how far skip back and forward go (the buttons show it), how often feeds are checked (or only when you ask), whether the show's next episode follows or playback stops, how close to the end counts as played, how many episodes a newly followed show downloads, and which downloads to keep (until played, the newest few per show, or until you remove them), with the space they take and a button to remove them all.
- Show settings on each show's page: newest or oldest first, hide played episodes, a speed of its own (change the speed while it plays and the show remembers it), skip its intro or outro, and how many of its newest episodes download by themselves.
- Find an episode within a show, and read an episode's show notes from its menu.
- Undo on the toasts that follow removing songs from the library, clearing the queue or taking a song out of it, removing a station, and marking a whole show played.
- Click the playing song's cover or title to go to it: its album, the station's page or the episode's show. The queue opens scrolled to what's playing.
- Song and episode lists work from the keyboard: Up and Down (and Page Up/Down, Home, End) move between rows without changing the volume, Enter plays, and the Menu key or Shift+F10 opens the row's menu.
- Up next for podcasts: line up episodes from any show and they play in that order, from Podcasts or an episode's menu.
- A notification when a show you follow has new episodes (Settings → Podcasts; on by default).
- Search finds your stations, shows and episodes too, alongside music.
- Pages remember how far down you'd scrolled when you come back to them with Back or from the sidebar.
- The mini player works with radio (it says LIVE, with no seek bar) and podcasts (skip back and forward buttons).
- The first-run welcome mentions internet radio and podcasts, with a switch for each.
- After an update, a short card says what's new. It shows once, and never on a first start.
- Back up and restore (Settings → Library): likes, ratings, playlists, play counts, listening history, music folders, stations and podcasts in one file. Restoring merges into what you have; nothing is deleted.
- An equalizer for each output device, if you want one (in the equalizer): headphones and speakers keep their own settings and switch over by themselves.
- Liked Songs and Last.fm loves stay in step if you choose to (Settings → Internet & sharing): liking a song loves it on Last.fm, and your existing loves can be brought in as likes.
- Smart playlist rules for lossless, sample rate and date liked.
- ReplayGain can be measured by itself for new music after each scan (Settings → Playback).
- The album tag editor can look the album up on MusicBrainz and fill in its title, album artist, year, genre and, if you want, every track's title and number.

### Fixed
- Renaming a playlist from the sidebar updates its page's heading straight away.
- Buttons that can't be pressed right now look it (dimmed), so "Saved" and "Following" no longer look like buttons to press.
- A station that stops answering says so in plain words instead of showing Qt's error text.
- Feeds, stations, MusicBrainz and cover lookups that fail say why in plain words ("the server couldn't be found", "nothing was found at that link") instead of showing Python's error text.
- In a narrow window, History says when its heatmap is showing only the last few weeks.

## [0.9.9.1] - 2026-10-16

Turn off what you don't use, and turn on internet radio and podcasts if you want them.

### Added
- Settings → Features: switch off what you don't use (Liked Songs, Folders, Stats, History, Recap, Visualizer, Library health, lyrics, and each card on Home). It disappears everywhere: the sidebar, Ctrl+K, links and shortcuts. Switch it back on and everything is still there.
- Internet radio (off until you switch it on in Settings → Features). Save stations by their stream link (.pls and .m3u links work too), import or export them as playlist files, or find them in the Radio Browser directory. The song a station is playing shows as the artist and title everywhere, including the tray, media keys and Discord. Dropped streams reconnect by themselves. Radio never counts toward your stats, history or recap; songs heard on the radio can count on Last.fm and ListenBrainz if you choose to (Settings → Internet & sharing). Offline mode stops it all.
- Podcasts (off until you switch them on in Settings → Features). Follow shows by their feed link, find them in the Apple Podcasts directory, bring your list from another app (OPML import and export), or add a folder of episode files. Episodes pick up where you stopped, show how much is left, and are marked played when you finish them; Podcasts shows what you were listening to and what's new. Download episodes to listen offline, by hand or automatically for a show, and have them removed once played. Chapters, skip back 15 s and forward 30 s, and a playback speed of their own (up to 3×) that doesn't change the music's. Episodes never count toward your stats, history or recap.

### Fixed
- The right-click menu in text fields uses the app's theme (it was a native menu with a white highlight that was hard to read).

## [0.9.9] - 2026-10-16

Right-click menus everywhere, back and forward like a browser, and fixes for narrow windows.

### Added
- Right-click works on everything you'd expect: songs everywhere (lists, queue, history, the playing song, Now Playing's cover), artists, folders, playlists in the sidebar, top artists and albums on Stats, and the random album on Home. The menus match the rest of the app.
- Songs can be removed from the library or moved to the trash, one at a time or as a selection ("More…" on the selection bar). The song menu also has Go to album, Go to artist, Show in folder, and Remove from the queue.
- Library health: every listed item opens its usual menu on right-click or long press, and clicking it opens the album or plays the song. Duplicates gets "Keep the best copies", which hides every copy but the best one of each song (lossless first, then bitrate and sample rate). Nothing is deleted.
- Back and forward like a browser: the mouse's back and forward buttons, plus Alt+← and Alt+→, step through the pages you've visited, across sections too.

### Fixed
- Home at narrow window sizes: the format breakdown no longer spills out of its card (the four facts go two by two when space is short), and this month's top artists stay inside the Listening card.
- The 12-month heatmap on History shows the most recent weeks that fit instead of running past its card in a narrow window.
- Letters on covers without art (artist avatars, Library health rows) are readable in every theme.

## [0.9.8] - 2026-10-13

Getting ready for testers: crashes leave a report, downloads are less than half the size, and the app starts
faster, uses less power while it waits and works better with screen readers.

### Added
- If Hallucinate crashes or runs into an error it can't handle, the next start offers a report to copy into a bug report: what went wrong, with the same setup details as Copy debug info. It never includes file paths, names or anything from your library.

### Changed
- Much smaller downloads: the AppImage is 108 MB instead of 270 MB, the macOS app 66 MB instead of 179 MB, and the Windows downloads less than half their size. They used to carry all of Qt, including a web browser engine Hallucinate never uses. Every build is now checked to play MP3, AAC, ALAC, FLAC, Ogg, Opus and WAV before release.
- Faster start: with a big library the window opens in under a second on later starts (the full database check now runs only after a crash, or weekly).
- Less power while idle: the backdrop drifts at a gentler frame rate, the seek bar stops redrawing the window ten times a second while another window has the focus, and a paused Now Playing stops drawing altogether instead of running the visualizer.
- Screen readers: every button, link, card, slider and field now has a spoken name and role, including the main Play/Pause button, album tiles, links on artist and album names, the listening heatmaps and the equalizer bands. Icon buttons say what they do ("Previous track") and toggles say whether they're on.

## [0.9.7.1] - 2026-10-13

### Changed
- New icons in place of the four-point sparkle, each saying what it's for: a calendar with a small chart for Recap, a list with a filter for smart playlists, a pulse line for Library health, overlapping pages for duplicates, and a download arrow for an available update.
- Screenshots and the tour clip show the new icons.

## [0.9.7] - 2026-10-13

### Fixed
- Album covers and artist pictures had jagged, stair-stepped rounded corners, and small round pictures (such as the top artists on Home and Stats) came out as octagons. Their edges are now smooth at every size.
- The update check reads four-part version numbers (such as 1.2.3.4), in case a release ever uses one.

### Changed
- The tour clip at the top of the README is sharp again; it had turned blocky from being compressed twice.
- A new social preview showing the app as it looks now, and the website and README brought up to date.

## [0.9.6] - 2026-10-13

A polish release: menus, dialogs and empty pages now look like the rest of Hallucinate.

### Changed
- Menus, dialogs, dropdowns, tooltips and text fields share the app's look: glass panels with soft shadows, rounded corners, the display font for dialog titles, pill buttons (the confirming one in the accent colour) and a short fade as they open. The page behind a dialog dims.
- Menu items have icons, and "Remove from library" and "Move to trash" are in the warning colour.
- Confirmations name their action ("Move to trash", "Remove", "Update now") instead of a bare "OK", and the trash confirmation's button is red.
- Pages with nothing to show explain what to do, with a button where there's an obvious next step: Songs, Albums and Artists before any music is added ("Open Settings"), Liked Songs and empty playlists, smart playlists with no matches ("Edit rules"), the queue, Search, Folders and History.
- New screenshots throughout, and a looping tour of the app at the top of the README and the website.

### Added
- Deleting a playlist or smart playlist asks first.

### Fixed
- The menu item under the pointer was white on white in dark themes, so it couldn't be read. It's now tinted with the theme's accent and stays readable in every theme.
- With "Show track info" on, artist pages and Recap drew an empty dark pill after each song in their lists. They now show the song's format, or nothing when it isn't known.
- Dropdowns cut their text short ("All ye…"), and the queue panel's buttons ran into its title when the panel was narrow.

## [0.9.5] - 2026-10-12

### Added
- Hallucinate has its own Flatpak repository: install it from the website (or with `flatpak install --user https://phosphene-dev.github.io/Hallucinate/hallucinate.flatpakref`) and it updates with your other Flatpak apps, through your software centre or `flatpak update`. Updates download only what changed. Every release also has a single-file `.flatpak` bundle that sets up the same repository. Everything is signed with the project's key. Hallucinate won't be submitted to Flathub; the runtime still comes from there.

### Changed
- Settings no longer says updates come "through Flathub": in the Flatpak and in distribution packages, they come through your software centre or package manager.
- The Flathub submission helper (`scripts/flathub_manifest.py`) is gone.

## [0.9.4] - 2026-10-12

Big libraries: Hallucinate is now tested with a quarter of a million songs (and a 300,000-listen history), and stays smooth at that size.

### Improved
- Faster with large libraries. On a 250,000-song test library: ready 8.7 → 5.5 s after start-up, a rescan or tag edit applies in 6.7 s instead of 12.7, and memory use is a third lower (1.5 → 1.1 GB).
- No more stalls on big libraries: opening Albums (half a second → under 0.1), the timeline (a third of a second → under 0.1) and applying a rescan (two-thirds of a second → a quarter or less) no longer hold the window up. A rescan that changes nothing no longer redraws anything.
- The timeline shows two rows of each year with "Show all" for the rest, so a year with hundreds of albums doesn't make you scroll past it.
- Search's album and artist results, smart playlists, radio and Home's mix no longer slow down as a library grows.
- An album's page opens without scanning the whole listening history.

## [0.9.3] - 2026-10-12

A safety and stability release: nothing looks different, but more can go wrong without hurting you.

### Security
- Song titles, lyrics and online lookup results can no longer format the interface or make it go online. A tag containing an image link used to make the window fetch it (a tracking pixel that also slipped past offline mode). All text is now shown as plain text, and the interface refuses any request that isn't local.
- Answers from online services are capped in size, so a broken or hostile server can't fill memory.
- The update check keeps only the version number from a release and only opens this project's own release page.
- The control socket (`hallucinate --next` and friends) now lives in your private runtime folder, so another user on the same computer can't block Hallucinate from starting.
- Dependencies are checked against known vulnerabilities in CI (none today).

### Stability
- The library database (likes, plays, playlists, history) is backed up once a day, keeping five. If it's ever damaged (a crash mid-write, a failing disk), it's set aside and the newest backup restored automatically, with a message saying so; nothing is deleted.
- A memory leak is fixed: each library reload (after a rescan, a tag edit or a folder change) left the previous album and artist song lists in memory for the rest of the session. The cache of visited pages is also capped.
- The cover thumbnail (512 MB) and waveform (256 MB) caches are kept to a size limit, dropping the least recently used.
- A damaged iTunes/MusicBee library file now gives a clear "this file looks damaged" message when importing.
- Malformed audio files, CUE sheets, playlists, lyrics, library imports, themes and Hallucinate's own state files are now fuzz-tested.
- Long-running checks on a 12,000-song library (every page, search, theme changes, rescans, queue changes) show memory levelling off with no further growth.

## [0.9.2] - 2026-10-12

### Added
- Album menus: right-click an album (or its "…" button, or the "…" on its page) to play it, play it next, queue it, add it to a playlist, edit its info, go to the artist, remove it from the library or move it to the trash. Works on the album grid, the colour wall, the timeline, Home, Search, Stats and artist pages.
- Select several albums with Ctrl/Shift+click in the album grid, the colour wall or search; a bar then plays, queues, adds to a playlist, removes or trashes them all. Right-clicking a selected album acts on the whole selection.
- Remove from library: the files stay on disk and rescans leave them out; Settings → Library brings them back. Plays, likes and playlists are kept.
- Move to trash: the music files go to the system trash (recoverable there), and a folder left with only covers or logs goes too. Nothing is ever deleted outright, and library folders themselves are never trashed.

### Fixed
- "Find cover online" no longer stops at "Network error: HTTP Error 500" when the Cover Art Archive (archive.org) fails one image: it tries a smaller size, the next matching release and the album's release-group cover, retries MusicBrainz once if it's busy, and says plainly when the servers are having trouble.

## [0.9.1] - 2026-10-12

### Fixed
- Typing a search in a big library no longer freezes the window. Results came over one value at a time, and each value had to wait for any background work in Python (a rescan, cover thumbnails, the equalizer), so a page of results could stall for most of a second on every keystroke. They now come over as one list, and song rows look up likes, the playing song and the format setting once per page instead of once per row (every song list benefits).
- Searches typed slowly no longer queue up behind each other: a search that's already been overtaken by more typing is skipped, so the latest results arrive straight away.

## [0.9.0] - 2026-10-12

### Added
- Offline mode (Settings → Internet & sharing): Hallucinate makes no internet connections at all. Lyrics and cover lookups, Last.fm and ListenBrainz, headphone EQ downloads and update checks stay off, and Discord status shows no cover art. Scrobbles wait in their queues and are sent when it's turned off; nothing is remembered as "not found" because of it. Every request goes through one place in the code, and a test fails if new code connects any other way.
- Update now: with the update check on, the Windows installer build and the AppImage can install a new release themselves. The download is checked against the SHA-256 digest GitHub publishes for it, then the installer runs silently (Windows) or the AppImage is swapped in place, and Hallucinate reopens on the new version.

### Changed
- "Scrobbling & sharing" in Settings is now "Internet & sharing".
- Closing the window now asks whether to quit, minimize or keep playing in the tray, with "Remember my choice"; Settings → Desktop → "When I close the window" changes it later. Minimize isn't offered on tiling window managers that have none (Hyprland, Sway, i3 and others). Anyone who had "Keep playing in the tray" on keeps it.
- Copies installed by a system package manager (AUR and other distribution packages) no longer offer the update check; the package manager updates them.

## [0.8.2] - 2026-10-12

### Fixed
- The Recap card's glows no longer square off its rounded corners; they now follow the card's shape, in the app and in saved images.

## [0.8.1] - 2026-10-12

### Changed
- Hallucinate now lives at https://github.com/Phosphene-dev/Hallucinate and its website at https://phosphene-dev.github.io/Hallucinate/. Old links redirect for now. The update check, "Report a bug" and the lyrics lookup's user agent point to the new address.
- The app ID is now `io.github.phosphene_dev.Hallucinate` (Flatpak, macOS bundle and Windows taskbar), ready for Flathub.

## [0.8.0] - 2026-10-12

### Added
- Select several songs at once: Ctrl+click toggles a song and Shift+click selects a range in any song list (songs, albums, artists, playlists, smart playlists, folders, search, stats, recap). A bar above the player then plays them, plays them next, queues them, adds them to a playlist (or a new one), likes or unlikes them, rates them or edits their tags together; fields that differ between them are marked mixed and left alone. Esc or leaving the page clears the selection.
- Undo queue changes (Ctrl+Z, or Undo in the queue panel, 20 steps): clearing the queue, removing or moving a song, or replacing the queue by playing something else. The playing song carries on when it can.
- Skip tracking: moving on by hand from a playing song before it counts as a play records a skip. Smart playlists get a Skip count field, and radio plays songs you keep skipping less (unless they're liked).
- Import from other players (Settings → Library): play counts, skips, last played, ratings and playlists from Strawberry, Clementine, Rhythmbox, MusicBee and iTunes/Apple Music, and foobar2000 play counts written to tags. Libraries in their usual places are found for you; importing again never counts twice, and ratings set here are kept.
- Find every missing cover at once from Library health (MusicBrainz and the Cover Art Archive, paced to MusicBrainz's one request a second, with progress and Stop).
- Headphone crossfeed (Settings → Sound): Light, Medium or Strong, so hard-panned stereo is easier on headphones. Shown in the signal path.
- Lyrics timing: nudge synced lyrics 0.25 s earlier or later in the lyrics panel or Now Playing, and save the corrected timing as an .lrc file next to the song. LRC [offset:] tags are honoured.
- CUE sheets stored inside the audio file (a CUESHEET tag in FLAC, Ogg, WavPack or Monkey's Audio, or FLAC's native cuesheet block) split it into songs, and CUE songs now get their own waveform seek bar.
- Copy debug info (Settings → About): versions, system, display and scaling, audio output, playback settings and the recent log for bug reports, with the home folder redacted and no file paths or account names. A Report a bug link sits next to it.
- An optional update check, off by default: when turned on it asks GitHub for the latest release at most once a day and shows "Update to …" in the sidebar when a newer version is out. It's off inside the Flatpak, where Flathub delivers updates.
- `scripts/flathub_manifest.py` writes the Flathub submission manifest for a release tag.

### Changed
- Settings are grouped into Appearance, Playback, Sound, Library, Scrobbling & sharing, Desktop and About, with chips to jump to each and a search box that keeps only the sections matching what you type.
- Small and tiled windows: the player bar sizes its controls to fit (no more overlap with the seek bar in narrow windows; the mini player button hides below 1100 px, Ctrl+M still works), and the selection bar sits over the page with short labels when space is tight.
- Every page, the queue, Now Playing and the welcome are now tested in all 17 themes for warnings and unthemed white areas.

## [0.7.0] - 2026-10-12

### Added
- Pride themes: Pride, Trans Pride (dark and light), Bi Pride, Lesbian Pride, Nonbinary Pride, Pan Pride and Ace Pride. Each is a calm, readable theme built around its flag: the flag's colours drift through the backdrop (very bright stripes are softened, and black, white and grey stripes stay out of it), a slim flag stripe sits under the logo, and the accent comes from the flag. Every text and accent colour meets WCAG AA contrast. Themes can now carry a `palette` of their own colours.
- The welcome's theme picker scrolls and shows each flag on its tile.

## [0.6.1] - 2026-10-12

### Fixed
- The Stats page's top artists and top albums showed as white rows with unreadable text.
- The sidebar no longer piles its entries on top of each other in short windows (tiling window managers, fractional scaling): entries tighten up, and whatever still doesn't fit scrolls above Settings.
- An accent taken from a dark album cover (Settings → Appearance → album colours) could make the playing song's title nearly invisible; it is now lightened (or darkened on light themes) until it reads.

## [0.6.0] - 2026-10-11

### Added
- Artist pages: a round picture lit by its own colours, facts (albums, songs, hours, years active, genres), your listening (plays, time, rank among your artists, first listen, plays per month for the last year), most played songs, the discography grouped by year, albums they appear on, and every song on demand. Radio starts from their most played song.
- Recap (in the sidebar): a week, month or year of listening summed up, with listening time against the period before, plays, songs, artists and days, top artists, albums and songs, new artists, top genres, the busiest day, the longest streak, when you listen (time of day, day of the week, and month by month for a year) and albums added. Step back through earlier periods, and save the highlights card as an image in Pictures.
- ReplayGain analysis: songs whose files have no ReplayGain tags can be measured (EBU R128 / ITU-R BS.1770 loudness, ReplayGain 2.0's -18 LUFS reference), with album gain from each album measured as a whole. Start it from Settings → Playback or from the new "Songs without ReplayGain" check on the Library health page. Files are never changed: results are kept in the library, survive rescans while the file is unchanged, and tags always win. The signal path marks measured gain.
- Headphone correction: search AutoEQ's 8,800+ headphone profiles in Settings → Equalizer (or import a ParametricEQ / GraphicEQ file) and the equalizer corrects your headphones towards neutral, under your own band settings, with headroom so it can't clip. The signal path names the profile.
- Lyrics in Now Playing: the lyrics button (or L) shows synced lyrics karaoke-style beside the cover, the sung line large and the others fading; click a line to jump there. Unsynced lyrics scroll.
- Playlist files: import M3U, M3U8 and PLS playlists (Playlists → + → Import; songs are matched by path, then by artist and title, then by file name, so playlists from another computer still work) and export any playlist, smart playlist, Liked Songs or the queue as M3U8, with relative paths when the songs sit below the playlist's folder.
- Star ratings: rate songs one to five stars from the track menu, the player or Now Playing (Ctrl+1…5, Ctrl+0 clears; clicking the same rating again clears it). Ratings written by other players (POPM, RATING, FMPS_RATING) are picked up until you rate a song here, and smart playlists can use them ("Rating is at least 4", sort by rating).
- Folder view (in the sidebar): browse the library by its folders on disk, with breadcrumbs, subfolders showing their song count, length and a cover, and the songs in each folder. Play, shuffle or queue a folder and everything below it.
- CUE sheets: a single-file album with a .cue sheet (one big FLAC, APE, WavPack or WAV) appears as its separate songs, with titles, performers, album, year, genre and ReplayGain from the sheet. The songs play gaplessly as one piece, and likes, ratings, history and playlists work as for any other song. Sheets that name the WAV a rip was made from still find the encoded file. Tag editing is turned off for these songs (edit the .cue instead).
- A first-run welcome: a fresh install opens on choosing your music folders (with a live count of songs found), a theme (from live previews) and, optionally, ListenBrainz or Last.fm scrobbling, instead of an empty Home. It can be skipped, and everything can be changed later in Settings.
- `scripts/bench_library.py` times the heavy library queries against a synthetic 50,000-song library.

### Changed
- Faster with big libraries (measured on 50,000 songs and 200,000 listens): artist pages 660 → 13 ms, "On this day" 950 → 85 ms, the colour wall's first run 4.2 → 1 s, history totals 2 → 0.5 s. The play log keeps accent-folded copies of artist, title and album (added once on upgrade).

## [0.5.0] - 2026-10-11

### Changed
- A new look of its own, inspired by the logo: a slowly drifting, cover-tinted backdrop with fine film grain; frosted glass panels; a floating player; a navigation rail that collapses to icons (playlists move into a menu); and the Unbounded display typeface (SIL OFL, bundled) for headings. Album covers lift and glow on hover, and pages dissolve in. The background motion can be turned off in Settings → Appearance. Everything is drawn with gradients, so it also works without a GPU.

### Added
- A waveform seek bar: each track's loudness is drawn as bars in the player (the played part lit, the time under the pointer on hover, click or drag to seek). Tracks are analysed once in the background, the next one ahead of time, and cached on disk.
- Home is now about your own library instead of a feed: a random album to play (or roll again), a 26-week listening heatmap with your streak and this month's top artists, library facts (hours of music, size on disk, lossless share, formats), a "Rediscover" shelf of albums you haven't played in three months (or ever), "On this day" from past years, and recently added albums. Recently played and your mix move to the Stats page, next to its top tracks.
- Signal path: a pill in the player says whether the sound reaches the output untouched; click it for every stage from file to device (source format, ReplayGain, equalizer, speed, volume, crossfade, output device and its rate), with the ones that change the sound lit, including resampling when the device runs at another rate.
- Library health (Settings → Library, or the link on Home): a score and checks for missing library folders, songs missing artist or album tags, albums split in two by mixed album-artist tags, albums without a cover, track numbers, a year or a genre, probable duplicates and low-bitrate files, each with a fix next to it (find a cover, edit tags or the album, remove a folder).
- Command palette (Ctrl+K): jump to any page, run any command (playback, views, visualizer style, theme, new playlist, rescan…) or open an album, artist or song by typing a few letters.
- Album pages are now sleeves: the cover large and lit by its own colours, liner notes (genre, format and sample rate, discs, size, when it was added, your plays with first and last listen, liked songs) and tracks split by disc. Play starts the album in order.
- The Albums page has three views, remembered between visits: A–Z, a colour wall (covers edge to edge, ordered round the colour wheel, then greys; colours are measured once per cover and cached) and a timeline (decades, then each year with its albums).
- Now Playing: press F, or the new button in the player, for a full-window view with the visualizer as a living backdrop in the cover's colours, a large cover, the track, a waveform seek bar and the controls. It melts in, the controls and pointer fade away when the mouse rests, Esc closes it, and F11 makes it full screen. Vinyl mode slides the record out of its sleeve and spins it while the music plays.
- New visualizer styles drawn with GPU shaders and tinted by the current cover: Liquid (flowing ink), Aurora (curtains of light that rise with the spectrum) and Nebula (a turning cloud of gas and stars that breathes with the bass), plus the bars. The Visualizer page now fills the page. The shader styles need hardware graphics; with Qt's software renderer the bars are shown instead.
- A History page with every listen, newest first and grouped by day (with each day's plays and listening time). Search it, narrow it to today, 7 or 30 days, this month or this year, pick a day on the 12-month heatmap, filter by artist (click an artist's name) or by source (played here or imported from Last.fm/ListenBrainz), play a song again, or remove a listen that shouldn't count (its song's play count follows). Clicking a day on Home's heatmap opens it here. The queries behind it are built to drive weekly, monthly and yearly summaries later.
- Project website at https://phosphene-dev.github.io/Hallucinate/ (GitHub Pages), styled after the logo. It detects the visitor's OS for the download button, and is rebuilt automatically after every release and whenever the site, screenshots or changelog change.

## [0.4.0] - 2026-10-10

### Added
- Windows media controls (System Media Transport Controls): media keys, the volume/media overlay and the lock screen show the current track with artwork and timeline, and can play/pause, stop, skip, seek, and toggle shuffle and repeat. CI tests them against the real Windows API on a Windows runner; the Windows build bundles the WinRT bindings.
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
