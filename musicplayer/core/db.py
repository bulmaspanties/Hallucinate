"""SQLite library storage with FTS5-backed search."""
import re
import sqlite3
import time
from typing import Iterable, Optional

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
  bitrate INTEGER NOT NULL DEFAULT 0,
  sample_rate INTEGER NOT NULL DEFAULT 0,
  art TEXT,
  added REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_tracks_album ON tracks(album_key);
CREATE INDEX IF NOT EXISTS idx_tracks_aa ON tracks(album_artist COLLATE NOCASE);
CREATE TABLE IF NOT EXISTS folders(path TEXT PRIMARY KEY);
"""

FTS = (
    "CREATE VIRTUAL TABLE IF NOT EXISTS tracks_fts USING fts5("
    "title, artist, album, tokenize='unicode61 remove_diacritics 2')"
)

COLS = (
    "path mtime size title artist album_artist aa_tag album album_key track_no disc_no "
    "year genre duration fmt bitrate sample_rate art"
).split()

_ORDER = "disc_no, track_no, title COLLATE NOCASE"


def _like(token: str) -> str:
    return "%" + token.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def _tokens(q: str) -> list:
    return re.findall(r"\w+", q.lower())


class Database:
    def __init__(self, path):
        self.conn = sqlite3.connect(str(path), timeout=30, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self.conn.executescript(SCHEMA)
        try:
            self.conn.execute(FTS)
            self.has_fts = True
        except sqlite3.OperationalError:
            self.has_fts = False
        self.conn.commit()

    def close(self):
        self.conn.close()

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

    def remove_folder(self, path: str):
        self.conn.execute("DELETE FROM folders WHERE path=?", (path,))
        self.remove_paths(self.paths_under(path))
        self.finalize()

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
        row = self.conn.execute("SELECT id, art FROM tracks WHERE path=?", (t["path"],)).fetchone()
        if row:
            tid = row["id"]
            params["art"] = params["art"] or row["art"]
            sets = ", ".join(f"{c}=:{c}" for c in COLS)
            self.conn.execute(f"UPDATE tracks SET {sets} WHERE id=:id", {**params, "id": tid})
        else:
            cols = ", ".join(COLS + ["added"])
            vals = ", ".join(":" + c for c in COLS + ["added"])
            cur = self.conn.execute(
                f"INSERT INTO tracks({cols}) VALUES({vals})", {**params, "added": time.time()}
            )
            tid = cur.lastrowid
        if self.has_fts:
            self.conn.execute("DELETE FROM tracks_fts WHERE rowid=?", (tid,))
            self.conn.execute(
                "INSERT INTO tracks_fts(rowid, title, artist, album) VALUES(?,?,?,?)",
                (tid, t["title"], t["artist"], t["album"]),
            )
        return tid

    def remove_paths(self, paths: Iterable[str]):
        for p in paths:
            row = self.conn.execute("SELECT id FROM tracks WHERE path=?", (p,)).fetchone()
            if not row:
                continue
            if self.has_fts:
                self.conn.execute("DELETE FROM tracks_fts WHERE rowid=?", (row["id"],))
            self.conn.execute("DELETE FROM tracks WHERE id=?", (row["id"],))

    def set_album_art(self, key: str, art: str):
        self.conn.execute("UPDATE tracks SET art=? WHERE album_key=?", (art, key))

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
        self.conn.commit()

    # --- reads ---------------------------------------------------------
    def counts(self) -> dict:
        r = self.conn.execute(
            "SELECT COUNT(*) t, COUNT(DISTINCT album_key) a, COUNT(DISTINCT lower(album_artist)) r FROM tracks"
        ).fetchone()
        return {"tracks": r["t"], "albums": r["a"], "artists": r["r"]}

    def track(self, tid: int) -> Optional[dict]:
        rows = self._rows("SELECT * FROM tracks WHERE id=?", (tid,))
        return rows[0] if rows else None

    def tracks(self) -> list:
        return self._rows(
            "SELECT * FROM tracks ORDER BY title COLLATE NOCASE, artist COLLATE NOCASE"
        )

    _ALBUM_SQL = """SELECT album_key, MIN(album) AS album, MIN(album_artist) AS album_artist,
                    MAX(year) AS year, COUNT(*) AS n, SUM(duration) AS duration,
                    MAX(art) AS art, MAX(added) AS added FROM tracks"""

    def albums(self, where: str = "", params=()) -> list:
        return self._rows(
            f"{self._ALBUM_SQL} {where} GROUP BY album_key ORDER BY year, album COLLATE NOCASE"
            if where
            else f"{self._ALBUM_SQL} GROUP BY album_key ORDER BY album COLLATE NOCASE",
            params,
        )

    def recent_albums(self, limit: int = 20) -> list:
        return self._rows(
            f"{self._ALBUM_SQL} GROUP BY album_key ORDER BY added DESC, album COLLATE NOCASE LIMIT ?",
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
               FROM tracks GROUP BY lower(album_artist) ORDER BY name COLLATE NOCASE"""
        )

    def artist_albums(self, name: str) -> list:
        return self.albums("WHERE lower(album_artist)=lower(?)", (name,))

    def artist_tracks(self, name: str, limit: int = 100000) -> list:
        return self._rows(
            "SELECT * FROM tracks WHERE lower(album_artist)=lower(?) OR lower(artist)=lower(?) "
            "ORDER BY album COLLATE NOCASE, " + _ORDER + " LIMIT ?",
            (name, name, limit),
        )

    def search(self, query: str, track_limit: int = 30, album_limit: int = 20, artist_limit: int = 12) -> dict:
        toks = _tokens(query)
        if not toks:
            return {"tracks": [], "albums": [], "artists": []}

        if self.has_fts:
            match = " ".join(f'"{t}"*' for t in toks)
            tracks = self._rows(
                "SELECT t.* FROM tracks_fts f JOIN tracks t ON t.id = f.rowid "
                "WHERE tracks_fts MATCH ? ORDER BY bm25(tracks_fts), t.title COLLATE NOCASE LIMIT ?",
                (match, track_limit),
            )
        else:
            clause = " AND ".join(
                "(title LIKE ? ESCAPE '\\' OR artist LIKE ? ESCAPE '\\' OR album LIKE ? ESCAPE '\\')" for _ in toks
            )
            params = [_like(t) for t in toks for _ in range(3)]
            tracks = self._rows(
                f"SELECT * FROM tracks WHERE {clause} ORDER BY title COLLATE NOCASE LIMIT ?",
                (*params, track_limit),
            )

        album_clause = " AND ".join(
            "(album LIKE ? ESCAPE '\\' OR album_artist LIKE ? ESCAPE '\\')" for _ in toks
        )
        album_params = [_like(t) for t in toks for _ in range(2)]
        first = _like(toks[0])[1:]
        albums = self._rows(
            f"{self._ALBUM_SQL} WHERE {album_clause} GROUP BY album_key "
            "ORDER BY (lower(MIN(album)) LIKE ? ESCAPE '\\') DESC, album COLLATE NOCASE LIMIT ?",
            (*album_params, first, album_limit),
        )

        artist_clause = " AND ".join("album_artist LIKE ? ESCAPE '\\'" for _ in toks)
        artists = self._rows(
            f"""SELECT MIN(album_artist) AS name, COUNT(DISTINCT album_key) AS albums,
                       COUNT(*) AS tracks, MAX(art) AS art
                FROM tracks WHERE {artist_clause} GROUP BY lower(album_artist)
                ORDER BY (lower(MIN(album_artist)) LIKE ? ESCAPE '\\') DESC, name COLLATE NOCASE LIMIT ?""",
            ([_like(t) for t in toks] + [first, artist_limit]),
        )
        return {"tracks": tracks, "albums": albums, "artists": artists}
