"""
Shot animation collection hierarchy.
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional, Tuple

import bpy

from monofx_pipeline_common.shot_collection_fix import (
    canonical_child_collection_name,
    child_names_to_fix,
    is_shot_collection_root_name,
    plan_shot_root_rename,
)
from monofx_pipeline_common.shot_paths import (
    SHOT_CHILD_COLLECTIONS,
    SHOT_COLLECTION_COLORS,
    SHOT_ROOT_COLLECTION_COLOR,
    detect_shot_from_path,
    shot_collection_root_name,
)


def detect_shot_from_blend_filepath(filepath: str) -> Optional[str]:
    if not filepath:
        return None
    return detect_shot_from_path(Path(filepath))


def _set_collection_color(coll: bpy.types.Collection, color_tag: str) -> None:
    if not color_tag or color_tag == "NONE":
        return
    if hasattr(coll, "color_tag"):
        coll.color_tag = color_tag


def _ensure_child_collection(
    parent: bpy.types.Collection,
    name: str,
    *,
    color_tag: str = "NONE",
) -> bpy.types.Collection:
    existing = parent.children.get(name)
    if existing is not None:
        _set_collection_color(existing, color_tag)
        return existing
    child = bpy.data.collections.new(name)
    _set_collection_color(child, color_tag)
    parent.children.link(child)
    return child


def _link_root_to_scene(scene: bpy.types.Scene, root: bpy.types.Collection) -> None:
    if root.name in scene.collection.children:
        return
    try:
        scene.collection.children.link(root)
    except RuntimeError:
        pass


def find_cameras_collection(scene: bpy.types.Scene, shot: str) -> Optional[bpy.types.Collection]:
    root_name = shot_collection_root_name(shot)
    root = bpy.data.collections.get(root_name)
    if root is None:
        return None
    return root.children.get("Cameras")


def find_cameras_collection_from_object(obj: bpy.types.Object) -> Optional[bpy.types.Collection]:
    """Cameras child collection under any Anim_* root that contains *obj*."""
    for coll in obj.users_collection:
        parent = coll.parent
        if parent is None or not is_shot_collection_root_name(parent.name):
            continue
        if canonical_child_collection_name(coll.name) == "Cameras":
            return coll
    return None


def ensure_cameras_collection(
    scene: bpy.types.Scene,
    shot: str,
    *,
    cam_obj: Optional[bpy.types.Object] = None,
) -> bpy.types.Collection:
    """Return ``Anim_<shot>/Cameras``, fixing or creating shot collections when needed."""
    existing = find_cameras_collection(scene, shot)
    if existing is not None:
        return existing

    fix_shot_collection_names(scene, shot)
    existing = find_cameras_collection(scene, shot)
    if existing is not None:
        return existing

    if cam_obj is not None and find_cameras_collection_from_object(cam_obj) is not None:
        fix_shot_collection_names(scene, shot)
        existing = find_cameras_collection(scene, shot)
        if existing is not None:
            return existing
        existing = find_cameras_collection_from_object(cam_obj)
        if existing is not None:
            return existing

    create_shot_collections(scene, shot)
    cameras = find_cameras_collection(scene, shot)
    if cameras is None:
        raise RuntimeError(f"Could not create Cameras collection for shot {shot!r}.")
    return cameras


def create_shot_collections(
    scene: bpy.types.Scene,
    shot: str,
) -> Tuple[bool, str, Optional[bpy.types.Collection]]:
    shot_token = (shot or "").strip().lower()
    if not shot_token:
        return False, "Shot token is empty.", None

    root_name = shot_collection_root_name(shot_token)
    root = bpy.data.collections.get(root_name)
    if root is None:
        root = bpy.data.collections.new(root_name)
    _set_collection_color(root, SHOT_ROOT_COLLECTION_COLOR)

    for child_name in SHOT_CHILD_COLLECTIONS:
        _ensure_child_collection(
            root,
            child_name,
            color_tag=SHOT_COLLECTION_COLORS.get(child_name, "NONE"),
        )

    _link_root_to_scene(scene, root)
    return True, f"Shot collections ready: {root_name}", root


def _shot_roots_linked_to_scene(scene: bpy.types.Scene) -> List[bpy.types.Collection]:
    roots: List[bpy.types.Collection] = []
    for child in scene.collection.children:
        if is_shot_collection_root_name(child.name):
            roots.append(child)
    return roots


def _merge_collection_contents(
    src: bpy.types.Collection,
    dst: bpy.types.Collection,
) -> None:
    for obj in list(src.objects):
        if obj.name not in dst.objects:
            try:
                dst.objects.link(obj)
            except RuntimeError:
                pass
        try:
            src.objects.unlink(obj)
        except RuntimeError:
            pass

    for child in list(src.children):
        existing = dst.children.get(child.name)
        if existing is not None:
            _merge_collection_contents(child, existing)
            try:
                src.children.unlink(child)
            except RuntimeError:
                pass
            try:
                if not child.objects and not child.children:
                    bpy.data.collections.remove(child)
            except Exception:
                pass
        else:
            try:
                dst.children.link(child)
            except RuntimeError:
                pass
            try:
                src.children.unlink(child)
            except RuntimeError:
                pass


def _fix_child_collection_names(root: bpy.types.Collection) -> int:
    renamed = 0
    for old_name, new_name in child_names_to_fix(child.name for child in root.children):
        child = root.children.get(old_name)
        if child is None:
            continue
        if bpy.data.collections.get(new_name) is not None and root.children.get(new_name) != child:
            continue
        child.name = new_name
        _set_collection_color(child, SHOT_COLLECTION_COLORS.get(new_name, "NONE"))
        renamed += 1

    for child_name in SHOT_CHILD_COLLECTIONS:
        _ensure_child_collection(
            root,
            child_name,
            color_tag=SHOT_COLLECTION_COLORS.get(child_name, "NONE"),
        )
    return renamed


def fix_shot_collection_names(
    scene: bpy.types.Scene,
    shot: str,
) -> Tuple[bool, str]:
    """
    Rename ``Anim_<shot>`` root to match *shot* from the file path and normalize child names.
    """
    shot_token = (shot or "").strip().lower()
    if not shot_token:
        return False, "Shot token is empty.",

    target_name = shot_collection_root_name(shot_token)
    roots = _shot_roots_linked_to_scene(scene)
    root_names = [coll.name for coll in roots]

    messages: List[str] = []
    rename_plan = plan_shot_root_rename(shot_token, root_names)

    if rename_plan is not None:
        from_name, to_name = rename_plan
        src = bpy.data.collections.get(from_name)
        if src is None:
            return False, f"Collection not found: {from_name}"

        dst = bpy.data.collections.get(to_name)
        if dst is not None and dst != src:
            _merge_collection_contents(src, dst)
            _unlink_collection_from_scene(scene, src)
            try:
                if not src.objects and not src.children:
                    bpy.data.collections.remove(src)
            except Exception:
                pass
            root = dst
            messages.append(f"Merged {from_name} into {to_name}")
        else:
            src.name = to_name
            root = src
            messages.append(f"Renamed {from_name} → {to_name}")
    else:
        root = bpy.data.collections.get(target_name)
        if root is None:
            if not roots:
                return False, "No Anim_<shot> collection found in the scene."
            if len(roots) > 1:
                return (
                    False,
                    "Multiple Anim_<shot> roots found; clean up manually or use Create Shot Collections.",
                )
            root = roots[0]
            if root.name.casefold() != target_name.casefold():
                return (
                    False,
                    f"Could not rename {root.name} to {target_name} (name conflict).",
                )

    if root is None:
        root = bpy.data.collections.get(target_name)
    if root is None:
        return False, "Shot collection root not found after fix."

    _set_collection_color(root, SHOT_ROOT_COLLECTION_COLOR)
    child_renamed = _fix_child_collection_names(root)
    if child_renamed:
        messages.append(f"Fixed {child_renamed} child collection name(s)")
    _link_root_to_scene(scene, root)

    if not messages:
        _fix_child_collection_names(root)
        return True, f"Shot collections already match {target_name}"

    return True, "; ".join(messages)


def _unlink_collection_from_scene(scene: bpy.types.Scene, coll: bpy.types.Collection) -> None:
    try:
        if coll.name in scene.collection.children:
            scene.collection.children.unlink(coll)
    except RuntimeError:
        pass
