import os
import sys
from pathlib import Path


def _data_base() -> Path:
    if sys.platform == "win32":
        return Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support"
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))


def _config_base() -> Path:
    override = os.environ.get("XDG_CONFIG_HOME")
    if override:
        return Path(override)
    if sys.platform == "win32":
        return Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support"
    return Path.home() / ".config"


def _cache_base() -> Path:
    if sys.platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Caches"
    return Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))


def legacy_locations() -> tuple:
    """Old Music Player paths, or None when data is explicitly redirected for isolation."""
    if os.environ.get("HALLUCINATE_DISABLE_LEGACY_MIGRATION"):
        return None
    return (_data_base() / "musicplayer", _config_base() / "musicplayer", _cache_base() / "musicplayer")


def data_dir() -> Path:
    override = os.environ.get("HALLUCINATE_DATA")
    if override:
        base = Path(override)
    elif sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming")) / "hallucinate"
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support" / "hallucinate"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "hallucinate"
    base.mkdir(parents=True, exist_ok=True)
    return base


def config_dir() -> Path:
    override = os.environ.get("XDG_CONFIG_HOME")
    if override:
        base = Path(override)
    elif sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path.home() / ".config"
    result = base / "hallucinate"
    result.mkdir(parents=True, exist_ok=True)
    return result


def cache_dir() -> Path:
    result = _cache_base() / "hallucinate"
    result.mkdir(parents=True, exist_ok=True)
    return result


def art_dir() -> Path:
    p = data_dir() / "art"
    p.mkdir(parents=True, exist_ok=True)
    return p


def db_path() -> Path:
    return data_dir() / "library.db"
