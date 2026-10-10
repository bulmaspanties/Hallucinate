"""Rule sets for smart playlists, compiled to SQL against the library.

A rule set is plain JSON so it can be stored in the database and edited from QML:

    {"match": "all" | "any",
     "rules": [{"field": "liked", "op": "is_true"},
               {"field": "last_played", "op": "not_in_last", "value": 60}],
     "sort": "random", "limit": 0}

Only whitelisted fields, operators and sort orders are accepted; values are always bound as SQL parameters.
Text comparisons are case- and accent-insensitive. Radio mode can use the same rules to restrict its picks."""
import json
import time

from .db import fold

# field -> (kind, SQL expression, label)
FIELDS = {
    "title": ("text", "t.title", "Title"),
    "artist": ("text", "t.artist", "Artist"),
    "album": ("text", "t.album", "Album"),
    "album_artist": ("text", "t.album_artist", "Album artist"),
    "genre": ("text", "t.genre", "Genre"),
    "format": ("text", "t.codec", "Format"),
    "path": ("text", "t.path", "File path"),
    "year": ("number", "t.year", "Year"),
    "duration": ("number", "t.duration / 60.0", "Length (minutes)"),
    "bitrate": ("number", "t.bitrate / 1000.0", "Bitrate (kb/s)"),
    "plays": ("number", "COALESCE(p.count, 0)", "Play count"),
    "added": ("date", "t.added", "Date added"),
    "last_played": ("date", "p.last", "Last played"),
    "liked": ("bool", "l.path IS NOT NULL", "Liked"),
}

# kind -> {op: label}
OPS = {
    "text": {"contains": "contains", "not_contains": "does not contain", "is": "is", "is_not": "is not",
             "starts_with": "starts with", "ends_with": "ends with"},
    "number": {"eq": "is", "ne": "is not", "gt": "is more than", "lt": "is less than",
               "ge": "is at least", "le": "is at most", "between": "is between"},
    "date": {"in_last": "in the last (days)", "not_in_last": "not in the last (days)", "never": "never"},
    "bool": {"is_true": "is yes", "is_false": "is no"},
}

SORTS = {
    "random": ("Random", "random()"),
    "title": ("Title", "t.s_title, t.s_artist"),
    "artist": ("Artist", "t.s_artist, t.s_album, t.disc_no, t.track_no"),
    "album": ("Album", "t.s_album, t.disc_no, t.track_no"),
    "year_desc": ("Newest first", "t.year DESC, t.s_album, t.disc_no, t.track_no"),
    "year_asc": ("Oldest first", "t.year, t.s_album, t.disc_no, t.track_no"),
    "added_desc": ("Recently added", "t.added DESC"),
    "plays_desc": ("Most played", "COALESCE(p.count, 0) DESC, t.s_title"),
    "last_played_desc": ("Recently played", "p.last IS NULL, p.last DESC"),
    "last_played_asc": ("Least recently played", "p.last IS NOT NULL, p.last"),
}

FROM = "FROM tracks t LEFT JOIN plays p ON p.path = t.path LEFT JOIN likes l ON l.path = t.path"
MAX_RULES = 50
MAX_LIMIT = 100_000
DAY_S = 86_400


def _like(text):
    return "%" + text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def _number(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"not a number: {value!r}") from None
    if number != number or number in (float("inf"), float("-inf")):
        raise ValueError(f"not a number: {value!r}")
    return number


def normalize(rules):
    """Validated copy of a rule set (dict or JSON text); raises ValueError when it is malformed."""
    if isinstance(rules, str):
        try:
            rules = json.loads(rules) if rules.strip() else {}
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid rules: {exc}") from None
    if not isinstance(rules, dict):
        raise ValueError("rules must be an object")
    match = rules.get("match", "all")
    if match not in ("all", "any"):
        raise ValueError(f"unknown match mode: {match!r}")
    items = rules.get("rules", [])
    if not isinstance(items, list) or len(items) > MAX_RULES:
        raise ValueError("rules must be a list of at most 50 rules")
    clean = []
    for rule in items:
        if not isinstance(rule, dict) or rule.get("field") not in FIELDS:
            raise ValueError(f"unknown field in rule: {rule!r}")
        kind = FIELDS[rule["field"]][0]
        op = rule.get("op")
        if op not in OPS[kind] or (op == "never" and rule["field"] != "last_played"):
            raise ValueError(f"operator {op!r} does not apply to {rule['field']}")
        value = rule.get("value")
        if kind == "text":
            value = "" if value is None else str(value)
        elif op == "between":
            if not isinstance(value, (list, tuple)) or len(value) != 2:
                raise ValueError("between needs two values")
            value = sorted(_number(v) for v in value)
        elif kind in ("number", "date") and op != "never":
            value = _number(value)
        else:
            value = None
        clean.append({"field": rule["field"], "op": op, "value": value})
    sort = rules.get("sort") or "artist"
    if sort not in SORTS:
        raise ValueError(f"unknown sort: {sort!r}")
    try:
        limit = int(rules.get("limit") or 0)
    except (TypeError, ValueError):
        raise ValueError("limit must be a whole number") from None
    return {"match": match, "rules": clean, "sort": sort, "limit": max(0, min(limit, MAX_LIMIT))}


def _condition(rule, now):
    kind, expr, _label = FIELDS[rule["field"]]
    op, value = rule["op"], rule["value"]
    if kind == "text":
        folded = fold(value)
        if op == "contains":
            return f"fold({expr}) LIKE ? ESCAPE '\\'", [_like(folded)]
        if op == "not_contains":
            return f"fold({expr}) NOT LIKE ? ESCAPE '\\'", [_like(folded)]
        if op == "is":
            return f"fold({expr}) = ?", [folded]
        if op == "is_not":
            return f"fold({expr}) != ?", [folded]
        if op == "starts_with":
            return f"fold({expr}) LIKE ? ESCAPE '\\'", [_like(folded)[1:]]
        return f"fold({expr}) LIKE ? ESCAPE '\\'", [_like(folded)[:-1]]
    if kind == "number":
        if op == "between":
            return f"{expr} BETWEEN ? AND ?", list(value)
        sql_op = {"eq": "=", "ne": "!=", "gt": ">", "lt": "<", "ge": ">=", "le": "<="}[op]
        return f"{expr} {sql_op} ?", [value]
    if kind == "date":
        if op == "never":
            return f"{expr} IS NULL", []
        since = now - value * DAY_S
        if op == "in_last":
            return f"{expr} >= ?", [since]
        return f"({expr} IS NULL OR {expr} < ?)", [since]  # never played counts as "not in the last N days"
    return (expr if op == "is_true" else f"NOT ({expr})"), []


def compile_where(rules, now=None):
    """(SQL condition, params) selecting the tracks a rule set matches; use with FROM."""
    rules = normalize(rules)
    now = time.time() if now is None else now
    parts = [_condition(rule, now) for rule in rules["rules"]]
    if not parts:
        return "1", []
    joiner = " AND " if rules["match"] == "all" else " OR "
    return "(" + joiner.join(f"({sql})" for sql, _ in parts) + ")", [p for _, params in parts for p in params]


def matching_tracks(db, rules, now=None):
    """Tracks (dicts, with a `plays` count) matching a rule set, sorted and limited as it says."""
    rules = normalize(rules)
    where, params = compile_where(rules, now)
    sql = f"SELECT t.*, COALESCE(p.count, 0) AS plays {FROM} WHERE {where} ORDER BY {SORTS[rules['sort']][1]}"
    if rules["limit"]:
        sql += " LIMIT ?"
        params = [*params, rules["limit"]]
    return db._rows(sql, params)


def count_matching(db, rules, now=None):
    rules = normalize(rules)
    where, params = compile_where(rules, now)
    total = db.conn.execute(f"SELECT COUNT(*) {FROM} WHERE {where}", params).fetchone()[0]
    return min(total, rules["limit"]) if rules["limit"] else total


def _format_number(value):
    return str(int(value)) if float(value).is_integer() else f"{value:g}"


def describe(rules):
    """Short human-readable summary, e.g. "Liked is yes and Last played not in the last 60 days"."""
    rules = normalize(rules)
    parts = []
    for rule in rules["rules"]:
        kind, _expr, label = FIELDS[rule["field"]]
        op_label = OPS[kind][rule["op"]]
        value = rule["value"]
        if kind == "date" and rule["op"] != "never":
            op_label = op_label.replace("(days)", f"{_format_number(value)} days")
            parts.append(f"{label} {op_label}")
        elif rule["op"] == "never":
            parts.append("Never played")
        elif kind == "bool":
            parts.append(f"{label} {op_label}")
        elif rule["op"] == "between":
            parts.append(f"{label} {op_label} {_format_number(value[0])} and {_format_number(value[1])}")
        elif kind == "number":
            parts.append(f"{label} {op_label} {_format_number(value)}")
        else:
            parts.append(f'{label} {op_label} "{value}"')
    text = (" and " if rules["match"] == "all" else " or ").join(parts) or "All songs"
    text += f" · {SORTS[rules['sort']][0].lower()}"
    if rules["limit"]:
        text += f" · up to {rules['limit']} songs"
    return text


def schema():
    """Fields, operators and sorts for the QML editor."""
    return {
        "fields": [{"key": k, "label": v[2], "kind": v[0]} for k, v in FIELDS.items()],
        "ops": {kind: [{"key": k, "label": v} for k, v in ops.items()] for kind, ops in OPS.items()},
        "sorts": [{"key": k, "label": v[0]} for k, v in SORTS.items()],
    }
