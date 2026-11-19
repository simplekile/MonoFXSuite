"""Test in Houdini (the Blender add-on's button), Houdini side: a test scene of one publish in /stage, built by the
MonoFX Loader as lighting reads it, and one check line on the status bar (never a modal dialog).

Blender starts a NEW ``houdini.exe -foreground houdini_test_startup.py`` each time (the add-on's file), with
``MONOFX_TEST_KIND`` (model / anim) and ``MONOFX_TEST_PATH`` (a model file, an anim version folder); that script calls
``main()``. The scene is never saved into the project: its name points at ``%TEMP%/MonoFX/houdini_test`` so a
save lands there (Monos would take a hip in the project for a work file). Decisions: tools/fx/anim_loader/publish_preview.py.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import traceback
from pathlib import Path

try:
    import hou  # type: ignore
except ImportError:  # outside Houdini
    hou = None  # type: ignore[assignment]

from tools.fx.anim_loader import config, logic
from tools.fx.anim_loader import publish_preview as pp

ENV_KIND, ENV_PATH = "MONOFX_TEST_KIND", "MONOFX_TEST_PATH"
ENV_REPORT = "MONOFX_TEST_REPORT"  # optional: also write the result there as JSON
NOTE_NAME = "monofx_test_checks"


def work_dir() -> Path:
    return Path(tempfile.gettempdir()) / "MonoFX" / "houdini_test"


# --- facts --------------------------------------------------------------------------------------------------------

def file_facts(path: str) -> pp.FileFacts:
    from monofx_pipeline_common.publish_checks import file_facts as _ff

    return _ff(path)


def stage_facts(stage, nodes: list) -> pp.StageFacts:
    """What the loaded stage shows: meshes, bindings to no Material, the nodes' errors and status notes."""
    facts = pp.StageFacts()
    for node in nodes:
        for err in node.errors():
            facts.node_errors.append(f"{node.name()}: {err.splitlines()[0][:160]}")
        for warn in node.warnings():
            facts.notes.append(f"{node.name()} warns: {warn.splitlines()[0][:160]}")
        status = node.parm(config.P_STATUS)
        if status is not None and status.evalAsString().strip():
            facts.notes.append(f"{node.name()}: {status.evalAsString().strip()}")
    from monofx_pipeline_common.publish_checks import usd_stage_facts

    return usd_stage_facts(stage, facts)


def lookdev_facts(stage, loaders: list) -> list:
    """Each shot loader with its lookdev on: how that lookdev sits on the anim under the instance prim (a lookdev
    made on another geometry, e.g. char_Mermaid V001 on the texturing geo, binds nothing on /Geo and adds its own
    static meshes, while the line read clean)."""
    from monofx_pipeline_common.publish_checks import lookdev_facts as _lf

    out = []
    for node in loaders:
        enable, path = node.parm(config.P_ENABLE["lookdev"]), node.parm(config.P_PATH["lookdev"])
        inst, anim = node.parm(config.P_INSTANCE), node.parm(config.P_ANIM_PATH)
        if None in (enable, path, inst, anim) or not enable.eval() or not path.evalAsString().strip():
            continue
        name = inst.evalAsString().strip()
        if not name:
            continue
        version = node.parm(config.P_VERSION["lookdev"]).evalAsString()
        try:
            out.append(_lf(stage, "/" + name, version, anim.evalAsString().strip()))
        except Exception as exc:  # a check that cannot read says so, it never stops the test
            out.append(None)
            print(f"MonoFX test: lookdev check of {node.name()} failed: {exc}")
    return [f for f in out if f is not None]


# --- the scene ----------------------------------------------------------------------------------------------------

def _safe(text: str) -> str:
    return re.sub(r"[^0-9A-Za-z_]+", "_", text).strip("_") or "publish"


def _build_asset(parent, plan: pp.Plan, notes: list[str]):
    from dataclasses import replace

    from apps.houdini import anim_loader_adapter as ad

    state = pp.asset_state(plan)
    node = parent.createNode(config.HDA_TYPE, ad._unique_name(parent, plan.asset))
    ad.write_state(node, state)
    res = ad.refresh(node)
    if res.lookdev and ad.lookdev_defines_geometry(res.lookdev):
        # a prop's lookdev is the complete asset and the loader would read it alone: the test is of the UV publish
        enabled = dict(state.enabled, lookdev=False)
        ad.write_state(node, replace(state, enabled=enabled))
        ad.refresh(node)
        notes.append(f"lookdev {state.versions.get('lookdev')} holds its own meshes: left off, this is the UV "
                     "publish alone.")
    elif state.versions.get("lookdev"):
        notes.append(f"with lookdev {state.versions['lookdev']}")
    else:
        notes.append("no lookdev published")
    return node, [node]


def _build_shot(parent, plan: pp.Plan, notes: list[str]):
    from apps.houdini import anim_loader_adapter as ad

    result = ad.load_shot(parent, plan.root, plan.shot, plan.anim_version)
    notes.extend(result.notes)
    loaders = [parent.node(n) for n in result.created]
    merge = next((c for c in parent.children() if c.userData(config.MERGE_USER_DATA) == plan.shot), None)
    if loaders:
        notes.append(ad.apply_timeline(loaders[0]))
    return (merge or (loaders[-1] if loaders else None)), loaders


def _build_sublayer(parent, plan: pp.Plan, notes: list[str]):
    from pxr import Sdf

    node = parent.createNode("sublayer", _safe(plan.title))
    node.parm("num_files").set(len(plan.files))
    for i, f in enumerate(plan.files, 1):
        node.parm(f"filepath{i}").set(Path(f).as_posix())
    if plan.files:
        layer = Sdf.Layer.FindOrOpen(plan.files[0])
        if layer is not None and layer.HasStartTimeCode() and layer.HasEndTimeCode():
            fps = layer.framesPerSecond or layer.timeCodesPerSecond or 24
            hou.setFps(fps)
            hou.playbar.setFrameRange(layer.startTimeCode, layer.endTimeCode)
            hou.playbar.setPlaybackRange(layer.startTimeCode, layer.endTimeCode)
    notes.append(plan.note)
    return node, [node]


def _ensure_hda() -> None:
    """The loader from the suite this module belongs to, when this Houdini has none of that type (an older install
    on the package path)."""
    if hou.nodeType(hou.lopNodeTypeCategory(), config.HDA_TYPE) is not None:
        return
    lib = Path(__file__).resolve().parents[2] / "otls" / config.HDA_FILE
    if lib.is_file():
        try:
            hou.hda.installFile(lib.as_posix())
        except hou.OperationFailed:
            pass


def build(kind: str, path: str, parent=None) -> dict:
    """The test scene in ``parent`` (``/stage``) and its checks: {line, ok, note, display, plan}."""
    from apps.houdini.solaris_adapter import manual_update

    parent = parent or hou.node("/stage")
    plan = pp.plan(kind, path)
    notes: list[str] = []
    if plan.mode in ("asset", "shot"):
        _ensure_hda()
    if plan.mode in ("asset", "shot") and hou.nodeType(hou.lopNodeTypeCategory(), config.HDA_TYPE) is None:
        return {"line": pp.HDA_MISSING, "ok": False, "note": pp.HDA_MISSING, "display": None, "plan": plan}
    with manual_update():
        if plan.mode == "asset":
            display, nodes = _build_asset(parent, plan, notes)
        elif plan.mode == "shot":
            display, nodes = _build_shot(parent, plan, notes)
        else:
            display, nodes = _build_sublayer(parent, plan, notes)
    if display is not None:
        display.setDisplayFlag(True)
    try:
        hou.setFrame(hou.playbar.frameRange()[0])
    except Exception:
        pass
    stage = display.stage() if display is not None else None
    sf = stage_facts(stage, nodes)
    sf.notes.extend(n for n in notes if n)
    if plan.mode == "shot":
        sf.lookdevs = lookdev_facts(stage, nodes)
    if plan.mode == "shot":
        meta = logic.read_outputs(logic.anim_publish_dir(Path(plan.root), plan.shot) / plan.anim_version)
        files = [str(Path(plan.files[0]).parent / o.file) if plan.files else o.file for o in meta]
        files = [f for f in files if os.path.isfile(f)] or list(plan.files)
    else:
        files = list(plan.files)
    ff = [file_facts(f) for f in files]
    line, ok = pp.check_line(plan.title, kind, ff, sf)
    note = pp.note_text(plan.title, kind, ff, sf, "", pp.SAVE_HINT)
    _sticky(parent, note, display)
    return {"line": line, "ok": ok, "note": note, "display": display, "plan": plan,
            "files": [f.__dict__ for f in ff], "stage": sf.__dict__}


def _sticky(parent, text: str, near) -> None:
    try:
        old = parent.findStickyNote(NOTE_NAME)
        if old is not None:
            old.destroy()
        note = parent.createStickyNote(NOTE_NAME)
        note.setText(text)
        note.setTextSize(0.25)
        lines = text.count("\n") + 1
        note.setSize(hou.Vector2(9.0, 0.6 + lines * 0.32))
        if near is not None:
            note.setPosition(near.position() + hou.Vector2(2.5, -note.size()[1] + 1.0))
    except Exception:  # the note is a convenience; the status line carries the result
        pass


# --- the GUI process ----------------------------------------------------------------------------------------------

def _show(display) -> None:
    """Network editor and Scene Viewer on /stage, the stage framed."""
    stage_net = hou.node("/stage")
    for tab in hou.ui.paneTabs():
        try:
            if tab.type() == hou.paneTabType.NetworkEditor:
                tab.setPwd(stage_net)
            elif tab.type() == hou.paneTabType.SceneViewer:
                tab.setPwd(stage_net)
        except Exception:
            continue
    if display is not None:
        display.setSelected(True, clear_all_selected=True)
    for tab in hou.ui.paneTabs():
        try:
            if tab.type() == hou.paneTabType.SceneViewer:
                tab.curViewport().frameAll()
            elif tab.type() == hou.paneTabType.NetworkEditor:
                tab.frameSelection() if display is not None else tab.homeToNetwork()
        except Exception:
            continue


def _status(line: str, ok: bool) -> None:
    print(line, flush=True)
    try:
        hou.ui.setStatusMessage(line, hou.severityType.Message if ok else hou.severityType.Warning)
    except Exception:
        pass


def run(kind: str, path: str) -> dict:
    """Builds the test scene and says the result; the scene is named into %TEMP%, never saved."""
    folder = work_dir()
    folder.mkdir(parents=True, exist_ok=True)
    plan = pp.plan(kind, path)
    try:
        hou.hipFile.setName((folder / f"test_{_safe(plan.title)}.hip").as_posix())
    except Exception:
        pass
    try:
        result = build(kind, path)
    except Exception as exc:
        traceback.print_exc()
        result = {"line": f"MonoFX test, {plan.title}: the test scene failed ({exc}).", "ok": False, "display": None}
    _status(result["line"], result["ok"])
    report = os.environ.get(ENV_REPORT, "").strip()
    if report:  # automation (the add-on's checks): the result as JSON as well
        try:
            Path(report).write_text(json.dumps({"line": result["line"], "ok": result["ok"],
                                                "note": result.get("note", ""), "hip": hou.hipFile.path()},
                                               indent=2), encoding="utf-8")
        except OSError:
            pass
    if hou.isUIAvailable():
        try:
            _show(result.get("display"))
        except Exception:
            traceback.print_exc()
        _later(lambda: _status(result["line"], result["ok"]))  # after startup messages, which overwrite it
    return result


def _later(fn, ms: int = 2500) -> None:
    try:
        from PySide6 import QtCore  # type: ignore
    except ImportError:
        try:
            from PySide2 import QtCore  # type: ignore
        except ImportError:
            return
    QtCore.QTimer.singleShot(ms, fn)


def main() -> None:
    kind = os.environ.get(ENV_KIND, "").strip().lower()
    path = os.environ.get(ENV_PATH, "").strip()
    if kind not in ("model", "anim") or not path:
        _status(f"MonoFX test: nothing to open ({ENV_KIND}={kind!r}, {ENV_PATH}={path!r}).", False)
        return
    if not os.path.exists(path):
        _status(f"MonoFX test: {path} is not on disk.", False)
        return
    if hou.isUIAvailable():
        import hdefereval  # type: ignore

        hdefereval.executeDeferred(lambda: run(kind, path))  # once the desktop is up
    else:
        print(json.dumps({k: v for k, v in run(kind, path).items() if k in ("line", "ok")}))
