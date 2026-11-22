"""Build the Mono Anim Loader LOP HDA (``mono_anim_loader::2.2``) from code into ``otls/mono_anim_loader.hdalc``.

hython tools/fx/anim_loader/build_hda.py [out.hdalc]

One node = one shot instance (or the camera). Geo: the branch's layers (lookdev, groom / cloth when read as
a Sublayer, anim) -> Graft Stages under ``/<mx_instance_name>`` on input 0 -> a new layer with the groom /
cloth value clips -> scale -> hide the hair driver. Camera: sublayered onto input 0 with 2.1's camera edits.
Spec docs/plans/anim_loader_v2_2.md, spikes S1/S2 in its section 6.
"""

from __future__ import annotations

import glob
import os
import sys

import hou

SUITE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if SUITE not in sys.path:
    sys.path.insert(0, SUITE)

from tools.fx.anim_loader import config  # noqa: E402

DEFAULT_OUT = os.path.join(SUITE, "otls", config.HDA_FILE)
INST = '`chs("../mx_instance_name")`'
# Where the instance sits: /<Prim Name>, or the stage root when Prim Name is off (config.P_USE_PRIM)
GRAFT_AT = '`ifs(ch("../mx_use_prim"), "/" + chs("../mx_instance_name"), "/")`'
ROOT_EXPR = '`ifs(ch("../mx_use_prim"), "/" + chs("../mx_instance_name"), "")`'
ROOT_CODE = config.ROOT_CODE

# Value clips authored after the graft (spike S2b): on /<instance><root> with clipPrimPath <root>, one clip set
# per task, no manifest (USD makes one). Reads only the HDA's hidden parms; never opens a file.
CLIP_CODE = '''hda = hou.pwd().parent()
stage = hou.pwd().editableStage()
from pxr import Usd
@ROOT@
for task in ("groom", "cloth"):
    if hda.evalParm("mx_%s_mode" % task) != "clip" or root is None:
        continue
    for token in hda.evalParm("mx_%s_roots" % task).split():
        # "src=dst": the clip reads src in the cache and sits on dst (groom: /Groom/<name>, outside Geo)
        src, _, dst = token.partition("=")
        prim = stage.OverridePrim(root + (dst or src))
        clips = Usd.ClipsAPI(prim)
        clips.SetClipPrimPath(src, task)
        clips.SetClipTemplateAssetPath(hda.parm("mx_%s_template" % task).unexpandedString(), task)
        clips.SetClipTemplateStartTime(hda.evalParm("mx_%s_first" % task), task)
        clips.SetClipTemplateEndTime(hda.evalParm("mx_%s_last" % task), task)
        clips.SetClipTemplateStride(1, task)
'''.replace("@ROOT@", ROOT_CODE)

# Groom outside Geo (the user's pick, 2026-11-17): the branch copies each groom curves prim of the cache to
# /Groom/<name> (mx_groom_roots "src=dst"), where lookdev binds hair. From the first frame when the cache has time
# samples (the clips after the graft give the motion); from the current frame's file when it has none ($F in
# mx_groom_topo, which makes this node time dependent). Spike S3: docs/plans/anim_loader_asset_source.md.
GROOM_TOPO_CODE = '''from pxr import Sdf
hda = hou.pwd().parent()
path = hou.pwd().evalParm("groom_file")
pairs = [t.partition("=") for t in hda.evalParm("mx_groom_roots").split()]
pairs = [(a, c) for a, b, c in pairs if b]
if path and pairs:
    src = Sdf.Layer.FindOrOpen(path)
    layer = hou.pwd().editableLayer()
    if src is not None:
        for a, c in pairs:
            parent = Sdf.Path(c).GetParentPath()
            Sdf.CreatePrimInLayer(layer, parent)
            spec = layer.GetPrimAtPath(parent)
            while spec is not None and spec.path != Sdf.Path.absoluteRootPath:
                spec.specifier = Sdf.SpecifierDef
                if not spec.typeName:
                    spec.typeName = "Xform"
                spec = layer.GetPrimAtPath(spec.path.GetParentPath())
            Sdf.CopySpec(src, a, layer, c)
        if hda.evalParm("@MODE@") == "clip":
            # The clips give every animated value: take the copied frame's own values off (time samples and the
            # default) so nothing in this layer can beat a clip. A Graft Stages after the loader (the shot layout's
            # graft_anim) flattens this copy and the clip metadata into one layer, where its first-frame samples
            # won and the groom stood still; a default in a stronger layer beats a clip as well. Values without
            # samples (counts, type, basis) are the topology and stay.
            def strip(spec):
                for attr in spec.attributes:
                    if layer.GetNumTimeSamplesForPath(attr.path):
                        for t in list(layer.ListTimeSamplesForPath(attr.path)):
                            layer.EraseTimeSample(attr.path, t)
                        attr.ClearDefaultValue()
                for child in spec.nameChildren:
                    strip(child)

            for a, c in pairs:
                spec = layer.GetPrimAtPath(c)
                if spec is not None:
                    strip(spec)
'''.replace("@MODE@", config.P_FX["groom"]["mode"])

# Right after the graft, on the graft's own flattened layer: the groom's animated values come off for real (a
# lookdev publish, Helen's, holds points and primvars on /Groom/<name> with a time sample, and widths as a default).
# With clips nothing under them may hold such a value: a Merge or a Graft Stages after the loader puts this layer and
# the clip metadata into one, where a sample (and a default) beats the clip: sh025_lighting_v004's groom stood still
# at the lookdev's value from merge_actors on. A value block does not do it: in one layer it beats the clip too (the
# groom lost its points). So: every time sample on the groom's prims, and the default of each attribute the cache
# animates, erased; an attribute the cache does not have at all keeps its value as a default (a lookdev-only primvar),
# counts, type, basis, bindings stay.
# The extent goes too, with clips or a $F sublayer (2026-11-22): the lookdev's is its rest pose (Helen's V009 authors
# one on /Groom/<name>, near the origin) and the cache authors none, so the groom's bounds stayed at the origin while
# its points moved with the body at (82, 31, 327): a camera framed on the bounds saw nothing. Without an extent USD
# and Hydra compute the bounds from the points. A cache with its own extent keeps it (from the clip / frame file).
GROOM_UNANIMATE_CODE = '''from pxr import Sdf
hda = hou.pwd().parent()
mode = hda.evalParm("@MODE@")
if mode in ("clip", "sublayer"):
    layer = hou.pwd().editableLayer()
    inst = hda.evalParm("mx_instance_name")
    _use = hda.parm("mx_use_prim")
    root = ("/" + inst if inst else None) if (_use is None or _use.eval()) else ""
    pairs = [t.partition("=") for t in hda.evalParm("mx_groom_roots").split()]
    pairs = [(a, c) for a, b, c in pairs if b]
    cache = Sdf.Layer.FindOrOpen(hda.evalParm("@TOPO@")) if hda.evalParm("@TOPO@") else None

    def cache_attrs(path):
        """(every attribute the cache has, the ones it animates) on a curves prim of its frame file"""
        spec = cache.GetPrimAtPath(path) if cache is not None else None
        attrs = list(spec.attributes) if spec else []
        return {x.name for x in attrs}, {x.name for x in attrs if cache.GetNumTimeSamplesForPath(x.path)}

    def drop_extent(spec, has):
        attr = spec.attributes["extent"] if "extent" in spec.attributes else None
        if attr is not None and (mode == "clip" or "extent" not in has):
            for t in list(layer.ListTimeSamplesForPath(attr.path)):
                layer.EraseTimeSample(attr.path, t)
            attr.ClearDefaultValue()
        for child in spec.nameChildren:
            drop_extent(child, has)

    def unanimate(spec, has, animated):
        for attr in spec.attributes:
            if attr.name == "extent":
                continue  # drop_extent's
            samples = list(layer.ListTimeSamplesForPath(attr.path))
            keep = layer.QueryTimeSample(attr.path, samples[0]) if samples and attr.name not in has else None
            for t in samples:
                layer.EraseTimeSample(attr.path, t)
            if keep is not None:  # the lookdev's own (a primvar the cache lacks): kept as a value, not dropped
                attr.default = keep
            elif samples or attr.name in animated:
                attr.ClearDefaultValue()
        for child in spec.nameChildren:
            unanimate(child, has, animated)

    for a, c in pairs:
        spec = layer.GetPrimAtPath(root + c) if root is not None else None
        if spec is not None:
            has, animated = cache_attrs(a)
            drop_extent(spec, has)
            if mode == "clip":
                unanimate(spec, has, animated)
'''.replace("@MODE@", config.P_FX["groom"]["mode"]).replace("@TOPO@", config.P_GROOM_TOPO)

# Heavy parts render only (the user's call, 2026-11-17: Helen's lookdev pulls 956 EXR UDIM tiles, 2.1 GB, and the
# viewport took 27 GB and hung). Houdini GL reads preview / all-purpose bindings and default / proxy purpose; Karma
# reads full bindings and render purpose. So, unless "Show in viewport" is on: every material binding of the
# instance moves to material:binding:full (all-purpose left empty), and groom curves get purpose render.
# Meshes that author no subdivisionScheme get "none": Blender's anim publish writes none, USD then reads
# catmullClark, and Houdini GL subdivided whole shots (sh025: >45 GB, crash in GR_OSDSubdSurfaceVK). An authored
# scheme stays.
PURPOSE_CODE = '''hda = hou.pwd().parent()
stage = hou.pwd().editableStage()
from pxr import Usd, UsdGeom, UsdShade
@ROOT@
vp = hda.evalParm("mx_viewport")
look_vp, groom_vp = vp & 1, vp & 2
if root is not None:
    # Subdivision per mesh: shot rule > lookdev > anim > none (adapter.author_subd, logic.subd_plan)
    from apps.houdini import anim_loader_adapter
    anim_loader_adapter.author_subd(hda, stage)
    # Groom curves: Karma's curve basis / width scale / style from the shot's rules (adapter.author_curves)
    anim_loader_adapter.author_curves(hda, stage)
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
'''.replace("@ROOT@", ROOT_CODE)

# What the shot shows of each prim (hidden / render only / viewport only / both): last, after Hide Prims and the
# groom's render purpose, so a rule wins over both (adapter.author_show, logic.parse_show_rules)
SHOW_CODE = '''hda = hou.pwd().parent()
stage = hou.pwd().editableStage()
from apps.houdini import anim_loader_adapter
anim_loader_adapter.author_show(hda, stage)
'''

# Time codes per second of the branch = the anim / geometry file's, the last layer slot set (adapter: lookdev, fx,
# then the anim). A Sublayer LOP takes the strongest layer's, the lookdev's: V001 of veh_Spaceship authors none, so
# the branch read USD's fallback 24 and a 30 fps anim was squeezed into 0-24 (sh002 v004). 0 = the file says
# nothing: Houdini's own rule. Python with hou and pxr only, so a baked loader keeps it.
BRANCH_FPS_EXPR = '''from pxr import Sdf
node = hou.pwd().parent()
files = [node.evalParm(n) for n in (%s) if node.parm(n) is not None]
files = [f for f in files if f]
layer = Sdf.Layer.FindOrOpen(files[-1]) if files else None
if layer is None:
    return 0
if layer.HasTimeCodesPerSecond():
    return layer.timeCodesPerSecond
return layer.framesPerSecond if layer.HasFramesPerSecond() else 0
''' % ", ".join(repr(n) for n in config.P_LAYERS)

PYTHON_MODULE = "from apps.houdini.anim_loader_adapter import *\n"
ON_CREATED = "from apps.houdini import anim_loader_adapter\nanim_loader_adapter.on_created(kwargs['node'])\n"
ON_LOADED = "from apps.houdini import anim_loader_adapter\nanim_loader_adapter.on_loaded(kwargs['node'])\n"


def _node(parent, kind, name, inputs=(), **parms):
    n = parent.createNode(kind, name)
    for i, src in enumerate(inputs):
        if src is not None:
            n.setInput(i, src)
    for k, v in parms.items():
        p = n.parm(k)
        if p is None:
            raise KeyError(f"{kind}.{k}")
        if isinstance(v, str) and v.startswith("="):
            p.setExpression(v[1:], hou.exprLanguage.Hscript)
        else:
            p.set(v)
    return n


# Camera aperture (config.P_CAM_APERTURE): nothing on the publish's own (default); else the loader's width in mm and
# the height from the publish camera's own ratio, or from the loader's ratio. Only the cameras of the loaded file:
# input 0's cameras pass through untouched. USD lens values are tenths of a scene unit.
CAM_APERTURE_CODE = '''hda = hou.pwd().parent()
mode = hda.parm("@MODE@")
mode = mode.evalAsString() if mode is not None else "@PUBLISH@"  # a menu: its token, not its index
path = hda.evalParm("@PATH@")
if mode != "@PUBLISH@" and path:
    from pxr import Sdf, Usd, UsdGeom
    src = Sdf.Layer.FindOrOpen(path)
    stage = hou.pwd().editableStage()
    cams = []
    if src is not None:
        src.Traverse(Sdf.Path.absoluteRootPath, lambda p: cams.append(p) if p.IsPrimPath()
                     and src.GetPrimAtPath(p).typeName == "Camera" else None)
    tenths = 1.0 / (100.0 * UsdGeom.GetStageMetersPerUnit(stage))
    width = hda.evalParm("horizontalAperture") * tenths
    for p in cams:
        prim = stage.GetPrimAtPath(p)
        if not prim or not prim.IsA(UsdGeom.Camera):
            continue
        cam = UsdGeom.Camera(prim)
        if mode == "@RATIO@":
            rx, ry = hda.evalParm("aspectratiox"), hda.evalParm("aspectratioy")
        else:
            t = Usd.TimeCode.EarliestTime()
            rx, ry = cam.GetHorizontalApertureAttr().Get(t), cam.GetVerticalApertureAttr().Get(t)
        cam.GetHorizontalApertureAttr().Set(width)
        if rx and ry and rx > 0 and ry > 0:
            cam.GetVerticalApertureAttr().Set(width * ry / rx)
'''.replace("@MODE@", config.P_CAM_APERTURE).replace("@PATH@", config.P_ANIM_PATH).replace(
    "@PUBLISH@", config.CAM_APERTURE_PUBLISH).replace("@RATIO@", config.CAM_APERTURE_RATIO)


def build_network(sub) -> None:
    src = sub.indirectInputs()[0]
    layers = _node(sub, "sublayer", "branch_layers", num_files=len(config.P_LAYERS))
    for i, name in enumerate(config.P_LAYERS, start=1):
        layers.parm(f"filepath{i}").set(f'`chs("../{name}")`')
    fps = _node(sub, "configurelayer", "branch_fps", (layers,))
    fps.parm("timepersecond").setExpression(BRANCH_FPS_EXPR, hou.exprLanguage.Python)
    fps.parm("settimepersecond").setExpression('ch("timepersecond") > 0', hou.exprLanguage.Hscript)
    topo = _node(sub, "pythonscript", "groom_topology", (fps,), python=GROOM_TOPO_CODE)
    ptg = topo.parmTemplateGroup()
    ptg.append(hou.StringParmTemplate("groom_file", "Groom File", 1))
    topo.setParmTemplateGroup(ptg)
    topo.parm("groom_file").setExpression(f'chs("../{config.P_GROOM_TOPO}")', hou.exprLanguage.Hscript)
    graft = _node(sub, "graftstages", "graft", (src, topo), primpath=GRAFT_AT, destpath="")
    unanimate = _node(sub, "pythonscript", "groom_unanimate", (graft,), python=GROOM_UNANIMATE_CODE)
    new_layer = _node(sub, "configurelayer", "fx_layer", (unanimate,), startnewlayer=1)
    clips = _node(sub, "pythonscript", "fx_clips", (new_layer,), python=CLIP_CODE)
    purpose = _node(sub, "pythonscript", "render_only", (clips,), python=PURPOSE_CODE)
    # Prim Name off: no /<inst> to scale, so the branch's own root prims are scaled before the graft (input 0's
    # prims pass through and are not the loader's); on: the instance prim after it, as before
    branch_scale = _node(sub, "xform", "branch_scale", (topo,), primpattern="/*",
                         scale='=if(ch("../mx_use_prim"), 1, ch("../scale"))')
    graft.setInput(1, branch_scale)
    geo_scale = _node(sub, "xform", "geo_scale", (purpose,), primpattern=ROOT_EXPR,
                      scale='=if(ch("../mx_use_prim"), ch("../scale"), 1)')
    hide = _node(sub, "configureprimitive", "hide_driver", (geo_scale,),
                 primpattern=f'{ROOT_EXPR}/`chs("../mx_hide_pattern")`', visibility="invisible")
    hide.parm("setvisibility").setExpression('ch("../mx_hide_enable")', hou.exprLanguage.Hscript)

    # camera: 2.1's chain (cam_Loader -> transform1 -> camera_edit1 -> transform4), on top of input 0
    cam = _node(sub, "sublayer", "cam_layer", (src,), filepath1=f'`chs("../{config.P_ANIM_PATH}")`')
    cam_scale = _node(sub, "xform", "cam_scale", (cam,), usexformcommonapi=0, scale='=ch("../scale2")')
    # before camera_edit: cam_x100 works on its input's last modified prims, which a Camera LOP sets to the cameras
    # and a Python LOP does not (the camera lost its x100 scale with cam_aperture last)
    aperture = _node(sub, "pythonscript", "cam_aperture", (cam_scale,), python=CAM_APERTURE_CODE)
    edit = _node(sub, "camera", "camera_edit", (aperture,), primpattern="%type:Camera", createprims=0)
    # clipping and guide scale only: the aperture is cam_aperture's (2.1 set the width alone here, 36 mm by default,
    # and left the height, so a 16:9 publish came out 3.05:1); nothing else is touched (transform, lens, focus)
    keep = ("clippingRange", "houdiniguidescale")
    for p in edit.parms():
        if p.name().endswith("_control") and not any(k in p.name() for k in keep):
            try:
                p.set("none")
            except hou.OperationFailed:
                pass
    for name in ("clippingRange1", "clippingRange2", "xn__houdiniguidescale_s3a"):
        edit.parm(name).setExpression(f'ch("../{name}")', hou.exprLanguage.Hscript)
    cam_x100 = _node(sub, "xform", "cam_x100", (edit,), xforminworldspace=0, usexformcommonapi=0, scale=100.0)

    show = _node(sub, "pythonscript", "show_rules", (hide,), python=SHOW_CODE)
    switch = _node(sub, "switch", "geo_or_cam", (show, cam_x100))
    switch.parm("input").setExpression(f'ch("../{config.P_GEO_CAM}")', hou.exprLanguage.Hscript)
    out = sub.node("output0") or sub.createNode("output", "output0")  # a LOP subnet comes with output0
    out.setInput(0, switch)
    out.setDisplayFlag(True)
    sub.layoutChildren()


def _parm_templates() -> hou.ParmTemplateGroup:
    """Layout D (the user's pick, 2026-11-17, checked in the Houdini 22 GUI at 420-760 px): Manager / Refresh on one row, a
    one-line status only when there is something to act on, Source / Parts / Geometry or Camera as plain groups,
    a checkbox in the label column per part, the status in the version menus' labels, Advanced closed. Joined rows
    only for checkbox + field: wider joins overflow a docked pane. Names of 2.1 are kept (Upgrade keeps values)."""
    T = hou
    g = hou.ParmTemplateGroup()
    cb = "hou.phm().cb_parm_changed(kwargs)"
    geo_only = f"{{ {config.P_GEO_CAM} == 1 }}"
    cam_only = f"{{ {config.P_GEO_CAM} == 0 }}"
    is_asset = f'{{ {config.P_SOURCE} == "{config.SOURCE_ASSET}" }}'
    is_shot = f'{{ {config.P_SOURCE} != "{config.SOURCE_ASSET}" }}'

    def s(name, label, default="", menu=None, callback=True, **kw):
        t = T.StringParmTemplate(name, label, 1, default_value=(default,), **kw)
        if menu:
            t.setItemGeneratorScript(menu)
            t.setItemGeneratorScriptLanguage(T.scriptLanguage.Python)
            t.setMenuType(T.menuType.Normal)  # the field shows the item's label: version + status
        if callback:
            t.setScriptCallback(cb)
            t.setScriptCallbackLanguage(T.scriptLanguage.Python)
        return t

    def toggle(name, label, default=True, callback=True):
        t = T.ToggleParmTemplate(name, label, default_value=default)
        if callback:
            t.setScriptCallback(cb)
            t.setScriptCallbackLanguage(T.scriptLanguage.Python)
        return t

    def button(name, label, script, help_text):
        t = T.ButtonParmTemplate(name, label)
        t.setScriptCallback(script)
        t.setScriptCallbackLanguage(T.scriptLanguage.Python)
        t.setHelp(help_text)
        return t

    def read_only(t):
        t.setConditional(T.parmCondType.DisableWhen, "{ 1 == 1 }")
        return t

    def hidden(t):
        t.hide(True)
        return t

    manager = button("mx_manager", "Manager", "hou.phm().cb_open_manager(kwargs)",
                     "Every loader of the shot: versions, update, load shot, subdivision.")
    manager.setJoinWithNext(True)  # two buttons fit a 420 px pane; Timeline sits with the anim it reads
    g.append(manager)
    refresh = button("mx_refresh", "Refresh", "hou.phm().cb_refresh(kwargs)",
                     "Read the publish folders again. Never changes a version.")
    refresh.setJoinWithNext(True)
    g.append(refresh)
    g.append(button("mx_reload", "Reload", "hou.phm().cb_reload(kwargs)",
                    "Read every file this loader uses again from disk (a publish written again into the same "
                    "version). Never changes a version."))
    # Open Folder (the user's ask, 2026-11-20): a toggle strip, one button per part, set back to 0 by its callback so
    # every click opens (a Normal strip does not call back when the same button is clicked again)
    words = {"anim": "Geo", "lookdev": "Lookdev", "groom": "Groom", "cloth": "Cloth"}
    open_folder = T.MenuParmTemplate(config.P_OPEN_FOLDER, "Open Folder", tuple(config.OPEN_FOLDER_BITS),
                                     tuple(words[p] for p in config.OPEN_FOLDER_BITS), default_value=0,
                                     is_button_strip=True, menu_type=T.menuType.StringToggle)
    open_folder.setScriptCallback("hou.phm().cb_open_folder(kwargs)")
    open_folder.setScriptCallbackLanguage(T.scriptLanguage.Python)
    open_folder.setHelp("The publish folder of the version on the node, in Explorer: Geo (the anim, or the model "
                        "for Source Asset), Lookdev, Groom, Cloth.")
    g.append(open_folder)
    status = read_only(T.StringParmTemplate(config.P_STATUS, "Status", 1))
    status.setConditional(T.parmCondType.HideWhen, '{ %s == "" }' % config.P_STATUS)
    status.setHelp("What needs you: a missing file, an unknown asset, a note. Newer versions show in the menus.")
    g.append(status)

    src = T.FolderParmTemplate("f_source", "Source", folder_type=T.folderType.Simple)
    source = s(config.P_SOURCE, "Source", default=config.SOURCE_SHOT,
               menu_items=(config.SOURCE_SHOT, config.SOURCE_ASSET), menu_labels=("Shot", "Asset"),
               menu_type=T.menuType.Normal)
    source.setHelp("Shot: the anim of a shot. Asset: the asset's own UV model, groom and lookdev (grooming, "
                   "lookdev). Same prim paths; switching back keeps the other's settings.")
    src.addParmTemplate(source)

    def shot_only(t):
        t.setConditional(T.parmCondType.HideWhen, is_asset)
        return t

    def asset_only(t):
        t.setConditional(T.parmCondType.HideWhen, is_shot)
        return t

    src.addParmTemplate(shot_only(s(config.P_SHOT, "Shot", menu="hou.phm().menu_shots(hou.pwd())")))
    src.addParmTemplate(shot_only(s(config.P_ANIM_VERSION, "Anim Version",
                                    menu="hou.phm().menu_anim_versions(hou.pwd())")))
    src.addParmTemplate(shot_only(s(config.P_ANIM_FILE, "Anim File", menu="hou.phm().menu_anim_files(hou.pwd())")))
    src.addParmTemplate(shot_only(button("apply_mx_timeline", "Apply Timeline", "hou.phm().cb_apply_timeline(kwargs)",
                                         "Frame range and fps of the scene from the anim publish.")))
    group = s(config.P_ASSET_GROUP, "Asset Type", menu="hou.phm().menu_asset_groups(hou.pwd())", callback=False)
    group.setHelp("Shortens the Asset menu: one folder of 01_assets (Characters, Props...).")
    group.setConditional(T.parmCondType.HideWhen, is_shot)
    src.addParmTemplate(group)
    asset = s(config.P_ASSET, "Asset", menu="hou.phm().menu_assets(hou.pwd())")
    asset.setHelp("Source Asset: the assets of the type above that have a UV publish.")
    asset.setConditional(T.parmCondType.HideWhen, f'{{ {config.P_GEO_CAM} == 1 {config.P_SOURCE} != "{config.SOURCE_ASSET}" }}')
    src.addParmTemplate(asset)
    model_v = asset_only(s(config.P_MODEL_VERSION, "Model Version", menu="hou.phm().menu_model_versions(hou.pwd())"))
    model_v.setHelp("UV publish of the asset (01_modelling/03_uv/publish).")
    src.addParmTemplate(model_v)
    model_f = asset_only(s(config.P_MODEL_FILE, "Model File", menu="hou.phm().menu_model_files(hou.pwd())"))
    model_f.setHelp("A version may hold several files; the standard <asset>_uv_publish.usd is picked first.")
    src.addParmTemplate(model_f)
    # The checkbox sits in the label column, as the parts' (the user's ask, 2026-11-20): on = /<name>/Geo/... (a
    # shot's default), off = the publish's own root prims (Source Asset's default). Default on: a scene saved before
    # the checkbox existed keeps its graft.
    use = toggle(config.P_USE_PRIM, "Prim Name", default=True, callback=False)
    use.hideLabel(True)
    use.setJoinWithNext(True)
    use.setHelp("On: the instance under /<Prim Name> (several instances, a shot). Off: the publish's own root "
                "prims (/Geo, /Groom), as published: an asset's lookdev or grooming scene.")
    use.setConditional(T.parmCondType.HideWhen, geo_only)
    src.addParmTemplate(use)
    inst = s(config.P_INSTANCE, "Prim Name")
    inst.setHelp("The prim the instance is grafted under: /<name>/Geo/...")
    inst.setConditional(T.parmCondType.HideWhen, geo_only)
    inst.setConditional(T.parmCondType.DisableWhen, f"{{ {config.P_USE_PRIM} == 0 }}")
    src.addParmTemplate(inst)
    g.append(src)

    parts = T.FolderParmTemplate("f_parts", "Parts", folder_type=T.folderType.Simple)
    parts.setConditional(T.parmCondType.HideWhen, geo_only)
    for part, label in (("lookdev", "Lookdev"), ("groom", "Groom"), ("cloth", "Cloth")):
        on = toggle(config.P_ENABLE[part], label)
        on.hideLabel(True)
        on.setJoinWithNext(True)  # the checkbox sits in the label column
        ver = s(config.P_VERSION[part], label, menu=f'hou.phm().menu_versions(hou.pwd(), "{part}")')
        ver.setConditional(T.parmCondType.DisableWhen, f"{{ {config.P_ENABLE[part]} == 0 }}")
        if part == "cloth":  # a shot cache: nothing for Source Asset
            on.setConditional(T.parmCondType.HideWhen, is_asset)
            ver.setConditional(T.parmCondType.HideWhen, is_asset)
        parts.addParmTemplate(on)
        parts.addParmTemplate(ver)
    vp_parts = tuple(config.VIEWPORT_BITS)
    vp = T.MenuParmTemplate(config.P_VIEWPORT, "Show in Viewport", vp_parts, tuple(p.title() for p in vp_parts),
                            default_value=sum(config.VIEWPORT_BITS.values()), is_button_strip=True,
                            menu_type=T.menuType.StringToggle)
    vp.setHelp("Off: loaded for render only (Karma), for a lighter viewport.")
    parts.addParmTemplate(vp)
    g.append(parts)

    geo = T.FolderParmTemplate("f_geo", "Geometry", folder_type=T.folderType.Simple)
    geo.setConditional(T.parmCondType.HideWhen, geo_only)
    geo.addParmTemplate(T.FloatParmTemplate("scale", "Uniform Scale", 1, default_value=(1.0,), min=0, max=10))
    # Hide Prims is off the pane (the user's ask, 2026-11-19): the inspector's eye shows and hides any prim now. The
    # parms stay, hidden, so the hair driver is still hidden by default and scenes keep what they had; the eye on
    # HairDriver_grp shows it.
    hide_on = T.ToggleParmTemplate("mx_hide_enable", "Hide", default_value=True)
    hide_on.hide(True)
    hide = T.StringParmTemplate("mx_hide_pattern", "Hide Prims", 1, default_value=("Geo/Groom_grp/HairDriver_grp",))
    hide.hide(True)
    geo.addParmTemplate(hide_on)
    geo.addParmTemplate(hide)
    g.append(geo)

    cam = T.FolderParmTemplate("f_cam", "Camera", folder_type=T.folderType.Simple)
    cam.setConditional(T.parmCondType.HideWhen, cam_only)
    # The publish's aperture by default: Blender writes its camera's real sensor (sh011: 20.955 x 11.787 mm, 16:9)
    ap = config.P_CAM_APERTURE
    cam.addParmTemplate(T.MenuParmTemplate(
        ap, "Aperture", (config.CAM_APERTURE_PUBLISH, config.CAM_APERTURE_WIDTH, config.CAM_APERTURE_RATIO),
        ("Publish's aperture", "Set width, keep the publish's ratio", "Set width and ratio"), default_value=0,
        help="The publish's camera as Blender wrote it, or a sensor width in mm with the height from the publish's "
             "ratio or from Aspect Ratio."))
    width = T.FloatParmTemplate("horizontalAperture", "Horizontal Aperture", 1, default_value=(36.0,), min=1, max=100)
    width.setConditional(T.parmCondType.HideWhen, f'{{ {ap} == "{config.CAM_APERTURE_PUBLISH}" }}')
    cam.addParmTemplate(width)
    ratio = T.FloatParmTemplate("aspectratio", "Aspect Ratio", 2, default_value=(16.0, 9.0),
                                naming_scheme=T.parmNamingScheme.XYZW)
    ratio.setConditional(T.parmCondType.HideWhen, f'{{ {ap} != "{config.CAM_APERTURE_RATIO}" }}')
    cam.addParmTemplate(ratio)
    # Base1 names (clippingRange1 / 2), as in 2.1 and as the inner camera reads them; the default XYZW named them
    # clippingRangex / y and the clipping never reached the camera
    cam.addParmTemplate(T.FloatParmTemplate("clippingRange", "Clipping Range", 2, default_value=(0.0001, 1e6),
                                            naming_scheme=T.parmNamingScheme.Base1))
    cam.addParmTemplate(T.FloatParmTemplate("scale2", "Uniform Scale", 1, default_value=(1.0,), min=0, max=10))
    cam.addParmTemplate(T.FloatParmTemplate("xn__houdiniguidescale_s3a", "Guide Scale", 1,
                                            default_value=(1.0,), min=0, max=10))
    g.append(cam)

    adv = T.FolderParmTemplate("f_advanced", "Advanced", folder_type=T.folderType.Collapsible)
    adv.addParmTemplate(s(config.P_ROOT, "Project Root", string_type=T.stringParmType.FileReference,
                          file_type=T.fileType.Directory))
    anim_path = read_only(T.StringParmTemplate(config.P_ANIM_PATH, "Anim Path", 1))
    anim_path.setConditional(T.parmCondType.HideWhen, is_asset)
    adv.addParmTemplate(anim_path)
    model_path = read_only(T.StringParmTemplate(config.P_MODEL_PATH, "Model Path", 1))
    model_path.setConditional(T.parmCondType.HideWhen, is_shot)
    adv.addParmTemplate(model_path)
    for part in ("lookdev", "groom", "cloth"):
        p = read_only(T.StringParmTemplate(config.P_PATH[part], f"{part.title()} Path", 1))
        p.setConditional(T.parmCondType.HideWhen, geo_only if part != "cloth" else
                         f'{{ {config.P_GEO_CAM} == 1 }} {{ {config.P_SOURCE} == "{config.SOURCE_ASSET}" }}')
        adv.addParmTemplate(p)
    g.append(adv)

    for t in (
        T.IntParmTemplate(config.P_GEO_CAM, "Geo / Cam", 1, default_value=(0,)),
        T.ToggleParmTemplate("LOP_scale", "LOP scale (2.1)", default_value=True),
        T.StringParmTemplate("mx_anim_publish_parent", "Anim Publish Folder (2.1)", 1),
        T.StringParmTemplate("mx_groom_asset", "Groom Asset (2.1)", 1),
        T.StringParmTemplate("mx_cloth_asset", "Cloth Asset (2.1)", 1),
        T.StringParmTemplate(config.P_SUBD_RULES, "Subdivision Rules", 1),
        T.StringParmTemplate(config.P_CURVE_RULES, "Curve Rules", 1),
        T.StringParmTemplate(config.P_SHOW_RULES, "Show Rules", 1),
        T.StringParmTemplate(config.P_GROOM_TOPO, "Groom Topology File", 1),
        *[T.StringParmTemplate(n, n, 1) for n in config.P_LAYERS],
        *[T.StringParmTemplate(k, k, 1) for task in config.P_FX.values() for k in
          (task["mode"], task["template"], task["roots"])],
        *[T.IntParmTemplate(k, k, 1) for task in config.P_FX.values() for k in (task["first"], task["last"])],
    ):
        g.append(hidden(t))
    return g


TAB_TOOL = """<?xml version="1.0" encoding="UTF-8"?>
<shelfDocument>
  <tool name="$HDA_DEFAULT_TOOL" label="$HDA_LABEL" icon="$HDA_ICON">
    <toolMenuContext name="viewer"><contextNetType>LOP</contextNetType></toolMenuContext>
    <toolMenuContext name="network"><contextOpType>$HDA_TABLE_AND_NAME</contextOpType></toolMenuContext>
    <toolSubmenu>MonoFX</toolSubmenu>
    <script scriptType="python"><![CDATA[import loptoolutils
loptoolutils.genericTool(kwargs, '$HDA_NAME', '%s')]]></script>
  </tool>
</shelfDocument>
""" % config.HDA_NODE_NAME


def build_all(otls_dir: str = os.path.dirname(DEFAULT_OUT)) -> list[str]:
    """MonoFX Loader, and the same node as Anim Loader 2.2 for scenes saved with it (hidden from Tab)."""
    return [build(os.path.join(otls_dir, config.HDA_FILE)),
            build(os.path.join(otls_dir, config.OLD_FILE), config.OLD_TYPE, "Mono Anim Loader 2.2 (old)", "2.2")]


def build(out_path: str = DEFAULT_OUT, type_name: str = config.HDA_TYPE, label: str = config.HDA_LABEL,
          version: str = "1.0") -> str:
    out_path = os.path.abspath(out_path).replace("\\", "/")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    backup_dir = os.path.join(os.path.dirname(out_path), "backup")
    had_backups = set(glob.glob(os.path.join(backup_dir, "*")))
    if os.path.exists(out_path):
        hou.hda.uninstallFile(out_path)
        os.remove(out_path)
    net = hou.node("/stage")
    sub = net.createNode("subnet", "mono_anim_loader_build")
    build_network(sub)
    hda = sub.createDigitalAsset(
        name=type_name, hda_file_name=out_path, description=label, min_num_inputs=0,
        max_num_inputs=1, version=version, ignore_external_references=True, change_node_type=True,
        create_backup=False)
    d = hda.type().definition()
    d.setParmTemplateGroup(_parm_templates())
    d.setIcon("LOP_valueclip")
    d.setComment(f"{label}, built by tools/fx/anim_loader/build_hda.py")
    if type_name == config.HDA_TYPE:
        d.addSection("Tools.shelf", TAB_TOOL)
    d.addSection("PythonModule", PYTHON_MODULE)
    d.setExtraFileOption("PythonModule/IsPython", True)
    d.addSection("OnCreated", ON_CREATED)
    d.setExtraFileOption("OnCreated/IsPython", True)
    d.addSection("OnLoaded", ON_LOADED)
    d.setExtraFileOption("OnLoaded/IsPython", True)
    d.save(out_path, hda, create_backup=False)
    hda.destroy()
    for f in set(glob.glob(os.path.join(backup_dir, "*"))) - had_backups:
        os.remove(f)
    if os.path.isdir(backup_dir) and not os.listdir(backup_dir):
        os.rmdir(backup_dir)
    return out_path


if __name__ == "__main__":
    if len(sys.argv) > 1:
        print("built", build(sys.argv[1]))
    else:
        for path in build_all():
            print("built", path)
