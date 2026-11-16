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

DEFAULT_OUT = os.path.join(SUITE, "otls", "mono_anim_loader.hdalc")
INST = '`chs("../mx_instance_name")`'

# Value clips authored after the graft (spike S2b): on /<instance><root> with clipPrimPath <root>, one clip set
# per task, no manifest (USD makes one). Reads only the HDA's hidden parms; never opens a file.
CLIP_CODE = '''hda = hou.pwd().parent()
stage = hou.pwd().editableStage()
from pxr import Usd
inst = hda.evalParm("mx_instance_name")
for task in ("groom", "cloth"):
    if hda.evalParm("mx_%s_mode" % task) != "clip" or not inst:
        continue
    for root in hda.evalParm("mx_%s_roots" % task).split():
        prim = stage.OverridePrim("/" + inst + root)
        clips = Usd.ClipsAPI(prim)
        clips.SetClipPrimPath(root, task)
        clips.SetClipTemplateAssetPath(hda.parm("mx_%s_template" % task).unexpandedString(), task)
        clips.SetClipTemplateStartTime(hda.evalParm("mx_%s_first" % task), task)
        clips.SetClipTemplateEndTime(hda.evalParm("mx_%s_last" % task), task)
        clips.SetClipTemplateStride(1, task)
'''

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
inst = hda.evalParm("mx_instance_name")
root = stage.GetPrimAtPath("/" + inst) if inst else None
look_vp = hda.evalParm("mx_lookdev_viewport")
groom_vp = hda.evalParm("mx_groom_viewport")
if root:
    # Subdivision per mesh: shot rule > lookdev > anim > none (adapter.author_subd, logic.subd_plan)
    from apps.houdini import anim_loader_adapter
    anim_loader_adapter.author_subd(hda, stage)
    for prim in Usd.PrimRange(root):
        if not look_vp:
            rel = prim.GetRelationship("material:binding")
            targets = rel.GetTargets() if rel else []
            if targets:
                prim.CreateRelationship("material:binding:full", False).SetTargets(targets)
                rel.SetTargets([])
        if not groom_vp and prim.IsA(UsdGeom.BasisCurves):
            UsdGeom.Imageable(prim).CreatePurposeAttr().Set(UsdGeom.Tokens.render)
'''

PYTHON_MODULE = "from apps.houdini.anim_loader_adapter import *\n"
ON_CREATED = "from apps.houdini import anim_loader_adapter\nanim_loader_adapter.on_created(kwargs['node'])\n"


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


def build_network(sub) -> None:
    src = sub.indirectInputs()[0]
    layers = _node(sub, "sublayer", "branch_layers", num_files=len(config.P_LAYERS))
    for i, name in enumerate(config.P_LAYERS, start=1):
        layers.parm(f"filepath{i}").set(f'`chs("../{name}")`')
    graft = _node(sub, "graftstages", "graft", (src, layers), primpath="/" + INST, destpath="")
    new_layer = _node(sub, "configurelayer", "fx_layer", (graft,), startnewlayer=1)
    clips = _node(sub, "pythonscript", "fx_clips", (new_layer,), python=CLIP_CODE)
    purpose = _node(sub, "pythonscript", "render_only", (clips,), python=PURPOSE_CODE)
    geo_scale = _node(sub, "xform", "geo_scale", (purpose,), primpattern="/" + INST, scale='=ch("../scale")')
    hide = _node(sub, "configureprimitive", "hide_driver", (geo_scale,),
                 primpattern=f'/{INST}/`chs("../mx_hide_pattern")`', visibility="invisible")
    hide.parm("setvisibility").setExpression('ch("../mx_hide_enable")', hou.exprLanguage.Hscript)

    # camera: 2.1's chain (cam_Loader -> transform1 -> camera_edit1 -> transform4), on top of input 0
    cam = _node(sub, "sublayer", "cam_layer", (src,), filepath1=f'`chs("../{config.P_ANIM_PATH}")`')
    cam_scale = _node(sub, "xform", "cam_scale", (cam,), usexformcommonapi=0, scale='=ch("../scale2")')
    edit = _node(sub, "camera", "camera_edit", (cam_scale,), primpattern="%type:Camera", createprims=0)
    keep = ("horizontalAperture", "clippingRange", "houdiniguidescale")
    for p in edit.parms():
        if p.name().endswith("_control") and not any(k in p.name() for k in keep):
            try:
                p.set("none")
            except hou.OperationFailed:
                pass
    edit.parm("aperture").set("setratio")
    for name in ("horizontalAperture", "clippingRange1", "clippingRange2", "aspectratiox", "aspectratioy",
                 "xn__houdiniguidescale_s3a"):
        edit.parm(name).setExpression(f'ch("../{name}")', hou.exprLanguage.Hscript)
    cam_x100 = _node(sub, "xform", "cam_x100", (edit,), xforminworldspace=0, usexformcommonapi=0, scale=100.0)

    switch = _node(sub, "switch", "geo_or_cam", (hide, cam_x100))
    switch.parm("input").setExpression(f'ch("../{config.P_GEO_CAM}")', hou.exprLanguage.Hscript)
    out = sub.node("output0") or sub.createNode("output", "output0")  # a LOP subnet comes with output0
    out.setInput(0, switch)
    out.setDisplayFlag(True)
    sub.layoutChildren()


def _parm_templates() -> hou.ParmTemplateGroup:
    T = hou
    g = hou.ParmTemplateGroup()
    cb = "hou.phm().cb_parm_changed(kwargs)"

    def s(name, label, default="", menu=None, callback=True, **kw):
        t = T.StringParmTemplate(name, label, 1, default_value=(default,), **kw)
        if menu:
            t.setItemGeneratorScript(menu)
            t.setItemGeneratorScriptLanguage(T.scriptLanguage.Python)
            t.setMenuType(T.menuType.StringReplace)
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

    def button(name, label, script):
        t = T.ButtonParmTemplate(name, label)
        t.setScriptCallback(script)
        t.setScriptCallbackLanguage(T.scriptLanguage.Python)
        return t

    def hidden(t):
        t.hide(True)
        return t

    status = T.StringParmTemplate(config.P_STATUS, "Status", 1)
    status.setTags({"editor": "1", "editorlines": "2-6"})
    status.setDisableWhen("{ 1 == 1 }")
    g.append(status)
    g.append(button("mx_manager", "Manager", "hou.phm().cb_open_manager(kwargs)"))
    g.append(button("mx_refresh", "Refresh", "hou.phm().cb_refresh(kwargs)"))
    g.append(button("apply_mx_timeline", "Apply Timeline", "hou.phm().cb_apply_timeline(kwargs)"))

    shot = T.FolderParmTemplate("f_shot", "Shot", folder_type=T.folderType.Simple)
    shot.addParmTemplate(s(config.P_ROOT, "Project Root", string_type=T.stringParmType.FileReference,
                           file_type=T.fileType.Directory))
    shot.addParmTemplate(s(config.P_SHOT, "Shot"))
    shot.addParmTemplate(s(config.P_ANIM_VERSION, "Anim Version", menu="hou.phm().menu_anim_versions(hou.pwd())"))
    shot.addParmTemplate(s(config.P_ANIM_FILE, "Anim File", menu="hou.phm().menu_anim_files(hou.pwd())"))
    shot.addParmTemplate(s(config.P_ASSET, "Asset", menu="hou.phm().menu_assets(hou.pwd())"))
    inst = s(config.P_INSTANCE, "Prim Name", callback=True)
    inst.setHelp("The prim the instance is grafted under: /<name>/Geo/...")
    shot.addParmTemplate(inst)
    g.append(shot)

    for part, label in (("lookdev", "Lookdev"), ("groom", "Groom"), ("cloth", "Cloth")):
        f = T.FolderParmTemplate(f"f_{part}", label, folder_type=T.folderType.Collapsible)
        f.setConditional(T.parmCondType.HideWhen, f"{{ {config.P_GEO_CAM} == 1 }}")
        f.addParmTemplate(toggle(config.P_ENABLE[part], f"Enable {label}"))
        f.addParmTemplate(s(config.P_VERSION[part], "Version",
                            menu=f'hou.phm().menu_versions(hou.pwd(), "{part}")'))
        f.addParmTemplate(s(config.P_PATH[part], "File", callback=False))
        if part in ("lookdev", "groom"):
            vp = T.ToggleParmTemplate(f"mx_{part}_viewport", "Show in Viewport", default_value=True)
            vp.setHelp("Off: loaded for render only (Karma), for a lighter viewport.")
            f.addParmTemplate(vp)
        g.append(f)

    geo = T.FolderParmTemplate("folder1", "Geometry Setting", folder_type=T.folderType.Collapsible)
    geo.setConditional(T.parmCondType.HideWhen, f"{{ {config.P_GEO_CAM} == 1 }}")
    geo.addParmTemplate(T.FloatParmTemplate("scale", "Uniform Scale", 1, default_value=(1.0,), min=0, max=10))
    geo.addParmTemplate(T.ToggleParmTemplate("mx_hide_enable", "Hide Hair Driver", default_value=True))
    geo.addParmTemplate(T.StringParmTemplate("mx_hide_pattern", "Hidden Prims", 1,
                                             default_value=("Geo/Groom_grp/HairDriver_grp",)))
    g.append(geo)

    cam = T.FolderParmTemplate("xn__Camerasetting_uma", "Camera setting", folder_type=T.folderType.Collapsible)
    cam.setConditional(T.parmCondType.HideWhen, f"{{ {config.P_GEO_CAM} == 0 }}")
    cam.addParmTemplate(T.FloatParmTemplate("scale2", "Uniform Scale", 1, default_value=(1.0,), min=0, max=10))
    cam.addParmTemplate(T.FloatParmTemplate("horizontalAperture", "Horizontal Aperture", 1, default_value=(36.0,),
                                            min=1, max=100))
    cam.addParmTemplate(T.FloatParmTemplate("xn__houdiniguidescale_s3a", "Scale Guide Geometry", 1,
                                            default_value=(1.0,), min=0, max=10))
    # Base1 names (clippingRange1 / 2), as in 2.1 and as the inner camera reads them; the default XYZW named them
    # clippingRangex / y and the clipping never reached the camera
    cam.addParmTemplate(T.FloatParmTemplate("clippingRange", "Clipping Range", 2, default_value=(0.001, 1e6),
                                            naming_scheme=T.parmNamingScheme.Base1))
    cam.addParmTemplate(T.FloatParmTemplate("aspectratio", "Aspect Ratio", 2, default_value=(16.0, 9.0),
                                            naming_scheme=T.parmNamingScheme.XYZW))
    g.append(cam)

    for t in (
        T.IntParmTemplate(config.P_GEO_CAM, "Geo / Cam", 1, default_value=(0,)),
        T.StringParmTemplate(config.P_ANIM_PATH, "Anim File Path", 1),
        T.ToggleParmTemplate("LOP_scale", "LOP scale (2.1)", default_value=True),
        T.StringParmTemplate("mx_anim_publish_parent", "Anim Publish Folder (2.1)", 1),
        T.StringParmTemplate("mx_groom_asset", "Groom Asset (2.1)", 1),
        T.StringParmTemplate("mx_cloth_asset", "Cloth Asset (2.1)", 1),
        T.StringParmTemplate(config.P_SUBD_RULES, "Subdivision Rules", 1),
        *[T.StringParmTemplate(n, n, 1) for n in config.P_LAYERS],
        *[T.StringParmTemplate(k, k, 1) for task in config.P_FX.values() for k in
          (task["mode"], task["template"], task["roots"])],
        *[T.IntParmTemplate(k, k, 1) for task in config.P_FX.values() for k in (task["first"], task["last"])],
    ):
        g.append(hidden(t))
    return g


def build(out_path: str = DEFAULT_OUT) -> str:
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
        name=config.HDA_TYPE, hda_file_name=out_path, description=config.HDA_LABEL, min_num_inputs=0,
        max_num_inputs=1, version="2.2", ignore_external_references=True, change_node_type=True,
        create_backup=False)
    d = hda.type().definition()
    d.setParmTemplateGroup(_parm_templates())
    d.setIcon("LOP_valueclip")
    d.setComment("Mono Anim Loader 2.2, built by tools/fx/anim_loader/build_hda.py")
    d.addSection("PythonModule", PYTHON_MODULE)
    d.setExtraFileOption("PythonModule/IsPython", True)
    d.addSection("OnCreated", ON_CREATED)
    d.setExtraFileOption("OnCreated/IsPython", True)
    d.save(out_path, hda, create_backup=False)
    hda.destroy()
    for f in set(glob.glob(os.path.join(backup_dir, "*"))) - had_backups:
        os.remove(f)
    if os.path.isdir(backup_dir) and not os.listdir(backup_dir):
        os.rmdir(backup_dir)
    return out_path


if __name__ == "__main__":
    print("built", build(sys.argv[1] if len(sys.argv) > 1 else DEFAULT_OUT))
