"""Podcasts: feeds, OPML, following, resuming where you stopped, played episodes, downloads and folders."""
import time

import pytest
from audio import FFMPEG, encode
from conftest import wait_for
from streamserver import StreamServer

from hallucinate.core import podcasts as pc

pytestmark = pytest.mark.skipif(not FFMPEG, reason="needs ffmpeg")

FEED = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd"
     xmlns:podcast="https://podcastindex.org/namespace/1.0">
<channel>
  <title>Test Talk</title>
  <itunes:author>Host Person</itunes:author>
  <description>&lt;p&gt;A show &amp;amp; more.&lt;/p&gt;</description>
  <itunes:image href="{base}/cover.png"/>
  <item>
    <title>Episode Two</title><guid>ep2</guid>
    <pubDate>Tue, 13 Oct 2026 08:00:00 +0000</pubDate>
    <itunes:duration>0:20</itunes:duration>
    <enclosure url="{base}/ep2.mp3" type="audio/mpeg" length="{size}"/>
    <podcast:chapters url="{base}/ch2.json" type="application/json+chapters"/>
    <description>&lt;p&gt;Second&lt;br/&gt;notes&lt;/p&gt;</description>
  </item>
  <item>
    <title>Episode One</title><guid>ep1</guid>
    <pubDate>Mon, 12 Oct 2026 08:00:00 +0000</pubDate>
    <itunes:duration>20</itunes:duration>
    <enclosure url="{base}/ep1.mp3" type="audio/mpeg" length="{size}"/>
  </item>
  <item><title>Just a blog post</title><guid>post</guid></item>
</channel>
</rss>"""
CHAPTERS = b'{"version":"1.2.0","chapters":[{"startTime":0,"title":"Intro"},{"startTime":8.5,"title":"Main"}]}'


@pytest.fixture(scope="module")
def clip(tmp_path_factory):
    return encode(tmp_path_factory.mktemp("ep") / "ep.mp3", "mp3", seconds=20).read_bytes()


@pytest.fixture
def server(clip):
    srv = StreamServer()
    srv.files.update({
        "/ep1.mp3": ("audio/mpeg", clip), "/ep2.mp3": ("audio/mpeg", clip), "/ch2.json": ("application/json", CHAPTERS),
        "/cover.png": ("image/png", b"\x89PNG\r\n\x1a\n" + b"\0" * 64),
    })
    srv.files["/feed.xml"] = ("application/rss+xml", FEED.format(base=srv.base, size=len(clip)).encode())
    yield srv
    srv.close()


def test_reading_a_feed(server, clip):
    podcast, episodes = pc.parse_feed(server.files["/feed.xml"][1], server.url("/feed.xml"))
    assert podcast["title"] == "Test Talk" and podcast["author"] == "Host Person"
    assert podcast["description"] == "A show & more." and podcast["image"].endswith("/cover.png")
    assert [e["title"] for e in episodes] == ["Episode Two", "Episode One"]  # the post without audio is left out
    two = episodes[0]
    assert two["guid"] == "ep2" and two["duration"] == 20 and two["size"] == len(clip)
    assert two["description"] == "Second\nnotes" and two["chapters_url"].endswith("/ch2.json")
    assert time.gmtime(two["published"]).tm_mday == 13
    with pytest.raises(ValueError):
        pc.parse_feed(b"<html>not a feed</html>")
    assert pc.parse_duration("1:02:03") == 3723 and pc.parse_duration("62:03") == 3723 and pc.parse_duration("x") == 0


def test_chapters_and_opml():
    assert pc.parse_chapters_json(CHAPTERS) == [{"start": 0.0, "title": "Intro"}, {"start": 8.5, "title": "Main"}]
    assert pc.parse_chapters_json(b"nonsense") == []
    opml = pc.make_opml([{"title": "A & B", "feed_url": "https://a/feed"}, {"title": "Folder", "folder": "/x"}])
    assert pc.parse_opml(opml) == [{"title": "A & B", "feed_url": "https://a/feed"}]
    nested = '<opml><body><outline text="Group"><outline text="One" xmlUrl="https://1/f"/></outline></body></opml>'
    assert pc.parse_opml(nested) == [{"title": "One", "feed_url": "https://1/f"}]


@pytest.fixture
def shows(qapp, tmp_path):
    from hallucinate.player import Player
    from hallucinate.podcasts import Podcasts

    player = Player(session_file=tmp_path / "session.json")
    podcasts = Podcasts(tmp_path / "streams.db", tmp_path / "data", tmp_path / "cache", player)
    messages = []
    podcasts.message.connect(messages.append)
    yield podcasts, player, messages
    podcasts.shutdown()
    player.shutdown()


def follow(podcasts, server, messages):
    podcasts.follow(server.url("/feed.xml"))
    assert wait_for(lambda: podcasts.count == 1 and not podcasts.busy), messages
    show = podcasts.shows._items[0]
    podcasts.openShow(show["id"])
    return show


def test_following_playing_and_resuming(shows, server):
    podcasts, player, messages = shows
    show = follow(podcasts, server, messages)
    assert show["title"] == "Test Talk" and show["unplayed"] == 2 and "2 new" in show["detail"]
    assert [e["title"] for e in podcasts.episodes._items] == ["Episode Two", "Episode One"]
    assert podcasts.latest.count == 2
    podcasts.follow(server.url("/feed.xml"))
    assert any("already follow" in m for m in messages)

    played = []
    player.played.connect(played.append)
    one = next(e for e in podcasts.episodes._items if e["title"] == "Episode One")
    podcasts.play(one["id"])
    assert wait_for(lambda: player.playing and player.position > 300, timeout=15), player.error
    assert player.current["kind"] == "episode" and player.queueLength == 2  # the newer episode follows
    player.seek(6000)
    assert wait_for(lambda: player.position >= 6000)
    player.pause()
    assert wait_for(lambda: podcasts._db.episode(one["id"])["position"] >= 5.5)
    podcasts.reload()
    assert podcasts.inProgress.count == 1 and "left" in podcasts.inProgress._items[0]["detail"]

    # picking it up again starts where it was left
    player.stop()
    podcasts.play(one["id"])
    assert player.current["resume_ms"] >= 5500
    assert wait_for(lambda: player.playing and player.position >= 5500, timeout=15), (player.position, player.error)
    # heard to the end: played, and nothing counted as a music play
    player.seek(19_000)
    assert wait_for(lambda: podcasts._db.episode(one["id"])["played"] == 1, timeout=15)
    assert not played
    assert wait_for(lambda: player.current.get("title") == "Episode Two", timeout=15)


def test_podcasts_keep_their_own_speed(shows, server, tmp_path):
    podcasts, player, messages = shows
    follow(podcasts, server, messages)
    song = {"id": 1, "path": str(encode(tmp_path / "song.flac", "flac", seconds=3)), "title": "Song",
            "artist": "A", "album": "B", "duration": 3, "artUrl": ""}
    player.playList([song], 0)
    player.setSpeed(1.25)
    podcasts.play(podcasts.episodes._items[0]["id"])
    assert player.speed == 1.0
    player.setSpeed(2.5)
    assert player.speed == 2.5
    player.playList([song], 0)
    assert player.speed == 1.25
    player.setSpeed(1.0)
    podcasts.play(podcasts.episodes._items[0]["id"])
    player.setSpeed(1.0)


def test_downloads_and_offline_listening(shows, server, clip):
    from hallucinate.core import net

    podcasts, player, messages = shows
    follow(podcasts, server, messages)
    two = podcasts.episodes._items[0]
    podcasts.download(two["id"])
    assert wait_for(lambda: podcasts._db.episode(two["id"])["local_path"], timeout=15), messages
    path = podcasts._db.episode(two["id"])["local_path"]
    assert open(path, "rb").read() == clip
    assert wait_for(lambda: podcasts.episodes._items[0]["status"] == "Downloaded")
    net.set_offline(True)
    try:
        podcasts.play(two["id"])
        assert player.current["path"] == path  # the file, not the stream
        assert wait_for(lambda: player.playing, timeout=10), player.error
        one = podcasts.episodes._items[1]
        player.stop()
        podcasts.play(one["id"])
        assert any("download episodes" in m for m in messages)
    finally:
        net.set_offline(False)
    # once played, a downloaded episode's file goes (Settings: remove downloads once played)
    player.stop()
    podcasts.markPlayed(two["id"], True)
    assert not podcasts._db.episode(two["id"])["local_path"]
    import os

    assert not os.path.exists(path)


def test_chapters_of_the_playing_episode(shows, server):
    podcasts, player, messages = shows
    follow(podcasts, server, messages)
    podcasts.play(podcasts.episodes._items[0]["id"])
    assert wait_for(lambda: len(podcasts.chapters) == 2, timeout=10)
    assert podcasts.chapters[1] == {"start": 8500, "title": "Main"}
    assert wait_for(lambda: player.playing, timeout=15), player.error
    podcasts.seekChapter(1)
    assert wait_for(lambda: player.position >= 8400)


def test_new_episodes_on_refresh_and_opml(shows, server, tmp_path, clip):
    podcasts, player, messages = shows
    show = follow(podcasts, server, messages)
    feed = server.files["/feed.xml"][1].decode()
    extra = f"""<item><title>Episode Three</title><guid>ep3</guid><pubDate>Wed, 14 Oct 2026 08:00:00 +0000</pubDate>
    <enclosure url="{server.base}/ep1.mp3" type="audio/mpeg" length="{len(clip)}"/></item>"""
    server.files["/feed.xml"] = ("application/rss+xml", feed.replace("<item>", extra + "<item>", 1).encode())
    podcasts.refresh(show["id"])
    assert wait_for(lambda: any(m == "1 new episode" for m in messages), timeout=10), messages
    assert podcasts.episodes._items[0]["title"] == "Episode Three"
    assert podcasts.exportOpml(str(tmp_path / "subs")) == "Saved 1 show to subs.opml"
    podcasts.unfollow(show["id"], True)
    assert podcasts.count == 0
    assert podcasts.importOpml(str(tmp_path / "subs.opml")) == "Following 1 new show"
    assert wait_for(lambda: podcasts.count == 1 and podcasts.shows._items[0]["episodes"] == 3, timeout=10)


def test_a_folder_of_episodes(shows, tmp_path):
    podcasts, player, messages = shows
    folder = tmp_path / "My Show"
    folder.mkdir()
    encode(folder / "01.mp3", "mp3", seconds=2, title="First", album="Local Show", artist="Me", date="2025-01-01")
    encode(folder / "02.mp3", "mp3", seconds=2, title="Second", album="Local Show", artist="Me", date="2025-02-01")
    podcasts.addFolder(str(folder))
    assert wait_for(lambda: podcasts.count == 1 and not podcasts.busy), messages
    show = podcasts.shows._items[0]
    assert show["title"] == "Local Show" and show["author"] == "Me"
    podcasts.openShow(show["id"])
    assert [e["title"] for e in podcasts.episodes._items] == ["Second", "First"]
    assert all(e["local"] and not e["downloaded"] for e in podcasts.episodes._items)
    first = podcasts.episodes._items[1]
    podcasts.markPlayed(first["id"], True)
    assert (folder / "01.mp3").exists()  # your own files are never deleted
    podcasts.unfollow(show["id"], True)
    assert (folder / "02.mp3").exists()


def test_directory_results(shows, monkeypatch):
    podcasts, player, messages = shows
    monkeypatch.setattr(pc, "search_directory", lambda q: [
        {"title": "Found Show", "author": "Someone", "feed_url": "https://f/feed", "image": "", "genre": "News"}])
    podcasts.search("news")
    assert wait_for(lambda: not podcasts.searching)
    assert podcasts.results.count == 1 and podcasts.results._items[0]["followed"] is False
    from hallucinate.core import net

    net.set_offline(True)
    try:
        podcasts.search("news")
        assert "Offline" in podcasts.status
    finally:
        net.set_offline(False)


def test_show_settings_and_episode_search(shows, server):
    podcasts, player, messages = shows
    show = follow(podcasts, server, messages)
    pid = show["id"]
    podcasts.setShowOption(pid, "newest_first", 0)
    assert [e["title"] for e in podcasts.episodes._items] == ["Episode One", "Episode Two"]
    podcasts.markPlayed(podcasts.episodes._items[0]["id"], True)
    podcasts.setShowOption(pid, "hide_played", 1)
    assert [e["title"] for e in podcasts.episodes._items] == ["Episode Two"]
    podcasts.setShowOption(pid, "hide_played", 0)
    podcasts.setEpisodeFilter("notes")  # Episode Two's notes say "Second notes"
    assert [e["title"] for e in podcasts.episodes._items] == ["Episode Two"]
    podcasts.setEpisodeFilter("")
    podcasts.setShowOption(pid, "speed", 7)  # not one of the choices
    assert podcasts.show(pid)["speed"] == 0
    # its intro skipped and a speed of its own
    podcasts.setShowOption(pid, "skip_intro", 15)
    podcasts.setShowOption(pid, "speed", 1.5)
    two = next(e for e in podcasts.episodes._items if e["title"] == "Episode Two")
    podcasts.play(two["id"])
    assert player.current["resume_ms"] == 15000 and player.speed == 1.5
    assert wait_for(lambda: player.playing and player.position >= 14000, timeout=15), player.error
    player.setSpeed(1.75)  # changing it while the show plays changes the show's
    assert wait_for(lambda: podcasts.show(pid)["speed"] == 1.75)
    player.stop()


def test_podcast_settings(shows, server, monkeypatch):
    podcasts, player, messages = shows
    podcasts.setOption("skipBack", 10)
    podcasts.setOption("skipBack", 11)  # not offered
    assert podcasts.options["skipBack"] == 10
    from hallucinate.podcasts import Podcasts

    again = Podcasts(podcasts._db.conn.execute("PRAGMA database_list").fetchone()[2], "/tmp", "/tmp", player)
    assert again.options["skipBack"] == 10  # remembered
    again.shutdown()
    podcasts.setOption("skipBack", 15)

    # "stop" after an episode: nothing else is queued after it
    show = follow(podcasts, server, messages)
    podcasts.setOption("afterEpisode", "stop")
    podcasts.play(podcasts.episodes._items[1]["id"])
    assert player.queueLength == 1
    podcasts.setOption("afterEpisode", "next")
    player.stop()

    # keep only the newest download of each show
    podcasts.setOption("keep", "latest")
    podcasts.setOption("keepCount", 1)
    for e in list(podcasts.episodes._items):
        podcasts.download(e["id"])
    assert wait_for(lambda: not podcasts._downloading, timeout=15)
    assert wait_for(lambda: len([e for e in podcasts._db.downloaded(show["id"])]) == 1, timeout=5)
    assert podcasts._db.downloaded(show["id"])[0]["guid"] == "ep2"
    assert podcasts.downloadsSize > 0
    podcasts.removeAllDownloads()
    assert podcasts.downloadsSize == 0 and not podcasts._db.downloaded(show["id"])
    podcasts.setOption("keep", "played")
    podcasts.setOption("keepCount", 3)


def test_up_next_and_new_episode_notifications(shows, server, clip):
    podcasts, player, messages = shows
    follow(podcasts, server, messages)
    one, two = podcasts.episodes._items[1], podcasts.episodes._items[0]
    podcasts.addUpNext(one["id"])
    podcasts.addUpNext(two["id"], True)  # first
    assert [e["title"] for e in podcasts.upNext._items] == ["Episode Two", "Episode One"]
    podcasts.playUpNext(two["id"])
    assert [t["title"] for t in player.queue] == ["Episode Two", "Episode One"]
    player.stop()
    podcasts.markPlayed(two["id"], True)  # heard: off the list
    assert [e["title"] for e in podcasts.upNext._items] == ["Episode One"]
    podcasts.removeUpNext(one["id"])
    assert podcasts.upNext.count == 0

    told = []
    podcasts.newEpisodes.connect(lambda show, title: told.append((show, title)))
    podcasts.setOption("notifyNew", 1)
    feed = server.files["/feed.xml"][1].decode()
    extra = f"""<item><title>Brand New</title><guid>new</guid><pubDate>Wed, 14 Oct 2026 08:00:00 +0000</pubDate>
    <enclosure url="{server.base}/ep1.mp3" type="audio/mpeg" length="{len(clip)}"/></item>"""
    server.files["/feed.xml"] = ("application/rss+xml", feed.replace("<item>", extra + "<item>", 1).encode())
    podcasts.refreshAll()
    assert wait_for(lambda: told, timeout=10)
    assert told[0] == ("Test Talk", "Brand New")
    podcasts.setOption("notifyNew", 0)


def test_the_top_search_stays_quick_with_many_episodes(tmp_path):
    """Search everywhere asks for shows and episodes on the GUI thread as you type: with 120 shows of 400
    episodes (each with long notes) it must stay well inside a frame or two."""
    import time

    from hallucinate.core.streams_db import StreamsDB

    db = StreamsDB(tmp_path / "s.db")
    notes = "words about the episode " * 60
    for p in range(120):
        pid = db.add_podcast({"title": f"Show {p}", "feed_url": f"https://x/{p}"})
        db.merge_episodes(pid, [{"guid": str(i), "title": f"Episode {i} of show {p}", "url": f"https://x/{p}/{i}",
                                 "published": 1.7e9 + i * 86400, "duration": 60, "description": notes}
                                for i in range(400)])
    start = time.perf_counter()
    for _ in range(5):
        db.podcasts()
        db.episodes(text="nothing-matches-this", limit=8, titles_only=True)
    per_search = (time.perf_counter() - start) / 5
    db.close()
    assert per_search < 0.05, f"{per_search * 1000:.0f} ms"


def test_a_refresh_writes_only_what_the_feed_changed(tmp_path):
    from hallucinate.core.streams_db import StreamsDB

    db = StreamsDB(tmp_path / "s.db")
    pid = db.add_podcast({"title": "Show", "feed_url": "https://x/feed"})
    eps = [{"guid": str(i), "title": f"E{i}", "url": f"https://x/{i}.mp3", "duration": 60} for i in range(50)]
    assert len(db.merge_episodes(pid, eps + [dict(eps[0])])) == 50  # listed twice in the feed: added once
    first = db.episodes(pid)[0]
    db.conn.execute("UPDATE episodes SET position=12 WHERE id=?", (first["id"],))
    db.conn.commit()
    before = db.conn.total_changes
    assert db.merge_episodes(pid, eps) == []
    assert db.conn.total_changes == before  # nothing changed: nothing written
    eps[0] = {**eps[0], "title": "E0 (fixed)"}
    assert db.merge_episodes(pid, eps) == []
    assert db.conn.total_changes == before + 1
    rows = {e["guid"]: e for e in db.episodes(pid)}
    assert rows["0"]["title"] == "E0 (fixed)" and len(rows) == 50
    assert rows[first["guid"]]["position"] == 12  # where you stopped is kept
    db.close()
