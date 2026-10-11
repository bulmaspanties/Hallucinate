"""The play log: every listen, searchable and filterable, plus totals for any span of time.

Pure functions over a Database (they run on a worker thread). The same filter and summary queries are meant to
back weekly, monthly and yearly summaries later. `now` is a Unix timestamp so tests can pin it."""
import datetime
import time

from .db import _like, _tokens

PERIODS = ("all", "today", "7d", "30d", "week", "month", "year")
_COLS = """l.id AS id, l.ts AS ts, l.path AS path, l.title AS title, l.artist AS artist, l.album AS album,
           l.duration AS duration, l.source AS source, t.album_key AS album_key, t.art AS art,
           CASE WHEN t.path IS NULL THEN 0 ELSE 1 END AS available"""


def _midnight(day):
    return time.mktime(day.timetuple())


def period_range(period, now=None):
    """(start, end) timestamps for a named period, end exclusive; None means unbounded.

    Named periods: all, today, 7d, 30d, week (since Monday), month, year; or "day:YYYY-MM-DD" for one day,
    "month:YYYY-MM" and "year:YYYY" for a calendar month or year."""
    now = time.time() if now is None else now
    today = datetime.date.fromtimestamp(now)
    kind, _, value = (period or "all").partition(":")
    try:
        if kind == "day" and value:
            day = datetime.date.fromisoformat(value)
            return _midnight(day), _midnight(day + datetime.timedelta(days=1))
        if kind == "month" and value:
            first = datetime.date.fromisoformat(value + "-01")
            following = (first + datetime.timedelta(days=32)).replace(day=1)
            return _midnight(first), _midnight(following)
        if kind == "year" and value:
            year = int(value)
            return _midnight(datetime.date(year, 1, 1)), _midnight(datetime.date(year + 1, 1, 1))
    except ValueError:
        return None, None
    if kind == "today":
        return _midnight(today), None
    if kind == "7d":
        return _midnight(today - datetime.timedelta(days=6)), None
    if kind == "30d":
        return _midnight(today - datetime.timedelta(days=29)), None
    if kind == "week":
        return _midnight(today - datetime.timedelta(days=today.weekday())), None
    if kind == "month":
        return _midnight(today.replace(day=1)), None
    if kind == "year":
        return _midnight(today.replace(month=1, day=1)), None
    return None, None


def _where(query="", start=None, end=None, artist="", source=""):
    clauses, params = [], []
    if start is not None:
        clauses.append("l.ts >= ?")
        params.append(start)
    if end is not None:
        clauses.append("l.ts < ?")
        params.append(end)
    if artist:
        clauses.append("fold(l.artist) = fold(?)")
        params.append(artist)
    if source == "local":
        clauses.append("l.source = 'local'")
    elif source == "imported":
        clauses.append("l.source != 'local'")
    for token in _tokens(query):
        clauses.append(
            "(fold(l.title) LIKE ? ESCAPE '\\' OR fold(l.artist) LIKE ? ESCAPE '\\' OR fold(l.album) LIKE ? ESCAPE '\\')")
        params += [_like(token)] * 3
    return ("WHERE " + " AND ".join(clauses)) if clauses else "", params


def plays(db, query="", start=None, end=None, artist="", source="", limit=200, offset=0):
    """Listens matching the filters, newest first. Each row has the log fields plus the track's album key and art
    when the file is still in the library (`available`), and its local `day` (ISO date) for grouping."""
    where, params = _where(query, start, end, artist, source)
    rows = db._rows(
        f"SELECT {_COLS} FROM play_log l LEFT JOIN tracks t ON t.path = l.path {where} "
        "ORDER BY l.ts DESC, l.id DESC LIMIT ? OFFSET ?",
        (*params, limit, offset),
    )
    for r in rows:
        when = datetime.datetime.fromtimestamp(r["ts"])
        r["day"] = when.date().isoformat()
        r["time"] = when.strftime("%H:%M")
        r["album_key"] = r["album_key"] or ""
        r["path"] = r["path"] or ""
    return rows


def summary(db, query="", start=None, end=None, artist="", source=""):
    """Totals for the listens matching the filters: plays, listening seconds, distinct songs, artists and albums,
    days listened, and the first and last listen."""
    where, params = _where(query, start, end, artist, source)
    row = db.conn.execute(
        f"""SELECT COUNT(*) AS plays, COALESCE(SUM(l.duration), 0) AS seconds,
                   COUNT(DISTINCT fold(l.artist) || char(31) || fold(l.title)) AS songs,
                   COUNT(DISTINCT fold(l.artist)) AS artists,
                   COUNT(DISTINCT fold(l.artist) || char(31) || fold(l.album)) AS albums,
                   COUNT(DISTINCT date(l.ts, 'unixepoch', 'localtime')) AS days,
                   MIN(l.ts) AS first, MAX(l.ts) AS last
            FROM play_log l {where}""",
        params,
    ).fetchone()
    return {
        "plays": row["plays"], "seconds": float(row["seconds"]), "songs": row["songs"], "artists": row["artists"],
        "albums": row["albums"], "days": row["days"], "first": row["first"] or 0, "last": row["last"] or 0,
    }


def daily_totals(db, query="", start=None, end=None, artist="", source=""):
    """{ISO date: {"plays", "seconds"}} for each local day with matching listens."""
    where, params = _where(query, start, end, artist, source)
    return {
        r["day"]: {"plays": r["plays"], "seconds": float(r["seconds"])}
        for r in db.conn.execute(
            f"""SELECT date(l.ts, 'unixepoch', 'localtime') AS day, COUNT(*) AS plays,
                       COALESCE(SUM(l.duration), 0) AS seconds
                FROM play_log l {where} GROUP BY day""",
            params,
        )
    }


def delete_play(db, play_id):
    """Remove one listen; the track's play count drops by one and its last-played time follows the log."""
    row = db.conn.execute("SELECT ts, path FROM play_log WHERE id = ?", (play_id,)).fetchone()
    if row is None:
        return False
    db.conn.execute("DELETE FROM play_log WHERE id = ?", (play_id,))
    if row["path"]:
        path = row["path"]
        db.conn.execute(
            """UPDATE plays SET count = count - 1,
                   last = COALESCE((SELECT MAX(ts) FROM play_log WHERE path = ?), last)
               WHERE path = ?""",
            (path, path),
        )
        db.conn.execute("DELETE FROM plays WHERE path = ? AND count <= 0", (path,))
    db.conn.commit()
    return True


def day_label(iso, now=None):
    """"Today", "Yesterday", a weekday within the last week, else a full date."""
    now = time.time() if now is None else now
    today = datetime.date.fromtimestamp(now)
    day = datetime.date.fromisoformat(iso)
    age = (today - day).days
    if age == 0:
        return "Today"
    if age == 1:
        return "Yesterday"
    if 1 < age < 7:
        return f"{day:%A}"
    return f"{day:%A} {day.day} {day:%B %Y}" if day.year != today.year else f"{day:%A} {day.day} {day:%B}"
