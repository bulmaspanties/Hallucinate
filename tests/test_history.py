"""The play log behind the History page: filters, totals, days, deleting a listen."""
import datetime
import time

import pytest

from hallucinate.core import history

DAY = 86_400
NOW = time.mktime(datetime.datetime(2026, 10, 11, 20, 0).timetuple())  # a Sunday evening


def add(db, path, title, artist, album, duration=200.0):
    db.upsert_track({
        "path": path, "mtime": 0, "size": 1, "title": title, "artist": artist, "album_artist": artist, "aa_tag": 1,
        "album": album, "album_key": f"{artist}|{album}", "track_no": 1, "disc_no": 0, "year": 2000, "genre": "",
        "duration": duration, "fmt": "FLAC", "codec": "FLAC", "bitrate": 0, "sample_rate": 44100,
    })


@pytest.fixture
def log(db):
    add(db, "/m/joga", "Jóga", "Björk", "Homogenic", 305)
    add(db, "/m/hunter", "Hunter", "Björk", "Homogenic", 255)
    add(db, "/m/teardrop", "Teardrop", "Massive Attack", "Mezzanine", 330)
    db.record_play("/m/joga", NOW - 3600)           # today
    db.record_play("/m/hunter", NOW - 3000)          # today
    db.record_play("/m/joga", NOW - DAY - 600)       # yesterday
    db.record_play("/m/teardrop", NOW - 40 * DAY)    # last month
    db.import_plays([
        {"ts": NOW - 400 * DAY, "artist": "Massive Attack", "title": "Angel", "album": "Mezzanine"},
        {"ts": NOW - 401 * DAY, "artist": "Björk", "title": "Jóga", "album": "Homogenic"},
    ], "lastfm")
    return db


def test_plays_newest_first_with_day_and_library_details(log):
    rows = history.plays(log)
    assert [r["title"] for r in rows] == ["Hunter", "Jóga", "Jóga", "Teardrop", "Angel", "Jóga"]
    first = rows[0]
    assert first["day"] == "2026-10-11" and first["time"] == "19:10"
    assert first["album_key"] == "Björk|Homogenic" and first["available"] == 1 and first["source"] == "local"
    angel = rows[4]
    assert angel["available"] == 0 and angel["path"] == "" and angel["album_key"] == "" and angel["source"] == "lastfm"
    assert rows[5]["available"] == 1  # an imported listen matched to a local file
    assert [r["title"] for r in history.plays(log, limit=2, offset=1)] == ["Jóga", "Jóga"]


def test_filters(log):
    titles = lambda **kw: [r["title"] for r in history.plays(log, **kw)]  # noqa: E731
    assert titles(query="joga") == ["Jóga", "Jóga", "Jóga"]  # accents and case don't matter
    assert titles(query="mezzanine") == ["Teardrop", "Angel"]
    assert titles(query="bjork hunt") == ["Hunter"]  # every word must match
    assert titles(artist="bjork") == ["Hunter", "Jóga", "Jóga", "Jóga"]
    assert titles(source="imported") == ["Angel", "Jóga"]
    assert titles(source="local") == ["Hunter", "Jóga", "Jóga", "Teardrop"]
    start, end = history.period_range("day:2026-10-10")
    assert titles(start=start, end=end) == ["Jóga"]
    assert titles(query="100%") == []


def test_period_ranges():
    def day(ts):
        return datetime.date.fromtimestamp(ts).isoformat()

    assert history.period_range("all", NOW) == (None, None)
    assert day(history.period_range("today", NOW)[0]) == "2026-10-11"
    assert day(history.period_range("7d", NOW)[0]) == "2026-10-05"
    assert day(history.period_range("30d", NOW)[0]) == "2026-09-12"
    assert day(history.period_range("week", NOW)[0]) == "2026-10-05"  # Monday
    assert day(history.period_range("month", NOW)[0]) == "2026-10-01"
    assert day(history.period_range("year", NOW)[0]) == "2026-01-01"
    start, end = history.period_range("month:2024-02", NOW)
    assert (day(start), day(end)) == ("2024-02-01", "2024-03-01")
    start, end = history.period_range("year:2025", NOW)
    assert (day(start), day(end)) == ("2025-01-01", "2026-01-01")
    assert history.period_range("day:nonsense", NOW) == (None, None)


def test_summary_and_daily_totals(log):
    total = history.summary(log)
    assert total["plays"] == 6 and total["songs"] == 4 and total["artists"] == 2 and total["albums"] == 2
    assert total["days"] == 5 and total["seconds"] == pytest.approx(305 * 3 + 255 + 330 + 0)
    start, _ = history.period_range("today", NOW)
    assert history.summary(log, start=start)["plays"] == 2
    days = history.daily_totals(log)
    assert days["2026-10-11"] == {"plays": 2, "seconds": 560.0}
    assert days["2026-10-10"]["plays"] == 1
    empty = history.summary(log, query="nothing like this")
    assert empty["plays"] == 0 and empty["first"] == 0


def test_delete_play_adjusts_play_counts(log):
    def plays_row(path):
        return log.conn.execute("SELECT count, last FROM plays WHERE path=?", (path,)).fetchone()

    assert plays_row("/m/joga")["count"] == 3  # two here, one imported
    newest_joga = next(r for r in history.plays(log) if r["title"] == "Jóga")
    assert history.delete_play(log, newest_joga["id"])
    row = plays_row("/m/joga")
    assert row["count"] == 2 and row["last"] == pytest.approx(NOW - DAY - 600)
    hunter = next(r for r in history.plays(log) if r["title"] == "Hunter")
    assert history.delete_play(log, hunter["id"])
    assert plays_row("/m/hunter") is None
    assert not history.delete_play(log, 99_999)
    angel = next(r for r in history.plays(log) if r["title"] == "Angel")
    assert history.delete_play(log, angel["id"])  # not in the library: only the log entry goes
    assert history.summary(log)["plays"] == 3


def test_day_label():
    assert history.day_label("2026-10-11", NOW) == "Today"
    assert history.day_label("2026-10-10", NOW) == "Yesterday"
    assert history.day_label("2026-10-07", NOW) == "Wednesday"
    assert history.day_label("2026-09-01", NOW) == "Tuesday 1 September"
    assert history.day_label("2025-09-01", NOW) == "Monday 1 September 2025"


def test_user_library_history(qapp, log):
    from conftest import wait_for

    from hallucinate.userlib import UserLibrary

    ul = UserLibrary(log.conn.execute("PRAGMA database_list").fetchone()["file"])
    try:
        model = ul.historyModel
        ul.loadHistory("", "all", "", "")
        assert wait_for(lambda: model.count == 6 and not ul.historyInfo["loading"])
        info = ul.historyInfo
        assert info["summary"]["plays"] == 6 and info["period"] == "all" and not info["hasMore"]
        assert len(info["heatmap"]["days"]) == 53 * 7 and info["days"]
        assert model.get(0)["dayLabel"] and model.get(0)["artUrl"] == ""

        ul.loadHistory("", "all", "Massive Attack", "")
        assert wait_for(lambda: model.count == 2)
        ul.loadHistory("joga", "all", "", "imported")
        assert wait_for(lambda: model.count == 1)

        ul.loadHistory("", "all", "", "")
        assert wait_for(lambda: model.count == 6)
        ul.removeHistoryEntry(model.get(0)["id"])
        assert wait_for(lambda: model.count == 5 and ul.historyInfo["summary"]["plays"] == 5)
    finally:
        ul.shutdown()


def test_history_pages_in(qapp, db, monkeypatch):
    from conftest import wait_for

    from hallucinate import userlib
    from hallucinate.userlib import UserLibrary

    add(db, "/m/a", "A", "Artist", "Album")
    for i in range(7):
        db.record_play("/m/a", NOW - i * 60)
    monkeypatch.setattr(userlib, "HISTORY_PAGE", 3)
    ul = UserLibrary(db.conn.execute("PRAGMA database_list").fetchone()["file"])
    try:
        ul.loadHistory("", "all", "", "")
        assert wait_for(lambda: ul.historyModel.count == 3 and ul.historyInfo["hasMore"])
        ul.loadMoreHistory()
        assert wait_for(lambda: ul.historyModel.count == 6)
        ul.loadMoreHistory()
        assert wait_for(lambda: ul.historyModel.count == 7 and not ul.historyInfo["hasMore"])
        ids = [ul.historyModel.get(i)["id"] for i in range(7)]
        assert len(set(ids)) == 7
    finally:
        ul.shutdown()
