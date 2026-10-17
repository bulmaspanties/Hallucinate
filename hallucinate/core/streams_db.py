"""Internet radio stations and podcasts, kept in their own small database (streams.db) next to the library's.

None of it touches the music library: stations and episodes never show up in songs, stats, history or recap.
Each row is small and the tables stay in the hundreds or low thousands, so the GUI thread may use it directly;
anything that needs the network happens elsewhere."""
import sqlite3
import time

SCHEMA = """
CREATE TABLE IF NOT EXISTS stations(
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    url TEXT NOT NULL,
    homepage TEXT NOT NULL DEFAULT '',
    favicon TEXT NOT NULL DEFAULT '',
    tags TEXT NOT NULL DEFAULT '',
    country TEXT NOT NULL DEFAULT '',
    codec TEXT NOT NULL DEFAULT '',
    bitrate INTEGER NOT NULL DEFAULT 0,
    uuid TEXT NOT NULL DEFAULT '',
    added REAL NOT NULL,
    last_played REAL NOT NULL DEFAULT 0,
    plays INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS podcasts(
    id INTEGER PRIMARY KEY,
    title TEXT NOT NULL,
    author TEXT NOT NULL DEFAULT '',
    feed_url TEXT NOT NULL DEFAULT '',
    folder TEXT NOT NULL DEFAULT '',
    link TEXT NOT NULL DEFAULT '',
    image TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    added REAL NOT NULL,
    checked REAL NOT NULL DEFAULT 0,
    error TEXT NOT NULL DEFAULT '',
    auto_download INTEGER NOT NULL DEFAULT 0,
    keep INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS episodes(
    id INTEGER PRIMARY KEY,
    podcast_id INTEGER NOT NULL REFERENCES podcasts(id) ON DELETE CASCADE,
    guid TEXT NOT NULL,
    title TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    url TEXT NOT NULL DEFAULT '',
    mime TEXT NOT NULL DEFAULT '',
    size INTEGER NOT NULL DEFAULT 0,
    published REAL NOT NULL DEFAULT 0,
    duration REAL NOT NULL DEFAULT 0,
    image TEXT NOT NULL DEFAULT '',
    chapters_url TEXT NOT NULL DEFAULT '',
    local_path TEXT NOT NULL DEFAULT '',
    position REAL NOT NULL DEFAULT 0,
    played INTEGER NOT NULL DEFAULT 0,
    played_at REAL NOT NULL DEFAULT 0,
    UNIQUE(podcast_id, guid)
);
CREATE INDEX IF NOT EXISTS idx_episodes_podcast ON episodes(podcast_id, published);
-- What a show's tile counts (episodes, unplayed, latest) and the top search's title match, read from these
-- alone instead of every episode's notes.
CREATE INDEX IF NOT EXISTS idx_episodes_counts ON episodes(podcast_id, played, published);
CREATE INDEX IF NOT EXISTS idx_episodes_titles ON episodes(published, title);
-- Songs heard on the radio (after a minute of each), newest last. The station's name is kept so the log still
-- reads right after the station is removed.
CREATE TABLE IF NOT EXISTS radio_log(
    id INTEGER PRIMARY KEY,
    ts REAL NOT NULL,
    station_id INTEGER NOT NULL DEFAULT 0,
    station TEXT NOT NULL DEFAULT '',
    artist TEXT NOT NULL DEFAULT '',
    title TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_radio_log_ts ON radio_log(ts);
-- Time spent listening, per station or show and day: kind is "station" or "podcast", day is YYYY-MM-DD.
CREATE TABLE IF NOT EXISTS listen_time(
    kind TEXT NOT NULL,
    item_id INTEGER NOT NULL,
    name TEXT NOT NULL DEFAULT '',
    day TEXT NOT NULL,
    seconds REAL NOT NULL DEFAULT 0,
    PRIMARY KEY(kind, item_id, day)
);
"""

STATION_FIELDS = ("name", "url", "homepage", "favicon", "tags", "country", "codec", "bitrate", "uuid")
PODCAST_FIELDS = ("title", "author", "feed_url", "folder", "link", "image", "description")
EPISODE_FIELDS = ("guid", "title", "description", "url", "mime", "size", "published", "duration", "image",
                  "chapters_url", "local_path")


class StreamsDB:
    def __init__(self, path):
        self.conn = sqlite3.connect(str(path), timeout=30, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.executescript(SCHEMA)
        self._migrate()
        self.conn.commit()

    def _migrate(self):
        ecols = {r["name"] for r in self.conn.execute("PRAGMA table_info(episodes)")}
        if "up_next" not in ecols:  # its place in Up next (0: not in it)
            self.conn.execute("ALTER TABLE episodes ADD COLUMN up_next REAL NOT NULL DEFAULT 0")
        cols = {r["name"] for r in self.conn.execute("PRAGMA table_info(podcasts)")}
        for name, kind in (("newest_first", "INTEGER NOT NULL DEFAULT 1"), ("hide_played", "INTEGER NOT NULL DEFAULT 0"),
                           ("speed", "REAL NOT NULL DEFAULT 0"), ("skip_intro", "INTEGER NOT NULL DEFAULT 0"),
                           ("skip_outro", "INTEGER NOT NULL DEFAULT 0")):
            if name not in cols:
                self.conn.execute(f"ALTER TABLE podcasts ADD COLUMN {name} {kind}")

    # --- what you've listened to -------------------------------------------------------------------------
    def log_radio_song(self, station_id, station, artist, title, ts=None):
        """A song heard on a station. The same song logged again within ten minutes (a stream repeating its
        title) is ignored."""
        ts = time.time() if ts is None else ts
        last = self.conn.execute("SELECT artist, title, ts FROM radio_log WHERE station_id=? ORDER BY ts DESC LIMIT 1",
                                 (station_id,)).fetchone()
        if last and last["artist"] == artist and last["title"] == title and ts - last["ts"] < 600:
            return
        self.conn.execute("INSERT INTO radio_log(ts, station_id, station, artist, title) VALUES(?, ?, ?, ?, ?)",
                          (ts, station_id, station, artist, title))
        self.conn.commit()

    def radio_log(self, limit=200, text="", station_id=0):
        where, params = [], []
        for word in (text or "").split():
            where.append("(artist || ' ' || title || ' ' || station) LIKE ?")
            params.append(f"%{word}%")
        if station_id:
            where.append("station_id=?")
            params.append(station_id)
        sql = "SELECT * FROM radio_log" + (" WHERE " + " AND ".join(where) if where else "")
        return [dict(r) for r in self.conn.execute(sql + " ORDER BY ts DESC LIMIT ?", (*params, limit))]

    def remove_radio_log(self, entry_id=0):
        """Remove one logged song, or (with no id) the whole log."""
        if entry_id:
            self.conn.execute("DELETE FROM radio_log WHERE id=?", (entry_id,))
        else:
            self.conn.execute("DELETE FROM radio_log")
        self.conn.commit()

    def add_listen_time(self, kind, item_id, name, seconds, ts=None):
        day = time.strftime("%Y-%m-%d", time.localtime(time.time() if ts is None else ts))
        self.conn.execute(
            "INSERT INTO listen_time(kind, item_id, name, day, seconds) VALUES(?, ?, ?, ?, ?) "
            "ON CONFLICT(kind, item_id, day) DO UPDATE SET seconds=seconds+excluded.seconds, name=excluded.name",
            (kind, item_id, name, day, float(seconds)))
        self.conn.commit()

    def listening(self, kind, days=0, limit=5):
        """Time spent on stations or shows: {"seconds", "top": [{item_id, name, seconds}]} for the last `days`
        days (0: all time)."""
        since = time.strftime("%Y-%m-%d", time.localtime(time.time() - (days - 1) * 86400)) if days else ""
        params = (kind, since)
        total = self.conn.execute("SELECT COALESCE(SUM(seconds), 0) FROM listen_time WHERE kind=? AND day>=?",
                                  params).fetchone()[0]
        top = [dict(r) for r in self.conn.execute(
            "SELECT item_id, MAX(name) AS name, SUM(seconds) AS seconds FROM listen_time WHERE kind=? AND day>=? "
            "GROUP BY item_id ORDER BY seconds DESC LIMIT ?", (*params, limit))]
        return {"seconds": float(total), "top": top}

    def radio_songs_heard(self, days=0):
        since = time.time() - days * 86400 if days else 0
        return self.conn.execute("SELECT COUNT(*) FROM radio_log WHERE ts>=?", (since,)).fetchone()[0]

    def episodes_finished(self, days=0):
        since = time.time() - days * 86400 if days else 0
        return self.conn.execute("SELECT COUNT(*) FROM episodes WHERE played=1 AND played_at>=?", (since,)).fetchone()[0]

    def close(self):
        self.conn.close()

    # --- stations --------------------------------------------------------------------------------------
    def stations(self):
        return [dict(r) for r in self.conn.execute("SELECT * FROM stations ORDER BY name COLLATE NOCASE")]

    def station(self, station_id):
        row = self.conn.execute("SELECT * FROM stations WHERE id=?", (station_id,)).fetchone()
        return dict(row) if row else None

    def station_by_url(self, url):
        row = self.conn.execute("SELECT * FROM stations WHERE url=?", (url,)).fetchone()
        return dict(row) if row else None

    def add_station(self, info):
        """Save a station (or, if its stream is already saved, return that one). Returns its id."""
        existing = self.station_by_url(info["url"])
        if existing:
            return existing["id"]
        from . import net
        from .stations import web_homepage

        if not net.is_web_url(info.get("url")):
            raise ValueError("A station's stream is a web link")
        fields = {k: info.get(k) or ("" if k != "bitrate" else 0) for k in STATION_FIELDS}
        for k in STATION_FIELDS:  # text stays text and numbers numbers, wherever the station came from
            fields[k] = (fields[k] if isinstance(fields[k], int) else 0) if k == "bitrate" else str(fields[k])
        fields["name"] = (fields["name"] or info["url"]).strip()
        fields["homepage"] = web_homepage(fields["homepage"])
        fields["favicon"] = fields["favicon"] if net.is_web_url(fields["favicon"]) else ""
        cur = self.conn.execute(
            f"INSERT INTO stations({', '.join(fields)}, added) VALUES ({', '.join('?' * len(fields))}, ?)",
            (*fields.values(), time.time()))
        self.conn.commit()
        return cur.lastrowid

    def update_station(self, station_id, **fields):
        fields = {k: v for k, v in fields.items() if k in STATION_FIELDS}
        if fields:
            sets = ", ".join(f"{k}=?" for k in fields)
            self.conn.execute(f"UPDATE stations SET {sets} WHERE id=?", (*fields.values(), station_id))
            self.conn.commit()

    def remove_station(self, station_id):
        self.conn.execute("DELETE FROM stations WHERE id=?", (station_id,))
        self.conn.commit()

    def station_played(self, station_id):
        self.conn.execute("UPDATE stations SET last_played=?, plays=plays+1 WHERE id=?", (time.time(), station_id))
        self.conn.commit()

    # --- podcasts --------------------------------------------------------------------------------------
    def podcasts(self):
        return [dict(r) for r in self.conn.execute(
            "SELECT p.*, COALESCE(a.unplayed, 0) AS unplayed, a.latest AS latest, COALESCE(a.n, 0) AS episodes "
            "FROM podcasts p LEFT JOIN (SELECT podcast_id, SUM(played=0) AS unplayed, MAX(published) AS latest, "
            "COUNT(*) AS n FROM episodes GROUP BY podcast_id) a ON a.podcast_id=p.id "
            "ORDER BY latest DESC, p.title COLLATE NOCASE")]

    def podcast(self, podcast_id):
        row = self.conn.execute("SELECT * FROM podcasts WHERE id=?", (podcast_id,)).fetchone()
        return dict(row) if row else None

    def podcast_by(self, feed_url="", folder=""):
        if feed_url:
            row = self.conn.execute("SELECT * FROM podcasts WHERE feed_url=?", (feed_url,)).fetchone()
        else:
            row = self.conn.execute("SELECT * FROM podcasts WHERE folder=? AND folder<>''", (folder,)).fetchone()
        return dict(row) if row else None

    def add_podcast(self, info):
        existing = self.podcast_by(info.get("feed_url", ""), info.get("folder", ""))
        if existing:
            return existing["id"]
        fields = {k: info.get(k) or "" for k in PODCAST_FIELDS}
        fields["title"] = fields["title"] or fields["feed_url"] or fields["folder"]
        cur = self.conn.execute(
            f"INSERT INTO podcasts({', '.join(fields)}, added) VALUES ({', '.join('?' * len(fields))}, ?)",
            (*fields.values(), time.time()))
        self.conn.commit()
        return cur.lastrowid

    def update_podcast(self, podcast_id, **fields):
        allowed = set(PODCAST_FIELDS) | {"checked", "error", "auto_download", "keep", "newest_first", "hide_played",
                                         "speed", "skip_intro", "skip_outro"}
        fields = {k: v for k, v in fields.items() if k in allowed}
        if fields:
            sets = ", ".join(f"{k}=?" for k in fields)
            self.conn.execute(f"UPDATE podcasts SET {sets} WHERE id=?", (*fields.values(), podcast_id))
            self.conn.commit()

    def remove_podcast(self, podcast_id):
        self.conn.execute("DELETE FROM podcasts WHERE id=?", (podcast_id,))
        self.conn.commit()

    # --- episodes --------------------------------------------------------------------------------------
    def merge_episodes(self, podcast_id, episodes):
        """Add new episodes and refresh what the feed says about known ones, keeping what's ours (where you
        stopped, played, the downloaded file). Returns the ids of the episodes that are new."""
        new = []
        names = [k for k in EPISODE_FIELDS if k != "local_path"]
        # What's known already, read in one go: an episode the feed says nothing new about isn't written
        # (a refresh of a long feed that hasn't changed then costs next to nothing).
        known = {r["guid"]: r for r in self.conn.execute(
            f"SELECT id, {', '.join(names)} FROM episodes WHERE podcast_id=?", (podcast_id,))}
        for ep in episodes:
            fields = {k: ep.get(k) if ep.get(k) is not None else ("" if k not in ("size", "published", "duration") else 0)
                      for k in names}
            if not fields["guid"]:
                continue
            row = known.get(fields["guid"])
            if row:
                changed = {k: v for k, v in fields.items() if k != "guid" and row[k] != v}
                if changed:
                    sets = ", ".join(f"{k}=?" for k in changed)
                    self.conn.execute(f"UPDATE episodes SET {sets} WHERE id=?", (*changed.values(), row["id"]))
            else:
                if ep.get("local_path"):
                    fields["local_path"] = ep["local_path"]
                cur = self.conn.execute(
                    f"INSERT INTO episodes(podcast_id, {', '.join(fields)}) VALUES (?, {', '.join('?' * len(fields))})",
                    (podcast_id, *fields.values()))
                new.append(cur.lastrowid)
                known[fields["guid"]] = {"id": cur.lastrowid, **fields}  # a feed listing it twice: once
        self.conn.commit()
        return new

    def episodes(self, podcast_id=None, unplayed_only=False, limit=None, oldest_first=False, text="",
                 titles_only=False):
        sql = ("SELECT e.*, p.title AS podcast, p.image AS podcast_image FROM episodes e "
               "JOIN podcasts p ON p.id=e.podcast_id")
        where, args = [], []
        if podcast_id is not None:
            where.append("e.podcast_id=?")
            args.append(podcast_id)
        if unplayed_only:
            where.append("e.played=0")
        for word in (text or "").split():
            pattern = "%" + word.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
            if titles_only:  # the top search: quick even across tens of thousands of episodes
                where.append("e.title LIKE ? ESCAPE '\\'")
                args.append(pattern)
            else:
                where.append("(e.title LIKE ? ESCAPE '\\' OR e.description LIKE ? ESCAPE '\\')")
                args += [pattern, pattern]
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY e.published ASC, e.id ASC" if oldest_first else " ORDER BY e.published DESC, e.id DESC"
        if limit:
            sql += f" LIMIT {int(limit)}"
        return [dict(r) for r in self.conn.execute(sql, args)]

    def episode(self, episode_id):
        row = self.conn.execute(
            "SELECT e.*, p.title AS podcast, p.image AS podcast_image FROM episodes e "
            "JOIN podcasts p ON p.id=e.podcast_id WHERE e.id=?", (episode_id,)).fetchone()
        return dict(row) if row else None

    def in_progress(self, limit=20):
        """Episodes started and not finished, most recently listened first."""
        return [dict(r) for r in self.conn.execute(
            "SELECT e.*, p.title AS podcast, p.image AS podcast_image FROM episodes e "
            "JOIN podcasts p ON p.id=e.podcast_id WHERE e.played=0 AND e.position>0 "
            "ORDER BY e.played_at DESC LIMIT ?", (limit,))]

    def set_position(self, episode_id, seconds):
        self.conn.execute("UPDATE episodes SET position=?, played_at=? WHERE id=?",
                          (max(0.0, float(seconds)), time.time(), episode_id))
        self.conn.commit()

    def set_played(self, episode_ids, played=True):
        ids = list(episode_ids)
        if not ids:
            return
        marks = ",".join("?" * len(ids))
        self.conn.execute(f"UPDATE episodes SET played=?, position=0, played_at=?{', up_next=0' if played else ''} "
                          f"WHERE id IN ({marks})", (1 if played else 0, time.time(), *ids))
        self.conn.commit()

    def up_next(self):
        return [dict(r) for r in self.conn.execute(
            "SELECT e.*, p.title AS podcast, p.image AS podcast_image FROM episodes e "
            "JOIN podcasts p ON p.id=e.podcast_id WHERE e.up_next>0 ORDER BY e.up_next")]

    def set_up_next(self, episode_id, on, first=False):
        if not on:
            self.conn.execute("UPDATE episodes SET up_next=0 WHERE id=?", (episode_id,))
        else:
            row = self.conn.execute("SELECT MIN(up_next), MAX(up_next) FROM episodes WHERE up_next>0").fetchone()
            lo, hi = row[0] or 1.0, row[1] or 0.0
            self.conn.execute("UPDATE episodes SET up_next=? WHERE id=?", (lo / 2 if first else hi + 1, episode_id))
        self.conn.commit()

    def set_local_path(self, episode_id, path):
        self.conn.execute("UPDATE episodes SET local_path=? WHERE id=?", (path or "", episode_id))
        self.conn.commit()

    def downloaded(self, podcast_id=None):
        sql = "SELECT * FROM episodes WHERE local_path<>''"
        args = ()
        if podcast_id is not None:
            sql += " AND podcast_id=?"
            args = (podcast_id,)
        return [dict(r) for r in self.conn.execute(sql, args)]
