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
from tools.fx.usd_export_maya.logic import build_export_jobs, load_rules_file, next_version_folder_name

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
            "[USD Publish] maya.cmds khong co — chi chay trong Maya (Script Editor), "
            "khong chay bang python.exe ngoai Maya."
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
        cam_render = _as_bool(settings.value(config.SETTINGS_KEY_CAMERA_RENDERABLE, False))
        skip_hidden = _as_bool(settings.value(config.SETTINGS_KEY_SKIP_HIDDEN, True), True)

        scene = maya_adapter.get_scene_path() or ""
        auto_pub = maya_adapter.default_publish_root_from_scene() or ""
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
            lambda: maya_adapter.default_publish_root_from_scene() or ""
        )
        ui.set_publish_locked(publish_locked)
        ui.set_publish_root(pub)
        ui.set_rules_path(str(rules))
        ui.set_camera_require_renderable(cam_render)
        ui.set_skip_hidden_outliner(skip_hidden)
        ui.set_scene_path_display(scene)

        def save_settings() -> None:
            locked = ui.get_publish_locked()
            settings.setValue(config.SETTINGS_KEY_PUBLISH_LOCKED, locked)
            if locked:
                settings.setValue("publish_root", ui.get_publish_root())
            else:
                settings.remove("publish_root")
            settings.setValue("rules_path", ui.get_rules_path())
            settings.setValue(
                config.SETTINGS_KEY_CAMERA_RENDERABLE,
                ui.get_camera_require_renderable(),
            )
            settings.setValue(
                config.SETTINGS_KEY_SKIP_HIDDEN,
                ui.get_skip_hidden_outliner(),
            )

        def apply_publish_from_scene() -> None:
            if ui.get_publish_locked():
                return
            sc = maya_adapter.get_scene_path()
            if sc:
                ui.set_publish_root(maya_adapter.default_publish_root_from_scene() or "")
            else:
                ui.set_publish_root("")

        def refresh_version_hint() -> None:
            root = ui.get_publish_root().strip()
            if not root:
                ui.set_next_version_label("Next folder: —")
                return
            ui.set_next_version_label(f"Next folder: {next_version_folder_name(root)}/")

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

            cams = maya_adapter.collect_export_cameras(
                only_renderable=ui.get_camera_require_renderable()
            )
            refs = maya_adapter.collect_reference_geometry_roots()
            xforms = maya_adapter.collect_transforms_long()
            jobs = build_export_jobs(
                rule_list, cameras=cams, ref_geometry=refs, transforms_long=xforms
            )
            if ui.get_skip_hidden_outliner():
                jobs = [j for j in jobs if maya_adapter.is_dag_visible(j.dag_path)]
            ui.set_jobs(jobs)
            if not jobs:
                ui.set_status(
                    "No targets: add a camera (not persp/top/front/side), or a reference "
                    "with ns:Geometry / GEO / Geo, or extend default_rules.json (transform_regex)."
                )
            else:
                ui.set_status(f"Found {len(jobs)} export target(s).")
            refresh_version_hint()
            ui.hide_loading()
            if app:
                app.processEvents()

        def on_scene_changed() -> None:
            apply_publish_from_scene()
            ui.set_scene_path_display(maya_adapter.get_scene_path() or "")
            refresh_version_hint()
            do_rescan()

        cb_ids = maya_adapter.add_scene_changed_callbacks(on_scene_changed)
        ui.set_on_close(lambda: maya_adapter.remove_scene_changed_callbacks(cb_ids))

        def do_publish() -> None:
            apply_publish_from_scene()
            save_settings()
            publish_root = ui.get_publish_root().strip()
            if not publish_root:
                ui.show_error(
                    "Publish",
                    "No publish folder (save the scene or set a locked path in Settings).",
                )
                return
            jobs = ui.checked_jobs()
            if not jobs:
                ui.show_error("Publish", "No rows selected for export.")
                return
            rules_path = ui.get_rules_path().strip()
            if not rules_path:
                ui.show_error("Publish", "Set rules file in Settings.")
                return

            vname = next_version_folder_name(publish_root)
            out_dir = Path(publish_root) / vname
            try:
                out_dir.mkdir(parents=True, exist_ok=True)
            except Exception as e:
                ui.show_error("Publish", f"Cannot create folder:\n{e}")
                return

            uv = ui.get_export_uvs()
            anim = ui.get_export_anim()
            scale = ui.get_scale()
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
                rules_path=rules_path,
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

        ui.set_callbacks(do_rescan, do_publish, refresh_version_hint)
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
