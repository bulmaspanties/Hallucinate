"""SQLite library storage with FTS5-backed search."""
import re
import sqlite3
import time
import unicodedata
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
  rg_track REAL,
  rg_album REAL,
  rg_peak REAL,
  added REAL NOT NULL,
  s_title TEXT NOT NULL DEFAULT '',
  s_album TEXT NOT NULL DEFAULT '',
  s_aa TEXT NOT NULL DEFAULT '',
  s_artist TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_tracks_album ON tracks(album_key);
CREATE TABLE IF NOT EXISTS folders(path TEXT PRIMARY KEY);
CREATE TABLE IF NOT EXISTS likes(path TEXT PRIMARY KEY, liked_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS playlists(id INTEGER PRIMARY KEY, name TEXT NOT NULL, created REAL NOT NULL);
CREATE TABLE IF NOT EXISTS playlist_items(
  id INTEGER PRIMARY KEY, playlist_id INTEGER NOT NULL REFERENCES playlists(id) ON DELETE CASCADE,
  path TEXT NOT NULL, pos INTEGER NOT NULL);
CREATE INDEX IF NOT EXISTS idx_pl_items ON playlist_items(playlist_id, pos);
CREATE TABLE IF NOT EXISTS plays(path TEXT PRIMARY KEY, count INTEGER NOT NULL, last REAL NOT NULL);
CREATE TABLE IF NOT EXISTS lyrics(path TEXT PRIMARY KEY, synced TEXT NOT NULL DEFAULT '',
  plain TEXT NOT NULL DEFAULT '', source TEXT NOT NULL DEFAULT '', fetched REAL NOT NULL);
"""

FTS = (
    "CREATE VIRTUAL TABLE IF NOT EXISTS tracks_fts USING fts5("
    "title, artist, album, tokenize='unicode61 remove_diacritics 2')"
)

COLS = (
    "path mtime size title artist album_artist aa_tag album album_key track_no disc_no "
    "year genre duration fmt bitrate sample_rate art rg_track rg_album rg_peak"
).split()

SEARCH_COLS = ["s_title", "s_album", "s_aa", "s_artist"]

_ORDER = "disc_no, track_no, s_title"


def _like(token: str) -> str:
    return "%" + token.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def fold(s: str) -> str:
    """Case- and accent-insensitive form used for searching and sorting (all scripts)."""
    s = unicodedata.normalize("NFKD", (s or "").casefold())
    return "".join(c for c in s if not unicodedata.combining(c))


def _tokens(q: str) -> list:
    return re.findall(r"\w+", fold(q))


class Database:
    def __init__(self, path):
        self.conn = sqlite3.connect(str(path), timeout=30, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.create_function("fold", 1, fold, deterministic=True)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self.conn.executescript(SCHEMA)
        self._migrate()
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_tracks_stitle ON tracks(s_title)")
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_tracks_saa ON tracks(s_aa)")
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_tracks_sartist ON tracks(s_artist)")
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
        missing = [c for c in SEARCH_COLS if c not in cols]
        if not missing:
            return
        for c in missing:
            self.conn.execute(f"ALTER TABLE tracks ADD COLUMN {c} TEXT NOT NULL DEFAULT ''")
        rows = self.conn.execute("SELECT id, title, artist, album, album_artist FROM tracks").fetchall()
        self.conn.executemany(
            "UPDATE tracks SET s_title=?, s_album=?, s_aa=?, s_artist=? WHERE id=?",
            [(fold(r["title"]), fold(r["album"]), fold(r["album_artist"]), fold(r["artist"]), r["id"]) for r in rows],
        )

    def close(self):
        self.conn.close()

    # --- user data: likes, playlists, play counts, lyrics cache ----------
    def liked_paths(self) -> set:
        return {r["path"] for r in self.conn.execute("SELECT path FROM likes")}

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

    def record_play(self, path: str, when: Optional[float] = None):
        self.conn.execute(
            "INSERT INTO plays(path, count, last) VALUES(?,1,?) "
            "ON CONFLICT(path) DO UPDATE SET count=count+1, last=excluded.last",
            (path, when or time.time()),
        )
        self.conn.commit()

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
        params["s_title"] = fold(t["title"])
        params["s_album"] = fold(t["album"])
        params["s_aa"] = fold(t["album_artist"])
        params["s_artist"] = fold(t["artist"])
        row = self.conn.execute("SELECT id, art FROM tracks WHERE path=?", (t["path"],)).fetchone()
        if row:
            tid = row["id"]
            params["art"] = params["art"] or row["art"]
            sets = ", ".join(f"{c}=:{c}" for c in COLS + SEARCH_COLS)
            self.conn.execute(f"UPDATE tracks SET {sets} WHERE id=:id", {**params, "id": tid})
        else:
            cols = ", ".join(COLS + SEARCH_COLS + ["added"])
            vals = ", ".join(":" + c for c in COLS + SEARCH_COLS + ["added"])
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
        self.conn.execute("UPDATE tracks SET s_aa = fold(album_artist) WHERE aa_tag = 0 AND s_aa != fold(album_artist)")
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

    def search(self, query: str, track_limit: int = 30, album_limit: int = 20, artist_limit: int = 12) -> dict:
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
