"""
Pick ``subdivisionScheme`` for meshes in an anim USD cache (no bpy).

USD reads a mesh without an authored ``subdivisionScheme`` as ``catmullClark``, so
Houdini's viewport subdivides every unmarked mesh (sh025: >45 GB, then a crash).
The cache therefore always authors the scheme, following the rule Blender's own
``wm.usd_export(export_subdivision="BEST_MATCH")`` uses for model publishes:

* the last modifier enabled for render is a Subdivision Surface -> ``catmullClark``,
  and the points are the cage under it (the exporter switches that modifier off in
  the viewport while it evaluates, then puts it back);
* anything else (no Subdivision, one with modifiers after it, Multires) -> ``none``.

If the Subdivision is already baked into the evaluated points (on in the viewport
with levels > 0, and it could not be switched off), the scheme is ``none``:
subdividing those points again would double the subdivision.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence

SCHEME_CATMULL_CLARK = "catmullClark"
SCHEME_NONE = "none"

SUBSURF_TYPE = "SUBSURF"


@dataclass(frozen=True)
class ModifierState:
    """What the decision needs from one Blender modifier."""

    type: str
    show_viewport: bool
    show_render: bool
    levels: int = 1  # viewport levels (Subdivision Surface only)


def render_subdiv_index(modifiers: Sequence[ModifierState]) -> Optional[int]:
    """Index of the Subdivision Surface that ends the render stack, else ``None``."""
    for index in range(len(modifiers) - 1, -1, -1):
        mod = modifiers[index]
        if not mod.show_render:
            continue
        return index if mod.type == SUBSURF_TYPE else None
    return None


def subdiv_baked_in_viewport(mod: ModifierState) -> bool:
    """True when the viewport evaluation already subdivides with ``mod``."""
    return bool(mod.show_viewport) and int(mod.levels) > 0


def subdivision_scheme(
    modifiers: Sequence[ModifierState],
    *,
    viewport_subdiv_disabled: bool = False,
) -> str:
    """Scheme to author for a mesh with ``modifiers`` (stack order, first to last).

    ``viewport_subdiv_disabled``: the exporter switched the render Subdivision off in
    the viewport, so the evaluated points are its cage.
    """
    index = render_subdiv_index(modifiers)
    if index is None:
        return SCHEME_NONE
    if subdiv_baked_in_viewport(modifiers[index]) and not viewport_subdiv_disabled:
        return SCHEME_NONE
    return SCHEME_CATMULL_CLARK
