"""
Render Preview Maya — entry point; wires UI, logic, Maya adapter.
"""

from __future__ import annotations

import importlib
import os
import traceback
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, QSettings
from PySide6.QtWidgets import QApplication

from tools.fx.render_preview_maya import config
from tools.fx.render_preview_maya.logic import (
    PlayblastRequest,
    default_basename_from_scene,
    default_output_root_from_scene,
    normalize_ext,
    validate_frame_range,
)

_active_ui: Optional[object] = None


def run() -> None:
    global _active_ui

    try:
        import apps.maya.adapter as maya_adapter
    except ImportError as e:
        print(f"[Render Preview] Import error: {e}")
        traceback.print_exc()
        return

    importlib.reload(maya_adapter)

    if not maya_adapter.is_available():
        print(
            "[Render Preview] maya.cmds khong co — chi chay trong Maya (Script Editor), "
            "khong chay bang python.exe ngoai Maya."
        )
        return

    try:
        import maya.utils as mu  # type: ignore
    except ImportError:
        mu = None  # type: ignore[assignment]

    def _build_and_show() -> None:
        global _active_ui
        import tools.fx.render_preview_maya.ui as ui_mod

        importlib.reload(ui_mod)

        settings = QSettings(config.SETTINGS_ORG, config.SETTINGS_APP)
        parent = maya_adapter.get_main_qt_window()
        ui = ui_mod.RenderPreviewMayaUI(parent)
        _active_ui = ui

        ui.setWindowTitle(config.WINDOW_TITLE)
        if parent:
            ui.setWindowFlags(ui.windowFlags() | Qt.WindowType.Window)

        scene = maya_adapter.get_scene_path() or ""
        # Prefer scene animation range if available; else playback range.
        astart, aend = maya_adapter.get_animation_range()
        if astart is not None and aend is not None:
            start, end = int(astart), int(aend)
        else:
            start, end = maya_adapter.get_playback_range()
        fps = float(maya_adapter.get_scene_fps() or 24.0)

        # Output path should follow the current scene by default.
        # We keep QSettings for user preferences, but avoid stale shot names across scenes.
        output_root_saved = str(settings.value(config.SETTINGS_KEY_OUTPUT_ROOT, "") or "")
        basename_saved = str(settings.value(config.SETTINGS_KEY_BASENAME, "") or "")
        ext = normalize_ext(str(settings.value(config.SETTINGS_KEY_EXT, "jpg") or "jpg"), "jpg")
        try:
            w = int(settings.value(config.SETTINGS_KEY_WIDTH, 1920) or 1920)
        except Exception:
            w = 1920
        try:
            h = int(settings.value(config.SETTINGS_KEY_HEIGHT, 1080) or 1080)
        except Exception:
            h = 1080
        # Always default range from current scene on startup.
        a, b = validate_frame_range(start, end)

        output_root_scene = default_output_root_from_scene(scene) if scene else ""
        basename_scene = default_basename_from_scene(scene) if scene else "untitled"

        output_root = output_root_scene or output_root_saved
        basename = basename_scene or basename_saved or "untitled"

        def _as_bool(v: object, default: bool = False) -> bool:
            if isinstance(v, str):
                s = v.lower().strip()
                if s in ("1", "true", "yes", "on"):
                    return True
                if s in ("0", "false", "no", "off"):
                    return False
                return default if s == "" else bool(v)
            if v is None:
                return default
            return bool(v)

        def _bool_setting(key: str, default: bool) -> bool:
            """Stable defaults: missing keys use ``default`` (HUD keys default ON)."""
            if not settings.contains(key):
                return default
            try:
                v = settings.value(key, default, type=bool)
                if isinstance(v, bool):
                    return v
            except Exception:
                pass
            return _as_bool(settings.value(key), default)

        activate = _bool_setting(config.SETTINGS_KEY_ACTIVATE_SHOT_CAMERA, True)
        rename_to_camera = _bool_setting(config.SETTINGS_KEY_RENAME_TO_CAMERA, False)
        loop = _bool_setting(config.SETTINGS_KEY_LOOP, False)
        force_over = _bool_setting(config.SETTINGS_KEY_FORCE_SHOT_OVERSCAN_1, True)
        hud_enabled = _bool_setting(config.SETTINGS_KEY_VIEWPORT_HUD_ENABLED, True)
        hud_font = str(settings.value(config.SETTINGS_KEY_VIEWPORT_HUD_FONT_SIZE, "large") or "large").lower().strip()
        if hud_font not in ("small", "large"):
            hud_font = "large"
        hud_shot = _bool_setting(config.SETTINGS_KEY_VIEWPORT_HUD_SHOW_SHOT, True)
        hud_frame = _bool_setting(config.SETTINGS_KEY_VIEWPORT_HUD_SHOW_FRAME, True)
        hud_cam = _bool_setting(config.SETTINGS_KEY_VIEWPORT_HUD_SHOW_CAMERA, True)
        hud_focal = _bool_setting(config.SETTINGS_KEY_VIEWPORT_HUD_SHOW_FOCAL, True)
        hud_fps = _bool_setting(config.SETTINGS_KEY_VIEWPORT_HUD_SHOW_FPS, True)

        state = ui_mod.RenderPreviewState(
            scene_path=scene,
            output_root=output_root,
            basename=basename,
            start_frame=a,
            end_frame=b,
            fps=fps,
            width=w,
            height=h,
            ext=ext,
            activate_shot_camera=activate,
            rename_to_camera=rename_to_camera,
            loop_playback=loop,
            force_shot_overscan_1=force_over,
            viewport_hud_enabled=hud_enabled,
            viewport_hud_font_size=hud_font,
            viewport_hud_show_shot=hud_shot,
            viewport_hud_show_frame=hud_frame,
            viewport_hud_show_camera=hud_cam,
            viewport_hud_show_focal_length=hud_focal,
            viewport_hud_show_fps=hud_fps,
        )
        ui.set_scene_path_display(scene)
        ui.set_state(state)

        def save_settings() -> None:
            s = ui.state()
            settings.setValue(config.SETTINGS_KEY_OUTPUT_ROOT, s.output_root)
            settings.setValue(config.SETTINGS_KEY_BASENAME, s.basename)
            settings.setValue(config.SETTINGS_KEY_EXT, s.ext)
            settings.setValue(config.SETTINGS_KEY_START, int(s.start_frame))
            settings.setValue(config.SETTINGS_KEY_END, int(s.end_frame))
            settings.setValue(config.SETTINGS_KEY_WIDTH, int(s.width))
            settings.setValue(config.SETTINGS_KEY_HEIGHT, int(s.height))
            settings.setValue(config.SETTINGS_KEY_ACTIVATE_SHOT_CAMERA, bool(s.activate_shot_camera))
            settings.setValue(config.SETTINGS_KEY_RENAME_TO_CAMERA, bool(s.rename_to_camera))
            settings.setValue(config.SETTINGS_KEY_LOOP, bool(s.loop_playback))
            settings.setValue(config.SETTINGS_KEY_FORCE_SHOT_OVERSCAN_1, bool(s.force_shot_overscan_1))
            settings.setValue(config.SETTINGS_KEY_VIEWPORT_HUD_ENABLED, bool(s.viewport_hud_enabled))
            settings.setValue(
                config.SETTINGS_KEY_VIEWPORT_HUD_FONT_SIZE,
                (s.viewport_hud_font_size or "large").lower().strip(),
            )
            settings.setValue(config.SETTINGS_KEY_VIEWPORT_HUD_SHOW_SHOT, bool(s.viewport_hud_show_shot))
            settings.setValue(config.SETTINGS_KEY_VIEWPORT_HUD_SHOW_FRAME, bool(s.viewport_hud_show_frame))
            settings.setValue(config.SETTINGS_KEY_VIEWPORT_HUD_SHOW_CAMERA, bool(s.viewport_hud_show_camera))
            settings.setValue(config.SETTINGS_KEY_VIEWPORT_HUD_SHOW_FOCAL, bool(s.viewport_hud_show_focal_length))
            settings.setValue(config.SETTINGS_KEY_VIEWPORT_HUD_SHOW_FPS, bool(s.viewport_hud_show_fps))
            settings.sync()

        ui.set_persist_settings(save_settings)

        def refresh_from_scene(*, force_scene_output: bool = True) -> None:
            sc = maya_adapter.get_scene_path() or ""
            st = ui.state()
            astart2, aend2 = maya_adapter.get_animation_range()
            if astart2 is not None and aend2 is not None:
                start2, end2 = int(astart2), int(aend2)
            else:
                start2, end2 = maya_adapter.get_playback_range()
            fps2 = float(maya_adapter.get_scene_fps() or st.fps or 24.0)
            a2, b2 = validate_frame_range(start2, end2)
            out_scene = default_output_root_from_scene(sc) if sc else ""
            base_scene = default_basename_from_scene(sc) if sc else "untitled"
            if force_scene_output:
                out_root2 = out_scene
                base2 = base_scene
            else:
                out_root2 = st.output_root or out_scene
                base2 = st.basename or base_scene
            ui.set_scene_path_display(sc)
            ui.set_state(
                ui_mod.RenderPreviewState(
                    scene_path=sc,
                    output_root=out_root2,
                    basename=base2,
                    start_frame=a2,
                    end_frame=b2,
                    fps=fps2,
                    width=st.width,
                    height=st.height,
                    ext=st.ext,
                    activate_shot_camera=st.activate_shot_camera,
                    rename_to_camera=st.rename_to_camera,
                    loop_playback=st.loop_playback,
                    force_shot_overscan_1=st.force_shot_overscan_1,
                    viewport_hud_enabled=st.viewport_hud_enabled,
                    viewport_hud_font_size=st.viewport_hud_font_size,
                    viewport_hud_show_shot=st.viewport_hud_show_shot,
                    viewport_hud_show_frame=st.viewport_hud_show_frame,
                    viewport_hud_show_camera=st.viewport_hud_show_camera,
                    viewport_hud_show_focal_length=st.viewport_hud_show_focal_length,
                    viewport_hud_show_fps=st.viewport_hud_show_fps,
                )
            )

        def on_scene_changed() -> None:
            # Scene can change playback/animation range without user clicking Refresh.
            try:
                refresh_from_scene(force_scene_output=True)
            except Exception:
                pass

        cb_ids = maya_adapter.add_scene_changed_callbacks(on_scene_changed)
        ui.set_on_close(lambda: maya_adapter.remove_scene_changed_callbacks(cb_ids))

        def open_preview_folder() -> None:
            s = ui.state()
            root = (s.output_root or "").strip()
            if not root:
                ui.show_error("Open Preview Folder", "No output root set.")
                return
            p = Path(root)
            if not p.exists():
                ui.show_error("Open Preview Folder", f"Folder does not exist:\n{root}")
                return
            try:
                os.startfile(str(p))  # type: ignore[attr-defined]
            except Exception as e:
                ui.show_error("Open Preview Folder", f"Failed to open folder:\n{e}")

        def do_playblast() -> None:
            save_settings()
            s = ui.state()
            if not s.output_root.strip():
                ui.show_error("Playblast", "Output root is empty (set in Settings).")
                return
            req = PlayblastRequest(
                output_root=s.output_root.strip(),
                basename=s.basename.strip() or "untitled",
                start_frame=int(s.start_frame),
                end_frame=int(s.end_frame),
                width=int(s.width),
                height=int(s.height),
                ext=s.ext,
                rename_to_camera=bool(s.rename_to_camera),
                activate_shot_camera=bool(s.activate_shot_camera),
                force_shot_overscan_1=bool(s.force_shot_overscan_1),
                viewport_hud_enabled=bool(s.viewport_hud_enabled),
                viewport_hud_font_size=("small" if str(s.viewport_hud_font_size).lower().strip() == "small" else "large"),
                viewport_hud_show_shot=bool(s.viewport_hud_show_shot),
                viewport_hud_show_frame=bool(s.viewport_hud_show_frame),
                viewport_hud_show_camera=bool(s.viewport_hud_show_camera),
                viewport_hud_show_focal_length=bool(s.viewport_hud_show_focal_length),
                viewport_hud_show_fps=bool(s.viewport_hud_show_fps),
                viewport_hud_scene_fps=float(s.fps or 24.0),
            )
            ui.show_loading("Playblasting...")
            try:
                out_path = maya_adapter.render_preview_playblast(req)
                ui.hide_loading()
                ui.show_info("Playblast", f"Playblast saved:\n{out_path}")
                # refresh preview
                ui.set_state(ui.state())
            except Exception as e:
                ui.hide_loading()
                ui.show_error("Playblast", str(e))

        ui.set_callbacks(
            on_playblast=do_playblast,
            on_open_folder=open_preview_folder,
            on_refresh_from_scene=refresh_from_scene,
        )

        ui.show()
        ui.raise_()
        ui.activateWindow()
        app = QApplication.instance()
        if app:
            app.processEvents()

        print("[Render Preview] Window opened.")

    if mu is not None:
        mu.executeDeferred(_build_and_show)
        print("[Render Preview] Scheduled UI (executeDeferred).")
    else:
        _build_and_show()

