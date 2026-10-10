# Contributing

Thanks for helping improve Hallucinate!

## Development setup
```sh
python -m venv .venv && . .venv/bin/activate
pip install -e '.[test]' ruff
```
Tests need `ffmpeg` on `PATH` (they generate real audio files).

## Before opening a PR
```sh
ruff check .
QT_QPA_PLATFORM=offscreen pytest -q
```
- Keep changes focused; add tests for new behavior.
- Tests fail if they leave a QObject in a reference cycle (it would otherwise be garbage-collected
  at a random point and can crash later tests). Shut down and `deleteLater()` the Qt objects a test
  creates, and monkeypatch classes rather than instances (see `tests/test_shell.py`).
- Update `README.md` and `CHANGELOG.md` for user-visible changes.
- Run through relevant parts of [docs/manual-qa.md](docs/manual-qa.md) for playback,
  MPRIS, Last.fm or theme changes.
- Never commit credentials. Last.fm keys/secrets live in the system keyring or
  `HALLUCINATE_LASTFM_API_KEY` / `HALLUCINATE_LASTFM_API_SECRET`.

## Themes
New built-in themes are JSON files in `hallucinate/themes/` (see the README theming guide).

## Conduct
Participation is governed by the [Code of Conduct](CODE_OF_CONDUCT.md).
