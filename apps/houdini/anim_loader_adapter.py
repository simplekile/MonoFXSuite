"""Mono Anim Loader 2.2, Houdini side: reads and writes loader nodes. Decisions live in tools/fx/anim_loader/logic.py.

The HDA's PythonModule is ``from apps.houdini.anim_loader_adapter import *``. Spec: docs/plans/anim_loader_v2_2.md.
"""

from __future__ import annotations

import dataclasses
import json
import re
import time
from pathlib import Path
from typing import Any

try:
    import hou  # type: ignore
except ImportError:  # outside Houdini
    hou = None  # type: ignore[assignment]

from tools.fx.anim_loader import config, logic
from tools.fx.anim_loader.logic import LoaderState, Output, Resolved

__all__ = [
    "read_state", "write_state", "refresh", "create_loader", "cb_parm_changed", "cb_refresh", "cb_reload",
    "cb_open_manager", "cb_open_folder", "cb_apply_timeline", "apply_timeline", "menu_versions", "menu_anim_versions",
    "menu_anim_files", "menu_assets", "menu_shots", "menu_model_versions", "menu_model_files", "menu_asset_groups", "on_created", "find_loaders", "load_shot", "update", "set_asset",
    "upgrade", "LoadResult", "on_loaded", "check_heavy_shot",
]

_F_RE = re.compile(r"\$F(\d*)")


# --- state <-> parms -------------------------------------------------------------------------

def _s(node, name: str) -> str:
    p = node.parm(name)
    return p.evalAsString().strip() if p is not None else ""


def use_prim(node) -> bool:
    """Prim Name on (graft under /<Prim Name>); a node without the parm (older HDA) grafts."""
    p = node.parm(config.P_USE_PRIM) if node is not None else None
    return True if p is None else bool(p.eval())


def set_use_prim(node, on: bool) -> None:
    p = node.parm(config.P_USE_PRIM)
    if p is not None:
        p.set(1 if on else 0)


def instance_root(node) -> str | None:
    """Where the instance sits: "/<Prim Name>", "" with Prim Name off (the publish's own root prims), None when
    there is nothing to work on (on, and no name)."""
    inst = _s(node, config.P_INSTANCE)
    if not use_prim(node):
        return ""
    return "/" + inst if inst else None


def instance_paths(node) -> list[str]:
    """The instance's top prims: /<Prim Name>, or with Prim Name off the branch's own root prims (input 0's prims
    pass through the loader and are not its own)."""
    root = instance_root(node)
    if root is None:
        return []
    if root:
        return [root]
    topo = node.node("groom_topology")
    try:
        stage = topo.stage() if topo is not None else None
    except hou.OperationFailed:
        stage = None
    if stage is None:
        return []
    return ["/" + c.GetName() for c in stage.GetPseudoRoot().GetChildren() if c.GetName() != "HoudiniLayerInfo"]


def _set(node, name: str, value) -> None:
    p = node.parm(name)
    if p is not None and p.eval() != value:
        p.set(value)


def _version(node, name: str) -> str:
    """A version parm's value when it is a version (``v003``); "" for 2.1's "select version" and the like."""
    value = _s(node, name)
    return value if re.match(r"^v\d+$", value, re.IGNORECASE) else ""


def read_state(node) -> LoaderState:
    """The node's parms as a LoaderState (no disk access)."""
    enabled = {part: bool(node.evalParm(config.P_ENABLE[part])) for part in logic.PARTS}
    versions = {part: _version(node, config.P_VERSION[part]) for part in logic.PARTS}
    kind = "cam" if node.evalParm(config.P_GEO_CAM) == 1 else "geo"
    source = config.SOURCE_ASSET if _s(node, config.P_SOURCE) == config.SOURCE_ASSET else config.SOURCE_SHOT
    return LoaderState(_s(node, config.P_ROOT), _s(node, config.P_SHOT), _version(node, config.P_ANIM_VERSION),
                       _s(node, config.P_ANIM_FILE), _s(node, config.P_ASSET) or None,
                       _s(node, config.P_INSTANCE), kind, enabled, versions, source,
                       _version(node, config.P_MODEL_VERSION), _s(node, config.P_MODEL_FILE))


def write_state(node, state: LoaderState) -> None:
    """Writes a state into the node's parms (callbacks do not fire on set)."""
    _set(node, config.P_ROOT, state.project_root)
    _set(node, config.P_SHOT, state.shot)
    _set(node, config.P_ANIM_VERSION, state.anim_version)
    _set(node, config.P_ANIM_FILE, state.anim_file)
    _set(node, config.P_ASSET, state.asset or "")
    _set(node, config.P_INSTANCE, state.instance_name)
    _set(node, config.P_GEO_CAM, 1 if state.kind == "cam" else 0)
    for part in logic.PARTS:
        _set(node, config.P_ENABLE[part], int(state.enabled.get(part, True)))
        _set(node, config.P_VERSION[part], state.versions.get(part, ""))
    _set(node, config.P_SOURCE, state.source)
    _set(node, config.P_MODEL_VERSION, state.model_version)
    _set(node, config.P_MODEL_FILE, state.model_file)


# --- groom / cloth layout ----------------------------------------------------------------------

def _frame_file(pattern: str, frame: int) -> str:
    return _F_RE.sub(lambda m: str(frame).zfill(int(m.group(1) or 1)), pattern)


def _template(pattern: str) -> str:
    return _F_RE.sub(lambda m: "#" * int(m.group(1) or 1), pattern)


def fx_layout(first_file: str) -> tuple[str, list[str]]:
    """(mode, root prims) of a groom / cloth sequence from its first file: value clips need time samples."""
    from pxr import Sdf

    layer = Sdf.Layer.FindOrOpen(first_file)
    if layer is None:
        return "", []
    roots = [p.path.pathString for p in layer.rootPrims if p.name != "HoudiniLayerInfo"]
    sampled = bool(layer.ListAllTimeSamples())
    return (config.FX_MODE_CLIP if sampled else config.FX_MODE_SUBLAYER), roots


_CURVE_TYPES = ("BasisCurves", "NurbsCurves", "HermiteCurves")


def groom_curves(first_file: str) -> list[str]:
    """Curves prims of a groom cache file (their paths in the file), read from its specs."""
    from pxr import Sdf

    layer = Sdf.Layer.FindOrOpen(first_file)
    out: list[str] = []
    if layer is None:
        return out

    def walk(spec):
        for child in spec.nameChildren:
            if child.typeName in _CURVE_TYPES:
                out.append(child.path.pathString)
            else:
                walk(child)
    walk(layer.pseudoRoot)
    return out


def refresh(node) -> Resolved:
    """Resolves the node's state and writes the paths, layers, clips and status it shows. Never changes a version."""
    state = read_state(node)
    r = logic.resolve(state)
    # Props and environments publish a complete asset as their lookdev (meshes and materials, defined there); the UV
    # publish is another mesh (Low / zHigh). Such a lookdev is the asset: the UV publish is not loaded (both would
    # double the geometry). Helen's lookdev only overrides: the UV model stays under it.
    complete = logic.is_asset(state) and bool(r.lookdev) and lookdev_defines_geometry(r.lookdev)
    if complete:
        r = dataclasses.replace(r, anim=r.lookdev, notes=tuple(n for n in r.notes if not n.startswith("Model file")))
    _set(node, config.P_ANIM_PATH, r.anim)
    _set(node, config.P_MODEL_PATH, r.anim if logic.is_asset(state) else "")
    if logic.is_asset(state) and state.asset:
        group = logic.asset_group_of(state.project_root, state.asset)
        if group:
            _set(node, config.P_ASSET_GROUP, group)
    for part in logic.PARTS:
        _set(node, config.P_PATH[part], getattr(r, part))
    notes = list(r.notes)
    layers = [] if complete else [r.lookdev]  # complete: r.anim is the lookdev, added last
    topo = ""
    asset_source = logic.is_asset(state)
    for task in logic.FX_TASKS:
        keys = config.P_FX[task]
        pattern = getattr(r, task)
        mode, roots, first, last, template = "", [], 0, 0, ""
        if pattern and asset_source:
            layers.append(pattern)  # the asset's groom publish: one file, already at /Groom
        elif pattern:
            first, last = r.frames[task]
            mode, roots = fx_layout(_frame_file(pattern, first))
            template = _template(pattern)
            if task == "groom":
                # groom sits outside Geo, at /Groom/<name> (the user's pick): the branch copies its topology there
                # from the first frame (or from each frame without time samples); the clips read from the cache's
                # own paths (clip primPath)
                curves = groom_curves(_frame_file(pattern, first))
                roots = [f"{src}={dst}" for src, dst in logic.groom_targets(curves)] if curves else roots
                topo = pattern if mode == config.FX_MODE_SUBLAYER else _frame_file(pattern, first)
                if mode == config.FX_MODE_SUBLAYER:
                    notes.append(f"{task}: no motion blur (no time samples)")
            elif mode == config.FX_MODE_SUBLAYER:
                layers.append(pattern)
                notes.append(f"{task}: no motion blur (no time samples)")
        _set(node, keys["mode"], mode)
        _set(node, keys["template"], template)
        _set(node, keys["first"], first)
        _set(node, keys["last"], last)
        _set(node, keys["roots"], " ".join(roots))
    _set(node, config.P_GROOM_TOPO, topo)
    layers.append(r.anim)
    layers = [x for x in layers if x] + [""] * len(config.P_LAYERS)
    for name, value in zip(config.P_LAYERS, layers):
        _set(node, name, value)
    step, short = logic.next_step(state)
    if complete and "model" in short:  # the lookdev is the asset: no model file to pick
        step, short = "", ""
    if step:  # the source is not set yet: say the next thing to do, not every part missing
        _set(node, config.P_STATUS, step)
        _show_comment(node, short)
    else:
        st = logic.status(state)
        versions = {"anim": logic.main_version(state), **state.versions}
        if asset_source:  # the main file is the model: say so
            st = {("model" if k == "anim" else k): v for k, v in st.items()}
            versions["model"] = versions.pop("anim")
            if complete:  # the lookdev is the asset: the UV publish is not loaded, its state does not matter
                st.pop("model", None)
                notes.insert(0, "Model: the lookdev publish (it holds the geometry)")
        _set(node, config.P_STATUS, " · ".join(logic.status_problems(st, versions) + notes))
        _show_comment(node, logic.status_comment(st))
    _MENUS.clear()  # the menus read the disk again
    return r


_COMPLETE_CACHE: dict[tuple[str, float], bool] = {}


def lookdev_defines_geometry(path: str) -> bool:
    """True when a lookdev publish defines meshes itself (a prop's or environment's complete asset), not only
    overrides on the UV model (Helen). Read from its layers' specs, cached by modification time."""
    import os

    from pxr import Sdf

    if not path or not os.path.isfile(path):
        return False
    key = (path, os.path.getmtime(path))
    if key in _COMPLETE_CACHE:
        return _COMPLETE_CACHE[key]
    found = False
    seen: set[str] = set()

    def layer_has_mesh(layer) -> bool:
        if layer is None or layer.identifier in seen:
            return False
        seen.add(layer.identifier)
        hit = []

        def visit(p):
            if hit:
                return
            spec = layer.GetPrimAtPath(p) if p.IsPrimPath() else None
            if spec is not None and spec.specifier == Sdf.SpecifierDef and spec.typeName == "Mesh":
                hit.append(p)
        layer.Traverse(Sdf.Path.absoluteRootPath, visit)
        if hit:
            return True
        return any(layer_has_mesh(Sdf.Layer.FindOrOpen(layer.ComputeAbsolutePath(sub))) for sub in layer.subLayerPaths)

    try:
        found = layer_has_mesh(Sdf.Layer.FindOrOpen(path))
    except Exception:
        found = False
    _COMPLETE_CACHE[key] = found
    return found


def _show_comment(node, text: str) -> None:
    """The status in the network editor: the node's comment, shown under it."""
    try:
        if node.comment() != text:
            node.setComment(text)
        node.setGenericFlag(hou.nodeFlag.DisplayComment, True)
    except (AttributeError, hou.OperationFailed):
        pass


# --- creating ------------------------------------------------------------------------------------

def _unique_name(parent, base: str) -> str:
    base = re.sub(r"[^0-9A-Za-z_]+", "_", base).strip("_") or "anim_loader"
    name, i = base, 2
    while parent.node(name) is not None:
        name, i = f"{base}_{i}", i + 1
    return name


def create_loader(parent, root: str, shot: str, anim_version: str, output: Output):
    """A new loader for one anim output, versions picked once (newest). The caller owns the undo group."""
    from apps.houdini.solaris_adapter import _place_new

    state = logic.initial_state(Path(root), shot, anim_version, output)
    node = parent.createNode(config.HDA_TYPE, _unique_name(parent, state.instance_name))
    set_use_prim(node, True)  # a shot's instances each under /<instance> (on_created turned it off in an asset scene)
    write_state(node, state)
    node.setUserData(config.USER_DATA, json.dumps({"shot": shot, "anim_file": output.file}))
    refresh(node)
    _place_new(node)
    return node


def on_created(node) -> None:
    """A node put down by hand: project and shot from $HIP; the artist picks the anim file."""
    try:
        hip = Path(hou.hipFile.path())
    except Exception:
        return
    root = logic.find_project_root(hip)
    asset = logic.detect_asset(root, hip) if root is not None else None
    if asset and not _s(node, config.P_ROOT):  # a scene in an asset folder (grooming, lookdev): the asset's model
        write_state(node, logic.initial_asset_state(root, asset))
        set_use_prim(node, False)  # the asset as published (/Geo...); load_shot / Upgrade set it on again
    elif root is not None and not _s(node, config.P_ROOT):
        _set(node, config.P_ROOT, root.as_posix())
        shot = logic.detect_shot(hip)
        if shot:
            _set(node, config.P_SHOT, shot)
            versions = logic.list_versions(logic.anim_publish_dir(root, shot))
            if versions:
                _set(node, config.P_ANIM_VERSION, versions[-1])
    refresh(node)  # the status says the next step: pick an anim file, another shot, or a project


# --- callbacks and menus -------------------------------------------------------------------------

def cb_parm_changed(kwargs: dict) -> None:
    node = kwargs["node"]
    name = kwargs.get("parm_name") or (kwargs["parm"].name() if kwargs.get("parm") is not None else "")
    if name == config.P_ANIM_FILE:
        _new_anim_file(node)
    elif name in (config.P_SHOT, config.P_ROOT):
        _new_shot(node)
    elif name == config.P_SOURCE:
        _new_source(node)
    elif name in (config.P_MODEL_VERSION, config.P_MODEL_FILE):
        state = read_state(node)
        if name == config.P_MODEL_VERSION:  # keep the picked file if the version has it, else the standard one
            asset_dir = logic.list_asset_dirs(Path(state.project_root)).get(state.asset or "")
            files = logic.usd_files(logic.model_publish_dir(asset_dir) / state.model_version) if asset_dir else []
            write_state(node, dataclasses.replace(state, model_file=logic.pick_file(files, state.asset or "", "uv",
                                                                                     state.model_file)))
    elif name == config.P_ASSET:  # the artist named the asset: its parts start at their newest, as in the manager
        state = read_state(node)
        if logic.is_asset(state) and state.asset and state.project_root:
            write_state(node, logic.initial_asset_state(Path(state.project_root), state.asset,
                                                        dataclasses.replace(state, asset=None)))
        else:
            write_state(node, logic.with_latest(state, logic.PARTS))
    refresh(node)


def _new_source(node) -> None:
    """Source changed. Nothing of the other source is cleared, so switching back restores it; Asset with no model
    yet picks the asset's newest parts once (the asset from the shot's instance, else from $HIP)."""
    state = read_state(node)
    if not logic.is_asset(state):
        if state.anim_file:  # back to the shot: the anim file's instance name again (/char_X_inst02 for a clone)
            write_state(node, dataclasses.replace(state, instance_name=logic.instance_name(state.anim_file)))
        return
    root = Path(state.project_root) if state.project_root else logic.find_project_root(Path(hou.hipFile.path()))
    if root is None:
        return
    asset = state.asset or logic.detect_asset(root, Path(hou.hipFile.path()))
    if asset and not state.model_version:
        write_state(node, logic.initial_asset_state(root, asset, state))
    elif asset:
        write_state(node, dataclasses.replace(state, project_root=str(root), asset=asset, instance_name=asset,
                                              kind="geo"))


def _new_anim_file(node) -> None:
    """The artist picked another anim file: the instance and the newest versions of its parts, once."""
    state = read_state(node)
    root = Path(state.project_root)
    out = next((o for o in logic.read_outputs(logic.anim_publish_dir(root, state.shot) / state.anim_version)
                if o.file == state.anim_file), None)
    if out is None:
        return
    write_state(node, logic.initial_state(root, state.shot, state.anim_version, out))
    node.setUserData(config.USER_DATA, json.dumps({"shot": state.shot, "anim_file": out.file}))


def _new_shot(node) -> None:
    """The artist changed the shot (or the project): the same instance moves there as Retarget does, else the
    shot's newest anim version and no anim file yet. A version or file of the old shot is never kept."""
    state = read_state(node)
    old_shot, old_file = _key(node)
    if state.project_root and old_shot == state.shot and state.anim_version in logic.list_versions(
            logic.anim_publish_dir(Path(state.project_root), state.shot)):
        return  # the shot it was on, with a version it has (e.g. the project root typed again)
    before = dataclasses.replace(state, shot="", anim_file=old_file or state.anim_file)  # "": moved from elsewhere
    new = logic.switch_shot(before, state.shot)
    write_state(node, new)
    if new.anim_file:
        node.setUserData(config.USER_DATA, json.dumps({"shot": new.shot, "anim_file": new.anim_file}))
    else:
        try:
            node.destroyUserData(config.USER_DATA)
        except hou.OperationFailed:
            pass


def cb_refresh(kwargs: dict) -> None:
    refresh(kwargs["node"])


def cb_open_manager(kwargs: dict) -> None:
    try:
        from tools.fx.anim_loader import ui
    except ImportError:
        _set(kwargs["node"], config.P_STATUS, "The manager window is not installed yet.")
        return
    ui.open_manager(kwargs["node"].parent().path())  # Load shot builds next to the node it was opened from


def apply_timeline(node) -> str:
    """fps and frame range from publish_meta.json, else from the anim file's stage metadata."""
    state = read_state(node)
    tl = logic.read_timeline(logic.anim_publish_dir(Path(state.project_root), state.shot) / state.anim_version)
    if tl is None and _s(node, config.P_ANIM_PATH):
        from pxr import Sdf

        layer = Sdf.Layer.FindOrOpen(_s(node, config.P_ANIM_PATH))
        if layer is not None and layer.HasStartTimeCode() and layer.HasEndTimeCode():
            tl = (layer.framesPerSecond or layer.timeCodesPerSecond, int(layer.startTimeCode), int(layer.endTimeCode))
    if tl is None:
        return "No timeline in the publish."
    fps, first, last = tl
    hou.setFps(fps)
    hou.playbar.setFrameRange(first, last)
    hou.playbar.setPlaybackRange(first, last)
    return f"Timeline {first}-{last} at {fps:g} fps."


def cb_apply_timeline(kwargs: dict) -> None:
    _set(kwargs["node"], config.P_STATUS, apply_timeline(kwargs["node"]))


def _menu(items: list[str]) -> list[str]:
    out: list[str] = []
    for i in items:
        out += [i, i]
    return out


# A Normal menu shows its item's label in the field, so Houdini runs the menu script whenever the parm pane draws.
# The disk scan behind it is kept a few seconds per node and dropped by refresh (any source parm change).
_MENUS: dict[tuple, tuple[float, list[str]]] = {}
MENU_CACHE_S = 5.0


def _cached(key: tuple, make) -> list[str]:
    now = time.monotonic()
    hit = _MENUS.get(key)
    if hit is not None and now - hit[0] < MENU_CACHE_S:
        return hit[1]
    value = make()
    _MENUS[key] = (now, value)
    return value


def _labelled(choices: list[tuple[str, str]]) -> list[str]:
    out: list[str] = []
    for token, label in choices:
        out += [token, label]
    return out


def menu_anim_versions(node) -> list[str]:
    state = read_state(node)
    return _cached((node.sessionId(), "anim", repr(state)), lambda: _labelled(logic.version_choices(state, "anim")))


def menu_anim_files(node) -> list[str]:
    root, shot, v = _s(node, config.P_ROOT), _s(node, config.P_SHOT), _s(node, config.P_ANIM_VERSION)
    if not (root and shot and v):
        return []
    return _cached((node.sessionId(), "files", root, shot, v), lambda: _menu(
        [o.file for o in logic.read_outputs(logic.anim_publish_dir(Path(root), shot) / v)]))


def menu_versions(node, part: str) -> list[str]:
    state = read_state(node)
    return _cached((node.sessionId(), part, repr(state)), lambda: _labelled(logic.version_choices(state, part)))


def menu_shots(node) -> list[str]:
    root, shot = _s(node, config.P_ROOT), _s(node, config.P_SHOT)
    return _cached(("shots", root, shot), lambda: _labelled(logic.shot_menu(root, shot)))


def menu_model_versions(node) -> list[str]:
    state = read_state(node)
    return _cached((node.sessionId(), "model", repr(state)), lambda: _labelled(logic.version_choices(state, "anim")))


def menu_model_files(node) -> list[str]:
    state = read_state(node)
    return _cached((node.sessionId(), "model_files", repr(state)), lambda: _labelled(logic.model_file_choices(state)))


def menu_assets(node) -> list[str]:
    """Source Asset: the assets of the picked group that have a UV publish; Source Shot: every asset."""
    root, cur = _s(node, config.P_ROOT), _s(node, config.P_ASSET)
    if not root:
        return []
    asset_src = _s(node, config.P_SOURCE) == config.SOURCE_ASSET
    group = _s(node, config.P_ASSET_GROUP) if asset_src else ""
    return _cached(("assets", root, group, cur, asset_src),
                   lambda: _labelled(logic.asset_menu(root, group, cur, asset_src)))


def menu_asset_groups(node) -> list[str]:
    root = _s(node, config.P_ROOT)
    if not root:
        return []
    return _cached(("groups", root), lambda: _labelled([("", "All")] + [(g, logic.group_label(g))
                                                                       for g in logic.asset_groups(Path(root))]))


def _is_loader(node: Any) -> bool:
    name = node.type().name()
    return name in (config.HDA_TYPE, *config.LEGACY_TYPES) or name.startswith(config.CHARACTER_LOADER_PREFIX)


def _is_character_loader(node: Any) -> bool:
    return node.type().name().startswith(config.CHARACTER_LOADER_PREFIX)


# --- commands of the manager window (each one undo step) ------------------------------------------

from dataclasses import dataclass, field  # noqa: E402


@dataclass
class LoadResult:
    created: list[str] = field(default_factory=list)
    kept: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def _loader_types() -> list:
    names = (config.HDA_TYPE, *config.LEGACY_TYPES)
    out = [t for t in (hou.nodeType(hou.lopNodeTypeCategory(), n) for n in names) if t is not None]
    out += [t for name, t in hou.lopNodeTypeCategory().nodeTypes().items()
            if name.startswith(config.CHARACTER_LOADER_PREFIX)]
    return out


def find_loaders(root=None) -> list:
    """Every loader in the scene (MonoFX Loader, Anim Loader 2.2 / 2.1, Character Loader 3.2), in every LOP
    network: /stage and LOP networks inside /obj (the grooming scenes keep theirs in /obj/Character_Loader).
    ``root``: only those under that node."""
    prefix = (root.path().rstrip("/") + "/") if root is not None else "/"
    nodes = [n for t in _loader_types() for n in t.instances() if n.path().startswith(prefix)]
    return sorted(nodes, key=lambda n: n.path())


def _key(node) -> tuple[str, str]:
    """(shot, anim file) a loader stands for; ("", "") for Source Asset, which Load shot and Retarget leave alone."""
    if _s(node, config.P_SOURCE) == config.SOURCE_ASSET:
        return "", ""
    try:
        data = json.loads(node.userData(config.USER_DATA) or "{}")
    except ValueError:
        data = {}
    return data.get("shot", ""), data.get("anim_file", "")


# The shot layout of the lighting scenes (skill solaris-shot-stage-layout): merge_actors -> actors, merge_cameras ->
# cameras, merge_environments -> environments, then graft_anim / graft_world. A network that has these merges gets
# its new loaders wired into them; any other network gets <shot>_merge / assets_merge as before.
LAYOUT_MERGES = {"actors": "merge_actors", "cameras": "merge_cameras", "environments": "merge_environments"}


def layout_merge(parent, area: str):
    """The shot layout's merge for ``area`` (actors / cameras / environments) in this network, else None."""
    node = parent.node(LAYOUT_MERGES[area])
    return node if node is not None and node.type().name() == "merge" else None


def _shot_merge(parent, shot: str):
    for n in parent.children():
        if n.userData(config.MERGE_USER_DATA) == shot:
            return n
    from apps.houdini.solaris_adapter import _place_new

    merge = parent.createNode("merge", _unique_name(parent, f"{shot}_merge"))
    merge.setUserData(config.MERGE_USER_DATA, shot)
    _place_new(merge)
    return merge


def load_shot(parent, root: str, shot: str, anim_version: str) -> LoadResult:
    """A loader for every output of an anim version that has none yet (found by user data, not by name)."""
    from apps.houdini.solaris_adapter import manual_update, undo_group

    result = LoadResult()
    have = {_key(n): n for n in find_loaders()}  # any version: Update moves versions, never a second loader
    outputs = logic.read_outputs(logic.anim_publish_dir(Path(root), shot) / anim_version)
    if not outputs:
        result.notes.append(f"No anim outputs in {shot} {anim_version}.")
        return result
    with undo_group(f"Load shot {shot} {anim_version}"), manual_update():
        merge = None
        for out in outputs:
            existing = have.get((shot, out.file))
            if existing is not None:
                result.kept.append(existing.name())
                continue
            node = create_loader(parent, root, shot, anim_version, out)
            target = layout_merge(parent, "cameras" if out.kind == "cam" else "actors")
            if target is None:
                merge = merge or _shot_merge(parent, shot)
                target = merge
            target.setNextInput(node)
            result.created.append(node.name())
    if result.created:
        check_heavy_shot()
    return result


def update(nodes: list, parts: tuple[str, ...] = ("anim", "lookdev", "groom", "cloth")) -> list[str]:
    """Moves the named parts of each 2.2 loader to their newest version; one undo step. Lines say what moved."""
    from apps.houdini.solaris_adapter import undo_group

    lines = []
    with undo_group("Update anim loaders"):
        for node in nodes:
            if node.type().name() != config.HDA_TYPE:
                continue
            old = read_state(node)
            new = logic.with_latest(old, parts)
            word = "model" if logic.is_asset(old) else "anim"
            a, b = logic.main_version(old), logic.main_version(new)
            moved = [f"{word} {a} -> {b}"] if a != b else []
            moved += [f"{p} {old.versions[p] or '-'} -> {new.versions[p]}" for p in logic.PARTS
                      if new.versions[p] != old.versions[p]]
            if moved:
                write_state(node, new)
                refresh(node)
                lines.append(f"{node.name()}: " + ", ".join(moved))
    return lines


def set_part_version(nodes: list, part: str, version: str) -> tuple[list[str], list[str]]:
    """Sets ``part`` ("anim": the anim, or the model on Source Asset; "lookdev", "groom", "cloth") to ``version`` on
    each MonoFX Loader, as the node's own version menu does (its parm callback runs: a model version keeps the
    picked file when it has it); one undo step. A loader without that version on disk is left as it is.
    Returns (what moved, what was left and why)."""
    from apps.houdini.solaris_adapter import undo_group

    moved, left = [], []
    with undo_group(f"Set {part} {version}"):
        for node in nodes:
            if node.type().name() != config.HDA_TYPE:
                left.append(f"{node.name()}: Upgrade first")
                continue
            state = read_state(node)
            asset = logic.is_asset(state)
            name = (config.P_MODEL_VERSION if asset else config.P_ANIM_VERSION) if part == "anim" \
                else config.P_VERSION[part]
            if _s(node, name) == version:
                continue
            if version not in {p.version for p in logic.version_picks(state, part, limit=10_000)}:
                left.append(f"{node.name()}: no {part} {version}")
                continue
            old = _s(node, name)
            _set(node, name, version)
            cb_parm_changed({"node": node, "parm_name": name})
            word = ("model" if asset else "anim") if part == "anim" else part
            moved.append(f"{node.name()}: {word} {old or '-'} -> {version}")
    return moved, left


def retarget(nodes: list, shot: str) -> tuple[list[str], list[str]]:
    """Loaders copied from another shot, moved to ``shot`` (``logic.retarget_state``); one undo step.
    (what moved, what was left and why). Never a second loader for an instance the shot already has. A shot merge
    whose loaders all moved is taken over by the new shot; a camera node named after its shot is renamed."""
    from apps.houdini.solaris_adapter import manual_update, undo_group

    moved, left = [], []
    nodes = [n for n in nodes if n.type().name() == config.HDA_TYPE]
    paths = {n.path() for n in nodes}
    have = {_key(n): n for n in find_loaders() if n.path() not in paths}
    old_shots = set()
    with undo_group(f"Retarget anim loaders to {shot}"), manual_update():
        for node in nodes:
            old = read_state(node)
            new, why = logic.retarget_state(old, shot)
            if new is None:
                left.append(why)
                continue
            if new == old:
                continue
            other = have.get((shot, new.anim_file))
            if other is not None:
                left.append(f"{old.instance_name}: {shot} already has it ({other.name()})")
                continue
            write_state(node, new)
            node.setUserData(config.USER_DATA, json.dumps({"shot": shot, "anim_file": new.anim_file}))
            have[(shot, new.anim_file)] = node
            if old.kind == "cam" and node.name() == old.instance_name:
                node.setName(_unique_name(node.parent(), new.instance_name))
            refresh(node)
            old_shots.add(old.shot)
            moved.append(f"{node.name()}: {old.shot} {old.anim_version} -> {shot} {new.anim_version}")
        parent = nodes[0].parent() if nodes else None
        if parent is not None and not any(n.userData(config.MERGE_USER_DATA) == shot for n in parent.children()):
            for merge in parent.children():
                tag = merge.userData(config.MERGE_USER_DATA)
                ins = [i for i in merge.inputs() if i is not None]
                if tag in old_shots and ins and all(_key(i)[0] == shot for i in ins if _is_loader(i)):
                    merge.setUserData(config.MERGE_USER_DATA, shot)
                    if merge.name().startswith(f"{tag}_merge"):
                        merge.setName(_unique_name(parent, f"{shot}_merge"))
                    break
    return moved, left


def set_asset(node, asset: str) -> None:
    """The artist names the asset of an "asset?" row; its parts start at their newest version."""
    from dataclasses import replace

    from apps.houdini.solaris_adapter import undo_group

    with undo_group(f"Set asset {asset}"):
        state = replace(read_state(node), asset=asset or None)
        write_state(node, logic.with_latest(state, logic.PARTS))
        refresh(node)


def upgrade(nodes: list) -> list:
    """2.1 loaders -> 2.2, keeping parms of the same name; the anim file becomes a name, the instance is read."""
    from apps.houdini.solaris_adapter import undo_group

    done = []
    with undo_group("Upgrade to MonoFX Loaders"):
        for node in nodes:
            if _is_baked(node):  # a baked loader: the MonoFX Loader again
                done.append(restore_baked(node))
                continue
            if _is_character_loader(node):
                new = _upgrade_character_loader(node)
                if new is not None:
                    done.append(new)
                continue
            if node.type().name() == config.OLD_TYPE:  # Anim Loader 2.2: same parms, the type is renamed
                new = node.changeNodeType(config.HDA_TYPE, keep_parms=True, keep_network_contents=False)
                refresh(new)
                done.append(new)
                continue
            if node.type().name() not in config.LEGACY_TYPES:
                continue
            anim = _s(node, config.P_ANIM_FILE) or _s(node, config.P_ANIM_PATH)
            new = node.changeNodeType(config.HDA_TYPE, keep_parms=True, keep_network_contents=False)
            anim_path = Path(anim)
            state = read_state(new)
            version = state.anim_version or anim_path.parent.name
            root = state.project_root
            out = next((o for o in logic.read_outputs(logic.anim_publish_dir(Path(root), state.shot) / version)
                        if o.file == anim_path.name), Output(anim_path.name, "cam" if
                                                             anim_path.name.lower().startswith("cam_") else "geo"))
            inst = logic.resolve_instance(out, set(logic.list_asset_dirs(Path(root))))
            from dataclasses import replace

            state = replace(state, anim_version=version, anim_file=out.file, asset=inst.asset,
                            instance_name=inst.name, kind=inst.kind)
            empty = tuple(p for p in logic.PARTS if not state.versions.get(p))
            write_state(new, logic.with_latest(state, empty) if empty else state)
            new.setUserData(config.USER_DATA, json.dumps({"shot": state.shot, "anim_file": out.file}))
            refresh(new)
            done.append(new)
    return done


def _upgrade_character_loader(node):
    """A Character Loader 3.2 -> a 2.2 node with Source Asset in its place: same name, position, wires and flags
    (its type has other parms, so changeNodeType cannot keep them). The prims move from /Geo to /<asset>/Geo."""
    values = {p.name(): p.evalAsString() for p in node.parms()}
    state, extra, why = logic.from_character_loader(values)
    if state is None:
        _set_status_bar(f"{node.name()}: not upgraded ({why})")
        return None
    parent, name, pos = node.parent(), node.name(), node.position()
    ins = [(c.inputIndex(), c.inputNode(), c.outputIndex()) for c in node.inputConnections()]
    outs = [(c.outputNode(), c.inputIndex()) for c in node.outputConnections()]
    display = node.isDisplayFlagSet()
    node.setName(_unique_name(parent, name + "_3_2"))
    new = parent.createNode(config.HDA_TYPE, name)
    set_use_prim(new, True)  # its prims move under /<asset> (the docstring); nodes after it were made for that
    new.setPosition(pos)
    for index, src, out_index in ins:
        new.setInput(index, src, out_index)
    for dst, index in outs:
        dst.setInput(index, new)
    write_state(new, state)
    for parm, value in extra.items():
        _set(new, parm, value)
    refresh(new)
    if display:
        new.setDisplayFlag(True)
    node.destroy()
    return new


def _set_status_bar(text: str) -> None:
    try:
        hou.ui.setStatusMessage(text, hou.severityType.Warning)
    except (AttributeError, hou.OperationFailed):
        pass


# --- manager layout A (the user's pick, 2026-11-17): add assets, view, links, what is new, hand off ----------

ASSETS_MERGE = "assets"  # MERGE_USER_DATA of the Merge LOP the Add drawer wires its loaders into


def add_assets(parent, root: str, names: list[str]) -> LoadResult:
    """A MonoFX Loader on Source Asset per asset (newest versions, once), wired into the shot layout's merges, else
    this network's ``assets_merge`` (made on first use, never wired further). An asset already in this network gets
    another instance, prim ``<asset>_inst02``... (set dressing places one asset several times). One undo step."""
    from apps.houdini.solaris_adapter import manual_update, undo_group

    result = LoadResult()
    taken = {_s(n, config.P_INSTANCE) for n in parent.children() if n.type().name() == config.HDA_TYPE}
    start, where = _add_anchor(parent)  # read before anything is made: the artist's selection and view
    had = {n.path() for n in parent.children()}
    made = []
    with undo_group(f"Add {len(names)} asset{'s' if len(names) != 1 else ''}"), manual_update():
        merge = None
        for name in names:
            prim, i = name, 1
            while prim in taken:  # another instance of an asset already placed here
                i += 1
                prim = f"{name}_inst{i:02d}"
            state = dataclasses.replace(logic.initial_asset_state(Path(root), name), instance_name=prim)
            node = parent.createNode(config.HDA_TYPE, _unique_name(parent, prim))
            # Source Asset: Prim Name off (the user's ask, 2026-11-20); a second instance of the asset here needs
            # its own /<asset>_inst02, or both would sit at /Geo
            set_use_prim(node, i > 1)
            write_state(node, state)
            refresh(node)
            if start is None:
                _place_new_node(node)
            made.append(node)
            # the shot layout: characters with the actors, everything else in the environments
            group = logic.asset_group_of(root, name)
            target = layout_merge(parent, "actors" if group == "_characters" else "environments")
            if target is None:
                merge = merge or _shot_merge(parent, ASSETS_MERGE)
                target = merge
            target.setNextInput(node)
            taken.add(prim)
            result.created.append(node.name())
        if start is not None and made:
            new_merge = merge if merge is not None and merge.path() not in had else None
            _place_column(parent, made + ([new_merge] if new_merge is not None else []), start)
        for k, node in enumerate(made):  # the new loaders selected: the artist sees what Add made
            node.setSelected(True, clear_all_selected=(k == 0))
    if made and where:
        result.notes.append(where)
    return result


def _network_editor(parent):
    """The Network Editor showing ``parent`` (the one under the cursor first is not knowable from a window: the
    current one, else any)."""
    try:
        tabs = [t for t in hou.ui.paneTabs() if t.type() == hou.paneTabType.NetworkEditor and t.pwd() == parent]
    except Exception:  # hython: no UI
        return None
    current = [t for t in tabs if t.isCurrentTab()]
    return (current or tabs or [None])[0]


def _add_anchor(parent) -> tuple[tuple[float, float] | None, str]:
    """Where Add puts its nodes (the user's pick, 2026-11-20): beside the selected node of this network, else in
    the middle of the Network Editor's view of it, else (no UI) Houdini's own free spot. (start, words for the
    result line)."""
    sel = [n for n in hou.selectedNodes() if n.parent() == parent]
    if sel:
        a = sel[-1]
        return (a.position()[0] + a.size()[0] + 1.5, a.position()[1]), f"beside {a.name()}"
    editor = _network_editor(parent)
    if editor is not None:
        try:
            c = editor.visibleBounds().center()
            return (c[0] - 0.5, c[1]), "in the middle of the view"
        except Exception:
            pass
    return None, ""


def _place_column(parent, nodes: list, start: tuple[float, float]) -> None:
    """``nodes`` one under the other from ``start``, the column moved right past any node already there."""
    mine = {n.path() for n in nodes}
    taken = [tuple(n.position()) for n in parent.children() if n.path() not in mine]
    for node, (x, y) in zip(nodes, logic.free_spots(start, len(nodes), taken)):
        node.setPosition(hou.Vector2(x, y))


def _place_new_node(node) -> None:
    try:
        from apps.houdini.solaris_adapter import _place_new

        _place_new(node)
    except Exception:  # placement is cosmetic
        pass


def _networks_of(nodes: list) -> list:
    out = []
    for n in nodes:
        if n.parent() not in out:
            out.append(n.parent())
    return out


def solo(paths: list[str]) -> int:
    """Solo the instances of these loaders in the viewport of their LOP networks (Houdini's Solo Geometry, view
    state: not saved, not undoable); an empty list clears the solo. Returns the prims soloed."""
    nodes = [hou.node(p) for p in paths if hou.node(p)]
    nets = _networks_of(nodes) or _networks_of(find_loaders())
    count = 0
    for net in nets:
        display = net.displayNode() if hasattr(net, "displayNode") else None
        if display is None:
            continue
        mine = [n for n in nodes if n.parent() == net]
        prims = [p for n in mine for p in instance_paths(n)]
        rule = hou.LopSelectionRule()
        rule.setPathPattern(" ".join(prims))  # empty: no solo
        with net.viewportOverrides(display) as overrides:  # Houdini edits overrides only inside a with block
            overrides.setSoloGeometry(rule)
        count += len(prims)
    return count


def set_viewport_part(part: str, on: bool) -> int:
    """Show in Viewport for lookdev or groom on every MonoFX Loader (a node parm: one undo step)."""
    from apps.houdini.solaris_adapter import undo_group

    bit = config.VIEWPORT_BITS[part]
    n = 0
    with undo_group(f"{part.title()} in viewport {'on' if on else 'off'}"):
        for node in find_loaders():
            if node.type().name() not in (config.HDA_TYPE, config.OLD_TYPE):
                continue
            value = int(node.evalParm(config.P_VIEWPORT))
            new = (value | bit) if on else (value & ~bit)
            if new != value:
                node.parm(config.P_VIEWPORT).set(new)
                n += 1
    return n


def viewport_part_on(part: str) -> bool:
    bit = config.VIEWPORT_BITS[part]
    nodes = [n for n in find_loaders() if n.type().name() in (config.HDA_TYPE, config.OLD_TYPE)]
    return all(int(n.evalParm(config.P_VIEWPORT)) & bit for n in nodes)  # no loader: nothing is hidden


def frame(path: str) -> bool:
    """Selects the loader's instance prim in a Scene Viewer showing its network and frames it (F)."""
    node = hou.node(path)
    inst = _s(node, config.P_INSTANCE) if node else ""
    if not inst:
        return False
    for pane in scene_viewers():
        try:
            if pane.pwd() != node.parent():
                pane.setPwd(node.parent())
            pane.setCurrentSceneGraphSelection([f"/{inst}"])
            pane.curViewport().frameSelected()
            return True
        except (AttributeError, hou.OperationFailed):
            continue
    return False


def publish_folder(path: str) -> str:
    """The folder of the loader's anim (or model) file, else its asset or shot folder; a layer row's version folder."""
    if LAYER_SEP in path:
        _node, _i, ref = _layer(path)
        return (ref.publish_dir() / ref.version).as_posix() if ref is not None else ""
    node = hou.node(path)
    if node is None:
        return ""
    state = read_state(node)
    main = _s(node, config.P_ANIM_PATH)
    if main:
        return str(Path(main).parent)
    root = Path(state.project_root) if state.project_root else None
    if root is None:
        return ""
    folder = logic.list_asset_dirs(root).get(state.asset or "")
    return str(folder) if folder else str(root / "02_shots" / state.shot)


def part_folders(path: str) -> dict[str, tuple[str, str]]:
    """{part: (word, folder)} of a loader, in column order (``logic.part_folders``); a layer row has its version
    folder as "anim"."""
    if LAYER_SEP in path:
        folder = publish_folder(path)
        return {"anim": ("Publish", folder)} if folder else {}
    node = hou.node(path)
    state = read_state(node) if node is not None else None
    if state is None:
        return {}
    return {part: (logic.part_word(state, part), folder) for part, folder in logic.part_folders(state).items()}


def open_part_folder(path: str, part: str) -> bool:
    found = part_folders(path).get(part)
    return open_external(found[1]) if found else False


def monos_link_for(path: str) -> str:
    node = hou.node(path)
    if node is None:
        return ""
    state = read_state(node)
    if not state.project_root:
        return ""
    root = Path(state.project_root)
    folder = logic.list_asset_dirs(root).get(state.asset or "")
    if logic.is_asset(state) or (folder is not None and not state.shot):
        return logic.monos_link(root, folder) if folder else ""
    return logic.monos_link(root, root / "02_shots" / state.shot, "shots") if state.shot else ""


def open_external(target: str) -> bool:
    """A folder in Explorer or a monos:// link in Monos."""
    import os

    if not target:
        return False
    try:
        os.startfile(target)  # type: ignore[attr-defined]  # Windows: the registered handler
        return True
    except OSError:
        return False


def set_source(paths: list[str], source: str) -> int:
    """Source Shot / Asset on these loaders (each keeps the other side's parms); one undo step."""
    from apps.houdini.solaris_adapter import undo_group

    n = 0
    with undo_group(f"Source {source}"):
        for p in paths:
            node = hou.node(p)
            if node is None or node.type().name() != config.HDA_TYPE or _s(node, config.P_SOURCE) == source:
                continue
            node.parm(config.P_SOURCE).set(source)
            cb_parm_changed({"node": node, "parm": node.parm(config.P_SOURCE), "parm_name": config.P_SOURCE})
            n += 1
    return n


_WEIGHT_CACHE: dict[tuple[str, float], int] = {}


def texture_bytes(lookdev_path: str) -> int:
    """Bytes of every file a lookdev publish pulls (textures, UDIM tiles included), cached by modification time
    (no hou: the manager's worker thread)."""
    import glob
    import os

    from pxr import Sdf, UsdUtils

    if not lookdev_path or not os.path.isfile(lookdev_path):
        return 0
    key = (lookdev_path, os.path.getmtime(lookdev_path))
    if key in _WEIGHT_CACHE:
        return _WEIGHT_CACHE[key]
    try:
        layers, assets, unresolved = UsdUtils.ComputeAllDependencies(Sdf.AssetPath(lookdev_path))
    except Exception:
        return 0
    files = {a for a in assets}
    for u in unresolved:  # <UDIM> patterns come back unresolved: their tiles
        if "<UDIM>" in u:
            files.update(glob.glob(u.replace("<UDIM>", "[0-9][0-9][0-9][0-9]")))
    total = 0
    for f in files:
        try:
            total += os.path.getsize(f)
        except OSError:
            pass
    _WEIGHT_CACHE.clear() if len(_WEIGHT_CACHE) > 256 else None
    _WEIGHT_CACHE[key] = total
    return total


def mesh_paths(path: str) -> list[str]:
    """The meshes of a publish file (cached with subdivision's reading of it)."""
    return subd_opinions(path)[0] if path else []


def handoff(paths: list[str], out_dir: str) -> list[str]:
    """Packages each loader's instance for someone without MonoFX: ``<out_dir>/<instance>_handoff/<instance>.usd``
    (the loader's stage as it is now, flattened: graft, subdivision, hidden prims, groom outside Geo, clips baked
    to time samples) plus a copy of every file it points at (textures, UDIM tiles) under ``textures/``, paths made
    relative. Lines say what was written."""
    import glob
    import os
    import shutil

    from pxr import Sdf, UsdUtils

    lines = []
    for p in paths:
        node = hou.node(p)
        inst = _s(node, config.P_INSTANCE) if node else ""
        if not inst:
            continue
        folder = Path(out_dir) / logic.handoff_name(inst)
        tex = folder / "textures"
        tex.mkdir(parents=True, exist_ok=True)
        flat = node.stage().Flatten()
        layer = Sdf.Layer.CreateNew(str(folder / f"{inst}.usd"))
        # Prim Name off: the instance's top prims at their own paths (/Geo, /_materials), not wrapped (a wrap would
        # leave bindings to /_materials pointing outside); the default prim is Geo when there is one
        tops = [t for t in instance_paths(node) if flat.GetPrimAtPath(t)]
        if not tops:
            lines.append(f"{inst}: nothing at {instance_root(node) or '/'}")
            continue
        for top in tops:
            Sdf.CopySpec(flat, top, layer, top)
        names = [t.strip("/") for t in tops]
        layer.defaultPrim = inst if inst in names else ("Geo" if "Geo" in names else names[0])
        for key in ("framesPerSecond", "timeCodesPerSecond", "startTimeCode", "endTimeCode", "metersPerUnit",
                    "upAxis"):
            if flat.pseudoRoot.GetInfo(key) is not None and flat.pseudoRoot.HasInfo(key):
                layer.pseudoRoot.SetInfo(key, flat.pseudoRoot.GetInfo(key))
        copied: dict[str, str] = {}
        size = 0

        def move(asset: str) -> str:
            nonlocal size
            if not asset or asset.startswith("./") or asset in copied:
                return copied.get(asset, asset)
            sources = glob.glob(asset.replace("<UDIM>", "[0-9][0-9][0-9][0-9]")) if "<UDIM>" in asset else [asset]
            sources = [s for s in sources if os.path.isfile(s)]
            if not sources:
                return asset
            for s in sources:
                dst = tex / os.path.basename(s)
                if not dst.exists():
                    shutil.copy2(s, dst)
                    size += dst.stat().st_size
            copied[asset] = "./textures/" + os.path.basename(asset)
            return copied[asset]

        UsdUtils.ModifyAssetPaths(layer, move)
        layer.Save()
        lines.append(f"{inst}: {folder} ({len(copied)} textures, {logic.size_word(size)})")
    return lines


# --- Sublayer / Reference LOPs that read a publish (the user's ask, 2026-11-17) --------------------------------

LAYER_TYPES = ("sublayer", "reference::2.0", "reference")
LAYER_SEP = "#"  # a layer row's path: <node path>#<file index>


def find_publish_layers(root=None) -> list[tuple[Any, int, logic.PublishRef]]:
    """(node, file index, publish) for every Sublayer / Reference LOP file that reads a publish, outside locked
    HDAs (a loader's own sublayers are its business). Paths with a variable or an expression are not read."""
    prefix = (root.path().rstrip("/") + "/") if root is not None else "/"
    out = []
    for name in LAYER_TYPES:
        t = hou.nodeType(hou.lopNodeTypeCategory(), name)
        for node in (t.instances() if t is not None else ()):
            if not node.path().startswith(prefix) or node.isInsideLockedHDA():
                continue
            n = node.parm("num_files")
            for i in range(1, (n.eval() if n is not None else 1) + 1):
                p = node.parm(f"filepath{i}")
                ref = logic.parse_publish_path(p.unexpandedString()) if p is not None else None
                if ref is not None:
                    out.append((node, i, ref))
    return sorted(out, key=lambda x: (x[0].path(), x[1]))


def _layer(path: str) -> tuple[Any, int, logic.PublishRef | None]:
    node_path, _, index = path.partition(LAYER_SEP)
    node = hou.node(node_path)
    i = int(index or 1)
    p = node.parm(f"filepath{i}") if node is not None else None
    return node, i, (logic.parse_publish_path(p.unexpandedString()) if p is not None else None)


def update_layers(paths: list[str]) -> list[str]:
    """Each layer file to the newest version of its publish that holds the same file; one undo step."""
    from apps.houdini.solaris_adapter import undo_group

    lines = []
    with undo_group("Update sublayers"):
        for path in paths:
            node, i, ref = _layer(path)
            if ref is None:
                continue
            found = logic.ref_versions(ref)
            newest = found[-1] if found else ""
            if newest and logic._vnum(newest) > logic._vnum(ref.version):
                node.parm(f"filepath{i}").set(ref.path_in(newest))
                lines.append(f"{node.name()}: {ref.word} {ref.version} -> {newest}")
    return lines


def _layer_roots(path: str) -> list[str]:
    from pxr import Sdf

    layer = Sdf.Layer.FindOrOpen(path)
    return [p.name for p in layer.rootPrims] if layer is not None else []


def _branch_after(node) -> list:
    """Nodes downstream of ``node`` up to the first node that joins branches (merge, graft): the ones whose prim
    patterns still name the layer's root prims."""
    out, todo, seen = [], list(node.outputs()), set()
    while todo:
        n = todo.pop(0)
        if n.path() in seen:
            continue
        seen.add(n.path())
        out.append(n)
        if n.type().name().split("::")[0] in ("merge", "graftstages", "graftbranches"):
            continue
        todo.extend(n.outputs())
    return out


def convert_layers(paths: list[str]) -> tuple[list[str], list[str]]:
    """Sublayer / Reference LOPs of one publish file -> MonoFX Loaders on Source Asset (same name, place, wires;
    lookdev or model at the version the node read, nothing else turned on). The loader puts the asset under
    /<prim>, so prim patterns of the nodes after it in its branch are moved there (xform and the like); a node
    further on that names those prims is listed, not changed. One undo step. (what was converted, notes)"""
    from apps.houdini.solaris_adapter import manual_update, undo_group

    done, notes = [], []
    with undo_group("Convert sublayers to MonoFX Loaders"), manual_update():
        for path in paths:
            node, i, ref = _layer(path)
            if ref is None or node is None:
                continue
            n_files = node.parm("num_files").eval() if node.parm("num_files") else 1
            if n_files != 1 or ref.kind != "asset":
                notes.append(f"{node.name()}: not converted ({'several files' if n_files != 1 else 'a shot file'})")
                continue
            if not ref.loader_reads:  # e.g. a texturing geo: the loader would look for it in 03_uv, "missing"
                notes.append(f"{node.name()}: not converted (a {ref.word} publish; the MonoFX Loader reads UV "
                             "models and lookdevs)")
                continue
            root = Path(ref.root)
            state = logic.initial_asset_state(root, ref.entity)
            if ref.part == "lookdev":
                state = dataclasses.replace(state, versions={**state.versions, "lookdev": ref.version})
            else:  # a model publish: that file, no lookdev (the node read none)
                state = dataclasses.replace(state, model_version=ref.version, model_file=ref.file,
                                            enabled={**state.enabled, "lookdev": False})
            state = dataclasses.replace(state, enabled={**state.enabled, "groom": False})
            parent, name = node.parent(), node.name()
            prim = re.sub(r"[^0-9A-Za-z_]+", "_", name).strip("_") or ref.entity
            roots = _layer_roots(ref.publish_dir().joinpath(ref.version, ref.file).as_posix())
            ins = [(c.inputIndex(), c.inputNode(), c.outputIndex()) for c in node.inputConnections()]
            outs = [(c.outputNode(), c.inputIndex()) for c in node.outputConnections()]
            display, pos = node.isDisplayFlagSet(), node.position()
            branch = _branch_after(node)
            node.setName(_unique_name(parent, name + "_sublayer"))
            loader = parent.createNode(config.HDA_TYPE, name)
            set_use_prim(loader, True)  # the nodes after it are moved under /<prim> below
            loader.setPosition(pos)
            write_state(loader, dataclasses.replace(state, instance_name=prim))
            _set(loader, "mx_hide_enable", 0)  # the sublayer showed every prim: the loader hides none either
            refresh(loader)
            for index, src, out_index in ins:
                loader.setInput(index, src, out_index)
            for dst, index in outs:
                dst.setInput(index, loader)
            if display:
                loader.setDisplayFlag(True)
            node.destroy()
            moved, named = [], []
            for n in branch:
                for p in n.parms():
                    if p.parmTemplate().type() != hou.parmTemplateType.String or p.isLocked():
                        continue
                    raw = p.unexpandedString()
                    if "lopinputprims" in raw and ("primpattern" in p.name() or "primpath" in p.name()):
                        # "every root prim of my input" meant the layer's root prims; the input's root is now
                        # /<prim>: name them under it, or the node would move the whole group in another frame
                        p.set(" ".join(f"/{prim}/{r}" for r in roots))
                        moved.append(n.name())
                        continue
                    if not any(f"/{r}" in raw for r in roots):
                        continue
                    if "primpattern" in p.name() or "primpath" in p.name():
                        new = logic.root_patterns_moved(raw, roots, prim)
                        if new != raw:
                            p.set(new)
                            moved.append(n.name())
                    else:
                        named.append(f"{n.name()}.{p.name()}")
            done.append(f"{name} -> /{prim}" + (f" (moved {', '.join(sorted(set(moved)))})" if moved else ""))
            if named:
                notes.append(f"{name}: check {', '.join(named[:4])} (they name the old prim paths)")
            tail = [n.name() for n in branch if n.type().name().split("::")[0] in ("graftstages", "graftbranches")]
            if tail:
                notes.append(f"{name}: after {tail[0]} its prims sit one level deeper, under /{prim}")
    return done, notes


# --- Bake to plain nodes, and back (the user's ask, 2026-11-17) -----------------------------------------------
# A loader becomes a plain subnet anyone with Houdini opens: the loader's own network copied in, its parms as spare
# parms without callbacks or menus, the subdivision Python LOP holding its plan as data (no MonoFX import). The
# subnet keeps the loader's parm values and a mark, so Upgrade turns it back into a MonoFX Loader.

BAKED_USER_DATA = "monofx_baked_loader"  # JSON {"type": <loader type>}: a baked loader, Upgrade restores it

BAKED_SHOW_CODE = """hda = hou.pwd().parent()
stage = hou.pwd().editableStage()
from pxr import UsdGeom
@ROOT@
# Each prim's own visibility and purpose, baked from the MonoFX Loader
RULES = %s
for rule in RULES if root is not None else []:
    tops = instance_prims(stage) if rule["pattern"] == "." else [stage.GetPrimAtPath(root + "/" + rule["pattern"])]
    for prim in tops:
        if not prim or not prim.IsA(UsdGeom.Imageable):
            continue
        img = UsdGeom.Imageable(prim)
        if "vis" in rule:
            img.CreateVisibilityAttr().Set(rule["vis"])
        if "purpose" in rule:
            img.CreatePurposeAttr().Set(rule["purpose"])
""".replace("@ROOT@", config.ROOT_CODE)

BAKED_SUBD_CODE = """hda = hou.pwd().parent()
stage = hou.pwd().editableStage()
from pxr import Sdf, Usd, UsdGeom
@ROOT@
vp = hda.evalParm("mx_viewport")
look_vp, groom_vp = vp & 1, vp & 2
# Subdivision per mesh, baked from the MonoFX Loader (shot rule > lookdev > anim > none): mesh -> (scheme, dicing)
PLAN = %s
if root is not None:
    for mesh, (scheme, dicing) in PLAN.items():
        prim = stage.GetPrimAtPath(root + mesh)
        if not prim:
            continue
        UsdGeom.Mesh(prim).GetSubdivisionSchemeAttr().Set(scheme)
        if dicing is not None:
            UsdGeom.PrimvarsAPI(prim).CreatePrimvar("karma:object:dicingquality", Sdf.ValueTypeNames.Float,
                                                    UsdGeom.Tokens.constant).Set(dicing)
for top in instance_prims(stage):
    for prim in Usd.PrimRange(top):
        if not look_vp:
            rel = prim.GetRelationship("material:binding")
            targets = rel.GetTargets() if rel else []
            if targets:
                prim.CreateRelationship("material:binding:full", False).SetTargets(targets)
                rel.SetTargets([])
        if not groom_vp and prim.IsA(UsdGeom.BasisCurves):
            UsdGeom.Imageable(prim).CreatePurposeAttr().Set(UsdGeom.Tokens.render)
""".replace("@ROOT@", config.ROOT_CODE)


def _plain_templates(group) -> "hou.ParmTemplateGroup":
    """The loader's parms without what needs MonoFX: buttons go, callbacks and menu scripts are cleared."""
    out = hou.ParmTemplateGroup()

    def clean(t):
        if t.type() == hou.parmTemplateType.Button:
            return None
        if t.type() == hou.parmTemplateType.Folder:
            kids = [k for k in (clean(c) for c in t.parmTemplates()) if k is not None]
            t.setParmTemplates(kids)
            return t
        if hasattr(t, "setScriptCallback"):
            t.setScriptCallback("")
        if hasattr(t, "itemGeneratorScript") and t.itemGeneratorScript():
            t.setItemGeneratorScript("")
            if hasattr(t, "setMenuType"):
                t.setMenuType(hou.menuType.StringReplace)
        return t

    for t in group.entries():
        c = clean(t)
        if c is not None:
            out.append(c)
    return out


def _copy_parm_values(src, dst) -> None:
    for p in src.parms():
        q = dst.parm(p.name())
        if q is None or q.isLocked():
            continue
        try:
            if p.parmTemplate().type() == hou.parmTemplateType.String:
                q.set(p.unexpandedString())  # $F stays a variable
            elif not p.keyframes():
                q.set(p.eval())
        except (hou.OperationFailed, TypeError):
            continue


def _replace(old, new) -> None:
    """``new`` takes ``old``'s name, place, wires and display flag; ``old`` goes."""
    parent, name = old.parent(), old.name()
    ins = [(c.inputIndex(), c.inputNode(), c.outputIndex()) for c in old.inputConnections()]
    outs = [(c.outputNode(), c.inputIndex()) for c in old.outputConnections()]
    display, pos = old.isDisplayFlagSet(), old.position()
    old.setName(_unique_name(parent, name + "_old"))
    new.setName(name)
    new.setPosition(pos)
    for index, src, out_index in ins:
        new.setInput(index, src, out_index)
    for dst, index in outs:
        dst.setInput(index, new)
    if display:
        new.setDisplayFlag(True)
    old.destroy()


def bake_loaders(paths: list[str]) -> tuple[list[str], list[str]]:
    """MonoFX Loaders -> plain subnets that need no MonoFX (see above); one undo step. (baked, notes)"""
    from apps.houdini.solaris_adapter import manual_update, undo_group

    done, notes = [], []
    with undo_group("Bake loaders to plain nodes"), manual_update():
        for path in paths:
            node = hou.node(path)
            if node is None or node.type().name() not in (config.HDA_TYPE, config.OLD_TYPE):
                continue
            node.cook(force=True)  # a locked LOP HDA makes its inner nodes on first cook
            plan, _faces = node_subd_plan(node)
            parent = node.parent()
            sub = parent.createNode("subnet", _unique_name(parent, node.name() + "_baked"))
            for child in sub.children():  # its own output0: the loader's comes with the copy
                child.destroy()
            group = sub.parmTemplateGroup()
            for t in _plain_templates(node.parmTemplateGroup()).entries():
                group.append(t)
            sub.setParmTemplateGroup(group)
            _copy_parm_values(node, sub)
            kids = node.children()
            copies = hou.copyNodesTo(kids, sub)
            by_name = {c.name(): c for c in copies}
            for orig in kids:  # wires from the subnet's input were not copied
                for i, conn in enumerate(orig.inputConnections()):
                    if conn.subnetIndirectInput() is not None:
                        by_name[orig.name()].setInput(conn.inputIndex(), sub.indirectInputs()[conn.subnetIndirectInput().number()])
                if orig.isDisplayFlagSet():
                    by_name[orig.name()].setDisplayFlag(True)
            subd = by_name.get("render_only")
            if subd is not None:
                data = {m: (c.scheme, c.dicing) for m, c in plan.items()}
                subd.parm("python").set(BAKED_SUBD_CODE % repr(data))
            show = by_name.get("show_rules")
            if show is not None:
                show.parm("python").set(BAKED_SHOW_CODE % repr(logic.parse_show_rules(_s(node, config.P_SHOW_RULES))))
            sub.setUserData(BAKED_USER_DATA, json.dumps({"type": node.type().name()}))
            sub.setComment("baked MonoFX Loader: no MonoFX needed; Upgrade in the manager restores the loader")
            name = node.name()
            _replace(node, sub)
            done.append(name)
    return done, notes


def _is_baked(node) -> bool:
    return bool(node.userData(BAKED_USER_DATA)) if node is not None else False


def find_baked(root=None) -> list:
    """Subnets made by bake_loaders, in every LOP network."""
    prefix = (root.path().rstrip("/") + "/") if root is not None else "/"
    t = hou.nodeType(hou.lopNodeTypeCategory(), "subnet")
    return sorted((n for n in (t.instances() if t else ()) if n.path().startswith(prefix) and _is_baked(n)),
                  key=lambda n: n.path())


def restore_baked(node):
    """A baked subnet -> the MonoFX Loader again, from the loader parms it kept (edits made inside are lost)."""
    loader = node.parent().createNode(config.HDA_TYPE, _unique_name(node.parent(), node.name() + "_loader"))
    set_use_prim(loader, True)  # baked before Prim Name had a toggle: it grafted; baked after: its value is copied
    _copy_parm_values(node, loader)
    refresh(loader)
    _replace(node, loader)
    return loader


def camera_info(path: str) -> dict:
    """The camera a loader puts on the stage, at the current frame (what renders: the loader's own settings applied):
    prim, focal length (and whether it is animated), apertures, clipping, f-stop, focus distance. {} without one."""
    from pxr import Usd, UsdGeom

    node = hou.node(path)
    if node is None:
        return {}
    try:
        stage = node.stage()
    except hou.OperationFailed:
        return {}
    if stage is None:
        return {}
    t = Usd.TimeCode(hou.frame())
    cam = next((p for p in stage.Traverse() if p.IsA(UsdGeom.Camera)), None)
    if cam is None:
        return {}
    c = UsdGeom.Camera(cam)

    mpu = UsdGeom.GetStageMetersPerUnit(stage) or 0.01

    def get(attr, scale=1.0):
        v = attr.Get(t) if attr else None
        return None if v is None else float(v) * scale

    # USD lens values are tenths of a scene unit (sh025, 1 m a unit: 35 mm is 0.35), distances are scene units:
    # the inspector says mm and m
    mm, m = mpu * 100.0, mpu
    focal = c.GetFocalLengthAttr()
    clip = c.GetClippingRangeAttr().Get(t)
    return {"prim": cam.GetPath().pathString, "focal": get(focal, mm), "focal_animated": focal.GetNumTimeSamples() > 1,
            "h_aperture": get(c.GetHorizontalApertureAttr(), mm), "v_aperture": get(c.GetVerticalApertureAttr(), mm),
            "clip": (clip[0] * m, clip[1] * m) if clip is not None else None, "fstop": get(c.GetFStopAttr()),
            "focus": get(c.GetFocusDistanceAttr(), m)}


# --- the manager window's backend --------------------------------------------------------------------

class HoudiniBackend:
    """What ``tools.fx.anim_loader.controller.Controller`` needs, on the scene. ``scan`` reads only the disk."""

    def __init__(self, parent_path: str = "/stage") -> None:
        self.parent_path = parent_path

    def loaders(self):
        from tools.fx.anim_loader.controller import LoaderInfo

        out = []
        for n in find_loaders():
            kind = n.type().name()
            legacy = kind != config.HDA_TYPE  # 2.2, 2.1, or a Character Loader 3.2: offered for Upgrade
            readable = kind in (config.HDA_TYPE, config.OLD_TYPE)  # 2.2 has the same parms: its state is real
            out.append(LoaderInfo(n.path(), read_state(n) if readable else None, legacy, n.name(),
                                  _s(n, config.P_SUBD_RULES) if readable else "",
                                  show=_show_settings(n) if readable else None))
        for n in find_baked():  # baked loaders: Upgrade restores them
            out.append(LoaderInfo(n.path(), None, True, n.name(), "", None, True))
        for node, i, ref in find_publish_layers():  # Sublayer / Reference LOPs reading a publish
            many = (node.parm("num_files").eval() if node.parm("num_files") else 1) > 1
            out.append(LoaderInfo(f"{node.path()}{LAYER_SEP}{i}", None, False,
                                  f"{node.name()} {i}" if many else node.name(), "", ref))
        return out

    @staticmethod
    def scan(infos):
        out = {i.path: logic.status(i.state) for i in infos if i.state is not None}
        for i in infos:  # Source Asset with a complete lookdev: the UV publish is not loaded, so not "missing"
            st = i.state
            if st is not None and logic.is_asset(st) and st.enabled.get("lookdev"):
                look = logic.resolve(st).lookdev
                if look and lookdev_defines_geometry(look):
                    out[i.path] = {**out[i.path], "anim": (logic.STATUS_OFF, None)}
        for i in infos:
            if getattr(i, "layer", None) is not None:
                out[i.path] = {i.layer.part: logic.ref_status(i.layer)}
        return out

    @staticmethod
    def subd(infos):
        """Per geo loader {"plan", "faces"}, from the publish files (worker thread)."""
        out = {}
        for i in infos:
            st = i.state
            if st is None or st.kind != "geo":
                continue
            r = logic.resolve(st)
            look = r.lookdev if st.enabled.get("lookdev") else ""
            geo = geometry_file(r.anim, look, logic.is_asset(st))
            plan, faces = plan_for(geo, look, i.subd_rules)
            groom = logic.first_frame_path(r.groom, r.frames.get("groom", (None,))[0]) \
                if st.enabled.get("groom") and r.groom else ""
            curves = groom_curve_counts(groom)
            out[i.path] = {"plan": plan, "faces": faces, "curves": curves,
                           "shown": shown_for(list(plan), list(curves), geo, look, getattr(i, "show", None))}
        return out

    @staticmethod
    def set_subd(path, patterns, scheme, dicing):
        from apps.houdini.solaris_adapter import undo_group

        node = hou.node(path)
        rules = logic.parse_subd_rules(_s(node, config.P_SUBD_RULES))
        with undo_group(f"Subdivision {node.name()}"):
            node.parm(config.P_SUBD_RULES).set(json.dumps(logic.set_subd_rules(rules, list(patterns), scheme, dicing)))

    @staticmethod
    def clear_subd(path, patterns):
        from apps.houdini.solaris_adapter import undo_group

        node = hou.node(path)
        rules = logic.parse_subd_rules(_s(node, config.P_SUBD_RULES))
        left = logic.clear_subd_rules(rules, patterns)
        with undo_group(f"Clear subdivision {node.name()}"):
            node.parm(config.P_SUBD_RULES).set(json.dumps(left) if left else "")

    @staticmethod
    def set_show(path, edits):
        """(pattern, "vis" | "purpose", value or None) edits of the shot's show rules; one undo step."""
        from apps.houdini.solaris_adapter import undo_group

        node = hou.node(path)
        rules = logic.parse_show_rules(_s(node, config.P_SHOW_RULES))
        left = logic.set_show_rules(rules, list(edits))
        with undo_group(f"Show {node.name()}"):
            node.parm(config.P_SHOW_RULES).set(json.dumps(left) if left else "")

    @staticmethod
    def set_show_many(by_loader):
        """{loader: edits} of one toggle click over several loaders; one undo step."""
        from apps.houdini.solaris_adapter import undo_group

        with undo_group("Show"):
            for path, edits in by_loader.items():
                node = hou.node(path)
                if node is None:
                    continue
                left = logic.set_show_rules(logic.parse_show_rules(_s(node, config.P_SHOW_RULES)), list(edits))
                node.parm(config.P_SHOW_RULES).set(json.dumps(left) if left else "")

    @staticmethod
    def clear_overrides(path, patterns):
        """The shot's subdivision and show rules for those rows (None: all of them); one undo step."""
        from apps.houdini.solaris_adapter import undo_group

        node = hou.node(path)
        subd = logic.clear_subd_rules(logic.parse_subd_rules(_s(node, config.P_SUBD_RULES)), patterns)
        show = logic.parse_show_rules(_s(node, config.P_SHOW_RULES))
        show = logic.clear_show_rules(show, patterns)
        with undo_group(f"Clear overrides {node.name()}"):
            node.parm(config.P_SUBD_RULES).set(json.dumps(subd) if subd else "")
            node.parm(config.P_SHOW_RULES).set(json.dumps(show) if show else "")

    @staticmethod
    def subd_to_asset(path):
        """The loader's subdivision and show rules on every other loader of the same asset; returns how many."""
        from apps.houdini.solaris_adapter import undo_group

        src = hou.node(path)
        asset = _s(src, config.P_ASSET)
        subd, show = _s(src, config.P_SUBD_RULES), _s(src, config.P_SHOW_RULES)
        others = [n for n in find_loaders() if n.type().name() == config.HDA_TYPE and n.path() != path
                  and asset and _s(n, config.P_ASSET) == asset]
        with undo_group(f"Overrides to every {asset}"):
            for n in others:
                n.parm(config.P_SUBD_RULES).set(subd)
                n.parm(config.P_SHOW_RULES).set(show)
        return len(others)

    @staticmethod
    def cam_parms(path):
        return cam_parms(path)

    @staticmethod
    def set_cam_parm(path, name, value):
        return set_cam_parm(path, name, value)

    @staticmethod
    def cam_mode(path):
        return cam_mode(path)

    @staticmethod
    def set_cam_mode(path, token):
        return set_cam_mode(path, token)

    @staticmethod
    def thumbnail(state) -> str:
        if not state.asset or not state.project_root:
            return ""
        asset_dir = logic.list_asset_dirs(Path(state.project_root)).get(state.asset)
        p = logic.asset_thumbnail(asset_dir) if asset_dir else None
        return p.as_posix() if p else ""

    @staticmethod
    def update(paths, parts):
        return update([hou.node(p) for p in paths if hou.node(p)], tuple(parts))

    @staticmethod
    def version_picks(path, part):
        node = hou.node(path)
        if node is None or node.type().name() not in (config.HDA_TYPE, config.OLD_TYPE):
            return []
        return logic.version_picks(read_state(node), part)

    @staticmethod
    def set_part_version(paths, part, version):
        return set_part_version([hou.node(p) for p in paths if hou.node(p)], part, version)

    def load_shot(self, root, shot, version):
        r = load_shot(hou.node(self.parent_path), root, shot, version)
        return r.created, r.kept

    @staticmethod
    def upgrade(paths):
        return len(upgrade([hou.node(p) for p in paths if hou.node(p)]))

    @staticmethod
    def retarget(paths, shot):
        return retarget([hou.node(p) for p in paths if hou.node(p) is not None], shot)

    @staticmethod
    def set_asset(path, asset):
        set_asset(hou.node(path), asset)

    @staticmethod
    def select(path):
        """Selects the node and brings it into view in the Network Editor (its network, framed)."""
        node = hou.node(path.partition(LAYER_SEP)[0])
        if node is None:
            return
        node.setSelected(True, clear_all_selected=True)
        node.setCurrent(True, clear_all_selected=False)
        for pane in hou.ui.paneTabs():
            if pane.type() != hou.paneTabType.NetworkEditor:
                continue
            try:
                if pane.pwd() != node.parent():
                    pane.cd(node.parent().path())
                pane.homeToSelection()
            except (AttributeError, hou.OperationFailed):
                continue
            break

    @staticmethod
    def undo():
        hou.undos.performUndo()

    @staticmethod
    def heavy_message():
        return None if hulls_on() else heavy_message()

    @staticmethod
    def set_hulls_only():
        return set_hulls_only(True)

    @staticmethod
    def hulls_on():
        return hulls_on()

    @staticmethod
    def assets(root: str) -> list[str]:
        return sorted(logic.list_asset_dirs(Path(root))) if root else []

    def add_assets(self, root, names):
        r = add_assets(hou.node(self.parent_path), root, list(names))
        return r.created, r.kept, r.notes

    @staticmethod
    def solo(paths):
        return solo(list(paths))

    @staticmethod
    def set_viewport_part(part, on):
        return set_viewport_part(part, on)

    @staticmethod
    def viewport_part_on(part):
        return viewport_part_on(part)

    @staticmethod
    def frame(path):
        return frame(path)

    @staticmethod
    def viewport_prims():
        return viewport_prims()

    @staticmethod
    def instance_roots(paths):
        out = {}
        for p in paths:
            node = hou.node(p)
            root = instance_root(node) if node is not None and node.parm(config.P_INSTANCE) is not None else None
            if root is not None:
                out[p] = root
        return out

    @staticmethod
    def select_prims(network, prims):
        return select_prims(network, prims)

    @staticmethod
    def displayed_loaders(network):
        return displayed_loaders(network)

    @staticmethod
    def display_roots(network, loaders):
        return display_roots(network, loaders)

    @staticmethod
    def open_folder(path):
        return open_external(publish_folder(path))

    @staticmethod
    def part_folders(path):
        return part_folders(path)

    @staticmethod
    def open_part_folder(path, part):
        return open_part_folder(path, part)

    @staticmethod
    def open_monos(path):
        return open_external(monos_link_for(path))

    @staticmethod
    def set_source(paths, source):
        return set_source(list(paths), source)

    @staticmethod
    def handoff(paths, out_dir):
        return handoff(list(paths), out_dir)

    @staticmethod
    def extras(infos, target_root, target_shot):
        """Worker thread: what is new per behind part (with mesh changes), texture weight, shot gaps."""
        news, weight = {}, {}
        for i in infos:
            st = i.state
            if st is None:
                continue
            items = []
            for part in (("anim",) if st.kind == "cam" else ("anim", *logic.PARTS)):
                w = logic.whats_new(st, part)
                if w is None:
                    continue
                if w.old_path and w.new_path:
                    try:
                        extra = logic.mesh_change_lines(mesh_paths(w.old_path), mesh_paths(w.new_path))
                    except Exception:
                        extra = []
                    w = dataclasses.replace(w, lines=tuple(extra) + w.lines)
                items.append(w)
            if items:
                news[i.path] = items
            r = logic.resolve(st)
            if r.lookdev and st.enabled.get("lookdev"):
                weight[i.path] = texture_bytes(r.lookdev)
        have = {i.state.anim_file for i in infos if i.state is not None and i.state.shot == target_shot
                and not logic.is_asset(i.state)}
        gaps = logic.shot_gaps(target_root, target_shot, have) if target_root and target_shot else ("", [])
        return {"news": news, "weight": weight, "gaps": gaps}

    @staticmethod
    def camera_info(path):
        return camera_info(path)

    @staticmethod
    def bake(paths):
        return bake_loaders(list(paths))

    @staticmethod
    def reload_from_disk(paths):
        return reload_from_disk(list(paths))

    @staticmethod
    def update_layers(paths):
        return update_layers(list(paths))

    @staticmethod
    def convert_layers(paths):
        return convert_layers(list(paths))

    @staticmethod
    def project_and_shot() -> tuple[str, str]:
        hip = Path(hou.hipFile.path())
        root = logic.find_project_root(hip)
        return (root.as_posix() if root else "", logic.detect_shot(hip) or "")


# --- subdivision ------------------------------------------------------------------------------------

_SUBD_CACHE: dict[tuple[str, float], tuple[list[str], dict[str, str], dict[str, int]]] = {}
DICING_PRIMVAR = "karma:object:dicingquality"


def subd_opinions(path: str) -> tuple[list[str], dict[str, str], dict[str, int]]:
    """(mesh paths, authored subdivisionScheme per prim, face count per mesh) of one publish file and its
    sublayers, read from the file itself (cached by modification time)."""
    import os

    from pxr import Usd, UsdGeom

    if not path or not os.path.isfile(path):
        return [], {}, {}
    key = (path, os.path.getmtime(path))
    if key not in _SUBD_CACHE:
        stage = Usd.Stage.Open(path, Usd.Stage.LoadNone)
        meshes, schemes, faces = [], {}, {}
        for prim in stage.TraverseAll():  # lookdev holds overs, which Traverse() skips
            attr = prim.GetAttribute("subdivisionScheme")
            if attr and attr.HasAuthoredValue():
                schemes[prim.GetPath().pathString] = str(attr.Get())
            if prim.IsA(UsdGeom.Mesh):
                meshes.append(prim.GetPath().pathString)
                counts = UsdGeom.Mesh(prim).GetFaceVertexCountsAttr().Get()
                faces[prim.GetPath().pathString] = len(counts) if counts is not None else 0
        _SUBD_CACHE.clear() if len(_SUBD_CACHE) > 64 else None
        _SUBD_CACHE[key] = (meshes, schemes, faces)
    return _SUBD_CACHE[key]


def plan_for(anim: str, lookdev: str, rules_text: str) -> tuple[dict, dict[str, int]]:
    """Subdivision plan from the publish files (no hou: safe on the manager's worker thread)."""
    meshes, anim_ops, faces = subd_opinions(anim)
    _, look_ops, _ = subd_opinions(lookdev)
    return logic.subd_plan(meshes, look_ops, anim_ops, logic.parse_subd_rules(rules_text)), faces


def geometry_file(anim: str, lookdev: str, asset_source: bool) -> str:
    """The file whose meshes the loader puts on the stage: a prop's complete lookdev (it defines the meshes and is
    loaded alone, `lookdev_defines_geometry`), else the anim / model publish. Subdivision and the inspector's table
    read their meshes from it: read from the model, Cliff01's 12 lookdev meshes were listed as none and got no
    subdivisionScheme (USD's catmullClark fallback)."""
    return lookdev if asset_source and lookdev and lookdev_defines_geometry(lookdev) else anim


def node_subd_plan(node) -> tuple[dict, dict[str, int]]:
    """The subdivision plan of a loader (logic.subd_plan) and its meshes' face counts."""
    look = _s(node, config.P_PATH["lookdev"]) if node.evalParm(config.P_ENABLE["lookdev"]) else ""
    asset = _s(node, config.P_SOURCE) == config.SOURCE_ASSET
    return plan_for(geometry_file(_s(node, config.P_ANIM_PATH), look, asset), look, _s(node, config.P_SUBD_RULES))


def author_subd(node, stage) -> None:
    """Called by the HDA's Python LOP after the graft: the scheme and dicing of every anim mesh of the instance."""
    from pxr import Sdf, UsdGeom

    root = instance_root(node)
    if root is None:
        return
    plan, _ = node_subd_plan(node)
    for mesh, choice in plan.items():
        prim = stage.GetPrimAtPath(root + mesh)
        if not prim:
            continue
        UsdGeom.Mesh(prim).GetSubdivisionSchemeAttr().Set(choice.scheme)
        if choice.dicing is not None:
            UsdGeom.PrimvarsAPI(prim).CreatePrimvar(DICING_PRIMVAR, Sdf.ValueTypeNames.Float,
                                                    UsdGeom.Tokens.constant).Set(choice.dicing)


# --- what each prim shows (visibility, purpose: the user's pick, layout B, 2026-11-17) --------------------------

_SHOW_CACHE: dict = {}
_CURVES_CACHE: dict = {}


def _show_settings(node) -> dict:
    """What the worker thread needs, read on the main thread: the shot's rules, Hide Prims, Show in Viewport."""
    return {"rules": _s(node, config.P_SHOW_RULES), "hide_on": bool(node.evalParm(config.P_HIDE_ENABLE)),
            "hide": _s(node, config.P_HIDE_PATTERN), "viewport": int(node.evalParm(config.P_VIEWPORT))}


def show_opinions(path: str) -> dict[str, dict]:
    """{prim (no leading "/"): {"visibility", "purpose"}} authored in a publish file and its sublayers (cached by
    modification time; lookdev holds overs, read with TraverseAll)."""
    import os

    from pxr import Usd

    if not path or not os.path.isfile(path):
        return {}
    key = (path, os.path.getmtime(path))
    if key not in _SHOW_CACHE:
        stage = Usd.Stage.Open(path, Usd.Stage.LoadNone)
        out: dict[str, dict] = {}
        for prim in stage.TraverseAll():
            for name in ("visibility", "purpose"):
                attr = prim.GetAttribute(name)
                if attr and attr.HasAuthoredValue():
                    v = attr.Get(Usd.TimeCode.EarliestTime()) if attr.GetNumTimeSamples() else attr.Get()
                    out.setdefault(prim.GetPath().pathString.strip("/"), {})[name] = str(v)
        _SHOW_CACHE.clear() if len(_SHOW_CACHE) > 64 else None
        _SHOW_CACHE[key] = out
    return _SHOW_CACHE[key]


def groom_curve_counts(path: str) -> dict[str, int]:  # not groom_curves (the cache's own paths, refresh)
    """{path under the instance ("/Groom/<name>"): control points} of the groom file's curves (its first frame for a
    sequence), where the loader puts them (logic.groom_targets)."""
    import os

    from pxr import Usd, UsdGeom

    if not path or not os.path.isfile(path):
        return {}
    key = (path, os.path.getmtime(path))
    if key not in _CURVES_CACHE:
        stage = Usd.Stage.Open(path, Usd.Stage.LoadNone)
        counts = {}
        for prim in stage.TraverseAll():
            if prim.IsA(UsdGeom.BasisCurves):
                pts = UsdGeom.BasisCurves(prim).GetPointsAttr()
                v = pts.Get(Usd.TimeCode.EarliestTime()) if pts.GetNumTimeSamples() else pts.Get()
                counts[prim.GetPath().pathString] = len(v) if v is not None else 0
        _CURVES_CACHE.clear() if len(_CURVES_CACHE) > 32 else None
        _CURVES_CACHE[key] = {dst: counts[src] for src, dst in logic.groom_targets(list(counts))}
    return _CURVES_CACHE[key]


def shown_for(meshes: list[str], curves: list[str], anim: str, lookdev: str, show: dict | None) -> dict:
    """logic.prim_shows for a loader's meshes and curves, from its publish files and settings (no hou)."""
    show = show or {}
    prims = [p.strip("/") for p in meshes + curves]
    groups = {"/".join(p.split("/")[:i]) for p in prims for i in range(1, p.count("/") + 1)}
    publish = {**show_opinions(anim), **show_opinions(lookdev)}
    hidden = logic.hide_targets(show.get("hide", ""), sorted(groups | set(prims))) if show.get("hide_on") else []
    render_only = [c.strip("/") for c in curves] if not (show.get("viewport", 3) & 2) else []
    return logic.prim_shows(prims, publish, hidden, render_only, logic.parse_show_rules(show.get("rules", "")))


def author_show(node, stage) -> None:
    """Called by the HDA's show_rules Python LOP, last: what the shot shows of each prim it names."""
    from pxr import UsdGeom

    root = instance_root(node)
    if root is None:
        return
    # each prim's own eye and purpose, as Houdini authors them: hiding prunes (the children keep their own
    # visibility for when the parent shows again), purpose inherits where a prim has none of its own
    for rule in logic.parse_show_rules(_s(node, config.P_SHOW_RULES)):
        paths = instance_paths(node) if rule["pattern"] == logic.ROOT else [f"{root}/{rule['pattern']}"]
        for prim in (stage.GetPrimAtPath(p) for p in paths):  # the root rule: each top prim with Prim Name off
            if not prim or not prim.IsA(UsdGeom.Imageable):
                continue
            img = UsdGeom.Imageable(prim)
            if "vis" in rule:
                img.CreateVisibilityAttr().Set(rule["vis"])
            if "purpose" in rule:
                img.CreatePurposeAttr().Set(rule["purpose"])


# --- the camera's settings on the loader (layout B: edited from the inspector) ---------------------------------
CAM_PARMS = ("clippingRange1", "clippingRange2", "horizontalAperture", "aspectratiox", "aspectratioy",
             "xn__houdiniguidescale_s3a")


def cam_parms(path: str) -> dict[str, float]:
    """The settings the camera uses now: aperture / ratio only when the node's Aperture mode sets them (on the
    publish's aperture they do nothing, so the inspector leaves those fields empty and off)."""
    node = hou.node(path)
    if node is None:
        return {}
    mode = node.parm(config.P_CAM_APERTURE)
    mode = mode.evalAsString() if mode is not None else config.CAM_APERTURE_WIDTH  # older node: it set the width
    unused = set()
    if mode == config.CAM_APERTURE_PUBLISH:
        unused = {"horizontalAperture", "aspectratiox", "aspectratioy"}
    elif mode == config.CAM_APERTURE_WIDTH:
        unused = {"aspectratiox", "aspectratioy"}
    return {n: node.parm(n).eval() for n in CAM_PARMS if n not in unused and node.parm(n) is not None}


def cam_mode(path: str) -> str:
    """The loader's Aperture mode; an older node without the menu set the width (config.CAM_APERTURE_WIDTH)."""
    node = hou.node(path)
    parm = node.parm(config.P_CAM_APERTURE) if node is not None else None
    if node is None:
        return ""
    return parm.evalAsString() if parm is not None else config.CAM_APERTURE_WIDTH


def set_cam_mode(path: str, token: str) -> bool:
    """The loader's Aperture mode (publish / width / ratio); one undo step."""
    from apps.houdini.solaris_adapter import undo_group

    node = hou.node(path)
    parm = node.parm(config.P_CAM_APERTURE) if node is not None else None
    if parm is None or token not in (config.CAM_APERTURE_PUBLISH, config.CAM_APERTURE_WIDTH,
                                     config.CAM_APERTURE_RATIO):
        return False
    with undo_group(f"Camera aperture {node.name()}"):
        parm.set(token)
    return True


def set_cam_parm(path: str, name: str, value: float) -> bool:
    """One of the loader's camera settings; one undo step."""
    from apps.houdini.solaris_adapter import undo_group

    node = hou.node(path)
    if node is None or name not in CAM_PARMS or node.parm(name) is None:
        return False
    with undo_group(f"Camera {node.name()}"):
        node.parm(name).set(float(value))
    return True


# --- Reload from disk (the user's ask, 2026-11-19): a file rewritten in the same version ---------------------------
# Refresh only works the paths out again; Houdini keeps every USD file it opened, so a publish written again into
# the same vNNN kept showing the old content. hou.lop.reloadLayer re-reads a file and dirties the LOP nodes using it.

def files_of(node) -> list[str]:
    """Every file the loader reads now (main file, parts with every frame, sublayer slots, groom topology)."""
    import os

    state = read_state(node)
    r = logic.resolve(state) if state is not None else None
    if r is None:
        return []
    paths = {"anim": r.anim, "lookdev": r.lookdev, "groom": r.groom, "cloth": r.cloth}
    extra = [_s(node, p) for p in config.P_LAYERS] + [_s(node, config.P_GROOM_TOPO)]
    return [p for p in logic.loader_files(paths, r.frames, extra) if os.path.isfile(p)]


def reload_from_disk(paths: list[str]) -> tuple[int, int]:
    """Re-read every file these loaders use from disk (lookdev's own sublayers too), then cook them again.
    Versions do not move. Returns (loaders, files)."""
    loaders, files = 0, set()
    for path in paths:
        node = hou.node(path)
        if node is None or node.type().name() not in (config.HDA_TYPE, config.OLD_TYPE):
            continue
        mine = files_of(node)
        for f in mine:
            if f in files:
                continue
            try:
                hou.lop.reloadLayer(f, True)  # recursive: a lookdev's sublayers, a file's references
            except hou.OperationFailed:
                continue
            files.add(f)
        _SUBD_CACHE.clear()  # the manager's own reads (meshes, schemes, shown states, curves) start again
        _SHOW_CACHE.clear()
        _CURVES_CACHE.clear()
        # the inner Sublayer LOPs' own Reload: it dirties what follows them (graft, clips, rules); reloadLayer alone
        # left the graft's flattened copy old, and cook(force) on the HDA does not cook its children again
        for child in node.allSubChildren():
            button = child.parm("reload")
            if button is not None and button.parmTemplate().type() == hou.parmTemplateType.Button:
                try:
                    button.pressButton()
                except hou.OperationFailed:
                    pass
        try:
            node.cook(force=True)
        except hou.OperationFailed:
            pass
        loaders += 1
    return loaders, len(files)


def cb_reload(kwargs: dict) -> None:
    node = kwargs["node"]
    n_loaders, n_files = reload_from_disk([node.path()])
    _set(node, config.P_STATUS, f"Reloaded {n_files} file{'s' if n_files != 1 else ''} from disk." if n_files
         else "Nothing to reload: no file on disk.")


def cb_open_folder(kwargs: dict) -> None:
    """The Open Folder strip (Geo | Lookdev | Groom | Cloth): the clicked part's publish folder in Explorer. The strip
    is a toggle strip set back to nothing at once, so every click is a click, also on the same button twice."""
    node = kwargs["node"]
    parm = node.parm(config.P_OPEN_FOLDER)
    value = int(parm.eval()) if parm is not None else 0
    if parm is not None:
        parm.set(0)
    part = next((p for p, bit in config.OPEN_FOLDER_BITS.items() if value & bit), "")
    state = read_state(node)
    if not part or state is None:
        return
    word = logic.part_word(state, part)
    if not open_part_folder(node.path(), part):
        _set(node, config.P_STATUS, f"No {word.lower()} publish folder for this loader.")


def shot_subd_load() -> list[tuple[str, int]]:
    """(loader, estimated viewport subdivision polygons) for every 2.2 geo loader in the scene."""
    out = []
    for n in find_loaders():
        if n.type().name() != config.HDA_TYPE or n.evalParm(config.P_GEO_CAM) == 1:
            continue
        plan, faces = node_subd_plan(n)
        out.append((n.name(), logic.subd_polygons(faces, plan)))
    return out


def heavy_message() -> str | None:
    return logic.heavy_shot_message(shot_subd_load())


def scene_viewers() -> list:
    """Every Scene Viewer of the UI: its own pane tabs, and the one inside each Context Viewer (Houdini 22's
    default layouts wrap the viewer in a ContextViewer pane, which paneTabType.SceneViewer alone misses: Draw
    Hulls Only said "No viewer shows /stage" while one did, the user's report 2026-11-17)."""
    out = []
    for p in hou.ui.paneTabs():
        kind = p.type()
        if kind == hou.paneTabType.SceneViewer:
            out.append(p)
        elif kind == getattr(hou.paneTabType, "ContextViewer", None):
            try:
                viewer = p.sceneViewer()
            except (AttributeError, hou.OperationFailed):
                viewer = None
            if viewer is not None:
                out.append(viewer)
    return out


def viewport_prims() -> dict[str, tuple[str, ...]]:
    """{LOP network path: the prims selected in the first Scene Viewer showing it}. The manager reads it on a timer
    (Houdini has no callback for a viewer's scene graph selection); {} without a UI."""
    if not hou.isUIAvailable():
        return {}
    out: dict[str, tuple[str, ...]] = {}
    for pane in _stage_viewers():
        try:
            net = pane.pwd().path()
            if net not in out:
                out[net] = tuple(pane.currentSceneGraphSelection() or ())
        except (AttributeError, hou.OperationFailed, hou.ObjectWasDeleted):
            continue
    return out


def _viewer_node(network: str):
    """The LOP whose stage the viewer draws: the network's viewer node (the display flag, or a node shown in its
    place), not the selected node (the user's case: display on one node, another selected)."""
    net = hou.node(network)
    for name in ("viewerNode", "displayNode"):
        fn = getattr(net, name, None) if net is not None else None
        try:
            node = fn() if fn else None
        except hou.OperationFailed:
            node = None
        if node is not None:
            return node
    return None


def displayed_loaders(network: str) -> list[str] | None:
    """The nodes the viewer's stage is cooked from (its viewer node and every input above it): a loader outside them
    is not in what the viewport draws. None: no viewer node (nothing to filter by)."""
    node = _viewer_node(network)
    if node is None:
        return None
    return [node.path(), *(n.path() for n in node.inputAncestors())]


_DRAWN: dict = {}  # (viewer node, its cook count) -> {prim path: child names}: one walk of the stage per cook


def _drawn_prims(node) -> dict[str, set[str]]:
    """{path: its children's names} of the node's stage down to ``logic.DRAWN_ROOT_DEPTH`` ("" the stage root);
    gprims are not walked into."""
    from pxr import UsdGeom

    key = (node.path(), node.cookCount())
    if key in _DRAWN:
        return _DRAWN[key]
    out: dict[str, set[str]] = {}
    try:
        stage = node.stage()
    except hou.OperationFailed:
        stage = None
    if stage is not None:
        todo = [(stage.GetPseudoRoot(), "", 0)]
        while todo:
            prim, path, depth = todo.pop()
            kids = prim.GetChildren()
            out[path] = {k.GetName() for k in kids}
            if depth < logic.DRAWN_ROOT_DEPTH:
                todo += [(k, k.GetPath().pathString, depth + 1) for k in kids if not k.IsA(UsdGeom.Gprim)]
    _DRAWN.clear()
    _DRAWN[key] = out
    return out


def display_roots(network: str, loaders: dict) -> dict[str, str]:
    """{loader: where its instance root sits on the stage the network's viewer draws} (``logic.drawn_roots``)."""
    node = _viewer_node(network)
    if node is None:
        return {p: r for p, (r, _t) in loaders.items()}
    return logic.drawn_roots(_drawn_prims(node), loaders)


def select_prims(network: str, prims: list[str]) -> bool:
    """Selects these prims in every Scene Viewer showing ``network`` (an empty list clears its selection); a viewer
    showing another network is left alone, and prims the viewer's stage does not hold are dropped (a node after the
    loader moved or pruned them). View state: no undo step."""
    if not hou.isUIAvailable():
        return False
    node = _viewer_node(network)
    try:
        stage = node.stage() if node is not None else None
    except hou.OperationFailed:
        stage = None
    if stage is not None:
        prims = [p for p in prims if stage.GetPrimAtPath(p)]
    done = False
    for pane in _stage_viewers():
        try:
            if pane.pwd().path() != network:
                continue
            if tuple(pane.currentSceneGraphSelection() or ()) != tuple(prims):
                with hou.undos.disabler():  # view state: Ctrl+Z undoes the artist's edit, not this selection
                    pane.setCurrentSceneGraphSelection(list(prims))
            done = True
        except (AttributeError, hou.OperationFailed, hou.ObjectWasDeleted):
            continue
    return done


def _stage_viewers() -> list:
    """Scene Viewers showing a LOP network: /stage has display options of its own, so a setting made while a
    viewer shows /obj does not reach the stage (measured: hulls set before switching to /stage was off)."""
    return [p for p in scene_viewers()
            if p.pwd() is not None and p.pwd().childTypeCategory() == hou.lopNodeTypeCategory()]


def set_hulls_only(enable: bool = True) -> int:
    """Draw Hulls Only on every viewport of the Scene Viewers showing /stage; returns how many (0: none shows it).
    View state, not saved in the loaders. Measured (Helen catmullClark, Houdini 22.0.466): RAM 12.8 -> 7.2 GB,
    VRAM +6.7 -> +4.9 GB once settled; meshes with scheme none: 2.5 GB."""
    n = 0
    for pane in _stage_viewers():
        for vp in pane.viewports():
            vp.settings().setHullsOnly(enable)
            n += 1
    return n


def hulls_on() -> bool:
    """True when every Scene Viewer viewport draws hulls only; False without a UI (hython has no hou.ui)."""
    if not hou.isUIAvailable():
        return False
    viewers = _stage_viewers()
    return bool(viewers) and all(vp.settings().hullsOnly() for p in viewers for vp in p.viewports())
    return False


_CHECK_PENDING = False


def check_heavy_shot() -> None:
    """Shows the heavy-shot prompt when the shot's subdivision is heavy (UI only, once per burst of calls)."""
    global _CHECK_PENDING
    if hou is None or not hou.isUIAvailable() or _CHECK_PENDING:
        return
    _CHECK_PENDING = True

    def run():
        global _CHECK_PENDING
        _CHECK_PENDING = False
        try:
            text = heavy_message()
            if text and not hulls_on():
                from tools.fx.anim_loader import ui

                def hulls():
                    if not set_hulls_only(True):
                        hou.ui.setStatusMessage("Anim Loader: no viewer shows /stage; open it, then Draw Hulls Only.",
                                                severity=hou.severityType.Warning)

                ui.show_heavy_shot_prompt(text, hulls)
        except Exception as exc:  # never break a scene load for a hint
            hou.ui.setStatusMessage(f"Anim Loader: {exc}", severity=hou.severityType.Warning)

    import hdefereval

    hdefereval.executeDeferred(run)


_OUTDATED_PENDING = False


def outdated_loaders(states: list | None = None) -> list:
    """``logic.outdated`` of the scene's MonoFX Loaders ((name, path, state) from ``loader_states``); reads the disk
    only, so it runs on a worker thread. 2.2 / 2.1 nodes are left out: Upgrade is their step, not Update."""
    states = loader_states() if states is None else states
    found = logic.outdated([(path, st, logic.status(st)) for _name, path, st in states])
    names = {path: name for name, path, _st in states}
    return [(names.get(path, path), bits, path) for path, bits in found]


def loader_states() -> list:
    """(name, path, state) of every MonoFX Loader (main thread: reads parms)."""
    return [(n.name(), n.path(), read_state(n)) for n in find_loaders() if n.type().name() == config.HDA_TYPE]


def check_outdated() -> None:
    """Scene opened: the loaders-behind prompt, stacked with the heavy-shot one (UI only, once per burst). The
    parms are read on the main thread, the publishes on a worker thread: a Dropbox project takes a second or more."""
    global _OUTDATED_PENDING
    if hou is None or not hou.isUIAvailable() or _OUTDATED_PENDING:
        return
    _OUTDATED_PENDING = True
    import threading

    import hdefereval

    def show(found, hip):
        try:
            from tools.fx.anim_loader import ui

            items = [(name, bits) for name, bits, _path in found]
            paths = [path for _name, _bits, path in found]

            def do_update():
                nodes = [n for n in (hou.node(p) for p in paths) if n is not None]
                lines = update(nodes)
                hou.ui.setStatusMessage("MonoFX Loader: " + ("; ".join(lines) if lines else "already up to date."))
                ui.refresh_manager()  # an open manager read the scene before: it still said "2 behind"

            ui.show_outdated_prompt(items, hip, do_update, lambda: ui.open_manager())
        except Exception as exc:  # never break a scene load for a hint
            hou.ui.setStatusMessage(f"MonoFX Loader: {exc}", severity=hou.severityType.Warning)

    def work(states, hip):
        try:
            found = outdated_loaders(states)
        except Exception:
            found = []
        hdefereval.executeDeferred(lambda: show(found, hip))

    def start():
        global _OUTDATED_PENDING
        _OUTDATED_PENDING = False
        try:
            states = loader_states()
        except Exception:
            return
        threading.Thread(target=work, args=(states, hou.hipFile.path()), daemon=True,
                         name="monofx-loader-outdated").start()

    hdefereval.executeDeferred(start)


def on_loaded(node) -> None:
    """A scene with loaders opened: one heavy-shot and one loaders-behind check for the whole scene."""
    check_heavy_shot()
    check_outdated()
