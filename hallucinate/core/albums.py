"""Albums as more than a track list: liner notes, a wall ordered by cover colour, and a timeline by year.

Pure functions over a Database; cover colours themselves are measured by the caller (that needs Qt) and cached
in the album_colors table, keyed by the art file so a new cover is measured again."""
from collections import Counter

from .insights import LOSSLESS


def liner_notes(db, key):
    """Facts for an album's page: genres, discs, formats, size, when it was added, and how you've listened to it.

    `trackPlays` maps each track's path to its play count."""
    rows = db._rows(
        "SELECT t.path, t.genre, t.disc_no, t.codec, t.fmt, t.bitrate, t.sample_rate, t.size, t.added, "
        "COALESCE(p.count, 0) AS plays, p.last AS last, CASE WHEN l.path IS NULL THEN 0 ELSE 1 END AS liked "
        "FROM tracks t LEFT JOIN plays p ON p.path = t.path LEFT JOIN likes l ON l.path = t.path "
        "WHERE t.album_key = ?",
        (key,),
    )
    if not rows:
        return {}
    genres = Counter(g.strip() for r in rows for g in (r["genre"] or "").replace(";", "/").split("/") if g.strip())
    formats = Counter((r["codec"] or r["fmt"] or "").upper() for r in rows)
    rates = sorted({r["sample_rate"] for r in rows if r["sample_rate"]})
    bitrates = [r["bitrate"] for r in rows if r["bitrate"]]
    first = db.conn.execute(
        "SELECT MIN(l.ts) FROM play_log l JOIN tracks t ON t.path = l.path WHERE t.album_key = ?", (key,)
    ).fetchone()[0]
    lasts = [r["last"] for r in rows if r["last"]]
    return {
        "genres": [g for g, _ in genres.most_common(4)],
        "discs": len({r["disc_no"] for r in rows if r["disc_no"] > 0}),
        "formats": [f for f, _ in formats.most_common() if f],
        "lossless": all(f in LOSSLESS for f in formats if f),
        "sampleRates": rates,
        "bitrate": round(sum(bitrates) / len(bitrates)) if bitrates else 0,
        "bytes": sum(r["size"] or 0 for r in rows),
        "added": min((r["added"] for r in rows if r["added"]), default=0),
        "plays": sum(r["plays"] for r in rows),
        "firstPlayed": first or 0,
        "lastPlayed": max(lasts) if lasts else 0,
        "liked": sum(r["liked"] for r in rows),
        "trackPlays": {r["path"]: r["plays"] for r in rows if r["plays"]},
    }


def cached_colors(db):
    """{album_key: (art, colour dict)} for every measured cover."""
    return {
        r["album_key"]: (r["art"], {"color": r["color"], "hue": r["hue"], "sat": r["sat"], "val": r["val"]})
        for r in db.conn.execute("SELECT * FROM album_colors")
    }


def store_colors(db, measured):
    """Save {album_key: (art, colour dict)}."""
    db.conn.executemany(
        "INSERT OR REPLACE INTO album_colors(album_key, art, color, hue, sat, val) VALUES(?,?,?,?,?,?)",
        [(k, art, c["color"], c["hue"], c["sat"], c["val"]) for k, (art, c) in measured.items()],
    )
    db.conn.execute("DELETE FROM album_colors WHERE album_key NOT IN (SELECT album_key FROM tracks)")
    db.conn.commit()


HUE_STEPS = 18


def colour_order(album):
    """Sort key for the colour wall: the spectrum from red round to magenta, light to dark within each hue,
    then near-greys from white to black, then albums without a cover."""
    c = album.get("cover")
    if not c:
        return (2, 0, 0)
    if c["sat"] < 0.2 or c["val"] < 0.16:
        return (1, -c["val"], 0)
    return (0, int(c["hue"] * HUE_STEPS) % HUE_STEPS, -c["val"])


def timeline(albums):
    """Albums grouped by decade and year, oldest first; albums without a year come last.

    Returns [{"decade": "1990s", "count", "years": [{"year": 1994, "albums": [...]}, ...]}, ...]."""
    by_year = {}
    for a in albums:
        by_year.setdefault(a.get("year") or 0, []).append(a)
    decades = {}
    for year in sorted(by_year):
        label = f"{year // 10 * 10}s" if year > 0 else "Unknown year"
        group = decades.setdefault(label, {"decade": label, "count": 0, "years": []})
        items = sorted(by_year[year], key=lambda a: ((a.get("album_artist") or "").casefold(), a.get("album") or ""))
        group["years"].append({"year": year, "albums": items})
        group["count"] += len(items)
    out = [g for k, g in decades.items() if k != "Unknown year"]
    if "Unknown year" in decades:
        out.append(decades["Unknown year"])
    return out
