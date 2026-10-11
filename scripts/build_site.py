"""Build the website into a folder: python scripts/build_site.py [OUT] (default: _site).

Fills site/index.html with the current version, its release date and its CHANGELOG entry, and copies the
README screenshots, logo and social preview next to it. The Pages workflow runs this on every release and
whenever the site, screenshots or changelog change, so the site always matches the latest release."""
import datetime
import html
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = "https://github.com/bulmaspanties/Hallucinate"
SITE_URL = os.environ.get("SITE_URL", "https://bulmaspanties.github.io/Hallucinate/")
WAVE_HEIGHTS = [10, 18, 28, 40, 26, 48, 34, 56, 34, 48, 26, 40, 28, 18, 10]


def project_version():
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    return re.search(r'^version\s*=\s*"([^"]+)"', text, re.M).group(1)


def released_version():
    """The newest vX.Y.Z tag, so a version bump merged ahead of its release doesn't advertise it early.

    Falls back to pyproject.toml when there are no tags (e.g. a shallow checkout); SITE_VERSION overrides."""
    if os.environ.get("SITE_VERSION"):
        return os.environ["SITE_VERSION"]
    try:
        tags = subprocess.run(["git", "tag", "--list", "v[0-9]*", "--sort=-v:refname"], cwd=ROOT,
                              capture_output=True, text=True, check=True).stdout.split()
    except (OSError, subprocess.CalledProcessError):
        tags = []
    return tags[0][1:] if tags else project_version()


def changelog_entry(version):
    """(date, markdown body) of the CHANGELOG section for `version`."""
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    match = re.search(rf"^## \[{re.escape(version)}\](?: - (\S+))?\s*$(.*?)(?=^## \[|\Z)", text, re.M | re.S)
    if not match:
        raise SystemExit(f"CHANGELOG.md has no section for {version}")
    return match.group(1), match.group(2).strip()


def inline(text):
    """Markdown inline code and links to HTML; everything else is escaped."""
    out = []
    for part in re.split(r"(`[^`]+`|\[[^\]]+\]\([^)]+\))", text):
        if part.startswith("`") and part.endswith("`"):
            out.append(f"<code>{html.escape(part[1:-1])}</code>")
        elif part.startswith("[") and "](" in part:
            label, url = re.match(r"\[([^\]]+)\]\(([^)]+)\)", part).groups()
            out.append(f'<a href="{html.escape(url, quote=True)}">{html.escape(label)}</a>')
        else:
            out.append(html.escape(part).replace("**", ""))
    return "".join(out)


def render_changes(markdown):
    """The small subset of Markdown the changelog uses: ### headings and "- " bullets (wrapped lines allowed)."""
    lines, items, out = markdown.splitlines(), [], []

    def flush():
        if items:
            out.append("<ul>" + "".join(f"<li>{inline(i)}</li>" for i in items) + "</ul>")
            items.clear()

    for line in lines:
        if line.startswith("### "):
            flush()
            out.append(f"<h3>{html.escape(line[4:].strip())}</h3>")
        elif line.startswith("- "):
            items.append(line[2:].strip())
        elif line.strip() and items:
            items[-1] += " " + line.strip()  # continuation of a wrapped bullet
    flush()
    return "\n        ".join(out)


def pretty_date(iso):
    if not iso:
        return "latest release"
    date = datetime.date.fromisoformat(iso)
    return f"{date:%B} {date.day}, {date.year}"


def build(out):
    out = Path(out)
    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(ROOT / "site", out)
    shutil.copytree(ROOT / "docs" / "screenshots", out / "screenshots")
    shutil.copy2(ROOT / "assets" / "logo" / "social-preview.png", out / "img" / "social-preview.png")

    version = released_version()
    date, changes = changelog_entry(version)
    wave = "".join(f'<b style="height:{h}px;animation-delay:-{i * 0.13:.2f}s"></b>'
                   for i, h in enumerate(WAVE_HEIGHTS))
    values = {
        "VERSION": version, "RELEASE_DATE": pretty_date(date), "CHANGES": render_changes(changes),
        "WAVE": wave, "REPO": REPO, "RELEASES": f"{REPO}/releases", "SITE_URL": SITE_URL,
    }
    page = (out / "index.html").read_text(encoding="utf-8")
    page = re.sub(r"\{\{([A-Z_]+)\}\}", lambda m: values[m.group(1)], page)
    (out / "index.html").write_text(page, encoding="utf-8")
    (out / ".nojekyll").write_text("", encoding="utf-8")  # serve files as-is
    return out


if __name__ == "__main__":
    print(build(sys.argv[1] if len(sys.argv) > 1 else ROOT / "_site"))
