"""MONO Grooming pure logic: re-import matching, region split, publish version and paths, lock names."""

from __future__ import annotations

import errno
import os
import random

import pytest

from tools.fx.grooming import config, logic
from tools.fx.grooming.logic import MeshPiece, match_locks, split_regions
from tools.fx.grooming.model import Lock


# ---------------------------------------------------------------------------
# match_locks
# ---------------------------------------------------------------------------

def _locks() -> list[Lock]:
    return [
        Lock(id=1, name="fringe_01", group="mai", root=(0.0, 10.0, 0.0), length=4.0),
        Lock(id=2, name="fringe_02", group="mai", root=(3.0, 10.0, 0.0), length=4.0),
        Lock(id=5, name="back_01", group="gay", root=(0.0, 8.0, -6.0), length=20.0),
    ]


def _piece(index, name, root, length, direction=(0.0, -1.0, 0.0)) -> MeshPiece:
    return MeshPiece(index=index, name=name, root=root, length=length, direction=direction)


def _same_pieces() -> list[MeshPiece]:
    return [_piece(i, lk.name, lk.root, lk.length) for i, lk in enumerate(_locks())]


def _by_piece(report) -> dict[int, tuple[int, str]]:
    return {m.piece: (m.lock_id, m.status) for m in report.matches}


def test_match_same_mesh_is_all_ok():
    r = match_locks(_same_pieces(), _locks(), next_id=6)
    assert _by_piece(r) == {0: (1, "ok"), 1: (2, "ok"), 2: (5, "ok")}
    assert r.orphaned == []
    assert r.counts == {"ok": 3, "unsure": 0, "new": 0, "orphaned": 0}


def test_match_renamed_lock_matches_by_position_unsure():
    pieces = _same_pieces()
    pieces[1].name = "fringe_renamed"
    r = match_locks(pieces, _locks(), next_id=6)
    assert _by_piece(r)[1] == (2, "unsure")
    assert r.orphaned == []


def test_match_lock_moved_a_little_stays_ok():
    pieces = _same_pieces()
    pieces[0].root = (0.0, 10.0, 1.5)          # 1.5 < 0.5 x 4
    assert _by_piece(match_locks(pieces, _locks(), 6))[0] == (1, "ok")


def test_match_lock_moved_a_lot_keeps_id_but_unsure():
    pieces = _same_pieces()
    pieces[0].root = (0.0, 10.0, 30.0)         # far from everything, same name
    r = match_locks(pieces, _locks(), 6)
    assert _by_piece(r)[0] == (1, "unsure")


def test_match_unnamed_piece_moved_a_lot_is_new():
    pieces = _same_pieces()
    pieces[0].name = ""
    pieces[0].root = (0.0, 10.0, 30.0)
    r = match_locks(pieces, _locks(), 6)
    assert _by_piece(r)[0] == (6, "new")
    assert r.orphaned == [1]


def test_match_deleted_lock_goes_to_orphaned():
    pieces = [p for p in _same_pieces() if p.name != "fringe_02"]
    r = match_locks(pieces, _locks(), 6)
    assert r.orphaned == [2]
    assert {m.lock_id for m in r.matches} == {1, 5}


def test_match_two_pieces_near_one_lock_one_wins_other_new():
    locks = [Lock(id=1, name="fringe_01", group="mai", root=(0.0, 10.0, 0.0), length=4.0)]
    pieces = [
        _piece(0, "", (0.6, 10.0, 0.0), 4.0),
        _piece(1, "", (0.2, 10.0, 0.0), 4.0),   # closer
    ]
    r = match_locks(pieces, locks, next_id=2)
    assert _by_piece(r) == {1: (1, "unsure"), 0: (2, "new")}


def test_match_name_beats_position():
    # A piece named like lock 2 sits right on lock 1's root: the name wins, lock 1 stays free.
    locks = _locks()[:2]
    pieces = [_piece(0, "fringe_02", (0.1, 10.0, 0.0), 4.0)]
    r = match_locks(pieces, locks, next_id=6)
    assert _by_piece(r) == {0: (2, "unsure")}       # name match but root 2.9 away (> 0.5 x 4)
    assert r.orphaned == [1]


def test_match_shape_only_is_unsure():
    # Renamed and moved 0.6 x length (beyond the position rule) but same length and direction.
    locks = [Lock(id=3, name="side_01", group="mai", root=(0.0, 0.0, 0.0), length=10.0)]
    pieces = [_piece(0, "x", (6.0, 0.0, 0.0), 10.5)]
    assert _by_piece(match_locks(pieces, locks, 4)) == {0: (3, "unsure")}


def test_match_shape_uses_direction_when_lock_has_one():
    lk = Lock(id=3, name="side_01", group="mai", root=(0.0, 0.0, 0.0), length=10.0)
    lk.direction = (1.0, 0.0, 0.0)                   # type: ignore[attr-defined]
    pieces = [_piece(0, "x", (6.0, 0.0, 0.0), 10.0, direction=(0.0, -1.0, 0.0))]
    assert _by_piece(match_locks(pieces, [lk], 4)) == {0: (4, "new")}


def test_match_different_length_at_same_root_is_new():
    locks = [Lock(id=1, name="a", group="g", root=(0.0, 0.0, 0.0), length=4.0)]
    pieces = [_piece(0, "", (0.0, 0.0, 0.0), 20.0)]
    assert _by_piece(match_locks(pieces, locks, 2)) == {0: (2, "new")}


def test_match_is_scale_free():
    def run(scale):
        locks = [Lock(id=1, name="a", group="g", root=(0.0, 0.0, 0.0), length=4.0 * scale)]
        pieces = [_piece(0, "a", (1.5 * scale, 0.0, 0.0), 4.0 * scale),
                  _piece(1, "", (0.0, 50.0 * scale, 0.0), 4.0 * scale)]
        return _by_piece(match_locks(pieces, locks, 2))
    assert run(1.0) == run(0.01) == run(100.0) == {0: (1, "ok"), 1: (2, "new")}


def test_match_new_ids_count_up_in_piece_order():
    pieces = [_piece(3, "", (100.0, 0.0, 0.0), 1.0), _piece(1, "", (200.0, 0.0, 0.0), 1.0)]
    r = match_locks(pieces, [], next_id=10)
    assert [(m.piece, m.lock_id, m.status) for m in r.matches] == [(1, 10, "new"), (3, 11, "new")]


def test_match_empty_inputs():
    assert match_locks([], [], 1).matches == []
    r = match_locks([], _locks(), 6)
    assert r.matches == [] and r.orphaned == [1, 2, 5]
    r = match_locks(_same_pieces(), [], 1)
    assert [m.lock_id for m in r.matches] == [1, 2, 3] and r.counts["new"] == 3


def test_match_duplicate_names_closest_root_takes_the_lock():
    locks = [Lock(id=1, name="a", group="g", root=(0.0, 0.0, 0.0), length=4.0)]
    pieces = [_piece(0, "a", (1.0, 0.0, 0.0), 4.0), _piece(1, "a", (0.5, 0.0, 0.0), 4.0)]
    assert _by_piece(match_locks(pieces, locks, 2)) == {1: (1, "ok"), 0: (2, "new")}


def test_match_zero_length_lock_does_not_crash():
    locks = [Lock(id=1, name="a", group="g", root=(0.0, 0.0, 0.0), length=0.0)]
    pieces = [_piece(0, "a", (0.0, 0.0, 0.0), 0.0), _piece(1, "", (1.0, 0.0, 0.0), 0.0)]
    assert _by_piece(match_locks(pieces, locks, 2)) == {0: (1, "ok"), 1: (2, "new")}


# ---------------------------------------------------------------------------
# split_regions
# ---------------------------------------------------------------------------

def test_split_nearest_root_within_group():
    pts = [(0.0, 0.0, 0.0), (0.9, 0.0, 0.0), (5.0, 0.0, 0.0), (0.0, 0.0, 0.0)]
    roots = {1: (0.0, 0.0, 0.0), 2: (1.0, 0.0, 0.0), 3: (0.1, 0.0, 0.0)}
    groups = {1: "mai", 2: "mai", 3: "gay"}
    out = split_regions(pts, roots, groups, ["mai", "mai", "mai", "gay"])
    assert out == [1, 2, 2, 3]


def test_split_group_without_lock_has_no_owner():
    out = split_regions([(0.0, 0.0, 0.0), (1.0, 0.0, 0.0)], {1: (0.0, 0.0, 0.0)}, {1: "mai"}, ["mai", "tai"])
    assert out == [1, config.NO_OWNER]


def test_split_ignores_closer_lock_of_another_group():
    out = split_regions([(0.0, 0.0, 0.0)], {1: (0.1, 0.0, 0.0), 2: (5.0, 0.0, 0.0)},
                        {1: "gay", 2: "mai"}, ["mai"])
    assert out == [2]


def test_split_tie_goes_to_lowest_id():
    out = split_regions([(0.0, 0.0, 0.0)], {7: (1.0, 0.0, 0.0), 3: (-1.0, 0.0, 0.0)},
                        {7: "g", 3: "g"}, ["g"])
    assert out == [3]


def test_split_empty_inputs():
    assert split_regions([], {}, {}, []) == []
    assert split_regions([(0.0, 0.0, 0.0)], {}, {}, ["g"]) == [config.NO_OWNER]


def test_split_length_mismatch_raises():
    with pytest.raises(ValueError):
        split_regions([(0.0, 0.0, 0.0)], {}, {}, [])


def test_split_pure_python_matches_numpy():
    pytest.importorskip("numpy")
    rng = random.Random(4)
    pts = [(rng.random(), rng.random(), rng.random()) for _ in range(2000)]
    groups = [rng.choice("abc") for _ in pts]
    roots = {i: (rng.random(), rng.random(), rng.random()) for i in range(1, 31)}
    gof = {i: rng.choice("ab") for i in roots}
    assert logic._split_numpy(pts, roots, gof, groups) == logic._split_python(pts, roots, gof, groups)


def test_split_50k_points_100_locks_is_fast():
    import time
    rng = random.Random(1)
    pts = [(rng.uniform(-10, 10), rng.uniform(0, 20), rng.uniform(-10, 10)) for _ in range(50_000)]
    groups = [rng.choice(("mai", "gay", "mai_trai", "mai_phai", "tai")) for _ in pts]
    roots = {i: (rng.uniform(-10, 10), rng.uniform(0, 20), rng.uniform(-10, 10)) for i in range(1, 101)}
    gof = {i: rng.choice(("mai", "gay", "mai_trai", "mai_phai")) for i in roots}
    t = time.perf_counter()
    out = split_regions(pts, roots, gof, groups)
    assert time.perf_counter() - t < 5.0
    assert len(out) == 50_000
    assert all(o == config.NO_OWNER for o, g in zip(out, groups) if g == "tai")


# ---------------------------------------------------------------------------
# publish_version
# ---------------------------------------------------------------------------

def _vs(n):
    return [f"v{i:03d}" for i in range(1, n + 1)]


def test_version_from_scene_when_free_and_newer():
    assert logic.publish_version("char_Helen_grooming_v007", _vs(6)) == ("v007", "")


def test_version_taken_proposes_next_with_note():
    v, note = logic.publish_version("char_Helen_grooming_v007", _vs(7))
    assert v == "v008"
    assert "v007" in note and "v008" in note


def test_version_older_than_newest_publish():
    v, note = logic.publish_version("char_Helen_grooming_v005", ["v001", "v009"])
    assert v == "v010" and "v009" in note


def test_version_scene_without_version_takes_next_free():
    v, note = logic.publish_version("char_Helen_grooming", _vs(3))
    assert v == "v004" and note


def test_version_no_publish_yet():
    assert logic.publish_version("char_Helen_grooming_v002", []) == ("v002", "")
    v, note = logic.publish_version("untitled", [])
    assert v == "v001" and note


def test_version_ignores_extension_and_junk_folders():
    assert logic.publish_version("char_Helen_grooming_v012.hiplc", ["v003", "_grooming", "old", "v010"]) == ("v012", "")


def test_version_keeps_wider_padding():
    assert logic.publish_version("a_v1000", ["v999"]) == ("v1000", "")


# ---------------------------------------------------------------------------
# publish_paths
# ---------------------------------------------------------------------------

def test_paths_walk_up_from_work_folder():
    usd, data = logic.publish_paths("D:/proj/assets/char_Helen/04_grooming/houdini/work", "char_Helen", "v007")
    assert usd == "D:/proj/assets/char_Helen/04_grooming/publish/v007/char_Helen_grooming_publish.usd"
    assert data == "D:/proj/assets/char_Helen/04_grooming/publish/v007/_grooming"


def test_paths_windows_backslashes_and_spaces():
    usd, data = logic.publish_paths(r"E:\01 Dev\my project\char_Helen\04_grooming\houdini\work\\",
                                    "char_Helen", "v008")
    assert usd == "E:/01 Dev/my project/char_Helen/04_grooming/publish/v008/char_Helen_grooming_publish.usd"
    assert data == "E:/01 Dev/my project/char_Helen/04_grooming/publish/v008/_grooming"


def test_paths_scene_directly_in_department():
    usd, _ = logic.publish_paths("/mnt/p/char_Helen/04_grooming", "char_Helen", "v001")
    assert usd == "/mnt/p/char_Helen/04_grooming/publish/v001/char_Helen_grooming_publish.usd"


def test_paths_uses_innermost_department_folder():
    usd, _ = logic.publish_paths("D:/04_grooming/char_A/04_grooming/work", "char_A", "v002")
    assert usd.startswith("D:/04_grooming/char_A/04_grooming/publish/v002/")


def test_paths_unc_share():
    usd, _ = logic.publish_paths(r"\\nas\job\char_Helen\04_grooming\houdini", "char_Helen", "v003")
    assert usd == "//nas/job/char_Helen/04_grooming/publish/v003/char_Helen_grooming_publish.usd"


def test_paths_outside_department_raises():
    with pytest.raises(ValueError):
        logic.publish_paths("D:/proj/char_Helen/03_lookdev/work", "char_Helen", "v001")


def test_paths_bad_version_raises():
    with pytest.raises(ValueError):
        logic.publish_paths("D:/p/char_Helen/04_grooming/work", "char_Helen", "7")


# ---------------------------------------------------------------------------
# lock_name
# ---------------------------------------------------------------------------

def test_lock_name_first():
    assert logic.lock_name("fringe", []) == "fringe_01"


def test_lock_name_after_highest_not_in_gap():
    assert logic.lock_name("fringe", ["fringe_01", "fringe_03", "back_07"]) == "fringe_04"


def test_lock_name_beyond_two_digits():
    assert logic.lock_name("f", [f"f_{i:02d}" for i in range(1, 100)]) == "f_100"


def test_lock_name_ignores_other_shapes():
    assert logic.lock_name("fringe", ["fringe_x", "fringe_02b", "fringe"]) == "fringe_01"


def test_lock_name_empty_prefix():
    assert logic.lock_name("", ["lock_01"]) == "lock_02"


# ---- region_owners: footprint split, stacked locks share ----

def test_region_owners_stacked_locks_share_their_patch():
    # Two fringe layers 2 mm apart with 3 cm wide roots (radius 1.5 cm) over the same scalp points,
    # and a third lock far away: nearest-root would give the patch to one layer only.
    pts = [(0.0, 0.0, 0.0), (0.005, 0.0, 0.0), (0.01, 0.0, 0.0), (0.2, 0.0, 0.0)]
    roots = {1: (0.0, 0.0, 0.0), 2: (0.002, 0.0, 0.0), 3: (0.2, 0.0, 0.0)}
    radii = {1: 0.015, 2: 0.015, 3: 0.015}
    groups = {1: "bang", 2: "bang", 3: "bang"}
    owners = logic.region_owners(pts, roots, radii, groups, ["bang"] * 4)
    assert set(owners[0]) == set(owners[1]) == set(owners[2]) == {1, 2}
    assert owners[3] == [3]
    assert owners[1][0] == 2          # nearest first (0.003 from lock 2, 0.005 from lock 1)


def test_region_owners_point_outside_every_footprint_goes_to_nearest():
    owners = logic.region_owners([(0.1, 0, 0), (0.3, 0, 0)], {1: (0, 0, 0), 2: (0.3, 0, 0)},
                                 {1: 0.01, 2: 0.01}, {1: "g", 2: "g"}, ["g", "g"])
    assert owners == [[1], [2]]


def test_region_owners_every_lock_gets_a_point_and_groups_stay_apart():
    # Lock 2 is crowded out (its footprint has no point and no point is nearest to it) but still
    # gets its nearest point; lock 3 is in another group and never takes "g" points.
    pts = [(0, 0, 0), (0.01, 0, 0)]
    roots = {1: (0, 0, 0), 2: (0.004, 0, 0.05), 3: (0.01, 0, 0)}
    owners = logic.region_owners(pts, roots, {1: 0.02, 2: 0.0, 3: 0.02}, {1: "g", 2: "g", 3: "h"},
                                 ["g", "g"])
    flat = [lid for o in owners for lid in o]
    assert 2 in flat and 3 not in flat


def test_region_owners_point_in_group_without_locks_has_none():
    assert logic.region_owners([(0, 0, 0)], {1: (0, 0, 0)}, {1: 1.0}, {1: "g"}, ["other"]) == [[]]


def test_section_floor_counts_flat_ribbons_and_converging_locks():
    # 2 cm wide flat ribbon (thickness 0) in metres: thickness counted as 0.6 cm
    s = logic.section_cm2(0.02, 0.0, 100.0)
    assert s == pytest.approx(3.14159 / 4 * 2.0 * 0.6, rel=1e-4)
    assert logic.lock_strands(150.0, 0.01, s) == round(150 * s)    # tiny shared patch: floor wins
    assert logic.lock_strands(150.0, 5.0, s) == 750                 # wide region: the scalp rule
    assert logic.lock_strands(150.0, 0.0, s) == 0                   # no region, no hair


def test_publish_paths_one_spelling_per_version():
    a, _ = logic.publish_paths("D:/p/char_Helen/04_grooming/houdini/work", "char_Helen", "V7")
    b, _ = logic.publish_paths("D:/p/char_Helen/04_grooming/houdini/work", "char_Helen", "v007")
    assert a == b and "/publish/v007/" in a


# ---- region_owners: past the footprints, the lock whose mesh lies over the scalp ----
# Every lock also gets a point on its own root, so the point tested is the only one in question.

def _with_roots(pt, near, roots):
    pts = [pt] + [roots[lid] for lid in sorted(roots)]
    return pts, [near] + [[] for _ in roots]


def test_region_owners_scalp_goes_to_the_mesh_lying_over_it_not_the_nearest_root():
    # Lock 1's root is nearer the point, but lock 2's mesh lies over it (Helen: 0.8 cm fringe locks
    # owned 8 x 8 cm of scalp by nearest root, while other locks' meshes lay over it).
    roots = {1: (0.0, 0, 0), 2: (0.2, 0, 0)}
    pts, near = _with_roots((0.05, 0, 0), [(0.04, 1), (0.002, 2)], roots)
    owners = logic.region_owners(pts, roots, {1: 0.01, 2: 0.01}, {1: "g", 2: "g"}, ["g"] * 3, near)
    assert owners[0] == [2]


def test_region_owners_footprint_comes_before_the_mesh():
    # A cap lying over another one's root: the root area stays with the lock rooted there.
    roots = {1: (0.0, 0, 0), 2: (0.3, 0, 0)}
    pts, near = _with_roots((0.005, 0, 0), [(0.001, 2), (0.01, 1)], roots)
    owners = logic.region_owners(pts, roots, {1: 0.02, 2: 0.02}, {1: "g", 2: "g"}, ["g"] * 3, near)
    assert owners[0] == [1]


def test_region_owners_layered_meshes_share_within_mesh_share():
    roots = {1: (0, 0, 0), 2: (0.3, 0, 0), 3: (0.5, 0, 0)}
    radii = {1: 0.01, 2: 0.01, 3: 0.01}
    groups = {1: "g", 2: "g", 3: "g"}
    pts, near = _with_roots((0.1, 0, 0), [(0.0030, 1), (0.0035, 2), (0.02, 3)], roots)
    assert logic.region_owners(pts, roots, radii, groups, ["g"] * 4, near, mesh_share=0.001)[0] == [1, 2]
    assert logic.region_owners(pts, roots, radii, groups, ["g"] * 4, near, mesh_share=0.0)[0] == [1]


def test_region_owners_mesh_of_another_group_or_an_excluded_lock_is_ignored():
    roots = {1: (0, 0, 0), 2: (0.3, 0, 0), 3: (0.6, 0, 0)}
    pts, near = _with_roots((0.1, 0, 0), [(0.001, 3), (0.002, 9), (0.05, 2)], roots)  # 9: excluded
    owners = logic.region_owners(pts, roots, {1: 0.01, 2: 0.01, 3: 0.01}, {1: "g", 2: "g", 3: "h"},
                                 ["g", "g", "g", "h"], near)
    assert owners[0] == [2]


def test_region_owners_needs_one_mesh_list_per_point():
    import pytest
    with pytest.raises(ValueError):
        logic.region_owners([(0, 0, 0), (1, 0, 0)], {1: (0, 0, 0)}, {1: 0.1}, {1: "g"}, ["g", "g"], [[]])


# ---- whorls: locks whose roots converge on one spot ----

def test_whorls_finds_locks_starting_at_one_spot_with_its_centre():
    roots = {1: (0.0, 0, 0), 2: (0.01, 0, 0), 3: (0.0, 0.01, 0), 4: (0.5, 0, 0)}
    out = logic.whorls(roots, radius=0.015, min_locks=3)
    assert set(out) == {1, 2, 3}
    cx, cy, _ = out[1]
    assert abs(cx - 0.01 / 3) < 1e-9 and abs(cy - 0.01 / 3) < 1e-9


def test_whorls_needs_min_locks_and_none_alone():
    roots = {1: (0.0, 0, 0), 2: (0.01, 0, 0), 3: (0.3, 0, 0)}
    assert logic.whorls(roots, radius=0.015, min_locks=3) == {}
    assert set(logic.whorls(roots, radius=0.015, min_locks=2)) == {1, 2}


def test_floating_text_lists_the_worst_roots_first() -> None:
    assert logic.floating_text([]) == ""
    one = logic.floating_text([("hair_base_17", 0.58)])
    assert one.startswith("1 lock root off the skin (hair_base_17 0.6 cm)")
    many = logic.floating_text([(f"l{i}", 0.3 + i / 10) for i in range(8)], shown=3)
    assert "(l7 1.0 cm, l6 0.9 cm, l5 0.8 cm and 5 more)" in many


def test_falloff_fades_between_the_two_heights() -> None:
    assert logic.falloff(0.2, 0.5, 0.5) == 0.0
    assert logic.falloff(0.5, 0.5, 0.5) == 0.5
    assert logic.falloff(0.8, 0.5, 0.5) == 1.0
    assert 0.0 < logic.falloff(0.4, 0.5, 0.5) < 0.5 < logic.falloff(0.6, 0.5, 0.5) < 1.0


# ---------------------------------------------------------------------------
# StagedFiles: publish writes temp names, renames at the end, cleans up only its own
# ---------------------------------------------------------------------------

def _publish_dirs(tmp_path):
    usd, tool = logic.publish_paths(str(tmp_path / "char_A" / "04_grooming" / "work"), "char_A", "v003")
    return usd, tool


def test_staged_files_rename_only_at_commit(tmp_path) -> None:
    usd, tool = _publish_dirs(tmp_path)
    s = logic.StagedFiles(token="t1")
    s.make_dirs(tool)
    usd_tmp = s.stage(usd, last=True)
    assert os.path.dirname(usd_tmp) == os.path.dirname(usd) and usd_tmp.endswith(".tmp.usd")
    open(usd_tmp, "w").write("usd")
    s.write_text(tool + "/publish.json", "{}")
    assert not os.path.exists(usd) and not os.path.exists(tool + "/publish.json")
    s.commit()
    assert open(usd).read() == "usd" and open(tool + "/publish.json").read() == "{}"
    assert sorted(os.listdir(os.path.dirname(usd))) == ["_grooming", "char_A_grooming_publish.usd"]


def test_staged_files_usd_renamed_last(tmp_path, monkeypatch) -> None:
    usd, tool = _publish_dirs(tmp_path)
    s = logic.StagedFiles()
    s.make_dirs(tool)
    open(s.stage(usd, last=True), "w").write("usd")
    s.write_text(tool + "/grooming_data.json", "{}")
    s.write_text(tool + "/publish.json", "{}")
    done = []
    real = os.replace
    monkeypatch.setattr(logic.os, "replace", lambda a, b: (done.append(os.path.basename(b)), real(a, b)))
    s.commit()
    assert done == ["grooming_data.json", "publish.json", "char_A_grooming_publish.usd"]


def test_abort_mid_commit_leaves_nothing_and_removes_new_folders(tmp_path, monkeypatch) -> None:
    usd, tool = _publish_dirs(tmp_path)
    publish_dir = os.path.dirname(os.path.dirname(usd))
    os.makedirs(publish_dir + "/v002")
    open(publish_dir + "/v002/old.usd", "w").write("old")
    open(publish_dir + "/v002/x.t9.tmp.usd", "w").write("someone else's temp")
    s = logic.StagedFiles(token="t9")
    s.make_dirs(tool)
    open(s.stage(usd, last=True), "w").write("usd")
    s.write_text(tool + "/publish.json", "{}")
    real = os.replace
    calls = []

    def flaky(a, b):
        calls.append(b)
        if len(calls) == 2:
            raise OSError(errno.ENOSPC, "No space left on device", b)
        real(a, b)

    monkeypatch.setattr(logic.os, "replace", flaky)
    with pytest.raises(OSError):
        s.commit()
    assert s.abort() == []
    assert sorted(os.listdir(publish_dir)) == ["v002"]          # v003 and _grooming were ours: gone
    assert sorted(os.listdir(publish_dir + "/v002")) == ["old.usd", "x.t9.tmp.usd"]  # untouched


def test_abort_keeps_folders_that_existed(tmp_path) -> None:
    usd, tool = _publish_dirs(tmp_path)
    os.makedirs(os.path.dirname(usd))
    s = logic.StagedFiles()
    s.make_dirs(tool)
    s.write_text(tool + "/publish.json", "{}")
    s.abort()
    assert os.path.isdir(os.path.dirname(usd)) and os.listdir(os.path.dirname(usd)) == []


def test_commit_never_overwrites(tmp_path) -> None:
    usd, tool = _publish_dirs(tmp_path)
    s = logic.StagedFiles()
    s.make_dirs(tool)
    open(s.stage(usd, last=True), "w").write("new")
    open(usd, "w").write("published meanwhile")
    with pytest.raises(FileExistsError):
        s.commit()
    s.abort()
    assert open(usd).read() == "published meanwhile"   # not ours: kept
    assert os.listdir(os.path.dirname(usd)) == ["char_A_grooming_publish.usd"]


def test_commit_refuses_a_temp_that_was_never_written(tmp_path) -> None:
    usd, tool = _publish_dirs(tmp_path)
    s = logic.StagedFiles()
    s.make_dirs(tool)
    s.stage(usd, last=True)
    with pytest.raises(FileNotFoundError):
        s.commit()


@pytest.mark.parametrize("exc, want", [
    (OSError(errno.ENOSPC, "No space left on device", "D:/p/x.usd"), "the disk is full: D:/p/x.usd"),
    (PermissionError(errno.EACCES, "Permission denied", "D:/p"), "the folder is not writable: D:/p"),
    (OSError(errno.EROFS, "Read-only file system", "/mnt/p"), "the folder is not writable: /mnt/p"),
    (FileExistsError(errno.EEXIST, "exists", "D:/p/x.usd"), "already published, not overwritten: D:/p/x.usd"),
    (RuntimeError("Error writing layer: No space left on device"), "the disk is full ("),
    (RuntimeError("Unable to open file: Permission denied"), "the folder is not writable ("),
    (RuntimeError("USD export wrote no file"), "USD export wrote no file"),
    (OSError(errno.EACCES, "Access is denied", r"D:\p\v003"), "the folder is not writable: D:/p/v003"),
])
def test_publish_error_names_what_the_artist_can_fix(exc, want) -> None:
    assert logic.publish_error(exc).startswith(want)


def test_make_dirs_says_when_a_file_is_in_the_way(tmp_path) -> None:
    usd, tool = _publish_dirs(tmp_path)
    publish_dir = os.path.dirname(os.path.dirname(usd))
    os.makedirs(os.path.dirname(publish_dir))
    open(publish_dir, "w").write("not a folder")
    with pytest.raises(NotADirectoryError) as e:
        logic.StagedFiles().make_dirs(tool)
    msg = logic.publish_error(e.value)
    assert msg.startswith("a file is in the way, not a folder: ") and "\\" not in msg and msg.endswith("/publish")


# ---- v0.2a density layers: one kind, "= D strands / cm2" ----

class _L:
    """A layer row as mask_compose reads it."""

    def __init__(self, id, value=0.0, opacity=1.0, on=True, kind="fill", parent=None, scope="all", group="", locks=()):
        self.id, self.value, self.opacity, self.on, self.kind, self.parent = id, value, opacity, on, kind, parent
        self.scope, self.group, self.locks = scope, group, list(locks)

    def applies(self, lock_id, group_id):
        if self.scope == "group":
            return group_id == self.group
        if self.scope == "locks":
            return lock_id in self.locks
        return True


def test_no_blend_modes_are_left():
    assert not hasattr(config, "MASK_MODES") and not hasattr(config, "MASK_UNITS")
    assert config.MASK_KINDS == ("fill", "folder")
    for gone in ("mask_blend", "mask_over", "mask_factor", "mask_is_absolute", "mask_layer_value", "far_chance"):
        assert not hasattr(logic, gone)
    assert all(d >= 0 for d in config.MASK_DENSITY_PICKS) and 0.0 in config.MASK_DENSITY_PICKS    # densities


@pytest.mark.parametrize("automatic", [0.0, 60.0, 150.0, 7000.0])
@pytest.mark.parametrize("D", [0.0, 40.0, 120.0, 300.0])
def test_painted_d_gives_d_whatever_the_automatic_density(automatic, D):
    keep, add = logic.mask_compose([(_L(0, D), 1.0)])
    assert logic.mask_density(automatic, keep, add) == pytest.approx(D)
    keep, add = logic.mask_compose([(_L(0, D), 0.0)])                  # black: the automatic groom
    assert keep == 1.0 and add == 0.0 and logic.mask_density(automatic, keep, add) == automatic


@pytest.mark.parametrize("mask, opacity", [(0.5, 1.0), (1.0, 0.5), (0.25, 1.0), (0.5, 0.5), (0.8, 0.9)])
def test_grey_mask_or_opacity_lies_between_by_the_coverage(mask, opacity):
    automatic, D = 180.0, 40.0
    keep, add = logic.mask_compose([(_L(0, D, opacity), mask)])
    coverage = mask * opacity
    assert logic.mask_density(automatic, keep, add) == pytest.approx(automatic + (D - automatic) * coverage)
    assert keep == pytest.approx(1.0 - coverage)


def test_layers_run_bottom_to_top_the_upper_one_wins_where_it_covers():
    low, high = _L(0, 40.0), _L(1, 300.0)
    keep, add = logic.mask_compose([(low, 1.0), (high, 1.0)])
    assert keep == 0.0 and add == pytest.approx(300.0)
    keep, add = logic.mask_compose([(low, 1.0), (high, 0.5)])
    assert keep == 0.0 and add == pytest.approx(170.0)                 # half way from 40 to 300
    keep, add = logic.mask_compose([(low, 0.5), (high, 0.5)])
    assert keep == pytest.approx(0.25) and add == pytest.approx(20.0 * 0.5 + 150.0)
    off = _L(1, 300.0, on=False)
    assert logic.mask_compose([(low, 1.0), (off, 1.0)]) == (0.0, 40.0)


def test_mask_compose_on_arrays():
    np = pytest.importorskip("numpy")
    a = np.array([0.0, 1.0, 0.5, 1.0], np.float32)
    b = np.array([0.0, 0.0, 1.0, 1.0], np.float32)
    keep, add = logic.mask_compose([(_L(0, 40.0), a), (_L(1, 300.0, 0.5), b)], np.ones(4, np.float32))
    for i in range(4):
        k, d = logic.mask_compose([(_L(0, 40.0), float(a[i])), (_L(1, 300.0, 0.5), float(b[i]))])
        assert keep[i] == pytest.approx(k) and add[i] == pytest.approx(d)
    assert keep[0] == 1.0 and add[0] == 0.0


def test_a_folders_mask_and_opacity_apply_to_all_its_layers():
    folder = _L(9, kind="folder")
    a, b = _L(1, 40.0, parent=9), _L(2, 300.0, parent=9)
    rows = [(folder, 1.0), (a, 1.0), (b, 0.5)]
    keep, add = logic.mask_compose(rows)
    assert keep == 0.0 and add == pytest.approx(170.0)
    # the folder's mask black: nothing of its layers
    assert logic.mask_compose([(folder, 0.0), (a, 1.0), (b, 0.5)]) == (1.0, 0.0)
    # half: half way between the automatic groom and what the folder makes
    keep, add = logic.mask_compose([(folder, 0.5), (a, 1.0), (b, 0.5)])
    assert keep == pytest.approx(0.5) and add == pytest.approx(85.0)
    folder.opacity = 0.5
    assert logic.mask_compose(rows) == pytest.approx((0.5, 85.0))
    folder.on = False
    assert logic.mask_compose(rows) == (1.0, 0.0)
    # a layer whose parent is not a folder of the rows counts as outside any
    assert logic.mask_compose([(a, 1.0)]) == (0.0, 40.0)


def test_mask_scope_sets_share_one_cover_between_locks_with_the_same_layers():
    masks = [_L(0, 40.0), _L(1, 80.0, scope="group", group="bang"), _L(2, 0.0, scope="locks", locks=[5]),
             _L(3, 9.0, on=False)]
    sets, of = logic.mask_scope_sets(masks, [(1, "back"), (2, "bang"), (3, "bang"), (5, "back")])
    assert sets == [(0,), (0, 1), (0, 2)]
    assert of == {1: 0, 2: 1, 3: 1, 5: 2}
    sets, of = logic.mask_scope_sets([masks[1]], [(1, "back"), (2, "bang")])
    assert sets == [(1,)] and of == {1: -1, 2: 0}
    folder = _L(9, kind="folder", on=False)
    inside = _L(4, 40.0, parent=9)
    sets, of = logic.mask_scope_sets([folder, inside], [(1, "back")])
    assert sets == [] and of == {1: -1}                                # a folder that is off: its layers reach nothing
    folder.on = True
    sets, of = logic.mask_scope_sets([folder, inside], [(1, "back")])
    assert sets == [(9, 4)]


def test_brush_weights_soft_edge():
    assert logic.brush_weights(0.0, 1.0, 0.5) == 1.0 and logic.brush_weights(0.5, 1.0, 0.5) == 1.0
    assert logic.brush_weights(1.0, 1.0, 0.5) == 0.0 and logic.brush_weights(2.0, 1.0, 0.5) == 0.0
    assert 0.0 < logic.brush_weights(0.9, 1.0, 0.5) < logic.brush_weights(0.6, 1.0, 0.5) < 1.0
    assert logic.brush_weights(0.99, 1.0, 0.0) == 1.0                   # hard edge
    np = pytest.importorskip("numpy")
    w = logic.brush_weights(np.array([0.0, 0.75, 1.5]), 1.0, 0.5)
    assert w[0] == 1.0 and w[1] == pytest.approx(0.5) and w[2] == 0.0


def test_density_color_is_fine_round_the_set_density_and_reaches_the_crown():
    ref = 150.0
    c0, c1, c2 = (logic.density_color(d, ref) for d in (0.0, 150.0, 300.0))
    assert sum(c0) < 0.2 and c1[1] > c1[0] and c1[1] > c1[2]            # near black; green at the set density
    assert c2[0] > c2[2] and c2 != c1                                    # yellow at twice it
    crown, v006 = logic.density_color(7059.0, ref), logic.density_color(5104.0, ref)
    assert crown != v006 and max(abs(a - b) for a, b in zip(crown, v006)) > 0.02
    assert logic.density_color(1e9, ref) == pytest.approx((1.0, 1.0, 1.0))
    assert logic.density_color(10.0, 0.0)                                # no reference: no crash


def test_layer_color_shows_one_mask_alone():
    assert logic.layer_color(1.0) == pytest.approx((1.0, 1.0, 1.0))
    assert logic.layer_color(0.0) == pytest.approx(logic.LAYER_UNPAINTED)
    mid = logic.layer_color(0.5)
    assert logic.LAYER_UNPAINTED[0] < mid[0] < 1.0
