"""Use the app round and round and watch its memory: does it level off, or keep climbing (a leak)?

    python scripts/soak_check.py [--tracks 20000] [--rounds 12]

Starts the real window on a synthetic library (bench_library.build, as scale_check.py), then repeats a round of
ordinary use: every page, the album views, an album and an artist page and back, a search, playing and skipping,
the queue and Now Playing opened and closed, and a library reload. After each round it reports the memory in use.
Memory grows over the first rounds as caches fill; after that, a round should cost nothing more. The last line
compares the second half's growth with the first's."""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import scale_check  # noqa: E402


def main():
    args = scale_check.arguments(tracks=20_000, plays=30_000, rounds=12)
    run = scale_check.launch(args)
    window, library, player, wait, go, call = run.window, run.library, run.player, run.wait, run.go, run.call
    QObject = run.QObject
    stack = window.findChild(QObject, "pageStack")
    now_playing = window.findChild(QObject, "nowPlayingView")
    albums = [library.albums.get(i) for i in range(min(20, library.albums.rowCount()))]

    def one_round(n):
        for page in ("home", "albums", "artists", "songs", "folders", "liked", "stats", "history", "recap", "health"):
            go(page)
            wait(150)
        go("albums")
        wait(150)
        for view in ("colour", "timeline", "grid"):
            stack.property("currentItem").setProperty("view", view)
            wait(300)
        album = albums[n % len(albums)]
        call("openAlbum", album["album_key"])
        wait(250)
        call("openArtist", album["album_artist"])
        wait(250)
        QObjectInvoke(window, "goBack")
        QObjectInvoke(window, "goBack")
        go("songs")
        wait(100)
        library.search(f"song {n}")
        wait(400)
        library.search("")
        library.playAlbum(album["album_key"], 0)
        for _ in range(4):
            player.next()
            wait(80)
        player.pause()
        window.setProperty("queueOpen", True)
        wait(200)
        window.setProperty("queueOpen", False)
        if now_playing is not None:
            now_playing.setProperty("open", True)
            wait(300)
            now_playing.setProperty("open", False)
        revision = library.detailRevision
        library.reload()
        deadline = time.time() + 60
        while library.detailRevision == revision and time.time() < deadline:
            wait(20)
        wait(300)

    def QObjectInvoke(obj, name):
        from PySide6.QtCore import QMetaObject, Qt

        QMetaObject.invokeMethod(obj, name, Qt.ConnectionType.DirectConnection)
        wait(150)

    import gc

    readings = []
    for n in range(args.rounds):
        one_round(n)
        gc.collect()
        wait(500)
        readings.append(scale_check.rss_mb())
        print(f"  round {n + 1:2d}: {readings[-1]:6.0f} MB", flush=True)
    half = len(readings) // 2
    early = readings[half - 1] - readings[0]
    late = readings[-1] - readings[half - 1]
    per_round = late / max(1, len(readings) - half)
    print(f"  growth: first half {early:+.0f} MB, second half {late:+.0f} MB ({per_round:+.1f} MB a round)"
          f"{'  <- keeps climbing' if per_round > 2 else ''}")
    import os

    os._exit(0)


if __name__ == "__main__":
    main()
