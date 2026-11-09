"""
Auto Material Builder controller — connects UI + logic + Solaris adapter.

Start page: where the textures come from, and the scene's assets built from Painter exports.
Version manager: one source's materials; for Painter exports, the version of each material.
"""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QMessageBox

from tools.fx.auto_material import config, updater
from tools.fx.auto_material.logic import (
    STATUS_OK,
    STATUS_UPDATE,
    asset_from_path,
    asset_kind,
    find_painter_usd,
    is_usd_path,
    latest_publish_version,
    list_painter_exports,
    new_library_name,
    pick_library,
    same_family,
    scan_and_group,
    substance_node_base,
    version_from_path,
    version_number,
)
from tools.fx.auto_material.ui import AutoMaterialUI

# How often the window reads the /stage selection while linked to it (ms)
SELECTION_POLL_MS = 400
# How often a read running off the main thread is checked for its result (ms)
READ_POLL_MS = 40

# Reads of files only (Painter exports with pxr, texture folders): never hou, which is main-thread only
_READER = ThreadPoolExecutor(max_workers=1, thread_name_prefix="monofx_auto_material")


def run(focus: str | None = None) -> None:
    """Open the window; *focus*: a Material Library path to open straight away (node menu)."""
    import importlib
    import apps.houdini.solaris_adapter as sa
    importlib.reload(sa)

    if not sa.is_available():
        return

    ui = AutoMaterialUI()
    ui.setWindowTitle(config.WINDOW_TITLE)

    # What the Version manager shows: a folder scan, or one asset's Painter exports.
    # assets: library path -> updater.SceneLibrary, the Start page's rows.
    state: dict = {"page": "start", "usd": None, "assets": {}, "folder_library": None}

    # ------------------------------------------------------------------
    # Scene assets (start page)
    # ------------------------------------------------------------------
    def scene_records(usd_path: str, library: str | None = None) -> tuple[str | None, dict]:
        """
        (library, material records) the scene has of the export's asset: *library* when given, else
        the asset's own {base}_materials, else the first library of the asset. Versions as the
        nodes have them (a material pasted from another version shows that version).
        """
        base = substance_node_base(usd_path)
        found = []
        for lib, text in sa.substance_libraries(sa.get_stage_context()):
            meta, records = sa.library_record(lib, text)
            if meta.get("export") and same_family(meta["export"], usd_path):
                found.append((lib.name(), records))
        for name, records in found:
            if name == library:
                return name, records
        if library:
            return library, {}
        own = base + config.SUBSTANCE_MATLIB_NODE_SUFFIX
        return next(((n, r) for n, r in found if n == own), found[0] if found else (None, {}))

    def asset_label(usd_path: str) -> tuple[str, str]:
        found = asset_from_path(usd_path)
        if found:
            return found[1], asset_kind(found[0])
        return substance_node_base(usd_path), "prop"

    def start_assets() -> list[dict]:
        """One row per library the tool built (Painter export or texture folder)."""
        libs = updater.scene_libraries(sa, sa.get_stage_context())
        state["assets"] = {lib.path: lib for lib in libs}
        return [{
            "key": lib.path,
            "name": lib.name,
            "kind": lib.kind,
            "meta": f"{lib.asset} · {lib.materials} materials",
            "chip": f"{lib.version}→{lib.latest}" if lib.needs_update else (lib.version or "?"),
            "status": STATUS_UPDATE if lib.needs_update else STATUS_OK,
            "tooltip": lib.source_label,
            "behind": lib.behind if lib.needs_update else 0,
            "total": lib.materials,
        } for lib in libs]

    def hip_painter_usd() -> str | None:
        publish = sa.resolve_publish_texture_folder()
        return find_painter_usd(publish) if publish else None

    def same_folder(a: str, b: str) -> bool:
        return os.path.normcase(os.path.normpath(a)) == os.path.normcase(os.path.normpath(b))

    def publish_card() -> tuple[str | None, str]:
        """Where the publish found from $HIP is, and what building from it will do."""
        usd = hip_painter_usd()
        if usd:
            name, _kind = asset_label(usd)
            lib = next((x for x in state["assets"].values()
                        if x.source == "usd" and same_family(x.location, usd)), None)
            if lib is None:
                action = "Create its materials and geometry"
            else:
                action = f"Update {lib.name}" if lib.needs_update else f"{lib.name} is up to date"
            return f"{name} · Painter USD {version_from_path(Path(usd).name) or ''} · from $HIP", action
        publish = sa.resolve_publish_texture_folder()
        if not publish:
            return None, ""
        newest = latest_publish_version(publish)
        found = asset_from_path(publish)
        name = found[1] if found else Path(publish).name
        groups, _unmatched = scan_and_group(publish)
        in_scene = {m for mats in sa.material_libraries(sa.get_stage_context()).values() for m in mats}
        new = [n for n in groups if n not in in_scene]
        old = [x for x in state["assets"].values()
               if x.source == "folder" and same_folder(x.location, publish) and x.needs_update]
        parts = [f"update {len(old)} librar{'ies' if len(old) != 1 else 'y'}"] if old else []
        parts += [f"create {len(new)} new material{'s' if len(new) != 1 else ''}"] if new else []
        action = " and ".join(parts)
        action = action[:1].upper() + action[1:] if action else "Everything is up to date"
        return f"{name} · textures {newest.name.lower() if newest else ''} · from $HIP", action

    def refresh_sidebar() -> None:
        """The scene's libraries and the publish found from $HIP, without touching what is open."""
        assets = start_assets()
        latest, action = publish_card()
        ui.show_start(latest, assets, action)

    def go_start() -> None:
        """First look: the first library behind its publish, else the publish not built yet, else
        the first library; nothing when the scene has none and there is no publish."""
        state["page"] = "start"
        state["usd"] = None
        ui.set_message("")
        refresh_sidebar()
        libs = list(state["assets"].values())
        behind = next((x for x in libs if x.needs_update), None)
        if behind is not None:
            on_open_asset(behind.path)
        elif (hip_painter_usd() or sa.resolve_publish_texture_folder()) and not libs:
            on_latest_publish()
        elif libs:
            on_open_asset(libs[0].path)

    # ------------------------------------------------------------------
    # Loading a source into the Version manager
    # ------------------------------------------------------------------
    reads = {"token": 0}

    def background(label: str, work, finish) -> None:
        """
        Run *work* (files only, no hou) off the main thread, the window free meanwhile; then
        *finish(result, error)* on the main thread. Opening something else drops this result. A
        result waits while a scene write blocks the window, so it never lands in the middle of one.
        """
        reads["token"] += 1
        token = reads["token"]
        ui.show_reading(label)
        future = _READER.submit(work)
        timer = QTimer(ui)
        timer.setInterval(READ_POLL_MS)

        def check() -> None:
            if not future.done() or ui.is_blocking():
                return
            timer.stop()
            timer.deleteLater()
            if token != reads["token"]:
                return
            ui.hide_reading()
            error = future.exception()
            finish(None if error else future.result(), error)

        timer.timeout.connect(check)
        timer.start()

    def open_folder(folder: str, library: str | None = None) -> None:
        """*library*: opened from its row, so that library is the target (no guessing)."""
        ui.set_message("")
        recursive = ui.is_recursive()
        background("Scanning textures…", lambda: scan_and_group(folder, recursive=recursive),
                   lambda result, error: show_folder(folder, library, result, error))

    def show_folder(folder: str, library: str | None, result, error) -> None:
        if error is not None:
            ui.set_message(f"Cannot read the folder: {error}", error=True)
            return
        groups, unmatched = result
        if not groups and not unmatched:
            ui.set_message("No image files found in this folder.", error=True)
            return
        state["page"], state["usd"] = "folder", None
        libraries = folder_targets()
        if library:
            lib, why = library, "fixed"
        else:
            lib, why = pick_library(libraries, list(groups), selected_library(), new_library_name(folder))
        ui.show_folder(folder, groups, unmatched, libraries, lib, why)
        ui.save_to_history(folder)

    def folder_targets() -> dict[str, dict[str, str]]:
        """Libraries a texture folder can go into: not the ones built from a Painter export, whose
        version record would no longer match (they update from their export)."""
        stage = sa.get_stage_context()
        painter = {lib.name() for lib, _record in sa.substance_libraries(stage)}
        return {k: v for k, v in sa.material_libraries(stage).items() if k not in painter}

    def scene_selection() -> list[str]:
        """Paths of the Material Libraries selected in /stage."""
        try:
            import hou
            return [n.path() for n in hou.selectedNodes()
                    if n.type().name() == "materiallibrary" and n.parent().path() == "/stage"]
        except Exception:
            return []

    def selected_library() -> str | None:
        """The one Material Library selected in /stage, while the window is linked to the selection."""
        paths = scene_selection() if ui.linked() else []
        return paths[0].rsplit("/", 1)[-1] if len(paths) == 1 else None

    def poll_selection() -> None:
        if ui.isVisible() and ui.linked():
            ui.set_scene_selection(scene_selection())

    def refresh_libraries() -> None:
        """The Library box again from the scene, keeping the library chosen."""
        ui.set_libraries(folder_targets())

    def open_usd(usd_path: str, library: str | None = None) -> None:
        """*library*: opened from its row, so that library (a copy too) is the one shown and built.
        What the scene has is read here (hou); every export is read off the main thread (pxr)."""
        ui.set_message("")
        name, records = scene_records(usd_path, library)
        background("Reading Painter exports…", lambda: updater.read_painter_asset(sa, usd_path, records),
                   lambda ctx, error: show_usd(usd_path, name, ctx, error))

    def show_usd(usd_path: str, library_name: str | None, ctx, error) -> None:
        if error is not None:
            ui.set_message(f"Cannot read the USD: {error}", error=True)
            return
        ctx["library"] = library_name
        if not ctx["plans"]:
            ui.set_message("No material with Painter textures in this USD.", error=True)
            return
        state["page"], state["usd"] = "usd", ctx
        latest = ctx["data"][ctx["latest"]]
        name, kind = asset_label(ctx["path"])
        geo = latest.source.geo_layers[0] if latest.source.geo_layers else ""
        # A publish keeps its version in the file name (_v005) or in its folder (…/v005/file.usd).
        folder = Path(geo).parent.name
        geo_v = version_from_path(geo) or (folder if version_number(folder) >= 0 and folder[:1] in "vV" else Path(geo).name)
        meta = " · ".join(x for x in (
            f"{name} · Painter USD",
            f"{len(ctx['exports'])} exports, latest {ctx['latest']}",
            f"geometry {geo_v}",
        ) if x)
        library = ctx["library"] or latest.source.node_base + config.SUBSTANCE_MATLIB_NODE_SUFFIX
        ui.show_usd(name, meta, kind, ctx["path"], ctx["plans"],
                    {v: d.groups for v, d in ctx["data"].items()}, set(latest.groups), library=library)
        ui.save_to_history(usd_path)

    def open_path(path: str) -> None:
        path = path.strip().strip('"')
        if is_usd_path(path):
            open_usd(path)
        elif Path(path).is_dir():
            open_folder(path)
        else:
            ui.set_message(f"Not a folder or a USD file: {path}", error=True)

    def on_latest_publish() -> None:
        ui.set_current("")
        usd = hip_painter_usd()
        publish = sa.resolve_publish_texture_folder()
        if usd or publish:
            open_path(usd or publish)
        elif sa.get_hip_dir() is None:
            ui.set_message("Save the .hip first: the publish is found from $HIP.", error=True)
        else:
            ui.set_message("Publish folder not found: $HIP/../../../03_surfacing/02_texturing/publish", error=True)

    def on_open_asset(key: str) -> None:
        lib = state["assets"].get(key)
        if lib is None:
            return
        ui.set_current(key)
        if lib.source == "usd":
            open_usd(lib.location, library=lib.name)
        else:
            open_folder(lib.location, library=lib.name)

    def on_reload() -> None:
        """Read the opened source again (the library it goes into stays)."""
        path = ui.source_path()
        if state["page"] == "usd" and state["usd"] is not None:
            open_usd(path, state["usd"].get("library"))
        elif state["page"] == "folder" and path:
            open_folder(path, library=ui.library())

    def on_undo() -> None:
        """The action bar's Undo: Houdini's undo of the last run (one step), then the window again."""
        try:
            import hou
            hou.undos.performUndo()
        except Exception as e:
            ui.set_message(f"Undo failed: {e}", error=True)
            return
        ui.show_undo(False)
        refresh_sidebar()
        on_reload()
        ui.set_message("Undone.")

    # A newer export while the Version manager is open: say so, change nothing.
    def on_activated() -> None:
        refresh_sidebar()
        if state["page"] == "folder":
            refresh_libraries()  # a library made, renamed or deleted while away
            return
        ctx = state["usd"]
        if state["page"] != "usd" or ctx is None:
            return
        exports = list_painter_exports(ctx["path"])
        if exports and version_number(exports[-1].version) > version_number(ctx["latest"]):
            name, _kind = asset_label(ctx["path"])
            ui.show_banner(f"{name} {exports[-1].version} was just published")

    def on_banner() -> None:
        ctx = state["usd"]
        if ctx is not None:
            open_usd(list_painter_exports(ctx["path"])[-1].usd_path, ctx.get("library"))

    # ------------------------------------------------------------------
    # Create / update
    # ------------------------------------------------------------------
    def stage_or_message():
        if not sa.is_lop_context_available():
            ui.set_message("Open a Solaris / LOP network first.", error=True)
            return None
        stage = sa.get_stage_context()
        if stage is None:
            ui.set_message("Cannot find /stage node.", error=True)
        return stage

    def done(created: list[str], updated: list[str], notes: list[str], cancelled: bool, library: str = "") -> None:
        parts = [f"created {len(created)}" if created else "", f"updated {len(updated)}" if updated else ""]
        text = ", ".join(p for p in parts if p)
        if text and library:
            text += f" in {library}"
        if cancelled:
            msg = f"Cancelled: {text} before cancel" if text else "Cancelled"
            ui.show_done(msg, "Click to continue")
            ui.set_message(msg, error=True)
        elif text:
            msg = f"Materials {text}."
            ui.show_done(msg, "Click to continue")
            ui.set_message(msg, error=False)
            ui.show_undo(True)
        else:
            ui.hide_loading()
            ui.set_message("Saved." if not notes else "Nothing was built.", error=False)
        # Notes go under the window, not in a dialog: a modal box blocks Houdini until it is closed.
        if notes:
            shown = notes[:4] + ([f"… and {len(notes) - 4} more"] if len(notes) > 4 else [])
            ui.set_message(ui.message() + "\n" + "\n".join(shown), error=cancelled, tooltip="\n".join(notes))

    def create_folder(stage) -> None:
        selected = sa.get_selected_lop_node()
        lib_name = ui.library()
        plans = [p for p in ui.plans() if p.enabled]
        ui.show_loading("Creating materials...")
        created: list[str] = []
        updated: list[str] = []
        notes: list[str] = []
        cancelled = False
        with sa.undo_group("MonoFX: Auto Material create"), sa.manual_update():
            for idx, plan in enumerate(plans):
                if ui.is_cancelled():
                    cancelled = True
                    break
                group = ui.group_for(plan)
                if group is None:
                    continue
                if ui.folder_status_of(plan) == STATUS_OK:
                    # Same version: left alone, unless it still has Houdini's %(UDIM)d
                    builder = stage.node(f"{lib_name}/{plan.name}")
                    if builder is not None and sa._uses_houdini_udim(builder):
                        sa.update_material(builder, group.slots, [])
                    continue
                ui.show_loading(f"Creating material {idx + 1}/{len(plans)}:  {plan.name}")
                result = sa.build_material(stage=stage, material_name=plan.name, slots=group.slots,
                                           mat_lib_name=lib_name, selected_node=selected)
                if result is None:
                    continue
                (updated if result.updated else created).append(result.node_name)
                notes += [f"{result.node_name}: {n}" for n in result.notes]
            mat_lib_node = stage.node(lib_name)
            if mat_lib_node and created:
                sa.layout_material_library(mat_lib_node, new_names=created)
            # Other libraries ticked under "Also used in": their materials only, none created
            groups = {p.name: ui.group_for(p) for p in plans if ui.group_for(p) is not None}
            for other in ([] if cancelled else ui.extra_libraries()):
                result = sa.update_folder_library(stage, other, groups, cancelled=ui.is_cancelled)
                updated += [f"{other}/{n}" for n in result.updated]
                notes += [f"{other}: {n}" for n in result.notes]
        refresh_libraries()  # chips: what was made or moved is now up to date
        refresh_sidebar()
        done(created, updated, notes, cancelled, library=mat_lib_node.path() if mat_lib_node else lib_name)

    def create_usd(stage) -> None:
        ctx = state["usd"]
        ui.show_loading("Building materials...")
        with sa.undo_group("MonoFX: Auto Material create"):
            result = sa.apply_painter_plan(stage, ctx["data"], ui.plans(), ctx["records"], ui.is_cancelled,
                                           library=ctx.get("library"))
        cancelled = ui.is_cancelled()
        refresh_sidebar()
        open_usd(ctx["path"], ctx.get("library"))  # chips now show the scene as it is; then the result
        lib = ctx.get("library") or ctx["data"][ctx["latest"]].source.node_base + config.SUBSTANCE_MATLIB_NODE_SUFFIX
        done(result.created, result.updated, result.notes, cancelled, library=f"{stage.path()}/{lib}")

    def on_create() -> None:
        stage = stage_or_message()
        if stage is None:
            return
        if state["page"] == "usd":
            create_usd(stage)
        else:
            create_folder(stage)

    def on_update_assets(keys: list[str]) -> None:
        stage = stage_or_message()
        if stage is None or not keys:
            return
        libs = [state["assets"][k] for k in keys if k in state["assets"]]
        created, updated, notes = updater.update_libraries(
            sa, stage, libs, ui.is_cancelled,
            progress=lambda i, lib: ui.show_loading(f"Updating {i}/{len(libs)}:  {lib.name}"))
        done(created, updated, notes, ui.is_cancelled())
        refresh_sidebar()
        on_reload()

    # --- Auto assign (texture folders) ---
    def on_auto_assign() -> None:
        if not sa.is_lop_context_available():
            ui.set_message("Open a Solaris / LOP network first.", error=True)
            return
        stage = sa.get_stage_context()
        if stage is None:
            ui.set_message("Cannot find /stage node.", error=True)
            return
        selected = sa.get_selected_lop_node()
        if selected is None:
            ui.set_message("Select a LOP node (e.g. merge output) that has the scene graph and /materials.", error=True)
            return
        ui.set_message("")
        ui.show_loading("Auto assigning materials...")
        try:
            with sa.undo_group("MonoFX: Auto assign"):
                created, msg = sa.run_auto_assign(stage, selected)
            ui.hide_loading()
            if created > 0:
                ui.show_done(msg, "Click to continue")
                ui.set_message(msg, error=False)
            else:
                stage_usd = sa.get_stage_from_lop_node(selected)
                materials = sa.get_material_names_under_scope(stage_usd) if stage_usd else {}
                if materials:
                    reply = QMessageBox.question(
                        ui,
                        config.WINDOW_TITLE,
                        "Không tìm thấy prim *_grp khớp với material. Bạn có muốn vẫn tạo sẵn Assign Material LOP cho từng material (để gán tay sau)?",
                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                        QMessageBox.StandardButton.No,
                    )
                    if reply == QMessageBox.StandardButton.Yes:
                        ui.show_loading("Đang tạo Assign Material LOP...")
                        try:
                            with sa.undo_group("MonoFX: Auto assign"):
                                n = sa.create_assign_for_all_materials(stage, selected, "/world/geo/*")
                            if n > 0:
                                done_msg = f"Đã tạo {n} Assign Material LOP (prim pattern: /world/geo/*). Gán tay sau."
                                ui.show_done(done_msg, "Click to continue")
                                ui.set_message(done_msg, error=False)
                            else:
                                ui.hide_loading()
                                ui.set_message(msg, error=True)
                        except Exception:
                            ui.hide_loading()
                            raise
                    else:
                        ui.set_message(msg, error=True)
                else:
                    ui.set_message(msg, error=True)
        except Exception as e:
            ui.hide_loading()
            ui.set_message(f"Auto assign failed: {e}", error=True)

    ui.on("latest_publish", on_latest_publish)
    ui.on("open_path", open_path)
    ui.on("open_asset", on_open_asset)
    ui.on("update_assets", on_update_assets)
    ui.on("undo", on_undo)
    ui.on("reload", on_reload)
    ui.on("create", on_create)
    ui.on("auto_assign", on_auto_assign)
    ui.on("banner", on_banner)
    ui.on("activated", on_activated)
    ui.open_library = on_open_asset  # the node menu's "Open in Auto Material" on a window already open

    # Link to selection: read the /stage selection while the window is up (no Houdini callback to undo)
    timer = QTimer(ui)
    timer.setInterval(SELECTION_POLL_MS)
    timer.timeout.connect(poll_selection)
    timer.start()

    go_start()
    if focus:
        on_open_asset(focus)

    # --- Show ---
    # A window owned by Houdini's main window stays above Houdini only, not above other apps.
    parent_win = sa.get_main_qt_window()
    from PySide6.QtCore import Qt
    if parent_win:
        ui.setParent(parent_win, ui.windowFlags() | Qt.WindowType.Window)
    ui.show()
