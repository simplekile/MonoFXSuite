"""HDA helpers: asset folder navigation, version/file menus, thumbnails, latest status.

Parms this module expects (names match typical HDA wiring):

- folder_path — string; menu can use :func:`menu_folder_path` (resolves walk-up to ``01_assets`` then walk-down to ``_characters``)
- Model_List — menu :func:`menu_model_list`; callback :func:`refresh`
- folderLocation — callback :func:`open_asset_folder`
- Version_List — menu :func:`menu_version_list`; callback :func:`onVersionChange`
- File_List — menu :func:`menu_file_list`
- open_file_location — callback :func:`open_file_location`
- latest_version — callback :func:`set_latest_version`
- Version_Groom_List — menu :func:`menu_version_groom_list`; callback :func:`onVersionGroomChange`
- File_Groom_List — menu :func:`menu_file_groom_list`
- open_file_groom_location — callback :func:`open_file_groom_location`
- latest_groom_version — callback :func:`set_latest_groom_version`
- Version_Lookdev_List — menu :func:`menu_version_lookdev_list`; callback :func:`onVersionLookdevChange`
- File_Lookdev_List — menu :func:`menu_file_lookdev_list`
- open_file_lookdev_location — callback :func:`open_file_lookdev_location`
- latest_lookdev_version — callback :func:`set_latest_lookdev_version`

Optional (no-op if missing): version_status, version_groom_status, version_lookdev_status, thumb_mode.
Spare: ``watch_publish``, ``watch_interval_sec`` (publish watch + :func:`cb_toggle_publish_watch`).

``ENABLE_VERSION_STATUS_UI`` — default ``False``: no updates to ``version_status`` /
``version_groom_status``, ``version_lookdev_status``, node color, or comment. Set ``True`` in this module to enable.

``CHARACTER_LOADER_CONSOLE_LOG`` — default ``True``: ``print`` resolve / menu / publish-watch
lines prefixed with ``[MonoFX character_loader]``. Set ``False`` to silence.

**Data:** Menus and callbacks read **disk directly** for the active asset (no stale JSON).
Version / file menus still invoke ``update_version_*_status``; those no-op unless
``ENABLE_VERSION_STATUS_UI`` is ``True``. Optional
:func:`scan_and_set_asset_cache` writes ``asset_cache`` userData if external tools need it.

**Realtime publish watch (optional):** :func:`start_publish_watch` uses
``hou.ui.addEventLoopCallback`` to poll the model + groom + lookdev **publish** directories
(only a cheap ``listdir`` of ``v*`` folders, default every 2s). When the set of
version folders changes, thumbnail updates (and version status UI if enabled). Call :func:`stop_publish_watch`
when turning off (e.g. spare toggle ``watch_publish``). Ineffective without a UI
(``hbatch`` / ``hython``).

**Python menu / callback scripts** on parms follow Houdini expression rules:

- **Single-line** field: only a Python **expression** (no ``=``, no ``return``). The
  value of the expression is the menu list, e.g.
  ``hou.phm().menu_folder_path()``.
- **Multi-line** editor (e.g. Ctrl+E): script is a **function body**; use
  ``return hou.phm().menu_folder_path()`` (and the same pattern for other menus).

Per parm (pick **one** style matching how you edited the script):

- ``folder_path``: ``hou.phm().menu_folder_path()`` *or* multiline ``return hou.phm().menu_folder_path()``
- ``Model_List``: ``hou.phm().menu_model_list(hou.pwd())``
- ``Version_List``: ``hou.phm().menu_version_list(hou.pwd())``
- ``File_List``: ``hou.phm().menu_file_list(hou.pwd())``
- ``Version_Groom_List``: ``hou.phm().menu_version_groom_list(hou.pwd())``
- ``File_Groom_List``: ``hou.phm().menu_file_groom_list(hou.pwd())``
- ``Version_Lookdev_List``: ``hou.phm().menu_version_lookdev_list(hou.pwd())``
- ``File_Lookdev_List``: ``hou.phm().menu_file_lookdev_list(hou.pwd())``

**Parm Python callbacks** run in an empty-ish namespace: bare ``open_asset_folder(...)``
raises ``NameError``. Use either:

- ``hou.phm().open_asset_folder(hou.pwd())`` (single-line expression), or
- ``hou.phm().cb_open_asset_folder(kwargs)`` (typical callback with ``kwargs``).

Other ``cb_*`` helpers: ``cb_open_file_location``, ``cb_open_file_groom_location``,
``cb_set_latest_version``, ``cb_set_latest_groom_version``, ``cb_set_latest_lookdev_version``, ``cb_on_version_change``,
``cb_on_version_groom_change``, ``cb_on_version_lookdev_change``, ``cb_refresh``,
``cb_open_file_lookdev_location``,
``cb_start_publish_watch``, ``cb_stop_publish_watch``, ``cb_toggle_publish_watch``.

The HDA **Python Module** must expose these (e.g.
``from apps.houdini.hda.character_loader import *``).
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import time
from collections import deque
from typing import Any

import hou

# Latest/outdated labels (version_status parms), node color, and comment.
ENABLE_VERSION_STATUS_UI = False

# Print resolve / watch messages to the Houdini Python console / shell.
CHARACTER_LOADER_CONSOLE_LOG = True


def _cl_log(msg: str) -> None:
    if CHARACTER_LOADER_CONSOLE_LOG:
        print(f"[MonoFX character_loader] {msg}", flush=True)


def _anchor_basename_matches(name: str, anchor: str) -> bool:
    if os.name == "nt":
        return name.casefold() == anchor.casefold()
    return name == anchor


def _walk_up_to_named_folder(start: str, folder_name: str) -> str | None:
    """Walk parents from ``start`` until a directory basename matches ``folder_name``."""
    path = os.path.normpath(start.strip())
    if not path:
        return None
    while path:
        if _anchor_basename_matches(os.path.basename(path), folder_name):
            return path
        parent = os.path.dirname(path)
        if parent == path:
            return None
        path = parent
    return None


def _find_descendant_dir_named(root: str, folder_name: str, max_depth: int = 8) -> str | None:
    """Breadth-first search under ``root`` for the first subdirectory named ``folder_name``."""
    if not os.path.isdir(root):
        return None
    q: deque[tuple[str, int]] = deque([(root, 0)])
    while q:
        d, depth = q.popleft()
        if depth > max_depth:
            continue
        try:
            entries = os.listdir(d)
        except OSError:
            continue
        deeper: list[str] = []
        for entry in entries:
            full = os.path.join(d, entry)
            if not os.path.isdir(full):
                continue
            if _anchor_basename_matches(entry, folder_name):
                return os.path.normpath(full)
            deeper.append(full)
        if depth < max_depth:
            for full in deeper:
                q.append((full, depth + 1))
    return None


def _folder_path_search_roots() -> list[str]:
    roots: list[str] = []
    for var in ("$HIP", "$JOB"):
        try:
            expanded = hou.expandString(var)
        except Exception:
            expanded = ""
        if expanded and expanded.strip():
            roots.append(expanded.strip())
    try:
        hip = hou.hipFile.path()
    except Exception:
        hip = ""
    if hip:
        roots.append(os.path.dirname(hip))
    seen: set[str] = set()
    out: list[str] = []
    for r in roots:
        n = os.path.normpath(r)
        if n and n not in seen:
            seen.add(n)
            out.append(n)
    return out


def find_characters_root(
    start_path: str | None = None,
    *,
    assets_folder: str = "01_assets",
    characters_folder: str = "_characters",
    max_descent_depth: int = 8,
) -> str | None:
    """From project file location: walk up to ``assets_folder``, then walk down to ``characters_folder``."""
    roots: list[str] = []
    if start_path and str(start_path).strip():
        roots.append(str(start_path).strip())
    else:
        roots = _folder_path_search_roots()
    _cl_log(
        f"find_characters_root: search_roots={roots!r} "
        f"assets_folder={assets_folder!r} characters_folder={characters_folder!r} max_depth={max_descent_depth}"
    )
    for r in roots:
        assets = _walk_up_to_named_folder(r, assets_folder)
        if not assets:
            _cl_log(f"find_characters_root: from start={r!r} -> no parent named {assets_folder!r}")
            continue
        _cl_log(f"find_characters_root: from start={r!r} -> {assets_folder}={assets!r}")
        ch = _find_descendant_dir_named(assets, characters_folder, max_descent_depth)
        if ch:
            _cl_log(f"find_characters_root: resolved -> {ch!r}")
            return ch
        _cl_log(
            f"find_characters_root: under {assets!r} no folder named {characters_folder!r} within depth {max_descent_depth}"
        )
    _cl_log("find_characters_root: FAILED (no match)")
    return None


def menu_folder_path(
    assets_folder: str = "01_assets",
    characters_folder: str = "_characters",
    max_descent_depth: int = 8,
) -> list[str]:
    folder = find_characters_root(
        None,
        assets_folder=assets_folder,
        characters_folder=characters_folder,
        max_descent_depth=max_descent_depth,
    )
    if folder:
        _cl_log(f"menu_folder_path: menu token -> {folder!r}")
        return [folder, f"{folder}  (Auto generate)"]
    _cl_log("menu_folder_path: empty menu (no folder resolved)")
    return []


def _list_char_assets(root: str) -> list[str]:
    if not os.path.isdir(root):
        return []
    return [
        f
        for f in sorted(os.listdir(root), key=str.lower)
        if os.path.isdir(os.path.join(root, f)) and f.startswith("char")
    ]


def _collect_versions_under_publish(publish_dir: str) -> dict[str, list[dict[str, Any]]]:
    versions: dict[str, list[dict[str, Any]]] = {}
    if not os.path.isdir(publish_dir):
        return versions
    for v in os.listdir(publish_dir):
        vpath = os.path.join(publish_dir, v)
        if not os.path.isdir(vpath) or not v.lower().startswith("v"):
            continue
        files: list[dict[str, Any]] = []
        for f in os.listdir(vpath):
            fpath = os.path.join(vpath, f)
            if os.path.isfile(fpath):
                name, ext = os.path.splitext(f)
                files.append({"name": name, "ext": ext, "file": f})
        versions[v] = files
    return versions


def _version_key(v: str) -> int:
    m = re.search(r"(\d+)", v)
    return int(m.group(1)) if m else -1


def _scan_asset_payload(root: str, asset: str) -> dict[str, Any]:
    asset_data: dict[str, Any] = {}
    publish_model = os.path.join(root, asset, "01_modelling", "03_uv", "publish")
    if os.path.isdir(publish_model):
        asset_data["model"] = _collect_versions_under_publish(publish_model)
    publish_groom = os.path.join(root, asset, "04_grooming", "publish")
    if os.path.isdir(publish_groom):
        asset_data["groom"] = _collect_versions_under_publish(publish_groom)
    publish_lookdev = os.path.join(root, asset, "05_lookdev", "publish")
    if os.path.isdir(publish_lookdev):
        asset_data["lookdev"] = _collect_versions_under_publish(publish_lookdev)
    return asset_data


def scan_and_set_asset_cache(node: hou.Node) -> list[str]:
    """Optional: deep-scan all ``char*`` assets and store JSON in ``asset_cache`` userData.

    Hot paths use disk reads only (:func:`menu_model_list`, :func:`menu_version_list`, …).
    Call this from a shelf/debug callback if something else must read ``asset_cache``.
    """
    root = node.evalParm("folder_path")
    assets = _list_char_assets(root)
    data: dict[str, Any] = {}
    for asset in assets:
        data[asset] = _scan_asset_payload(root, asset)
    node.setUserData("asset_cache", json.dumps(data))
    return assets


def _model_publish_dir(node: hou.Node) -> str | None:
    root = node.evalParm("folder_path")
    asset = node.evalParm("Model_List")
    if not root or not asset or not os.path.isdir(root):
        return None
    return os.path.join(root, asset, "01_modelling", "03_uv", "publish")


def _groom_publish_dir(node: hou.Node) -> str | None:
    root = node.evalParm("folder_path")
    asset = node.evalParm("Model_List")
    if not root or not asset or not os.path.isdir(root):
        return None
    return os.path.join(root, asset, "04_grooming", "publish")


def _lookdev_publish_dir(node: hou.Node) -> str | None:
    root = node.evalParm("folder_path")
    asset = node.evalParm("Model_List")
    if not root or not asset or not os.path.isdir(root):
        return None
    return os.path.join(root, asset, "05_lookdev", "publish")


def _disk_model_tree(node: hou.Node) -> dict[str, list[dict[str, Any]]]:
    """UV publish folder: version name -> file entries (disk only)."""
    pub = _model_publish_dir(node)
    if not pub:
        return {}
    return _collect_versions_under_publish(pub)


def _disk_groom_tree(node: hou.Node) -> dict[str, list[dict[str, Any]]]:
    """Groom publish folder: version name -> file entries (disk only)."""
    pub = _groom_publish_dir(node)
    if not pub:
        return {}
    return _collect_versions_under_publish(pub)


def _disk_lookdev_tree(node: hou.Node) -> dict[str, list[dict[str, Any]]]:
    """Lookdev publish folder: version name -> file entries (disk only)."""
    pub = _lookdev_publish_dir(node)
    if not pub:
        return {}
    return _collect_versions_under_publish(pub)


def _fingerprint_version_folders(publish_dir: str | None) -> tuple[str, ...]:
    """Cheap publish-dir snapshot: sorted ``v*`` subfolder names (no file crawl)."""
    if not publish_dir or not os.path.isdir(publish_dir):
        return ()
    names = [
        x
        for x in os.listdir(publish_dir)
        if os.path.isdir(os.path.join(publish_dir, x)) and x.lower().startswith("v")
    ]
    names.sort(key=_version_key)
    return tuple(names)


_watch_registry: dict[str, dict[str, Any]] = {}
_watch_loop_registered = False


def _publish_watch_tick() -> None:
    if not _watch_registry:
        return
    now = time.monotonic()
    for path in list(_watch_registry):
        node = hou.node(path)
        ent = _watch_registry.get(path)
        if not node or not ent:
            _watch_registry.pop(path, None)
            continue
        interval = float(ent["interval"])
        if now - float(ent["t_last"]) < interval:
            continue
        ent["t_last"] = now
        fp_m = _fingerprint_version_folders(_model_publish_dir(node))
        fp_g = _fingerprint_version_folders(_groom_publish_dir(node))
        fp_l = _fingerprint_version_folders(_lookdev_publish_dir(node))
        if "fp_l" not in ent:
            ent["fp_l"] = fp_l
        if ent.get("fp_m") is None:
            ent["fp_m"] = fp_m
            ent["fp_g"] = fp_g
            ent["fp_l"] = fp_l
            try:
                if ENABLE_VERSION_STATUS_UI:
                    update_version_status(node)
                    update_version_groom_status(node)
                    update_version_lookdev_status(node)
                update_network_thumbnail(node)
            except hou.OperationFailed:
                pass
            continue
        if fp_m == ent["fp_m"] and fp_g == ent["fp_g"] and fp_l == ent["fp_l"]:
            continue
        _cl_log(
            f"publish_watch {node.path()}: publish dirs changed "
            f"model_versions={fp_m!r} groom_versions={fp_g!r} lookdev_versions={fp_l!r}"
        )
        ent["fp_m"] = fp_m
        ent["fp_g"] = fp_g
        ent["fp_l"] = fp_l
        try:
            if ENABLE_VERSION_STATUS_UI:
                update_version_status(node)
                update_version_groom_status(node)
                update_version_lookdev_status(node)
            update_network_thumbnail(node)
        except hou.OperationFailed:
            pass


def _ensure_publish_watch_loop() -> None:
    global _watch_loop_registered
    if _watch_loop_registered:
        return
    ui = getattr(hou, "isUIAvailable", None)
    if ui is not None and not ui():
        return
    try:
        hou.ui.addEventLoopCallback(_publish_watch_tick)
        _watch_loop_registered = True
    except Exception:
        pass


def _maybe_remove_publish_watch_loop() -> None:
    global _watch_loop_registered
    if _watch_registry or not _watch_loop_registered:
        return
    try:
        hou.ui.removeEventLoopCallback(_publish_watch_tick)
    except Exception:
        pass
    _watch_loop_registered = False


def start_publish_watch(node: hou.Node, interval: float = 2.0) -> None:
    """Poll publish roots on the UI event loop (~every ``interval`` seconds). Updates status + thumb when version folders change."""
    _cl_log(f"start_publish_watch: {node.path()} interval={interval}s")
    _watch_registry[node.path()] = {
        "interval": max(0.25, float(interval)),
        "t_last": 0.0,
        "fp_m": None,
        "fp_g": None,
        "fp_l": None,
    }
    _ensure_publish_watch_loop()


def stop_publish_watch(node: hou.Node) -> None:
    """Unregister this node from publish polling."""
    _cl_log(f"stop_publish_watch: {node.path()}")
    _watch_registry.pop(node.path(), None)
    _maybe_remove_publish_watch_loop()


def is_publish_watch_active(node: hou.Node) -> bool:
    return node.path() in _watch_registry


def menu_model_list(node: hou.Node) -> list[str]:
    root = node.evalParm("folder_path")
    assets = _list_char_assets(root)
    menu: list[str] = []
    for asset in assets:
        menu.extend([asset, asset])
    return menu


def menu_version_list(node: hou.Node) -> list[str]:
    model = _disk_model_tree(node)
    versions = list(model.keys())
    if not versions:
        update_version_status(node)
        return ["", "No Version"]
    versions.sort(key=_version_key)
    menu: list[str] = []
    for v in versions:
        menu.extend([v, v])
    update_version_status(node)
    return menu


def menu_file_list(node: hou.Node) -> list[str]:
    model = _disk_model_tree(node)
    asset = node.evalParm("Model_List")
    version = node.evalParm("Version_List")
    if not asset or not version:
        update_version_status(node)
        return []
    files = model.get(version, [])
    if not files:
        update_version_status(node)
        return ["", "No Files"]
    menu: list[str] = []
    for f in files:
        name = f.get("name", "")
        ext = f.get("ext", "")
        file = f.get("file", "")
        label = name + ext
        menu.extend([file, label])
    update_version_status(node)
    return menu


def menu_version_groom_list(node: hou.Node) -> list[str]:
    groom = _disk_groom_tree(node)
    versions = list(groom.keys())
    if not versions:
        update_version_groom_status(node)
        return ["", "No Groom Version"]
    versions.sort(key=_version_key)
    menu: list[str] = []
    for v in versions:
        menu.extend([v, v])
    update_version_groom_status(node)
    return menu


def menu_file_groom_list(node: hou.Node) -> list[str]:
    groom = _disk_groom_tree(node)
    asset = node.evalParm("Model_List")
    version = node.evalParm("Version_Groom_List")
    if not asset or not version:
        update_version_groom_status(node)
        return []
    files = groom.get(version, [])
    if not files:
        update_version_groom_status(node)
        return ["", "No Groom Files"]
    menu: list[str] = []
    for f in files:
        name = f.get("name", "")
        ext = f.get("ext", "")
        file = f.get("file", "")
        label = name + ext
        menu.extend([file, label])
    update_version_groom_status(node)
    return menu


def menu_version_lookdev_list(node: hou.Node) -> list[str]:
    lookdev = _disk_lookdev_tree(node)
    versions = list(lookdev.keys())
    if not versions:
        update_version_lookdev_status(node)
        return ["", "No Lookdev Version"]
    versions.sort(key=_version_key)
    menu: list[str] = []
    for v in versions:
        menu.extend([v, v])
    update_version_lookdev_status(node)
    return menu


def menu_file_lookdev_list(node: hou.Node) -> list[str]:
    lookdev = _disk_lookdev_tree(node)
    asset = node.evalParm("Model_List")
    version = node.evalParm("Version_Lookdev_List")
    if not asset or not version:
        update_version_lookdev_status(node)
        return []
    files = lookdev.get(version, [])
    if not files:
        update_version_lookdev_status(node)
        return ["", "No Lookdev Files"]
    menu: list[str] = []
    for f in files:
        name = f.get("name", "")
        ext = f.get("ext", "")
        file = f.get("file", "")
        label = name + ext
        menu.extend([file, label])
    update_version_lookdev_status(node)
    return menu


def open_asset_folder(node: hou.Node) -> None:
    root_folder = node.evalParm("folder_path")
    asset = node.evalParm("Model_List")

    asset_folder = os.path.normpath(os.path.join(root_folder, asset))

    if not os.path.isdir(asset_folder):
        hou.ui.displayMessage(asset_folder)
        return

    subprocess.Popen(["explorer", asset_folder])


def open_file_location(node: hou.Node) -> None:
    root = node.evalParm("folder_path")
    asset = node.evalParm("Model_List")
    version = node.evalParm("Version_List")
    file = node.evalParm("File_List")

    path = os.path.normpath(
        os.path.join(
            root,
            asset,
            "01_modelling",
            "03_uv",
            "publish",
            version,
            file,
        )
    )

    if not os.path.exists(path):
        hou.ui.displayMessage(path)
        return

    if os.name == "nt":
        subprocess.Popen(["explorer", "/select,", path])
    else:
        subprocess.Popen(["xdg-open", os.path.dirname(path)])


def open_file_groom_location(node: hou.Node) -> None:
    root = node.evalParm("folder_path")
    asset = node.evalParm("Model_List")
    version = node.evalParm("Version_Groom_List")
    file = node.evalParm("File_Groom_List")

    path = os.path.normpath(
        os.path.join(
            root,
            asset,
            "04_grooming",
            "publish",
            version,
            file,
        )
    )

    if not os.path.exists(path):
        hou.ui.displayMessage(path)
        return

    if os.name == "nt":
        subprocess.Popen(["explorer", "/select,", path])
    else:
        subprocess.Popen(["xdg-open", os.path.dirname(path)])


def open_file_lookdev_location(node: hou.Node) -> None:
    root = node.evalParm("folder_path")
    asset = node.evalParm("Model_List")
    version = node.evalParm("Version_Lookdev_List")
    file = node.evalParm("File_Lookdev_List")

    path = os.path.normpath(
        os.path.join(
            root,
            asset,
            "05_lookdev",
            "publish",
            version,
            file,
        )
    )

    if not os.path.exists(path):
        hou.ui.displayMessage(path)
        return

    if os.name == "nt":
        subprocess.Popen(["explorer", "/select,", path])
    else:
        subprocess.Popen(["xdg-open", os.path.dirname(path)])


def set_latest_version(node: hou.Node) -> None:
    versions = list(_disk_model_tree(node).keys())

    parm = node.parm("Version_List")

    if not versions:
        if parm and parm.menuItems():
            parm.set(parm.menuItems()[0])
        return

    versions.sort(key=_version_key)

    latest = versions[-1]

    if parm:
        parm.set(latest)


def set_latest_groom_version(node: hou.Node) -> None:
    versions = list(_disk_groom_tree(node).keys())

    parm = node.parm("Version_Groom_List")

    if not versions:
        if parm and parm.menuItems():
            parm.set(parm.menuItems()[0])
        return

    versions.sort(key=_version_key)

    latest = versions[-1]

    if parm:
        parm.set(latest)


def set_latest_lookdev_version(node: hou.Node) -> None:
    versions = list(_disk_lookdev_tree(node).keys())

    parm = node.parm("Version_Lookdev_List")

    if not versions:
        if parm and parm.menuItems():
            parm.set(parm.menuItems()[0])
        return

    versions.sort(key=_version_key)

    latest = versions[-1]

    if parm:
        parm.set(latest)


def update_version_status(node: hou.Node) -> None:
    if not ENABLE_VERSION_STATUS_UI:
        return

    version = node.evalParm("Version_List")

    versions = list(_disk_model_tree(node).keys())

    parm = node.parm("version_status")

    if not versions:
        if parm:
            parm.set("No model publish versions on disk")
        return

    versions.sort(key=_version_key)
    latest = versions[-1]

    if version == latest:
        if parm:
            parm.set("✓ This is the Latest Version")

        node.setColor(hou.Color((0.3, 0.8, 0.3)))
        node.setComment("Latest")
    else:
        if parm:
            parm.set(f"Outdated -> recommend select the Latest: {latest}")

        node.setColor(hou.Color((0.9, 0.4, 0.4)))
        node.setComment(f"Outdated → Latest {latest}")

    node.setGenericFlag(hou.nodeFlag.DisplayComment, True)


def update_version_groom_status(node: hou.Node) -> None:
    if not ENABLE_VERSION_STATUS_UI:
        return

    version = node.evalParm("Version_Groom_List")

    versions = list(_disk_groom_tree(node).keys())

    parm = node.parm("version_groom_status")

    if not versions:
        if parm:
            parm.set("No groom publish versions on disk")
        return

    versions.sort(key=_version_key)
    latest = versions[-1]

    if version == latest:
        if parm:
            parm.set("✓ This is the Latest Version")

        node.setColor(hou.Color((0.3, 0.8, 0.3)))
        node.setComment("Latest")
    else:
        if parm:
            parm.set(f"Outdated -> recommend select the Latest: {latest}")

        node.setColor(hou.Color((0.9, 0.4, 0.4)))
        node.setComment(f"Outdated → Latest {latest}")

    node.setGenericFlag(hou.nodeFlag.DisplayComment, True)


def update_version_lookdev_status(node: hou.Node) -> None:
    if not ENABLE_VERSION_STATUS_UI:
        return

    version = node.evalParm("Version_Lookdev_List")

    versions = list(_disk_lookdev_tree(node).keys())

    parm = node.parm("version_lookdev_status")

    if not versions:
        if parm:
            parm.set("No lookdev publish versions on disk")
        return

    versions.sort(key=_version_key)
    latest = versions[-1]

    if version == latest:
        if parm:
            parm.set("✓ This is the Latest Version")

        node.setColor(hou.Color((0.3, 0.8, 0.3)))
        node.setComment("Latest")
    else:
        if parm:
            parm.set(f"Outdated -> recommend select the Latest: {latest}")

        node.setColor(hou.Color((0.9, 0.4, 0.4)))
        node.setComment(f"Outdated → Latest {latest}")

    node.setGenericFlag(hou.nodeFlag.DisplayComment, True)


def _get_network_editors(node: hou.Node) -> list:
    panes = []

    for pane in hou.ui.paneTabs():
        if pane.type() == hou.paneTabType.NetworkEditor:
            if pane.pwd() == node.parent():
                panes.append(pane)

    return panes


def _build_thumb_path(node: hou.Node) -> str | None:
    root = node.evalParm("folder_path")
    asset = node.evalParm("Model_List")

    parm = node.parm("thumb_mode")
    mode = parm.eval() if parm else 0

    meta_folder = os.path.join(root, asset, ".meta")

    thumb = None

    if mode == 0:
        thumb = os.path.join(meta_folder, "thumb_uv.user.png")
    elif mode == 1:
        thumb = os.path.join(meta_folder, "thumb_lookdev.user.png")

    if not thumb or not os.path.exists(thumb):
        fallback = os.path.join(root, asset, "thumbnail.user.png")
        thumb = fallback if os.path.exists(fallback) else None

    return os.path.normpath(thumb) if thumb else None


def update_network_thumbnail(node: hou.Node) -> None:
    thumb = _build_thumb_path(node)

    panes = _get_network_editors(node)
    if not panes:
        return

    for pane in panes:
        images = list(pane.backgroundImages())

        filtered = []

        for img in images:
            try:
                if img.relativeToPath() == node.path():
                    continue
            except Exception:
                pass

            filtered.append(img)

        if thumb and os.path.exists(thumb):
            bg = hou.NetworkImage()
            bg.setPath(thumb)

            bg.setRelativeToPath(node.path())

            bg.setRect(
                hou.BoundingRect(
                    -1,
                    0.25,
                    1.5,
                    3,
                )
            )

            bg.setBrightness(0.9)

            filtered.append(bg)

        pane.setBackgroundImages(filtered)


def update_file_list(node: hou.Node) -> None:
    parm = node.parm("File_List")

    if not parm:
        return

    menu = parm.menuItems()

    if not menu:
        parm.set("")
        return

    current = parm.eval()

    if current not in menu:
        parm.set(menu[0])


def update_file_groom_list(node: hou.Node) -> None:
    parm = node.parm("File_Groom_List")

    if not parm:
        return

    menu = parm.menuItems()

    if not menu:
        parm.set("")
        return

    current = parm.eval()

    if current not in menu:
        parm.set(menu[0])


def update_file_lookdev_list(node: hou.Node) -> None:
    parm = node.parm("File_Lookdev_List")

    if not parm:
        return

    menu = parm.menuItems()

    if not menu:
        parm.set("")
        return

    current = parm.eval()

    if current not in menu:
        parm.set(menu[0])


def onVersionChange(node: hou.Node) -> None:
    update_file_list(node)
    update_version_status(node)


def onVersionGroomChange(node: hou.Node) -> None:
    update_file_groom_list(node)
    update_version_groom_status(node)


def onVersionLookdevChange(node: hou.Node) -> None:
    update_file_lookdev_list(node)
    update_version_lookdev_status(node)


def refresh(node: hou.Node) -> None:
    set_latest_version(node)
    set_latest_groom_version(node)
    set_latest_lookdev_version(node)

    update_file_list(node)
    update_file_groom_list(node)
    update_file_lookdev_list(node)

    update_version_status(node)
    update_version_groom_status(node)
    update_version_lookdev_status(node)

    update_network_thumbnail(node)


# Parm Python callbacks: run in a namespace without this module's globals — always
# call through hou.phm(), e.g. hou.phm().cb_open_asset_folder(kwargs)


def cb_open_asset_folder(kwargs: dict) -> None:
    open_asset_folder(kwargs["node"])


def cb_open_file_location(kwargs: dict) -> None:
    open_file_location(kwargs["node"])


def cb_open_file_groom_location(kwargs: dict) -> None:
    open_file_groom_location(kwargs["node"])


def cb_open_file_lookdev_location(kwargs: dict) -> None:
    open_file_lookdev_location(kwargs["node"])


def cb_set_latest_version(kwargs: dict) -> None:
    set_latest_version(kwargs["node"])


def cb_set_latest_groom_version(kwargs: dict) -> None:
    set_latest_groom_version(kwargs["node"])


def cb_set_latest_lookdev_version(kwargs: dict) -> None:
    set_latest_lookdev_version(kwargs["node"])


def cb_on_version_change(kwargs: dict) -> None:
    onVersionChange(kwargs["node"])


def cb_on_version_groom_change(kwargs: dict) -> None:
    onVersionGroomChange(kwargs["node"])


def cb_on_version_lookdev_change(kwargs: dict) -> None:
    onVersionLookdevChange(kwargs["node"])


def cb_refresh(kwargs: dict) -> None:
    refresh(kwargs["node"])


def cb_start_publish_watch(kwargs: dict) -> None:
    node = kwargs["node"]
    interval = 2.0
    pi = node.parm("watch_interval_sec")
    if pi is not None:
        try:
            interval = float(pi.eval())
        except (TypeError, ValueError):
            pass
    start_publish_watch(node, interval=interval)


def cb_stop_publish_watch(kwargs: dict) -> None:
    stop_publish_watch(kwargs["node"])


def cb_toggle_publish_watch(kwargs: dict) -> None:
    node = kwargs["node"]
    p = node.parm("watch_publish")
    if p is not None and int(p.eval()) != 0:
        cb_start_publish_watch(kwargs)
    else:
        cb_stop_publish_watch(kwargs)
