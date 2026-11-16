"""Mono Anim Loader 2.2, Houdini side: reads and writes loader nodes. Decisions live in tools/fx/anim_loader/logic.py.

The HDA's PythonModule is ``from apps.houdini.anim_loader_adapter import *``. Spec: docs/plans/anim_loader_v2_2.md.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

try:
    import hou  # type: ignore
except ImportError:  # outside Houdini
    hou = None  # type: ignore[assignment]

from tools.fx.anim_loader import config, logic
from tools.fx.anim_loader.logic import LoaderState, Output, Resolved

__all__ = [
    "read_state", "write_state", "refresh", "create_loader", "cb_parm_changed", "cb_refresh",
    "cb_open_manager", "cb_apply_timeline", "apply_timeline", "menu_versions", "menu_anim_versions",
    "menu_anim_files", "menu_assets", "on_created", "find_loaders", "load_shot", "update", "set_asset",
    "upgrade", "LoadResult",
]

_F_RE = re.compile(r"\$F(\d*)")


# --- state <-> parms -------------------------------------------------------------------------

def _s(node, name: str) -> str:
    p = node.parm(name)
    return p.evalAsString().strip() if p is not None else ""


def _set(node, name: str, value) -> None:
    p = node.parm(name)
    if p is not None and p.eval() != value:
        p.set(value)


def read_state(node) -> LoaderState:
    """The node's parms as a LoaderState (no disk access)."""
    enabled = {part: bool(node.evalParm(config.P_ENABLE[part])) for part in logic.PARTS}
    versions = {part: _s(node, config.P_VERSION[part]) for part in logic.PARTS}
    kind = "cam" if node.evalParm(config.P_GEO_CAM) == 1 else "geo"
    return LoaderState(_s(node, config.P_ROOT), _s(node, config.P_SHOT), _s(node, config.P_ANIM_VERSION),
                       _s(node, config.P_ANIM_FILE), _s(node, config.P_ASSET) or None,
                       _s(node, config.P_INSTANCE), kind, enabled, versions)


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


def refresh(node) -> Resolved:
    """Resolves the node's state and writes the paths, layers, clips and status it shows. Never changes a version."""
    state = read_state(node)
    r = logic.resolve(state)
    _set(node, config.P_ANIM_PATH, r.anim)
    for part in logic.PARTS:
        _set(node, config.P_PATH[part], getattr(r, part))
    notes = list(r.notes)
    layers = [r.lookdev]
    for task in logic.FX_TASKS:
        keys = config.P_FX[task]
        pattern = getattr(r, task)
        mode, roots, first, last, template = "", [], 0, 0, ""
        if pattern:
            first, last = r.frames[task]
            mode, roots = fx_layout(_frame_file(pattern, first))
            template = _template(pattern)
            if mode == config.FX_MODE_SUBLAYER:
                layers.append(pattern)
                notes.append(f"{task}: no motion blur (cache has no time samples)")
            elif task == "groom":
                layers.append(_frame_file(pattern, first))  # topology for the clips (counts, widths)
        _set(node, keys["mode"], mode)
        _set(node, keys["template"], template)
        _set(node, keys["first"], first)
        _set(node, keys["last"], last)
        _set(node, keys["roots"], " ".join(roots))
    layers.append(r.anim)
    layers = [x for x in layers if x] + [""] * len(config.P_LAYERS)
    for name, value in zip(config.P_LAYERS, layers):
        _set(node, name, value)
    _set(node, config.P_STATUS, _status_text(state, notes))
    return r


def _status_text(state: LoaderState, notes: list[str]) -> str:
    parts = []
    for part, (st, newer) in logic.status(state).items():
        version = state.anim_version if part == "anim" else state.versions.get(part, "")
        text = f"{part} {version}".strip() if st in (logic.STATUS_OK, logic.STATUS_NEWER) else f"{part} {st}"
        if newer:
            text += f" ({newer} available)"
        parts.append(text)
    return " | ".join(parts) + ("\n" + "\n".join(notes) if notes else "")


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
    if root is not None and not _s(node, config.P_ROOT):
        _set(node, config.P_ROOT, root.as_posix())
        shot = logic.detect_shot(hip)
        if shot:
            _set(node, config.P_SHOT, shot)
            versions = logic.list_versions(logic.anim_publish_dir(root, shot))
            if versions:
                _set(node, config.P_ANIM_VERSION, versions[-1])
    _set(node, config.P_STATUS, "Pick an anim file.")


# --- callbacks and menus -------------------------------------------------------------------------

def cb_parm_changed(kwargs: dict) -> None:
    node = kwargs["node"]
    if kwargs.get("parm_name") == config.P_ANIM_FILE or (kwargs.get("parm") is not None
                                                          and kwargs["parm"].name() == config.P_ANIM_FILE):
        _new_anim_file(node)
    refresh(node)


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


def cb_refresh(kwargs: dict) -> None:
    refresh(kwargs["node"])


def cb_open_manager(kwargs: dict) -> None:
    try:
        from tools.fx.anim_loader import ui
    except ImportError:
        _set(kwargs["node"], config.P_STATUS, "The manager window is not installed yet.")
        return
    ui.open_manager()


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


def menu_anim_versions(node) -> list[str]:
    root, shot = _s(node, config.P_ROOT), _s(node, config.P_SHOT)
    return _menu(logic.list_versions(logic.anim_publish_dir(Path(root), shot))) if root and shot else []


def menu_anim_files(node) -> list[str]:
    root, shot, v = _s(node, config.P_ROOT), _s(node, config.P_SHOT), _s(node, config.P_ANIM_VERSION)
    if not (root and shot and v):
        return []
    return _menu([o.file for o in logic.read_outputs(logic.anim_publish_dir(Path(root), shot) / v)])


def menu_versions(node, part: str) -> list[str]:
    state = read_state(node)
    if not state.project_root or state.asset is None:
        return []
    return _menu(logic.list_part_versions(state, part))


def menu_assets(node) -> list[str]:
    root = _s(node, config.P_ROOT)
    return _menu(sorted(logic.list_asset_dirs(Path(root)))) if root else []


def _is_loader(node: Any) -> bool:
    return node.type().name() in (config.HDA_TYPE, *config.LEGACY_TYPES)


# --- commands of the manager window (each one undo step) ------------------------------------------

from dataclasses import dataclass, field  # noqa: E402


@dataclass
class LoadResult:
    created: list[str] = field(default_factory=list)
    kept: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def find_loaders(root=None) -> list:
    """Every Mono Anim Loader (2.2 and 2.1) under /stage, in subnets too."""
    root = root or hou.node("/stage")
    return [n for n in root.allSubChildren() if _is_loader(n)]


def _key(node) -> tuple[str, str]:
    try:
        data = json.loads(node.userData(config.USER_DATA) or "{}")
    except ValueError:
        data = {}
    return data.get("shot", ""), data.get("anim_file", "")


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
            merge = merge or _shot_merge(parent, shot)
            merge.setNextInput(node)
            result.created.append(node.name())
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
            moved = [f"anim {old.anim_version} -> {new.anim_version}"] if new.anim_version != old.anim_version else []
            moved += [f"{p} {old.versions[p] or '-'} -> {new.versions[p]}" for p in logic.PARTS
                      if new.versions[p] != old.versions[p]]
            if moved:
                write_state(node, new)
                refresh(node)
                lines.append(f"{node.name()}: " + ", ".join(moved))
    return lines


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
    with undo_group("Upgrade anim loaders to 2.2"):
        for node in nodes:
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
