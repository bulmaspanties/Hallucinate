"""What Home shows about your own library: facts, albums to rediscover, this day in past years, and when you listen.

Pure functions over a Database; they run on a worker thread. `now` is a Unix timestamp so tests can pin it."""
import datetime
import time

LOSSLESS = {"FLAC", "ALAC", "WAV", "AIFF", "WAVPACK", "APE", "TTA", "DSF", "DFF"}
DAY = 86_400
_ALBUM_COLS = """t.album_key AS album_key, MIN(t.album) AS album, MIN(t.album_artist) AS album_artist,
                 MAX(t.year) AS year, COUNT(*) AS n, SUM(t.duration) AS duration, MAX(t.art) AS art"""


def library_facts(db, top_formats=4):
    """Totals for the whole library: hours, bytes, lossless share and the most common formats."""
    row = db.conn.execute(
        "SELECT COUNT(*) AS tracks, COUNT(DISTINCT album_key) AS albums, COUNT(DISTINCT s_aa) AS artists, "
        "COALESCE(SUM(duration), 0) AS seconds, COALESCE(SUM(size), 0) AS bytes FROM tracks"
    ).fetchone()
    formats = db._rows(
        "SELECT UPPER(CASE WHEN codec != '' THEN codec ELSE fmt END) AS name, COUNT(*) AS count "
        "FROM tracks GROUP BY name ORDER BY count DESC, name"
    )
    total = row["tracks"] or 0
    lossless = sum(f["count"] for f in formats if f["name"] in LOSSLESS)
    shown = formats[:top_formats]
    rest = sum(f["count"] for f in formats[top_formats:])
    if rest:
        shown.append({"name": "Other", "count": rest})
    for f in shown:
        f["share"] = f["count"] / total if total else 0.0
    return {
        "tracks": total, "albums": row["albums"], "artists": row["artists"],
        "seconds": float(row["seconds"]), "bytes": int(row["bytes"]),
        "lossless": lossless / total if total else 0.0, "formats": shown,
    }


def rediscover_albums(db, now=None, limit=12, min_age_days=90):
    """Albums you played before but not for at least `min_age_days`, most loved first.

    Topped up with albums never played at all, so a library without much history still gets suggestions."""
    now = time.time() if now is None else now
    cutoff = now - min_age_days * DAY
    played = db._rows(
        f"""SELECT {_ALBUM_COLS}, SUM(p.count) AS plays, MAX(p.last) AS last
            FROM tracks t JOIN plays p ON p.path = t.path
            GROUP BY t.album_key HAVING MAX(p.last) < ?
            ORDER BY plays DESC, last LIMIT ?""",
        (cutoff, limit),
    )
    for album in played:
        album["reason"] = "Last played " + _month_year(album["last"])
    if len(played) < limit:
        never = db._rows(
            f"""SELECT {_ALBUM_COLS} FROM tracks t
                WHERE t.album_key NOT IN (SELECT t2.album_key FROM tracks t2 JOIN plays p ON p.path = t2.path)
                GROUP BY t.album_key ORDER BY random() LIMIT ?""",
            (limit - len(played),),
        )
        for album in never:
            album["reason"] = "Never played"
        played += never
    return played


def on_this_day(db, now=None, window_days=3, limit=12):
    """Albums you listened to around today's date in earlier years, most recent year first."""
    now = time.time() if now is None else now
    today = datetime.date.fromtimestamp(now)
    rows = db._rows(
        "SELECT l.ts AS ts, t.album_key AS album_key FROM play_log l JOIN tracks t ON t.path = l.path "
        "WHERE l.ts < ?",
        (now - 300 * DAY,),
    )
    years = {}
    for r in rows:
        day = datetime.date.fromtimestamp(r["ts"])
        try:
            same_day = day.replace(year=today.year)
        except ValueError:  # 29 February
            same_day = day.replace(year=today.year, day=28)
        if day.year < today.year and abs((same_day - today).days) <= window_days:
            years.setdefault(r["album_key"], set()).add(day.year)
    if not years:
        return []
    keys = sorted(years, key=lambda k: (-max(years[k]), k))[:limit]
    by_key = {a["album_key"]: a for a in db._rows(
        f"SELECT {_ALBUM_COLS} FROM tracks t WHERE t.album_key IN ({','.join('?' * len(keys))}) GROUP BY t.album_key",
        keys)}
    out = []
    for key in keys:
        if key in by_key:
            album = by_key[key]
            album["reason"] = "Played on this day in " + ", ".join(str(y) for y in sorted(years[key], reverse=True))
            out.append(album)
    return out


def listening_heatmap(db, now=None, weeks=26):
    """Plays per day for the last `weeks` weeks, as columns of Monday-to-Sunday ending with this week.

    Returns {"days": [count, …] oldest first, "first": ISO date of the first cell, "today": index of today,
    "max", "total", "streak" (consecutive days with plays up to today or yesterday) and "activeDays"}."""
    now = time.time() if now is None else now
    today = datetime.date.fromtimestamp(now)
    first = today - datetime.timedelta(days=today.weekday() + (weeks - 1) * 7)
    start = time.mktime(first.timetuple())
    counts = [0] * (weeks * 7)
    for (ts,) in db.conn.execute("SELECT ts FROM play_log WHERE ts >= ? AND ts <= ?", (start, now)):
        index = (datetime.date.fromtimestamp(ts) - first).days
        if 0 <= index < len(counts):
            counts[index] += 1
    today_index = (today - first).days
    streak, i = 0, today_index if counts[today_index] else today_index - 1
    while i >= 0 and counts[i]:
        streak += 1
        i -= 1
    return {
        "days": counts, "first": first.isoformat(), "today": today_index, "max": max(counts),
        "total": sum(counts), "streak": streak, "activeDays": sum(1 for c in counts if c),
    }


def top_artists(db, now=None, days=30, limit=5):
    """Most played artists over the last `days` days."""
    now = time.time() if now is None else now
    return db.listening_stats(period_start=now - days * DAY, limit=limit)["artists"]


def _month_year(ts):
    return f"{datetime.date.fromtimestamp(ts):%b %Y}"
