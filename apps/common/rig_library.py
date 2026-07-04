"""
Rig library scan on disk — no DCC imports.

Shared by Maya Reference Manager and Blender rig linking.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Literal, Optional, Sequence, Tuple

from apps.common.project_layout import (
    find_project_root,
    list_publish_version_dirs,
    parse_asset_from_project_path,
    version_dir_sort_key,
)

Mode = Literal["publish", "work"]

DEFAULT_PUBLISH_SUBPATH = "02_rigging/02_build_rig/publish"
DEFAULT_MAYA_WORK_SUBPATH = "02_rigging/02_build_rig/maya/work"
DEFAULT_BLENDER_WORK_SUBPATH = "02_rigging/02_build_rig/blender/work"
THUMB_RELATIVE = ".meta/thumb_rig.user.png"

KNOWN_DISPLAY_PREFIXES: Tuple[str, ...] = (
    "char_",
    "prop_",
    "env_",
    "veh_",
    "graphic_",
)

MAYA_EXTENSIONS: Tuple[str, ...] = (".ma", ".mb")
BLENDER_EXTENSIONS: Tuple[str, ...] = (".blend",)


@dataclass(frozen=True)
class RigVersionEntry:
    label: str
    path: str
    sort_key: tuple
    mtime: float


@dataclass
class RigOffer:
    asset_root: Path
    asset_folder_name: str
    display_name: str
    versions: List[RigVersionEntry] = field(default_factory=list)
    default_index: int = 0


def _normalize_extensions(extensions: Sequence[str]) -> Tuple[str, ...]:
    out: List[str] = []
    for ext in extensions:
        e = (ext or "").strip().lower()
        if not e:
            continue
        if not e.startswith("."):
            e = f".{e}"
        if e not in out:
            out.append(e)
    return tuple(out) if out else MAYA_EXTENSIONS


def extensions_for_path(file_path: str) -> Tuple[str, ...]:
    """Infer DCC extensions from a rig file path suffix."""
    suffix = Path(str(file_path).strip()).suffix.lower()
    if suffix == ".blend":
        return BLENDER_EXTENSIONS
    if suffix in (".ma", ".mb"):
        return MAYA_EXTENSIONS
    return MAYA_EXTENSIONS


def thumb_path_for_asset(
    asset_root: Path,
    *,
    thumb_relative: str = THUMB_RELATIVE,
) -> Path:
    rel = thumb_relative.strip().lstrip("/\\")
    return asset_root / rel.replace("\\", os.sep).replace("/", os.sep)


def suggest_namespace_from_asset(asset_folder_name: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9_]", "_", (asset_folder_name or "ref").strip())
    if s and s[0].isdigit():
        s = "r_" + s
    return s or "ref"


def display_name_from_asset_folder(folder_name: str) -> str:
    low = folder_name.lower()
    for pfx in KNOWN_DISPLAY_PREFIXES:
        if low.startswith(pfx):
            return folder_name[len(pfx) :]
    return folder_name


def _stem_is_publish_rig(stem: str) -> bool:
    s = stem.lower()
    return "_rig_" in s and "_publish" in s


def _stem_work_version_sort(stem: str) -> tuple:
    m = re.search(r"_v(\d+)", stem, re.IGNORECASE)
    if m:
        return (int(m.group(1)), stem.lower())
    return (0, stem.lower())


def _mtime(p: Path) -> float:
    try:
        return p.stat().st_mtime
    except OSError:
        return 0.0


def scan_rigs(
    project_root: Path,
    assets_group: str,
    mode: Mode,
    *,
    publish_subpath: str = DEFAULT_PUBLISH_SUBPATH,
    work_subpath: str = DEFAULT_MAYA_WORK_SUBPATH,
    extensions: Sequence[str] = MAYA_EXTENSIONS,
) -> List[RigOffer]:
    """
    List rig files under ``project_root/01_assets/<assets_group>/<asset>/`` for one group.
    """
    exts = _normalize_extensions(extensions)
    base = project_root / "01_assets" / assets_group
    if not base.is_dir():
        return []

    offers: List[RigOffer] = []
    try:
        asset_dirs = [p for p in base.iterdir() if p.is_dir()]
    except OSError:
        return []

    asset_dirs.sort(key=lambda p: p.name.lower())

    for asset_root in asset_dirs:
        entries: List[RigVersionEntry] = []

        if mode == "publish":
            pub = asset_root.joinpath(*publish_subpath.replace("\\", "/").split("/"))
            for ver_dir in list_publish_version_dirs(pub):
                vn = ver_dir.name
                try:
                    files = [p for p in ver_dir.iterdir() if p.is_file()]
                except OSError:
                    continue
                for f in files:
                    if f.suffix.lower() not in exts:
                        continue
                    if not _stem_is_publish_rig(f.stem):
                        continue
                    sk = (version_dir_sort_key(vn), f.name.lower())
                    label = f"{vn} · {f.name}"
                    entries.append(
                        RigVersionEntry(
                            label=label,
                            path=str(f.resolve()),
                            sort_key=sk,
                            mtime=_mtime(f),
                        )
                    )
        else:
            work = asset_root.joinpath(*work_subpath.replace("\\", "/").split("/"))
            if work.is_dir():
                try:
                    files = [p for p in work.iterdir() if p.is_file()]
                except OSError:
                    files = []
                for f in files:
                    if f.suffix.lower() not in exts:
                        continue
                    if "_rig_" not in f.stem.lower():
                        continue
                    if not re.search(r"_v\d+", f.stem, re.IGNORECASE):
                        continue
                    sk = _stem_work_version_sort(f.stem) + (f.name.lower(),)
                    entries.append(
                        RigVersionEntry(
                            label=f.name,
                            path=str(f.resolve()),
                            sort_key=sk,
                            mtime=_mtime(f),
                        )
                    )

        entries.sort(key=lambda e: e.sort_key)
        default_index = len(entries) - 1 if entries else 0
        offers.append(
            RigOffer(
                asset_root=asset_root,
                asset_folder_name=asset_root.name,
                display_name=display_name_from_asset_folder(asset_root.name),
                versions=entries,
                default_index=max(0, default_index),
            )
        )

    return [o for o in offers if o.versions]


def resolve_project_root_from_scene_path(scene_path: Optional[str]) -> Optional[Path]:
    if not scene_path or not str(scene_path).strip():
        return None
    return find_project_root(Path(scene_path))


def thumb_path_for_reference_file(
    reference_path: str,
    project_root: Optional[Path],
) -> Optional[Path]:
    """
    If ``reference_path`` is under ``project_root/01_assets/<group>/<asset>/...``,
    return the asset ``.meta/thumb_rig.user.png`` when that file exists.
    """
    if not project_root or not str(reference_path).strip():
        return None
    norm = os.path.normpath(str(reference_path).strip().replace("/", os.sep))
    if not norm:
        return None
    parsed = parse_asset_from_project_path(Path(norm), project_root)
    if not parsed:
        try:
            parsed = parse_asset_from_project_path(Path(norm).resolve(), project_root)
        except OSError:
            parsed = None
    if not parsed:
        return None
    group, asset_name = parsed
    asset_root = project_root / "01_assets" / group / asset_name
    tp = thumb_path_for_asset(asset_root)
    return tp if tp.is_file() else None


def library_location_for_file(
    resolved_file: str,
    project_root: Path,
) -> Optional[tuple[str, str]]:
    """Returns (assets_group, asset_folder) for Library sync."""
    return parse_asset_from_project_path(Path(resolved_file), project_root)


def _norm_compare_path(path: str) -> str:
    """Stable path string for equality checks (resolve when possible)."""
    p = os.path.normpath(str(path).strip().replace("/", os.sep))
    if not p:
        return ""
    try:
        return os.path.normcase(str(Path(p).resolve()))
    except OSError:
        return os.path.normcase(p)


def _work_stem_identity(stem: str) -> str:
    return re.sub(r"_v\d+$", "", stem, flags=re.IGNORECASE).lower()


def _rig_entries_for_same_scene_rig(
    file_path: str,
    project_root: Path,
    mode: Mode,
    *,
    publish_subpath: str = DEFAULT_PUBLISH_SUBPATH,
    work_subpath: Optional[str] = None,
    extensions: Optional[Sequence[str]] = None,
) -> Optional[tuple[List[RigVersionEntry], str]]:
    """
    Resolve library entries for the same logical rig as ``file_path``.

    Returns ``(entries_sorted_by_version, current_norm_path)`` or ``None`` if the
    reference cannot be mapped to scanned rig versions.
    """
    if not str(file_path).strip() or not project_root:
        return None
    loc = library_location_for_file(file_path, project_root)
    if loc is None:
        try:
            loc = library_location_for_file(str(Path(file_path).resolve()), project_root)
        except OSError:
            loc = None
    if loc is None:
        return None

    exts = _normalize_extensions(extensions) if extensions is not None else extensions_for_path(file_path)
    if work_subpath is None:
        work_subpath = (
            DEFAULT_BLENDER_WORK_SUBPATH
            if exts == BLENDER_EXTENSIONS
            else DEFAULT_MAYA_WORK_SUBPATH
        )

    group, asset_folder = loc
    offers = scan_rigs(
        project_root,
        group,
        mode,
        publish_subpath=publish_subpath,
        work_subpath=work_subpath,
        extensions=exts,
    )
    offer = next((o for o in offers if o.asset_folder_name == asset_folder), None)
    if offer is None or not offer.versions:
        return None

    cur = Path(os.path.normpath(str(file_path).replace("/", os.sep)))
    cur_cmp = _norm_compare_path(str(file_path))

    if mode == "publish":
        name = cur.name.lower()
        candidates = [e for e in offer.versions if Path(e.path).name.lower() == name]
    else:
        ident = _work_stem_identity(cur.stem)
        candidates = [
            e for e in offer.versions if _work_stem_identity(Path(e.path).stem) == ident
        ]

    if not candidates:
        return None
    entries = sorted(candidates, key=lambda e: e.sort_key)
    return (entries, cur_cmp)


def matching_rig_versions_for_scene_path(
    file_path: str,
    project_root: Path,
    mode: Mode,
    *,
    publish_subpath: str = DEFAULT_PUBLISH_SUBPATH,
    work_subpath: Optional[str] = None,
    extensions: Optional[Sequence[str]] = None,
) -> List[RigVersionEntry]:
    """All rig files on disk for the same logical rig as the scene reference (sorted oldest → newest)."""
    out = _rig_entries_for_same_scene_rig(
        file_path,
        project_root,
        mode,
        publish_subpath=publish_subpath,
        work_subpath=work_subpath,
        extensions=extensions,
    )
    if out is None:
        return []
    entries, _ = out
    return entries


_PUBLISH_VER_DIR_RE = re.compile(r"^[vV](\d+)$", re.IGNORECASE)


def version_display_token_from_path(file_path: str, mode: Mode) -> str:
    """
    Compact version label for UI (e.g. ``v002``): publish parent folder ``V002``,
    or work-file stem ``*_v003``.
    """
    raw = str(file_path).strip()
    if not raw:
        return ""
    p = Path(os.path.normpath(raw.replace("/", os.sep)))
    if mode == "publish":
        m = _PUBLISH_VER_DIR_RE.match(p.parent.name.strip())
        if m:
            return f"v{int(m.group(1)):03d}"
        return ""
    m = re.search(r"_v(\d+)", p.stem, re.IGNORECASE)
    if m:
        return f"v{int(m.group(1)):03d}"
    return ""


@dataclass(frozen=True)
class SceneRefVersionDisplay:
    """Precomputed tokens for the Scene table Version column."""

    current_token: str
    newest_token: str
    is_on_newest: bool
    has_scan_match: bool
    newest_path: str
    scene_path: str


def scene_ref_version_display(
    scene_path: str,
    project_root: Path,
    mode: Mode,
    *,
    matching_entries: Optional[List[RigVersionEntry]] = None,
    publish_subpath: str = DEFAULT_PUBLISH_SUBPATH,
    work_subpath: Optional[str] = None,
    extensions: Optional[Sequence[str]] = None,
) -> Optional[SceneRefVersionDisplay]:
    """Build version column state; ``None`` when there is no path to inspect."""
    raw = str(scene_path).strip()
    if not raw:
        return None
    entries = (
        matching_entries
        if matching_entries is not None
        else matching_rig_versions_for_scene_path(
            raw,
            project_root,
            mode,
            publish_subpath=publish_subpath,
            work_subpath=work_subpath,
            extensions=extensions,
        )
    )
    cur_tok = version_display_token_from_path(raw, mode) or "—"
    if not entries:
        return SceneRefVersionDisplay(
            current_token=cur_tok,
            newest_token="",
            is_on_newest=True,
            has_scan_match=False,
            newest_path="",
            scene_path=raw,
        )
    newest = entries[-1]
    new_tok = version_display_token_from_path(newest.path, mode) or "—"
    on_newest = rig_paths_equivalent(raw, newest.path)
    return SceneRefVersionDisplay(
        current_token=cur_tok,
        newest_token=new_tok,
        is_on_newest=on_newest,
        has_scan_match=True,
        newest_path=newest.path,
        scene_path=raw,
    )


def rig_paths_equivalent(path_a: str, path_b: str) -> bool:
    """True if two paths refer to the same file (for replace / version pick)."""
    return _norm_compare_path(path_a) == _norm_compare_path(path_b)


def rig_version_index_for_scene_path(
    file_path: str,
    entries: List[RigVersionEntry],
) -> int:
    """Combo-box default: index of the file the scene points at, else last index (newest)."""
    if not entries:
        return 0
    cur_cmp = _norm_compare_path(str(file_path))
    for i, e in enumerate(entries):
        if _norm_compare_path(e.path) == cur_cmp:
            return i
    return len(entries) - 1


def newer_rig_version_for_scene_path(
    file_path: str,
    project_root: Path,
    mode: Mode,
    *,
    publish_subpath: str = DEFAULT_PUBLISH_SUBPATH,
    work_subpath: Optional[str] = None,
    extensions: Optional[Sequence[str]] = None,
) -> Optional[RigVersionEntry]:
    """
    If ``file_path`` is under a project asset and ``scan_rigs`` lists a **newer**
    rig file for the same logical rig, return that entry.

    Returns ``None`` when not in-project, unknown in the library scan, or already
    on the newest matching file.
    """
    out = _rig_entries_for_same_scene_rig(
        file_path,
        project_root,
        mode,
        publish_subpath=publish_subpath,
        work_subpath=work_subpath,
        extensions=extensions,
    )
    if out is None:
        return None
    entries, cur_cmp = out
    if not entries:
        return None
    best = max(entries, key=lambda e: e.sort_key)
    if _norm_compare_path(best.path) == cur_cmp:
        return None
    return best
