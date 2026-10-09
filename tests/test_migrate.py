def test_migrates_user_data_and_settings(tmp_path, monkeypatch):
    import keyring
    from PySide6.QtCore import QSettings

    from hallucinate.migrate import migrate_legacy

    old_data = tmp_path / "data" / "musicplayer"
    old_config = tmp_path / "config" / "musicplayer"
    old_cache = tmp_path / "cache" / "musicplayer"
    new_data = tmp_path / "data" / "hallucinate"
    new_config = tmp_path / "config" / "hallucinate"
    new_cache = tmp_path / "cache" / "hallucinate"
    old_data.mkdir(parents=True)
    old_config.mkdir(parents=True)
    old_cache.mkdir(parents=True)
    (old_data / "library.db").write_bytes(b"library")
    (old_config / "preferences.json").write_text('{"theme":"Dark"}', encoding="utf-8")
    (old_cache / "cover.png").write_bytes(b"cover")
    old_settings = QSettings(str(old_config / "musicplayer.conf"), QSettings.Format.IniFormat)
    old_settings.setValue("volume", 0.6)
    old_settings.sync()

    class Settings:
        values = {}

        def allKeys(self):
            return list(self.values)

        def setValue(self, key, value):
            self.values[key] = value

        def value(self, key):
            return self.values.get(key)

        def sync(self):
            pass

    current = Settings()
    secrets = {("Music Player Last.fm", "session"): "old-session"}
    monkeypatch.setattr(keyring, "get_password", lambda service, user: secrets.get((service, user)))
    monkeypatch.setattr(keyring, "set_password", lambda service, user, value: secrets.__setitem__((service, user), value))
    monkeypatch.setattr(keyring, "delete_password", lambda service, user: secrets.pop((service, user), None))

    result = migrate_legacy(new_data, new_config, (old_data, old_config, old_cache), current, new_cache)

    assert result["data"] and result["config"] and result["cache"] and result["settings"] == 1
    assert (new_data / "library.db").read_bytes() == b"library"
    assert (new_config / "preferences.json").read_text(encoding="utf-8") == '{"theme":"Dark"}'
    assert float(current.value("volume")) == 0.6
    assert (new_cache / "cover.png").read_bytes() == b"cover"
    assert secrets[("Hallucinate Last.fm", "session")] == "old-session"
    assert not old_data.exists()
    assert (new_data / ".migrated-from-musicplayer").exists()


def test_migration_does_not_overwrite_new_data(tmp_path):
    from hallucinate.migrate import migrate_legacy

    old = tmp_path / "old"
    new = tmp_path / "new"
    old.mkdir()
    new.mkdir()
    (old / "library.db").write_text("legacy", encoding="utf-8")
    (new / "library.db").write_text("current", encoding="utf-8")

    migrate_legacy(new, tmp_path / "config-new", (old, tmp_path / "missing-config"))

    assert (new / "library.db").read_text(encoding="utf-8") == "current"
    assert (old / "library.db").read_text(encoding="utf-8") == "legacy"
