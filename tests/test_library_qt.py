import pytest
from conftest import make_mp3, wait_for


def test_background_scan_and_directory_watcher(qapp, tmp_path):
    pytest.importorskip("PySide6.QtCore", exc_type=ImportError)
    from hallucinate.library import Library

    root = tmp_path / "watched"
    root.mkdir()
    db_path = tmp_path / "library.db"
    art_dir = tmp_path / "art"
    art_dir.mkdir()
    library = Library(db_path, art_dir)
    try:
        library.addFolder(str(root))
        assert wait_for(lambda: not library.scanning, timeout=10)
        assert str(root) in library._watcher.directories()
        make_mp3(root / "new.mp3", "Watcher Song", "Watcher Artist", "Watcher Album")
        assert wait_for(lambda: library.trackCount == 1, timeout=10)

        (root / "new.mp3").unlink()
        assert wait_for(lambda: library.trackCount == 0, timeout=10)
        assert wait_for(lambda: not library.scanning, timeout=5)
    finally:
        assert wait_for(lambda: not library.scanning, timeout=10)
        library.shutdown()
