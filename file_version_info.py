"""Generate a PyInstaller version-info resource from version.txt.

Usage (called automatically by main.spec):
    from file_version_info import make_version_info
    version_info = make_version_info()

This embeds proper Windows VERSIONINFO metadata into the .exe so that:
- Windows sees a Company Name / Product Name / Description
- SmartScreen and antivirus heuristics give fewer false positives
- The "Details" tab in Explorer shows real publisher information
"""
from __future__ import annotations

from pathlib import Path
from PyInstaller.utils.win32.versioninfo import (
    FixedFileInfo,
    StringFileInfo,
    StringStruct,
    StringTable,
    VarFileInfo,
    VarStruct,
    VSVersionInfo,
)


def _read_version() -> tuple[str, tuple[int, int, int, int]]:
    version_file = Path(__file__).resolve().parent / "version.txt"
    raw = version_file.read_text(encoding="utf-8").strip().lstrip("vV")
    parts = [int(p) for p in raw.split(".")[:3]]
    while len(parts) < 4:
        parts.append(0)
    return raw, tuple(parts[:4])


def make_version_info() -> VSVersionInfo:
    version_str, (major, minor, patch, build) = _read_version()
    return VSVersionInfo(
        ffi=FixedFileInfo(
            filevers=(major, minor, patch, build),
            prodvers=(major, minor, patch, build),
            mask=0x3F,
            flags=0x0,
            OS=0x40004,        # VOS_NT_WINDOWS32
            fileType=0x1,      # VFT_APP
            subtype=0x0,
        ),
        kids=[
            StringFileInfo([
                StringTable(
                    "040904B0",    # lang=US-English, charset=Unicode
                    [
                        StringStruct("CompanyName", "Delta Dyeing S.A.E."),
                        StringStruct("FileDescription", "Planning — Delta Dyeing PDF-to-Excel Converter"),
                        StringStruct("FileVersion", version_str),
                        StringStruct("InternalName", "Planning"),
                        StringStruct("LegalCopyright", "© Delta Dyeing S.A.E."),
                        StringStruct("OriginalFilename", "Planning.exe"),
                        StringStruct("ProductName", "Planning"),
                        StringStruct("ProductVersion", version_str),
                    ],
                ),
            ]),
            VarFileInfo([VarStruct("Translation", [0x0409, 0x04B0])]),
        ],
    )


def make_updater_version_info() -> VSVersionInfo:
    version_str, (major, minor, patch, build) = _read_version()
    return VSVersionInfo(
        ffi=FixedFileInfo(
            filevers=(major, minor, patch, build),
            prodvers=(major, minor, patch, build),
            mask=0x3F,
            flags=0x0,
            OS=0x40004,
            fileType=0x1,
            subtype=0x0,
        ),
        kids=[
            StringFileInfo([
                StringTable(
                    "040904B0",
                    [
                        StringStruct("CompanyName", "Delta Dyeing S.A.E."),
                        StringStruct("FileDescription", "Planning Application Updater"),
                        StringStruct("FileVersion", version_str),
                        StringStruct("InternalName", "PlanningUpdater"),
                        StringStruct("LegalCopyright", "© Delta Dyeing S.A.E."),
                        StringStruct("OriginalFilename", "PlanningUpdater.exe"),
                        StringStruct("ProductName", "Planning"),
                        StringStruct("ProductVersion", version_str),
                    ],
                ),
            ]),
            VarFileInfo([VarStruct("Translation", [0x0409, 0x04B0])]),
        ],
    )
