"""Move Blender's root-level material scope under the USD default prim (pxr only, no bpy).

Blender's ``wm.usd_export`` always writes materials to a sibling of the exported root
(``/_materials``) and has no option to change it. An asset must be self-contained under its
default prim, so the exporter calls this after writing the file: ``/_materials`` becomes
``/<defaultPrim>/material`` (the same scope texturing and lookdev use), and every material
binding and shader connection is pointed at the new path.
"""

from __future__ import annotations

SOURCE_SCOPE = "/_materials"
TARGET_SCOPE_NAME = "material"

_LIST_FIELDS = ("explicitItems", "addedItems", "prependedItems", "appendedItems", "deletedItems", "orderedItems")


def _retarget(path, src, dst):
    return path.ReplacePrefix(src, dst) if path.HasPrefix(src) else path


def move_materials_under_default_prim(
    filepath: str,
    *,
    source: str = SOURCE_SCOPE,
    scope_name: str = TARGET_SCOPE_NAME,
) -> str | None:
    """Move ``source`` under the layer's default prim. Returns the new scope path, or None if nothing moved.

    Nothing is changed (and None returned) when the layer has no default prim, no ``source`` scope,
    or the target already exists.
    """
    from pxr import Sdf

    layer = Sdf.Layer.FindOrOpen(str(filepath))
    if layer is None:
        return None
    default = layer.defaultPrim
    src = Sdf.Path(source)
    if not default or layer.GetPrimAtPath(src) is None:
        return None
    parent = Sdf.Path("/" + default)
    if layer.GetPrimAtPath(parent) is None:
        return None
    dst = parent.AppendChild(scope_name)
    if layer.GetPrimAtPath(dst) is not None:
        return None

    edit = Sdf.BatchNamespaceEdit()
    edit.Add(src, dst)
    if not layer.Apply(edit):
        return None

    def retarget_list_editor(editor) -> None:
        # Blender writes `prepend rel ...`, so every list-op list must be rewritten, not just explicit.
        for field in _LIST_FIELDS:
            items = list(getattr(editor, field))
            fixed = [_retarget(p, src, dst) for p in items]
            if fixed != items:
                setattr(editor, field, fixed)

    def visit(path):
        spec = layer.GetObjectAtPath(path)
        if isinstance(spec, Sdf.RelationshipSpec):
            retarget_list_editor(spec.targetPathList)
        elif isinstance(spec, Sdf.AttributeSpec):
            retarget_list_editor(spec.connectionPathList)

    layer.Traverse(Sdf.Path.absoluteRootPath, visit)
    layer.Save()
    return str(dst)


__all__ = ["move_materials_under_default_prim", "SOURCE_SCOPE", "TARGET_SCOPE_NAME"]
