"""USD batch loader logic — no Houdini imports."""

from __future__ import annotations

import os
import re
from pathlib import Path

from tools.fx.usd_batch_loader.config import USD_EXTS


def parse_strip_tokens(strip_raw: str) -> list[str]:
    """Split comma-separated strip tokens (e.g. ``prop_,publish``)."""
    return [t.strip() for t in strip_raw.split(",") if t.strip()]


def apply_strip_name(stem: str, strip_raw: str) -> str:
    """Remove each comma-separated token from *stem* (case-insensitive substring)."""
    result = stem
    for token in parse_strip_tokens(strip_raw):
        result = re.sub(re.escape(token), "", result, flags=re.IGNORECASE)
    result = re.sub(r"_+", "_", result).strip("_")
    return result or stem


def node_name_from_label(filename: str, strip_raw: str = "") -> str:
    """USD filename → safe Houdini node name after optional strip."""
    stem = apply_strip_name(Path(filename).stem, strip_raw)
    safe = re.sub(r"[^A-Za-z0-9_]", "_", stem).strip("_")
    return safe or "usd"


def collect_usd_files(
    folder: str,
    *,
    recursive: bool = False,
    extensions: tuple[str, ...] = USD_EXTS,
) -> list[tuple[str, str]]:
    """Return sorted ``(abs_path, filename)`` pairs from *folder*."""
    root = os.path.normpath(folder)
    if not os.path.isdir(root):
        return []

    paths: list[str] = []
    if recursive:
        for dirpath, _dirnames, filenames in os.walk(root):
            for name in filenames:
                if name.lower().endswith(extensions):
                    paths.append(os.path.join(dirpath, name))
    else:
        for name in os.listdir(root):
            full = os.path.join(root, name)
            if os.path.isfile(full) and name.lower().endswith(extensions):
                paths.append(full)

    paths.sort(key=lambda p: os.path.basename(p).lower())
    return [(p, os.path.basename(p)) for p in paths]
