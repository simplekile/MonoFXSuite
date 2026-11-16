"""Spike S2b (plan Task 4): value clips authored AFTER Graft Stages, in a new layer, no manifest. hython, no args.

Result 2026-11-17: groom equals the file at 12, blurs at 10.5, survives a USD ROP write; cloth overrides the anim
points only with configurelayer startnewlayer=1 before the Python LOP (same layer: anim samples win)."""
import hou, numpy as np, time
from pxr import Usd, UsdGeom
R = "E:/01 Dev/sandbox/claude/anim_loader/fake_project/02_shots/sh900"
H = "/Geo/Groom_grp/Hair_grp/hair"; D = "/Geo/Outfit_grp/Costume_grp/Geo_Dress"
net = hou.node('/stage')
def branch(name, files):
    b = net.createNode('sublayer', name + '_b'); b.parm('num_files').set(len(files))
    for i, f in enumerate(files): b.parm(f'filepath{i+1}').set(f)
    return b
CODE = '''
from pxr import Usd, UsdGeom, Sdf
stage = hou.pwd().editableStage()
for inst, prim, tmpl, first, last, topo in JOBS:
    path = "/" + inst + prim
    p = stage.GetPrimAtPath(path)
    if not p:
        topo_stage = Usd.Stage.Open(topo)
        src = topo_stage.GetPrimAtPath(prim)
        p = stage.DefinePrim(path, src.GetTypeName())
        for a in ("curveVertexCounts", "type", "widths", "basis", "wrap"):
            at = src.GetAttribute(a)
            if at and at.Get() is not None:
                p.CreateAttribute(a, at.GetTypeName()).Set(at.Get())
        w = src.GetAttribute("widths")
        if w: p.GetAttribute("widths").SetMetadata("interpolation", w.GetMetadata("interpolation"))
    c = Usd.ClipsAPI(p)
    c.SetClipPrimPath(prim)
    c.SetClipTemplateAssetPath(tmpl)
    c.SetClipTemplateStartTime(first); c.SetClipTemplateEndTime(last); c.SetClipTemplateStride(1)
'''
g_in = f"{R}/02_fx/groom/publish/v001/Robot_inst02"
c_in = f"{R}/02_fx/cloth/publish/v001/char_Robot_2"
jobs = [("char_Robot_inst02", H, g_in + "/sh900_groom.####.usd", 1, 24, g_in + "/sh900_groom.0001.usd"),
        ("char_Robot_2", D, c_in + "/sh900_cloth.####.usd", 1, 24, c_in + "/sh900_cloth.0001.usd")]
b1 = branch('i2', [f"{R}/01_anim/publish/v002/geo_char_Robot_inst02.usd"])
b2 = branch('r2', [f"{R}/01_anim/publish/v002/geo_char_Robot_2.usd"])
g1 = net.createNode('graftstages'); g1.setInput(1, b1); g1.parm('primpath').set('/char_Robot_inst02'); g1.parm('destpath').set('')
g2 = net.createNode('graftstages'); g2.setInput(0, g1); g2.setInput(1, b2); g2.parm('primpath').set('/char_Robot_2'); g2.parm('destpath').set('')
cl = net.createNode('configurelayer'); cl.setInput(0, g2); cl.parm('startnewlayer').set(1)
py = net.createNode('pythonscript'); py.setInput(0, cl); py.parm('python').set('JOBS = ' + repr(jobs) + '\n' + CODE)
def P(st, path, t):
    v = UsdGeom.PointBased(st.GetPrimAtPath(path)).GetPointsAttr().Get(Usd.TimeCode(t)); return None if v is None else np.asarray(v)
hou.setFrame(12)
st = py.stage(); print('errors', py.errors())
hair = '/char_Robot_inst02' + H
f12 = Usd.Stage.Open(g_in + "/sh900_groom.0012.usd")
print('groom == file at 12', np.allclose(P(st, hair, 12), P(f12, H, 12)))
a, m, b = P(st, hair, 10), P(st, hair, 10.5), P(st, hair, 11)
print('groom blur', np.abs(m-a).max() > 1e-6, np.allclose(m, (a+b)/2, atol=1e-4))
c12 = Usd.Stage.Open(c_in + "/sh900_cloth.0012.usd"); anim = Usd.Stage.Open(f"{R}/01_anim/publish/v002/geo_char_Robot_2.usd")
dress = '/char_Robot_2' + D
print('cloth == cloth file', np.allclose(P(st, dress, 12), P(c12, D, 12)), 'differs from anim', np.abs(P(st, dress, 12) - P(anim, D, 12)).max())
drv = P(st, '/char_Robot_inst02/Geo/Groom_grp/HairDriver_grp/Geo_HairBase', 12)
roots = P(st, hair, 12).reshape(-1, 8, 3)[:300, 0]
print('roots on driver max m', float(np.min(np.linalg.norm(roots[:, None] - drv[None], axis=2), axis=1).max()))
t = time.time()
for f in range(1, 25):
    hou.setFrame(f); P(py.stage(), hair, f)
print('per frame s', round((time.time() - t) / 24, 4))
# saved for render: does the clip survive a USD ROP write?
rop = net.createNode('usd_rop'); rop.setInput(0, py)
out = "E:/01 Dev/sandbox/claude/anim_loader/spike/s2_render.usda"
rop.parm('lopoutput').set(out); rop.parm('trange').set(0); rop.parm('flattenfilelayers').set(1) if rop.parm('flattenfilelayers') else None; rop.parm('savestyle').set('flattenstage') if rop.parm('savestyle') else None; rop.render()
saved = Usd.Stage.Open(out)
print('saved blur', np.abs(P(saved, hair, 10.5) - P(saved, hair, 10)).max() > 1e-6)
