"""
Resolve USD publish folders from a saved .blend path (no bpy).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

_VERSION_DIR_RE = re.compile(r"^[vV](\d{3})$")
_TASK_CODE_RE = re.compile(r"^\d{2}_(?P<code>.+)$", re.IGNORECASE)
_BLEND_VERSION_SUFFIX_RE = re.compile(r"_v(\d{1,3})(?:_(.+))?$", re.IGNORECASE)
_INVALID_BLEND_DESC_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
# Common ``NN_<code>`` task codes (longest first for greedy strip).
_KNOWN_BLEND_TASK_SUFFIXES: tuple[str, ...] = (
    "modelling",
    "lookdev",
    "retopo",
    "sculpt",
    "groom",
    "rigging",
    "rig",
    "uv",
    "fx",
)


def task_code_from_modelling_folder(task_folder: str) -> Optional[str]:
    """``02_retopo`` → ``retopo``."""
    m = _TASK_CODE_RE.match(task_folder.strip())
    return m.group("code") if m else None


def asset_name_from_blend_stem(stem: str, task_code: Optional[str] = None) -> str:
    """
    ``char_Kahlii_retopo_v005`` → ``char_Kahlii`` when *task_code* is ``retopo``.
    """
    name = (stem or "").strip()
    if not name:
        return ""
    name = _BLEND_VERSION_SUFFIX_RE.sub("", name)
    codes: list[str] = []
    if task_code:
        codes.append(task_code.strip())
    for code in _KNOWN_BLEND_TASK_SUFFIXES:
        if code not in codes:
            codes.append(code)
    for code in codes:
        if not code:
            continue
        suffix = f"_{code}"
        if name.casefold().endswith(suffix.casefold()) and len(name) > len(suffix):
            name = name[: -len(suffix)]
            break
    return name.strip("_") or stem.strip()


def asset_name_from_scene(scene_path: Path) -> str:
    """
    Asset slug for Geo_<Asset>: pipeline folder under ``01_assets``, else parsed .blend stem.
    """
    parts = list(scene_path.parts)
    low = [p.casefold() for p in parts]
    try:
        i_assets = low.index("01_assets")
        if i_assets + 2 < len(parts):
            return parts[i_assets + 2]
    except ValueError:
        pass
    task_folder = modelling_task_folder_from_scene(scene_path)
    task_code = task_code_from_modelling_folder(task_folder) if task_folder else None
    parsed = asset_name_from_blend_stem(scene_path.stem, task_code)
    return parsed if parsed else "Asset"


def modelling_task_folder_from_scene(scene_path: Path) -> Optional[str]:
    """Task folder under ``01_modelling`` (e.g. ``02_retopo``, ``03_uv``)."""
    parts = list(scene_path.parts)
    low = [p.casefold() for p in parts]
    try:
        i_assets = low.index("01_assets")
        i_modelling = low.index("01_modelling", i_assets + 1)
    except ValueError:
        return None
    if i_modelling + 1 >= len(parts):
        return None
    task_name = parts[i_modelling + 1]
    if not _TASK_CODE_RE.match(task_name):
        return None
    return task_name


def resolve_publish_root_from_scene(scene_path: Path) -> Optional[Path]:
    """
    ``.../01_modelling/<task>/publish`` inferred from where the .blend is saved.

    Example: ``.../02_retopo/blender/work/foo.blend`` → ``.../02_retopo/publish``.
    """
    parts = list(scene_path.parts)
    low = [p.casefold() for p in parts]
    try:
        i_assets = low.index("01_assets")
        i_modelling = low.index("01_modelling", i_assets + 1)
    except ValueError:
        return None
    if i_modelling + 1 >= len(parts):
        return None
    task_name = parts[i_modelling + 1]
    if not _TASK_CODE_RE.match(task_name):
        return None
    task_root = Path(*parts[: i_modelling + 2])
    return task_root / "publish"


def default_usd_basename_from_scene(scene_path: Path) -> str:
    parts = list(scene_path.parts)
    low = [p.casefold() for p in parts]
    try:
        i_assets = low.index("01_assets")
    except ValueError:
        return "asset_publish"
    if i_assets + 2 >= len(parts):
        return "asset_publish"
    asset_name = parts[i_assets + 2]
    dept_code = "publish"
    task = modelling_task_folder_from_scene(scene_path)
    if task:
        m = _TASK_CODE_RE.match(task)
        if m:
            dept_code = m.group("code")
    return f"{asset_name}_{dept_code.strip().lower()}_publish"


def sanitize_collection_slug(collection_name: str) -> str:
    """Normalize a collection name for USD filenames (lowercase, spaces → underscores)."""
    s = (collection_name or "").strip().lower()
    s = re.sub(r"\s+", "_", s)
    s = re.sub(r"_+", "_", s)
    return s.strip("_") or "collection"


def collection_publish_usd_basename(scene_path: Path, collection_name: str) -> str:
    """
    Per-collection publish basename: ``env_House_uv_house1_publish`` from scene + collection.
    """
    base = default_usd_basename_from_scene(scene_path)
    slug = sanitize_collection_slug(collection_name)
    suffix = "_publish"
    if base.casefold().endswith(suffix):
        prefix = base[: -len(suffix)]
        return f"{prefix}_{slug}{suffix}"
    return f"{base}_{slug}{suffix}"


def list_version_numbers(publish_root: Path) -> list[int]:
    out: list[int] = []
    try:
        if not publish_root.is_dir():
            return out
        for child in publish_root.iterdir():
            if not child.is_dir():
                continue
            m = _VERSION_DIR_RE.match(child.name)
            if m:
                out.append(int(m.group(1)))
    except OSError:
        return []
    out.sort()
    return out


def version_folder_from_number(num: int) -> str:
    n = max(1, min(999, int(num)))
    return f"v{n:03d}"


def auto_next_version_number(publish_root: Path) -> int:
    vers = list_version_numbers(publish_root)
    if not vers:
        return 1
    return min(vers[-1] + 1, 999)


def next_version_name(publish_root: Path) -> str:
    return version_folder_from_number(auto_next_version_number(publish_root))


def blend_base_stem(stem: str) -> str:
    """``char_Kahlii_retopo_v005_note`` → ``char_Kahlii_retopo``; bare stem unchanged."""
    name = (stem or "").strip()
    if not name:
        return ""
    m = _BLEND_VERSION_SUFFIX_RE.search(name)
    if m:
        prefix = name[: m.start()].strip("_")
        return prefix or name[: m.start()]
    return name.strip("_") or name


def version_number_from_blend_stem(stem: str) -> Optional[int]:
    m = _BLEND_VERSION_SUFFIX_RE.search((stem or "").strip())
    if not m:
        return None
    try:
        return int(m.group(1))
    except ValueError:
        return None


def description_from_blend_stem(stem: str) -> str:
    m = _BLEND_VERSION_SUFFIX_RE.search((stem or "").strip())
    if not m:
        return ""
    return str(m.group(2) or "").strip()


def sanitize_blend_description(raw: str) -> str:
    s = (raw or "").strip()
    if not s:
        return ""
    s = s.replace(" ", "_")
    s = _INVALID_BLEND_DESC_CHARS.sub("", s)
    s = s.strip("._")
    return s[:64]


def build_blend_save_filename(
    base: str,
    version_num: int,
    description: str = "",
    *,
    suffix: str = ".blend",
) -> str:
    desc = sanitize_blend_description(description)
    core = f"{base}_v{max(1, min(999, int(version_num))):03d}"
    if desc:
        core = f"{core}_{desc}"
    return f"{core}{suffix}"


def scene_work_save_context(scene_path: Path) -> tuple[Optional[Path], str, str]:
    """Return ``(work_dir, base_stem, error_message)`` for save-version helpers."""
    if not str(scene_path).strip() or not str(scene_path.name or "").strip():
        return None, "", "Save the .blend file first."
    parent = scene_path.parent
    if not parent:
        return None, "", "Invalid scene path."
    base = blend_base_stem(scene_path.stem)
    if not base:
        return None, "", "Could not parse blend filename."
    return parent, base, ""


def list_work_blend_versions(work_dir: Path, base_stem: str) -> list[int]:
    """Version numbers of ``.blend`` files in *work_dir* sharing the same base stem."""
    base_cf = base_stem.casefold()
    out: list[int] = []
    if not base_cf or not work_dir.is_dir():
        return out
    try:
        for child in work_dir.iterdir():
            if child.suffix.lower() != ".blend":
                continue
            if blend_base_stem(child.stem).casefold() != base_cf:
                continue
            vn = version_number_from_blend_stem(child.stem)
            if vn is not None:
                out.append(vn)
    except OSError:
        return out
    out.sort()
    return out


def latest_blend_version_number(scene_path: Path) -> tuple[bool, int, str]:
    """Highest ``_v###`` number in the work folder for this scene's base stem."""
    parent, base, err = scene_work_save_context(scene_path)
    if parent is None:
        return False, 0, err
    found = list_work_blend_versions(parent, base)
    current_v = version_number_from_blend_stem(scene_path.stem)
    if current_v is not None:
        found.append(current_v)
    if not found:
        return True, 0, ""
    return True, max(found), ""


def preview_next_blend_version(scene_path: Path) -> tuple[bool, int, str]:
    """Next version number after the highest existing work-file version."""
    ok, latest, err = latest_blend_version_number(scene_path)
    if not ok:
        return False, 0, err
    next_v = latest + 1
    if next_v > 999:
        return False, 0, "Version limit reached (v999)."
    return True, next_v, ""


def find_blend_files_for_version(
    work_dir: Path,
    base_stem: str,
    version_num: int,
) -> list[Path]:
    base_cf = base_stem.casefold()
    out: list[Path] = []
    if not base_cf or not work_dir.is_dir():
        return out
    try:
        for child in work_dir.iterdir():
            if child.suffix.lower() != ".blend":
                continue
            if blend_base_stem(child.stem).casefold() != base_cf:
                continue
            if version_number_from_blend_stem(child.stem) == int(version_num):
                out.append(child)
    except OSError:
        return out
    out.sort(key=lambda p: p.name.lower())
    return out


def version_number_taken(
    work_dir: Path,
    base_stem: str,
    version_num: int,
    *,
    exclude: Optional[Path] = None,
) -> bool:
    exclude_norm = ""
    if exclude is not None:
        try:
            exclude_norm = str(exclude.resolve()).casefold()
        except OSError:
            exclude_norm = str(exclude).casefold()
    for path in find_blend_files_for_version(work_dir, base_stem, version_num):
        try:
            if exclude_norm and str(path.resolve()).casefold() == exclude_norm:
                continue
        except OSError:
            if exclude_norm and str(path).casefold() == exclude_norm:
                continue
        return True
    return False


def build_blend_save_path_for_version(
    scene_path: Path,
    version_num: int,
    description: str = "",
) -> tuple[bool, str, str]:
    parent, base, err = scene_work_save_context(scene_path)
    if parent is None:
        return False, "", err
    if int(version_num) < 1 or int(version_num) > 999:
        return False, "", "Version must be between v001 and v999."
    suffix = scene_path.suffix or ".blend"
    new_name = build_blend_save_filename(base, int(version_num), description, suffix=suffix)
    return True, str(parent / new_name), ""


def blend_path_with_version_description(
    scene_path: Path,
    description: str = "",
) -> tuple[bool, str, str]:
    """Same version number as *scene_path*, with an updated description suffix."""
    version = version_number_from_blend_stem(scene_path.stem)
    if version is None:
        return False, "", "Current file has no version suffix (_v001)."
    return build_blend_save_path_for_version(scene_path, version, description)


def next_blend_save_path(
    scene_path: Path,
    description: str = "",
) -> tuple[bool, str, str]:
    """Next incremental work-file path in the same folder as *scene_path*."""
    ok, next_v, err = preview_next_blend_version(scene_path)
    if not ok:
        return False, "", err
    return build_blend_save_path_for_version(scene_path, next_v, description)


_SHOT_RE = re.compile(r"^(sh\d{3,}[a-z0-9]*)$", re.IGNORECASE)
# Task folder: 01_anim (shots), 06_anim (assets), etc. — Maya parity.
_ANIM_TASK_RE = re.compile(r"^\d{2}_anim$", re.IGNORECASE)

ANIM_PUBLISH_PATH_HINT = (
    "Save .blend under …/<NN_anim>/… "
    "(e.g. 02_shots/<shot>/01_anim/… or 01_assets/…/06_anim/…) "
    "to resolve publish path."
)


def detect_shot_from_scene_path(scene_path: Path) -> Optional[str]:
    """Detect shot token (``sh002``, ``sh003a``) from path segments."""
    for part in list(scene_path.parts) + [p.name for p in scene_path.parents]:
        m = _SHOT_RE.match(part)
        if m:
            return m.group(1).lower()
    return None


def find_anim_task_index(parts: list[str]) -> Optional[int]:
    """Index of the first ``NN_anim`` path segment, or ``None``."""
    for i, seg in enumerate(parts):
        if _ANIM_TASK_RE.match(seg):
            return i
    return None


def resolve_anim_publish_root_from_scene(scene_path: Path) -> Optional[Path]:
    """
    ``.../<NN_anim>/publish`` inferred from a saved .blend path (Maya parity).

    Examples:
      ``.../02_shots/sh002/01_anim/blender/work/foo.blend``
        → ``.../sh002/01_anim/publish``
      ``.../01_assets/_characters/char_X/06_anim/blender/work/foo.blend``
        → ``.../char_X/06_anim/publish``
    """
    parts = list(scene_path.parts)
    i_anim = find_anim_task_index(parts)
    if i_anim is None:
        return None
    return Path(*parts[: i_anim + 1]) / "publish"


def default_anim_geo_usd_basename(scene_path: Path) -> str:
    """
    Basename without extension for anim geo cache (``geo_char_Zephys``).

    Parses the .blend stem, strips version / task suffixes, ensures ``geo_`` prefix.
    """
    stem = scene_path.stem
    name = asset_name_from_blend_stem(stem, "anim")
    if not name:
        name = stem.strip() or "asset"
    if not name.lower().startswith("geo_"):
        name = f"geo_{name}"
    return name


def relative_anim_publish_display(scene_path: Path, usd_path: Path) -> str:
    """Short path from the anim task parent, e.g. ``06_anim/publish/v001/geo_char_A.usd``."""
    try:
        parts = list(scene_path.parts)
        i_anim = find_anim_task_index(parts)
        if i_anim is not None and i_anim > 0:
            anchor = Path(*parts[:i_anim])
            rel = Path(usd_path).resolve().relative_to(anchor.resolve())
            return rel.as_posix()
        if i_anim is not None:
            rel = Path(usd_path).resolve().relative_to(
                (Path(*parts[: i_anim + 1])).resolve()
            )
            return rel.as_posix()
    except (ValueError, OSError):
        pass
    p = Path(usd_path)
    i_anim = find_anim_task_index(list(scene_path.parts))
    task = scene_path.parts[i_anim] if i_anim is not None else "01_anim"
    return f"{task}/publish/{p.parent.name}/{p.name}"


def relative_publish_display(scene_path: Path, usd_path: Path) -> str:
    """Short path from asset folder, e.g. ``02_retopo/publish/v001/file.usd``."""
    try:
        parts = list(scene_path.parts)
        low = [p.casefold() for p in parts]
        i_assets = low.index("01_assets")
        if i_assets + 2 < len(parts):
            anchor = Path(*parts[: i_assets + 3])
            rel = Path(usd_path).resolve().relative_to(anchor.resolve())
            return rel.as_posix()
    except (ValueError, OSError):
        pass
    p = Path(usd_path)
    task = modelling_task_folder_from_scene(scene_path)
    if task:
        return f"{task}/publish/{p.parent.name}/{p.name}"
    return p.name
