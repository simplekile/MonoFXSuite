"""
Plan per-rig anim USD geo export jobs (Maya-style one file per linked rig).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import bpy

from . import publish_paths
from .anim_usd_cache_exporter import (
    PublishGeoGroup,
    collect_mesh_names_for_merged_publishes,
    collect_mesh_names_for_publish_names,
    collect_publish_geo_groups,
)
from .anim_usd_cache_paths_ui import ensure_usd_extension, scene_blend_path
from monofx_pipeline_common.anim_geo_naming import resolve_geo_usd_basename
from monofx_pipeline_common.anim_geo_merge import group_publish_geo_by_link
from monofx_pipeline_common.project_layout import find_project_root, parse_asset_from_project_path
from .rig_adapter import _collection_rig_paths


@dataclass(frozen=True)
class GeoExportJob:
    publish_name: str
    output_basename: str
    filepath: str
    mesh_names: tuple[str, ...]
    source_publish_names: tuple[str, ...] = ()
    # When set, matches ``AnimUsdExportAssetItem.asset_id`` (CUSTOM rows).
    list_asset_id: str = ""

    @property
    def mesh_count(self) -> int:
        return len(self.mesh_names)

    @property
    def asset_id(self) -> str:
        if len(self.source_publish_names) > 1:
            return f"link:{self.output_basename}"
        return self.publish_name


def _library_path_for_publish_name(publish_name: str) -> Optional[Path]:
    coll = bpy.data.collections.get(publish_name)
    if coll is None:
        return None
    _, resolved = _collection_rig_paths(coll)
    if not resolved:
        return None
    return Path(resolved)


def link_key_for_publish_name(publish_name: str) -> str:
    """Stable key for grouping linked rig instances (resolved .blend path)."""
    lib_path = _library_path_for_publish_name(publish_name)
    if lib_path is None:
        return f"publish:{publish_name}"
    try:
        return lib_path.resolve().as_posix().casefold()
    except OSError:
        return lib_path.as_posix().casefold()


def _publish_override_names_for_library_path(lib_path: Path) -> tuple[str, ...]:
    """All scene ``*_publish*`` overrides that reference the same rig library."""
    try:
        target = lib_path.resolve().as_posix().casefold()
    except OSError:
        target = lib_path.as_posix().casefold()

    names: list[str] = []
    for coll in bpy.data.collections:
        if "publish" not in coll.name.casefold():
            continue
        other = _library_path_for_publish_name(coll.name)
        if other is None:
            continue
        try:
            key = other.resolve().as_posix().casefold()
        except OSError:
            key = other.as_posix().casefold()
        if key == target:
            names.append(coll.name)
    return tuple(sorted(set(names), key=str.lower))


def _display_publish_names(names: tuple[str, ...]) -> str:
    if not names:
        return "Geo"
    if len(names) == 1:
        return names[0]
    return " · ".join(names)


def _job_from_publish_groups(
    groups: list[PublishGeoGroup],
    *,
    project_root: Optional[Path],
    out_dir: Path,
    used_basenames: set[str],
    merge_by_link: bool,
    context: Optional[bpy.types.Context] = None,
) -> GeoExportJob:
    publish_names = tuple(sorted({g.publish_name for g in groups}, key=str.lower))
    if merge_by_link and publish_names:
        lib_path = _library_path_for_publish_name(publish_names[0])
        if lib_path is not None:
            expanded = _publish_override_names_for_library_path(lib_path)
            if expanded:
                publish_names = expanded

    mesh_names: list[str] = []
    for group in groups:
        mesh_names.extend(group.mesh_names)
    if merge_by_link and len(publish_names) > 1:
        mesh_names.extend(
            collect_mesh_names_for_merged_publishes(publish_names, context)
        )
    elif merge_by_link and publish_names:
        mesh_names.extend(
            collect_mesh_names_for_publish_names(publish_names, context)
        )
    mesh_tuple = tuple(sorted(set(mesh_names), key=str.lower))

    asset_folder = None
    for group in groups:
        asset_folder = _asset_folder_for_publish_group(group, project_root)
        if asset_folder:
            break
    basename = resolve_geo_usd_basename(
        asset_folder=asset_folder,
        publish_name=publish_names[0] if not asset_folder else None,
        used=used_basenames,
    )
    filepath = ensure_usd_extension(str(out_dir / f"{basename}.usd"))
    return GeoExportJob(
        publish_name=_display_publish_names(publish_names),
        output_basename=basename,
        filepath=filepath,
        mesh_names=mesh_tuple,
        source_publish_names=publish_names,
    )


def _asset_folder_for_publish_group(
    group: PublishGeoGroup,
    project_root: Optional[Path],
) -> Optional[str]:
    lib_path = _library_path_for_publish_name(group.publish_name)
    if lib_path is None or project_root is None:
        return None
    parsed = parse_asset_from_project_path(lib_path, project_root)
    if parsed is None:
        return None
    return parsed[1]


def resolve_export_output_dir(props) -> tuple[bool, Path, str]:
    from . import anim_usd_cache_paths_ui as path_ui

    ok, filepath, err = path_ui.resolve_output_path(props)
    if not ok:
        return False, Path(), err
    return True, Path(filepath).parent, ""


def plan_geo_export_jobs(
    context: bpy.types.Context,
    props,
    *,
    allow_selection_fallback: bool = True,
) -> tuple[list[GeoExportJob], str]:
    ok_dir, out_dir, err = resolve_export_output_dir(props)
    if not ok_dir:
        return [], err

    groups = collect_publish_geo_groups(context)
    if groups:
        scene_path = scene_blend_path()
        project_root = (
            find_project_root(scene_path) if scene_path is not None else None
        )
        merge_by_link = bool(getattr(props, "anim_usd_merge_by_link", False))
        used_basenames: set[str] = set()
        jobs: list[GeoExportJob] = []
        for bucket in group_publish_geo_by_link(
            groups,
            merge_by_link=merge_by_link,
            link_key_fn=link_key_for_publish_name if merge_by_link else None,
        ):
            jobs.append(
                _job_from_publish_groups(
                    bucket,
                    project_root=project_root,
                    out_dir=out_dir,
                    used_basenames=used_basenames,
                    merge_by_link=merge_by_link,
                    context=context,
                )
            )
        jobs = [job for job in jobs if job.mesh_count > 0]
        return jobs, ""

    if not allow_selection_fallback:
        return [], (
            "No publish geo targets. Use Add Selected, or link a *_publish* "
            "rig with a <namespace>::Geo collection."
        )

    from .anim_usd_cache_exporter import collect_export_mesh_objects

    meshes = collect_export_mesh_objects(context)
    if not meshes:
        return [], (
            "No mesh objects to export. Link a *_publish* rig with a "
            "<namespace>::Geo collection, or Add Selected mesh object(s)."
        )

    from . import anim_usd_cache_paths_ui as path_ui

    ok_path, filepath, path_err = path_ui.resolve_output_path(props)
    if not ok_path:
        return [], path_err

    scene_path = scene_blend_path()
    if scene_path is not None:
        basename = publish_paths.default_anim_geo_usd_basename(scene_path)
    else:
        basename = Path(filepath).stem or "geo_asset"

    names = tuple(sorted({obj.name for obj in meshes}, key=str.lower))
    return [
        GeoExportJob(
            publish_name="Selection",
            output_basename=basename,
            filepath=ensure_usd_extension(filepath),
            mesh_names=names,
        )
    ], ""


def geo_output_filenames_for_ui(
    context: bpy.types.Context,
    props,
) -> list[tuple[str, str]]:
    jobs, _ = plan_geo_export_jobs(context, props)
    return [(job.publish_name, Path(job.filepath).name) for job in jobs]


def plan_custom_mesh_geo_job(
    *,
    display_name: str,
    mesh_names: tuple[str, ...],
    list_asset_id: str,
    out_dir: Path,
    used_basenames: set[str],
    output_filename: str = "",
) -> Optional[GeoExportJob]:
    """Build a GEO job for manually added mesh object(s)."""
    names = tuple(sorted({n for n in mesh_names if n}, key=str.lower))
    if not names:
        return None
    from monofx_pipeline_common.anim_geo_naming import (
        alloc_unique_basename,
        sanitize_filename_component,
    )

    override = (output_filename or "").strip()
    if override:
        stem = Path(override).stem if Path(override).suffix else override
        stem = sanitize_filename_component(stem) or "geo_unnamed"
        basename = alloc_unique_basename(stem, used_basenames)
    else:
        basename = resolve_geo_usd_basename(
            publish_name=display_name or names[0],
            used=used_basenames,
        )
    filepath = ensure_usd_extension(str(out_dir / f"{basename}.usd"))
    return GeoExportJob(
        publish_name=display_name or names[0],
        output_basename=basename,
        filepath=filepath,
        mesh_names=names,
        list_asset_id=list_asset_id,
    )
