"""
Auto Material: the scene's Material Libraries and updating them to their latest publish, without
the window. Used by the Start page (In this scene, Update) and by the node menu (OPmenu.xml).
No Qt here, so the node menu runs without opening anything.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from tools.fx.auto_material.logic import (
    asset_from_path,
    asset_kind,
    latest_publish_version,
    list_painter_exports,
    plan_materials,
    scan_and_group,
    substance_node_base,
    version_number,
)


@dataclass
class SceneLibrary:
    """A Material Library the tool built: from a Painter export ("usd") or texture folders ("folder")."""
    path: str              # node path, the row's key
    name: str              # node name
    source: str            # "usd" | "folder"
    asset: str             # asset name (char_Helen), else the library name
    kind: str              # asset kind for the icon
    materials: int
    version: str           # what the scene has (the oldest material's)
    latest: str            # newest publish, "" when it cannot be found
    location: str          # newest export's .usd, or the publish folder
    records: dict          # usd: the scene's MaterialRecords
    behind: int = 0        # materials older than the latest publish

    @property
    def needs_update(self) -> bool:
        return bool(self.latest) and version_number(self.latest) > version_number(self.version)

    @property
    def source_label(self) -> str:
        return f"Painter USD · {self.location}" if self.source == "usd" else f"Texture folder · {self.location}"


def _asset(path: str, fallback: str) -> tuple[str, str]:
    found = asset_from_path(path)
    return (found[1], asset_kind(found[0])) if found else (fallback, "prop")


def scene_libraries(sa: Any, stage: Any) -> list[SceneLibrary]:
    """Every library the tool built in *stage*, Painter exports first, each in network order."""
    out: list[SceneLibrary] = []
    for lib, text in sa.substance_libraries(stage):
        meta, records = sa.library_record(lib, text)  # versions as the nodes have them
        export = meta.get("export") or ""
        if not export:
            continue
        exports = list_painter_exports(export) if Path(export).exists() else []
        latest = exports[-1] if exports else None
        asset, kind = _asset(export, substance_node_base(export))
        newest = latest.version if latest else ""
        behind = sum(1 for r in records.values()
                     if not r.left_out and r.version and version_number(r.version) < version_number(newest))
        out.append(SceneLibrary(
            lib.path(), lib.name(), "usd", asset, kind, len(records), meta.get("version") or "",
            newest, latest.usd_path if latest else export, records, behind,
        ))
    for info in sa.folder_libraries(stage):
        newest = latest_publish_version(info.publish)
        asset, kind = _asset(info.publish, info.name)
        newest_v = newest.name.lower() if newest else ""
        behind = sum(1 for v in info.versions.values() if v and version_number(v) < version_number(newest_v))
        out.append(SceneLibrary(
            info.path, info.name, "folder", asset, kind, len(info.versions), info.version,
            newest_v, info.publish, {}, behind,
        ))
    return out


def read_painter_asset(sa: Any, usd_path: str, records: dict) -> dict:
    """Every export of the asset, read, and the plan against what the scene has (*records*)."""
    exports = list_painter_exports(usd_path)
    data = sa.read_painter_exports(exports)
    if not data:
        raise RuntimeError("No Painter export could be read.")
    plans = plan_materials({v: d.groups for v, d in data.items()}, records)
    return {"path": exports[-1].usd_path, "exports": exports, "data": data,
            "latest": exports[-1].version, "records": records, "plans": plans}


def update_library(sa: Any, stage: Any, lib: SceneLibrary, cancelled: Callable[[], bool] | None = None) -> Any:
    """
    Move *lib* to its latest publish: pinned and left-out Painter materials stay, materials the
    publish no longer has stay, nothing new is created for a texture folder library.
    """
    if lib.source == "usd":
        ctx = read_painter_asset(sa, lib.location, lib.records)
        return sa.apply_painter_plan(stage, ctx["data"], ctx["plans"], ctx["records"], cancelled, library=lib.name)
    groups, _unmatched = scan_and_group(lib.location)
    return sa.update_folder_library(stage, lib.name, groups, cancelled=cancelled)


def update_libraries(sa: Any, stage: Any, libs: list[SceneLibrary],
                     cancelled: Callable[[], bool] | None = None,
                     progress: Callable[[int, SceneLibrary], None] | None = None) -> tuple[list, list, list]:
    """(created, updated, notes) for updating *libs*, all in one undo step."""
    created: list[str] = []
    updated: list[str] = []
    notes: list[str] = []
    with sa.undo_group("MonoFX: Auto Material update"):
        for i, lib in enumerate(libs, 1):
            if cancelled is not None and cancelled():
                break
            if progress is not None:
                progress(i, lib)
            try:
                result = update_library(sa, stage, lib, cancelled)
            except Exception as e:
                notes.append(f"{lib.name}: cannot update ({e})")
                continue
            created += result.created
            updated += [f"{lib.name}/{n}" for n in result.updated]
            notes += [f"{lib.name}: {n}" for n in result.notes]
    return created, updated, notes
