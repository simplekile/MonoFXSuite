"""grooming-check's qc_metrics.py, the parts that need no Houdini (v0.2b B5): a drawn lock's strands are left out of
the mesh numbers and nothing else changes when no lock is drawn; the spine frames the drawn-lock section reads."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
import pytest

SCRIPT = Path(__file__).resolve().parents[1] / ".claude" / "skills" / "grooming-check" / "scripts" / "qc_metrics.py"


@pytest.fixture(scope="module")
def qc():
    spec = importlib.util.spec_from_file_location("qc_metrics_under_test", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _strands(n, drawn_from=None, seed=3):
    rng = np.random.default_rng(seed)
    m = {a: rng.uniform(0.001, 0.02, n) for a in ("qc_len", "qc_maxseg", "qc_seg_ratio", "qc_dmax", "qc_dmean",
                                                    "qc_dtip", "qc_other")}
    m["qc_maxang"] = rng.uniform(1, 40, n)
    m["qc_sharp"] = rng.uniform(0, 0.02, n)
    m["qc_rev"] = rng.uniform(0, 0.1, n)
    m["lock_id"] = np.repeat(np.arange(4), n // 4)
    m["drawn"] = np.zeros(n, dtype=bool)
    if drawn_from is not None:
        m["drawn"][drawn_from:] = True
        for a in ("qc_dmax", "qc_dmean", "qc_dtip", "qc_other"):
            m[a][drawn_from:] = -1.0          # what VEX_STRAND writes for a drawn lock
    return m


def test_no_drawn_lock_gives_the_numbers_as_before(qc):
    m = _strands(400)
    old = dict(m)
    del old["drawn"]                              # a report from before v0.2b had no drawn flag
    assert qc.summary(m) == qc.summary(old)
    assert qc.per_lock(m, {}) == qc.per_lock(old, {})


def test_drawn_strands_leave_the_mesh_numbers_only(qc):
    m = _strands(400, drawn_from=300)            # lock 3 drawn
    s = qc.summary(m)
    mesh_only = {k: v[:300] for k, v in m.items()}
    s_mesh = qc.summary(mesh_only)
    for k in ("dmax_p95_cm", "dmean_p50_cm", "dtip_p95_cm", "other_mean"):
        assert s[k] == s_mesh[k]                  # the -1 of a drawn lock never reaches a mesh number
    assert s["strands"] == 400                    # its strands still count, and in the shape numbers
    assert s["kink_p95_deg"] == pytest.approx(float(np.percentile(m["qc_maxang"], 95)))
    rows = {r["lock_id"]: r for r in qc.per_lock(m, {3: "drawn_01"})}
    assert rows[3]["drawn"] is True and rows[3]["name"] == "drawn_01"
    assert rows[3]["dmax_p95_cm"] is None and rows[3]["dtip_p95_cm"] is None and rows[3]["other_mean"] is None
    assert rows[0]["dmax_p95_cm"] is not None and "drawn" not in rows[0]
    # a drawn row ranks by its shape alone (no TypeError on its missing mesh numbers)
    r = dict(rows[3], coverage=None, width_ratio=None)
    assert qc.badness(r) == pytest.approx(r["kink_p95_deg"] / 35.0 + r["zigzag_p95"] / 0.15 + r["maxseg_p95_cm"] / 2.0)


def test_spine_frames_and_nearest_u_on_a_straight_spine(qc):
    P = np.stack([np.linspace(0, 1, 11), np.zeros(11), np.zeros(11)], 1)
    T = np.tile([1.0, 0, 0], (11, 1))
    A = np.tile([0.2, 1.0, 0], (11, 1))           # not square to the tangent: made square
    c, t, a, m = qc.spine_frames(P, T, A, np.array([0.0, 0.25, 1.0]))
    assert np.allclose(c[:, 0], [0, 0.25, 1.0]) and np.allclose(t, [1, 0, 0])
    assert np.allclose(a, [0, 1, 0]) and np.allclose(m, [0, 0, 1])
    X = np.array([[0.3, 0.5, 0.0], [2.0, 0.0, 0.0], [-1.0, 0.1, 0.0]])
    assert np.allclose(qc.nearest_u(X, P), [0.3, 1.0, 0.0])


def test_the_drawn_checks_are_only_added_with_a_drawn_lock(qc):
    # the groom with no drawn lock keeps exactly its checks (t55's 27): the drawn ones are not in LIMITS
    assert "drawn_root_skin_worst_cm" not in qc.LIMITS and "drawn_width_off_worst" not in qc.LIMITS
    assert len(qc.LIMITS) == 27
    assert qc.DRAWN_WIDTH_SHARE == 0.20 and qc.DRAWN_STATIONS == (0.3, 0.5, 0.7, 0.9)


def test_the_script_reads_the_carried_mesh(qc):
    text = SCRIPT.read_text(encoding="utf-8")
    assert '"MESH_CARRIED" if carried else "pieces"' in text
    assert 'measure(imp, ref_mesh, None, "ref")' in text      # the reference stays on the modelled mesh
    cap = (SCRIPT.parent / "qc_capture.py").read_text(encoding="utf-8")
    assert "/MESH_CARRIED" in cap and "@lock_id!=" in cap and "solo({name})" not in cap


def test_latest_join_skin_is_left_out_and_nothing_moves_without_it(qc):
    """Skin owned by a lock with Latest join under 1 leaves skin_thin_*; with no such lock every number is as before."""
    owners = [[1], [1, 2], [2], [3], []]
    area = np.array([1.0, 2.0, 1.0, 4.0, 3.0])
    ratio = np.array([0.1, 0.2, 0.9, 0.3, 1.0])
    arch = np.array([False, False, False, True, False])
    asked = np.ones(5, dtype=bool)
    share, per, has, thin, latest = qc.skin_thin_numbers(owners, area, ratio, arch, asked)
    assert share == pytest.approx(3.0 / 4.0) and not latest.any()
    assert per[1] == pytest.approx(1.0) and per[2] == pytest.approx(2.0 / 3.0)
    share2, per2, has2, _thin2, latest2 = qc.skin_thin_numbers(owners, area, ratio, arch, asked, {1})
    assert list(latest2) == [True, True, False, False, False]
    assert share2 == 0.0 and per2[1] == 0.0 and not has2[:2].any()
    assert per2[2] == pytest.approx(0.0)        # its prim shared with lock 1 is left out with it


def test_latest_join_locks_reads_the_resolved_setting(qc):
    from tools.fx.grooming.model import GroomData, Group, Lock
    data = GroomData(groups=[Group(id="f", name="F", overrides={"join_limit": 0.3}), Group(id="b", name="B")],
                     locks=[Lock(id=1, name="a", group="f"), Lock(id=2, name="b", group="b"),
                            Lock(id=3, name="c", group="b", overrides={"join_limit": 0.5})])
    assert qc.latest_join_locks(data) == {1, 3}
    assert qc.latest_join_locks(GroomData(locks=[Lock(id=1, name="a", group="")])) == set()


def test_near_any_and_latest_skin_lines(qc):
    rng = np.random.default_rng(5)
    pts = rng.uniform(0, 10, (3000, 3))
    q = rng.uniform(-2, 12, (200, 3))
    brute = (((q[:, None, :] - pts[None, :, :]) ** 2).sum(-1) <= 0.25).any(1)
    assert (qc.near_any(q, pts, 0.5) == brute).all()
    assert not qc.near_any(q, np.zeros((0, 3)), 0.5).any()
    lines = qc.latest_skin_lines(np.array([1.0, 1.0, 2.0]), [True, False, False], [True, True, False])
    assert lines == {"area_cm2": 4.0, "bare_share": 0.75, "uncovered_share": 0.5}
