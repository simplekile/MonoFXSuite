"""MONO Grooming v0.2b, B1: schema 7 (control points, drawn locks) and the pure control-point logic. No `hou`.

The measured spines in `fixtures/grooming/t76_spines.json` are three of Helen's (49 points, scene units, metres:
unit_cm 100) from the spike t76 (`out/q4/spines.npz`): hair_bang_11 (the spike's fringe lock, 17.6 cm),
hair_back_20 (the longest, 89.6 cm), hair_base_20 (24.0 cm, the most strands). The fixture holds positions only:
tangents are taken from the points and the width axis is carried along without twist, as a stand-in for the
network's `tangentu` / `lock_axis`.
"""

import json
import math
from pathlib import Path

import numpy as np
import pytest

from tools.fx.grooming import config, logic
from tools.fx.grooming.model import SCHEMA, GroomData, Group, Lock, Orphan, migrate

FIXTURE = Path(__file__).parent / "fixtures" / "grooming" / "t76_spines.json"
_FIX = json.loads(FIXTURE.read_text())
UNIT = _FIX["unit_cm"]
NAMES = sorted(_FIX["spines"])


def _frame(P):
    """Tangents from the points (central differences) and a width axis carried along without twist."""
    n = len(P)
    T = P[np.minimum(np.arange(n) + 1, n - 1)] - P[np.maximum(np.arange(n) - 1, 0)]
    T /= np.linalg.norm(T, axis=1)[:, None]
    a = np.cross(T[0], [0.0, 1.0, 0.0])
    A = np.zeros_like(P)
    for i in range(n):
        a = a - T[i] * np.dot(a, T[i])
        a /= np.linalg.norm(a)
        A[i] = a
    return T, A


SPINES = {}
for _n in NAMES:
    _P = np.asarray(_FIX["spines"][_n], float)
    SPINES[_n] = (_P,) + _frame(_P)


def _cm(P):
    return logic.arc_lengths(P)[-1] * UNIT


# ---- the spike's VEX, transcribed line by line (build_proto.py VEX_SPINE_EDIT): the reference ----

def _vex(P, T, A, cp, scalp=None):
    n, K = len(P), len(cp)
    S = [0.0]
    for i in range(1, n):
        S.append(S[-1] + float(np.linalg.norm(P[i] - P[i - 1])))
    L = max(S[-1], 1e-9)
    t0 = T[0] / np.linalg.norm(T[0])
    a0 = A[0] - t0 * np.dot(A[0], t0)
    a0 = a0 / np.linalg.norm(a0)
    m0 = np.cross(t0, a0)
    D = []
    j = 0
    for k in range(K):
        sk = L * k / (K - 1)
        while j < n - 2 and S[j + 1] < sk:
            j += 1
        f = min(max((sk - S[j]) / max(S[j + 1] - S[j], 1e-12), 0.0), 1.0)
        mk = P[j] * (1 - f) + P[j + 1] * f
        ck = P[0] + t0 * cp[k][0] + a0 * cp[k][1] + m0 * cp[k][2]
        if k == 0 and scalp is not None and np.linalg.norm(cp[0]) > 1e-7:
            ck = scalp(ck)
        D.append(ck - mk)
    N = []
    for i in range(n):
        x = S[i] / L * (K - 1)
        k = min(int(math.floor(x)), K - 2)
        f = x - k
        p0, p1, p2, p3 = D[max(k - 1, 0)], D[k], D[k + 1], D[min(k + 2, K - 1)]
        d = 0.5 * ((2 * p1) + (-p0 + p2) * f + (2 * p0 - 5 * p1 + 4 * p2 - p3) * f * f
                   + (-p0 + 3 * p1 - 3 * p2 + p3) * f * f * f)
        N.append(P[i] + d)
    N = np.array(N)
    axes = []
    for i in range(n):
        tn = N[min(i + 1, n - 1)] - N[max(i - 1, 0)]
        tn /= np.linalg.norm(tn)
        told = T[i] / np.linalg.norm(T[i])
        a = A[i] - told * np.dot(A[i], told)
        a /= np.linalg.norm(a)
        ax = np.cross(told, tn)                      # dihedral(told, tn) applied by Rodrigues
        s, c = np.linalg.norm(ax), np.dot(told, tn)
        if s > 1e-12:
            ax /= s
            a = a * c + np.cross(ax, a) * s + ax * np.dot(ax, a) * (1 - c)
        a = a - tn * np.dot(a, tn)
        axes.append(a / np.linalg.norm(a))
    return N, np.array(axes)


def _bend(H, cm):
    """The spike's 2 cm tip move: the outer handles pushed along the width axis, more toward the tip."""
    c = np.array(H, float)
    K = len(c)
    for k in range(1, K):
        c[k, 1] += cm / UNIT * (k / (K - 1)) ** 2
    return c


def _turn(H, deg):
    """The spike's 25 deg turn: the whole lock about its root, round the thickness axis."""
    c = np.array(H, float)
    a = np.radians(deg)
    rot = np.array([[np.cos(a), -np.sin(a), 0], [np.sin(a), np.cos(a), 0], [0, 0, 1]])
    return c[0] + (c - c[0]) @ rot.T


# ---- schema 7 ----

SIX = {"schema": 6, "asset": "char_Helen", "defaults": {"density": 140.0}, "id_high": 3,
       "groups": [{"id": "bang", "name": "Bang", "color": [0.9, 0.2, 0.1], "overrides": {"clump": 0.3}}],
       "locks": [{"id": 1, "name": "bang_01", "group": "bang", "root": [0.1, 1.6, 0.05], "length": 0.17,
                  "direction": [0.0, -1.0, 0.0], "overrides": {"frizz": 0.1}, "match": "ok", "root_flip": True},
                 {"id": 3, "name": "bang_02", "group": "bang", "excluded": True}],
       "orphans": [{"id": 2, "name": "bang_03", "group": "bang", "overrides": {"density": 90.0}}],
       "masks": [{"id": -1, "kind": "base", "name": "Automatic"},
                 {"id": 0, "kind": "density", "name": "Thin", "density": 40.0, "scope": "group", "group": "bang"},
                 {"id": 1, "kind": "paint", "name": "Mask", "parent": 0}],
       "mask_id_high": 1, "regions_stale": True, "stale_why": ["bang_01 root flipped"]}


def test_schema_is_7_and_step_6_to_7_sets_the_number_only():
    assert SCHEMA == 7
    new = migrate(dict(SIX))
    assert new == dict(SIX, schema=7) and SIX["schema"] == 6          # the input is not changed
    with pytest.raises(ValueError, match="newer than this tool"):
        migrate({"schema": 8})


def test_schema_6_file_loads_the_same_data():
    d = GroomData.from_json(json.dumps(SIX))
    six = GroomData.from_json(json.dumps(SIX))
    assert d == six and d.schema == 7
    out = json.loads(d.to_json())
    for key in ("asset", "defaults", "id_high", "mask_id_high", "regions_stale", "stale_why"):
        assert out[key] == SIX[key], key
    lk = d.lock(1)
    assert (lk.name, lk.group, lk.root, lk.length, lk.direction, lk.overrides, lk.root_flip) == (
        "bang_01", "bang", (0.1, 1.6, 0.05), 0.17, (0.0, -1.0, 0.0), {"frizz": 0.1}, True)
    assert d.lock(3).excluded and [o.id for o in d.orphans] == [2] and d.orphans[0].overrides == {"density": 90.0}
    assert [(m.id, m.kind) for m in d.masks] == [(-1, "base"), (0, "density"), (1, "paint")]
    # no edit, no drawn lock: every lock is its measured spine and of the mesh
    for lk in d.locks:
        assert (lk.source, lk.spine, lk.handles, lk.curve, lk.edited, lk.drawn) == ("mesh", [], None, [], False, False)
    assert d.orphans[0].spine == [] and d.orphans[0].handles is None and d.edited_locks() == []
    assert out["schema"] == 7 and out["locks"][0]["spine"] == [] and out["locks"][0]["handles"] is None


def test_an_edit_and_a_drawn_lock_round_trip_through_json():
    d = GroomData.from_json(json.dumps(SIX))
    d.lock(1).spine = [(0.0, 0.0, 0.0), (0.05, 0.001, 0.0), (0.1, 0.004, -0.002), (0.15, 0.01, 0.0)]
    d.lock(3).handles = 7
    dr = d.add_drawn_lock("bang", [(0.0, 1.5, 0.1), (0.0, 1.45, 0.14), (0.0, 1.4, 0.16)], 2.0, 0.6, 0.25)
    again = GroomData.from_json(d.to_json())
    assert again == d and again.schema == 7
    assert again.lock(1).spine == d.lock(1).spine and again.lock(1).edited and again.edited_locks() == [1]
    assert again.lock(3).handles == 7 and again.lock(3).spine == []
    g = again.lock(dr.id)
    assert (g.source, g.drawn, g.edited, g.width_cm, g.thick_cm, g.taper) == ("drawn", True, False, 2.0, 0.6, 0.25)
    assert g.curve == [(0.0, 1.5, 0.1), (0.0, 1.45, 0.14), (0.0, 1.4, 0.16)] and g.root == (0.0, 1.5, 0.1)
    assert g.length == pytest.approx(math.dist((0, 1.5, .1), (0, 1.45, .14)) + math.dist((0, 1.45, .14), (0, 1.4, .16)))


def test_stored_points_that_cannot_be_read_are_dropped_not_guessed():
    raw = dict(SIX, schema=7, locks=[{"id": 1, "name": "a", "group": "bang", "spine": [[0, 0, 0], [1, 2]],
                                      "handles": 30, "curve": [[0, 0, 0], ["x", 0, 0]]},
                                     {"id": 3, "name": "b", "group": "bang", "handles": 6.0},
                                     {"id": 4, "name": "c", "group": "bang", "handles": True}])
    d = GroomData.from_json(json.dumps(raw))
    # a count out of range is clamped by the one rule (the manager, 2026-11-21; t80 N2): 30 is 12
    assert d.lock(1).spine == [] and d.lock(1).handles == 12 and d.lock(1).curve == []
    assert d.lock(3).handles == 6 and d.lock(4).handles is None


def test_a_missing_lock_keeps_its_edit_and_reassign_hands_it_on():
    lk = Lock(id=5, name="bang_05", group="bang", overrides={"clump": 0.5}, root_flip=True,
              spine=[(0.0, 0.0, 0.0), (0.1, 0.0, 0.01), (0.2, 0.0, 0.0), (0.3, 0.0, 0.0)], handles=4)
    orphan = Orphan.from_lock(lk)
    assert (orphan.id, orphan.overrides, orphan.root_flip, orphan.spine, orphan.handles) == (
        5, {"clump": 0.5}, True, lk.spine, 4)
    orphan.spine.append((9.0, 9.0, 9.0))
    assert len(lk.spine) == 4                                          # a copy, not the lock's own list
    orphan.spine.pop()
    d = GroomData(groups=[Group("bang", "Bang")], orphans=[orphan],
                  locks=[Lock(id=9, name="bang_09", group="bang", match="new")])
    again = GroomData.from_json(d.to_json())
    assert again.orphans[0].spine == lk.spine and again.orphans[0].handles == 4
    assert again.reassign_orphan(5, 9) == []
    new = again.lock(9)
    assert new.spine == lk.spine and new.handles == 4 and new.edited and new.match == "ok" and again.orphans == []


def test_reassign_to_a_drawn_lock_leaves_its_own_shape():
    d = GroomData(groups=[Group("g", "G")], orphans=[Orphan(id=1, name="a", group="g", spine=[(0, 0, 0), (1, 0, 0)])])
    d.note_ids()
    dr = d.add_drawn_lock("g", [(0, 0, 0), (0, 1, 0)], 1.0, 0.5)
    d.reassign_orphan(1, dr.id)
    assert d.lock(dr.id).spine == [] and d.lock(dr.id).curve == [(0.0, 0.0, 0.0), (0.0, 1.0, 0.0)]


def test_drawn_lock_ids_are_never_reused_and_only_drawn_locks_are_deleted():
    d = GroomData(groups=[Group("g", "G")], locks=[Lock(id=1, name="g_01", group="g")],
                  orphans=[Orphan(id=4, name="g_04", group="g")])
    d.note_ids()
    a = d.add_drawn_lock("g", [(0, 0, 0), (0, 0.1, 0)], 2.0, 0.6)
    assert a.id == 5 and a.name not in ("g_01", "g_04") and d.regions_stale and f"{a.name} drawn" in d.stale_why
    lay = d.add_mask(kind="density", scope="locks", locks=[1, a.id])
    assert not d.remove_drawn_lock(1) and d.lock(1) is not None        # a lock of the mesh is not deleted here
    assert d.remove_drawn_lock(a.id) and d.lock(a.id) is None and d.mask(lay.id).locks == [1]
    assert not d.remove_drawn_lock(a.id)
    b = d.add_drawn_lock("g", [(0, 0, 0), (0, 0.1, 0)], 2.0, 0.6)
    assert b.id == 6 and GroomData.from_json(d.to_json()).next_lock_id() == 7
    with pytest.raises(ValueError):
        d.add_drawn_lock("g", [(0, 0, 0)], 2.0, 0.6)
    with pytest.raises(ValueError):
        d.add_drawn_lock("g", [(0, 0, 0), (0, 1, 0)], 0.0, 0.6)


def test_reset_returns_to_the_measured_spine_and_keeps_the_handle_count():
    d = GroomData(locks=[Lock(id=1, name="a", group="g", spine=[(0, 0, 0), (1, 0, 0)], handles=6),
                         Lock(id=2, name="b", group="g")])
    assert d.edited_locks() == [1]
    assert logic.reset_locks(d.locks, [1, 2]) == [1]
    assert d.lock(1).spine == [] and d.lock(1).handles == 6 and not d.lock(1).edited and d.edited_locks() == []
    assert not d.lock(1).reset_spine()


# ---- root frame ----

@pytest.mark.parametrize("name", NAMES)
def test_root_frame_round_trip(name):
    P, T, A = SPINES[name]
    origin, R = logic.root_frame(P, T, A)
    assert np.allclose(R @ R.T, np.eye(3)) and np.isclose(np.linalg.det(R), 1.0)
    assert np.allclose(origin, P[0]) and np.allclose(R[0], T[0])
    back = logic.frame_to_world(logic.world_to_frame(P, origin, R), origin, R)
    assert np.abs(back - P).max() < 1e-12
    v = np.array([0.3, -0.2, 0.9])
    assert np.allclose(logic.direction_to_world(logic.direction_to_frame(v, R), R), v)
    H = logic.measured_handles(P, T, A, 5)
    assert np.all(H[0] == 0.0) and not logic.root_moved(H)
    assert np.allclose(logic.frame_to_world(H, origin, R)[-1], P[-1])


# ---- the edit (the spike's rule) ----

@pytest.mark.parametrize("name", NAMES)
@pytest.mark.parametrize("K", range(config.HANDLES_MIN, config.HANDLES_MAX + 1))
def test_handles_equal_to_the_measured_spine_move_nothing(name, K):
    P, T, A = SPINES[name]
    e = logic.edited_spine(P, T, A, logic.measured_handles(P, T, A, K))
    assert np.linalg.norm(e.P - P, axis=1).max() * UNIT <= 0.001
    assert np.allclose(e.root, P[0]) and e.edited


def test_no_handles_is_the_measured_spine():
    P, T, A = SPINES["hair_bang_11"]
    e = logic.edited_spine(P, T, A, [])
    assert not e.edited and np.array_equal(e.P, P)


@pytest.mark.parametrize("name", NAMES)
@pytest.mark.parametrize("case", ["tip_2cm", "turn_25deg"])
def test_the_edit_gives_the_spikes_vex_numbers(name, case):
    P, T, A = SPINES[name]
    H0 = logic.measured_handles(P, T, A, 5)
    H = _bend(H0, 2.0) if case == "tip_2cm" else _turn(H0, 25.0)
    N, axes = _vex(P, T, A, H)
    e = logic.edited_spine(P, T, A, H)
    assert np.linalg.norm(e.P - N, axis=1).max() * UNIT < 1e-9
    assert np.abs(e.axis - axes).max() < 1e-9
    # the frame stays square and turns with the tangent
    assert np.allclose(np.linalg.norm(e.axis, axis=1), 1) and np.abs(np.sum(e.axis * e.tangent, axis=1)).max() < 1e-9
    assert np.allclose(e.minor, np.cross(e.tangent, e.axis)) and e.curveu[0] == 0 and e.curveu[-1] == pytest.approx(1)
    origin, R = logic.root_frame(P, T, A)
    tip = logic.frame_to_world(H, origin, R)[-1]
    assert np.linalg.norm(e.P[-1] - tip) * UNIT < 1e-9 and np.allclose(e.P[0], P[0])     # root and tip on handles
    assert np.allclose(e.direction, (e.P[-1] - e.P[0]) / np.linalg.norm(e.P[-1] - e.P[0]))


def test_a_2cm_tip_move_moves_the_tip_2cm_along_the_width_axis():
    P, T, A = SPINES["hair_bang_11"]
    e = logic.edited_spine(P, T, A, _bend(logic.measured_handles(P, T, A, 5), 2.0))
    _, R = logic.root_frame(P, T, A)
    assert np.allclose((e.P[-1] - P[-1]) * UNIT, 2.0 * R[1])
    moved = np.linalg.norm(e.P - P, axis=1) * UNIT
    assert np.all(np.diff(moved) >= -1e-9)                             # more toward the tip, nothing at the root


def test_a_25deg_turn_turns_the_lock_about_its_root():
    P, T, A = SPINES["hair_back_20"]
    e = logic.edited_spine(P, T, A, _turn(logic.measured_handles(P, T, A, 5), 25.0))
    _, R = logic.root_frame(P, T, A)
    # the tip is the measured tip turned 25 deg round the root's thickness axis (in world)
    assert np.linalg.norm(e.P[-1] - logic.rotate_about_root([P[0], P[-1]], R[2], 25.0)[1]) * UNIT < 1e-9
    assert np.allclose(e.P[0], P[0]) and logic.arc_lengths(e.P)[-1] == pytest.approx(logic.arc_lengths(P)[-1], rel=0.02)
    # the width axis turns with the tangent, by the shortest turn: at every point it turns no more than the
    # tangent did, and the tangent turned (about 25 deg along most of the lock)
    def ang(u, v):
        return np.degrees(np.arccos(np.clip(np.sum(u * v, axis=1), -1, 1)))
    turn_t, turn_a = ang(T, e.tangent), ang(A, e.axis)
    assert np.all(turn_a <= turn_t + 1e-6) and np.median(turn_t) == pytest.approx(25, abs=5)


def test_a_moved_root_goes_onto_the_skin_and_an_unmoved_one_stays():
    P, T, A = SPINES["hair_bang_11"]
    calls = []

    def skin(p):
        calls.append(p)
        return np.array([p[0], p[1], 0.0])                             # a flat skin at z = 0

    H = logic.measured_handles(P, T, A, 5)
    e = logic.edited_spine(P, T, A, H, skin)
    assert calls == [] and np.array_equal(e.P[0], P[0])                 # never snapped while not moved
    H[0, 1] += 1.0 / UNIT                                              # slid 1 cm across
    e = logic.edited_spine(P, T, A, H, skin)
    N, _ = _vex(P, T, A, H, skin)
    assert len(calls) == 2 and abs(e.P[0][2]) < 1e-12 and np.abs(e.P - N).max() < 1e-12
    assert np.allclose(logic.edited_spine(P, T, A, H).P[0], logic.frame_to_world(H, *logic.root_frame(P, T, A))[0])


# ---- how many handles ----

@pytest.mark.parametrize("cm, k", [(0.0, 4), (12.6, 4), (15.2, 4), (17.6, 4), (24.8, 5), (32.0, 5), (32.1, 6),
                                   (56.0, 8), (89.6, 12), (500.0, 12)])
def test_handle_count_by_length(cm, k):
    assert logic.handle_count(cm) == k


def test_handle_count_override_and_its_range():
    assert logic.handle_count(89.6, 5) == 5 and logic.handle_count(10.0, 9) == 9
    assert logic.handle_count(10.0, 2) == config.HANDLES_MIN and logic.handle_count(10.0, 40) == config.HANDLES_MAX
    # back_20 89.6, bang_11 17.6, base_20 24.0 cm
    assert [logic.handle_count(_cm(SPINES[n][0])) for n in NAMES] == [12, 4, 4]
    assert logic.lock_handle_count(Lock(1, "a", "g", handles=7), 89.6) == 7
    assert logic.lock_handle_count(Lock(1, "a", "g", spine=[(0, 0, 0)] * 6, handles=7), 89.6) == 6
    assert logic.lock_handle_count(Lock(1, "a", "g"), 89.6) == 12
    assert logic.lock_handle_count(Lock(1, "a", "g", source="drawn", curve=[(0, 0, 0)] * 5), 89.6) == 5


# ---- re-sampling an edit to another handle count ----

@pytest.mark.parametrize("name", NAMES)
@pytest.mark.parametrize("case", ["tip_2cm", "turn_25deg", "root_1cm"])
def test_resample_5_8_5_keeps_the_edited_spine(name, case):
    P, T, A = SPINES[name]
    H0 = logic.measured_handles(P, T, A, 5)
    if case == "tip_2cm":
        H = _bend(H0, 2.0)
    elif case == "turn_25deg":
        H = _turn(H0, 25.0)
    else:
        H = H0.copy()
        H[0, 1] += 1.0 / UNIT
    before = logic.edited_spine(P, T, A, H).P
    H8, gap8 = logic.resample_spine(P, T, A, H, 8, UNIT)
    H5, gap5 = logic.resample_spine(P, T, A, H8, 5, UNIT)
    assert len(H8) == 8 and len(H5) == 5
    assert np.array_equal(H8[0], H[0]) and np.array_equal(H5[0], H[0])          # the root stays as stored
    for Hn, gap in ((H8, gap8), (H5, gap5)):
        moved = np.linalg.norm(logic.edited_spine(P, T, A, Hn).P - before, axis=1).max() * UNIT
        assert moved <= config.RESAMPLE_TOL_CM and gap <= config.RESAMPLE_TOL_CM
    assert np.abs(H5 - H).max() * UNIT < 0.05                              # nearly the handles it started from


def test_resample_of_no_edit_or_the_measured_handles():
    P, T, A = SPINES["hair_base_20"]
    assert logic.resample_spine(P, T, A, [], 8, UNIT)[0].shape == (0, 3)
    H8, gap = logic.resample_spine(P, T, A, logic.measured_handles(P, T, A, 5), 8, UNIT)
    assert gap < 1e-9 and np.abs(H8 - logic.measured_handles(P, T, A, 8)).max() * UNIT < 1e-6
    with pytest.raises(ValueError):
        logic.resample_spine(P, T, A, H8, 1, UNIT)


# ---- rotate / scale about the root ----

def test_rotate_and_scale_about_the_root():
    P, T, A = SPINES["hair_bang_11"]
    H = logic.measured_handles(P, T, A, 5)
    assert np.allclose(logic.rotate_about_root(H, [0, 0, 1], 25.0), _turn(H, 25.0))
    assert np.allclose(logic.rotate_about_root(H, [0, 0, 5], 360.0), H)
    moved = H.copy()
    moved[0] = [0.0, 0.01, 0.0]
    r = logic.rotate_about_root(moved, [0, 1, 0], 40.0)
    assert np.array_equal(r[0], moved[0])
    assert np.allclose(np.linalg.norm(r - r[0], axis=1), np.linalg.norm(moved - moved[0], axis=1))
    s = logic.scale_about_root(moved, 1.5)
    assert np.array_equal(s[0], moved[0]) and np.allclose(s - s[0], 1.5 * (moved - moved[0]))
    assert np.allclose(logic.scale_about_root(H, 1.0), H) and logic.rotate_about_root([], [0, 0, 1], 5).shape == (0, 3)
    e = logic.edited_spine(P, T, A, logic.scale_about_root(H, 1.2))
    assert logic.arc_lengths(e.P)[-1] == pytest.approx(1.2 * logic.arc_lengths(P)[-1], rel=0.01)


# ---- strokes ----

def _helix(cm_long=20.0, turns=0.75, radius_cm=2.0, n=200):
    t = np.linspace(0, 1, n)
    a = 2 * np.pi * turns * t
    return np.c_[radius_cm * np.cos(a), radius_cm * np.sin(a), -cm_long * t] / UNIT


def test_a_stroke_becomes_the_fewest_handles_within_the_tolerance():
    Q = _helix()
    H, gap = logic.stroke_handles(Q, UNIT)
    K = len(H)
    assert gap <= config.STROKE_TOL_CM and config.HANDLES_MIN <= K <= config.HANDLES_MAX
    assert np.allclose(H[0], Q[0]) and np.allclose(H[-1], Q[-1])
    if K > config.HANDLES_MIN:                                         # one fewer would miss
        fewer = logic.at_lengths(Q, logic.arc_lengths(Q)[-1] * logic.handle_shares(K - 1))
        assert logic.curve_gap(Q, logic.curve_points(fewer)) * UNIT > config.STROKE_TOL_CM
    straight = np.c_[np.zeros(50), np.zeros(50), np.linspace(0, -0.2, 50)]
    Hs, gs = logic.stroke_handles(straight, UNIT)
    assert len(Hs) == config.HANDLES_MIN and gs < 1e-9
    with pytest.raises(ValueError):
        logic.stroke_handles([[0, 0, 0], [0, 0, 0]], UNIT)


def test_a_drawn_lock_spine_from_its_handles():
    H, _ = logic.stroke_handles(_helix(), UNIT)
    sp = logic.drawn_spine(H, 49)
    assert sp.shape == (49, 3) and np.allclose(sp[0], H[0]) and np.allclose(sp[-1], H[-1])
    seg = np.linalg.norm(np.diff(sp, axis=0), axis=1)
    assert seg.max() / seg.min() < 1.05                                # at equal lengths
    assert logic.curve_gap(sp, _helix()) * UNIT <= config.STROKE_TOL_CM + 0.05


@pytest.mark.parametrize("name", NAMES)
def test_a_redrawn_lock_lies_within_the_tolerance_of_its_stroke(name):
    P, T, A = SPINES[name]
    stroke = logic.edited_spine(P, T, A, _turn(logic.measured_handles(P, T, A, 5), 25.0)).P
    stroke = logic.at_lengths(stroke, np.linspace(0, logic.arc_lengths(stroke)[-1], 300))
    H, gap = logic.redraw_handles(P, T, A, stroke, UNIT)
    assert gap <= config.STROKE_TOL_CM and np.all(H[0] == 0.0)          # it starts at the root: root not moved
    assert logic.curve_gap(logic.edited_spine(P, T, A, H).P, stroke) * UNIT == pytest.approx(gap)
    # a stroke started 1 cm off the root moves the root, onto the skin when the network gives one
    off = stroke + np.r_[[1.0 / UNIT, 0, 0]] * np.clip(1 - np.linspace(0, 4, len(stroke)), 0, 1)[:, None]
    H2, gap2 = logic.redraw_handles(P, T, A, off, UNIT)
    assert logic.root_moved(H2) and gap2 <= config.STROKE_TOL_CM


# ---- drawn lock numbers ----

def test_drawn_footprint_and_profile():
    assert logic.drawn_footprint_cm(2.0) == pytest.approx(1.0) == config.REGION_FOOTPRINT * 2.0
    assert logic.drawn_footprint_cm(-1.0) == 0.0
    w, t = logic.drawn_profile([0.0, 0.5, 1.0], 2.0, 0.6, 0.3)
    assert np.allclose(w, [2.0, 2.0 * (1 - 0.7 * 0.25), 0.6]) and np.allclose(t, [0.6, 0.6 * (1 - 0.7 * 0.25), 0.18])


def test_flat_handles_round_trip():
    H = [(0.0, 0.0, 0.0), (0.1, 0.2, 0.3), (1.5, -2.0, 0.25)]
    flat = logic.flat_handles(H)
    assert flat == [0.0, 0.0, 0.0, 0.1, 0.2, 0.3, 1.5, -2.0, 0.25] and logic.unflat_handles(flat) == H
    assert logic.unflat_handles(flat + [7.0]) == H and logic.flat_handles([]) == []


# ---- the model takes what logic returns, and garbage in the new fields is dropped, never raised (t80 D1, D2) ----

def test_model_takes_numpy_handles_from_logic():
    H, _gap = logic.stroke_handles(np.c_[np.linspace(0, 0.2, 30), np.zeros(30), np.zeros(30)], 100.0)
    d = GroomData()
    lk = d.add_drawn_lock("g", H, 2.0, 0.6)
    assert len(lk.curve) == len(H) and all(isinstance(p, tuple) for p in lk.curve)
    ed = Lock(9, "a", "g", spine=H)                    # assigned as is by a caller
    assert ed.edited and logic.lock_handle_count(ed, 10.0) == len(H)
    d.locks.append(ed)
    assert len(GroomData.from_json(d.to_json()).lock(9).spine) == len(H)
    assert ed.reset_spine() and not ed.edited


@pytest.mark.parametrize("field,value", [("handles", float("nan")), ("handles", float("inf")), ("handles", -float("inf")),
                                         ("spine", 5), ("spine", [[0, 0, 0], [float("nan"), 0, 0]]),
                                         ("spine", [[0, 0, 0], [float("inf"), 0, 0]]), ("curve", 7)])
def test_garbage_in_new_fields_is_dropped(field, value):
    d = GroomData(locks=[Lock(1, "a", "g", spine=[(0.0, 0.0, 0.0), (0.1, 0.0, 0.0)], handles=6)],
                  orphans=[Orphan(2, "o", "g")])
    raw = json.loads(d.to_json())
    raw["locks"][0][field] = value
    raw["orphans"][0][field] = value
    out = GroomData.from_json(json.dumps(raw))
    lk, orphan = out.lock(1), out.orphans[0]
    if field == "handles":
        assert lk.handles is None and orphan.handles is None
    else:
        assert getattr(lk, field) == [] and getattr(orphan, field, []) == []


def test_drawn_lock_refuses_non_finite_width():
    for w, t in ((float("nan"), 1.0), (float("inf"), 1.0), (1.0, float("nan"))):
        with pytest.raises(ValueError):
            GroomData().add_drawn_lock("g", [(0, 0, 0), (0, 1, 0)], w, t)


# ---- the manager's decisions of 2026-11-21 (after t80 and t79) ----

def test_handle_counts_are_clamped_by_one_rule_on_load():
    raw = dict(SIX, schema=7, locks=[{"id": 1, "name": "a", "group": "bang", "handles": 13},
                                     {"id": 2, "name": "b", "group": "bang", "handles": 2},
                                     {"id": 3, "name": "c", "group": "bang", "handles": 12.0},
                                     {"id": 4, "name": "d", "group": "bang", "handles": 7.5},
                                     {"id": 5, "name": "e", "group": "bang", "handles": float("nan")}])
    d = GroomData.from_json(json.dumps(raw).replace("NaN", "NaN"))
    assert [d.lock(i).handles for i in range(1, 6)] == [12, 4, 12, None, None]
    assert [logic.handle_count(10.0, x) for x in (13, 2, 12)] == [12, 4, 12]


def test_a_drawn_lock_keeps_its_curve_as_drawn_and_reset_puts_it_back():
    d = GroomData(groups=[Group("bang", "Bang")])
    curve = [(0.0, 0.0, 0.0), (0.0, 0.1, 0.0), (0.0, 0.2, 0.05)]
    lk = d.add_drawn_lock("bang", curve, 2.0, 0.6)
    assert lk.drawn_curve == curve and not lk.edited
    lk.curve = [(0.0, 0.0, 0.0), (0.05, 0.1, 0.0), (0.0, 0.25, 0.05)]
    lk.root, lk.length = lk.curve[0], 0.3
    assert lk.edited                                      # a drawn lock whose points were moved is edited
    again = GroomData.from_json(d.to_json()).lock(lk.id)
    assert again.drawn_curve == curve and again.edited
    assert d.edited_locks() == [lk.id]
    assert lk.reset_spine() is True and lk.curve == curve and not lk.edited
    assert math.isclose(lk.length, sum(math.dist(a, b) for a, b in zip(curve, curve[1:])))
    assert lk.reset_spine() is False


def test_a_drawn_lock_saved_without_drawn_curve_takes_its_curve():
    raw = dict(SIX, schema=7, locks=[{"id": 1, "name": "a", "group": "bang", "source": "drawn",
                                      "curve": [[0, 0, 0], [0, 0.1, 0]], "width_cm": 2, "thick_cm": 0.6}])
    lk = GroomData.from_json(json.dumps(raw)).lock(1)
    assert lk.drawn_curve == lk.curve and not lk.edited


def test_a_source_outside_the_list_reads_as_mesh():
    raw = dict(SIX, schema=7, locks=[{"id": 1, "name": "a", "group": "bang", "source": "painted"},
                                     {"id": 2, "name": "b", "group": "bang", "source": 3}])
    d = GroomData.from_json(json.dumps(raw))
    assert d.lock(1).source == config.SOURCE_MESH and d.lock(2).source == config.SOURCE_MESH


def test_reassign_orphan_without_an_edit_keeps_the_targets_edit():
    edit = [(0.0, 0.0, 0.0), (0.1, 0.0, 0.0), (0.2, 0.01, 0.0), (0.3, 0.0, 0.0)]
    d = GroomData(groups=[Group("bang", "Bang")], orphans=[Orphan(id=5, name="x", group="bang")],
                  locks=[Lock(id=9, name="bang_09", group="bang", spine=list(edit), handles=4)])
    d.reassign_orphan(5, 9)
    assert d.lock(9).spine == edit and d.lock(9).handles == 4
    d2 = GroomData(groups=[Group("bang", "Bang")], orphans=[Orphan(id=5, name="x", group="bang", spine=edit[:2] + edit[2:], handles=5)],
                   locks=[Lock(id=9, name="bang_09", group="bang")])
    d2.reassign_orphan(5, 9)
    assert d2.lock(9).spine == edit and d2.lock(9).handles == 5


def test_add_drawn_lock_refuses_a_curve_without_length_or_with_garbage():
    d = GroomData(groups=[Group("bang", "Bang")])
    for curve in ([(0.0, 0.0, 0.0), (0.0, 0.0, 0.0)], [(0.0, 0.0, 0.0), (float("nan"), 0.0, 0.0)],
                  [(0.0, 0.0, 0.0), (0.0, 0.1, 0.0), (0.0, 0.0, 0.0)]):
        with pytest.raises(ValueError):
            d.add_drawn_lock("bang", curve, 2.0, 0.6)
    for w in (float("nan"), float("inf"), 0.0):
        with pytest.raises(ValueError):
            d.add_drawn_lock("bang", [(0.0, 0.0, 0.0), (0.0, 0.1, 0.0)], w, 0.6)
    assert d.locks == []


def test_rotate_and_scale_with_garbage_leave_the_handles():
    H = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (2.0, 0.5, 0.0)]
    for axis in ((0.0, 0.0, 0.0), (float("nan"), 0.0, 1.0), (0.0, float("inf"), 0.0)):
        assert logic.rotate_about_root(H, axis, 90.0).tolist() == [list(p) for p in H]
    assert logic.rotate_about_root(H, (0, 0, 1), float("nan")).tolist() == [list(p) for p in H]
    for f in (0.0, -1.0, float("nan"), float("inf")):
        assert logic.scale_about_root(H, f).tolist() == [list(p) for p in H]


def test_a_stroke_with_a_point_that_is_not_a_number_is_refused():
    bad = [(0.0, 0.0, 0.0), (float("nan"), 0.0, 0.0), (1.0, 0.0, 0.0)]
    with pytest.raises(ValueError):
        logic.stroke_handles(bad, 100.0)
    P, T, A = SPINES[NAMES[0]]
    with pytest.raises(ValueError):
        logic.redraw_handles(P, T, A, bad, 100.0)


def test_strokes_take_at_most_12_handles_and_say_the_gap():
    t = np.linspace(0, 1, 400)
    wiggle = np.stack([t * 0.3, 0.02 * np.sin(t * 60), np.zeros_like(t)], 1)    # 12 handles cannot hold it
    H, gap = logic.stroke_handles(wiggle, 100.0)
    assert len(H) == config.HANDLES_MAX and gap > config.STROKE_TOL_CM
    P, T, A = SPINES[NAMES[0]]
    H, gap = logic.redraw_handles(P, T, A, P + np.stack([np.zeros(len(P)), 0.01 * np.sin(np.linspace(0, 40, len(P))),
                                                          np.zeros(len(P))], 1), 100.0)
    assert len(H) <= config.HANDLES_MAX
    assert not hasattr(config, "STROKE_HANDLES_MAX")


def test_drawn_handle_count_refits_the_curve():
    curve = [(0.0, 0.0, 0.0), (0.0, 0.05, 0.01), (0.0, 0.1, 0.03), (0.01, 0.15, 0.06), (0.0, 0.2, 0.1)]
    new, gap = logic.drawn_handle_count(curve, 8, 100.0)
    assert len(new) == 8 and np.allclose(new[0], curve[0]) and gap < config.RESAMPLE_TOL_CM
    back, gap2 = logic.drawn_handle_count(new, 5, 100.0)
    assert len(back) == 5 and gap2 < config.RESAMPLE_TOL_CM
    assert len(logic.drawn_handle_count(curve, 30, 100.0)[0]) == config.HANDLES_MAX


def test_set_drawn_has_its_own_undo_label():
    assert config.UNDO_SPINE["drawn"].startswith("MONO Grooming: ")
