"""Fold a camera's data prim into its object Xform in an exported USD layer (pxr only, no bpy).

Blender 5.2.2's ``wm.usd_export`` with ``export_animation=True`` and ``merge_parent_xform=True``
writes the camera object as a bare Xform and drops its Camera prim (sh012a anim v007: Houdini
found no camera). With ``merge_parent_xform=False`` the Camera is written as a child of the
object's Xform (``.../cam_sh012a/cam_sh012a``). The camera writer exports that way and folds the
child back here, so the camera keeps the path earlier publishes had (``.../cam_sh012a``), which
lighting scenes point their render camera at.
"""

from __future__ import annotations


def _foldable(layer, xform_spec):
    """The single Camera child of ``xform_spec`` when it can be folded into it, else None."""
    if xform_spec.typeName != "Xform":
        return None
    children = list(xform_spec.nameChildren)
    if len(children) != 1:
        return None
    child = children[0]
    if child.typeName != "Camera" or list(child.nameChildren):
        return None
    # Blender's camera data prim has no transform; a Camera with xformOps is an object's prim
    # (already folded, or merged by Blender), and folding it would put it on its parent's path.
    if any(prop.name.startswith("xformOp") for prop in child.properties):
        return None
    if any(prop.name in xform_spec.properties for prop in child.properties):
        return None
    return child


def fold_cameras(filepath: str) -> int:
    """Fold every Camera prim that is the only child of an Xform into that Xform.

    The Xform becomes the Camera (its transform stays, the camera's attributes move onto it) and
    the child goes. Returns how many were folded; the file is saved only when that is not 0.
    """
    from pxr import Sdf

    layer = Sdf.Layer.FindOrOpen(str(filepath))
    if layer is None:
        return 0
    layer.Reload(force=True)  # a layer still open in this session would be the one from before the export

    found = []

    def _visit(path):
        if not path.IsPrimPath():
            return
        spec = layer.GetPrimAtPath(path)
        if spec is not None and _foldable(layer, spec) is not None:
            found.append(path)

    layer.Traverse(Sdf.Path.absoluteRootPath, _visit)

    folded = 0
    for path in found:
        parent = layer.GetPrimAtPath(path)
        child = _foldable(layer, parent)
        if child is None:
            continue
        for prop in list(child.properties):
            Sdf.CopySpec(layer, prop.path, layer, path.AppendProperty(prop.name))
        for key in ("apiSchemas", "kind"):
            if child.HasInfo(key) and not parent.HasInfo(key):
                parent.SetInfo(key, child.GetInfo(key))
        parent.typeName = "Camera"
        del parent.nameChildren[child.name]
        folded += 1

    if folded:
        layer.Save()
    return folded


__all__ = ["fold_cameras"]
