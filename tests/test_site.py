"""The website build (scripts/build_site.py): every placeholder filled, every local file present."""
import re
import sys
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import build_site  # noqa: E402


class _Refs(HTMLParser):
    def __init__(self):
        super().__init__()
        self.refs = []

    def handle_starttag(self, tag, attrs):
        for name, value in attrs:
            if name in ("src", "href", "srcset") and value:
                self.refs.append(value)


def test_site_builds_with_local_assets(tmp_path, monkeypatch):
    monkeypatch.setenv("SITE_VERSION", build_site.project_version())
    out = build_site.build(tmp_path / "site")
    page = (out / "index.html").read_text(encoding="utf-8")
    assert "{{" not in page and "}}" not in page
    assert f"Download Hallucinate {build_site.project_version()}" in page
    parser = _Refs()
    parser.feed(page)
    local = {re.split(r"[?#]", r)[0] for r in parser.refs if not r.startswith(("http", "#", "mailto:"))}
    assert local, "no local references found"
    missing = [r for r in local if not (out / r).is_file()]
    assert not missing, missing
    assert (out / ".nojekyll").exists()


def test_changelog_rendering():
    html = build_site.render_changes(
        "### Added\n- Radio mode with `code` and a [link](https://example.com).\n  Wrapped line.\n"
        "- Escapes <script>\n\n### Fixed\n- A fix"
    )
    assert html.count("<h3>") == 2 and html.count("<li>") == 3
    assert "<code>code</code>" in html and '<a href="https://example.com">link</a>' in html
    assert "Wrapped line." in html and "&lt;script&gt;" in html


def test_released_version_override(monkeypatch):
    monkeypatch.setenv("SITE_VERSION", "9.9.9")
    assert build_site.released_version() == "9.9.9"
