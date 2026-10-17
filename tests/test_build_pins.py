"""The release builds install pinned, checksummed versions: the pins must cover what the app depends on."""
import re
from pathlib import Path

import pytest

tomllib = pytest.importorskip("tomllib")  # Python 3.11+

ROOT = Path(__file__).resolve().parent.parent


def _name(requirement):
    return re.split(r"[<>=!~; \[]", requirement.strip(), maxsplit=1)[0].lower().replace("_", "-").replace(".", "-")


def test_every_dependency_is_pinned_with_a_checksum():
    deps = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["dependencies"]
    lock = (ROOT / "packaging" / "build-requirements.txt").read_text()
    pinned = {m.group(1).lower() for m in re.finditer(r"^([A-Za-z0-9_.-]+)==", lock, re.M)}
    missing = {_name(d) for d in deps} - pinned
    assert not missing, f"not in packaging/build-requirements.txt: {sorted(missing)}"
    for block in re.split(r"\n(?=[A-Za-z])", lock.split("\n", 4)[-1]):
        if "==" in block:
            assert "--hash=sha256:" in block, block.splitlines()[0]
