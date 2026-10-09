import os
import sys
from pathlib import Path


def data_dir() -> Path:
    override = os.environ.get("MUSICPLAYER_DATA")
    if override:
        base = Path(override)
    elif sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming")) / "musicplayer"
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support" / "musicplayer"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "musicplayer"
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
    result = base / "musicplayer"
    result.mkdir(parents=True, exist_ok=True)
    return result


def art_dir() -> Path:
    p = data_dir() / "art"
    p.mkdir(parents=True, exist_ok=True)
    return p


def db_path() -> Path:
    return data_dir() / "library.db"
