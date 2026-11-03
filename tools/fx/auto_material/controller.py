"""
Auto Material Builder controller — connects UI + logic + Solaris adapter.

Start page: where the textures come from, and the scene's assets built from Painter exports.
Version manager: one source's materials; for Painter exports, the version of each material.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QMessageBox

from tools.fx.auto_material import config
from tools.fx.auto_material.logic import (
    STATUS_NEW,
    STATUS_OK,
    STATUS_UPDATE,
    asset_from_path,
    asset_kind,
    find_painter_usd,
    is_usd_path,
    list_painter_exports,
    parse_record,
    plan_materials,
    scan_and_group,
    substance_node_base,
    version_from_path,
    version_number,
)
from tools.fx.auto_material.ui import AutoMaterialUI


def run() -> None:
    import importlib
    import apps.houdini.solaris_adapter as sa
    importlib.reload(sa)

    if not sa.is_available():
        return

    ui = AutoMaterialUI()
    ui.setWindowTitle(config.WINDOW_TITLE)

    # What the Version manager shows: a folder scan, or one asset's Painter exports.
    state: dict = {"page": "start", "usd": None, "assets": {}}

    # ------------------------------------------------------------------
    # Scene assets (start page)
    # ------------------------------------------------------------------
    def scene_records() -> dict[str, tuple[dict, dict]]:
        """node base -> (record fields, material records) for each library built from an export."""
        stage = sa.get_stage_context()
        out: dict[str, tuple[dict, dict]] = {}
        for _lib, text in sa.substance_libraries(stage):
            meta, records = parse_record(text)
            if meta.get("export"):
                out[substance_node_base(meta["export"])] = (meta, records)
        return out

    def asset_label(usd_path: str) -> tuple[str, str]:
        found = asset_from_path(usd_path)
        if found:
            return found[1], asset_kind(found[0])
        return substance_node_base(usd_path), "prop"

    def start_assets() -> list[dict]:
        stage = sa.get_stage_context()
        libraries = sa.substance_libraries(stage)
        branch = sa.branch_library(sa.get_selected_lop_node(), [lib for lib, _ in libraries])
        assets: list[dict] = []
        keys: dict[str, str] = {}
        for lib, text in libraries:
            meta, records = parse_record(text)
            export = meta.get("export") or ""
            if not export:
                continue
            exports = list_painter_exports(export) if Path(export).exists() else []
            latest = exports[-1] if exports else None
            scene_v = meta.get("version") or ""
            name, kind = asset_label(export)
            newer = latest is not None and version_number(latest.version) > version_number(scene_v)
            assets.append({
                "key": substance_node_base(export),
                "name": name,
                "kind": kind,
                "meta": f"{len(records)} materials · export {scene_v}",
                "chip": f"{scene_v}→{latest.version}" if newer else scene_v,
                "status": STATUS_UPDATE if newer else STATUS_OK,
                "branch": branch is not None and lib.path() == branch.path(),
            })
            keys[substance_node_base(export)] = (latest.usd_path if latest else export)
        # The .hip's own asset, when its latest export is not built yet.
        usd = hip_painter_usd()
        if usd and substance_node_base(usd) not in keys:
            name, kind = asset_label(usd)
            version = version_from_path(Path(usd).name) or ""
            assets.append({"key": substance_node_base(usd), "name": name, "kind": kind,
                           "meta": "Not in the scene yet", "chip": f"+{version}", "status": STATUS_NEW})
            keys[substance_node_base(usd)] = usd
        state["assets"] = keys
        return assets

    def hip_painter_usd() -> str | None:
        publish = sa.resolve_publish_texture_folder()
        return find_painter_usd(publish) if publish else None

    def go_start() -> None:
        state["page"] = "start"
        state["usd"] = None
        ui.set_message("")
        usd = hip_painter_usd()
        if usd:
            name, _kind = asset_label(usd)
            latest = f"{name} · {version_from_path(Path(usd).name) or ''} · USD"
        else:
            publish = sa.resolve_publish_texture_folder()
            latest = f"{Path(publish).name} · textures" if publish else None
        ui.show_start(latest, start_assets())

    # ------------------------------------------------------------------
    # Loading a source into the Version manager
    # ------------------------------------------------------------------
    def open_folder(folder: str) -> None:
        ui.set_message("")
        ui.show_loading("Scanning textures...")
        try:
            groups, unmatched = scan_and_group(folder, recursive=ui.is_recursive())
        finally:
            ui.hide_loading()
        if not groups and not unmatched:
            ui.set_message("No image files found in this folder.", error=True)
            return
        state["page"], state["usd"] = "folder", None
        ui.show_folder(folder, groups, unmatched)
        ui.save_to_history(folder)

    def read_asset(usd_path: str) -> dict:
        """Every export of the asset, read; and what the scene has of it."""
        exports = list_painter_exports(usd_path)
        data = sa.read_painter_exports(exports)
        if not data:
            raise RuntimeError("No Painter export could be read.")
        latest = exports[-1].version
        _meta, records = scene_records().get(substance_node_base(usd_path), ({}, {}))
        plans = plan_materials({v: d.groups for v, d in data.items()}, records)
        return {"path": exports[-1].usd_path, "exports": exports, "data": data,
                "latest": latest, "records": records, "plans": plans}

    def open_usd(usd_path: str) -> None:
        ui.set_message("")
        ui.show_loading("Reading Painter exports...")
        try:
            ctx = read_asset(usd_path)
        except Exception as e:
            ui.hide_loading()
            ui.set_message(f"Cannot read the USD: {e}", error=True)
            return
        ui.hide_loading()
        if not ctx["plans"]:
            ui.set_message("No material with Painter textures in this USD.", error=True)
            return
        state["page"], state["usd"] = "usd", ctx
        latest = ctx["data"][ctx["latest"]]
        name, kind = asset_label(ctx["path"])
        found = asset_from_path(ctx["path"])
        geo = latest.source.geo_layers[0] if latest.source.geo_layers else ""
        # A publish keeps its version in the file name (_v005) or in its folder (…/v005/file.usd).
        folder = Path(geo).parent.name
        geo_v = version_from_path(geo) or (folder if version_number(folder) >= 0 and folder[:1] in "vV" else Path(geo).name)
        meta = " · ".join(x for x in (
            found[0].lstrip("_") if found else "",
            f"{len(ctx['exports'])} exports, latest {ctx['latest']}",
            f"geometry {geo_v}",
        ) if x)
        ui.show_usd(name, meta, kind, ctx["path"], ctx["plans"],
                    {v: d.groups for v, d in ctx["data"].items()}, set(latest.groups))
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
        usd = hip_painter_usd()
        publish = sa.resolve_publish_texture_folder()
        if usd or publish:
            open_path(usd or publish)
        elif sa.get_hip_dir() is None:
            ui.set_message("Save the .hip first: the publish is found from $HIP.", error=True)
        else:
            ui.set_message("Publish folder not found: $HIP/../../../03_surfacing/02_texturing/publish", error=True)

    def on_open_asset(key: str) -> None:
        path = state["assets"].get(key)
        if path:
            open_usd(path)

    def on_reload() -> None:
        path = ui.source_path()
        if state["page"] in ("folder", "usd") and path:
            open_path(path)

    # A newer export while the Version manager is open: say so, change nothing.
    def on_activated() -> None:
        if state["page"] == "start":
            go_start()
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
            open_usd(list_painter_exports(ctx["path"])[-1].usd_path)

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

    def done(created: list[str], updated: list[str], notes: list[str], cancelled: bool) -> None:
        parts = [f"created {len(created)}" if created else "", f"updated {len(updated)}" if updated else ""]
        text = ", ".join(p for p in parts if p)
        if cancelled:
            msg = f"Cancelled: {text} before cancel" if text else "Cancelled"
            ui.show_done(msg, "Click to continue")
            ui.set_message(msg, error=True)
        elif text:
            msg = f"Materials {text}."
            ui.show_done(msg, "Click to continue")
            ui.set_message(msg, error=False)
        else:
            ui.hide_loading()
            ui.set_message("Saved." if not notes else "Nothing was built.", error=False)
        if notes:
            QMessageBox.information(ui, config.WINDOW_TITLE, "\n".join(notes))

    def create_folder(stage) -> None:
        selected = sa.get_selected_lop_node()
        names = ui.get_all_material_prefixes()
        ui.show_loading("Creating materials...")
        created: list[str] = []
        updated: list[str] = []
        notes: list[str] = []
        cancelled = False
        with sa.manual_update():
            mat_lib_node = None
            for idx, plan in enumerate(p for p in ui.plans() if p.enabled):
                if ui.is_cancelled():
                    cancelled = True
                    break
                ui.show_loading(f"Creating material {idx + 1}/{len(names)}:  {plan.name}")
                group = ui.group_for(plan)
                if group is None:
                    continue
                result = sa.build_material(stage=stage, material_name=plan.name, slots=group.slots,
                                           selected_node=selected)
                if result is None:
                    continue
                (updated if result.updated else created).append(result.node_name)
                notes += [f"{result.node_name}: {n}" for n in result.notes]
                if mat_lib_node is None:
                    mat_lib_node = stage.node("materiallibrary1")
            if mat_lib_node and created:
                sa.layout_material_library(mat_lib_node, new_names=created)
        done(created, updated, notes, cancelled)

    def create_usd(stage) -> None:
        ctx = state["usd"]
        ui.show_loading("Building materials...")
        result = sa.apply_painter_plan(stage, ctx["data"], ui.plans(), ctx["records"], ui.is_cancelled)
        done(result.created, result.updated, result.notes, ui.is_cancelled())
        open_usd(ctx["path"])  # chips now show the scene as it is

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
        created: list[str] = []
        updated: list[str] = []
        notes: list[str] = []
        for i, key in enumerate(keys, 1):
            path = state["assets"].get(key)
            if not path:
                continue
            ui.show_loading(f"Updating asset {i}/{len(keys)}:  {asset_label(path)[0]}")
            if ui.is_cancelled():
                break
            try:
                ctx = read_asset(path)
            except Exception as e:
                notes.append(f"{asset_label(path)[0]}: cannot read ({e})")
                continue
            result = sa.apply_painter_plan(stage, ctx["data"], ctx["plans"], ctx["records"], ui.is_cancelled)
            created += result.created
            updated += result.updated
            notes += result.notes
        done(created, updated, notes, ui.is_cancelled())
        go_start()

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
    ui.on("change", go_start)
    ui.on("reload", on_reload)
    ui.on("create", on_create)
    ui.on("auto_assign", on_auto_assign)
    ui.on("banner", on_banner)
    ui.on("activated", on_activated)

    go_start()

    # --- Show ---
    parent_win = sa.get_main_qt_window()
    from PySide6.QtCore import Qt
    if parent_win:
        flags = ui.windowFlags() | Qt.WindowType.Window | Qt.WindowType.WindowStaysOnTopHint
        ui.setWindowFlags(flags)
        ui.setParent(parent_win, flags)
    else:
        ui.setWindowFlags(ui.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)
    ui.show()
