"""Tests for the subdivisionScheme an anim USD cache authors per mesh."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_path = (
    _ROOT
    / "tools/fx/monofx_pipeline_blender/monofx_pipeline_blender/anim_usd_cache_subdiv.py"
)
_spec = importlib.util.spec_from_file_location("anim_usd_cache_subdiv", _path)
assert _spec and _spec.loader
_mod = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = _mod  # dataclasses look the module up
_spec.loader.exec_module(_mod)

M = _mod.ModifierState
scheme = _mod.subdivision_scheme
render_subdiv_index = _mod.render_subdiv_index


def _arm():
    return M("ARMATURE", True, True)


def test_no_modifiers_is_none():
    assert scheme([]) == "none"


def test_deform_only_is_none():
    assert scheme([_arm(), M("CORRECTIVE_SMOOTH", True, True)]) == "none"


def test_render_subdiv_off_in_viewport_is_catmull_clark():
    mods = [_arm(), M("SUBSURF", False, True, levels=1)]
    assert scheme(mods) == "catmullClark"


def test_viewport_subdiv_switched_off_by_exporter_is_catmull_clark():
    mods = [_arm(), M("SUBSURF", True, True, levels=2)]
    assert scheme(mods, viewport_subdiv_disabled=True) == "catmullClark"


def test_subdiv_baked_into_points_is_none():
    # On in the viewport and not switched off: the points are already subdivided.
    mods = [_arm(), M("SUBSURF", True, True, levels=2)]
    assert scheme(mods) == "none"


def test_viewport_levels_zero_points_are_the_cage():
    mods = [_arm(), M("SUBSURF", True, True, levels=0)]
    assert scheme(mods) == "catmullClark"


def test_subdiv_viewport_only_is_none():
    assert scheme([_arm(), M("SUBSURF", True, False)]) == "none"


def test_subdiv_not_last_in_render_stack_is_none():
    mods = [_arm(), M("SUBSURF", False, True), M("BEVEL", True, True)]
    assert scheme(mods) == "none"
    assert render_subdiv_index(mods) is None


def test_viewport_only_modifier_after_subdiv_is_ignored():
    mods = [_arm(), M("SUBSURF", False, True), M("SMOOTH", True, False)]
    assert render_subdiv_index(mods) == 1
    assert scheme(mods) == "catmullClark"


def test_multires_is_none_like_blender_usd_export():
    assert scheme([M("MULTIRES", True, True)]) == "none"
