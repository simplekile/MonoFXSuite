"""MONO Grooming pure logic: re-import matching, region split, publish version and paths, lock names."""

from __future__ import annotations

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
