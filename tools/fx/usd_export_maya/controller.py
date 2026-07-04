"""
USD Publish — entry point; wires UI, logic, Maya adapter.
"""

from __future__ import annotations

import importlib
import json
import os
import traceback
from pathlib import Path
from typing import List, Optional

from PySide6.QtCore import Qt, QSettings
from PySide6.QtWidgets import QApplication

from tools.fx.usd_export_maya import config
from tools.fx.usd_export_maya.logic import (
    apply_scene_filename_to_export_jobs,
    build_export_jobs,
    list_existing_version_folders,
    load_rules_file,
    next_version_folder_name,
    publish_versions_scan_root,
)

_active_ui: Optional[object] = None


def _as_bool(v: object, default: bool = False) -> bool:
    if isinstance(v, str):
        return v.lower() in ("1", "true", "yes")
    if v is None:
        return default
    return bool(v)


def _is_stale_publish_path(path: str) -> bool:
    """Locked path points at the wrong ``.../maya/work/publish`` (or nested) tree."""
    if not path or not str(path).strip():
        return False
    n = os.path.normpath(str(path)).replace("\\", "/").lower().rstrip("/")
    if "/maya/work/publish" in n:
        return True
    if n.endswith("/work/publish"):
        return True
    return False


def run() -> None:
    global _active_ui

    try:
        import apps.maya.adapter as maya_adapter
    except ImportError as e:
        print(f"[USD Publish] Import error: {e}")
        traceback.print_exc()
        return

    importlib.reload(maya_adapter)

    if not maya_adapter.is_available():
        print(
            "[USD Publish] maya.cmds not available — run inside Maya (Script Editor), "
            "not with a standalone python.exe."
        )
        return

    try:
        import maya.utils as mu  # type: ignore
    except ImportError:
        mu = None  # type: ignore[assignment]

    def _build_and_show() -> None:
        global _active_ui

        import tools.fx.usd_export_maya.ui as ui_mod

        importlib.reload(ui_mod)

        settings = QSettings(config.SETTINGS_ORG, config.SETTINGS_APP)
        app = QApplication.instance()

        parent = maya_adapter.get_main_qt_window()
        ui = ui_mod.UsdExportMayaUI(parent)
        _active_ui = ui

        ui.setWindowTitle(config.WINDOW_TITLE)
        if parent:
            ui.setWindowFlags(ui.windowFlags() | Qt.WindowType.Window)

        rules_default = config.default_rules_path()
        publish_locked = _as_bool(
            settings.value(config.SETTINGS_KEY_PUBLISH_LOCKED, False), False
        )
        rules = settings.value("rules_path", rules_default) or rules_default
        output_preset = str(settings.value(config.SETTINGS_KEY_OUTPUT_PATH_PRESET, "anim") or "anim")
        cam_render = _as_bool(settings.value(config.SETTINGS_KEY_CAMERA_RENDERABLE, False))
        skip_hidden = _as_bool(settings.value(config.SETTINGS_KEY_SKIP_HIDDEN, True), True)
        geo_non_ref = _as_bool(
            settings.value(config.SETTINGS_KEY_GEOMETRY_INCLUDE_NON_REFERENCE, True), True
        )
        auto_name_scene = _as_bool(
            settings.value(config.SETTINGS_KEY_AUTO_NAME_FROM_SCENE, False), False
        )
        subdivide = _as_bool(settings.value(config.SETTINGS_KEY_SUBDIVIDE, False), False)
        normals = _as_bool(settings.value(config.SETTINGS_KEY_NORMALS, False), False)
        export_uvs = _as_bool(settings.value(config.SETTINGS_KEY_EXPORT_UVS, True), True)
        export_anim = _as_bool(settings.value(config.SETTINGS_KEY_EXPORT_ANIM, True), True)
        try:
            export_scale = float(settings.value(config.SETTINGS_KEY_SCALE, 1.0) or 1.0)
        except Exception:
            export_scale = 1.0
        usd_raw = str(settings.value(config.SETTINGS_KEY_USD_OPTIONS_RAW, "") or "")
        rules_override_json = str(
            settings.value(config.SETTINGS_KEY_RULES_OVERRIDE_JSON, "") or ""
        )
        ver_mode = str(settings.value(config.SETTINGS_KEY_PUBLISH_VERSION_MODE, "auto") or "auto")
        try:
            ver_num = int(settings.value(config.SETTINGS_KEY_PUBLISH_VERSION_NUMBER, 1) or 1)
        except Exception:
            ver_num = 1
        ver_num = max(1, min(999, ver_num))
        ver_folder = str(settings.value(config.SETTINGS_KEY_PUBLISH_VERSION_FOLDER, "") or "")

        scene = maya_adapter.get_scene_path() or ""
        ui.set_output_path_preset(output_preset)
        auto_pub = maya_adapter.publish_root_from_scene_preset(ui.get_output_path_preset()) or ""
        if publish_locked:
            pub = str(settings.value("publish_root", "") or "")
            if _is_stale_publish_path(pub):
                publish_locked = False
                settings.setValue(config.SETTINGS_KEY_PUBLISH_LOCKED, False)
                settings.remove("publish_root")
                pub = auto_pub if scene else ""
        else:
            pub = auto_pub if scene else ""

        ui.set_auto_publish_supplier(
            lambda: maya_adapter.publish_root_from_scene_preset(ui.get_output_path_preset()) or ""
        )
        ui.set_publish_locked(publish_locked)
        ui.set_publish_root(pub)
        ui.set_rules_path(str(rules))
        ui.set_camera_require_renderable(cam_render)
        ui.set_skip_hidden_outliner(skip_hidden)
        ui.set_geometry_include_non_reference(geo_non_ref)
        ui.set_auto_name_from_scene(auto_name_scene)
        ui.set_export_subdivide(subdivide)
        ui.set_export_normals(normals)
        ui.set_export_uvs(export_uvs)
        ui.set_export_anim(export_anim)
        ui.set_scale(export_scale)
        ui.set_usd_options_raw(usd_raw)
        ui.set_rules_override_json(rules_override_json)
        ui.set_publish_version(ver_mode, ver_num, ver_folder)
        # Scene path is used internally for path resolution; main UI shows publish path preview instead.

        def save_settings() -> None:
            locked = ui.get_publish_locked()
            settings.setValue(config.SETTINGS_KEY_PUBLISH_LOCKED, locked)
            if locked:
                settings.setValue("publish_root", ui.get_publish_root())
            else:
                settings.remove("publish_root")
            settings.setValue("rules_path", ui.get_rules_path())
            settings.setValue(config.SETTINGS_KEY_OUTPUT_PATH_PRESET, ui.get_output_path_preset())
            settings.setValue(
                config.SETTINGS_KEY_CAMERA_RENDERABLE,
                ui.get_camera_require_renderable(),
            )
            settings.setValue(
                config.SETTINGS_KEY_SKIP_HIDDEN,
                ui.get_skip_hidden_outliner(),
            )
            settings.setValue(
                config.SETTINGS_KEY_GEOMETRY_INCLUDE_NON_REFERENCE,
                ui.get_geometry_include_non_reference(),
            )
            settings.setValue(
                config.SETTINGS_KEY_AUTO_NAME_FROM_SCENE,
                ui.get_auto_name_from_scene(),
            )
            settings.setValue(
                config.SETTINGS_KEY_SUBDIVIDE,
                ui.get_export_subdivide(),
            )
            settings.setValue(
                config.SETTINGS_KEY_NORMALS,
                ui.get_export_normals(),
            )
            settings.setValue(config.SETTINGS_KEY_EXPORT_UVS, ui.get_export_uvs())
            settings.setValue(config.SETTINGS_KEY_EXPORT_ANIM, ui.get_export_anim())
            settings.setValue(config.SETTINGS_KEY_SCALE, ui.get_scale())
            settings.setValue(config.SETTINGS_KEY_USD_OPTIONS_RAW, ui.get_usd_options_raw())
            settings.setValue(
                config.SETTINGS_KEY_RULES_OVERRIDE_JSON,
                ui.get_rules_override_json(),
            )
            settings.setValue(config.SETTINGS_KEY_PUBLISH_VERSION_MODE, ui.get_publish_version_mode())
            settings.setValue(
                config.SETTINGS_KEY_PUBLISH_VERSION_NUMBER,
                ui.get_publish_version_number(),
            )
            settings.setValue(
                config.SETTINGS_KEY_PUBLISH_VERSION_FOLDER,
                ui.get_publish_version_overwrite_folder(),
            )

        def apply_publish_from_scene() -> None:
            if ui.get_publish_locked():
                return
            sc = maya_adapter.get_scene_path()
            if sc:
                ui.set_publish_root(
                    maya_adapter.publish_root_from_scene_preset(ui.get_output_path_preset()) or ""
                )
            else:
                ui.set_publish_root("")

        def refresh_version_hint() -> None:
            root = ui.get_publish_root().strip()
            if not root:
                preset = ui.get_output_path_preset()
                scene_ok = bool(maya_adapter.get_scene_path())
                if not scene_ok:
                    ui.set_publish_path_preview(
                        "— Save the scene first — cannot resolve publish path."
                    )
                elif preset == "anim":
                    ui.set_publish_path_preview(
                        "Anim publish: no anim task folder in path (e.g. …/01_anim/…). "
                        "Rig/asset without 01_anim — use Custom and set publish root manually."
                    )
                elif preset == "uv":
                    ui.set_publish_path_preview(
                        "UV preset: scene is not under 01_assets/… — use Custom or Anim."
                    )
                else:
                    ui.set_publish_path_preview("—")
                ui.set_version_overwrite_options([])
                return
            root_base = str(publish_versions_scan_root(root))
            folders = list_existing_version_folders(root)
            ui.set_version_overwrite_options(folders)
            mode = ui.get_publish_version_mode()
            if mode == "manual":
                vname = f"v{ui.get_publish_version_number():03d}"
                ui.set_publish_path_preview(str(Path(root_base) / vname))
            elif mode == "overwrite":
                ow = ui.get_publish_version_overwrite_folder()
                if ow:
                    ui.set_publish_path_preview(str(Path(root_base) / ow))
                elif folders:
                    ui.set_publish_path_preview(str(Path(root_base) / folders[-1]))
                else:
                    ui.set_publish_path_preview(
                        f"{root_base} — (no v### folders yet; publish once or use Auto/Manual)"
                    )
            else:
                vnext = next_version_folder_name(root)
                ui.set_publish_path_preview(str(Path(root_base) / vnext))
                try:
                    ui.update_auto_version_spin(int(vnext[1:]))
                except Exception:
                    ui.update_auto_version_spin(1)

        def do_rescan() -> None:
            apply_publish_from_scene()
            save_settings()
            ui.show_loading("Scanning scene...")
            if app:
                app.processEvents()
            rules_path = ui.get_rules_path().strip()
            if not rules_path or not Path(rules_path).is_file():
                ui.set_jobs([])
                ui.set_status("Rules file missing or invalid — set in Settings.")
                refresh_version_hint()
                ui.hide_loading()
                if app:
                    app.processEvents()
                return
            try:
                _, rule_list = load_rules_file(rules_path)
            except Exception as e:
                ui.set_jobs([])
                ui.show_error("Rules", str(e))
                refresh_version_hint()
                ui.hide_loading()
                if app:
                    app.processEvents()
                return

            # If user edited rules in Settings, override rules file.
            override = ui.get_rules_override_json().strip()
            if override:
                try:
                    data = json.loads(override)
                    if isinstance(data, dict) and isinstance(data.get("rules"), list):
                        rule_list = data["rules"]
                except Exception:
                    pass

            cams = maya_adapter.collect_export_cameras(
                only_renderable=ui.get_camera_require_renderable()
            )
            refs = maya_adapter.collect_reference_geometry_roots(
                include_non_reference=ui.get_geometry_include_non_reference()
            )
            xforms = maya_adapter.collect_transforms_long()
            jobs = build_export_jobs(
                rule_list, cameras=cams, ref_geometry=refs, transforms_long=xforms
            )
            if ui.get_skip_hidden_outliner():
                jobs = [j for j in jobs if maya_adapter.is_dag_visible(j.dag_path)]
            if ui.get_auto_name_from_scene():
                jobs = apply_scene_filename_to_export_jobs(
                    jobs, maya_adapter.get_scene_path() or ""
                )
            ui.set_jobs(jobs)
            if not jobs:
                ui.set_status(
                    "No targets: add a camera (not persp/top/front/side), or Geometry / GEO / Geo "
                    "(reference or enable native Geometry in Settings), or extend "
                    "default_rules.json (transform_regex)."
                )
            else:
                ui.set_status(f"Found {len(jobs)} export target(s).")
            refresh_version_hint()
            ui.hide_loading()
            if app:
                app.processEvents()

        def on_scene_changed() -> None:
            apply_publish_from_scene()
            refresh_version_hint()
            do_rescan()

        cb_ids = maya_adapter.add_scene_changed_callbacks(on_scene_changed)
        ui.set_on_close(lambda: maya_adapter.remove_scene_changed_callbacks(cb_ids))

        def do_publish() -> None:
            apply_publish_from_scene()
            save_settings()
            publish_root_raw = ui.get_publish_root().strip()
            if not publish_root_raw:
                ui.show_error(
                    "Publish",
                    "No publish folder (save the scene or set a locked path in Settings).",
                )
                return
            publish_base = publish_versions_scan_root(publish_root_raw)
            jobs = ui.checked_jobs()
            if not jobs:
                ui.show_error("Publish", "No rows selected for export.")
                return
            rules_path = ui.get_rules_path().strip()
            if not rules_path:
                ui.show_error("Publish", "Set rules file in Settings.")
                return

            mode_v = ui.get_publish_version_mode()
            if mode_v == "manual":
                vname = f"v{ui.get_publish_version_number():03d}"
            elif mode_v == "overwrite":
                vname = ui.get_publish_version_overwrite_folder().strip()
                if not vname:
                    ui.show_error(
                        "Publish",
                        "Overwrite: pick an existing version folder (none found under publish root).",
                    )
                    return
            else:
                vname = next_version_folder_name(str(publish_base))
            out_dir = publish_base / vname
            if mode_v == "overwrite":
                if not out_dir.is_dir():
                    ui.show_error(
                        "Publish",
                        f"Overwrite: folder does not exist:\n{out_dir}",
                    )
                    return
            else:
                try:
                    out_dir.mkdir(parents=True, exist_ok=True)
                except Exception as e:
                    ui.show_error("Publish", f"Cannot create folder:\n{e}")
                    return

            uv = ui.get_export_uvs()
            anim = ui.get_export_anim()
            scale = ui.get_scale()
            subdiv = ui.get_export_subdivide()
            normals_opt = ui.get_export_normals()
            outputs: List[dict] = []
            failed: List[str] = []

            ui.show_loading(f"Publishing {len(jobs)} USD file(s)...")
            if app:
                app.processEvents()
            for job in jobs:
                if ui.is_cancelled():
                    failed.append("cancelled")
                    break
                fname = f"{job.output_basename}.usd"
                fpath = str(out_dir / fname)
                try:
                    ui.show_loading(f"Exporting: {fname}")
                    if app:
                        app.processEvents()
                    if ui.get_skip_hidden_outliner() and not maya_adapter.is_dag_visible(job.dag_path):
                        continue
                    maya_adapter.select_single_dag(job.dag_path)
                    maya_adapter.export_selection_usd(
                        fpath,
                        export_uvs=uv,
                        export_anim=anim,
                        strip_namespaces=True,
                        scale=scale,
                        export_subdivide=subdiv,
                        export_normals=normals_opt,
                        usd_options_raw=ui.get_usd_options_raw(),
                    )
                    outputs.append(
                        {
                            "file": fname,
                            "rule_id": job.rule_id,
                            "dag": job.dag_path,
                        }
                    )
                except Exception as e:
                    failed.append(f"{job.output_basename}: {e}")
                finally:
                    if app:
                        app.processEvents()

            meta = maya_adapter.build_meta_dict(
                version_folder=vname,
                outputs=outputs,
                export_uvs=uv,
                export_anim=anim,
                strip_namespaces=True,
                scale=scale,
                export_subdivide=subdiv,
                export_normals=normals_opt,
                rules_path=rules_path,
                geometry_include_non_reference=ui.get_geometry_include_non_reference(),
            )
            meta_path = out_dir / config.META_FILENAME
            try:
                meta_path.write_text(
                    json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8"
                )
            except Exception as e:
                failed.append(f"meta: {e}")

            if failed:
                ui.set_status("Completed with errors:\n" + "\n".join(failed[:8]))
                ui.show_error("Publish", "Some exports failed:\n" + "\n".join(failed[:12]))
            else:
                ui.set_status(f"Published {len(outputs)} file(s) → {out_dir}")
                ui.show_done(f"Published {len(outputs)} file(s)", "Click to continue")
                ui.show_info("Publish", f"Done.\n{out_dir}")

            ui.hide_loading()
            if app:
                app.processEvents()
            do_rescan()

        def on_output_preset_changed() -> None:
            apply_publish_from_scene()
            save_settings()
            refresh_version_hint()

        def open_publish_folder() -> None:
            publish_root = ui.get_publish_root().strip()
            if not publish_root:
                ui.show_error(
                    "Open Publish Folder",
                    "No publish folder (save the scene or set a locked path in Settings).",
                )
                return
            p = Path(publish_root)
            if not p.exists():
                ui.show_error(
                    "Open Publish Folder",
                    f"Folder does not exist:\n{publish_root}",
                )
                return
            try:
                os.startfile(str(p))  # type: ignore[attr-defined]
            except Exception as e:
                ui.show_error("Open Publish Folder", f"Failed to open folder:\n{e}")

        ui.set_callbacks(
            do_rescan,
            do_publish,
            open_publish_folder,
            refresh_version_hint,
            on_output_preset_changed=on_output_preset_changed,
        )
        apply_publish_from_scene()
        refresh_version_hint()
        do_rescan()
        ui.show()
        ui.raise_()
        ui.activateWindow()
        app = QApplication.instance()
        if app:
            app.processEvents()

        print("[USD Publish] Window opened.")

    if mu is not None:
        mu.executeDeferred(_build_and_show)
        print("[USD Publish] Scheduled UI (executeDeferred).")
    else:
        _build_and_show()
