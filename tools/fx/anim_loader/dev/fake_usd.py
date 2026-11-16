"""USD writers for the Mono Anim Loader fake data (pxr + numpy; run under hython). Not shipped to artists.

Layouts follow the real publishes of 260826_grn_vp97 (sh025 v005): root ``/Geo``, Y up, metres, 30 fps;
groom / cloth caches are one file per frame (``<shot>_groom.0000.usd``), written by the old grooming
department process whose exact layout is unknown, so both styles are written: time sample at the file's
frame (``timesample=True``) or default value only.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from pxr import Gf, Sdf, Usd, UsdGeom, UsdShade, Vt

FAKE_README = "Fake cache made by Claude for Mono Anim Loader tests, not a real publish.\n"


def _stage(path: Path, fps: float, start: float, end: float) -> Usd.Stage:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()
    st = Usd.Stage.CreateNew(str(path))
    UsdGeom.SetStageUpAxis(st, UsdGeom.Tokens.y)
    UsdGeom.SetStageMetersPerUnit(st, 1.0)
    st.SetFramesPerSecond(fps)
    st.SetTimeCodesPerSecond(fps)
    st.SetStartTimeCode(start)
    st.SetEndTimeCode(end)
    return st


def grid(nx: int, nz: int, size: float, y: float = 0.0) -> tuple[np.ndarray, list[int], list[int]]:
    """A flat grid: points (N, 3), faceVertexCounts, faceVertexIndices."""
    xs, zs = np.meshgrid(np.linspace(-size / 2, size / 2, nx), np.linspace(-size / 2, size / 2, nz))
    pts = np.stack([xs.ravel(), np.full(xs.size, y), zs.ravel()], axis=1)
    idx = []
    for j in range(nz - 1):
        for i in range(nx - 1):
            a = j * nx + i
            idx += [a, a + 1, a + nx + 1, a + nx]
    return pts, [4] * ((nx - 1) * (nz - 1)), idx


def _mesh(st: Usd.Stage, path: str, pts0: np.ndarray, counts, idx, motion, frames) -> None:
    m = UsdGeom.Mesh.Define(st, path)
    m.CreateFaceVertexCountsAttr(counts)
    m.CreateFaceVertexIndicesAttr(idx)
    attr = m.CreatePointsAttr()
    for f in frames:
        attr.Set(Vt.Vec3fArray.FromNumpy(motion(pts0, f).astype(np.float32)), Usd.TimeCode(f))


def write_anim_geo(path: Path, fps: float, frames: range, offset: float, phase: float) -> None:
    """A fake character: body, hair driver and dress meshes, moving differently per instance."""
    st = _stage(path, fps, frames[0], frames[-1])
    for p in ("/Geo", "/Geo/Base_grp", "/Geo/Base_grp/Body_grp", "/Geo/Groom_grp",
              "/Geo/Groom_grp/HairDriver_grp", "/Geo/Outfit_grp", "/Geo/Outfit_grp/Costume_grp"):
        UsdGeom.Xform.Define(st, p)
    st.SetDefaultPrim(st.GetPrimAtPath("/Geo"))

    def motion(pts, f):
        out = pts.copy()
        out[:, 0] += offset + 0.05 * f
        out[:, 1] += 0.2 * np.sin(phase + f * 0.3 + pts[:, 0] * 2.0)
        return out

    body, bc, bi = grid(45, 45, 1.0, 1.0)
    _mesh(st, "/Geo/Base_grp/Body_grp/Geo_Body", body, bc, bi, motion, frames)
    hair, hc, hi = grid(30, 30, 0.4, 1.7)
    _mesh(st, "/Geo/Groom_grp/HairDriver_grp/Geo_HairBase", hair, hc, hi, motion, frames)
    dress, dc, di = grid(30, 30, 0.8, 0.6)
    _mesh(st, "/Geo/Outfit_grp/Costume_grp/Geo_Dress", dress, dc, di, motion, frames)
    st.GetRootLayer().Save()


def write_camera(path: Path, shot: str, fps: float, frames: range) -> None:
    st = _stage(path, fps, frames[0], frames[-1])
    UsdGeom.Xform.Define(st, "/root")
    UsdGeom.Xform.Define(st, f"/root/{shot}_cam_root")
    cam = UsdGeom.Camera.Define(st, f"/root/{shot}_cam_root/cam_{shot}")
    op = cam.AddTranslateOp()
    for f in frames:
        op.Set(Gf.Vec3d(0.1 * f, 1.5, 6.0), Usd.TimeCode(f))
    st.SetDefaultPrim(st.GetPrimAtPath("/root"))
    st.GetRootLayer().Save()


def write_lookdev(path: Path, asset: str, color: tuple[float, float, float], body_path: str) -> None:
    """A lookdev publish: a material at ``/materials`` (outside ``/Geo``) bound to the body mesh."""
    st = _stage(path, 30.0, 0, 0)
    UsdGeom.Scope.Define(st, "/materials")
    mat = UsdShade.Material.Define(st, f"/materials/{asset}_mtl")
    sh = UsdShade.Shader.Define(st, f"/materials/{asset}_mtl/surface")
    sh.CreateIdAttr("UsdPreviewSurface")
    sh.CreateInput("diffuseColor", Sdf.ValueTypeNames.Color3f).Set(Gf.Vec3f(*color))
    mat.CreateSurfaceOutput().ConnectToSource(sh.ConnectableAPI(), "surface")
    body = st.OverridePrim(body_path)
    UsdShade.MaterialBindingAPI.Apply(body).Bind(mat)
    st.GetRootLayer().Save()


def _driver_points(anim: Usd.Stage, mesh_paths: list[str], frame: float) -> np.ndarray:
    chunks = []
    for p in mesh_paths:
        v = UsdGeom.PointBased(anim.GetPrimAtPath(p)).GetPointsAttr().Get(Usd.TimeCode(frame))
        if v is not None:
            chunks.append(np.asarray(v, dtype=np.float32))
    return np.concatenate(chunks) if chunks else np.zeros((0, 3), np.float32)


def write_groom_frames(anim_file: Path, driver_meshes: list[str], out_dir: Path, shot: str,
                       frames: range, fps: float, strands: int, segs: int = 8, length: float = 0.08,
                       timesample: bool = True) -> int:
    """One BasisCurves file per frame at ``/Geo/Groom_grp/Hair_grp/hair``, rooted on the driver meshes."""
    anim = Usd.Stage.Open(str(anim_file))
    rng = np.random.default_rng(7)
    first = _driver_points(anim, driver_meshes, frames[0])
    pick = rng.choice(len(first), size=min(strands, len(first)), replace=len(first) < strands)
    t = np.linspace(0.0, 1.0, segs, dtype=np.float32)[None, :, None]
    for f in frames:
        roots = _driver_points(anim, driver_meshes, f)[pick]
        centre = roots.mean(axis=0)
        out = roots - centre
        out /= np.maximum(np.linalg.norm(out, axis=1, keepdims=True), 1e-6)
        droop = np.array([0.0, -1.0, 0.0], np.float32)
        pts = roots[:, None, :] + length * t * out[:, None, :] + 0.5 * length * t ** 2 * droop
        st = _stage(out_dir / f"{shot}_groom.{f:04d}.usd", fps, f, f)
        for p in ("/Geo", "/Geo/Groom_grp", "/Geo/Groom_grp/Hair_grp"):
            UsdGeom.Xform.Define(st, p)
        c = UsdGeom.BasisCurves.Define(st, "/Geo/Groom_grp/Hair_grp/hair")
        c.CreateTypeAttr(UsdGeom.Tokens.linear)
        c.CreateCurveVertexCountsAttr(Vt.IntArray([segs] * len(roots)))
        c.CreateWidthsAttr(Vt.FloatArray([0.0004]))
        c.SetWidthsInterpolation(UsdGeom.Tokens.constant)
        value = Vt.Vec3fArray.FromNumpy(pts.reshape(-1, 3).astype(np.float32))
        c.CreatePointsAttr().Set(value, Usd.TimeCode(f) if timesample else Usd.TimeCode.Default())
        st.SetDefaultPrim(st.GetPrimAtPath("/Geo"))
        st.GetRootLayer().Save()
    (out_dir / "_FAKE_README.txt").write_text(FAKE_README, encoding="utf-8")
    return len(frames)


def write_cloth_frames(anim_file: Path, meshes: list[str], out_dir: Path, shot: str, frames: range, fps: float,
                       push: float = 0.005, timesample: bool = True) -> int:
    """One file per frame overriding the points of the anim's outfit meshes (same prim paths), pushed out."""
    anim = Usd.Stage.Open(str(anim_file))
    for f in frames:
        st = _stage(out_dir / f"{shot}_cloth.{f:04d}.usd", fps, f, f)
        for p in meshes:
            src = UsdGeom.Mesh(anim.GetPrimAtPath(p))
            pts = np.asarray(src.GetPointsAttr().Get(Usd.TimeCode(f)), np.float32)
            d = pts - pts.mean(axis=0)
            d /= np.maximum(np.linalg.norm(d, axis=1, keepdims=True), 1e-6)
            parts = p.strip("/").split("/")
            for i in range(1, len(parts)):
                UsdGeom.Xform.Define(st, "/" + "/".join(parts[:i]))
            m = UsdGeom.Mesh.Define(st, p)
            m.CreateFaceVertexCountsAttr(src.GetFaceVertexCountsAttr().Get())
            m.CreateFaceVertexIndicesAttr(src.GetFaceVertexIndicesAttr().Get())
            value = Vt.Vec3fArray.FromNumpy((pts + push * d).astype(np.float32))
            m.CreatePointsAttr().Set(value, Usd.TimeCode(f) if timesample else Usd.TimeCode.Default())
        st.SetDefaultPrim(st.GetPrimAtPath("/Geo"))
        st.GetRootLayer().Save()
    (out_dir / "_FAKE_README.txt").write_text(FAKE_README, encoding="utf-8")
    return len(frames)
