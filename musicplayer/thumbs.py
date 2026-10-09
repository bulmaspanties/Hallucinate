"""Cached, size-bucketed cover thumbnails served to QML as ``image://art/<px>/<encoded file url>``.

QML requests run on Qt's image-loader threads (``Image.asynchronous``), so decoding and scaling
large embedded covers never touches the GUI thread. Scaled results are cached on disk."""
import hashlib
import os
from pathlib import Path
from urllib.parse import unquote

from PySide6.QtCore import QSize, Qt, QUrl
from PySide6.QtGui import QImage, QImageReader
from PySide6.QtQuick import QQuickImageProvider

BUCKETS = (64, 128, 256, 512)


def bucket(px: int) -> int:
    return next((b for b in BUCKETS if px <= b), BUCKETS[-1])


class ArtProvider(QQuickImageProvider):
    def __init__(self, cache_dir):
        super().__init__(QQuickImageProvider.ImageType.Image)
        self._dir = Path(cache_dir)
        try:
            self._dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass

    @staticmethod
    def parse(image_id: str):
        size_part, _, rest = image_id.partition("/")
        try:
            px = bucket(int(size_part))
        except ValueError:
            return None, ""
        rest = unquote(rest)
        path = QUrl(rest).toLocalFile() if rest.startswith("file:") else rest
        return px, path

    def _cache_path(self, path: str, px: int, mtime: float) -> Path:
        digest = hashlib.sha1(f"{path}|{mtime}|{px}".encode("utf-8", "surrogateescape")).hexdigest()
        return self._dir / f"{digest}.jpg"

    def requestImage(self, image_id, size, requested_size):
        px, path = self.parse(image_id)
        image = QImage()
        if px and path:
            image = self.load(path, px)
        if image.isNull():
            # Undecodable/missing art: a transparent pixel keeps QML quiet and shows the placeholder.
            image = QImage(1, 1, QImage.Format.Format_ARGB32)
            image.fill(0)
        if not image.isNull():
            size.setWidth(image.width())
            size.setHeight(image.height())
        return image

    def load(self, path: str, px: int) -> QImage:
        try:
            mtime = os.stat(path).st_mtime
        except OSError:
            return QImage()
        cached = self._cache_path(path, px, mtime)
        if cached.exists():
            image = QImage(str(cached))
            if not image.isNull():
                return image
        reader = QImageReader(path)
        reader.setAutoTransform(True)
        native = reader.size()
        if native.isValid() and max(native.width(), native.height()) > px:
            reader.setScaledSize(native.scaled(QSize(px, px), Qt.AspectRatioMode.KeepAspectRatio))
        image = reader.read()
        if image.isNull():
            return image
        if max(image.width(), image.height()) > px:
            image = image.scaled(px, px, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        try:
            tmp = cached.with_suffix(".tmp")
            if image.save(str(tmp), "JPG" if not image.hasAlphaChannel() else "PNG", 88):
                os.replace(tmp, cached)
        except OSError:
            pass
        return image
