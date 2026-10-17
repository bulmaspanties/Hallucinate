"""What's new in this version, shown once after an update (not on a first start). A few lines a person reads
in ten seconds; the changelog has the rest."""

HIGHLIGHTS = {
    "0.9.9.4": [
        "Music servers: songs on your Jellyfin, Navidrome or other Subsonic server join your library "
        "(switch it on in Settings → Features, then add a server in Settings → Music servers).",
        "Star ratings are saved in the songs' own tags, and a cover you add is saved as cover.jpg in the "
        "album's folder, so other players see them too.",
        "What you choose stays chosen: a cover you picked, a rating you cleared and your own lyrics are no "
        "longer replaced.",
        "Fixed: the window could stop responding while left open, with a radio station from last time. "
        "Slow networks, sleeping disks and locked keyrings can't freeze it any more.",
    ],
    "0.9.9.3": [
        "Rearrange the sidebar: drag an entry, right-click it, or use Settings → Features.",
        "Find genres online, for one album in Edit album or for every album without one in Library health. "
        "You check what's found before anything is saved.",
        "Internet radio lists the songs you heard, and radio and podcasts show how much you've listened.",
        "Podcast episodes can count on Last.fm and ListenBrainz if you want (Settings → Internet & sharing).",
        "A full review for bugs and safety: safer links, downloads, updates and saving, and many small fixes.",
    ],
    "0.9.9.2": [
        "Undo on the toasts after removing songs, clearing the queue, removing a station or marking a show played.",
        "Click the playing song's cover or title to go to its album, station or show.",
        "Song and episode lists work from the keyboard: arrows, Page Up/Down, Home, End, Enter and the Menu key.",
        "Podcasts get their own settings: skip lengths, how often feeds are checked, what's kept, Up next across "
        "shows, show settings (speed, skip intro and outro, oldest first) and new-episode notifications.",
        "Your own accent colour, themes that follow the system's light or dark mode, making your own theme, "
        "and the new Ribbon theme.",
        "Two new visualizer styles, Halo and Waves, and a Reduce motion setting.",
        "Back up and restore your likes, ratings, playlists, history, stations and podcasts (Settings → Library).",
        "Search covers stations and podcasts too, and pages remember where you'd scrolled to.",
        "An equalizer for each output device, Liked Songs in step with Last.fm loves, MusicBrainz lookup in the "
        "album tag editor, and ReplayGain measured for new music by itself (each is optional).",
    ],
}


def highlights(version):
    return list(HIGHLIGHTS.get(version, []))
