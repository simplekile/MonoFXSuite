"""
Camera naming aligned with Maya USD Publish (``cam_`` + leaf) and Houdini ``cam_*.usd`` scan.

Primary camera per shot: ``cam_{shot}`` (e.g. ``cam_sh010``).
Additional cameras: ``cam_{shot}_02``, ``cam_{shot}_03``, …
"""

from __future__ import annotations

import re
from typing import Dict, Iterable, Optional, Union

_CAMERA_OBJECT_RE = re.compile(
    r"^cam_(?P<shot>sh\d{3,}[a-z0-9]*)(?:_(?P<idx>\d{2}))?$",
    re.IGNORECASE,
)
_CAMERA_USD_SHOT_STEM_RE = re.compile(r"^cam_sh\d", re.IGNORECASE)
_LEGACY_OBJECT_RE = re.compile(
    r"^(?P<shot>sh\d{3,}[a-z0-9]*)(?:_(?P<idx>\d{2}))?$",
    re.IGNORECASE,
)
_SHOT_TOKEN_RE = re.compile(r"^(sh)(\d+)([a-z0-9]*)$", re.IGNORECASE)


def normalize_shot_token(shot: str) -> str:
    """
    Normalize shot token like Maya ``_shot_token_from_scene_path`` (``sh1`` → ``sh001``).
    """
    token = (shot or "shot").strip().lower()
    m = _SHOT_TOKEN_RE.match(token)
    if m:
        return f"sh{int(m.group(2)):03d}{m.group(3)}"
    return token or "shot"


def format_camera_object_name(shot: str, index: int) -> str:
    """``cam_sh010`` for the first camera; ``cam_sh010_02`` for the second, etc."""
    shot_token = normalize_shot_token(shot)
    idx = max(1, min(99, int(index)))
    if idx <= 1:
        return f"cam_{shot_token}"
    return f"cam_{shot_token}_{idx:02d}"


def _parse_camera_index(name: str, shot_token: str) -> int:
    for pattern in (_CAMERA_OBJECT_RE, _LEGACY_OBJECT_RE):
        m = pattern.match((name or "").strip())
        if m is None:
            continue
        if m.group("shot").lower() != shot_token:
            continue
        idx = m.group("idx")
        if idx is None:
            return 1
        try:
            return int(idx)
        except ValueError:
            continue
    return 0


def next_camera_name(shot: str, existing_names: Iterable[str]) -> str:
    """
    Next camera object name for *shot*.

    First camera: ``cam_sh010``; further cameras: ``cam_sh010_02``, …
    """
    shot_token = normalize_shot_token(shot)
    max_idx = 0
    for name in existing_names:
        max_idx = max(max_idx, _parse_camera_index(name, shot_token))
    return format_camera_object_name(shot_token, max_idx + 1)


def parse_camera_object_name(name: str) -> Optional[tuple[str, int]]:
    """Return ``(shot_token, index)`` for ``cam_sh###`` names, else ``None``."""
    m = _CAMERA_OBJECT_RE.match((name or "").strip())
    if m is None:
        return None
    idx = int(m.group("idx")) if m.group("idx") else 1
    return m.group("shot").lower(), idx


_CAMERA_RENAME_LOOSE_RE = re.compile(
    r"^cam_(?P<shot>[a-z0-9]+)(?:_(?P<idx>\d+))?$",
    re.IGNORECASE,
)


def normalize_camera_rename_name(name: str) -> Optional[str]:
    """
    Parse rename input and return a canonical camera object name.

    Accepts strict pipeline names (``cam_sh010``, ``cam_sh010_02``) and lenient
    forms such as ``cam_sh010_2`` or fallback ``cam_shot_2`` → ``cam_shot_02``.
    """
    raw = (name or "").strip()
    if not raw.lower().startswith("cam_"):
        return None

    parsed = parse_camera_object_name(raw)
    if parsed is not None:
        shot_token, index = parsed
        return format_camera_object_name(shot_token, index)

    loose = _CAMERA_RENAME_LOOSE_RE.match(raw)
    if loose is None:
        return None
    shot_token = normalize_shot_token(loose.group("shot"))
    idx_str = loose.group("idx")
    index = int(idx_str) if idx_str else 1
    if index < 1 or index > 99:
        return None
    return format_camera_object_name(shot_token, index)


def camera_name_matches_shot(cam_name: str, shot: str) -> bool:
    """True when *cam_name* is already ``cam_{shot}`` or ``cam_{shot}_##``."""
    parsed = parse_camera_object_name(cam_name)
    if parsed is None:
        return False
    return parsed[0] == normalize_shot_token(shot)


def resolve_name_fixer_camera_name(
    cam_name: str,
    shot: str,
    existing_names: Iterable[str],
) -> str:
    """
    Target camera name for Cam rig fixer.

    Keeps the current name when it already matches *shot*; otherwise allocates
    the next ``cam_{shot}`` name.
    """
    name = (cam_name or "").strip()
    if camera_name_matches_shot(name, shot):
        return name
    return next_camera_name(shot, existing_names)


_CAMERA_RIG_PART_KEYS = ("root", "body", "look", "motion", "aim", "orbit")

# Canonical empty suffixes (operator-facing rig layer names in Outliner).
# Internal dict keys stay stable in code; Name Fixer migrates legacy suffixes.
RIG_PART_CANONICAL_SUFFIX: Dict[str, str] = {
    "root": "_root",
    "body": "_mount",
    "look": "_boom",
    "motion": "_head",
    "aim": "_aim",
    "orbit": "_orbit",
}

RIG_PART_OPERATOR_LABEL: Dict[str, str] = {
    "root": "Stage",
    "body": "Mount",
    "look": "Boom",
    "motion": "Head",
    "aim": "Aim",
    "orbit": "Orbit Pivot",
}

_LEGACY_CAMERA_RIG_SUFFIX = {
    "body": "_rig",
    "look": "_offset",
    "motion": "_ctrl",
}

# Older rig builds before canonical suffixes (still resolved at load time).
_LEGACY_EXTRA_SUFFIXES: Dict[str, tuple[str, ...]] = {
    "body": ("_body",),
    "look": ("_look",),
    "motion": ("_motion", "_bank", "_roll"),
    "orbit": ("_pan",),
}

# Older rig builds before ``_motion`` (still resolved as the motion layer).
_LEGACY_MOTION_SUFFIXES = ("_bank", "_roll", "_ctrl")

_RIG_PART_SUFFIXES = tuple(
    sorted(
        {
            suffix
            for suffix in (
                *RIG_PART_CANONICAL_SUFFIX.values(),
                *_LEGACY_CAMERA_RIG_SUFFIX.values(),
                *(s for group in _LEGACY_EXTRA_SUFFIXES.values() for s in group),
            )
        },
        key=len,
        reverse=True,
    )
)


def iter_rig_part_name_candidates(cam_name: str, part_key: str) -> Iterable[str]:
    """Canonical name first, then legacy aliases for *part_key*."""
    base = (cam_name or "cam_shot").strip()
    yield f"{base}{RIG_PART_CANONICAL_SUFFIX[part_key]}"
    legacy = _LEGACY_CAMERA_RIG_SUFFIX.get(part_key)
    if legacy is not None:
        yield f"{base}{legacy}"
    for suffix in _LEGACY_EXTRA_SUFFIXES.get(part_key, ()):
        yield f"{base}{suffix}"


def rig_part_suffixes_for_part(part_key: str) -> tuple[str, ...]:
    suffixes = [RIG_PART_CANONICAL_SUFFIX[part_key]]
    legacy = _LEGACY_CAMERA_RIG_SUFFIX.get(part_key)
    if legacy is not None:
        suffixes.append(legacy)
    suffixes.extend(_LEGACY_EXTRA_SUFFIXES.get(part_key, ()))
    return tuple(suffixes)


def rig_part_suffix_matches(object_name: str, part_key: str) -> bool:
    lower = (object_name or "").casefold()
    return any(lower.endswith(suffix.casefold()) for suffix in rig_part_suffixes_for_part(part_key))


def camera_rig_names(cam_name: str) -> Dict[str, str]:
    """Empty rig part names for a camera named ``cam_{shot}`` or ``cam_{shot}_##``."""
    base = (cam_name or "cam_shot").strip()
    return {key: f"{base}{RIG_PART_CANONICAL_SUFFIX[key]}" for key in _CAMERA_RIG_PART_KEYS}


def legacy_camera_rig_names(cam_name: str) -> Dict[str, str]:
    """Pre-rename rig part object names (body/look/motion were rig/offset/ctrl)."""
    base = (cam_name or "cam_shot").strip()
    return {key: f"{base}{suffix}" for key, suffix in _LEGACY_CAMERA_RIG_SUFFIX.items()}


def iter_camera_rig_object_names(cam_name: str):
    """All object names (current + legacy) used to detect an existing rig."""
    seen: set[str] = set()
    for key in _CAMERA_RIG_PART_KEYS:
        for name in iter_rig_part_name_candidates(cam_name, key):
            if name not in seen:
                seen.add(name)
                yield name


def camera_name_from_rig_part(object_name: str) -> Optional[str]:
    """``cam_sh010_root`` → ``cam_sh010``; returns ``None`` if not a rig part name."""
    name = (object_name or "").strip()
    lower = name.casefold()
    for suffix in _RIG_PART_SUFFIXES:
        if lower.endswith(suffix):
            return name[: -len(suffix)]
    return None


def usd_camera_basename(cam_object_name: str) -> str:
    """
    Published USD filename stem.

    Object ``cam_sh010`` → ``cam_sh010`` (Maya/Houdini).
  Legacy object ``sh010_01`` → ``cam_sh010``.
    """
    leaf = (cam_object_name or "").strip()
    if leaf.lower().startswith("cam_"):
        return leaf
    m = _LEGACY_OBJECT_RE.match(leaf)
    if m:
        idx = int(m.group("idx")) if m.group("idx") else 1
        return format_camera_object_name(m.group("shot"), idx)
    return f"cam_{leaf}" if leaf else "cam_shot"


def resolve_camera_usd_basename(
    cam_object_name: str,
    *,
    scene_path: Optional[Union[str, "Path"]] = None,
) -> str:
    """
    Published ``cam_*.usd`` stem for a Blender camera object.

    Uses ``cam_sh###`` when the object is already named that way; otherwise falls
    back to the shot token from *scene_path* (``Dolly_Camera`` → ``cam_sh003a``).
    """
    leaf = (cam_object_name or "").strip().split(":")[-1]
    direct = usd_camera_basename(leaf)
    if _CAMERA_USD_SHOT_STEM_RE.match(direct):
        return direct
    if scene_path is not None:
        from pathlib import Path

        from .shot_paths import detect_shot_from_path

        shot = detect_shot_from_path(Path(scene_path))
        if shot:
            return format_camera_object_name(shot, 1)
    return direct


def usd_basename_from_camera_leaf(leaf: str, *, prefix: str = "cam_") -> str:
    """
    Maya USD Publish rule: ``prefix + leaf``, without doubling when *leaf* already
    starts with *prefix* (e.g. leaf ``cam_sh010`` → ``cam_sh010``).
    """
    body = (leaf or "").strip()
    pfx = (prefix or "").strip()
    if not body:
        return pfx or "cam_shot"
    if pfx and body.lower().startswith(pfx.lower()):
        return body
    return f"{pfx}{body}"
