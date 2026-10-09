import difflib

from PySide6.QtCore import Property, QAbstractListModel, QModelIndex, Qt, Signal, Slot

TRACK_KEYS = [
    "id", "path", "title", "artist", "album", "album_artist", "album_key", "track_no",
    "disc_no", "year", "genre", "duration", "durText", "fmt", "artUrl",
    "codec", "bitrate",
]
ALBUM_KEYS = ["album_key", "album", "album_artist", "year", "n", "duration", "durText", "artUrl"]
ARTIST_KEYS = ["name", "albums", "tracks", "artUrl"]


MAX_DIFF_OPS = 300


def compute_ops(old_keys, new_keys, limit=MAX_DIFF_OPS):
    """Row operations turning `old_keys` into `new_keys`, or None when a reset is cheaper.

    Pure function so it can run on a worker thread."""
    if old_keys == new_keys:
        return []
    ops = [
        op
        for op in difflib.SequenceMatcher(None, old_keys, new_keys, autojunk=False).get_opcodes()
        if op[0] != "equal"
    ]
    return ops if len(ops) <= limit else None


class DictModel(QAbstractListModel):
    """List model over dicts; roles are fixed by `keys`.

    `key_field` names a unique field used to diff updates so that a rescan only inserts/removes the
    changed rows instead of resetting the whole view (which would lose scroll position)."""

    countChanged = Signal()

    def __init__(self, keys, parent=None, key_field=None):
        super().__init__(parent)
        self._key_field = key_field
        self.revision = 0
        base = int(Qt.ItemDataRole.UserRole) + 1
        self._names = list(keys)
        self._roles = {base + i: k.encode() for i, k in enumerate(keys)}
        self._items = []

    def roleNames(self):
        return self._roles

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self._items)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not 0 <= index.row() < len(self._items):
            return None
        name = self._roles.get(role)
        return self._items[index.row()].get(name.decode()) if name else None

    @Property(int, notify=countChanged)
    def count(self):
        return len(self._items)

    def set_items(self, items):
        self.beginResetModel()
        self._items = list(items)
        self.revision += 1
        self.endResetModel()
        self.countChanged.emit()

    def snapshot_keys(self):
        """(revision, keys) for computing a diff off-thread; None when diffing is unavailable."""
        if not self._key_field:
            return None
        f = self._key_field
        return self.revision, [i[f] for i in self._items]

    def update_items(self, items, ops=None, revision=None):
        """Apply `items` using precomputed `ops` when they still match this model, else reset."""
        items = list(items)
        if ops is None or revision != self.revision:
            self.set_items(items)
            return
        for tag, i1, i2, j1, j2 in reversed(ops):
            if tag in ("delete", "replace") and i2 > i1:
                self.beginRemoveRows(QModelIndex(), i1, i2 - 1)
                del self._items[i1:i2]
                self.endRemoveRows()
            if tag in ("insert", "replace") and j2 > j1:
                self.beginInsertRows(QModelIndex(), i1, i1 + (j2 - j1) - 1)
                self._items[i1:i1] = items[j1:j2]
                self.endInsertRows()
        changed = self._items != items
        self._items = items
        self.revision += 1
        if changed and items:
            self.dataChanged.emit(self.index(0), self.index(len(items) - 1))
        self.countChanged.emit()

    def items(self):
        return self._items

    @Slot(result="QVariantList")
    def toList(self):
        return list(self._items)

    @Slot(int, result="QVariantMap")
    def get(self, i):
        return dict(self._items[i]) if 0 <= i < len(self._items) else {}
