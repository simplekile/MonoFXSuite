"""MonoFX Suite updates, without bpy (tests load this file on its own).

The add-on is installed by ``MonoFXSuite_Setup.exe`` with the rest of the suite, and a release ships only that
installer (the user's call, 2026-11-19: the add-on ZIP went, the Setup installs Blender too). So the add-on checks the
suite's version against the latest GitHub release and offers the Setup; ``bl_info``'s version, which releases never
moved, is not what decides.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Iterable, Optional

GITHUB_REPO = "simplekile/MonoFXSuite"
RELEASE_API_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
SETUP_ASSET = "MonoFXSuite_Setup.exe"
SUITE_VERSION_FILE = "SUITE_VERSION"  # written into the add-on folder by build/build.ps1 from the suite's VERSION

_VERSION_RE = re.compile(r"v?(\d+)\.(\d+)\.(\d+)")

Version = tuple[int, int, int]


def parse_version(text: str) -> Optional[Version]:
    """``0.1.37`` or ``v0.1.37`` -> (0, 1, 37); None when it is not a version."""
    m = _VERSION_RE.search((text or "").strip())
    return (int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else None


def format_version(version: Version) -> str:
    return ".".join(str(x) for x in version)


def version_files(package_dir: Path, local_appdata: Optional[str] = None) -> list[Path]:
    """Where the installed suite's version is written, first found wins: the stamp the build puts in the add-on
    folder, then the VERSION the installer writes for Monos (always writable)."""
    appdata = local_appdata if local_appdata is not None else os.environ.get("LOCALAPPDATA", "")
    files = [package_dir / SUITE_VERSION_FILE]
    if appdata:
        files.append(Path(appdata) / "Monos" / "tools" / "MonoFXSuite" / "VERSION")
    return files


def installed_suite_version(files: Iterable[Path]) -> Optional[Version]:
    for path in files:
        try:
            version = parse_version(path.read_text(encoding="utf-8"))
        except OSError:
            continue
        if version is not None:
            return version
    return None


def pick_setup_asset(assets: list) -> Optional[dict]:
    """The release's MonoFXSuite_Setup.exe."""
    for asset in assets or []:
        if isinstance(asset, dict) and str(asset.get("name", "")).lower() == SETUP_ASSET.lower():
            return asset
    return None


def compare(installed: Optional[Version], latest: Optional[Version]) -> str:
    """"update", "current", "ahead" or "unknown" (no installed version: the add-on was copied by hand)."""
    if latest is None:
        return "unknown"
    if installed is None:
        return "unknown"
    if latest > installed:
        return "update"
    return "ahead" if installed > latest else "current"
