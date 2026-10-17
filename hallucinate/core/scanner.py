"""Incremental folder scanner: only new/changed files are parsed."""
import os
import re
import time
from typing import Callable, Optional

from . import cue, tags
from .db import Database

_CUE_SONG = re.compile(r"^(.*\.[A-Za-z0-9]+)#\d+$")
COMMIT_EVERY_S = 0.2  # changes waiting longer than this are saved before the next file is read


class Scanner:
    def __init__(self, db: Database, art_dir, progress: Optional[Callable[[int], None]] = None,
                 should_stop: Optional[Callable[[], bool]] = None):
        self.db = db
        self.art_dir = str(art_dir)
        self.progress = progress
        self.should_stop = should_stop or (lambda: False)
        self._art = {k: v for k, v in db.album_art_map().items() if v and os.path.exists(v)}
        self._seen = 0
        self._hidden = set()

    def scan(self, folders) -> dict:
        stats = {"added": 0, "updated": 0, "removed": 0, "unchanged": 0, "errors": 0, "dirs": []}
        self._hidden = self.db.hidden_paths()  # removed from the library on purpose
        for folder in folders:
            if self.should_stop():
                break
            self._scan_folder(folder, stats)
        self.db.finalize()
        return stats

    def refresh_files(self, paths) -> int:
        """Re-read specific files (after a tag edit) and update their rows. Returns how many were updated."""
        n = 0
        for path in paths:
            t = tags.read_track(path, art_known=lambda k: k in self._art)
            if t is None:
                continue
            self._attach_art(t, os.path.dirname(path))
            self.db.upsert_track(t)
            n += 1
        self.db.finalize()
        self.db.commit()
        return n

    def _scan_folder(self, folder: str, stats: dict):
        if not os.path.isdir(folder):
            return  # unmounted/missing: keep existing entries
        existing = self.db.paths_under(folder)
        # songs of CUE sheets embedded in their file, by file, so an unchanged one isn't read again
        embedded = {}
        for p in existing:
            m = _CUE_SONG.match(p)
            if m:
                embedded.setdefault(m.group(1), []).append(p)
        seen = set()
        pending = 0
        last_commit = time.monotonic()
        visited = set()
        for root, dirs, files in os.walk(folder, followlinks=True):
            real = os.path.realpath(root)
            if real in visited:  # symlink loop / duplicate view of a directory
                dirs[:] = []
                continue
            visited.add(real)
            dirs[:] = sorted(d for d in dirs if not d.startswith("."))
            stats["dirs"].append(root)
            sheets = self._cue_sheets(root, files)
            for name in sorted(files):
                if self.should_stop():
                    self.db.commit()
                    return
                if os.path.splitext(name)[1].lower() not in tags.AUDIO_EXTS:
                    continue
                path = os.path.join(root, name)
                if path in self._hidden:
                    continue
                try:
                    st = os.stat(path)
                except OSError:
                    continue
                self._seen += 1
                if self.progress and self._seen % 25 == 0:
                    self.progress(self._seen)
                if path in sheets:
                    pending += self._scan_cue(path, st, sheets[path], existing, seen, stats)
                    continue
                seen.add(path)
                old = existing.get(path)
                if old and old[0] == st.st_mtime and old[1] == st.st_size:
                    stats["unchanged"] += 1
                    continue
                songs = embedded.get(path, [])
                if not old and songs and all(existing[p] == (st.st_mtime, st.st_size) for p in songs):
                    seen.update(songs)  # a file split by its own CUE sheet, unchanged
                    stats["unchanged"] += len(songs)
                    continue
                if pending and time.monotonic() - last_commit > COMMIT_EVERY_S:
                    # Not while reading a file (a slow or network disk): the library's other writers
                    # (adding a folder, saving a play) would wait on this scan's lock until it's done.
                    self.db.commit()
                    pending, last_commit = 0, time.monotonic()
                t = tags.read_track(path, art_known=lambda k: k in self._art)
                if t is None:
                    stats["errors"] += 1
                    continue
                sheet_text = t.pop("_cuesheet", "")
                if sheet_text:
                    rows = self._embedded_cue_rows(t, sheet_text)
                    if rows:
                        seen.discard(path)
                        for row in rows:
                            self._attach_art(row, root)
                            self.db.upsert_track(row)
                            seen.add(row["path"])
                            stats["updated" if row["path"] in existing else "added"] += 1
                        pending += len(rows)
                        continue
                self._attach_art(t, root)
                self.db.upsert_track(t)
                stats["updated" if old else "added"] += 1
                pending += 1
                if pending >= 200:
                    self.db.commit()
                    pending, last_commit = 0, time.monotonic()
        gone = [p for p in existing if p not in seen]
        if gone:
            self.db.remove_paths(gone)
            stats["removed"] += len(gone)
        self.db.commit()

    @staticmethod
    def _cue_sheets(directory, files):
        """{audio path: (sheet, file entry, sheet mtime)} for the audio files that CUE sheets here split up."""
        audio = [f for f in files if os.path.splitext(f)[1].lower() in tags.AUDIO_EXTS]
        out = {}
        for name in sorted(files):
            if not name.lower().endswith(".cue") or not audio:
                continue
            path = os.path.join(directory, name)
            try:
                mtime = os.stat(path).st_mtime
            except OSError:
                continue
            for target, (sheet, entry) in cue.split_files(path, audio).items():
                out.setdefault(target, (sheet, entry, mtime))
        return out

    def _scan_cue(self, path, st, found, existing, seen, stats) -> int:
        """Add the songs a CUE sheet makes of one audio file. Returns how many rows were written."""
        sheet, entry, cue_mtime = found
        expected = [cue.virtual_path(path, t["number"]) for t in entry["tracks"]]
        mtime = max(st.st_mtime, cue_mtime)
        # A song with no length (a last track past the end of the file) is never stored, so it can't count
        # against "unchanged": editing the sheet or the file changes mtime for every song that is.
        known = [p for p in expected if p in existing]
        if known and all(existing[p] == (mtime, st.st_size) for p in known):
            seen.update(known)
            stats["unchanged"] += len(known)
            return 0
        whole = tags.read_track(path, art_known=lambda k: False)
        if whole is None:
            stats["errors"] += 1
            return 0
        rows = cue.tracks(whole, sheet, entry, cue_mtime)
        art = whole.get("_art")
        for row in rows:
            if art is not None:
                row["_art"] = art
            self._attach_art(row, os.path.dirname(path))
            old = existing.get(row["path"])
            self.db.upsert_track(row)
            seen.add(row["path"])
            stats["updated" if old else "added"] += 1
        return len(rows)

    @staticmethod
    def _embedded_cue_rows(whole, text):
        """Songs from a CUE sheet stored inside the file (the entry splitting it into the most songs)."""
        sheet = cue.parse(text)
        entries = [f for f in sheet["files"] if len(f["tracks"]) >= 2]
        if not entries:
            return []
        entry = max(entries, key=lambda f: len(f["tracks"]))
        art = whole.get("_art")
        rows = cue.tracks(whole, sheet, entry)
        for row in rows:
            row["_art"] = art
        return rows

    def _attach_art(self, t: dict, directory: str):
        key = t["album_key"]
        raw = t.pop("_art", None)
        if key in self._art:
            t["art"] = self._art[key]
            return
        path = None
        chosen = self.db.chosen_art(key)
        if chosen and os.path.isfile(chosen):
            path = chosen  # you picked this one: the file's own picture doesn't replace it
        elif raw:
            path = os.path.join(self.art_dir, key + tags._image_ext(raw))
            from .atomic import write_atomic

            os.makedirs(self.art_dir, exist_ok=True)  # the cover cache may have been cleared
            write_atomic(path, lambda fh: fh.write(raw))  # never a half-written cover, even if stopped
        else:
            path = tags.find_folder_art(directory)
        if path:
            self._art[key] = path
            t["art"] = path
            self.db.set_album_art(key, path)
