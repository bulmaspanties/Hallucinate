"""One-time migration of user data from the pre-rename "Music Player" (musicplayer) install."""
import logging
import shutil
from pathlib import Path

logger = logging.getLogger(__name__)
MARKER = ".migrated-from-musicplayer"
OLD_KEYRING = {"Music Player Last.fm": "Hallucinate Last.fm"}
KEYRING_USERS = ("api_key", "api_secret", "session")


def _is_empty(path: Path) -> bool:
    return not path.exists() or not any(path.iterdir())


def migrate_dir(old: Path, new: Path) -> bool:
    """Move `old` to `new` unless `new` already holds data. Falls back to copying across filesystems."""
    if not old.is_dir() or old == new:
        return False
    try:
        new.parent.mkdir(parents=True, exist_ok=True)
        new.mkdir(parents=True, exist_ok=True)
        for source in old.iterdir():
            target = new / source.name
            if target.exists():
                if source.is_dir() and target.is_dir():
                    migrate_dir(source, target)
                continue
            shutil.move(str(source), str(target))
        if _is_empty(old):
            old.rmdir()
    except OSError as exc:
        logger.warning("Could not move %s to %s: %s", old, new, exc)
        return False
    return True


def migrate_settings(settings_new, config_new: Path) -> int:
    """Copy QSettings from the old organisation/app (file moved with the config dir, or native store)."""
    from PySide6.QtCore import QSettings
    old = None
    legacy_file = config_new / "musicplayer.conf"
    if legacy_file.is_file():
        old = QSettings(str(legacy_file), QSettings.Format.IniFormat)
    else:
        old = QSettings("musicplayer", "musicplayer")
    copied = 0
    if old.allKeys() and not settings_new.allKeys():
        for key in old.allKeys():
            settings_new.setValue(key, old.value(key))
            copied += 1
        settings_new.sync()
    if legacy_file.is_file():
        del old
        try:
            legacy_file.unlink()
        except OSError:
            pass
    return copied


def migrate_keyring() -> int:
    try:
        import keyring
    except ImportError:
        return 0
    moved = 0
    for old_service, new_service in OLD_KEYRING.items():
        for user in KEYRING_USERS:
            try:
                value = keyring.get_password(old_service, user)
                if value and not keyring.get_password(new_service, user):
                    keyring.set_password(new_service, user, value)
                    moved += 1
                if value:
                    keyring.delete_password(old_service, user)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Keyring migration skipped: %s", exc)
                return moved
    return moved


def migrate_legacy(data_new: Path, config_new: Path, old_locations, settings_new=None, cache_new=None) -> dict:
    """Run the one-time migration from the old data/config/cache directories and QSettings."""
    result = {"data": False, "config": False, "cache": False, "settings": 0, "keyring": 0}
    if not old_locations:
        return result
    old_data, old_config = old_locations[:2]
    old_cache = old_locations[2] if len(old_locations) > 2 else None
    marker = data_new / MARKER
    if marker.exists():
        return result
    result["data"] = migrate_dir(old_data, data_new)
    result["config"] = migrate_dir(old_config, config_new)
    if old_cache is not None and cache_new is not None:
        result["cache"] = migrate_dir(old_cache, cache_new)
    if settings_new is not None:
        result["settings"] = migrate_settings(settings_new, config_new)
    result["keyring"] = migrate_keyring()
    try:
        data_new.mkdir(parents=True, exist_ok=True)
        marker.write_text("ok", encoding="utf-8")
    except OSError:
        pass
    return result
