"""Check a release ZIP BEFORE (or after) it is uploaded to GitHub, the way the in-app updater will check it.

    python tools/check_release_zip.py dist\\Planning.zip
    python tools/check_release_zip.py https://github.com/bibo-crypto/Planning/releases/download/v1.3.8/Planning.zip --tag v1.3.8

Exit code 0 = the updater will accept it, 1 = it will refuse it (the reasons are printed).  Standard library only.

The updater refuses, and this tool reports: no Planning.exe; no ``_internal\\python3*.dll`` (an update made of Planning.exe
alone would leave the program unable to start). The installed version comes from the GitHub release tag, so the ZIP itself
is independent of the number in its name. ``build.bat`` creates the accepted, version-independent ``dist\\Planning.zip``.
"""
from __future__ import annotations

import argparse
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath

MIN_PLAUSIBLE_BYTES = 40 * 1024 * 1024        # a whole PyInstaller folder is far bigger than the 14 MB Planning.exe alone


def check_zip(path: Path, tag: str | None = None) -> list[str]:
    """Return the problems that make the updater refuse *path* (an empty list means it will accept it)."""
    try:
        archive = zipfile.ZipFile(path)
    except (zipfile.BadZipFile, OSError) as exc:
        return [f"not a readable ZIP file: {exc}"]
    with archive:
        names = [n for n in archive.namelist() if not n.endswith("/")]
        lowered = {PurePosixPath(n.replace("\\", "/")).as_posix().lower(): n for n in names}
        exe_entries = [low for low in lowered if low in ("planning.exe",) or low.count("/") == 1 and low.endswith("/planning.exe")]
        if not exe_entries:
            return ["Planning.exe is not at the top of the ZIP (the ZIP must hold the CONTENTS of dist\\Planning)"]
        prefix = exe_entries[0][: -len("planning.exe")]
        problems = []
        if archive.getinfo(lowered[exe_entries[0]]).file_size == 0:
            problems.append("Planning.exe is empty")
        dlls = [low for low in lowered if low.startswith(prefix + "_internal/") and PurePosixPath(low).name.startswith("python3")
                and low.endswith(".dll") and low.count("/") == prefix.count("/") + 1]
        if not dlls:
            problems.append("_internal\\python3*.dll is missing: the ZIP holds only %d file(s) (%s), but the whole program folder is needed "
                            "- create it with \"build.bat\"" % (len(names), ", ".join(PurePosixPath(n).name for n in names[:3])))
        total = sum(i.file_size for i in archive.infolist())
        if total < MIN_PLAUSIBLE_BYTES:
            problems.append(f"the ZIP unpacks to only {total / 1024 / 1024:.1f} MB; a complete program folder is much bigger")
        return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("source", help="a ZIP file, or the https URL of the release asset")
    parser.add_argument("--tag", help="the release tag the ZIP is published under, e.g. v1.3.6")
    args = parser.parse_args(argv)
    path = Path(args.source)
    temp = None
    if args.source.lower().startswith(("http://", "https://")):
        temp = tempfile.NamedTemporaryFile(suffix=".zip", delete=False)
        temp.close()
        print(f"Downloading {args.source} ...")
        urllib.request.urlretrieve(args.source, temp.name)            # noqa: S310 -- the owner passes his own release URL
        path = Path(temp.name)
    try:
        problems = check_zip(path, args.tag)
    finally:
        if temp is not None:
            Path(temp.name).unlink(missing_ok=True)
    if problems:
        print("The updater will REFUSE this ZIP:")
        for problem in problems:
            print("  -", problem)
        return 1
    print("OK: the updater will accept this ZIP.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
