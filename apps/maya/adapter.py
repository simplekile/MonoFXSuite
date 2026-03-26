"""
Thin Maya adapter — only place that imports maya.cmds / maya.OpenMayaUI.

Tools use this module to talk to Maya. logic.py must never import maya.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

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


def collect_reference_geometry_roots() -> List[Dict[str, str]]:
    """
    For each reference namespace, look for a common geo root name under that namespace.

    Tries: Geometry, GEO, Geo, geo (first match wins per namespace).
    """
    if not is_available():
        return []
    geo_candidates = ("Geometry", "GEO", "Geo", "geo")
    out: List[Dict[str, str]] = []
    for ns in _reference_namespace_strings():
        for suffix in geo_candidates:
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
            out.append({"long_path": long_p[0], "namespace": ns})
            break
    return out


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


def export_selection_usd(
    file_path: str,
    *,
    export_uvs: bool = True,
    export_anim: bool = True,
    strip_namespaces: bool = True,
    scale: float = 1.0,
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

    sel = cmds.ls(selection=True, long=True) or []
    if not sel:
        raise RuntimeError("Nothing selected for USD export")

    dag = sel[0]
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

    opt = (
        f"exportUVSets={'1' if export_uvs else '0'};"
        f"exportMaterials=0;stripNamespaces={'1' if strip_namespaces else '0'};"
    )
    if export_anim:
        start, end = get_playback_range()
        opt += f"animation=1;startTime={start};endTime={end};"

    usd_path = file_path.replace("\\", "/")

    if scale != 1.0 and not is_camera:
        cmds.scale(scale, scale, scale, dag, absolute=True)

    try:
        cmds.file(
            usd_path,
            force=True,
            options=opt,
            type="USD Export",
            exportSelected=True,
        )
    finally:
        if scale != 1.0 and not is_camera:
            try:
                cmds.scale(1.0 / scale, 1.0 / scale, 1.0 / scale, dag, absolute=True)
            except Exception:
                pass

    if not os.path.isfile(file_path):
        raise RuntimeError(f"USD file was not created: {file_path}")


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def build_meta_dict(
    *,
    version_folder: str,
    outputs: List[Dict[str, Any]],
    export_uvs: bool,
    export_anim: bool,
    strip_namespaces: bool,
    scale: float,
    rules_path: str,
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
        },
        "rules_file": rules_path,
        "outputs": outputs,
    }
