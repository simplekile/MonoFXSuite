#!/usr/bin/env python3
"""Build Blender install ZIP from monofx_pipeline_blender add-on sources."""

from __future__ import annotations

import argparse
import re
import shutil
import sys
import zipfile
from pathlib import Path

_PKG_ROOT = Path(__file__).resolve().parents[1]
_ADDON_DIR = _PKG_ROOT / "monofx_pipeline_blender"
_RELEASES = _PKG_ROOT / "releases"
_REPO_ROOT = _PKG_ROOT.parents[2]
_PKG_COMMON_SRC = _REPO_ROOT / "packages" / "monofx_pipeline_common" / "src" / "monofx_pipeline_common"
_VENDOR_DIR = _ADDON_DIR / "vendor" / "monofx_pipeline_common"


def _vendor_pipeline_common() -> None:
    """Bundle monofx_pipeline_common into the add-on vendor folder for ZIP installs."""
    if not _PKG_COMMON_SRC.is_dir():
        raise SystemExit(f"monofx_pipeline_common package not found: {_PKG_COMMON_SRC}")
    _VENDOR_DIR.parent.mkdir(parents=True, exist_ok=True)
    if _VENDOR_DIR.exists():
        shutil.rmtree(_VENDOR_DIR)
    shutil.copytree(
        _PKG_COMMON_SRC,
        _VENDOR_DIR,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )


_VERSION_RE = re.compile(
    r'"version":\s*\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)'
)


def _init_path() -> Path:
    return _ADDON_DIR / "__init__.py"


def _read_version() -> tuple[int, int, int]:
    text = _init_path().read_text(encoding="utf-8")
    m = _VERSION_RE.search(text)
    if m:
        return int(m.group(1)), int(m.group(2)), int(m.group(3))
    return 0, 0, 0


def _write_version(major: int, minor: int, patch: int) -> None:
    init_py = _init_path()
    text = init_py.read_text(encoding="utf-8")
    new_text, count = _VERSION_RE.subn(
        f'"version": ({major}, {minor}, {patch})',
        text,
        count=1,
    )
    if count != 1:
        raise SystemExit(f'Could not update "version" in {init_py}')
    init_py.write_text(new_text, encoding="utf-8")


def bump_version(part: str) -> tuple[int, int, int]:
    major, minor, patch = _read_version()
    if part == "major":
        major += 1
        minor = 0
        patch = 0
    elif part == "minor":
        minor += 1
        patch = 0
    elif part == "patch":
        patch += 1
    else:
        raise SystemExit(f"Unknown bump part: {part!r} (use major, minor, or patch)")
    _write_version(major, minor, patch)
    print(f"Bumped version to ({major}, {minor}, {patch})")
    return major, minor, patch


def build(out_path: Path | None = None) -> Path:
    if not _ADDON_DIR.is_dir():
        raise SystemExit(f"Add-on folder not found: {_ADDON_DIR}")

    _vendor_pipeline_common()
    major, minor, patch = _read_version()
    _RELEASES.mkdir(parents=True, exist_ok=True)
    if out_path is None:
        ver_tag = "".join(str(x) for x in (major, minor, patch))
        out_path = _RELEASES / f"monofx_pipeline_blender_v{ver_tag}.zip"

    root_name = "monofx_pipeline_blender"
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(_ADDON_DIR.rglob("*")):
            if not path.is_file():
                continue
            if "__pycache__" in path.parts or path.suffix == ".pyc":
                continue
            arc = f"{root_name}/{path.relative_to(_ADDON_DIR).as_posix()}"
            zf.write(path, arc)

    print(f"Wrote {out_path} ({out_path.stat().st_size} bytes)")
    return out_path


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Vendor monofx_pipeline_common, optionally bump add-on version, build install ZIP.",
    )
    parser.add_argument(
        "--bump",
        choices=("major", "minor", "patch"),
        help="Increment bl_info version in monofx_pipeline_blender/__init__.py before building.",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help="Output ZIP path (default: releases/monofx_pipeline_blender_v<version>.zip).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    if args.bump:
        bump_version(args.bump)
    build(args.output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
