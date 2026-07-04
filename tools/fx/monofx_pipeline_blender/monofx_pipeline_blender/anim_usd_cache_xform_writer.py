"""
Static bind Xforms for anim USD cache — matches Model USD orientation on prims.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Mapping

import bpy
from bpy.types import Context
from pxr import Gf, UsdGeom

from . import config

if TYPE_CHECKING:
    from mathutils import Matrix

logger = logging.getLogger("monofx.anim_usd_cache")


class MatrixXformOpCache:
    """One matrix xform op per prim — never stack duplicate ``MakeMatrixXform`` ops."""

    def __init__(self) -> None:
        self._ops: dict[str, object] = {}

    def set(
        self,
        prim,
        gf_matrix: Gf.Matrix4d,
        *,
        frame: float | None = None,
    ) -> None:
        from pxr import Usd

        key = str(prim.GetPath())
        op = self._ops.get(key)
        if op is None:
            xformable = UsdGeom.Xformable(prim)
            op = xformable.MakeMatrixXform()
            self._ops[key] = op
        if frame is None:
            op.Set(gf_matrix)
        else:
            op.Set(gf_matrix, Usd.TimeCode(frame))


def _axis_enum_to_io_string(axis: str) -> str:
    """Map addon enum (``NEGATIVE_Z``) to ``axis_conversion`` tokens (``-Z``)."""
    axis = str(axis or "").strip()
    if axis.startswith("NEGATIVE_"):
        return "-" + axis.split("_", 1)[1]
    return axis


def build_axis_conversion_matrix(
    forward: str = config.DEFAULT_EXPORT_FORWARD,
    up: str = config.DEFAULT_EXPORT_UP,
) -> "Matrix":
    """
    Match ``wm.usd_export`` root orientation (``usd_writer_transform.cc``).

    Blender's C exporter transposes ``mat3_from_axis_conversion`` before
    ``mat @ matrix_world``; use the same transpose here so anim cache aligns
    with published model USD.
    """
    from bpy_extras.io_utils import axis_conversion

    rot = axis_conversion(
        from_forward="Y",
        from_up="Z",
        to_forward=_axis_enum_to_io_string(forward),
        to_up=_axis_enum_to_io_string(up),
    )
    return rot.transposed().to_4x4()


def matrix_to_gf(mat: "Matrix") -> Gf.Matrix4d:
    return Gf.Matrix4d(
        float(mat[0][0]),
        float(mat[0][1]),
        float(mat[0][2]),
        float(mat[0][3]),
        float(mat[1][0]),
        float(mat[1][1]),
        float(mat[1][2]),
        float(mat[1][3]),
        float(mat[2][0]),
        float(mat[2][1]),
        float(mat[2][2]),
        float(mat[2][3]),
        float(mat[3][0]),
        float(mat[3][1]),
        float(mat[3][2]),
        float(mat[3][3]),
    )


def resolve_orientation_matrix(context: Context) -> "Matrix":
    """Same orientation policy as Model → USD publish (``wm.usd_export``)."""
    import mathutils

    props = context.scene.monofx_pipeline_blender_props
    if not props.convert_orientation:
        return mathutils.Matrix.Identity(4)
    return build_axis_conversion_matrix(
        str(props.export_forward_axis),
        str(props.export_up_axis),
    )


def bind_matrix_for_hierarchy_object(
    obj: bpy.types.Object,
    *,
    parent_in_export_hierarchy: bool,
    orient_matrix: "Matrix",
    unit_scale: float,
    parent_world: "Matrix | None" = None,
) -> "Matrix":
    """
    Static bind matrix for one exported prim.

    Prefer ``usd_xform_from_evaluated_worlds`` (parent-relative, matches
    ``wm.usd_export``). This helper remains for callers that only have a bare
    ``Object`` without a depsgraph snapshot.
    """
    if parent_in_export_hierarchy and parent_world is not None:
        mat = parent_world.inverted() @ obj.matrix_world.copy()
    elif parent_in_export_hierarchy:
        mat = obj.matrix_local.copy()
    else:
        mat = orient_matrix @ obj.matrix_world.copy()
    if unit_scale != 1.0:
        mat.translation *= unit_scale
    return mat


def usd_xform_from_evaluated_worlds(
    obj_name: str,
    node: object,
    hierarchy_names: set[str],
    world_matrices: Mapping[str, "Matrix"],
    *,
    orient_matrix: "Matrix",
    unit_scale: float,
) -> "Matrix":
    """
    Animated USD xform for one hierarchy prim (``usd_writer_transform.cc``).

    Export root: ``orient @ matrix_world``.
    Children: ``parent_world.inverted() @ matrix_world`` (constraints baked in
    evaluated world matrices).
    """
    import mathutils

    world = world_matrices.get(obj_name)
    if world is None:
        logger.warning("No evaluated world matrix for %s; using identity", obj_name)
        return mathutils.Matrix.Identity(4)

    parent_name = getattr(node, "parent_name", None)
    parent_in = bool(parent_name and parent_name in hierarchy_names)
    if not parent_in:
        mat = orient_matrix @ world
    else:
        parent_world = world_matrices.get(parent_name or "")
        if parent_world is None:
            mat = orient_matrix @ world
        else:
            mat = parent_world.inverted() @ world

    if unit_scale != 1.0:
        mat.translation *= unit_scale
    return mat


def evaluated_world_matrices_for_hierarchy(
    hierarchy: Mapping[str, object],
    *,
    depsgraph: bpy.types.Depsgraph,
) -> dict[str, "Matrix"]:
    """Evaluated ``matrix_world`` per object (rig constraints included)."""
    worlds: dict[str, "Matrix"] = {}
    for obj_name in hierarchy:
        obj = bpy.data.objects.get(obj_name)
        if obj is None:
            logger.warning("Hierarchy object not found in bpy.data.objects: %s", obj_name)
            continue
        eval_obj = obj.evaluated_get(depsgraph)
        worlds[obj_name] = eval_obj.matrix_world.copy()
    return worlds


def write_prim_bind_xform(
    prim,
    gf_matrix: Gf.Matrix4d,
    *,
    op_cache: MatrixXformOpCache | None = None,
) -> None:
    if op_cache is not None:
        op_cache.set(prim, gf_matrix)
        return
    xformable = UsdGeom.Xformable(prim)
    op = xformable.MakeMatrixXform()
    op.Set(gf_matrix)


def write_prim_animated_xform(
    prim,
    gf_matrix: Gf.Matrix4d,
    frame: float,
    *,
    op_cache: MatrixXformOpCache | None = None,
) -> None:
    if op_cache is not None:
        op_cache.set(prim, gf_matrix, frame=frame)
        return
    from pxr import Usd

    xformable = UsdGeom.Xformable(prim)
    op = xformable.MakeMatrixXform()
    op.Set(gf_matrix, Usd.TimeCode(frame))


def author_hierarchy_bind_xforms(
    *,
    context: Context,
    hierarchy: Mapping[str, object],
    mesh_prims: Mapping[str, UsdGeom.Mesh],
    xform_prims: Mapping[str, UsdGeom.Xform],
    frame: int,
    orient_matrix: "Matrix",
    unit_scale: float,
) -> None:
    """Write static bind Xforms once at *frame* (typically ``frame_start``)."""
    scene = context.scene
    scene.frame_set(int(frame))
    try:
        context.view_layer.update()
    except Exception:
        pass

    hierarchy_names = set(hierarchy.keys())
    depsgraph = context.evaluated_depsgraph_get()
    world_matrices = evaluated_world_matrices_for_hierarchy(
        hierarchy,
        depsgraph=depsgraph,
    )
    bind_cache = MatrixXformOpCache()
    for obj_name, node in hierarchy.items():
        obj = bpy.data.objects.get(obj_name)
        if obj is None:
            continue
        mat = usd_xform_from_evaluated_worlds(
            obj_name,
            node,
            hierarchy_names,
            world_matrices,
            orient_matrix=orient_matrix,
            unit_scale=unit_scale,
        )
        gf = matrix_to_gf(mat)
        if getattr(node, "is_mesh", False):
            mesh = mesh_prims.get(obj_name)
            if mesh is None:
                continue
            write_prim_bind_xform(mesh.GetPrim(), gf, op_cache=bind_cache)
            logger.debug("Bind xform mesh %s", obj_name)
        else:
            xform = xform_prims.get(obj_name)
            if xform is None:
                continue
            write_prim_bind_xform(xform.GetPrim(), gf, op_cache=bind_cache)
            logger.debug("Bind xform %s", obj_name)
