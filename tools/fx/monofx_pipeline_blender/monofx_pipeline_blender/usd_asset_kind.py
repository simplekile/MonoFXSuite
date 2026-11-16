"""Mark an exported asset's root prim with a USD model kind (pxr only, no bpy).

The USD asset structure guidelines expect the asset root (the default prim) to be
``kind = component``. Blender's ``wm.usd_export`` writes no kind, so the exporter calls this
right after exporting a model.
"""

from __future__ import annotations

_GROUPING_KINDS = ("component", "group", "assembly")


def set_default_prim_kind(filepath: str, kind: str = "component") -> bool:
    """Set ``kind`` on the layer's default prim. True if the file changed.

    Leaves the file alone (False) when there is no default prim, the prim already has a kind,
    or a descendant already has a component/group/assembly kind (a component may not contain
    one, so setting it would produce an invalid kind hierarchy).
    """
    from pxr import Sdf

    layer = Sdf.Layer.FindOrOpen(str(filepath))
    if layer is not None:
        layer.Reload(force=True)  # a layer still open in this session would be the one from before the export
    if layer is None or not layer.defaultPrim:
        return False
    root = layer.GetPrimAtPath("/" + layer.defaultPrim)
    if root is None or root.kind:
        return False

    def has_grouping_descendant(spec) -> bool:
        for child in spec.nameChildren:
            if child.kind in _GROUPING_KINDS or has_grouping_descendant(child):
                return True
        return False

    if has_grouping_descendant(root):
        return False
    root.kind = kind
    layer.Save()
    return True


__all__ = ["set_default_prim_kind"]
