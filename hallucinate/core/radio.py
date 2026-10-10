"""Radio mode: pick tracks from the local library that suit what was just playing.

Candidates are scored against a few seed tracks (the end of the queue) using listening history and tags:
tracks and artists played in the same listening sessions as the seeds, the seeds' own artists, shared
genres and nearby years, plus a little weight for liked and often-played songs. Recently played tracks are
held back. The final pick is a weighted random choice among the best candidates, with at most two tracks
per artist in a batch and no artist twice in a row, so stations stay varied and differ between runs."""
import math
import random
import re
import time

from .db import fold
from .rules import FROM, compile_where

SESSION_GAP_S = 30 * 60  # plays this close to a seed play count as the same listening session
RECENT_S = 6 * 3600  # tracks played this recently are held back
POOL_PER_SOURCE = 250
TOP_N = 80
MAX_PER_ARTIST = 2

W_COPLAY = 1.5  # per co-play, up to COPLAY_CAP
COPLAY_CAP = 4
W_SEED_ARTIST = 2.0
W_COPLAY_ARTIST = 1.5
W_GENRE = 1.5
W_YEAR_NEAR = 1.0  # within 3 years
W_YEAR_SAME_ERA = 0.5  # within 8 years
W_LIKED = 1.0
W_PLAYS = 0.3  # times log(1 + play count)
RECENT_PENALTY = 4.0


def genres(text):
    """Folded genre names from a tag like "Rock; Indie/Pop"."""
    return {g for g in (fold(part).strip() for part in re.split(r"[;/,|]", text or "")) if g}


def _artist(row):
    return row["s_artist"] or fold(row["artist"])


def _placeholders(items):
    return ",".join("?" * len(items))


def radio_tracks(db, seeds, exclude=(), limit=10, rng=None, now=None, rules=None):
    """Up to `limit` library tracks (dicts) to follow `seeds` (paths, most recent last).

    `exclude` holds paths that must not be picked (typically the whole queue). `rules` (a smart playlist rule
    set) restricts picks to the tracks it matches, so a smart playlist can continue as a station."""
    rng = rng or random.Random()
    now = time.time() if now is None else now
    seeds = [p for p in seeds if p]
    if not seeds:
        return []
    excluded = set(exclude) | set(seeds)
    seed_rows = db._rows(f"SELECT * FROM tracks WHERE path IN ({_placeholders(seeds)})", seeds)
    if not seed_rows:
        return []
    seed_artists = {_artist(r) for r in seed_rows}
    seed_genres = set().union(*(genres(r["genre"]) for r in seed_rows))
    seed_years = [r["year"] for r in seed_rows if r["year"]]

    # Tracks heard in the same listening sessions as the seeds, and how often.
    coplay = {}
    for r in db._rows(
        f"""SELECT b.path AS path, COUNT(*) AS n FROM play_log a
            JOIN play_log b ON b.ts BETWEEN a.ts - ? AND a.ts + ? AND b.path IS NOT NULL AND b.path != a.path
            WHERE a.path IN ({_placeholders(seeds)})
            GROUP BY b.path ORDER BY n DESC LIMIT ?""",
        (SESSION_GAP_S, SESSION_GAP_S, *seeds, POOL_PER_SOURCE),
    ):
        coplay[r["path"]] = r["n"]

    where, where_params = compile_where(rules, now) if rules else ("1", [])
    base = f"SELECT t.* {FROM} WHERE {where} AND"
    pool = {}

    def add(rows):
        for r in rows:
            if r["path"] not in excluded:
                pool.setdefault(r["path"], dict(r))

    if coplay:
        paths = list(coplay)
        add(db._rows(f"{base} t.path IN ({_placeholders(paths)})", (*where_params, *paths)))
    coplay_artists = {_artist(r) for r in pool.values()} - seed_artists
    artists = list(seed_artists | coplay_artists)
    add(db._rows(
        f"{base} t.s_artist IN ({_placeholders(artists)}) ORDER BY random() LIMIT ?",
        (*where_params, *artists, POOL_PER_SOURCE),
    ))
    if seed_genres:
        clauses = " OR ".join("fold(t.genre) LIKE ?" for _ in seed_genres)
        add(db._rows(
            f"{base} ({clauses}) ORDER BY random() LIMIT ?",
            (*where_params, *(f"%{g}%" for g in seed_genres), POOL_PER_SOURCE),
        ))
    add(db._rows(f"{base} 1 ORDER BY random() LIMIT ?", (*where_params, POOL_PER_SOURCE)))
    if not pool:
        return []

    liked = {r["path"] for r in db._rows("SELECT path FROM likes")}
    plays = {r["path"]: (r["count"], r["last"]) for r in db._rows("SELECT path, count, last FROM plays")}

    scored = []
    for path, row in pool.items():
        artist = _artist(row)
        score = W_COPLAY * min(coplay.get(path, 0), COPLAY_CAP)
        if artist in seed_artists:
            score += W_SEED_ARTIST
        elif artist in coplay_artists:
            score += W_COPLAY_ARTIST
        if seed_genres and genres(row["genre"]) & seed_genres:
            score += W_GENRE
        if row["year"] and seed_years:
            gap = min(abs(row["year"] - y) for y in seed_years)
            score += W_YEAR_NEAR if gap <= 3 else W_YEAR_SAME_ERA if gap <= 8 else 0.0
        if path in liked:
            score += W_LIKED
        count, last = plays.get(path, (0, 0.0))
        score += W_PLAYS * math.log1p(count)
        if last and now - last < RECENT_S:
            score -= RECENT_PENALTY
        scored.append((score, path))
    scored.sort(key=lambda s: (-s[0], s[1]))
    candidates = scored[:TOP_N]

    picked = []
    per_artist = {}
    by_path = {r["path"]: r for r in seed_rows}
    previous = _artist(by_path.get(seeds[-1], seed_rows[-1]))
    while candidates and len(picked) < limit:
        allowed = [
            c for c in candidates
            if per_artist.get(_artist(pool[c[1]]), 0) < MAX_PER_ARTIST and _artist(pool[c[1]]) != previous
        ]
        if not allowed:
            allowed = [c for c in candidates if _artist(pool[c[1]]) != previous] or candidates
        top = max(s for s, _ in allowed)
        choice = rng.choices(allowed, weights=[math.exp((s - top) / 1.5) for s, _ in allowed])[0]
        candidates.remove(choice)
        row = pool[choice[1]]
        artist = _artist(row)
        per_artist[artist] = per_artist.get(artist, 0) + 1
        previous = artist
        picked.append(row)
    return picked
