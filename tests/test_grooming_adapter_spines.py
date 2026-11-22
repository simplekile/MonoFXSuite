"""MONO Grooming v0.2b B2: the adapter's hou-free helpers for control points and drawn locks (the network and the
functions that touch Houdini are checked by tests/houdini/grooming/accept_v02b.py in hython)."""

from __future__ import annotations

import math
import re
from pathlib import Path

import numpy as np
import pytest

from apps.houdini import grooming_adapter as ga
from tools.fx.grooming import config, logic, model
from tools.fx.grooming.logic import DetectReport, Match, MeshPiece
from tools.fx.grooming.model import GroomData, Group, Lock, Orphan

ROOT = Path(__file__).resolve().parents[1]


def _piece(i, name="", root=(0.0, 0.0, 0.0), length=0.2):
    return MeshPiece(index=i, name=name, root=root, length=length, direction=(0.0, -1.0, 0.0))


def _data_with_drawn():
    data = GroomData(groups=[Group(id="g", name="G")],
                     locks=[Lock(id=1, name="g_01", group="g", root=(0, 0, 0), length=0.2,
                                 spine=[(0, 0, 0), (0.1, 0.01, 0), (0.2, 0.02, 0.0)], handles=5),
                            Lock(id=2, name="g_02", group="g", root=(1, 0, 0), length=0.2)])
    data.add_drawn_lock("g", [(0.5, 0, 0), (0.5, -0.1, 0), (0.5, -0.2, 0.01)], 2.0, 0.6, 0.3, name="g_drawn")
    return data


def test_mesh_locks_leave_the_drawn_ones_out():
    data = _data_with_drawn()
    assert [lk.id for lk in ga.mesh_locks(data)] == [1, 2]
    assert data.locks[-1].drawn


def test_edit_cp_values_are_the_flat_handles_of_edited_locks_only():
    data = _data_with_drawn()
    drawn = data.locks[-1].id
    out = ga.edit_cp_values(data, [1, 2, drawn, -1, 99])
    assert out[0] == logic.flat_handles(data.lock(1).spine) and len(out[0]) == 9
    assert out[1:] == [[], [], [], []]          # not edited, drawn (its curve is its shape), unknown, missing


def test_apply_detect_leaves_a_drawn_lock_alone_and_orphans_keep_their_edit():
    data = _data_with_drawn()
    drawn = data.locks[-1].id
    # Detect matched lock 2 only (match_locks is given the mesh locks): lock 1 is missing, the drawn lock stays
    report = DetectReport(matches=[Match(0, 2, "ok")], orphaned=[1])
    out = ga.apply_detect(data, [_piece(0, root=(1, 0, 0))], ["g"], report)
    assert [lk.id for lk in out.locks] == [2, drawn]
    lk = out.lock(drawn)
    assert lk.drawn and lk.match == "ok" and lk.curve == data.lock(drawn).curve
    assert [(o.id, o.spine, o.handles) for o in out.orphans] == [(1, data.lock(1).spine, 5)]
    # a report naming the drawn lock as missing (a caller that gave match_locks every lock) still leaves it
    out2 = ga.apply_detect(data, [_piece(0, root=(1, 0, 0))], ["g"],
                           DetectReport(matches=[Match(0, 2, "ok")], orphaned=[1, drawn]))
    assert out2.lock(drawn) is not None and all(o.id != drawn for o in out2.orphans)


def test_match_locks_with_the_mesh_locks_never_matches_a_drawn_lock():
    data = _data_with_drawn()
    drawn = data.lock(data.locks[-1].id)
    piece = _piece(0, root=drawn.root, length=drawn.length)      # a new piece right at the drawn lock's root
    rep = logic.match_locks([piece], ga.mesh_locks(data), data.next_lock_id())
    assert all(m.lock_id != drawn.id for m in rep.matches)
    assert drawn.id not in rep.orphaned


def test_assign_pieces_with_the_mesh_locks_leaves_the_drawn_lock():
    data = _data_with_drawn()
    drawn = data.lock(data.locks[-1].id)
    ids = ga.assign_pieces([("", drawn.root, drawn.length)], ga.mesh_locks(data))
    assert ids == [-1]


def test_drawn_spine_arrays_root_on_skin_frame_and_profile():
    curve = [(0.0, 0.0, 0.0), (0.0, 0.05, 0.02), (0.0, 0.08, 0.08), (0.0, 0.06, 0.14)]
    on = (0.001, -0.002, 0.0)
    a = ga.drawn_spine_arrays(curve, 49, 100.0, 2.0, 0.6, 0.3, width_mult=1.5, thick_mult=0.5, twist_add=0.3,
                              root_on_skin=on, skin_normal=(0.0, 1.0, 0.0))
    P = a["P"]
    assert P.shape == (49, 3)
    assert np.allclose(P[0], on)                                  # the root on the skin
    assert np.allclose(a["root"], on) and math.isclose(a["length"], logic.arc_lengths(P)[-1])
    # the frame: unit, square, the minor is tangent x axis
    for v in ("tangent", "axis", "minor"):
        assert np.allclose(np.linalg.norm(a[v], axis=1), 1.0)
    assert np.allclose(np.sum(a["tangent"] * a["axis"], 1), 0.0, atol=1e-9)
    assert np.allclose(a["minor"], np.cross(a["tangent"], a["axis"]))
    # at the root the width axis lies on the skin (across the lock): square to the skin's normal before the twist
    assert abs(float(np.dot(a["axis"][0], (0.0, 1.0, 0.0)))) < 1e-9
    # widths: the set width x width_mult at the root, taper x it at the tip, scene units
    assert math.isclose(a["width"][0], 2.0 / 100 * 1.5) and math.isclose(a["width"][-1], 2.0 / 100 * 1.5 * 0.3)
    assert math.isclose(a["thick"][0], 0.6 / 100 * 0.5)
    assert math.isclose(a["twist"][-1], 0.3) and a["twist"][0] == 0.0
    assert a["curveu"][0] == 0.0 and math.isclose(a["curveu"][-1], 1.0)


def test_drawn_spine_arrays_without_skin_is_the_curve():
    curve = [(0.0, 0.0, 0.0), (0.0, 0.1, 0.0), (0.0, 0.2, 0.05)]
    a = ga.drawn_spine_arrays(curve, 20, 100.0, 2.0, 0.6)
    assert np.allclose(a["P"], logic.drawn_spine(curve, 20))


def test_drawn_group_is_a_blast_group_of_lock_ids():
    assert ga.drawn_group([]) == "@lock_id==-1"          # matches no strand: an empty Blast group deletes all
    assert ga.drawn_group([61, 64]) == "@lock_id==61 @lock_id==64"


def test_footprint_owners_takes_the_centres_within_the_radius_and_names_who_gave():
    centres = [(0, 0, 0), (0.005, 0, 0), (0.02, 0, 0), (0.0, 0.009, 0)]
    owners = [[1], [1, 2], [3], [4]]
    sel, gave = ga.footprint_owners(centres, owners, (0.0, 0.0, 0.0), 0.01)
    assert sel == [0, 1, 3] and gave == [1, 2, 4]
    # nothing within the radius: the nearest one at least
    sel, gave = ga.footprint_owners(centres, owners, (0.019, 0.0, 0.0), 0.0001)
    assert sel == [2] and gave == [3]
    assert ga.footprint_owners([], [], (0, 0, 0), 1.0) == ([], [])


def test_scalp_text():
    assert ga.scalp_text(0, False, 0, 0) == ""
    assert ga.scalp_text(2, True, 100, 100) == ""
    t = ga.scalp_text(1, False, 0, 0)
    assert "input 4" in t and "drawn lock stays at rest" in t
    t = ga.scalp_text(3, True, 90, 100)
    assert "90 points" in t and "rest scalp 100" in t and "3 drawn locks" in t


def test_spine_record_and_publish_record():
    data = _data_with_drawn()
    rec = ga.spine_record(data)
    assert rec == {"edited": ["g_01"], "drawn": ["g_drawn"]}
    pub = ga.publish_record("char_A", "v001", "a.usd", "s.hip", data, 10, "/obj/n")
    assert pub["spines"] == rec and pub["schema"] == model.SCHEMA


def test_spines_from_publish_brings_edits_by_name_and_drawn_locks_with_their_id():
    published = _data_with_drawn()
    drawn = published.locks[-1]
    fresh = GroomData(groups=[Group(id="g", name="G")],
                      locks=[Lock(id=1, name="g_01", group="g"), Lock(id=2, name="g_02", group="g")])
    fresh.note_ids()
    out, got = ga.spines_from_publish(fresh, published)
    assert got == {"edited": ["g_01"], "drawn": ["g_drawn"], "not_found": []}
    assert out.lock(1).spine == published.lock(1).spine and out.lock(1).handles == 5
    d = out.lock(drawn.id)                        # its id: no lock here ever had it (the id seeds its scatter)
    assert d is not None and d.drawn and d.curve == drawn.curve and d.width_cm == 2.0 and d.taper == 0.3
    assert out.regions_stale and "edits from a publish" in out.stale_why
    assert fresh.lock(1).spine == []              # input untouched
    # again: the drawn lock is there already, nothing doubles
    out2, got2 = ga.spines_from_publish(out, published)
    assert got2["drawn"] == [] and sum(lk.drawn for lk in out2.locks) == 1


def test_spines_from_publish_gives_a_new_id_when_the_id_was_used_here():
    published = _data_with_drawn()
    drawn = published.locks[-1]
    here = GroomData(groups=[Group(id="g", name="G")], locks=[Lock(id=1, name="g_01", group="g")])
    here.id_high = drawn.id + 5                    # that id was a lock here once: never used again
    out, got = ga.spines_from_publish(here, published)
    d = next(lk for lk in out.locks if lk.drawn)
    assert d.id > drawn.id + 5
    # a group the scene does not have: the drawn lock goes to one it has
    published.locks[-1].group = "elsewhere"
    out, _ = ga.spines_from_publish(GroomData(groups=[Group(id="g", name="G")]), published)
    assert next(lk for lk in out.locks if lk.drawn).group == "g"


def test_edit_attribute_names_match_the_network():
    """build_hda's VEX reads the names cook_assign writes (config's), and the inner node names the adapter reads
    exist in the network."""
    text = (ROOT / "tools/fx/grooming/build_hda.py").read_text(encoding="utf-8")
    assert 'f[]@%s' % config.ATTR_EDIT_CP in text and 'i@%s' % config.ATTR_EDITED in text
    for name in (ga.NODE_SPINES_MEASURED, ga.NODE_MESH_CARRIED, ga.NODE_ANIM_SCALP, "drawn_locks"):
        assert f'"{name}"' in text, name
    assert '"%s"' % ga.ATTR_DRAWN in text
    # every adapter function a Python SOP of the network calls exists
    for fn in set(re.findall(r"grooming_adapter\.(cook_\w+)\(", text)):
        assert callable(getattr(ga, fn, None)), fn


def test_v02b_functions_are_exported():
    for name in ("lock_handles", "lock_spines", "set_points", "reset_points", "rotate_points", "scale_points", "set_handle_count",
                 "redraw_lock", "draw_lock", "set_drawn", "delete_drawn_locks", "edited_ids", "drawn_ids",
                 "scalp_wired", "animated_scalp", "import_spines"):
        assert name in ga.__all__ and callable(getattr(ga, name)), name


def test_scalp_wired_parm_is_not_in_the_cache_key():
    assert "scalp_wired" in ga._KEY_SKIP_PARMS


def test_input_labels_are_four():
    import importlib
    import sys
    import types
    if "hou" not in sys.modules:
        sys.modules["hou"] = types.ModuleType("hou")       # build_hda imports hou at the top; nothing is built here
        try:
            bh = importlib.import_module("tools.fx.grooming.build_hda")
        finally:
            del sys.modules["hou"]
    else:
        bh = importlib.import_module("tools.fx.grooming.build_hda")
    assert bh.INPUT_LABELS[3] == "Animated scalp" and len(bh.INPUT_LABELS) == 4


def test_most_skin_group_is_the_group_that_gave_most():
    data = GroomData(groups=[Group(id="a", name="A"), Group(id="b", name="B")],
                     locks=[Lock(id=1, name="a_01", group="a"), Lock(id=2, name="b_01", group="b")])
    assert ga.most_skin_group(data, [[1], [2], [2], [1, 2]]) == "b"      # 2.5 against 1.5
    assert ga.most_skin_group(data, [[1], [2]]) == "a"                   # a tie: the lower id
    assert ga.most_skin_group(data, [[99]]) == "" and ga.most_skin_group(data, []) == ""


def test_give_back_frees_only_the_skin_the_deleted_lock_owned_alone():
    freed, kept = ga.give_back([[5], [5, 2], [3], []], {5})
    assert freed == [0] and kept == [[], [2], [3], []]


def test_gap_text_only_past_the_tolerance():
    assert ga._gap_text(0.2, 6, 0.25) == ""
    assert "0.61 cm" in ga._gap_text(0.61, 12, 0.25) and "12 handles" in ga._gap_text(0.61, 12, 0.25)


def test_drawn_locks_are_named_drawn_nn():
    assert ga.DRAWN_PREFIX == "drawn"
    assert logic.lock_name("drawn", ["drawn_01", "hair_bang_02"]) == "drawn_02"


# ---- t84: bad input never reaches groom_data (B-1, B-2, minors 1-3) ----

def _row(n=9, length=0.3):
    """A measured spine row (scene units) straight down -y from the origin, width axis +x."""
    P = np.array([(0.0, -length * i / (n - 1), 0.0) for i in range(n)])
    return {"P": P, "tangent": np.tile((0.0, -1.0, 0.0), (n, 1)), "axis": np.tile((1.0, 0.0, 0.0), (n, 1)), "prim": 0}


def _mesh_lock():
    data = GroomData(groups=[Group(id="g", name="G")],
                     locks=[Lock(id=1, name="g_01", group="g", root=(0, 0, 0), length=0.3)])
    return data, data.locks[0]


def _handles(lk, row, unit=100.0):
    return np.array(ga._handles_now(lk, row, unit)[0], dtype=float)


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -float("inf")])
def test_store_points_refuses_a_non_finite_handle_before_any_change(bad):
    data, lk = _mesh_lock()
    row = _row()
    H = _handles(lk, row)
    H[2, 1] = bad
    before = data.to_json()
    for space in ("frame", "points"):
        with pytest.raises(ValueError, match="finite"):
            ga._store_points(lk, row, H.tolist(), space, 100.0, data)
    assert data.to_json() == before and "NaN" not in before and not lk.edited


@pytest.mark.parametrize("k", [0, 1, 2, 3, 13, 100])
def test_store_points_refuses_a_handle_count_outside_4_to_12(k):
    data, lk = _mesh_lock()
    H = [(0.0, -0.01 * i, 0.0) for i in range(k)]
    with pytest.raises(ValueError):
        ga._store_points(lk, _row(), H, "frame", 100.0, data)
    assert not lk.edited


def test_store_points_refuses_a_handle_past_the_reach():
    data, lk = _mesh_lock()
    row = _row()
    H = _handles(lk, row)
    H[-1] = (0.0, -config.LOCK_REACH_MAX_CM / 100.0 * 1.01, 0.0)
    with pytest.raises(ValueError, match="LOCK_REACH_MAX_CM"):
        ga._store_points(lk, row, H.tolist(), "frame", 100.0, data)
    H[-1] = (0.0, -config.LOCK_REACH_MAX_CM / 100.0 * 0.99, 0.0)
    assert ga._store_points(lk, row, H.tolist(), "frame", 100.0, data) == (True, False)


def test_store_points_with_the_measured_handles_changes_nothing():
    # t84 minor 1: no write, so no undo step and "nothing changed"
    data, lk = _mesh_lock()
    row = _row()
    H = _handles(lk, row)
    assert ga._store_points(lk, row, (H + config.SPINE_STILL * 0.5).tolist(), "frame", 100.0, data) == (False, False)
    assert not lk.edited
    H[-1, 0] += config.SPINE_STILL * 10
    assert ga._store_points(lk, row, H.tolist(), "frame", 100.0, data) == (True, False) and lk.edited


def test_store_points_drawn_lock_unchanged_and_bad_values():
    data = _data_with_drawn()
    lk = next(x for x in data.locks if x.drawn)
    curve = np.array(lk.curve, dtype=float)
    # the drawn lock of _data_with_drawn has 3 places: give it 4 first
    four = np.vstack([curve, curve[-1] + (0, -0.1, 0)])
    assert ga._store_points(lk, None, four.tolist(), "points", 100.0, data)[0]
    assert ga._store_points(lk, None, four.tolist(), "points", 100.0, data) == (False, False)
    bad = four.copy()
    bad[1, 0] = float("nan")
    with pytest.raises(ValueError):
        ga._store_points(lk, None, bad.tolist(), "points", 100.0, data)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), "x", None, []])
def test_finite_guard(value):
    with pytest.raises(ValueError):
        ga._finite(value, "v")


def test_in_range_names_the_limit():
    assert ga._in_range(2, config.SCALE_RANGE, "scale factor") == 2.0
    for bad in (1e9, 0.0, -1.0, float("nan"), float("inf"), True):
        with pytest.raises(ValueError):
            ga._in_range(bad, config.SCALE_RANGE, "scale factor")
    with pytest.raises(ValueError, match="10"):
        ga._in_range(1e6, config.DRAWN_WIDTH_RANGE_CM, "width (cm)")


@pytest.mark.parametrize("factor", [1e9, 0, -1, float("nan"), float("inf"), 0.01, 11])
def test_scale_points_refuses_a_factor_outside_the_range_before_reading_the_node(factor):
    with pytest.raises(ValueError):
        ga.scale_points(None, [1], factor)


@pytest.mark.parametrize("axis, deg", [((float("nan"), 0, 0), 10), ((0, 1, 0), float("inf")), ((0, 1), 10)])
def test_rotate_points_refuses_non_finite_axis_or_degrees(axis, deg):
    with pytest.raises(ValueError):
        ga.rotate_points(None, [1], axis, deg)


@pytest.mark.parametrize("count", [7.5, "7", True, float("nan"), 3, 13])
def test_set_handle_count_refuses_a_non_whole_or_out_of_range_count(count):
    with pytest.raises(ValueError):
        ga.set_handle_count(None, [1], count)


def test_limits_live_in_config():
    assert config.SPINE_STILL == 1e-6 and ga.ROOT_SAME_CM == config.ROOT_SAME_CM
    assert config.DRAWN_ROOT_FADE == 0.25
    src = (ROOT / "tools/fx/grooming/build_hda.py").read_text(encoding="utf-8")
    assert "config.SPINE_STILL" in src and "\nSPINE_STILL =" not in src
