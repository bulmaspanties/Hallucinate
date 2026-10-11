"""Library health: things worth fixing in a collection, each with what to do about it.

Pure functions over a Database. Every check returns {"id", "title", "detail", "count", "kind", "items"} where
`kind` says what the items are ("album", "track" or "folder") so the page can offer the right fix, and `items`
is capped (count is the full number)."""
import os

LIMIT = 200
UNKNOWN_ARTIST = "Unknown Artist"
UNKNOWN_ALBUM = "Unknown Album"
LOW_BITRATE = 128_000
LOSSY = ("MP3", "AAC", "OGG", "VORBIS", "OPUS", "WMA", "M4A", "MP4")


def _albums(db, having, params=()):
    rows = db._rows(
        f"""SELECT album_key, MIN(album) AS album, MIN(album_artist) AS album_artist, MAX(year) AS year,
                   COUNT(*) AS n, MAX(art) AS art, MIN(path) AS path
            FROM tracks GROUP BY album_key HAVING {having} ORDER BY MIN(s_aa), MIN(s_album)""",
        params,
    )
    return rows


def _check(id_, title, detail, kind, items):
    return {"id": id_, "title": title, "detail": detail, "kind": kind, "count": len(items), "items": items[:LIMIT]}


def missing_covers(db):
    return _check("covers", "Albums without a cover",
                  "No cover in the files or the folder. Find one online or pick an image.",
                  "album", _albums(db, "MAX(art) IS NULL OR MAX(art) = ''"))


def missing_year(db):
    return _check("year", "Albums without a year",
                  "They sit at the end of the timeline and can't be found by year.",
                  "album", _albums(db, "MAX(year) <= 0"))


def missing_genre(db):
    return _check("genre", "Albums without a genre",
                  "Smart playlists and radio use genres to find related music.",
                  "album", _albums(db, "MAX(genre) = ''"))


def unknown_artist_or_album(db):
    rows = db._rows(
        "SELECT * FROM tracks WHERE artist = ? OR album = ? ORDER BY path LIMIT ?",
        (UNKNOWN_ARTIST, UNKNOWN_ALBUM, LIMIT + 1000),
    )
    return _check("untagged", "Songs missing artist or album tags",
                  "Shown as “Unknown” and grouped together. Edit their tags.", "track", rows)


def missing_track_numbers(db):
    return _check("numbers", "Albums without track numbers",
                  "Their songs play in title order instead of the album's.",
                  "album", _albums(db, "COUNT(*) > 1 AND MAX(track_no) = 0"))


def split_albums(db):
    """The same album title in one folder under more than one album key (usually mixed album-artist tags)."""
    groups = {}
    for r in db.conn.execute(
        "SELECT album_key, album, album_artist, s_album, path, art FROM tracks WHERE album != ?", (UNKNOWN_ALBUM,)
    ):
        group = groups.setdefault((r["s_album"], os.path.dirname(r["path"])), {})
        group.setdefault(r["album_key"], r)
    rows = []
    for parts in groups.values():
        if len(parts) > 1:
            first = parts[min(parts)]
            rows.append({"album_key": first["album_key"], "album": first["album"],
                         "album_artist": " / ".join(sorted({p["album_artist"] for p in parts.values()})),
                         "path": first["path"], "art": first["art"], "parts": len(parts)})
    rows.sort(key=lambda r: r["album"].casefold())
    return _check("split", "Albums split in two",
                  "One folder's album shows up more than once, usually because its songs disagree on the album "
                  "artist. Give them the same album artist.", "album", rows)


def low_bitrate(db):
    marks = ",".join("?" * len(LOSSY))
    rows = db._rows(
        f"""SELECT * FROM tracks WHERE bitrate > 0 AND bitrate < ?
              AND UPPER(CASE WHEN codec != '' THEN codec ELSE fmt END) IN ({marks})
            ORDER BY bitrate, path LIMIT ?""",
        (LOW_BITRATE, *LOSSY, LIMIT + 1000),
    )
    return _check("bitrate", "Low-quality files",
                  "Lossy files under 128 kbps; worth replacing if you have better copies.", "track", rows)


def duplicates(db):
    rows = db.duplicate_tracks(LIMIT + 1000)
    return _check("duplicates", "Probable duplicates",
                  "The same title, artist and length more than once.", "track", rows)


def missing_folders(db):
    rows = [{"path": f} for f in db.folders() if not os.path.isdir(f)]
    return _check("folders", "Library folders that can't be found",
                  "Unplugged drives show up here too. Remove a folder only if it is gone for good.", "folder", rows)


CHECKS = (missing_folders, unknown_artist_or_album, split_albums, missing_covers, missing_track_numbers,
          missing_year, missing_genre, duplicates, low_bitrate)


def report(db):
    """All checks, the ones with problems first (in the order above), then a total and an overall score.

    The score is the share of tracks free of track-level problems and of albums free of album-level ones."""
    results = [check(db) for check in CHECKS]
    total = sum(r["count"] for r in results)
    tracks = db.conn.execute("SELECT COUNT(*) FROM tracks").fetchone()[0]
    albums = db.conn.execute("SELECT COUNT(DISTINCT album_key) FROM tracks").fetchone()[0]
    album_issues = sum(r["count"] for r in results if r["kind"] == "album")
    track_issues = sum(r["count"] for r in results if r["kind"] == "track")
    parts = []
    if albums:
        parts.append(max(0.0, 1 - album_issues / (albums * 5)))  # five album checks
    if tracks:
        parts.append(max(0.0, 1 - track_issues / (tracks * 3)))  # three track checks
    score = round(100 * sum(parts) / len(parts)) if parts else 100
    if any(r["id"] == "folders" and r["count"] for r in results):
        score = min(score, 60)
    results.sort(key=lambda r: r["count"] == 0)
    return {"checks": results, "issues": total, "score": score, "tracks": tracks, "albums": albums}
