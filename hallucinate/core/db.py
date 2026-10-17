"""SQLite library storage with FTS5-backed search."""
import re
import sqlite3
import time
import unicodedata
from typing import Iterable, Optional

from .remote import SQL_LOCAL

SCHEMA = """
CREATE TABLE IF NOT EXISTS tracks(
  id INTEGER PRIMARY KEY,
  path TEXT NOT NULL UNIQUE,
  mtime REAL NOT NULL,
  size INTEGER NOT NULL,
  title TEXT NOT NULL,
  artist TEXT NOT NULL,
  album_artist TEXT NOT NULL,
  aa_tag INTEGER NOT NULL DEFAULT 0,
  album TEXT NOT NULL,
  album_key TEXT NOT NULL,
  track_no INTEGER NOT NULL DEFAULT 0,
  disc_no INTEGER NOT NULL DEFAULT 0,
  year INTEGER NOT NULL DEFAULT 0,
  genre TEXT NOT NULL DEFAULT '',
  duration REAL NOT NULL DEFAULT 0,
  fmt TEXT NOT NULL DEFAULT '',
  codec TEXT NOT NULL DEFAULT '',
  bitrate INTEGER NOT NULL DEFAULT 0,
  sample_rate INTEGER NOT NULL DEFAULT 0,
  art TEXT,
  rg_track REAL,
  rg_album REAL,
  rg_peak REAL,
  added REAL NOT NULL,
  s_title TEXT NOT NULL DEFAULT '',
  s_album TEXT NOT NULL DEFAULT '',
  s_aa TEXT NOT NULL DEFAULT '',
  s_artist TEXT NOT NULL DEFAULT '',
  file TEXT,
  cue_start REAL NOT NULL DEFAULT 0,
  cue_end REAL NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_tracks_album ON tracks(album_key);
CREATE TABLE IF NOT EXISTS folders(path TEXT PRIMARY KEY);
-- files removed from the library on purpose: rescans leave them out until they're restored
CREATE TABLE IF NOT EXISTS hidden(path TEXT PRIMARY KEY, hidden_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS likes(path TEXT PRIMARY KEY, liked_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS ratings(path TEXT PRIMARY KEY, stars INTEGER NOT NULL, rated_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS playlists(id INTEGER PRIMARY KEY, name TEXT NOT NULL, created REAL NOT NULL);
CREATE TABLE IF NOT EXISTS playlist_items(
  id INTEGER PRIMARY KEY, playlist_id INTEGER NOT NULL REFERENCES playlists(id) ON DELETE CASCADE,
  path TEXT NOT NULL, pos INTEGER NOT NULL);
CREATE INDEX IF NOT EXISTS idx_pl_items ON playlist_items(playlist_id, pos);
CREATE TABLE IF NOT EXISTS smart_playlists(id INTEGER PRIMARY KEY, name TEXT NOT NULL, rules TEXT NOT NULL,
  created REAL NOT NULL);
CREATE TABLE IF NOT EXISTS plays(path TEXT PRIMARY KEY, count INTEGER NOT NULL, last REAL NOT NULL);
CREATE TABLE IF NOT EXISTS skips(path TEXT PRIMARY KEY, count INTEGER NOT NULL, last REAL NOT NULL);
CREATE TABLE IF NOT EXISTS play_log(
  id INTEGER PRIMARY KEY, ts REAL NOT NULL, path TEXT, artist TEXT NOT NULL DEFAULT '',
  title TEXT NOT NULL DEFAULT '', album TEXT NOT NULL DEFAULT '', duration REAL NOT NULL DEFAULT 0,
  source TEXT NOT NULL DEFAULT 'local',
  s_artist TEXT NOT NULL DEFAULT '', s_title TEXT NOT NULL DEFAULT '', s_album TEXT NOT NULL DEFAULT '',
  UNIQUE(ts, artist, title));
CREATE INDEX IF NOT EXISTS idx_play_log_ts ON play_log(ts);
CREATE TABLE IF NOT EXISTS loudness(path TEXT PRIMARY KEY, mtime REAL NOT NULL, size INTEGER NOT NULL,
  track_gain REAL, album_gain REAL, peak REAL, measured REAL NOT NULL);
CREATE TABLE IF NOT EXISTS album_colors(album_key TEXT PRIMARY KEY, art TEXT NOT NULL, color TEXT NOT NULL,
  hue REAL NOT NULL, sat REAL NOT NULL, val REAL NOT NULL);
CREATE TABLE IF NOT EXISTS lyrics(path TEXT PRIMARY KEY, synced TEXT NOT NULL DEFAULT '',
  plain TEXT NOT NULL DEFAULT '', source TEXT NOT NULL DEFAULT '', fetched REAL NOT NULL);
-- a cover you chose for an album: it stays, whatever the files' own pictures are
CREATE TABLE IF NOT EXISTS chosen_art(album_key TEXT PRIMARY KEY, art TEXT NOT NULL, chosen_at REAL NOT NULL);
"""

FTS = (
    "CREATE VIRTUAL TABLE IF NOT EXISTS tracks_fts USING fts5("
    "title, artist, album, tokenize='unicode61 remove_diacritics 2')"
)

COLS = (
    "path mtime size title artist album_artist aa_tag album album_key track_no disc_no "
    "year genre duration fmt codec bitrate sample_rate art rg_track rg_album rg_peak file cue_start cue_end"
).split()

# Folded copies (see fold) kept beside the originals, so queries never call the Python fold() per row: from
# inside SQLite each call must take the GIL, which crawls whenever another thread is busy (a big library).
SEARCH_COLS = ["s_title", "s_album", "s_aa", "s_artist", "s_genre"]

_ORDER = "disc_no, track_no, s_title"


def _like(token: str) -> str:
    return "%" + token.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def _like_prefix(text: str) -> str:
    """`text` escaped for use at the start of a LIKE pattern (with ESCAPE '\\')."""
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def fold(s: str) -> str:
    """Case- and accent-insensitive form used for searching and sorting (all scripts)."""
    s = unicodedata.normalize("NFKD", (s or "").casefold())
    return "".join(c for c in s if not unicodedata.combining(c))


def _tokens(q: str) -> list:
    return re.findall(r"\w+", fold(q))


def group_index(albums, artists):
    """Folded names for searching albums and artists in memory (see search_groups)."""
    return ([(fold(a.get("album") or ""), fold(a.get("album_artist") or ""), a) for a in albums],
            [(fold(a.get("name") or ""), a) for a in artists])


def search_groups(index, query, album_limit=20, artist_limit=12):
    """Albums and artists matching `query`, from group_index(): the same rules as Database.search (every word
    in the album title or its artist; every word in the artist's name; names starting with the first word
    first), but over the few thousand albums and artists instead of every song: milliseconds rather than a
    scan of a quarter-million rows."""
    toks = _tokens(query)
    if not toks:
        return [], []
    albums_idx, artists_idx = index
    first = toks[0]
    albums = [(not album.startswith(first), album, row) for album, aa, row in albums_idx
              if all(t in album or t in aa for t in toks)]
    albums.sort(key=lambda x: (x[0], x[1]))
    artists = [(not name.startswith(first), name, row) for name, row in artists_idx if all(t in name for t in toks)]
    artists.sort(key=lambda x: (x[0], x[1]))
    return [r for *_, r in albums[:album_limit]], [r for *_, r in artists[:artist_limit]]


class Database:
    def __init__(self, path):
        self.conn = sqlite3.connect(str(path), timeout=30, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.create_function("fold", 1, fold, deterministic=True)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self.conn.executescript(SCHEMA)
        # All of an upgrade or none of it: a crash between adding a column and filling it in would otherwise
        # leave it half-done for good (SQLite's schema changes are transactional).
        self.conn.execute("BEGIN")
        try:
            self._migrate()
            self.conn.commit()
        except BaseException:
            self.conn.rollback()
            raise
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_tracks_stitle ON tracks(s_title)")
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_tracks_saa ON tracks(s_aa)")
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_tracks_sartist ON tracks(s_artist)")
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_play_log_sartist ON play_log(s_artist)")
        # a song's or album's own listens (album page "first played", radio, history edits) without a full scan
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_play_log_path ON play_log(path)")
        try:
            self.conn.execute(FTS)
            self.has_fts = True
        except sqlite3.OperationalError:
            self.has_fts = False
        self.conn.commit()

    def _migrate(self):
        cols = {r["name"] for r in self.conn.execute("PRAGMA table_info(tracks)")}
        if "rg_track" not in cols:
            for c in ("rg_track", "rg_album", "rg_peak"):
                self.conn.execute(f"ALTER TABLE tracks ADD COLUMN {c} REAL")
            # Zero mtime makes the next scan re-read every file so ReplayGain tags get picked up.
            self.conn.execute("UPDATE tracks SET mtime=0")
        if "rg_measured" not in cols:
            # 1 when the ReplayGain values came from Hallucinate's own analysis rather than the file's tags
            self.conn.execute("ALTER TABLE tracks ADD COLUMN rg_measured INTEGER NOT NULL DEFAULT 0")
        if "file" not in cols:
            # CUE sheet songs: the real audio file and where the song lies in it (cue_end 0: to the end)
            self.conn.execute("ALTER TABLE tracks ADD COLUMN file TEXT")
            self.conn.execute("ALTER TABLE tracks ADD COLUMN cue_start REAL NOT NULL DEFAULT 0")
            self.conn.execute("ALTER TABLE tracks ADD COLUMN cue_end REAL NOT NULL DEFAULT 0")
        if "codec" not in cols:
            self.conn.execute("ALTER TABLE tracks ADD COLUMN codec TEXT NOT NULL DEFAULT ''")
            self.conn.execute(
                """UPDATE tracks SET codec=CASE UPPER(fmt)
                     WHEN 'WAVE' THEN 'WAV' WHEN 'AIF' THEN 'AIFF' WHEN 'WV' THEN 'WAVPACK'
                     WHEN 'OGA' THEN 'OGG' ELSE UPPER(fmt) END"""
            )
            # These extensions can contain different codecs; re-read only the ambiguous files.
            self.conn.execute(
                "UPDATE tracks SET mtime=0 WHERE UPPER(fmt) IN ('M4A', 'M4B', 'MP4', 'OGG', 'OGA', 'MKA')"
            )
        if "s_genre" not in cols and "s_title" in cols:
            self.conn.execute("ALTER TABLE tracks ADD COLUMN s_genre TEXT NOT NULL DEFAULT ''")
            genres = [r[0] for r in self.conn.execute("SELECT DISTINCT genre FROM tracks WHERE genre != ''")]
            self.conn.executemany("UPDATE tracks SET s_genre=? WHERE genre=?", [(fold(g), g) for g in genres])
            cols.add("s_genre")
        missing = [c for c in SEARCH_COLS if c not in cols]
        if missing:
            for c in missing:
                self.conn.execute(f"ALTER TABLE tracks ADD COLUMN {c} TEXT NOT NULL DEFAULT ''")
            rows = self.conn.execute("SELECT id, title, artist, album, album_artist, genre FROM tracks").fetchall()
            self.conn.executemany(
                "UPDATE tracks SET s_title=?, s_album=?, s_aa=?, s_artist=?, s_genre=? WHERE id=?",
                [(fold(r["title"]), fold(r["album"]), fold(r["album_artist"]), fold(r["artist"]), fold(r["genre"]),
                  r["id"]) for r in rows],
            )
        log_cols = {r["name"] for r in self.conn.execute("PRAGMA table_info(play_log)")}
        if "duration" not in log_cols:
            self.conn.execute("ALTER TABLE play_log ADD COLUMN duration REAL NOT NULL DEFAULT 0")
            self.conn.execute(
                """UPDATE play_log SET duration=COALESCE(
                     (SELECT duration FROM tracks WHERE tracks.path=play_log.path), 0)
                   WHERE duration=0 AND path IS NOT NULL"""
            )
        if "s_artist" not in log_cols:
            # Folded copies make history, artist and stats queries index-friendly (fold() per row is slow).
            for c in ("s_artist", "s_title", "s_album"):
                self.conn.execute(f"ALTER TABLE play_log ADD COLUMN {c} TEXT NOT NULL DEFAULT ''")
            self.conn.execute("UPDATE play_log SET s_artist=fold(artist), s_title=fold(title), s_album=fold(album)")

    def close(self):
        self.conn.close()

    # --- user data: likes, playlists, play counts, lyrics cache ----------
    def liked_paths(self) -> set:
        return {r["path"] for r in self.conn.execute("SELECT path FROM likes")}

    def ratings(self) -> dict:
        return {r["path"]: r["stars"] for r in self.conn.execute("SELECT path, stars FROM ratings WHERE stars > 0")}

    def set_rating(self, path: str, stars: int):
        """1–5 stars; 0 clears the rating. A cleared rating is kept as 0 stars, so one left in the file's tags
        (by another player, or a file that can't be written) doesn't come back at the next scan."""
        stars = max(0, min(5, int(stars)))
        self.conn.execute("INSERT OR REPLACE INTO ratings(path, stars, rated_at) VALUES(?,?,?)",
                          (path, stars, time.time()))
        self.conn.commit()

    def set_liked(self, path: str, liked: bool):
        if liked:
            self.conn.execute("INSERT OR IGNORE INTO likes(path, liked_at) VALUES(?,?)", (path, time.time()))
        else:
            self.conn.execute("DELETE FROM likes WHERE path=?", (path,))
        self.conn.commit()

    def liked_tracks(self) -> list:
        return self._rows(
            "SELECT t.* FROM likes l JOIN tracks t ON t.path=l.path ORDER BY l.liked_at DESC, t.id DESC"
        )

    def playlists(self) -> list:
        return self._rows(
            "SELECT p.id, p.name, COUNT(t.id) AS n FROM playlists p "
            "LEFT JOIN playlist_items i ON i.playlist_id=p.id LEFT JOIN tracks t ON t.path=i.path "
            "GROUP BY p.id ORDER BY p.name COLLATE NOCASE"
        )

    def create_playlist(self, name: str) -> int:
        cur = self.conn.execute("INSERT INTO playlists(name, created) VALUES(?,?)", (name.strip() or "New playlist", time.time()))
        self.conn.commit()
        return cur.lastrowid

    def rename_playlist(self, pid: int, name: str):
        self.conn.execute("UPDATE playlists SET name=? WHERE id=?", (name.strip() or "Playlist", pid))
        self.conn.commit()

    def delete_playlist(self, pid: int):
        self.conn.execute("DELETE FROM playlist_items WHERE playlist_id=?", (pid,))
        self.conn.execute("DELETE FROM playlists WHERE id=?", (pid,))
        self.conn.commit()

    def playlist_add(self, pid: int, paths: list):
        pos = self.conn.execute("SELECT COALESCE(MAX(pos), -1) + 1 FROM playlist_items WHERE playlist_id=?", (pid,)).fetchone()[0]
        self.conn.executemany(
            "INSERT INTO playlist_items(playlist_id, path, pos) VALUES(?,?,?)",
            [(pid, p, pos + n) for n, p in enumerate(paths)],
        )
        self.conn.commit()

    def smart_playlists(self) -> list:
        return self._rows("SELECT id, name, rules FROM smart_playlists ORDER BY name COLLATE NOCASE, id")

    def smart_playlist(self, sid: int) -> Optional[dict]:
        rows = self._rows("SELECT id, name, rules FROM smart_playlists WHERE id=?", (sid,))
        return rows[0] if rows else None

    def create_smart_playlist(self, name: str, rules: str) -> int:
        cur = self.conn.execute(
            "INSERT INTO smart_playlists(name, rules, created) VALUES(?,?,?)", (name, rules, time.time()))
        self.conn.commit()
        return cur.lastrowid

    def update_smart_playlist(self, sid: int, name: str, rules: str):
        self.conn.execute("UPDATE smart_playlists SET name=?, rules=? WHERE id=?", (name, rules, sid))
        self.conn.commit()

    def delete_smart_playlist(self, sid: int):
        self.conn.execute("DELETE FROM smart_playlists WHERE id=?", (sid,))
        self.conn.commit()

    def playlist_tracks(self, pid: int) -> list:
        return self._rows(
            "SELECT t.*, i.id AS item_id FROM playlist_items i JOIN tracks t ON t.path=i.path "
            "WHERE i.playlist_id=? ORDER BY i.pos, i.id",
            (pid,),
        )

    def playlist_remove_item(self, item_id: int):
        self.conn.execute("DELETE FROM playlist_items WHERE id=?", (item_id,))
        self.conn.commit()

    def playlist_move(self, pid: int, src: int, dst: int):
        ids = [r["id"] for r in self.conn.execute(
            "SELECT i.id FROM playlist_items i JOIN tracks t ON t.path=i.path WHERE i.playlist_id=? ORDER BY i.pos, i.id", (pid,))]
        if not (0 <= src < len(ids) and 0 <= dst < len(ids)):
            return
        ids.insert(dst, ids.pop(src))
        self.conn.executemany("UPDATE playlist_items SET pos=? WHERE id=?", [(n, i) for n, i in enumerate(ids)])
        self.conn.commit()

    def record_skip(self, path: str, when: Optional[float] = None):
        self.conn.execute(
            "INSERT INTO skips(path, count, last) VALUES(?,1,?) "
            "ON CONFLICT(path) DO UPDATE SET count=count+1, last=excluded.last",
            (path, when or time.time()),
        )
        self.conn.commit()

    def skip_counts(self) -> dict:
        return {r[0]: r[1] for r in self.conn.execute("SELECT path, count FROM skips")}

    def record_play(self, path: str, when: Optional[float] = None):
        when = when or time.time()
        self.conn.execute(
            "INSERT OR IGNORE INTO play_log(ts, path, artist, title, album, duration, source, s_artist, s_title, s_album) "
            "SELECT ?, path, artist, title, album, duration, 'local', s_artist, s_title, s_album FROM tracks WHERE path=?",
            (when, path))
        self.conn.execute(
            "INSERT INTO plays(path, count, last) VALUES(?,1,?) "
            "ON CONFLICT(path) DO UPDATE SET count=count+1, last=excluded.last",
            (path, when),
        )
        self.conn.commit()

    def import_plays(self, items: Iterable[dict], source: str) -> dict:
        """Merge external listens ({ts, artist, title, album}); matched local tracks also bump `plays`."""
        added = matched = 0
        lookup = {}
        for r in self.conn.execute("SELECT path, artist, title, duration FROM tracks"):
            lookup.setdefault((fold(r["artist"]), fold(r["title"])), (r["path"], r["duration"]))
        for it in items:
            artist, title = (it.get("artist") or "").strip(), (it.get("title") or "").strip()
            try:
                ts = float(it.get("ts") or 0)
            except (TypeError, ValueError):
                continue
            if not artist or not title or ts <= 0:
                continue
            match = lookup.get((fold(artist), fold(title)))
            path = match[0] if match else None
            try:
                duration = match[1] if match else float(it.get("duration") or 0)
            except (TypeError, ValueError):
                duration = 0
            cur = self.conn.execute(
                "INSERT OR IGNORE INTO play_log(ts, path, artist, title, album, duration, source, s_artist, s_title, s_album) "
                "VALUES(?,?,?,?,?,?,?,?,?,?)",
                (ts, path, artist, title, it.get("album") or "", duration, source, fold(artist), fold(title),
                 fold(it.get("album") or "")))
            if not cur.rowcount:
                continue
            added += 1
            if path:
                matched += 1
                self.conn.execute(
                    "INSERT INTO plays(path, count, last) VALUES(?,1,?) "
                    "ON CONFLICT(path) DO UPDATE SET count=count+1, last=MAX(last, excluded.last)", (path, ts))
        self.conn.commit()
        return {"added": added, "matched": matched}

    def listening_stats(self, period_start=None, limit=10):
        params = () if period_start is None else (period_start,)
        where = "" if period_start is None else "WHERE l.ts >= ?"
        if period_start is None:
            artists = self._rows(
                """SELECT MIN(t.album_artist) AS name, SUM(p.count) AS plays,
                          COUNT(DISTINCT t.album_key) AS albums, COUNT(*) AS tracks, MAX(t.art) AS art
                   FROM plays p JOIN tracks t ON t.path=p.path
                   GROUP BY t.s_aa ORDER BY plays DESC, name COLLATE NOCASE LIMIT ?""",
                (limit,),
            )
            albums = self._rows(
                f"""{self._ALBUM_SQL.replace("FROM tracks", "FROM tracks t JOIN plays p ON p.path=t.path")}
                    GROUP BY t.album_key ORDER BY SUM(p.count) DESC LIMIT ?""",
                (limit,),
            )
            for row in albums:
                row["plays"] = self.conn.execute(
                    "SELECT SUM(count) FROM plays p JOIN tracks t ON t.path=p.path WHERE t.album_key=?",
                    (row["album_key"],),
                ).fetchone()[0]
            tracks = self._rows(
                """SELECT t.*, p.count AS plays FROM plays p JOIN tracks t ON t.path=p.path
                   ORDER BY p.count DESC, p.last DESC LIMIT ?""",
                (limit,),
            )
            listen_count = self.conn.execute("SELECT COALESCE(SUM(count),0) FROM plays").fetchone()[0]
        else:
            artists = self._rows(
                f"""SELECT MIN(l.artist) AS name, COUNT(*) AS plays, COUNT(DISTINCT l.album) AS albums,
                           COUNT(DISTINCT l.title) AS tracks, MAX(t.art) AS art
                    FROM play_log l LEFT JOIN tracks t ON t.path=l.path {where}
                    GROUP BY +l.s_artist ORDER BY plays DESC, name COLLATE NOCASE LIMIT ?""",
                (*params, limit),
            )
            albums = self._rows(
                f"""SELECT MAX(t.album_key) AS album_key, MIN(l.album) AS album, MIN(l.artist) AS album_artist,
                           MAX(t.year) AS year, COUNT(*) AS n, SUM(l.duration) AS duration,
                           MAX(t.art) AS art, MAX(l.ts) AS added, COUNT(*) AS plays
                    FROM play_log l LEFT JOIN tracks t ON t.path=l.path {where}
                    GROUP BY +l.s_artist, l.s_album
                    ORDER BY plays DESC, album COLLATE NOCASE LIMIT ?""",
                (*params, limit),
            )
            tracks = self._rows(
                f"""SELECT l.path, MIN(l.title) AS title, MIN(l.artist) AS artist, MIN(l.album) AS album,
                           MAX(t.album_key) AS album_key, MAX(t.art) AS art, MAX(t.duration) AS duration,
                           COUNT(*) AS plays, MAX(t.year) AS year, MAX(t.track_no) AS track_no,
                           MAX(t.disc_no) AS disc_no, MAX(t.id) AS id
                    FROM play_log l LEFT JOIN tracks t ON t.path=l.path {where} AND l.path IS NOT NULL
                    GROUP BY +l.s_artist, l.s_title
                    ORDER BY plays DESC, title COLLATE NOCASE LIMIT ?""",
                (*params, limit),
            )
            listen_count = self.conn.execute(
                f"SELECT COUNT(*) FROM play_log l {where}", params
            ).fetchone()[0]
        if period_start is None:
            listening_seconds = self.conn.execute(
                "SELECT COALESCE(SUM(t.duration * p.count),0) "
                "FROM plays p JOIN tracks t ON t.path=p.path"
            ).fetchone()[0]
        else:
            listening_seconds = self.conn.execute(
                f"SELECT COALESCE(SUM(l.duration),0) FROM play_log l {where}", params
            ).fetchone()[0]
        return {
            "artists": artists,
            "albums": albums,
            "tracks": tracks,
            "listens": listen_count,
            "listeningSeconds": listening_seconds,
        }

    def home_mix(self, limit=40):
        rows = self._rows(
            """WITH scored AS (
                 SELECT t.*, COALESCE(p.count,0) AS plays, p.last AS last,
                        CASE WHEN l.path IS NULL THEN 0 ELSE 1 END AS liked,
                        ROW_NUMBER() OVER (
                          PARTITION BY CASE WHEN t.album_artist != '' THEN t.s_aa ELSE t.s_artist END
                          ORDER BY COALESCE(p.count,0) DESC,
                                   CASE WHEN l.path IS NULL THEN 0 ELSE 1 END DESC,
                                   p.last DESC, t.s_title
                        ) AS artist_rank
                 FROM tracks t
                 LEFT JOIN plays p ON p.path=t.path
                 LEFT JOIN likes l ON l.path=t.path
                 WHERE p.path IS NOT NULL OR l.path IS NOT NULL
               )
               SELECT * FROM scored
               ORDER BY artist_rank, plays DESC, liked DESC, last DESC, s_title
               LIMIT ?""",
            (limit,),
        )
        return rows

    def filter_values(self):
        return {
            "genres": [r["genre"] for r in self.conn.execute(
                "SELECT DISTINCT genre FROM tracks WHERE genre != '' ORDER BY genre COLLATE NOCASE"
            )],
            "years": [r["year"] for r in self.conn.execute(
                "SELECT DISTINCT year FROM tracks WHERE year > 0 ORDER BY year DESC"
            )],
            "formats": [r["fmt"] for r in self.conn.execute(
                "SELECT DISTINCT fmt FROM tracks WHERE fmt != '' ORDER BY fmt COLLATE NOCASE"
            )],
        }

    def filtered_tracks(self, genre="", year=0, fmt=""):
        clauses, params = [], []
        if genre:
            clauses.append("genre = ?")
            params.append(genre)
        if year:
            clauses.append("year = ?")
            params.append(year)
        if fmt:
            clauses.append("fmt = ?")
            params.append(fmt)
        where = "WHERE " + " AND ".join(clauses) if clauses else ""
        return self._rows(f"SELECT * FROM tracks {where} ORDER BY s_title, s_artist", params)

    def duplicate_tracks(self, limit=1000):
        return self._rows(
            """WITH duplicate_groups AS (
                 SELECT s_title, s_artist, ROUND(duration) AS duration_key, COUNT(*) AS duplicate_count
                 FROM tracks
                 WHERE s_title != '' AND s_artist != '' AND duration > 0
                 GROUP BY s_title, s_artist, ROUND(duration)
                 HAVING COUNT(*) > 1
               )
               SELECT t.*, d.duplicate_count FROM duplicate_groups d JOIN tracks t
                 ON t.s_title=d.s_title AND t.s_artist=d.s_artist AND ROUND(t.duration)=d.duration_key
               ORDER BY d.duplicate_count DESC, t.s_artist, t.s_title, t.path LIMIT ?""",
            (limit,),
        )

    def most_played(self, limit: int = 10) -> list:
        return self._rows(
            "SELECT t.*, p.count AS plays FROM plays p JOIN tracks t ON t.path=p.path "
            "ORDER BY p.count DESC, p.last DESC LIMIT ?",
            (limit,),
        )

    def recently_played_albums(self, limit: int = 12) -> list:
        keys = [r["album_key"] for r in self.conn.execute(
            "SELECT t.album_key FROM plays p JOIN tracks t ON t.path=p.path "
            "GROUP BY t.album_key ORDER BY MAX(p.last) DESC LIMIT ?", (limit,))]
        by_key = {a["album_key"]: a for a in self._rows(
            f"{self._ALBUM_SQL} WHERE album_key IN ({','.join('?' * len(keys))}) GROUP BY album_key", keys)} if keys else {}
        return [by_key[k] for k in keys if k in by_key]

    def get_lyrics(self, path: str) -> Optional[dict]:
        rows = self._rows("SELECT * FROM lyrics WHERE path=?", (path,))
        return rows[0] if rows else None

    def set_lyrics(self, path: str, synced: str, plain: str, source: str):
        self.conn.execute(
            "INSERT OR REPLACE INTO lyrics(path, synced, plain, source, fetched) VALUES(?,?,?,?,?)",
            (path, synced or "", plain or "", source, time.time()),
        )
        self.conn.commit()

    def track_by_path(self, path: str) -> Optional[dict]:
        rows = self._rows("SELECT * FROM tracks WHERE path=?", (path,))
        return rows[0] if rows else None

    def commit(self):
        self.conn.commit()

    def _rows(self, sql, params=()) -> list:
        return [dict(r) for r in self.conn.execute(sql, params)]

    # --- folders -------------------------------------------------------
    def folders(self) -> list:
        return [r["path"] for r in self.conn.execute("SELECT path FROM folders ORDER BY path")]

    def add_folder(self, path: str):
        self.conn.execute("INSERT OR IGNORE INTO folders(path) VALUES(?)", (path,))
        self.conn.commit()

    def forget_folder(self, path: str):
        self.conn.execute("DELETE FROM folders WHERE path=?", (path,))
        self.conn.commit()

    def purge_folder(self, path: str):
        self.remove_paths(self.paths_under(path))
        self.finalize()

    def remove_folder(self, path: str):
        self.forget_folder(path)
        self.purge_folder(path)

    # --- writes --------------------------------------------------------
    def paths_under(self, folder: str) -> dict:
        import os
        prefix = folder.rstrip(os.sep) + os.sep
        cur = self.conn.execute(
            "SELECT path, mtime, size FROM tracks WHERE path >= ? AND path < ?",
            (prefix, prefix + "\U0010ffff"),
        )
        return {r["path"]: (r["mtime"], r["size"]) for r in cur}

    def upsert_track(self, t: dict) -> int:
        params = {c: t.get(c) for c in COLS}
        params["codec"] = t.get("codec") or t.get("fmt", "")
        params["cue_start"] = t.get("cue_start") or 0.0
        params["cue_end"] = t.get("cue_end") or 0.0
        params["s_title"] = fold(t["title"])
        params["s_album"] = fold(t["album"])
        params["s_aa"] = fold(t["album_artist"])
        params["s_artist"] = fold(t["artist"])
        params["s_genre"] = fold(t.get("genre") or "")
        params["rg_measured"] = 0
        if params.get("rg_track") is None and params.get("rg_album") is None:
            # No ReplayGain tags: use our own measurement if it is for this very file
            m = self.conn.execute(
                "SELECT track_gain, album_gain, peak FROM loudness WHERE path=? AND mtime=? AND size=?",
                (t["path"], t.get("mtime"), t.get("size")),
            ).fetchone()
            if m:
                params.update(rg_track=m["track_gain"], rg_album=m["album_gain"], rg_peak=m["peak"], rg_measured=1)
        extra = SEARCH_COLS + ["rg_measured"]
        row = self.conn.execute("SELECT id, art FROM tracks WHERE path=?", (t["path"],)).fetchone()
        if row:
            tid = row["id"]
            params["art"] = params["art"] or row["art"]
            sets = ", ".join(f"{c}=:{c}" for c in COLS + extra)
            self.conn.execute(f"UPDATE tracks SET {sets} WHERE id=:id", {**params, "id": tid})
        else:
            cols = ", ".join(COLS + extra + ["added"])
            vals = ", ".join(":" + c for c in COLS + extra + ["added"])
            cur = self.conn.execute(
                f"INSERT INTO tracks({cols}) VALUES({vals})", {**params, "added": time.time()}
            )
            tid = cur.lastrowid
        if t.get("rating"):
            # A rating written by another player counts until you rate the song here
            self.conn.execute("INSERT OR IGNORE INTO ratings(path, stars, rated_at) VALUES(?,?,?)",
                              (t["path"], int(t["rating"]), time.time()))
        if self.has_fts:
            self.conn.execute("DELETE FROM tracks_fts WHERE rowid=?", (tid,))
            self.conn.execute(
                "INSERT INTO tracks_fts(rowid, title, artist, album) VALUES(?,?,?,?)",
                (tid, t["title"], t["artist"], t["album"]),
            )
        return tid

    # --- ReplayGain analysis -----------------------------------------------
    def albums_needing_gain(self, limit=None):
        """[(album_key, [paths in album order])] for albums with a song lacking ReplayGain; whole albums are
        returned so album gain covers every song."""
        keys = [r[0] for r in self.conn.execute(
            f"SELECT DISTINCT album_key FROM tracks WHERE rg_track IS NULL AND file IS NULL AND {SQL_LOCAL} "
            "ORDER BY album_key"
            + (" LIMIT ?" if limit else ""), (limit,) if limit else ())]
        return [(k, [r[0] for r in self.conn.execute(
            f"SELECT path FROM tracks WHERE album_key=? AND file IS NULL AND {SQL_LOCAL} ORDER BY {_ORDER}", (k,))]) for k in keys]

    def tracks_without_gain(self) -> int:
        return self.conn.execute(f"SELECT COUNT(*) FROM tracks WHERE rg_track IS NULL AND file IS NULL AND {SQL_LOCAL}").fetchone()[0]

    def store_loudness(self, results):
        """Save measurements [{path, track_gain, album_gain, peak}] and use them for songs without gain tags."""
        now = time.time()
        for r in results:
            st = self.conn.execute("SELECT mtime, size FROM tracks WHERE path=?", (r["path"],)).fetchone()
            if st is None:
                continue
            self.conn.execute(
                "INSERT OR REPLACE INTO loudness(path, mtime, size, track_gain, album_gain, peak, measured) "
                "VALUES(?,?,?,?,?,?,?)",
                (r["path"], st["mtime"], st["size"], r["track_gain"], r["album_gain"], r["peak"], now),
            )
            self.conn.execute(
                "UPDATE tracks SET rg_track=?, rg_album=?, rg_peak=?, rg_measured=1 "
                "WHERE path=? AND (rg_track IS NULL OR rg_measured=1)",
                (r["track_gain"], r["album_gain"], r["peak"], r["path"]),
            )
        self.conn.commit()

    def remove_paths(self, paths: Iterable[str]):
        for p in paths:
            row = self.conn.execute("SELECT id FROM tracks WHERE path=?", (p,)).fetchone()
            if not row:
                continue
            if self.has_fts:
                self.conn.execute("DELETE FROM tracks_fts WHERE rowid=?", (row["id"],))
            self.conn.execute("DELETE FROM tracks WHERE id=?", (row["id"],))

    @staticmethod
    def file_of(path: str) -> str:
        """The file a library path lives in: CUE sheet songs are "file.flac#3"."""
        m = re.match(r"^(.*\.[A-Za-z0-9]+)#\d+$", path)
        return m.group(1) if m else path

    def hide_paths(self, paths: Iterable[str]) -> int:
        """Take songs out of the library and keep later scans from adding their files back."""
        paths = list(paths)
        now = time.time()
        files = {self.file_of(p) for p in paths}
        self.conn.executemany("INSERT OR IGNORE INTO hidden(path, hidden_at) VALUES(?, ?)", [(f, now) for f in files])
        # every song of a hidden file goes, so a CUE album doesn't leave stragglers
        doomed = set(paths)
        for f in files:
            doomed.update(r[0] for r in self.conn.execute(
                "SELECT path FROM tracks WHERE path=? OR path LIKE ? ESCAPE '\\'", (f, _like_prefix(f) + "#%")))
        self.remove_paths(doomed)
        self.conn.commit()
        return len(doomed)

    def hidden_paths(self) -> set:
        return {r[0] for r in self.conn.execute("SELECT path FROM hidden")}

    def unhide(self, paths: Iterable[str]) -> int:
        """Let these songs' files back into the library (on the next scan)."""
        files = {self.file_of(p) for p in paths}
        n = sum(self.conn.execute("DELETE FROM hidden WHERE path=?", (f,)).rowcount for f in files)
        self.conn.commit()
        return n

    def unhide_all(self) -> int:
        n = self.conn.execute("DELETE FROM hidden").rowcount
        self.conn.commit()
        return n

    def set_album_art(self, key: str, art: str):
        self.conn.execute("UPDATE tracks SET art=? WHERE album_key=?", (art, key))

    def carry_file_caches(self, path: str, mtime: float, size: int):
        """`path` was rewritten with new tags only (by this app): its row and its loudness measurement stay
        right for the new file, so the next scan needn't read it again or ReplayGain analyse it again."""
        self.conn.execute("UPDATE tracks SET mtime=?, size=? WHERE path=?", (mtime, size, path))
        self.conn.execute("UPDATE loudness SET mtime=?, size=? WHERE path=?", (mtime, size, path))

    def chosen_art(self, key: str):
        """The cover you picked for an album (from a file or found online), or None."""
        row = self.conn.execute("SELECT art FROM chosen_art WHERE album_key=?", (key,)).fetchone()
        return row["art"] if row else None

    def set_chosen_art(self, key: str, art: str):
        self.conn.execute("INSERT OR REPLACE INTO chosen_art(album_key, art, chosen_at) VALUES(?,?,?)",
                          (key, art, time.time()))
        self.set_album_art(key, art)

    def art_in_use(self, art: str) -> bool:
        return bool(self.conn.execute("SELECT 1 FROM tracks WHERE art=? LIMIT 1", (art,)).fetchone()
                    or self.conn.execute("SELECT 1 FROM chosen_art WHERE art=? LIMIT 1", (art,)).fetchone())

    def album_art_map(self) -> dict:
        cur = self.conn.execute(
            "SELECT album_key, MAX(art) AS art FROM tracks WHERE art IS NOT NULL GROUP BY album_key"
        )
        return {r["album_key"]: r["art"] for r in cur}

    def finalize(self):
        """Give tracks without an album-artist tag a consistent album artist."""
        self.conn.execute(
            """UPDATE tracks SET album_artist = (
                 SELECT CASE WHEN COUNT(DISTINCT t2.artist) > 1 THEN 'Various Artists'
                             ELSE MIN(t2.artist) END
                 FROM tracks t2 WHERE t2.album_key = tracks.album_key)
               WHERE aa_tag = 0"""
        )
        # each distinct name folded once, in Python, and only rows that differ written
        names = {}
        stale = []
        for tid, aa, s_aa in self.conn.execute("SELECT id, album_artist, s_aa FROM tracks WHERE aa_tag = 0"):
            folded = names.get(aa)
            if folded is None:
                folded = names[aa] = fold(aa)
            if folded != s_aa:
                stale.append((folded, tid))
        self.conn.executemany("UPDATE tracks SET s_aa=? WHERE id=?", stale)
        self.conn.commit()

    # --- reads ---------------------------------------------------------
    def counts(self) -> dict:
        r = self.conn.execute(
            "SELECT COUNT(*) t, COUNT(DISTINCT album_key) a, COUNT(DISTINCT s_aa) r FROM tracks"
        ).fetchone()
        return {"tracks": r["t"], "albums": r["a"], "artists": r["r"]}

    def track(self, tid: int) -> Optional[dict]:
        rows = self._rows("SELECT * FROM tracks WHERE id=?", (tid,))
        return rows[0] if rows else None

    def tracks(self) -> list:
        return self._rows(
            "SELECT * FROM tracks ORDER BY s_title, artist COLLATE NOCASE"
        )

    # Columns the all-songs list doesn't carry: search-only folded copies and housekeeping. Everything that
    # playback, the signal path or the song rows read stays.
    SONG_LIST_SKIP = ("s_title", "s_artist", "s_album", "s_aa", "aa_tag", "added", "mtime", "size")

    def song_list(self) -> list:
        """Every song, title order, as the Songs page needs them: tuples straight into dicts (faster than
        sqlite3.Row) and without the columns in SONG_LIST_SKIP (a quarter less memory per song)."""
        cols = [r[1] for r in self.conn.execute("PRAGMA table_info(tracks)") if r[1] not in self.SONG_LIST_SKIP]
        cur = self.conn.cursor()
        cur.row_factory = None
        cur.execute(f"SELECT {', '.join(cols)} FROM tracks ORDER BY s_title, artist COLLATE NOCASE")
        return [dict(zip(cols, row)) for row in cur]

    _ALBUM_SQL = """SELECT album_key, MIN(album) AS album, MIN(album_artist) AS album_artist,
                    MAX(year) AS year, COUNT(*) AS n, SUM(duration) AS duration,
                    MAX(art) AS art, MAX(added) AS added FROM tracks"""

    def albums(self, where: str = "", params=()) -> list:
        return self._rows(
            f"{self._ALBUM_SQL} {where} GROUP BY album_key ORDER BY year, MIN(s_album)"
            if where
            else f"{self._ALBUM_SQL} GROUP BY album_key ORDER BY MIN(s_album)",
            params,
        )

    def recent_albums(self, limit: int = 20) -> list:
        return self._rows(
            f"{self._ALBUM_SQL} GROUP BY album_key ORDER BY added DESC, MIN(s_album) LIMIT ?",
            (limit,),
        )

    def album(self, key: str) -> Optional[dict]:
        rows = self._rows(f"{self._ALBUM_SQL} WHERE album_key=? GROUP BY album_key", (key,))
        return rows[0] if rows else None

    def album_tracks(self, key: str) -> list:
        return self._rows(f"SELECT * FROM tracks WHERE album_key=? ORDER BY {_ORDER}", (key,))

    def artists(self) -> list:
        return self._rows(
            """SELECT MIN(album_artist) AS name, COUNT(DISTINCT album_key) AS albums,
                      COUNT(*) AS tracks, MAX(art) AS art
               FROM tracks GROUP BY s_aa ORDER BY MIN(s_aa)"""
        )

    def artist_albums(self, name: str) -> list:
        return self.albums("WHERE s_aa=?", (fold(name),))

    def artist_tracks(self, name: str, limit: int = 100000) -> list:
        return self._rows(
            "SELECT * FROM tracks WHERE s_aa=? OR s_artist=? "
            "ORDER BY s_album, " + _ORDER + " LIMIT ?",
            (fold(name), fold(name), limit),
        )

    def search(self, query: str, track_limit: int = 30, album_limit: int = 20, artist_limit: int = 12,
               groups: bool = True) -> dict:
        """Songs, albums and artists matching `query`. With groups=False only songs are looked up (the library
        finds albums and artists in memory with search_groups)."""
        toks = _tokens(query)
        if not toks:
            return {"tracks": [], "albums": [], "artists": []}

        if self.has_fts:
            match = " ".join(f'"{t}"*' for t in toks)
            tracks = self._rows(
                "SELECT t.* FROM tracks_fts f JOIN tracks t ON t.id = f.rowid "
                "WHERE tracks_fts MATCH ? ORDER BY bm25(tracks_fts), t.s_title LIMIT ?",
                (match, track_limit),
            )
        else:
            clause = " AND ".join(
                "(s_title LIKE ? ESCAPE '\\' OR s_artist LIKE ? ESCAPE '\\' OR s_album LIKE ? ESCAPE '\\')" for _ in toks
            )
            params = [_like(t) for t in toks for _ in range(3)]
            tracks = self._rows(
                f"SELECT * FROM tracks WHERE {clause} ORDER BY s_title LIMIT ?",
                (*params, track_limit),
            )

        if not groups:
            return {"tracks": tracks, "albums": [], "artists": []}
        album_clause = " AND ".join(
            "(s_album LIKE ? ESCAPE '\\' OR s_aa LIKE ? ESCAPE '\\')" for _ in toks
        )
        album_params = [_like(t) for t in toks for _ in range(2)]
        first = _like(toks[0])[1:]
        albums = self._rows(
            f"{self._ALBUM_SQL} WHERE {album_clause} GROUP BY album_key "
            "ORDER BY (MIN(s_album) LIKE ? ESCAPE '\\') DESC, MIN(s_album) LIMIT ?",
            (*album_params, first, album_limit),
        )

        artist_clause = " AND ".join("s_aa LIKE ? ESCAPE '\\'" for _ in toks)
        artists = self._rows(
            f"""SELECT MIN(album_artist) AS name, COUNT(DISTINCT album_key) AS albums,
                       COUNT(*) AS tracks, MAX(art) AS art
                FROM tracks WHERE {artist_clause} GROUP BY s_aa
                ORDER BY (MIN(s_aa) LIKE ? ESCAPE '\\') DESC, MIN(s_aa) LIMIT ?""",
            ([_like(t) for t in toks] + [first, artist_limit]),
        )
        return {"tracks": tracks, "albums": albums, "artists": artists}
