"""Stamp the scene fps on an exported USD layer (pxr only, no bpy).

Blender's ``wm.usd_export`` writes ``timeCodesPerSecond`` / ``framesPerSecond`` only when it
exports animation; a static export (model / UV publish) keeps the USD default of 24 even when
the scene runs at 30. A Houdini Sublayer LOP then copies that 24 onto the stage root and
overrides the hip's fps. The exporter calls this right after ``wm.usd_export``.
"""

from __future__ import annotations


def stamp_fps(filepath: str, fps: float) -> bool:
    """Set ``timeCodesPerSecond`` and ``framesPerSecond`` to ``fps``. True if the file changed.

    Does nothing (False) for a missing file or a non-positive ``fps``, and does not rewrite a
    layer that already authors both values. A layer that authors neither (or one) gets both,
    even at 24: an unauthored fps is only USD's fallback, not a stamp.
    """
    from pxr import Sdf

    fps = float(fps)
    if fps <= 0:
        return False
    layer = Sdf.Layer.FindOrOpen(str(filepath))
    if layer is not None:
        layer.Reload(force=True)  # a layer still open in this session would be the one from before the export
    if layer is None:
        return False
    # Read only what the layer authors: an unauthored value reads as USD's fallback (24), and
    # Blender 5.2's static export at 24 fps authors neither, so comparing values alone never wrote.
    if (
        layer.HasTimeCodesPerSecond()
        and layer.HasFramesPerSecond()
        and layer.timeCodesPerSecond == fps
        and layer.framesPerSecond == fps
    ):
        return False
    layer.timeCodesPerSecond = fps
    layer.framesPerSecond = fps
    layer.Save()
    return True


__all__ = ["stamp_fps"]
