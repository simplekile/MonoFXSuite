"""
Pure logic of MONO Grooming (no `hou`): re-import matching, region split, publish paths, naming.

The dataclasses below are the shared contract between the adapter and the panel (spec:
docs/plans/grooming_v0_1.md, "Adapter API"). The function signatures are fixed so the other parts
can be written against them.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Sequence

from tools.fx.grooming import config


@dataclass
class LockInfo:
    """What the cooked geometry says about one lock (measured, not stored in the JSON)."""
    id: int
    name: str
    group: str
    root: tuple[float, float, float]
    length: float
    width: float          # mean measured lock width
    thick: float          # mean measured lock thickness
    twist: float          # total measured twist, radians
    strands: int          # strands generated at full count
    region_area_cm2: float
    floating_cm2: float = 0.0   # skin under floating mesh, its roots moved to the lock's start (falloff-weighted)


@dataclass
class MeshPiece:
    """One hair-mesh piece as detection sees it, before it has an id."""
    index: int                         # piece number in the input geometry
    name: str                          # prim `name`, "" when the mesh has none
    root: tuple[float, float, float]   # spine root (closest to the scalp)
    length: float
    direction: tuple[float, float, float]  # unit root -> tip


@dataclass
class Match:
    piece: int            # MeshPiece.index
    lock_id: int          # existing id, or a new one
    status: str           # "ok" | "unsure" | "new"


@dataclass
class DetectReport:
    matches: list[Match] = field(default_factory=list)
    orphaned: list[int] = field(default_factory=list)   # lock ids with no piece any more
    # (lock name, cm) of the locks whose mesh root edge floats over config.ROOT_GAP_CM off the skin
    floating: list[tuple[str, float]] = field(default_factory=list)

    @property
    def counts(self) -> dict[str, int]:
        out = {"ok": 0, "unsure": 0, "new": 0, "orphaned": len(self.orphaned)}
        for m in self.matches:
            out[m.status] += 1
        return out


@dataclass
class PublishResult:
    ok: bool
    path: str
    version: str
    message: str


# ---------------------------------------------------------------------------
# Re-import matching
# ---------------------------------------------------------------------------

def _dist(a: Sequence[float], b: Sequence[float]) -> float:
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))


def _length_ratio(a: float, b: float) -> float:
    lo, hi = sorted((abs(a), abs(b)))
    if hi == 0.0:
        return 1.0
    return math.inf if lo == 0.0 else hi / lo


def _dot(a: Sequence[float], b: Sequence[float]) -> float | None:
    na, nb = math.sqrt(sum(x * x for x in a)), math.sqrt(sum(x * x for x in b))
    if na == 0.0 or nb == 0.0:
        return None
    return sum(x * y for x, y in zip(a, b)) / (na * nb)


def falloff(height_cm: float, far_cm: float, soft: float) -> float:
    """How much of the skin's roots start the lock where its mesh lies `height_cm` over it: smoothstep from
    far_cm x (1 - soft) to far_cm x (1 + soft), as build_hda region_join (VEX smooth)."""
    lo, hi = far_cm * (1 - soft), far_cm * (1 + soft)
    if hi <= lo:
        return 1.0 if height_cm > far_cm else 0.0
    t = min(max((height_cm - lo) / (hi - lo), 0.0), 1.0)
    return t * t * (3 - 2 * t)


def floating_text(floating: Sequence[tuple[str, float]], shown: int = 5) -> str:
    """The Detect line's warning about locks whose root floats off the skin, or "" when none does."""
    if not floating:
        return ""
    worst = sorted(floating, key=lambda f: -f[1])
    names = ", ".join(f"{n} {g:.1f} cm" for n, g in worst[:shown])
    more = f" and {len(worst) - shown} more" if len(worst) > shown else ""
    return (f"{len(worst)} lock root{'s' if len(worst) > 1 else ''} off the skin ({names}{more}): "
            f"their meshes start in the air; Root to skin bends them down")


def match_locks(pieces: Sequence[MeshPiece], locks: Sequence["object"], next_id: int) -> DetectReport:
    """Match hair-mesh pieces to existing locks (model.Lock): by name, then root distance, then shape.

    A match by name with the root still close is "ok"; a match by position or shape only is "unsure";
    a piece matching nothing gets a new id from `next_id` upward. Each lock matches at most one piece.

    Distances are relative to the lock's size, `scale = max(lock.length, piece.length)`, so the rule
    does not depend on scene units (thresholds in `config.MATCH_*`):

    1. same name, root moved <= 0.5 x scale  -> "ok"
    1b. piece without a name, root and length unchanged (<= 1e-5 x scale) -> "ok"
    2. same name, root farther               -> "unsure" (the lock moved a lot)
    3. root moved <= 0.25 x scale and length within x1.5  -> "unsure" (renamed, or the mesh has no names)
    4. root moved <= 1 x scale, length within x1.1 and, when the lock stores a `direction`, direction
       within ~25 degrees (dot >= 0.9)  -> "unsure" (shape)

    Rules run in that order over all pieces; inside a rule the closest pair wins, so with two pieces
    near one lock the closer one takes it and the other goes on to the later rules (often "new").
    `model.Lock` stores no direction today, so rule 4 checks it only when the lock has the attribute.
    Matches come back in piece order, new ids are given in piece order, `orphaned` is sorted.
    """
    pieces = sorted(pieces, key=lambda p: p.index)
    free_pieces = {p.index: p for p in pieces}
    free_locks = {lk.id: lk for lk in locks}
    found: dict[int, Match] = {}

    def scale(p: MeshPiece, lk) -> float:
        return max(float(lk.length), float(p.length), 0.0)

    def by_name(close: bool):
        def score(p, lk):
            if not p.name or p.name != lk.name:
                return None
            d = _dist(p.root, lk.root)
            if (d <= config.MATCH_NAME_ROOT_TOL * scale(p, lk)) != close:
                return None
            return d, "ok" if close else "unsure"
        return score

    def by_root(p, lk):
        d = _dist(p.root, lk.root)
        if d > config.MATCH_ROOT_TOL * scale(p, lk):
            return None
        if _length_ratio(p.length, lk.length) > config.MATCH_ROOT_LENGTH_RATIO:
            return None
        return d, "unsure"

    def by_shape(p, lk):
        d = _dist(p.root, lk.root)
        if d > config.MATCH_SHAPE_ROOT_TOL * scale(p, lk):
            return None
        if _length_ratio(p.length, lk.length) > config.MATCH_SHAPE_LENGTH_RATIO:
            return None
        direction = getattr(lk, "direction", None)
        if direction is not None:
            dot = _dot(p.direction, direction)
            if dot is not None and dot < config.MATCH_SHAPE_MIN_DOT:
                return None
        return d, "unsure"

    def unchanged(p, lk):
        # A piece without a name, at the same root and length as stored at the last Detect: the mesh
        # did not change there, so the match is sure (a hair mesh without per-lock names). A named
        # piece whose name changed stays "unsure" below, so a rename is shown to the user.
        if p.name:
            return None
        if _dist(p.root, lk.root) > config.MATCH_UNCHANGED_TOL * scale(p, lk):
            return None
        if abs(float(p.length) - float(lk.length)) > config.MATCH_UNCHANGED_TOL * scale(p, lk):
            return None
        return 0.0, "ok"

    for score in (by_name(True), unchanged, by_name(False), by_root, by_shape):
        cands = []
        for p in free_pieces.values():
            for lk in free_locks.values():
                hit = score(p, lk)
                if hit is not None:
                    cands.append((hit[0], p.index, lk.id, hit[1]))
        for _, pi, lid, status in sorted(cands):
            if pi in free_pieces and lid in free_locks:
                found[pi] = Match(piece=pi, lock_id=lid, status=status)
                del free_pieces[pi], free_locks[lid]

    for p in pieces:
        if p.index in free_pieces:
            found[p.index] = Match(piece=p.index, lock_id=next_id, status="new")
            next_id += 1
    return DetectReport(matches=[found[p.index] for p in pieces], orphaned=sorted(free_locks))


# ---------------------------------------------------------------------------
# Region split
# ---------------------------------------------------------------------------

def _locks_by_group(roots, groups_of) -> dict[str, list[int]]:
    out: dict[str, list[int]] = {}
    for lid in sorted(roots):
        out.setdefault(groups_of.get(lid, ""), []).append(lid)
    return out


def _split_python(scalp_points, roots, groups_of, point_groups) -> list[int]:
    by_group = {g: [(lid, *roots[lid]) for lid in ids] for g, ids in _locks_by_group(roots, groups_of).items()}
    out = []
    for (px, py, pz), g in zip(scalp_points, point_groups):
        best, best_d = config.NO_OWNER, math.inf
        for lid, x, y, z in by_group.get(g, ()):
            d = (px - x) ** 2 + (py - y) ** 2 + (pz - z) ** 2
            if d < best_d:
                best, best_d = lid, d
        out.append(best)
    return out


def _split_numpy(scalp_points, roots, groups_of, point_groups) -> list[int]:
    import numpy as np

    pts = np.asarray(scalp_points, dtype=np.float64).reshape(-1, 3)
    grp = np.asarray(point_groups, dtype=object)
    out = np.full(len(pts), config.NO_OWNER, dtype=np.int64)
    for g, ids in _locks_by_group(roots, groups_of).items():
        rows = np.nonzero(grp == g)[0]
        if not len(rows):
            continue
        r = np.asarray([roots[i] for i in ids], dtype=np.float64)
        ids_arr = np.asarray(ids, dtype=np.int64)
        for start in range(0, len(rows), 8192):     # chunks keep the distance matrix small
            chunk = rows[start:start + 8192]
            d = ((pts[chunk, None, :] - r[None, :, :]) ** 2).sum(axis=2)
            out[chunk] = ids_arr[d.argmin(axis=1)]  # argmin keeps the first (lowest id) on a tie
    return out.tolist()


def split_regions(scalp_points: Sequence[tuple[float, float, float]],
                  roots: dict[int, tuple[float, float, float]],
                  groups_of: dict[int, str],
                  point_groups: Sequence[str]) -> list[int]:
    """`lock_owner` per scalp point: the nearest lock root among locks of the point's group (region),
    `config.NO_OWNER` where the group has no lock.

    Straight-line distance to the root; on a tie the lowest lock id wins. A lock missing from
    `groups_of` counts as group "". Uses numpy when present (Houdini ships it). Measured, 50k points x
    100 locks: numpy 0.04 s in 4 groups, 0.2 s all in one group; the pure-Python fallback 0.2 s / 0.75 s.
    """
    if len(scalp_points) != len(point_groups):
        raise ValueError(f"{len(scalp_points)} scalp points but {len(point_groups)} point groups")
    if not len(scalp_points):
        return []
    try:
        import numpy  # noqa: F401
    except ImportError:
        return _split_python(scalp_points, roots, groups_of, point_groups)
    return _split_numpy(scalp_points, roots, groups_of, point_groups)


def region_owners(scalp_points: Sequence[tuple[float, float, float]],
                  roots: dict[int, tuple[float, float, float]],
                  radii: dict[int, float],
                  groups_of: dict[int, str],
                  point_groups: Sequence[str],
                  mesh_near: Sequence[Sequence[tuple[float, int]]] | None = None,
                  mesh_share: float = 0.0) -> list[list[int]]:
    """Locks growing hair at each scalp point: every lock of the point's group whose footprint covers
    it (distance to its root <= its radius, about half its root width), else the lock of the group
    whose MESH lies nearest over it (`mesh_near`: per point, (distance, lock) to each lock's hair mesh;
    locks within `mesh_share` of the nearest share), else the nearest lock root of the group, else none.

    Stacked locks (Helen's fringe layers: roots 1-4 mm apart, under one scalp polygon) share the
    patch they stand on instead of the nearest one taking it all; the HDA divides a shared patch's
    density between its owners, so the strand count of the scalp does not change. The footprint comes
    first so a cap lying on another one's root keeps its own root area. Past the footprints the scalp
    goes to the lock lying over it: by nearest root, Helen's 0.8 cm wide fringe locks owned 8 x 8 cm of
    scalp, and 59 % of roots spread at the set density sat over 1 cm from their own lock's mesh (under a
    neighbour's). Every lock of a group that has points gets at least its nearest point. Lists are
    sorted by distance (nearest first).
    """
    if mesh_near is not None and len(mesh_near) != len(scalp_points):
        raise ValueError(f"{len(scalp_points)} scalp points but {len(mesh_near)} mesh distance lists")
    if len(scalp_points) != len(point_groups):
        raise ValueError(f"{len(scalp_points)} scalp points but {len(point_groups)} point groups")
    by_group = _locks_by_group(roots, groups_of)
    out: list[list[int]] = []
    nearest_of: dict[int, tuple[float, int]] = {}   # lock -> (distance, point) of its nearest point
    for i, (p, g) in enumerate(zip(scalp_points, point_groups)):
        cands = []
        for lid in by_group.get(g, ()):
            d = _dist(p, roots[lid])
            cands.append((d, lid))
            if lid not in nearest_of or d < nearest_of[lid][0]:
                nearest_of[lid] = (d, i)
        inside = sorted((d, lid) for d, lid in cands if d <= max(radii.get(lid, 0.0), 0.0))
        over = sorted((d, lid) for d, lid in (mesh_near[i] if mesh_near is not None else ())
                      if lid in roots and groups_of.get(lid, "") == g)
        if inside:
            out.append([lid for _, lid in inside])
        elif over:
            out.append([lid for d, lid in over if d <= over[0][0] + max(mesh_share, 0.0)])
        elif cands:
            out.append([min(cands)[1]])
        else:
            out.append([])
    covered = {lid for owners in out for lid in owners}
    for lid, (_d, i) in nearest_of.items():
        if lid not in covered:
            out[i].append(lid)
    return out


def whorls(roots: dict[int, tuple[float, float, float]], radius: float,
           min_locks: int = 3) -> dict[int, tuple[float, float, float]]:
    """Locks that start at a whorl, each with its whorl's centre: a lock with at least `min_locks` - 1
    other roots within `radius` of its own (roots on the skin). The centre is the mean of those roots.

    Helen: ~12 crown caps start at one spot, whose skin cannot hold enough roots at the set density for
    all their starts (the approved v006 put 17.5 % of its roots within 1 cm of it), so those locks get
    extra roots packed there; the rest of the scalp stays at the set density."""
    out: dict[int, tuple[float, float, float]] = {}
    ids = sorted(roots)
    for lid in ids:
        near = [roots[o] for o in ids if _dist(roots[lid], roots[o]) <= radius]
        if len(near) >= max(min_locks, 1):
            n = len(near)
            out[lid] = (sum(p[0] for p in near) / n, sum(p[1] for p in near) / n, sum(p[2] for p in near) / n)
    return out


def section_cm2(width: float, thick: float, unit_cm: float) -> float:
    """Cross-section of a lock in cm² from its widest band (scene units): an ellipse whose
    thickness is at least 30 % of its width, so a flat ribbon still counts as a lock of hair."""
    w = max(width, 0.0) * unit_cm
    t = max(thick, config.SECTION_MIN_THICK_RATIO * max(width, 0.0)) * unit_cm
    return math.pi / 4.0 * w * t


def drag_factor(expected_strands: float, budget: int | None = None) -> float:
    """Strand fraction a slider drag grows the dragged locks at: 1 (their real count) up to `budget`
    strands, else budget / expected snapped down to a step of PREVIEW_FACTOR_STEP (0.8^k): the factor is
    in each lock's cache key, so ticks of a drag reuse the strands of a value already seen."""
    budget = config.DRAG_STRAND_BUDGET if budget is None else budget
    if expected_strands <= budget or expected_strands <= 0:
        return 1.0
    f = budget / float(expected_strands)
    step = config.PREVIEW_FACTOR_STEP
    return step ** math.ceil(math.log(f) / math.log(step) - 1e-6)


def lock_strands(density: float, region_cm2: float, section: float) -> int:
    """Strands of a lock at full count: density x its share of the scalp, at least density x its own
    cross-section (locks whose roots converge on a small patch). Same rule as the HDA's region_frame."""
    if region_cm2 <= 0.0:
        return 0
    return int(round(density * max(region_cm2, section)))


# ---------------------------------------------------------------------------
# Publish
# ---------------------------------------------------------------------------

_SCENE_VERSION_RE = re.compile(r"[._]v(\d+)(?=$|[._])", re.IGNORECASE)
_VERSION_RE = re.compile(r"^v(\d+)$", re.IGNORECASE)


def _fmt_version(n: int) -> str:
    return f"v{n:03d}"


def publish_version(scene_name: str, existing: Sequence[str]) -> tuple[str, str]:
    """Default publish version and a note for the panel.

    `scene_name` like "char_Helen_grooming_v007"; `existing` like ["v001", ..., "v006"].
    Uses the scene's vNNN unless that already exists or is not newer than the newest publish, then the
    next free one, and says why in the note.

    The note is "" when the scene's version is used. "Next free" is one above the newest publish, never
    a gap below it. Names in `existing` that are not vNNN (e.g. "_grooming") are ignored; the scene's
    version is its last `_vNNN`, an extension may follow.
    """
    taken = sorted({int(m.group(1)) for v in existing if (m := _VERSION_RE.match(v.strip()))})
    newest = taken[-1] if taken else 0
    nxt = _fmt_version(newest + 1)
    found = _SCENE_VERSION_RE.findall(scene_name or "")
    if not found:
        return nxt, f"The scene name has no _vNNN: the next free version, {nxt}."
    n = int(found[-1])
    scene_v = _fmt_version(n)
    if n in taken:
        return nxt, f"{scene_v} is already published: {nxt}, so nothing is overwritten."
    if n < newest:
        return nxt, f"{scene_v} is older than the newest publish {_fmt_version(newest)}: {nxt}."
    return scene_v, ""


def publish_paths(hip_dir: str, asset: str, version: str) -> tuple[str, str]:
    """(usd_path, tool_data_dir) for the asset groom publish, found by walking up from the scene's
    folder to the asset folder that holds `04_grooming`.

    Pure path logic (nothing is read from disk): the innermost `04_grooming` in `hip_dir` is the
    department folder. Paths come back with forward slashes (Houdini and USD take them on Windows),
    spaces kept. Raises ValueError when `hip_dir` is not inside a `04_grooming` folder or `version`
    is not vNNN.
    """
    m = _VERSION_RE.match(version or "")
    if not m:
        raise ValueError(f"publish version must look like v007, got {version!r}")
    # one spelling per version, so "v7" or "V007" cannot slip past the overwrite check into a 2nd folder
    version = _fmt_version(int(m.group(1)))
    raw = (hip_dir or "").replace("\\", "/")
    lead = "//" if raw.startswith("//") else ("/" if raw.startswith("/") else "")
    parts = [p for p in raw.split("/") if p]
    dept = config.DEPARTMENT_DIR.lower()
    idx = max((i for i, p in enumerate(parts) if p.lower() == dept), default=-1)
    if idx < 0:
        raise ValueError(f"{hip_dir!r} is not inside a {config.DEPARTMENT_DIR} folder")
    version_dir = lead + "/".join(parts[:idx + 1] + ["publish", version])
    usd = f"{version_dir}/{config.PUBLISH_FILE_TEMPLATE.format(asset=asset)}"
    return usd, f"{version_dir}/{config.TOOL_DATA_DIR}"


# ---------------------------------------------------------------------------
# Naming and colour
# ---------------------------------------------------------------------------

def lock_color(lock_id: int) -> tuple[float, float, float]:
    """Colour of a lock when colouring by lock, the same in the panel and the viewport: hues spread by
    the golden ratio, so neighbouring ids differ."""
    import colorsys

    hue = (lock_id * 0.618033988749895) % 1.0
    return tuple(round(c, 4) for c in colorsys.hsv_to_rgb(hue, 0.55, 0.92))  # type: ignore[return-value]



def lock_name(group_prefix: str, taken: Sequence[str]) -> str:
    """Next free name like "fringe_03" for a group prefix.

    One above the highest `prefix_NN` in `taken`: a gap is not reused, so a deleted (orphaned) lock's
    name never comes back on another lock. Empty prefix -> "lock".
    """
    prefix = group_prefix or "lock"
    pattern = re.compile(rf"^{re.escape(prefix)}_(\d+)$")
    n = max((int(m.group(1)) for t in taken if (m := pattern.match(t))), default=0) + 1
    while f"{prefix}_{n:0{config.LOCK_NAME_DIGITS}d}" in taken:
        n += 1
    return f"{prefix}_{n:0{config.LOCK_NAME_DIGITS}d}"
