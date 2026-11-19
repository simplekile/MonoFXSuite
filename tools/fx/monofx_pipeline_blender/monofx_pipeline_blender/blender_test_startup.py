"""Blender startup script of the add-on's Test in Blender (``blender.exe --python blender_test_startup.py``).

Runs in a NEW Blender process, never in the artist's (the add-on does not import it): an empty file, the publish
imported with Blender's own USD importer (a model file, or every geo / camera file of an anim version with the
publish's fps and frame range), then the same checks as Test in Houdini (``monofx_pipeline_common.publish_checks``)
plus whether Blender brought every mesh in. One line on the status bar, the full list in the text block
"MonoFX test". The file is never saved; a save goes where the artist picks (the process runs in
%TEMP%/MonoFX/blender_test). What to open: ``MONOFX_TEST_KIND`` / ``MONOFX_TEST_PATH``.
"""

import json
import os
import re
import sys
import traceback
from pathlib import Path

import bpy

HERE = Path(__file__).resolve().parent
TEXT_NAME = "MonoFX test"
USD_EXTS = (".usd", ".usda", ".usdc")
SAVE_HINT = "This file is not saved; save it outside the project if you keep it (Monos would take it for a work file)."


def _common_on_path():
    for cand in [HERE.parents[d] / "packages" / "monofx_pipeline_common" / "src" for d in (2, 3, 4)
                 if len(HERE.parents) > d] + [HERE / "vendor"]:
        if (cand / "monofx_pipeline_common").is_dir():
            if str(cand) not in sys.path:
                sys.path.insert(0, str(cand))
            return


def _meta(folder):
    try:
        data = json.loads((folder / "publish_meta.json").read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def publish_files(kind, path):
    """The model file, or an anim version's geo and camera files (publish_meta.json order, else geo_* / cam_*)."""
    p = Path(path)
    if kind == "model":
        return [p]
    folder = p if p.is_dir() else p.parent
    outs = [o.get("file") for o in _meta(folder).get("outputs", []) if isinstance(o, dict)]
    files = [folder / f for f in outs if f and (folder / f).is_file()]
    if files:
        return files
    usd = sorted(f for f in folder.iterdir() if f.is_file() and f.suffix.lower() in USD_EXTS)
    return [f for f in usd if f.name.lower().startswith(("geo_", "cam_"))] or usd


def title(kind, path):
    parts = Path(path).parts
    low = [x.lower() for x in parts]
    ver = next((x for x in reversed(parts) if re.match(r"^[vV]\d+$", x)), "")
    if "01_assets" in low and low.index("01_assets") + 2 < len(parts):
        name = parts[low.index("01_assets") + 2]
    elif "02_shots" in low and low.index("02_shots") + 1 < len(parts):
        name = parts[low.index("02_shots") + 1]
    else:
        name = Path(path).stem
    return f"{name} {kind} {ver}".strip()


def _apply_timeline(folder, files):
    meta = _meta(folder)
    scene = bpy.context.scene
    try:
        fps = float(meta["fps"])
        first, last = (int(x) for x in meta["playback_range"])
    except (KeyError, TypeError, ValueError):
        from pxr import Sdf

        layer = Sdf.Layer.FindOrOpen(str(files[0])) if files else None
        if layer is None or not (layer.HasStartTimeCode() and layer.HasEndTimeCode()):
            return ""
        fps = layer.framesPerSecond or layer.timeCodesPerSecond or 24.0
        first, last = int(layer.startTimeCode), int(layer.endTimeCode)
    scene.render.fps = max(1, round(fps))
    scene.render.fps_base = scene.render.fps / fps
    scene.frame_start, scene.frame_end = first, last
    scene.frame_set(first)
    return f"Timeline {first}-{last} at {fps:g} fps."


def _window_context():
    """A window and its 3D view: an operator run from a timer has no window, and usd_import's poll needs one."""
    win = bpy.context.window_manager.windows[0]
    area = next((a for a in win.screen.areas if a.type == "VIEW_3D"), None)
    region = next((r for r in area.regions if r.type == "WINDOW"), None) if area else None
    return bpy.context.temp_override(window=win, area=area, region=region) if area else         bpy.context.temp_override(window=win)


def _import(files):
    """Each file through Blender's USD importer; (meshes Blender made per file, notes)."""
    made, notes = {}, []
    for f in files:
        before = set(bpy.data.objects)
        try:
            with _window_context():
                bpy.ops.wm.usd_import(filepath=str(f))
        except Exception as exc:
            notes.append(f"Blender could not import {f.name}: {str(exc).splitlines()[0][:160]}")
        new = [o for o in bpy.data.objects if o not in before]
        made[f.name] = sum(1 for o in new if o.type == "MESH")
    return made, notes


def run(kind, path):
    _common_on_path()
    from monofx_pipeline_common import publish_checks as pc
    from pxr import Usd

    files = publish_files(kind, path)
    name = title(kind, path)
    made, import_errors = _import(files)
    notes = []
    if kind == "anim":
        notes.append(_apply_timeline(Path(path) if Path(path).is_dir() else Path(path).parent, files))
    ff = [pc.file_facts(str(f)) for f in files]
    sf = pc.StageFacts(node_errors=list(import_errors))
    for f in files:
        try:
            pc.usd_stage_facts(Usd.Stage.Open(str(f)), sf)
        except Exception:
            pass
    for f, facts in zip(files, ff):
        got = made.get(f.name, 0)
        if facts.meshes and got < facts.meshes:
            sf.node_errors.append(f"Blender imported {got} of {facts.meshes} meshes of {f.name}")
    sf.notes.append(f"Blender imported {sum(made.values())} mesh objects.")
    sf.notes.extend(n for n in notes if n)
    line, ok = pc.check_line(name, kind, ff, sf)
    note = pc.note_text(name, kind, ff, sf, "", SAVE_HINT)
    text = bpy.data.texts.get(TEXT_NAME) or bpy.data.texts.new(TEXT_NAME)
    text.from_string(note)
    return line, ok, note


def _show(line):
    """The line on every window's status bar (stays until the next tool sets one) and the view framed."""
    for win in bpy.context.window_manager.windows:
        try:
            with bpy.context.temp_override(window=win):
                bpy.context.workspace.status_text_set(line)
        except Exception:
            pass
        for area in win.screen.areas:
            if area.type != "VIEW_3D":
                continue
            region = next((r for r in area.regions if r.type == "WINDOW"), None)
            try:
                with bpy.context.temp_override(window=win, area=area, region=region):
                    bpy.ops.view3d.view_all()
            except Exception:
                pass


def _new_file():
    with _window_context():
        bpy.ops.wm.read_homefile(use_empty=True)  # an empty file; the artist's preferences and add-ons stay
    bpy.app.timers.register(_start, first_interval=0.5)  # read_homefile replaces the screens: wait for them
    return None


def _start():
    kind = os.environ.get("MONOFX_TEST_KIND", "").strip().lower()
    path = os.environ.get("MONOFX_TEST_PATH", "").strip()
    if kind not in ("model", "anim") or not path or not os.path.exists(path):
        line, ok, note = f"MonoFX test: nothing to open ({kind!r}, {path!r}).", False, ""
    else:
        try:
            line, ok, note = run(kind, path)
        except Exception as exc:
            traceback.print_exc()
            line, ok, note = f"MonoFX test, {title(kind, path)}: the test file failed ({exc}).", False, ""
    print(line, flush=True)
    report = os.environ.get("MONOFX_TEST_REPORT", "").strip()
    if report:  # automation: the result as JSON as well
        try:
            Path(report).write_text(json.dumps({"line": line, "ok": ok, "note": note,
                                                "objects": len(bpy.data.objects),
                                                "fps": bpy.context.scene.render.fps,
                                                "frames": [bpy.context.scene.frame_start, bpy.context.scene.frame_end]},
                                               indent=2), encoding="utf-8")
        except OSError:
            pass
    bpy.app.timers.register(lambda: _show(line), first_interval=0.5)  # after the new file's UI is up
    return None


bpy.app.timers.register(_new_file, first_interval=0.5)
