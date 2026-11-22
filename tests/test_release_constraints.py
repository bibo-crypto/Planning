"""constraints-release.txt must agree with requirements.txt (a pin outside the allowed range would break `pip install -c`)."""
from pathlib import Path

import pytest

packaging = pytest.importorskip("packaging")
from packaging.requirements import Requirement          # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def _requirements(name):
    lines = (ROOT / name).read_text(encoding="utf-8").splitlines()
    return [Requirement(line.split("#")[0].strip()) for line in lines
            if line.split("#")[0].strip() and not line.lstrip().startswith(("-r", "-c"))]


def test_every_pin_is_exact_and_inside_the_range_requirements_txt_allows():
    allowed = {r.name.lower().replace("_", "-"): r for r in _requirements("requirements.txt")}
    pins = _requirements("constraints-release.txt")
    assert pins, "constraints-release.txt is empty"
    problems = []
    for pin in pins:
        specs = list(pin.specifier)
        if len(specs) != 1 or specs[0].operator != "==":
            problems.append(f"{pin.name}: not an exact == pin ({pin.specifier})")
            continue
        wanted = allowed.get(pin.name.lower().replace("_", "-"))
        if wanted and not wanted.specifier.contains(specs[0].version, prereleases=True):
            problems.append(f"{pin.name}=={specs[0].version} is outside requirements.txt ({wanted.specifier})")
    assert problems == []


def test_every_direct_requirement_is_pinned():
    pinned = {r.name.lower().replace("_", "-") for r in _requirements("constraints-release.txt")}
    missing = [r.name for r in _requirements("requirements.txt") if r.name.lower().replace("_", "-") not in pinned]
    assert missing == []
