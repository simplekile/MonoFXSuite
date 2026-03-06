"""
Auto Material logic — DCC-agnostic.
Scan folder for texture files, parse naming conventions, group into material sets.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from tools.fx.auto_material.config import (
    GENERIC_ALIAS_TO_SLOT,
    IMAGE_EXTENSIONS,
    PIPELINE_NAME_TO_SLOT,
    RESOLUTION_TOKENS,
    UDIM_REGEX,
)


@dataclass
class ParseResult:
    filepath: str
    prefix: str
    slot: str
    colorspace: str | None = None
    udim: bool = False
    parse_mode: str = "pipeline"


@dataclass
class SlotInfo:
    filepath: str
    colorspace: str | None = None
    udim: bool = False


@dataclass
class MaterialGroup:
    prefix: str
    slots: dict[str, SlotInfo] = field(default_factory=dict)
    parse_mode: str = "pipeline"


# ---------------------------------------------------------------------------
# Scan
# ---------------------------------------------------------------------------

def scan_images(folder: str, recursive: bool = True) -> list[str]:
    root = Path(folder)
    if not root.is_dir():
        return []
    pattern = "**/*" if recursive else "*"
    return sorted(
        str(p)
        for p in root.glob(pattern)
        if p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS
    )


# ---------------------------------------------------------------------------
# UDIM helpers
# ---------------------------------------------------------------------------

_UDIM_RE = re.compile(UDIM_REGEX)


def _strip_udim(stem: str) -> tuple[str, bool]:
    """Remove trailing .XXXX from stem. Returns (clean_stem, has_udim)."""
    m = re.search(r"\.(\d{4})$", stem)
    if m and int(m.group(1)) >= 1001:
        return stem[: m.start()], True
    return stem, False


def _make_udim_path(filepath: str) -> str:
    """Replace the UDIM tile number with %(UDIM)d token."""
    p = Path(filepath)
    stem = p.stem
    m = re.search(r"\.(\d{4})$", stem)
    if m and int(m.group(1)) >= 1001:
        new_stem = stem[: m.start()] + ".%(UDIM)d"
        return str(p.with_name(new_stem + p.suffix))
    return filepath


# ---------------------------------------------------------------------------
# Pipeline parse
# ---------------------------------------------------------------------------

def try_pipeline_parse(filepath: str) -> ParseResult | None:
    """
    Parse pipeline naming: {prefix}_{Slot}_{ColorSpace}.{UDIM}.{ext}
    Prefix may contain underscores. Slot is the first token that matches a known PascalCase name.
    """
    p = Path(filepath)
    ext = p.suffix.lower()
    if ext not in IMAGE_EXTENSIONS:
        return None

    stem = p.stem
    stem_clean, has_udim = _strip_udim(stem)

    parts = stem_clean.split("_")
    if len(parts) < 2:
        return None

    slot_idx: int | None = None
    slot_token: str | None = None
    for i, token in enumerate(parts):
        if token in PIPELINE_NAME_TO_SLOT:
            slot_idx = i
            slot_token = token
            break

    if slot_idx is None or slot_token is None:
        return None

    prefix = "_".join(parts[:slot_idx]) if slot_idx > 0 else parts[0]
    colorspace = "_".join(parts[slot_idx + 1 :]) if slot_idx + 1 < len(parts) else None
    slot_internal = PIPELINE_NAME_TO_SLOT[slot_token]

    return ParseResult(
        filepath=filepath,
        prefix=prefix,
        slot=slot_internal,
        colorspace=colorspace or None,
        udim=has_udim,
        parse_mode="pipeline",
    )


# ---------------------------------------------------------------------------
# Generic parse
# ---------------------------------------------------------------------------

def try_generic_parse(filepath: str) -> ParseResult | None:
    """
    Fallback: split all separators, scan tokens right-to-left for known keyword.
    """
    p = Path(filepath)
    ext = p.suffix.lower()
    if ext not in IMAGE_EXTENSIONS:
        return None

    stem = p.stem
    stem_clean, has_udim = _strip_udim(stem)

    tokens = re.split(r"[_\-.]", stem_clean)
    if not tokens:
        return None

    slot_idx = -1
    slot_internal: str | None = None

    for i in range(len(tokens) - 1, -1, -1):
        t_lower = tokens[i].lower()
        if t_lower in RESOLUTION_TOKENS:
            continue
        if t_lower in GENERIC_ALIAS_TO_SLOT:
            slot_idx = i
            slot_internal = GENERIC_ALIAS_TO_SLOT[t_lower]
            break

    if slot_internal is None or slot_idx < 0:
        return None

    prefix_tokens = [t for t in tokens[:slot_idx] if t.lower() not in RESOLUTION_TOKENS]
    prefix = "_".join(prefix_tokens) if prefix_tokens else p.parent.name

    if not prefix:
        prefix = "unnamed"

    return ParseResult(
        filepath=filepath,
        prefix=prefix,
        slot=slot_internal,
        colorspace=None,
        udim=has_udim,
        parse_mode="generic",
    )


# ---------------------------------------------------------------------------
# Auto parse
# ---------------------------------------------------------------------------

def auto_parse(filepath: str) -> ParseResult | None:
    return try_pipeline_parse(filepath) or try_generic_parse(filepath)


# ---------------------------------------------------------------------------
# Group
# ---------------------------------------------------------------------------

def group_by_prefix(results: list[ParseResult]) -> dict[str, MaterialGroup]:
    groups: dict[str, MaterialGroup] = {}
    for r in results:
        if r.prefix not in groups:
            groups[r.prefix] = MaterialGroup(prefix=r.prefix, parse_mode=r.parse_mode)
        g = groups[r.prefix]
        if r.slot not in g.slots:
            path = _make_udim_path(r.filepath) if r.udim else r.filepath
            g.slots[r.slot] = SlotInfo(
                filepath=path,
                colorspace=r.colorspace,
                udim=r.udim,
            )
    return dict(sorted(groups.items()))


def group_by_subfolder(results: list[ParseResult]) -> dict[str, MaterialGroup]:
    groups: dict[str, MaterialGroup] = {}
    for r in results:
        folder_name = Path(r.filepath).parent.name or "root"
        if folder_name not in groups:
            groups[folder_name] = MaterialGroup(prefix=folder_name, parse_mode=r.parse_mode)
        g = groups[folder_name]
        if r.slot not in g.slots:
            path = _make_udim_path(r.filepath) if r.udim else r.filepath
            g.slots[r.slot] = SlotInfo(
                filepath=path,
                colorspace=r.colorspace,
                udim=r.udim,
            )
    return dict(sorted(groups.items()))


def scan_and_group(
    folder: str,
    recursive: bool = True,
) -> tuple[dict[str, MaterialGroup], list[str]]:
    """
    Full pipeline: scan → parse → group.
    Returns (groups, unmatched_files).
    """
    files = scan_images(folder, recursive=recursive)
    parsed: list[ParseResult] = []
    unmatched: list[str] = []

    for f in files:
        result = auto_parse(f)
        if result is not None:
            parsed.append(result)
        else:
            unmatched.append(f)

    groups = group_by_prefix(parsed)
    return groups, unmatched
