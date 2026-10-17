"""Your own data in one file, to keep safe or carry to another computer: likes, ratings, playlists (plain and
smart), play counts, skips, every listen, songs taken out of the library, music folders, stations, podcast
subscriptions with where you were in each episode, Up next, the songs heard on the radio and the time spent on
stations and shows.

The music itself, covers and caches aren't in it: they come back from your folders. Restoring merges into what
is already there (nothing is deleted); songs are matched by path, so a backup restored on a computer where the
music lives elsewhere keeps the history but can't attach likes to files it can't find."""
import gzip
import json
import sqlite3
import time

from .. import __version__
from .atomic import write_atomic

FORMAT = "hallucinate-backup"
VERSION = 1
LIBRARY_TABLES = {
    "folders": ("path",),
    "hidden": ("path", "hidden_at"),
    "likes": ("path", "liked_at"),
    "ratings": ("path", "stars", "rated_at"),
    "plays": ("path", "count", "last"),
    "skips": ("path", "count", "last"),
    "play_log": ("ts", "path", "artist", "title", "album", "duration", "source", "s_artist", "s_title", "s_album"),
    "smart_playlists": ("name", "rules", "created"),
}
STATION_COLUMNS = ("name", "url", "homepage", "favicon", "tags", "country", "codec", "bitrate", "uuid", "added",
                   "last_played", "plays")
PODCAST_COLUMNS = ("title", "author", "feed_url", "folder", "link", "image", "description", "added", "auto_download",
                   "newest_first", "hide_played", "speed", "skip_intro", "skip_outro")
EPISODE_STATE = ("guid", "title", "url", "published", "duration", "position", "played", "played_at", "up_next")


def _rows(conn, table, columns):
    have = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
    cols = [c for c in columns if c in have]
    if not cols:
        return []
    return [dict(zip(cols, r)) for r in conn.execute(f"SELECT {', '.join(cols)} FROM {table}")]


def export(library_db, streams_db, target):
    """Write a backup of the two databases' user data to `target` (gzipped JSON). Returns a summary dict."""
    data = {"format": FORMAT, "version": VERSION, "app": __version__, "created": time.time()}
    lib = sqlite3.connect(str(library_db))
    try:
        for table, cols in LIBRARY_TABLES.items():
            data[table] = _rows(lib, table, cols)
        data["playlists"] = [
            {"name": name, "created": created,
             "paths": [r[0] for r in lib.execute("SELECT path FROM playlist_items WHERE playlist_id=? ORDER BY pos", (pid,))]}
            for pid, name, created in lib.execute("SELECT id, name, created FROM playlists ORDER BY id")
        ]
    finally:
        lib.close()
    data["stations"], data["podcasts"] = [], []
    if streams_db is not None:
        st = sqlite3.connect(str(streams_db))
        try:
            data["stations"] = _rows(st, "stations", STATION_COLUMNS)
            data["radio_log"] = _rows(st, "radio_log", ("ts", "station", "artist", "title"))
            data["listen_time"] = _rows(st, "listen_time", ("kind", "name", "day", "seconds"))
            for row in st.execute("SELECT id FROM podcasts"):
                pid = row[0]
                podcast = dict(zip(PODCAST_COLUMNS, st.execute(
                    f"SELECT {', '.join(PODCAST_COLUMNS)} FROM podcasts WHERE id=?", (pid,)).fetchone()))
                cols = ", ".join(EPISODE_STATE)
                podcast["episodes"] = [dict(zip(EPISODE_STATE, r)) for r in st.execute(
                    f"SELECT {cols} FROM episodes WHERE podcast_id=? AND (played=1 OR position>0 OR up_next>0)", (pid,))]
                data["podcasts"].append(podcast)
        except sqlite3.OperationalError:
            pass
        finally:
            st.close()
    payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
    write_atomic(target, lambda f: f.write(gzip.compress(payload)), private=True)
    return summary(data)



def summary(data):
    return {"likes": len(data.get("likes", [])), "ratings": sum(1 for r in data.get("ratings", []) if r.get("stars")),
            "playlists": len(data.get("playlists", [])) + len(data.get("smart_playlists", [])),
            "listens": len(data.get("play_log", [])), "stations": len(data.get("stations", [])),
            "podcasts": len(data.get("podcasts", []))}


MAX_BYTES = 64 * 1024 * 1024  # decompressed; years of listening is a few MB, so this is only a bomb's limit
S, N, I = "str", "num", "int"
# What each row of a backup may hold: (field, kind, required). Anything else in a row is ignored, and a row
# missing a required field or holding the wrong kind of value is skipped, so a damaged or crafted file can
# neither crash a restore half-way nor smuggle odd values into the databases.
ROWS = {
    "folders": [("path", S, True)],
    "hidden": [("path", S, True), ("hidden_at", N, False)],
    "likes": [("path", S, True), ("liked_at", N, False)],
    "ratings": [("path", S, True), ("stars", I, True), ("rated_at", N, False)],
    "plays": [("path", S, True), ("count", I, True), ("last", N, False)],
    "skips": [("path", S, True), ("count", I, True), ("last", N, False)],
    "play_log": [("ts", N, True), ("path", S, True), ("artist", S, False), ("title", S, False), ("album", S, False),
                 ("duration", N, False), ("source", S, False), ("s_artist", S, False), ("s_title", S, False),
                 ("s_album", S, False)],
    "smart_playlists": [("name", S, True), ("rules", S, True), ("created", N, False)],
    "playlists": [("name", S, True), ("created", N, False), ("paths", "paths", False)],
    "stations": [(c, I if c in ("bitrate", "plays") else N if c in ("added", "last_played") else S, c == "url")
                 for c in STATION_COLUMNS],
    "radio_log": [("ts", N, True), ("station", S, False), ("artist", S, False), ("title", S, False)],
    "listen_time": [("kind", S, True), ("name", S, True), ("day", S, True), ("seconds", N, True)],
    "podcasts": [(c, N if c in ("added", "speed") else I if c in (
        "auto_download", "newest_first", "hide_played", "skip_intro", "skip_outro") else S, c == "title")
        for c in PODCAST_COLUMNS] + [("episodes", "episodes", False)],
}
EPISODE_ROW = [("guid", S, True), ("title", S, False), ("url", S, False), ("published", N, False),
               ("duration", N, False), ("position", N, False), ("played", I, False), ("played_at", N, False),
               ("up_next", N, False)]


def _value(value, kind):
    import math

    if kind == S:
        return value[:10_000] if isinstance(value, str) else None
    if kind in (N, I):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            return None
        return int(value) if kind == I else float(value)
    if kind == "paths":
        return [p for p in value if isinstance(p, str)] if isinstance(value, list) else None
    if kind == "episodes":
        return [r for r in (_row(e, EPISODE_ROW) for e in value) if r] if isinstance(value, list) else None
    return None


def _row(raw, spec):
    if not isinstance(raw, dict):
        return None
    row = {}
    for field, kind, required in spec:
        value = _value(raw.get(field), kind) if field in raw else None
        if value is None:
            if required:
                return None
            continue
        row[field] = value
    return row


def clean(data):
    """A backup's contents with every row checked against ROWS (see there)."""
    out = {k: data.get(k) for k in ("format", "version", "app", "created")}
    for key, spec in ROWS.items():
        rows = data.get(key)
        out[key] = [r for r in (_row(x, spec) for x in rows) if r] if isinstance(rows, list) else []
    from . import net

    out["stations"] = [s for s in out["stations"] if net.is_web_url(s["url"])]
    for p in out["podcasts"]:
        p.setdefault("episodes", [])
        for e in p["episodes"]:
            if e.get("url") and not net.is_web_url(e["url"]):
                e["url"] = ""
    for r in out["ratings"]:
        r["stars"] = max(0, min(5, r["stars"]))
    return out


def read(source):
    """The backup in `source`; raises ValueError for anything that isn't one."""
    try:
        with gzip.open(source, "rb") as f:
            raw = f.read(MAX_BYTES + 1)
    except (OSError, EOFError) as exc:
        raise ValueError(f"That isn't a Hallucinate backup ({exc})") from exc
    if len(raw) > MAX_BYTES:
        raise ValueError("That backup is far bigger than any real one")
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeError, ValueError) as exc:
        raise ValueError("That isn't a Hallucinate backup") from exc
    if not isinstance(data, dict) or data.get("format") != FORMAT:
        raise ValueError("That isn't a Hallucinate backup")
    version = data.get("version", 0)
    if not isinstance(version, int) or isinstance(version, bool):
        raise ValueError("That isn't a Hallucinate backup")
    if version > VERSION:
        raise ValueError("That backup is from a newer Hallucinate; update to restore it")
    return clean(data)


def restore(data, library_db, streams_db):
    """Merge a backup into the databases. Existing likes, ratings and positions win only where the backup has
    nothing; counts take the larger value; playlists with the same name gain the backup's missing songs."""
    data = clean(data)
    lib = sqlite3.connect(str(library_db))
    try:
        cur = lib.cursor()
        for r in data.get("folders", []):
            cur.execute("INSERT OR IGNORE INTO folders(path) VALUES(?)", (r["path"],))
        for r in data.get("hidden", []):
            cur.execute("INSERT OR IGNORE INTO hidden(path, hidden_at) VALUES(?, ?)", (r["path"], r.get("hidden_at", 0)))
        for r in data.get("likes", []):
            cur.execute("INSERT OR IGNORE INTO likes(path, liked_at) VALUES(?, ?)", (r["path"], r.get("liked_at", 0)))
        for r in data.get("ratings", []):
            cur.execute("INSERT OR IGNORE INTO ratings(path, stars, rated_at) VALUES(?, ?, ?)",  # yours win
                        (r["path"], r["stars"], r.get("rated_at", 0)))
        for table in ("plays", "skips"):
            for r in data.get(table, []):
                cur.execute(f"INSERT INTO {table}(path, count, last) VALUES(?, ?, ?) ON CONFLICT(path) DO UPDATE SET "
                            "count=MAX(count, excluded.count), last=MAX(last, excluded.last)",
                            (r["path"], r["count"], r.get("last", 0)))
        log_cols = LIBRARY_TABLES["play_log"]
        for r in data.get("play_log", []):
            cur.execute(f"INSERT OR IGNORE INTO play_log({', '.join(log_cols)}) VALUES({', '.join('?' * len(log_cols))})",
                        tuple(r.get(c, "" if c not in ("ts", "duration") else 0) for c in log_cols))
        for r in data.get("smart_playlists", []):
            if not cur.execute("SELECT 1 FROM smart_playlists WHERE name=?", (r["name"],)).fetchone():
                cur.execute("INSERT INTO smart_playlists(name, rules, created) VALUES(?, ?, ?)",
                            (r["name"], r["rules"], r.get("created", time.time())))
        for p in data.get("playlists", []):
            row = cur.execute("SELECT id FROM playlists WHERE name=?", (p["name"],)).fetchone()
            pid = row[0] if row else cur.execute("INSERT INTO playlists(name, created) VALUES(?, ?)",
                                                 (p["name"], p.get("created", time.time()))).lastrowid
            have = {r[0] for r in cur.execute("SELECT path FROM playlist_items WHERE playlist_id=?", (pid,))}
            pos = cur.execute("SELECT COALESCE(MAX(pos), -1) FROM playlist_items WHERE playlist_id=?", (pid,)).fetchone()[0]
            for path in p.get("paths", []):
                if path not in have:
                    pos += 1
                    cur.execute("INSERT INTO playlist_items(playlist_id, path, pos) VALUES(?, ?, ?)", (pid, path, pos))
        lib.commit()
    finally:
        lib.close()
    if streams_db is not None:
        from .streams_db import StreamsDB

        st = StreamsDB(streams_db)
        try:
            for s in data.get("stations", []):
                if not st.station_by_url(s["url"]):
                    sid = st.add_station(s)
                    st.conn.execute("UPDATE stations SET added=?, last_played=?, plays=? WHERE id=?",
                                    (s.get("added") or time.time(), s.get("last_played") or 0, s.get("plays") or 0, sid))
            station_ids = {s["name"]: s["id"] for s in st.stations()}
            have = {(r["ts"], r["artist"], r["title"]) for r in st.radio_log(limit=10_000_000)}
            for r in data.get("radio_log", []):
                if (r["ts"], r.get("artist", ""), r.get("title", "")) not in have:
                    st.conn.execute("INSERT INTO radio_log(ts, station_id, station, artist, title) VALUES(?, ?, ?, ?, ?)",
                                    (r["ts"], station_ids.get(r.get("station", ""), 0), r.get("station", ""),
                                     r.get("artist", ""), r.get("title", "")))
            show_ids = {p["title"]: p["id"] for p in st.podcasts()}
            for p in data.get("podcasts", []):
                show_ids.setdefault(p["title"], st.add_podcast(p))
            for t in data.get("listen_time", []):
                item = (station_ids if t["kind"] == "station" else show_ids).get(t["name"])
                if item:  # the larger of the two days' counts, so restoring twice adds nothing
                    st.conn.execute(
                        "INSERT INTO listen_time(kind, item_id, name, day, seconds) VALUES(?, ?, ?, ?, ?) "
                        "ON CONFLICT(kind, item_id, day) DO UPDATE SET seconds=MAX(seconds, excluded.seconds)",
                        (t["kind"], item, t["name"], t["day"], t["seconds"]))
            for p in data.get("podcasts", []):
                pid = st.add_podcast(p)
                st.update_podcast(pid, **{k: p[k] for k in ("auto_download", "newest_first", "hide_played", "speed",
                                                            "skip_intro", "skip_outro") if p.get(k) is not None})
                eps = p.get("episodes", [])
                st.merge_episodes(pid, [{k: e.get(k) for k in ("guid", "title", "url", "published", "duration")}
                                        for e in eps])
                for e in eps:
                    st.conn.execute(
                        "UPDATE episodes SET position=MAX(position, ?), played=MAX(played, ?), "
                        "played_at=MAX(played_at, ?), up_next=CASE WHEN up_next>0 THEN up_next ELSE ? END "
                        "WHERE podcast_id=? AND guid=?",
                        (e.get("position") or 0, e.get("played") or 0, e.get("played_at") or 0, e.get("up_next") or 0,
                         pid, e["guid"]))
            st.conn.commit()
        finally:
            st.close()
    return summary(data)
