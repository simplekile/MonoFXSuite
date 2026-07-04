"""
Thin Maya adapter — only place that imports maya.cmds / maya.OpenMayaUI.

Tools use this module to talk to Maya. logic.py must never import maya.
"""

from __future__ import annotations

import contextlib
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Optional, Tuple

try:
    import maya.cmds as cmds  # type: ignore
except ImportError:
    cmds = None  # type: ignore[assignment]


def is_available() -> bool:
    return cmds is not None


def get_main_qt_window() -> Any:
    """Maya main window for parenting PySide6 dialogs."""
    if not is_available():
        return None
    try:
        import maya.OpenMayaUI as omui  # type: ignore
        from shiboken6 import wrapInstance  # type: ignore
        from PySide6.QtWidgets import QWidget  # type: ignore

        ptr = omui.MQtUtil.mainWindow()
        if ptr:
            return wrapInstance(int(ptr), QWidget)
    except Exception:
        pass
    return None


def get_scene_path() -> Optional[str]:
    if not is_available():
        return None
    try:
        p = cmds.file(query=True, sceneName=True) or cmds.file(query=True, sn=True)
        if not p:
            return None
        p = str(p)
        if not os.path.isabs(p):
            try:
                root = cmds.workspace(query=True, rootDirectory=True)
                if root:
                    p = os.path.normpath(os.path.join(str(root), p))
                else:
                    p = os.path.normpath(os.path.abspath(p))
            except Exception:
                p = os.path.normpath(os.path.abspath(p))
        try:
            p = os.path.realpath(p)
        except OSError:
            p = os.path.normpath(p)
        return p
    except Exception:
        return None


def default_publish_root_from_scene() -> Optional[str]:
    """
    Resolve ``<task>/publish`` from the saved scene path.

    Walks up from ``dirname(scene)``. Handles common layouts:

    - ``.../<task>/maya/...`` (``work``, ``wip``, nested folders) → ``<task>/publish``.
    - ``.../<task>/maya/work/...`` → ``<task>/publish`` (``maya``'s parent is the task).
    - ``.../<task>/work/...`` (no ``maya``) → ``<task>/publish``.
    - Else → ``dirname(scene)/publish``.
    """
    path = get_scene_path()
    if not path:
        return None
    try:
        norm = os.path.normpath(os.path.realpath(path))
    except OSError:
        norm = os.path.normpath(path)

    cur = os.path.dirname(norm)
    steps = 0
    result: Optional[str] = None
    rule = "fallback"

    while cur and steps < 64:
        steps += 1
        base = os.path.basename(cur).lower()
        parent = os.path.dirname(cur)
        parent_base = os.path.basename(parent).lower() if parent else ""

        if base == "maya":
            result = os.path.normpath(os.path.join(parent, "publish"))
            rule = "under_maya"
            break

        if base == "work" and parent_base == "maya":
            gp = os.path.dirname(parent)
            result = os.path.normpath(os.path.join(gp, "publish"))
            rule = "maya_work"
            break

        if base == "work":
            result = os.path.normpath(os.path.join(parent, "publish"))
            rule = "work_only"
            break

        if parent == cur:
            break
        cur = parent

    if result is None:
        scene_dir = os.path.dirname(norm)
        result = os.path.normpath(os.path.join(scene_dir, "publish"))

    debug_log_publish_resolution(f"path={norm!s} rule={rule} -> publish={result!s}")
    return result


# Shot / sequence task folder: 01_anim, 02_anim, …
_SHOT_ANIM_TASK_RE = re.compile(r"^\d{2}_anim$", re.IGNORECASE)


def shot_anim_task_publish_from_scene() -> Optional[str]:
    """
    If the scene path contains a task folder like ``01_anim`` (``NN_anim``), return::

        <path-to-that-folder>/publish

    Example:
        ``.../02_shots/sh001/01_anim/maya/work/file.ma``
        → ``.../02_shots/sh001/01_anim/publish``
    """
    path = get_scene_path()
    if not path:
        return None
    try:
        norm = os.path.normpath(os.path.realpath(path))
    except OSError:
        norm = os.path.normpath(path)
    try:
        parts = list(Path(norm).parts)
    except Exception:
        return None
    for i, seg in enumerate(parts):
        if _SHOT_ANIM_TASK_RE.match(seg):
            out = os.path.normpath(str(Path(*parts[: i + 1]) / "publish"))
            debug_log_publish_resolution(
                f"shot_anim_task_publish path={norm!s} hit={seg!s} -> {out!s}"
            )
            return out
    return None


def publish_root_from_scene_preset(preset: str) -> Optional[str]:
    """
    Resolve publish root from current scene path for a given preset.

    Presets:
    - "anim": only if path contains task folder ``NN_anim`` (e.g. ``01_anim``) →
      ``.../NN_anim/publish``. No asset/dept fallback — rig/asset scenes without ``NN_anim``
      must use **Custom** (or save under a shot ``…/01_anim/…`` path).
    - "uv":  resolve to .../01_modelling/03_uv/publish under the current asset
    - "custom": caller-managed (returns None)
    """
    p = (preset or "anim").strip().lower()
    if p in ("", "anim"):
        return shot_anim_task_publish_from_scene()
    if p == "uv":
        return uv_publish_root_from_scene()
    return None


def uv_publish_root_from_scene() -> Optional[str]:
    """
    Resolve UV publish root for assets.

    Example target:
    .../01_assets/_characters/char_Zephys/01_modelling/03_uv/publish
    """
    path = get_scene_path()
    if not path:
        return None
    try:
        norm = os.path.normpath(os.path.realpath(path))
    except OSError:
        norm = os.path.normpath(path)
    parts = norm.replace("\\", "/").split("/")
    low = [p.lower() for p in parts]

    try:
        i_assets = low.index("01_assets")
    except ValueError:
        return None

    # Need at least: 01_assets/<group>/<asset>/...
    if i_assets + 2 >= len(parts):
        return None
    asset_root = "/".join(parts[: i_assets + 3])  # include asset folder name

    # UV publish is always under modelling — do not infer dept from scene path
    # (e.g. file under 02_rigging/... must not become .../02_rigging/03_uv/publish).
    uv_root = os.path.normpath(os.path.join(asset_root, "01_modelling", "03_uv", "publish"))
    debug_log_publish_resolution(f"uv_preset path={norm!s} -> {uv_root!s}")
    return uv_root


def debug_log_publish_resolution(msg: str) -> None:
    if os.environ.get("MONOFX_USD_PUBLISH_DEBUG", "").strip() not in ("1", "true", "yes"):
        return
    try:
        print(f"[USD Publish] {msg}")
    except Exception:
        pass


def get_playback_range() -> Tuple[int, int]:
    if not is_available():
        return (0, 0)
    try:
        a = int(cmds.playbackOptions(query=True, minTime=True))
        b = int(cmds.playbackOptions(query=True, maxTime=True))
        return (a, b)
    except Exception:
        return (0, 0)


def get_animation_range() -> Tuple[Optional[int], Optional[int]]:
    """Animation range from scene if available; else (None, None)."""
    if not is_available():
        return (None, None)
    try:
        if cmds.optionVar(exists="animationStartTime") and cmds.optionVar(exists="animationEndTime"):
            return (
                int(cmds.optionVar(query="animationStartTime")),
                int(cmds.optionVar(query="animationEndTime")),
            )
    except Exception:
        pass
    return (None, None)


def get_time_unit() -> str:
    if not is_available():
        return ""
    try:
        return str(cmds.currentUnit(query=True, time=True) or "")
    except Exception:
        return ""


# Fallback when MEL currentTimeUnitToFPS is unavailable (short names from currentUnit -q -t)
_TIME_UNIT_FPS_FALLBACK: Dict[str, float] = {
    "game": 15.0,
    "film": 24.0,
    "pal": 25.0,
    "ntsc": 30.0,
    "show": 24.0,
    "palf": 50.0,
    "ntscf": 29.97,
    "sec": 1.0,
}


def get_scene_fps() -> Optional[float]:
    """Playback FPS for the current scene time unit (e.g. 24.0 for film)."""
    if not is_available():
        return None
    try:
        import maya.mel as mel  # type: ignore

        v = mel.eval("currentTimeUnitToFPS()")
        f = float(v)
        if f > 0:
            return f
    except Exception:
        pass
    u = get_time_unit().lower().strip()
    return _TIME_UNIT_FPS_FALLBACK.get(u)


# ---------------------------------------------------------------------------
# Render Preview / Playblast helpers
# ---------------------------------------------------------------------------

# HUD names (must match temporary_render_preview_hud)
_RENDER_PREVIEW_HUD_SHOT = "MonoFX_RenderPreview_Shot"
_RENDER_PREVIEW_HUD_FRAME = "MonoFX_RenderPreview_Frame"
_RENDER_PREVIEW_HUD_CAMERA = "MonoFX_RenderPreview_Camera"
_RENDER_PREVIEW_HUD_FOCAL = "MonoFX_RenderPreview_Focal"
_RENDER_PREVIEW_HUD_FPS = "MonoFX_RenderPreview_FPS"

_RENDER_PREVIEW_HUD_ALL: Tuple[str, ...] = (
    _RENDER_PREVIEW_HUD_SHOT,
    _RENDER_PREVIEW_HUD_FRAME,
    _RENDER_PREVIEW_HUD_CAMERA,
    _RENDER_PREVIEW_HUD_FOCAL,
    _RENDER_PREVIEW_HUD_FPS,
)


def _debug_log_render_preview(msg: str) -> None:
    if os.environ.get("MONOFX_RENDER_PREVIEW_DEBUG", "").strip() not in ("1", "true", "yes"):
        return
    try:
        print(f"[Render Preview] {msg}")
    except Exception:
        pass


def _camera_shape_from_transform(camera_transform_or_shape: str) -> Optional[str]:
    """Return camera shape node given a transform or shape name."""
    if not is_available() or not camera_transform_or_shape:
        return None
    n = str(camera_transform_or_shape)
    try:
        if cmds.nodeType(n) == "camera":
            return n
    except Exception:
        pass
    try:
        shapes = cmds.listRelatives(n, shapes=True, type="camera", fullPath=True) or []
        return str(shapes[0]) if shapes else None
    except Exception:
        return None


def find_shot_camera_shape() -> Optional[str]:
    """
    Pick a camera shape whose leaf name contains 'shot' or 'sh' (compat with legacy tool).
    Returns the camera shape full path if possible.
    """
    if not is_available():
        return None
    best: Optional[str] = None
    for t in cmds.ls(type="transform", long=True) or []:
        try:
            shapes = cmds.listRelatives(t, shapes=True, type="camera", fullPath=True) or []
            if not shapes:
                continue
            leaf = str(t).split("|")[-1].split(":")[-1].lower()
            if "shot" in leaf:
                return str(shapes[0])
            if "sh" in leaf:
                best = best or str(shapes[0])
        except Exception:
            continue
    return best


def focus_panel_with_shot_camera() -> bool:
    """Focus a visible modelPanel that is using a shot camera (by leaf name match)."""
    if not is_available():
        return False
    try:
        panels = cmds.getPanel(visiblePanels=True) or []
    except Exception:
        panels = []
    for panel in panels:
        try:
            if cmds.getPanel(typeOf=panel) != "modelPanel":
                continue
            cam = cmds.modelPanel(panel, query=True, camera=True) or ""
            leaf = str(cam).split("|")[-1].split(":")[-1].lower()
            if "shot" in leaf or "sh" in leaf:
                cmds.setFocus(panel)
                return True
        except Exception:
            continue
    return False


def get_model_panel_with_shot_camera() -> Optional[str]:
    """
    Visible modelPanel already assigned a shot camera (leaf name contains ``shot`` or ``sh``).
    Does not change UI focus — avoids extra panel activation / redraw churn during playblast.
    """
    if not is_available():
        return None
    try:
        panels = cmds.getPanel(visiblePanels=True) or []
    except Exception:
        panels = []
    for panel in panels:
        try:
            if cmds.getPanel(typeOf=panel) != "modelPanel":
                continue
            cam = cmds.modelPanel(panel, query=True, camera=True) or ""
            leaf = str(cam).split("|")[-1].split(":")[-1].lower()
            if "shot" in leaf or "sh" in leaf:
                return str(panel)
        except Exception:
            continue
    return None


def resolve_render_preview_model_panel(*, prefer_shot_camera: bool) -> Optional[str]:
    """Panel name for playblast: shot camera panel if requested and found, else focused / first visible."""
    if prefer_shot_camera:
        p = get_model_panel_with_shot_camera()
        if p:
            return p
    return get_playblast_model_panel()


def get_focused_model_panel_camera() -> Optional[str]:
    """Camera (transform or shape) assigned to the currently focused modelPanel."""
    if not is_available():
        return None
    try:
        panel = cmds.getPanel(withFocus=True) or ""
        if not panel:
            return None
        if cmds.getPanel(typeOf=panel) != "modelPanel":
            return None
        cam = cmds.modelPanel(panel, query=True, camera=True) or ""
        return str(cam) if cam else None
    except Exception:
        return None


@contextlib.contextmanager
def temporary_attr(node: str, attr: str, value: Any) -> Iterator[None]:
    """
    Temporarily set a node attribute, restoring original value after.
    Safe no-op if attribute doesn't exist or isn't settable.
    """
    if not is_available() or not node or not attr:
        yield
        return
    if not cmds.objExists(node):
        yield
        return
    try:
        if not cmds.attributeQuery(attr, node=node, exists=True):
            yield
            return
    except Exception:
        yield
        return

    plug = f"{node}.{attr}"
    orig = None
    changed = False
    try:
        try:
            orig = cmds.getAttr(plug)
        except Exception:
            orig = None
        try:
            if cmds.getAttr(plug, lock=True):
                yield
                return
        except Exception:
            pass
        try:
            cmds.setAttr(plug, value)
            changed = True
            _debug_log_render_preview(f"temp set {plug}={value} (orig={orig})")
        except Exception:
            changed = False
        yield
    finally:
        if not changed:
            return
        try:
            cmds.setAttr(plug, orig)
            _debug_log_render_preview(f"restore {plug}={orig}")
        except Exception:
            pass


def get_playblast_model_panel() -> Optional[str]:
    """Model panel used for playblast: focused modelPanel, else first visible."""
    if not is_available():
        return None
    try:
        panel = cmds.getPanel(withFocus=True) or ""
        if panel and cmds.getPanel(typeOf=panel) == "modelPanel":
            return str(panel)
    except Exception:
        pass
    try:
        for p in cmds.getPanel(visiblePanels=True) or []:
            if cmds.getPanel(typeOf=p) == "modelPanel":
                return str(p)
    except Exception:
        pass
    return None


def _hud_layout_visibility_query() -> Optional[bool]:
    """Global HUD layout on/off (if False, no custom HUD draws)."""
    if not is_available():
        return None
    try:
        import maya.mel as mel  # type: ignore

        v = mel.eval("headsUpDisplay -query -layoutVisibility")
        if isinstance(v, (list, tuple)):
            v = v[0] if v else 0
        return bool(int(v))
    except Exception:
        return None


def _hud_layout_visibility_set(visible: bool) -> None:
    if not is_available():
        return
    try:
        import maya.mel as mel  # type: ignore

        mel.eval(f"headsUpDisplay -edit -layoutVisibility {1 if visible else 0};")
    except Exception:
        pass


@contextlib.contextmanager
def temporary_global_hud_layout_visible(enabled: bool) -> Iterator[None]:
    """
    Ensure global HUD layout is visible during playblast.
    See headsUpDisplay -layoutVisibility (global; when off, no HUD draws).
    """
    if not is_available() or not enabled:
        yield
        return
    prev = _hud_layout_visibility_query()
    _hud_layout_visibility_set(True)
    try:
        yield
    finally:
        if prev is not None:
            _hud_layout_visibility_set(prev)


def _list_heads_up_display_names() -> List[str]:
    if not is_available():
        return []
    try:
        raw = cmds.headsUpDisplay(listHeadsUpDisplays=True)
        if raw is None:
            return []
        if isinstance(raw, str):
            return [raw] if raw else []
        return [str(x) for x in raw]
    except Exception:
        return []


@contextlib.contextmanager
def temporary_hide_preexisting_heads_up_displays(enabled: bool) -> Iterator[None]:
    """
    Hide every headsUpDisplay that already exists before the tool adds its own.
    After the context, restore each entry's previous ``visible`` flag.

    Playblast then shows only HUDs created afterward (e.g. MonoFX_RenderPreview_*),
    not the user's poly count / camera name / other Maya HUD presets.
    """
    if not is_available() or not enabled:
        yield
        return
    names = _list_heads_up_display_names()
    prev_vis: Dict[str, bool] = {}
    for name in names:
        try:
            if not cmds.headsUpDisplay(name, exists=True):
                continue
            v = cmds.headsUpDisplay(name, query=True, visible=True)
            prev_vis[name] = bool(v) if v is not None else True
        except Exception:
            prev_vis[name] = True
    for name in prev_vis:
        try:
            cmds.headsUpDisplay(name, edit=True, visible=False)
        except Exception:
            pass
    try:
        yield
    finally:
        for name, vis in prev_vis.items():
            try:
                if cmds.headsUpDisplay(name, exists=True):
                    cmds.headsUpDisplay(name, edit=True, visible=vis)
            except Exception:
                pass


@contextlib.contextmanager
def temporary_model_editor_heads_up_display(panel: Optional[str], enabled: bool) -> Iterator[None]:
    """Force HUD drawing on a model panel; restore previous flag after."""
    if not is_available() or not panel or not enabled:
        yield
        return
    orig: Optional[bool] = None
    try:
        v = cmds.modelEditor(panel, query=True, headsUpDisplay=True)
        orig = bool(v) if v is not None else True
    except Exception:
        orig = True
    try:
        cmds.modelEditor(panel, edit=True, headsUpDisplay=True)
    except Exception:
        pass
    try:
        yield
    finally:
        if orig is not None:
            try:
                cmds.modelEditor(panel, edit=True, headsUpDisplay=orig)
            except Exception:
                pass


def _shot_token_from_scene_path(scene_path: str) -> str:
    """
    Best-effort shot token: `sh###` if found in the path, else basename without extension.
    """
    p = str(scene_path or "").replace("\\", "/")
    m = re.search(r"(^|/)(sh)(\d+)(/|$)", p, re.IGNORECASE)
    if m:
        try:
            n = int(m.group(3))
            return f"sh{n:03d}"
        except Exception:
            return f"{m.group(2).lower()}{m.group(3)}"
    base = os.path.basename(p)
    name, _ = os.path.splitext(base)
    return name or "shot"


@contextlib.contextmanager
def temporary_render_preview_hud(
    *,
    shot_token: str,
    font_size: str = "large",
    model_panel: Optional[str] = None,
    show_shot: bool = True,
    show_frame: bool = True,
    show_camera: bool = True,
    show_focal_length: bool = True,
    show_fps: bool = True,
    scene_fps: float = 24.0,
) -> Iterator[None]:
    """
    Create temporary viewport HUD rows for playblast (only enabled rows).
    Removed automatically after the context ends.

    Layout (Maya HUD grid, bottom row sections 5–9): Shot = bottom-left (5), Camera = bottom-center (7),
    Frame / Focal / FPS = bottom-right (9), stacked bottom→top as FPS, Frame, Focal so Focal sits above Frame
    and FPS below Frame.

    Per Autodesk docs, ``command`` must be paired with a trigger (e.g. ``attachToRefresh``).
    Global ``layoutVisibility`` is handled separately (see ``temporary_global_hud_layout_visible``).
    """
    if not is_available():
        yield
        return

    def _safe_remove(name: str) -> None:
        try:
            if cmds.headsUpDisplay(name, exists=True):
                cmds.headsUpDisplay(name, remove=True)
        except Exception:
            pass

    for n in _RENDER_PREVIEW_HUD_ALL:
        _safe_remove(n)

    def _cam_xform_from_panel() -> Optional[str]:
        if not model_panel:
            return None
        try:
            c = cmds.modelPanel(model_panel, query=True, camera=True) or ""
            return str(c) if c else None
        except Exception:
            return None

    def _cam_name_value() -> str:
        t = _cam_xform_from_panel()
        if not t:
            return ""
        return str(t).split("|")[-1].split(":")[-1]

    def _focal_value() -> str:
        t = _cam_xform_from_panel()
        if not t:
            return ""
        sh = _camera_shape_from_transform(t)
        if not sh:
            return ""
        try:
            v = cmds.getAttr(f"{sh}.focalLength")
            return f"{float(v):.2f} mm"
        except Exception:
            return ""

    def _fps_value() -> str:
        try:
            f = float(scene_fps)
            if f == int(f):
                return f"{int(f)} fps"
            return f"{f:g} fps"
        except Exception:
            return ""

    def _shot_value() -> str:
        return str(shot_token or "")

    def _frame_value() -> str:
        try:
            return str(int(cmds.currentTime(query=True)))
        except Exception:
            return ""

    if not (show_shot or show_camera or show_frame or show_focal_length or show_fps):
        yield
        return

    fs = "small" if str(font_size).lower().strip() == "small" else "large"
    # Bottom row: | 5 | 6 | 7 | 8 | 9 |  → left / … / center / … / right
    sec_bl = 5
    sec_bc = 7
    sec_br = 9

    def _place(
        name: str,
        label: str,
        cmd: Callable[[], str],
        *,
        section: int,
        compact: bool = False,
    ) -> None:
        try:
            block = int(cmds.headsUpDisplay(nextFreeBlock=section))
        except Exception:
            block = 0
        if section == sec_bl:
            ba = "left"
        elif section == sec_bc:
            ba = "center"
        else:
            ba = "right"
        # Stacked Focal / Frame / FPS: small row height + tight widths (large blockSize = 50px each).
        if compact:
            bsz, pad, lw, dw = "small", 4, 44, 78
        else:
            bsz, pad, lw, dw = "medium", 10, 72, 140
        cmds.headsUpDisplay(
            name,
            section=section,
            block=block,
            label=label,
            command=cmd,
            labelFontSize=fs,
            dataFontSize=fs,
            blockSize=bsz,
            padding=pad,
            labelWidth=lw,
            dataWidth=dw,
            allowOverlap=True,
            visible=True,
            attachToRefresh=True,
            blockAlignment=ba,
        )

    try:
        if show_shot:
            _place(_RENDER_PREVIEW_HUD_SHOT, "Shot", _shot_value, section=sec_bl)
        if show_camera:
            _place(_RENDER_PREVIEW_HUD_CAMERA, "Camera", _cam_name_value, section=sec_bc)
        # Bottom-right column: create bottom → top so block index grows upward (FPS under Frame, Focal above Frame).
        if show_fps:
            _place(_RENDER_PREVIEW_HUD_FPS, "FPS", _fps_value, section=sec_br, compact=True)
        if show_frame:
            _place(_RENDER_PREVIEW_HUD_FRAME, "Frame", _frame_value, section=sec_br, compact=True)
        if show_focal_length:
            _place(_RENDER_PREVIEW_HUD_FOCAL, "Focal", _focal_value, section=sec_br, compact=True)
    except Exception as e:
        _debug_log_render_preview(f"headsUpDisplay create failed: {e}")
        for n in _RENDER_PREVIEW_HUD_ALL:
            _safe_remove(n)
        yield
        return

    try:
        yield
    finally:
        for n in _RENDER_PREVIEW_HUD_ALL:
            _safe_remove(n)


def render_preview_playblast(req: Any) -> str:
    """
    Run Maya playblast for Render Preview tool.

    Expected req attributes:
    output_root, basename, start_frame, end_frame, width, height, ext,
    rename_to_camera, activate_shot_camera, force_shot_overscan_1
    """
    if not is_available():
        raise RuntimeError("Maya commands not available")

    output_root = str(getattr(req, "output_root", "") or "").strip()
    basename = str(getattr(req, "basename", "") or "").strip() or "untitled"
    # Do not use ``v or default``: frame 0 is valid and is falsy in Python.
    try:
        start_frame = int(getattr(req, "start_frame", 0))
    except (TypeError, ValueError):
        start_frame = 0
    try:
        end_frame = int(getattr(req, "end_frame", start_frame))
    except (TypeError, ValueError):
        end_frame = start_frame
    a = start_frame
    b = end_frame
    if b < a:
        a, b = b, a
    width = int(getattr(req, "width", 1920) or 1920)
    height = int(getattr(req, "height", 1080) or 1080)
    ext = str(getattr(req, "ext", "jpg") or "jpg").lower().strip()
    rename_to_camera = bool(getattr(req, "rename_to_camera", False))
    activate_shot_camera = bool(getattr(req, "activate_shot_camera", True))
    force_shot_overscan_1 = bool(getattr(req, "force_shot_overscan_1", True))
    hud_enabled = bool(getattr(req, "viewport_hud_enabled", True))
    hud_font_size = str(getattr(req, "viewport_hud_font_size", "large") or "large")
    hud_show_shot = bool(getattr(req, "viewport_hud_show_shot", True))
    hud_show_frame = bool(getattr(req, "viewport_hud_show_frame", True))
    hud_show_camera = bool(getattr(req, "viewport_hud_show_camera", True))
    hud_show_focal = bool(getattr(req, "viewport_hud_show_focal_length", True))
    hud_show_fps = bool(getattr(req, "viewport_hud_show_fps", True))
    try:
        hud_scene_fps = float(getattr(req, "viewport_hud_scene_fps", 24.0) or 24.0)
    except (TypeError, ValueError):
        hud_scene_fps = 24.0

    hud_any = hud_enabled and (
        hud_show_shot or hud_show_frame or hud_show_camera or hud_show_focal or hud_show_fps
    )

    if not output_root:
        raise RuntimeError("Output root is empty")

    epn = resolve_render_preview_model_panel(prefer_shot_camera=activate_shot_camera)

    if rename_to_camera:
        cam: Optional[str] = None
        if epn:
            try:
                c = cmds.modelPanel(epn, query=True, camera=True) or ""
                cam = str(c) if c else None
            except Exception:
                cam = None
        if not cam:
            cam = get_focused_model_panel_camera()
        if cam:
            leaf = str(cam).split("|")[-1].split(":")[-1]
            if leaf:
                basename = leaf

    out_dir = os.path.normpath(os.path.join(output_root, basename))
    os.makedirs(out_dir, exist_ok=True)
    prefix = os.path.normpath(os.path.join(out_dir, basename))

    fmt = "image" if ext in ("jpg", "png") else "movie"
    compression = ext

    # Choose shot camera overscan target (independent of focused panel).
    cam_shape = find_shot_camera_shape() if force_shot_overscan_1 else None
    ctx = temporary_attr(cam_shape, "overscan", 1.0) if cam_shape else contextlib.nullcontext()

    shot_token = _shot_token_from_scene_path(get_scene_path() or "")
    hud_ctx = (
        temporary_render_preview_hud(
            shot_token=shot_token,
            font_size=hud_font_size,
            model_panel=epn,
            show_shot=hud_show_shot,
            show_frame=hud_show_frame,
            show_camera=hud_show_camera,
            show_focal_length=hud_show_focal,
            show_fps=hud_show_fps,
            scene_fps=hud_scene_fps,
        )
        if hud_any
        else contextlib.nullcontext()
    )
    layout_ctx = temporary_global_hud_layout_visible(hud_any)
    hide_other_huds_ctx = temporary_hide_preexisting_heads_up_displays(hud_any)

    panel_hud_ctx = temporary_model_editor_heads_up_display(epn, hud_any)

    # showOrnaments=False often strips viewport overlays from playblast output (incl. HUD).
    # headsUpDisplay on the model panel must also be enabled for custom HUD to draw.
    pb_common: Dict[str, Any] = {
        "widthHeight": (width, height),
        "viewer": False,
        "showOrnaments": bool(hud_any),
        "percent": 100,
        "forceOverwrite": True,
    }
    if epn:
        pb_common["editorPanelName"] = epn

    # Order: global layout on → hide existing HUDs → create tool HUDs → panel allows HUD draw.
    with ctx, layout_ctx, hide_other_huds_ctx, hud_ctx, panel_hud_ctx:
        if fmt == "image":
            # Per-frame + completeFilename: exact output path (reliable frame 0 / numbering).
            # Do not call currentTime() before each playblast — playblast(frame=...) already
            # advances time; a prior currentTime would evaluate the frame twice (DG + capture).
            orig_time = cmds.currentTime(query=True)
            try:
                for f in range(a, b + 1):
                    out_file = os.path.normpath(os.path.join(out_dir, f"{basename}.{f:04d}.{ext}"))
                    cmds.playblast(
                        **pb_common,
                        format="image",
                        compression=compression,
                        completeFilename=out_file,
                        frame=f,
                        clearCache=(f == a),
                    )
            finally:
                try:
                    cmds.currentTime(orig_time, edit=True)
                except Exception:
                    pass
        else:
            pb_movie: Dict[str, Any] = {
                **pb_common,
                "filename": prefix,
                "format": fmt,
                "compression": compression,
                "sequenceTime": False,
                "rawFrameNumbers": True,
                "clearCache": True,
            }
            cmds.playblast(
                **pb_movie,
                startTime=a,
                endTime=b,
            )

    # Return a best-effort output path for UI message.
    if fmt == "image":
        return os.path.normpath(os.path.join(out_dir, f"{basename}.{a:04d}.{ext}"))
    # Movie output naming varies; return expected path first, else folder.
    expected = os.path.normpath(os.path.join(out_dir, f"{basename}.{ext}"))
    return expected if os.path.exists(expected) else out_dir


def get_maya_version_string() -> str:
    if not is_available():
        return ""
    try:
        return str(cmds.about(version=True) or "")
    except Exception:
        return ""


def get_maya_api_version() -> int:
    if not is_available():
        return 0
    try:
        return int(cmds.about(apiVersion=True) or 0)
    except Exception:
        return 0


def get_maya_usd_plugin_version() -> str:
    if not is_available():
        return ""
    try:
        if cmds.pluginInfo("mayaUsdPlugin", query=True, loaded=True):
            v = cmds.pluginInfo("mayaUsdPlugin", query=True, version=True)
            return str(v) if v else "loaded"
        return "not_loaded"
    except Exception:
        return ""


def ensure_maya_usd_plugin() -> bool:
    if not is_available():
        return False
    try:
        if not cmds.pluginInfo("mayaUsdPlugin", query=True, loaded=True):
            cmds.loadPlugin("mayaUsdPlugin", quiet=True)
        return bool(cmds.pluginInfo("mayaUsdPlugin", query=True, loaded=True))
    except Exception:
        return False


def collect_export_cameras(*, only_renderable: bool = False) -> List[Dict[str, str]]:
    """
    Transforms that have a camera shape, excluding default orthographic/persp by leaf name.

    If ``only_renderable`` is True, skip cameras whose shape has ``renderable`` == False
    (when that attribute exists).
    """
    if not is_available():
        return []
    default_cams = {"persp", "top", "front", "side"}
    out: List[Dict[str, str]] = []
    for t in cmds.ls(type="transform", long=True) or []:
        shapes = cmds.listRelatives(t, shapes=True, type="camera", fullPath=True) or []
        if not shapes:
            continue
        if only_renderable:
            try:
                if cmds.attributeQuery("renderable", node=shapes[0], exists=True):
                    if not bool(cmds.getAttr(shapes[0] + ".renderable")):
                        continue
            except Exception:
                pass
        short = t.split("|")[-1]
        leaf = short.split(":")[-1]
        if leaf in default_cams:
            continue
        out.append({"long_path": t, "leaf": leaf})
    return out


def _reference_namespace_strings() -> List[str]:
    """Unique reference namespaces (no trailing ':')."""
    if not is_available():
        return []
    seen: set[str] = set()
    ordered: List[str] = []

    def add_ns(raw: str) -> None:
        if not raw:
            return
        ns = raw.rstrip(":").strip()
        if not ns:
            return
        if ns not in seen:
            seen.add(ns)
            ordered.append(ns)

    for path in (
        (cmds.file(query=True, reference=True) or [])
        + (cmds.file(query=True, r=True) or [])
    ):
        try:
            add_ns(cmds.file(path, query=True, namespace=True) or "")
        except Exception:
            pass

    for ref_node in cmds.ls(type="reference", long=True) or []:
        try:
            add_ns(cmds.referenceQuery(ref_node, namespace=True) or "")
        except Exception:
            pass

    return ordered


_GEO_ROOT_LEAVES_PRIMARY = ("Geometry",)
_GEO_ROOT_LEAVES_FALLBACK = ("GEO", "Geo", "geo")
_GEO_ROOT_LEAVES_ALL = _GEO_ROOT_LEAVES_PRIMARY + _GEO_ROOT_LEAVES_FALLBACK


def _native_geo_namespace_for_root(long_path: str) -> str:
    """For non-reference geo roots, use parent transform leaf for ``name_from: namespace``."""
    segs = [s for s in (long_path or "").split("|") if s]
    if len(segs) >= 2:
        return segs[-2].split(":")[-1]
    return "scene"


def _dedupe_nested_geometry_roots(entries: List[Dict[str, str]]) -> List[Dict[str, str]]:
    """
    If both ``|Group|Geometry`` and ``|Group|Geometry|geo`` match, keep only the shallowest
    root so we do not export the same branch twice.
    """
    if len(entries) < 2:
        return entries

    def dag_depth(p: str) -> int:
        return p.count("|")

    sorted_e = sorted(entries, key=lambda d: dag_depth(d["long_path"]))
    kept: List[Dict[str, str]] = []
    for d in sorted_e:
        lp = d["long_path"]
        if any(lp.startswith(k["long_path"] + "|") for k in kept):
            continue
        kept.append(d)
    return kept


def collect_reference_geometry_roots(*, include_non_reference: bool = True) -> List[Dict[str, str]]:
    """
    For each reference namespace, look for a common geo root name under that namespace.

    Tries: Geometry, GEO, Geo, geo (first match wins per namespace).

    If ``include_non_reference`` is True (default), also adds scene-native transforms whose
    leaf name is one of those roots and ``referenceQuery(..., isNodeReferenced=True)`` is False.

    Nested matches (e.g. ``|Group|Geometry`` and ``|Group|Geometry|geo``) are reduced to the
    shallowest DAG path only.
    """
    if not is_available():
        return []
    out: List[Dict[str, str]] = []
    seen: set[str] = set()

    for ns in _reference_namespace_strings():
        found = False
        for suffix in _GEO_ROOT_LEAVES_PRIMARY:
            geo_name = f"{ns}:{suffix}"
            if not cmds.objExists(geo_name):
                continue
            try:
                if not cmds.referenceQuery(geo_name, isNodeReferenced=True):
                    continue
            except Exception:
                continue
            long_p = cmds.ls(geo_name, long=True) or []
            if not long_p:
                continue
            lp = long_p[0]
            out.append({"long_path": lp, "namespace": ns})
            seen.add(lp)
            found = True
            break
        if found:
            continue
        for suffix in _GEO_ROOT_LEAVES_FALLBACK:
            geo_name = f"{ns}:{suffix}"
            if not cmds.objExists(geo_name):
                continue
            try:
                if not cmds.referenceQuery(geo_name, isNodeReferenced=True):
                    continue
            except Exception:
                continue
            long_p = cmds.ls(geo_name, long=True) or []
            if not long_p:
                continue
            lp = long_p[0]
            out.append({"long_path": lp, "namespace": ns})
            seen.add(lp)
            break

    if include_non_reference:
        leaves = frozenset(_GEO_ROOT_LEAVES_ALL)
        for t in cmds.ls(type="transform", long=True) or []:
            try:
                leaf = t.split("|")[-1].split(":")[-1]
            except Exception:
                continue
            if leaf not in leaves:
                continue
            if t in seen:
                continue
            try:
                if cmds.referenceQuery(t, isNodeReferenced=True):
                    continue
            except Exception:
                continue
            ns = _native_geo_namespace_for_root(t)
            out.append({"long_path": t, "namespace": ns})
            seen.add(t)

    return _dedupe_nested_geometry_roots(out)


def is_dag_visible(long_path: str) -> bool:
    """
    True if the node and its transform parents have visibility on.
    This mirrors common Outliner hide expectations for export roots.
    """
    if not is_available() or not long_path:
        return True
    node = long_path
    while node:
        try:
            if cmds.attributeQuery("visibility", node=node, exists=True):
                if not bool(cmds.getAttr(node + ".visibility")):
                    return False
        except Exception:
            pass
        try:
            parents = cmds.listRelatives(node, parent=True, fullPath=True) or []
        except Exception:
            parents = []
        node = parents[0] if parents else ""
    return True


def add_scene_changed_callbacks(callback: Callable[[], None]) -> Tuple[Optional[int], Optional[int]]:
    """
    Invoke ``callback()`` after File Open and after New Scene.
    Returns (id_open, id_new) for removal; either may be None on failure.
    """
    if not is_available():
        return (None, None)
    try:
        import maya.api.OpenMaya as om2  # type: ignore

        def _wrap(*_args: Any) -> None:
            try:
                callback()
            except Exception:
                pass

        id_open = om2.MSceneMessage.addCallback(om2.MSceneMessage.kAfterOpen, _wrap)
        id_new = om2.MSceneMessage.addCallback(om2.MSceneMessage.kAfterNew, _wrap)
        return (id_open, id_new)
    except Exception:
        return (None, None)


def remove_scene_changed_callbacks(ids: Tuple[Optional[int], Optional[int]]) -> None:
    if not is_available():
        return
    try:
        import maya.api.OpenMaya as om2  # type: ignore

        for cid in ids:
            if cid is not None:
                try:
                    om2.MSceneMessage.removeCallback(cid)
                except Exception:
                    pass
    except Exception:
        pass


def collect_transforms_long() -> List[str]:
    if not is_available():
        return []
    return list(cmds.ls(type="transform", long=True) or [])


def select_single_dag(long_path: str) -> None:
    if not is_available():
        return
    cmds.select(long_path, replace=True)


def _reference_geometry_long_path(ref_node_short: str) -> str:
    """Geometry-style node inside a reference namespace."""
    if not is_available():
        return ""
    rn = str(ref_node_short or "").strip()
    if not rn:
        return ""
    ns = _reference_namespace(rn)
    if not ns:
        return ""

    for suffix in ("Geometry", "GEO", "Geo", "geo"):
        node = f"{ns}:{suffix}"
        if not cmds.objExists(node):
            continue
        long_paths = cmds.ls(node, long=True) or []
        if not long_paths:
            continue
        return str(long_paths[0])
    return ""


def _reference_root_long_path(ref_node_short: str) -> str:
    """Best outer root transform for a reference namespace."""
    if not is_available():
        return ""
    rn = str(ref_node_short or "").strip()
    if not rn:
        return ""
    ns = _reference_namespace(rn)
    if not ns:
        return ""

    geo = _reference_geometry_long_path(rn)
    if geo:
        cur = str(geo)
        while True:
            try:
                parents = cmds.listRelatives(cur, parent=True, fullPath=True) or []
            except Exception:
                parents = []
            if not parents:
                return cur
            parent = str(parents[0])
            pshort = parent.split("|")[-1]
            if not pshort.startswith(ns + ":"):
                return cur
            cur = parent

    try:
        transforms = cmds.ls(f"{ns}:*", long=True, type="transform") or []
    except Exception:
        transforms = []
    for t in transforms:
        short = str(t).split("|")[-1]
        if ":" not in short:
            continue
        try:
            parents = cmds.listRelatives(t, parent=True, fullPath=True) or []
        except Exception:
            parents = []
        if parents:
            pshort = str(parents[0]).split("|")[-1]
            if pshort.startswith(ns + ":"):
                continue
        return str(t)
    return ""


def _reference_main_long_path(ref_node_short: str) -> str:
    """Primary Main control/transform inside a reference namespace."""
    if not is_available():
        return ""
    rn = str(ref_node_short or "").strip()
    if not rn:
        return ""
    ns = _reference_namespace(rn)
    if not ns:
        return ""
    for suffix in ("Main", "main"):
        node = f"{ns}:{suffix}"
        if not cmds.objExists(node):
            continue
        long_paths = cmds.ls(node, long=True, type="transform") or cmds.ls(node, long=True) or []
        if long_paths:
            return str(long_paths[0])
    return ""


def _reference_top_main_long_path(ref_node_short: str) -> str:
    """Highest main-like ancestor starting from the exact Main node, excluding system groups."""
    if not is_available():
        return ""
    rn = str(ref_node_short or "").strip()
    if not rn:
        return ""
    ns = _reference_namespace(rn)
    if not ns:
        return ""
    cur = _reference_main_long_path(rn)
    if not cur:
        return ""
    best = str(cur)
    while True:
        try:
            parents = cmds.listRelatives(cur, parent=True, fullPath=True) or []
        except Exception:
            parents = []
        if not parents:
            break
        parent = str(parents[0])
        pshort = parent.split("|")[-1]
        if not pshort.startswith(ns + ":"):
            break
        leaf = pshort.split(":")[-1]
        low = leaf.lower()
        if "main" in low and "system" not in low:
            best = parent
        cur = parent
    return best


def _reference_custom_long_path(ref_node_short: str, token: str, exclude_token: str = "") -> str:
    """Highest transform in namespace whose leaf contains include token and not exclude token."""
    if not is_available():
        return ""
    rn = str(ref_node_short or "").strip()
    raw = str(token or "").strip()
    if not rn or not raw:
        return ""
    ns = _reference_namespace(rn)
    if not ns:
        return ""
    q = raw.lower()
    q_ex = str(exclude_token or "").strip().lower()
    try:
        transforms = cmds.ls(f"{ns}:*", long=True, type="transform") or []
    except Exception:
        transforms = []
    best = ""
    best_depth = 10**9
    for t in transforms:
        leaf = str(t).split("|")[-1].split(":")[-1]
        low = leaf.lower()
        if q not in low:
            continue
        if q_ex and q_ex in low:
            continue
        depth = str(t).count("|")
        if depth < best_depth:
            best = str(t)
            best_depth = depth
    return best


def focus_references_in_outliner(
    ref_node_shorts: List[str],
    *,
    mode: str = "root",
    custom_token: str = "",
    custom_exclude_token: str = "",
) -> bool:
    """
    Select root transforms for one or more references so Outliner follows them.
    """
    if not is_available():
        return False
    roots: List[str] = []
    seen: set[str] = set()
    for rn in ref_node_shorts:
        if mode == "geometry":
            root = _reference_geometry_long_path(rn) or _reference_root_long_path(rn)
        elif mode == "main":
            root = _reference_main_long_path(rn) or _reference_root_long_path(rn)
        elif mode == "top_main":
            root = _reference_top_main_long_path(rn) or _reference_root_long_path(rn)
        elif mode == "custom":
            root = (
                _reference_custom_long_path(rn, custom_token, custom_exclude_token)
                or _reference_root_long_path(rn)
            )
        else:
            root = _reference_root_long_path(rn)
        if root and root not in seen:
            seen.add(root)
            roots.append(root)
    if not roots:
        return False
    try:
        cmds.select(roots, replace=True)
    except Exception:
        return False
    return True


def focus_reference_in_outliner(ref_node_short: str) -> bool:
    """Backward-compatible single-reference helper."""
    return focus_references_in_outliner([ref_node_short], mode="root")


def focus_model_panel_for_hotkeys(*, prefer_shot_camera: bool = False) -> bool:
    """Return keyboard focus to a Maya model panel so viewport hotkeys work again."""
    if not is_available():
        return False
    try:
        panel = resolve_render_preview_model_panel(prefer_shot_camera=prefer_shot_camera)
        if not panel:
            return False
        cmds.setFocus(panel)
        return True
    except Exception:
        return False


def export_selection_usd(
    file_path: str,
    *,
    export_uvs: bool = True,
    export_anim: bool = True,
    strip_namespaces: bool = True,
    scale: float = 1.0,
    export_subdivide: bool = False,
    export_normals: bool = False,
    usd_options_raw: str = "",
) -> None:
    """
    Export current selection to USD via built-in USD Export.
    Raises RuntimeError on failure.
    """
    if not is_available():
        raise RuntimeError("Maya commands not available")
    if not ensure_maya_usd_plugin():
        raise RuntimeError("mayaUsdPlugin could not be loaded")

    file_path = os.path.normpath(file_path)
    parent = os.path.dirname(file_path)
    if parent and not os.path.isdir(parent):
        os.makedirs(parent, exist_ok=True)

    orig_sel = cmds.ls(selection=True, long=True) or []
    if not orig_sel:
        raise RuntimeError("Nothing selected for USD export")

    dag = orig_sel[0]
    is_camera = False
    try:
        if cmds.nodeType(dag) == "camera":
            is_camera = True
        else:
            for sh in cmds.listRelatives(dag, shapes=True, fullPath=True, noIntermediate=True) or []:
                if cmds.nodeType(sh) == "camera":
                    is_camera = True
                    break
    except Exception:
        pass

    usd_path = file_path.replace("\\", "/")

    # Use the same mechanism as Maya's File > Export Selection > USD (options string),
    # matching the UI defaults as closely as possible.
    def _encode_options(opts: Dict[str, Any]) -> str:
        parts: List[str] = []
        for k, v in opts.items():
            parts.append(f"{k}={v}")
        # Maya's command often starts with a leading ';'
        return ";" + ";".join(parts)

    raw = (usd_options_raw or "").strip()
    if raw:
        # Accept either full string starting with ';' or bare key=value list.
        opt_str = raw if raw.startswith(";") else (";" + raw)
        # If exporting a camera, ensure we don't exclude cameras in raw options.
        if is_camera:
            opt_str = opt_str.replace("excludeExportTypes=[Cameras,Lights]", "excludeExportTypes=[]")
            opt_str = opt_str.replace("excludeExportTypes=[Cameras]", "excludeExportTypes=[]")
            opt_str = opt_str.replace("excludeExportTypes=[Cameras, Lights]", "excludeExportTypes=[]")
    else:
        default_mesh_scheme = "catmullClark" if export_subdivide else "none"

        # Baseline taken from Maya 2025 UI export command (user-provided).
        opts: Dict[str, Any] = {
            "exportUVs": 1 if export_uvs else 0,
            "exportSkels": "none",
            "exportSkin": "none",
            "exportBlendShapes": 0,
            "exportDisplayColor": 0,
            # UI sometimes emits filterTypes=nurbsCurve; leave empty to avoid filtering cameras/meshes unexpectedly.
            "filterTypes": "",
            "exportColorSets": 0,
            "exportComponentTags": 0,
            "defaultMeshScheme": default_mesh_scheme,
            "animation": 1 if export_anim else 0,
            "eulerFilter": 0,
            "staticSingleSample": 0,
            "startTime": "",
            "endTime": "",
            "frameStride": 1,
            "frameSample": "",
            "defaultUSDFormat": "usdc",
            "rootPrim": "",
            "rootPrimType": "xform",
            "defaultPrim": "None",
            "exportMaterials": 0,
            "shadingMode": "useRegistry",
            "convertMaterialsTo": "[]",
            "exportAssignedMaterials": 1,
            "exportRelativeTextures": "automatic",
            "exportInstances": 1,
            "exportVisibility": 0,
            "mergeTransformAndShape": 1,
            "includeEmptyTransforms": 1,
            "stripNamespaces": 1 if strip_namespaces else 0,
            "worldspace": 0,
            "exportStagesAsRefs": 1,
            # Do not exclude cameras by default (tool exports camera targets).
            "excludeExportTypes": "[]",
            "legacyMaterialScope": 0,
        }

        opts["exportNormals"] = 1 if export_normals else 0

        if export_anim:
            start, end = get_playback_range()
            opts["startTime"] = start
            opts["endTime"] = end
            opts["staticSingleSample"] = 0
        else:
            try:
                t = int(cmds.currentTime(query=True))
            except Exception:
                t = 0
            opts["startTime"] = t
            opts["endTime"] = t
            opts["staticSingleSample"] = 1

        opt_str = _encode_options(opts)

    if scale != 1.0 and not is_camera:
        cmds.scale(scale, scale, scale, dag, absolute=True)
    try:
        # Prefer exporting the selected root to preserve hierarchy / group transforms.
        # If Maya USD exporter fails on some problematic meshes, fall back to exporting by
        # selecting mesh parent transforms (noIntermediate) under the root.
        if not is_camera:
            cmds.select(dag, replace=True)
        try:
            cmds.file(
                usd_path,
                force=True,
                options=opt_str,
                type="USD Export",
                exportSelected=True,
            )
        except Exception:
            if is_camera:
                raise
            try:
                mesh_shapes = (
                    cmds.listRelatives(
                        dag,
                        allDescendents=True,
                        type="mesh",
                        fullPath=True,
                        noIntermediate=True,
                    )
                    or []
                )
                mesh_parents: List[str] = []
                seen: set[str] = set()
                for sh in mesh_shapes:
                    try:
                        p = (cmds.listRelatives(sh, parent=True, fullPath=True) or [""])[0]
                    except Exception:
                        p = ""
                    if not p or p in seen:
                        continue
                    seen.add(p)
                    mesh_parents.append(p)
                if mesh_parents:
                    cmds.select(mesh_parents, replace=True)
                else:
                    cmds.select(dag, replace=True)
            except Exception:
                cmds.select(dag, replace=True)
            cmds.file(
                usd_path,
                force=True,
                options=opt_str,
                type="USD Export",
                exportSelected=True,
            )
    finally:
        try:
            if orig_sel:
                cmds.select(orig_sel, replace=True)
        except Exception:
            pass
        if scale != 1.0 and not is_camera:
            try:
                cmds.scale(1.0 / scale, 1.0 / scale, 1.0 / scale, dag, absolute=True)
            except Exception:
                pass

    if not os.path.isfile(file_path):
        raise RuntimeError(f"USD file was not created: {file_path}")


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def scene_is_modified() -> bool:
    if not is_available():
        return False
    try:
        return bool(cmds.file(query=True, modified=True))
    except Exception:
        return False


def open_scene_path(path: str, *, force: bool = False) -> None:
    if not is_available():
        raise RuntimeError("Maya commands not available")
    p = os.path.normpath(path)
    cmds.file(p, open=True, force=force)


def create_file_reference(path: str, namespace: str) -> None:
    if not is_available():
        raise RuntimeError("Maya commands not available")
    p = os.path.normpath(path)
    ns = (namespace or "ref").strip().replace(" ", "_")
    cmds.file(p, reference=True, namespace=ns, mergeNamespacesOnClash=True)


def _reference_namespace(ref_node_short: str) -> str:
    """Reference namespace without leading ':'."""
    if not is_available():
        return ""
    rn = str(ref_node_short or "").strip()
    if not rn:
        return ""
    try:
        ns = str(cmds.referenceQuery(rn, namespace=True) or "")
    except Exception:
        ns = ""
    ns = ns.strip()
    if ns.startswith(":"):
        ns = ns[1:]
    return ns


def _unique_namespace(base: str) -> str:
    """Return a namespace that does not exist yet."""
    if not is_available():
        return (base or "ref").strip().replace(" ", "_") or "ref"
    b = (base or "ref").strip().replace(" ", "_")
    b = re.sub(r"[^a-zA-Z0-9_]", "_", b) or "ref"
    if not cmds.namespace(exists=b):
        return b
    for i in range(1, 9999):
        cand = f"{b}_{i:02d}"
        if not cmds.namespace(exists=cand):
            return cand
    return f"{b}_{os.getpid()}"


def rename_reference_namespace(ref_node_short: str, new_namespace: str) -> str:
    """
    Rename a reference namespace and return the final namespace used.

    Maya may reject collisions, so we sanitize and ensure uniqueness first.
    """
    if not is_available():
        raise RuntimeError("Maya commands not available")
    rn = str(ref_node_short or "").strip()
    if not rn:
        raise RuntimeError("Invalid reference node")
    cur_ns = _reference_namespace(rn)
    raw = (new_namespace or "").strip().replace(" ", "_")
    new_ns = _unique_namespace(raw or cur_ns or "ref")
    try:
        cmds.file(edit=True, namespace=new_ns, referenceNode=rn)
    except Exception as e:
        raise RuntimeError(f"Could not rename reference namespace: {e}") from e
    return new_ns


def reload_reference_node(ref_node_short: str) -> None:
    """Force a reference to reload from disk (unload/load)."""
    if not is_available():
        raise RuntimeError("Maya commands not available")
    rn = str(ref_node_short or "").strip()
    if not rn:
        return
    try:
        loaded = bool(cmds.referenceQuery(rn, isLoaded=True))
    except Exception:
        loaded = True
    if loaded:
        try:
            cmds.file(unloadReference=rn)
        except Exception:
            pass
    cmds.file(loadReference=rn)


def duplicate_reference_node(ref_node_short: str, *, namespace: Optional[str] = None) -> str:
    """
    Create a new reference pointing at the same file.
    Returns the new reference node short name (best-effort; empty on failure).
    """
    if not is_available():
        raise RuntimeError("Maya commands not available")
    rn = str(ref_node_short or "").strip()
    if not rn:
        raise RuntimeError("Invalid reference node")
    _, resolved = _reference_query_paths(rn)
    if not resolved:
        raise RuntimeError("Reference has no resolved path")
    base_ns = namespace or (_reference_namespace(rn) + "_dup")
    new_ns = _unique_namespace(base_ns)
    before = set(cmds.ls(type="reference", long=False) or [])
    create_file_reference(resolved, new_ns)
    after = set(cmds.ls(type="reference", long=False) or [])
    created = list(after - before)
    for cand in created:
        try:
            if _reference_namespace(cand) == new_ns:
                return cand
        except Exception:
            continue
    return created[0] if created else ""


def _reference_edit_strings(ref_node_short: str) -> List[str]:
    if not is_available():
        return []
    rn = str(ref_node_short or "").strip()
    if not rn:
        return []
    try:
        edits = cmds.referenceQuery(rn, editStrings=True) or []
        return [str(e) for e in edits if str(e).strip()]
    except Exception:
        return []


def duplicate_reference_smart(ref_node_short: str, *, namespace: Optional[str] = None) -> str:
    """
    Duplicate a reference and attempt to preserve reference edits (anim/pose/transform/constraints...).

    Strategy:
    - Query reference edit strings from the source reference.
    - Create a new reference to the same file under a new namespace.
    - Rewrite namespace tokens inside edit strings and eval them as MEL (best-effort).
    """
    if not is_available():
        raise RuntimeError("Maya commands not available")
    src = str(ref_node_short or "").strip()
    if not src:
        raise RuntimeError("Invalid reference node")
    src_ns = _reference_namespace(src)
    edits = _reference_edit_strings(src)
    new_ref = duplicate_reference_node(src, namespace=namespace)
    if not new_ref:
        raise RuntimeError("Failed to duplicate reference")
    new_ns = _reference_namespace(new_ref)
    if not edits or not src_ns or not new_ns:
        return new_ref
    try:
        import maya.mel as mel  # type: ignore
    except Exception:
        return new_ref

    needle = src_ns + ":"
    repl = new_ns + ":"
    for cmd in edits:
        try:
            mel.eval(cmd.replace(needle, repl))
        except Exception:
            continue
    return new_ref


def _reference_node_short_name(ref_node_long: str) -> str:
    return ref_node_long.split("|")[-1]


def _is_file_reference_node(short_name: str) -> bool:
    """
    False for Maya internal / placeholder reference nodes that are not tied to a file.
    Querying those (e.g. ``_UNKNOWN_REF_NODE_``) errors: "not associated with a reference file".
    """
    if not short_name or not str(short_name).strip():
        return False
    s = str(short_name).strip()
    if s == "sharedReferenceNode":
        return False
    if s == "_UNKNOWN_REF_NODE_":
        return False
    if "UNKNOWN_REF_NODE" in s.upper():
        return False
    return True


def _expand_maya_file_path(path: str) -> str:
    """Turn Maya workspace-relative paths into absolute paths when possible."""
    if not path or not str(path).strip():
        return ""
    p = str(path).strip()
    if os.path.isabs(p):
        try:
            return os.path.normpath(os.path.realpath(p))
        except OSError:
            return os.path.normpath(p)
    try:
        exp = cmds.workspace(expandName=p)
        if exp:
            ep = str(exp).strip()
            if ep:
                try:
                    return os.path.normpath(os.path.realpath(ep))
                except OSError:
                    return os.path.normpath(ep)
    except Exception:
        pass
    try:
        return os.path.normpath(os.path.abspath(p))
    except Exception:
        return os.path.normpath(p)


def _reference_query_paths(ref_node_short: str) -> Tuple[str, str]:
    """
    Return (unresolved_path, resolved_path) for a reference node short name.

    Note: ``referenceQuery`` does **not** support ``fullPath``; passing it raises
    TypeError on Maya 2025 and leaves paths empty if swallowed.
    """
    unresolved = ""
    resolved = ""
    rn = ref_node_short
    if not _is_file_reference_node(rn):
        return ("", "")
    try:
        u = cmds.referenceQuery(rn, unresolvedFilename=True, withoutCopyNumber=True)
        unresolved = str(u).strip() if u else ""
    except Exception:
        pass
    try:
        r = cmds.referenceQuery(rn, filename=True, withoutCopyNumber=True)
        resolved = str(r).strip() if r else ""
    except Exception:
        try:
            r2 = cmds.referenceQuery(rn, filename=True)
            resolved = str(r2).strip() if r2 else ""
        except Exception:
            pass
    if unresolved:
        unresolved = _expand_maya_file_path(unresolved)
    if resolved:
        resolved = _expand_maya_file_path(resolved)
    if not resolved and unresolved:
        resolved = unresolved
    if not resolved and not unresolved:
        try:
            import maya.mel as mel  # type: ignore

            q = rn.replace("\\", "/").replace('"', '\\"')
            out = mel.eval(f'referenceQuery -filename -withoutCopyNumber "{q}"')
            if out:
                resolved = _expand_maya_file_path(str(out).strip())
        except Exception:
            pass
    return (unresolved, resolved)


def _file_path_in_project_root(resolved: str, project_root_norm: str) -> bool:
    if not resolved or not project_root_norm:
        return False
    try:
        rpp = Path(resolved).resolve()
        prp = Path(project_root_norm).resolve()
        rpp.relative_to(prp)
        return True
    except (ValueError, OSError):
        pass
    try:
        r = os.path.normcase(os.path.normpath(os.path.realpath(resolved)))
        p = os.path.normcase(os.path.normpath(os.path.realpath(project_root_norm)))
        return r == p or r.startswith(p + os.sep)
    except OSError:
        r = os.path.normcase(os.path.normpath(resolved))
        p = os.path.normcase(os.path.normpath(project_root_norm))
        return r == p or r.startswith(p + os.sep)


def collect_file_references(project_root: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    One row per ``reference`` DG node.

    Keys: ref_node_long, ref_node_short, namespace, unresolved_path, resolved_path,
    is_loaded, exists_on_disk, in_project (optional bool if project_root set).
    """
    if not is_available():
        return []
    pr_norm: Optional[str] = None
    if project_root and str(project_root).strip():
        try:
            pr_norm = os.path.normpath(os.path.realpath(str(project_root)))
        except OSError:
            pr_norm = os.path.normpath(str(project_root))

    rows: List[Dict[str, Any]] = []
    for ref_node in cmds.ls(type="reference", long=True) or []:
        try:
            short = _reference_node_short_name(ref_node)
            if not _is_file_reference_node(short):
                continue
            unresolved, resolved = _reference_query_paths(short)
            try:
                ns = str(cmds.referenceQuery(short, namespace=True) or "")
            except Exception:
                ns = ""
            if ns.startswith(":"):
                ns = ns[1:]
            try:
                loaded = bool(cmds.referenceQuery(short, isLoaded=True))
            except Exception:
                loaded = True

            exists = False
            if resolved:
                try:
                    rp = os.path.normpath(os.path.realpath(resolved))
                    exists = os.path.isfile(rp)
                except OSError:
                    exists = os.path.isfile(resolved)

            in_proj: Optional[bool] = None
            if pr_norm and resolved:
                in_proj = _file_path_in_project_root(resolved, pr_norm)

            rows.append(
                {
                    "ref_node_long": ref_node,
                    "ref_node_short": short,
                    "namespace": ns,
                    "unresolved_path": unresolved,
                    "resolved_path": resolved,
                    "is_loaded": loaded,
                    "exists_on_disk": exists,
                    "in_project": in_proj,
                }
            )
        except Exception:
            continue
    return rows


def load_reference_node(ref_node_short: str) -> None:
    if not is_available():
        raise RuntimeError("Maya commands not available")
    cmds.file(loadReference=ref_node_short)


def unload_reference_node(ref_node_short: str) -> None:
    if not is_available():
        raise RuntimeError("Maya commands not available")
    cmds.file(unloadReference=ref_node_short)


def replace_reference_path(ref_node_short: str, new_path: str) -> None:
    if not is_available():
        raise RuntimeError("Maya commands not available")
    np = os.path.normpath(new_path)
    cmds.file(np, loadReference=ref_node_short)


def remove_file_reference(ref_node_short: str, *, exists_on_disk: bool, is_loaded: bool) -> None:
    """
    Remove a file reference. When the file exists, Maya 2025 expects a loaded ref first;
    when missing, skip load and try ``removeReference`` on the unloaded node.
    """
    if not is_available():
        raise RuntimeError("Maya commands not available")
    rn = ref_node_short
    if exists_on_disk:
        if not is_loaded:
            cmds.file(loadReference=rn)
        cmds.file(removeReference=True, referenceNode=rn)
    else:
        cmds.file(removeReference=True, referenceNode=rn)


def build_meta_dict(
    *,
    version_folder: str,
    outputs: List[Dict[str, Any]],
    export_uvs: bool,
    export_anim: bool,
    strip_namespaces: bool,
    scale: float,
    export_subdivide: bool,
    export_normals: bool,
    rules_path: str,
    geometry_include_non_reference: bool = True,
) -> Dict[str, Any]:
    pmin, pmax = get_playback_range()
    amin, amax = get_animation_range()
    scene = get_scene_path() or ""
    return {
        "schema_version": 1,
        "exported_at_utc": utc_now_iso(),
        "publish_version_folder": version_folder,
        "maya_version": get_maya_version_string(),
        "maya_api_version": get_maya_api_version(),
        "maya_usd_plugin": get_maya_usd_plugin_version(),
        "scene_path": scene,
        "time_unit": get_time_unit(),
        "fps": get_scene_fps(),
        "playback_range": [pmin, pmax],
        "animation_range": [amin, amax] if amin is not None and amax is not None else None,
        "export_options": {
            "export_uvs": export_uvs,
            "export_anim": export_anim,
            "strip_namespaces": strip_namespaces,
            "scale": scale,
            "export_subdivide": export_subdivide,
            "export_normals": export_normals,
            "geometry_include_non_reference": geometry_include_non_reference,
        },
        "rules_file": rules_path,
        "outputs": outputs,
    }


def get_ordered_selection_long(*, type_name: Optional[str] = None) -> List[str]:
    if not is_available():
        return []
    kwargs: Dict[str, Any] = {"selection": True, "long": True, "orderedSelection": True}
    if type_name:
        kwargs["type"] = type_name
    try:
        return [str(x) for x in (cmds.ls(**kwargs) or [])]
    except Exception:
        return []


def get_world_translation(node: str) -> Tuple[float, float, float]:
    if not is_available() or not node:
        return (0.0, 0.0, 0.0)
    try:
        vals = cmds.xform(node, query=True, worldSpace=True, translation=True) or [0.0, 0.0, 0.0]
        return (float(vals[0]), float(vals[1]), float(vals[2]))
    except Exception:
        return (0.0, 0.0, 0.0)


def set_world_translation(node: str, xyz: Tuple[float, float, float]) -> None:
    if not is_available() or not node:
        return
    cmds.xform(node, worldSpace=True, translation=[float(xyz[0]), float(xyz[1]), float(xyz[2])])


def get_world_rotate_pivot(node: str) -> Tuple[float, float, float]:
    if not is_available() or not node:
        return (0.0, 0.0, 0.0)
    try:
        vals = cmds.xform(node, query=True, worldSpace=True, rotatePivot=True) or [0.0, 0.0, 0.0]
        return (float(vals[0]), float(vals[1]), float(vals[2]))
    except Exception:
        return get_world_translation(node)


def get_local_scale(node: str) -> Tuple[float, float, float]:
    if not is_available() or not node:
        return (1.0, 1.0, 1.0)
    try:
        vals = cmds.getAttr(f"{node}.scale")[0]
        return (float(vals[0]), float(vals[1]), float(vals[2]))
    except Exception:
        return (1.0, 1.0, 1.0)


def create_locator(name: str, *, world_position: Tuple[float, float, float]) -> str:
    if not is_available():
        raise RuntimeError("Maya commands not available")
    created = cmds.spaceLocator(name=name) or []
    locator = str(created[0]) if created else ""
    if not locator:
        raise RuntimeError("Failed to create locator")
    set_world_translation(locator, world_position)
    return locator


def set_locator_display_scale(locator: str, size: float) -> None:
    if not is_available() or not locator:
        return
    shapes = cmds.listRelatives(locator, shapes=True, fullPath=True) or []
    if not shapes:
        return
    s = max(0.001, float(size))
    for axis in ("X", "Y", "Z"):
        try:
            cmds.setAttr(f"{shapes[0]}.localScale{axis}", s)
        except Exception:
            pass


def delete_node(node: str) -> None:
    if not is_available() or not node:
        return
    try:
        if cmds.objExists(node):
            cmds.delete(node)
    except Exception:
        pass


def node_exists(node: str) -> bool:
    if not is_available() or not node:
        return False
    try:
        return bool(cmds.objExists(node))
    except Exception:
        return False


def select_nodes(nodes: List[str]) -> None:
    if not is_available():
        return
    valid = [str(n) for n in nodes if str(n).strip()]
    if not valid:
        try:
            cmds.select(clear=True)
        except Exception:
            pass
        return
    cmds.select(valid, replace=True)


def show_in_view_message(message: str, *, position: str = "topCenter", fade: bool = True) -> None:
    if not is_available():
        return
    try:
        cmds.inViewMessage(
            amg=str(message),
            pos=position,
            fade=bool(fade),
        )
    except Exception:
        try:
            print(message)
        except Exception:
            pass
