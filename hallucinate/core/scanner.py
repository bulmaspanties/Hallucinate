"""Incremental folder scanner: only new/changed files are parsed."""
import os
from typing import Callable, Optional

from . import tags
from .db import Database


class Scanner:
    def __init__(self, db: Database, art_dir, progress: Optional[Callable[[int], None]] = None,
                 should_stop: Optional[Callable[[], bool]] = None):
        self.db = db
        self.art_dir = str(art_dir)
        self.progress = progress
        self.should_stop = should_stop or (lambda: False)
        self._art = {k: v for k, v in db.album_art_map().items() if v and os.path.exists(v)}
        self._seen = 0

    def scan(self, folders) -> dict:
        stats = {"added": 0, "updated": 0, "removed": 0, "unchanged": 0, "errors": 0, "dirs": []}
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
        seen = set()
        pending = 0
        visited = set()
        for root, dirs, files in os.walk(folder, followlinks=True):
            real = os.path.realpath(root)
            if real in visited:  # symlink loop / duplicate view of a directory
                dirs[:] = []
                continue
            visited.add(real)
            dirs[:] = sorted(d for d in dirs if not d.startswith("."))
            stats["dirs"].append(root)
            for name in sorted(files):
                if self.should_stop():
                    self.db.commit()
                    return
                if os.path.splitext(name)[1].lower() not in tags.AUDIO_EXTS:
                    continue
                path = os.path.join(root, name)
                try:
                    st = os.stat(path)
                except OSError:
                    continue
                seen.add(path)
                self._seen += 1
                if self.progress and self._seen % 25 == 0:
                    self.progress(self._seen)
                old = existing.get(path)
                if old and old[0] == st.st_mtime and old[1] == st.st_size:
                    stats["unchanged"] += 1
                    continue
                t = tags.read_track(path, art_known=lambda k: k in self._art)
                if t is None:
                    stats["errors"] += 1
                    continue
                self._attach_art(t, root)
                self.db.upsert_track(t)
                stats["updated" if old else "added"] += 1
                pending += 1
                if pending >= 200:
                    self.db.commit()
                    pending = 0
        gone = [p for p in existing if p not in seen]
        if gone:
            self.db.remove_paths(gone)
            stats["removed"] += len(gone)
        self.db.commit()

    def _attach_art(self, t: dict, directory: str):
        key = t["album_key"]
        raw = t.pop("_art", None)
        if key in self._art:
            t["art"] = self._art[key]
            return
        path = None
        if raw:
            path = os.path.join(self.art_dir, key + tags._image_ext(raw))
            with open(path, "wb") as fh:
                fh.write(raw)
        else:
            path = tags.find_folder_art(directory)
        if path:
            self._art[key] = path
            t["art"] = path
            self.db.set_album_art(key, path)
