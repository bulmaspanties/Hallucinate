from PySide6.QtCore import Property, QAbstractListModel, QModelIndex, Qt, Signal, Slot

TRACK_KEYS = [
    "id", "path", "title", "artist", "album", "album_artist", "album_key", "track_no",
    "disc_no", "year", "genre", "duration", "durText", "fmt", "artUrl",
]
ALBUM_KEYS = ["album_key", "album", "album_artist", "year", "n", "duration", "durText", "artUrl"]
ARTIST_KEYS = ["name", "albums", "tracks", "artUrl"]


class DictModel(QAbstractListModel):
    """List model over dicts; roles are fixed by `keys`."""

    countChanged = Signal()

    def __init__(self, keys, parent=None):
        super().__init__(parent)
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
        self.endResetModel()
        self.countChanged.emit()

    @Slot(result="QVariantList")
    def toList(self):
        return list(self._items)

    @Slot(int, result="QVariantMap")
    def get(self, i):
        return dict(self._items[i]) if 0 <= i < len(self._items) else {}
