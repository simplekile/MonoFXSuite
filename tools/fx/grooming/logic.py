"""
Pure logic of MONO Grooming (no `hou`): re-import matching, region split, publish paths, naming.

The dataclasses below are the shared contract between the adapter and the panel (spec:
docs/plans/grooming_v0_1.md, "Adapter API"). The function signatures are fixed so the other parts
can be written against them.
"""

from __future__ import annotations

import errno
import math
import os
import re
import uuid
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
    # v0.2a density layers. `strands` is what the lock is expected to grow under them (whorl roots apart):
    # auto_strands x keep_share + layer_strands
    auto_strands: int = 0       # its count without layers (density x max(skin, cross-section))
    layer_strands: int = 0      # roots the layers scatter on its skin (the network's exact count)
    keep_share: float = 1.0     # expected share of its automatic roots that stay
    mask_share: float = 1.0     # strands / auto_strands
    layered: bool = False       # a layer covers some of its skin


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


class StagedFiles:
    """Files of one publish written under temp names next to their final names, renamed at the end.

    `stage(final)` gives the temp path to write (same folder, so the rename never crosses a disk, and
    the extension kept, so USD still knows the format); `commit()` renames them all (`os.replace`), the
    ones staged `last` after the others (the USD, so a USD on disk always has its records). It refuses
    a final name that exists by then. `abort()` removes exactly what this publish made: its own temp
    files by name (never a glob, another publish may be writing next to it), the final files it had
    renamed, and the folders it created while they are empty. Nothing written before is touched.
    """

    def __init__(self, token: str | None = None):
        self.token = token or uuid.uuid4().hex[:8]
        self._files: list[tuple[str, str, bool]] = []   # (temp, final, last)
        self._dirs: list[str] = []                      # created by make_dirs, outermost first
        self._placed: list[str] = []                    # final names renamed by commit

    def make_dirs(self, path: str) -> None:
        """os.makedirs that remembers which folders it created, for abort."""
        missing = []
        d = os.path.normpath(path)
        while d and not os.path.isdir(d):
            if os.path.exists(d):
                raise NotADirectoryError(errno.ENOTDIR, "a file is in the way, not a folder", d)
            missing.append(d)
            parent = os.path.dirname(d)
            if parent == d:
                break
            d = parent
        for d in reversed(missing):
            os.mkdir(d)
            self._dirs.append(d)

    def stage(self, final: str, last: bool = False) -> str:
        folder, name = os.path.split(final)
        stem, ext = os.path.splitext(name)
        temp = os.path.join(folder, f"{stem}.{self.token}.tmp{ext}").replace("\\", "/")
        self._files.append((temp, final, last))
        return temp

    def write_text(self, final: str, text: str) -> str:
        """Write `text` to the temp name of `final` (flushed to disk, so a full disk fails here)."""
        temp = self.stage(final)
        with open(temp, "w", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        return temp

    def commit(self) -> None:
        order = [f for f in self._files if not f[2]] + [f for f in self._files if f[2]]
        for temp, final, _last in order:
            if not os.path.isfile(temp):
                raise FileNotFoundError(errno.ENOENT, "nothing was written", temp)
            if os.path.exists(final):
                raise FileExistsError(errno.EEXIST, "already exists, not overwritten", final)
            os.replace(temp, final)
            self._placed.append(final)

    def abort(self) -> list[str]:
        """Remove what this publish made; returns what could not be removed (for the message)."""
        left = []
        for path in [t for t, _f, _l in self._files] + self._placed:
            try:
                if os.path.isfile(path):
                    os.remove(path)
            except OSError:
                left.append(path)
        for d in reversed(self._dirs):
            try:
                if os.path.isdir(d) and not os.listdir(d):
                    os.rmdir(d)
            except OSError:
                pass
        self._placed = []
        return left


_NOT_WRITABLE = {errno.EACCES, errno.EPERM, errno.EROFS}


def publish_error(exc: BaseException) -> str:
    """What the panel says when a publish write fails: the cases an artist can act on by name."""
    path = str(getattr(exc, "filename", None) or "").replace("\\", "/")
    where = f": {path}" if path else ""
    if isinstance(exc, FileExistsError):
        return f"already published, not overwritten{where}"
    if isinstance(exc, OSError):
        if exc.errno == errno.ENOSPC or getattr(exc, "winerror", None) in (39, 112):
            return f"the disk is full{where}"
        if exc.errno in _NOT_WRITABLE or getattr(exc, "winerror", None) == 5:
            return f"the folder is not writable{where}"
        if exc.strerror:
            return f"{exc.strerror}{where}"
    text = str(exc)
    low = text.lower()
    if "no space" in low or "disk full" in low or "not enough space" in low:
        return f"the disk is full ({text})"
    if "permission denied" in low or "access is denied" in low or "read-only" in low:
        return f"the folder is not writable ({text})"
    return text or type(exc).__name__


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


# ---------------------------------------------------------------------------
# v0.2a density layers (docs/plans/grooming_v0_2.md; the model: config.MASK_MODES). Every function takes plain
# floats or numpy arrays (one number per scalp point), so the HDA's mask_read, the brush and the tests share
# one rule.
#
# A density layer over what lies below:   density = below + (D - below) x e,   e = its mask x its opacity.
# The bottom is the automatic groom, which is not a number but the automatic ROOTS (gathered at lock starts
# and whorls, thin under floating mesh), so the stack is carried as two numbers per skin point:
#     keep  the share of the automatic roots still there: the product of (1 - e) over the layers
#     add   the density the layers themselves ask, strands / cm2: add x (1 - e) + D x e, layer by layer
# and the density is   automatic x keep + add   (`layer_density`): the same rule, written apart.
# ---------------------------------------------------------------------------

def _np():
    import numpy as np
    return np


def mask_blend(below, value, mode: str):
    """What a layer of `value` makes of the mask value `below` at full coverage and opacity (config.MASK_MODES):
    Normal value, Multiply below x value, Add, Subtract, Min, Max."""
    np = _np()
    if mode == "normal":
        return value + below * 0
    if mode == "multiply":
        return below * value
    if mode == "add":
        return below + value
    if mode == "subtract":
        return below - value
    if mode == "min":
        return np.minimum(below, value)
    if mode == "max":
        return np.maximum(below, value)
    raise ValueError(f"mask blend mode {mode!r}")


def mask_stack(rows, start=0.0):
    """The mask of one density layer, 0..1: its paint and fill layers blended bottom to top, starting from black
    (a density layer with nothing painted applies nowhere). `rows`, bottom first: (layer, value, coverage);
    `layer` has on, mode, opacity; `value` and `coverage` are numbers or arrays per scalp point. One layer:
        m = below + (blend(below, value) - below) x coverage x opacity, clamped to 0..1
    Layers that are off are skipped. `start`: 0.0, or an array of zeros (the shape of the result)."""
    np = _np()
    m = np.asarray(start, dtype=np.float64) * 1.0
    for layer, value, coverage in rows:
        if not layer.on:
            continue
        m = np.clip(m + (mask_blend(m, value, layer.mode) - m) * (coverage * layer.opacity), 0.0, 1.0)
    return m


def legacy_mask(rows, start=1.0):
    """(keep, add) of a 0..1 mask as the test build before density layers read it (`groom_data` schema 5, and
    the 0..1 layers of schemas 2 / 3): the stack's value t = keep + add starts at 1, the automatic groom (keep 1,
    add 0), and a layer changes it to t + (blend(t, value) - t) x coverage x opacity, moving the two parts as
    its mode means:
      Normal    overrides what is below, automatic groom included: both x (1 - e), add + value x e
      Multiply  scales what is below: both x (1 - e + e x value)
      Add       add + value x e          Subtract  add - value x e (under 0 it eats into keep)
      Min       where t is over value both are scaled down to it
      Max       where t is under value the difference goes to add
    The density was automatic x keep + the lock's Density x add: white = the lock's Density, black = no hair,
    Multiply and Min thin the automatic groom. `rows`, bottom first: (layer, value, coverage) as `mask_stack`.
    A density layer marked `legacy` carries such a stack: over (keep, add) below it gives keep x keep',
    add x keep' + D x add' (`MaskData.weights`), D the owner's Density when the file was read."""
    np = _np()
    keep = np.asarray(start, dtype=np.float64) * 1.0
    add = keep * 0.0
    for layer, value, coverage in rows:
        if not layer.on:
            continue
        e = coverage * layer.opacity
        t = keep + add
        mode = layer.mode
        if mode == "normal":
            keep, add = keep * (1.0 - e), add * (1.0 - e) + value * e
        elif mode == "multiply":
            f = 1.0 - e + e * value
            keep, add = keep * f, add * f
        elif mode == "add":
            add = add + value * e
        elif mode == "subtract":
            add = add - value * e
        elif mode == "min":
            f = np.where(t > value, 1.0 + (value / np.maximum(t, 1e-12) - 1.0) * e, 1.0)
            keep, add = keep * f, add * f
        elif mode == "max":
            add = add + np.maximum(value - t, 0.0) * e
        else:
            raise ValueError(f"mask blend mode {mode!r}")
        add = np.clip(add, -keep, 1.0 - keep)
    keep = np.clip(keep + np.minimum(add, 0.0), 0.0, 1.0)
    return keep, np.clip(add, 0.0, 1.0)


def density_over(keep, add, density, effect):
    """One density layer of `density` (strands / cm2) over (keep, add) with effect = its mask x its opacity:
    below + (D - below) x effect, on both parts. Returns (keep, add)."""
    return keep * (1.0 - effect), add * (1.0 - effect) + density * effect


def density_compose(rows, start=1.0):
    """(keep, add) through density layers, bottom first: `rows` of (density, effect), numbers or arrays per
    scalp point. Over the automatic groom (keep 1, add 0). `start`: 1.0, or an array of ones."""
    np = _np()
    keep = np.asarray(start, dtype=np.float64) * 1.0
    add = keep * 0.0
    for density, effect in rows:
        keep, add = density_over(keep, add, density, effect)
    return keep, add


def layer_density(automatic, keep, add):
    """The density where layers cover the skin: automatic x keep + the layers' own density."""
    return automatic * keep + add


_OWNER_RANK = {"all": 0, "group": 1, "locks": 2}


def density_order(masks: Sequence["object"], lock_id: int, group_id: str) -> list:
    """The density layers that are on and owned by a row the lock is under, in the order they apply, bottom
    first: the layers of all locks, then of the lock's group, then of the lock (the more specific wins); inside
    one owner in the list's order (the upper layer wins)."""
    reach = [m for m in masks if getattr(m, "kind", "") == "density" and m.on and m.applies(lock_id, group_id)]
    return sorted(reach, key=lambda m: _OWNER_RANK.get(m.scope, 0))      # stable: the list's order inside a rank


def mask_scope_sets(masks: Sequence["object"], locks: Sequence[tuple]
                    ) -> tuple[list[tuple[int, ...]], dict[int, int]]:
    """Which density layers reach which lock. `masks`: the layer list, bottom first; `locks`: (lock id, group
    id). Returns the distinct sets, each the ids of the density layers that are on and reach the lock in the
    order they apply (`density_order`), and per lock id the index of its set, -1 when no layer reaches it (its
    density is the automatic one). Locks with the same set share one (keep, add) on the scalp."""
    sets: list[tuple[int, ...]] = []
    of: dict[int, int] = {}
    for lock in locks:
        lock_id, group_id = lock[0], lock[1]
        ids = tuple(m.id for m in density_order(masks, lock_id, group_id))
        if not ids:
            of[lock_id] = -1
            continue
        if ids not in sets:
            sets.append(ids)
        of[lock_id] = sets.index(ids)
    return sets, of


def owners_sharing(layer, prim_owners: Sequence[int], group_of: dict) -> int:
    """How many of a skin prim's owners (lock ids) a density layer's D is shared by: the owners the layer is
    owned for. "= D" owned by all locks means all the locks on that skin give D together; owned by a group,
    the group's locks there together; owned by a lock, that lock alone. At least 1."""
    return max(1, sum(1 for lock_id in prim_owners if layer.applies(lock_id, group_of.get(lock_id, ""))))


def brush_weights(dist, radius: float, soft: float = config.BRUSH_SOFT):
    """Weight of a dab at distance `dist` from its centre: 1 inside (1 - soft) x radius, easing to 0 at the
    radius (smoothstep). `soft` 0 is a hard edge."""
    inner = radius * (1.0 - min(1.0, max(0.0, soft)))
    span = max(radius - inner, 1e-9)
    try:
        w = min(1.0, max(0.0, (radius - dist) / span))
    except (TypeError, ValueError):
        import numpy as np
        w = np.clip((radius - dist) / span, 0.0, 1.0)
    return w * w * (3.0 - 2.0 * w)


COVER_GONE = 1e-6      # an erased coverage under this is no coverage


def mask_dab(value, coverage, weight, paint: float, erase: bool = False):
    """One dab on a paint layer's (value, coverage) with the brush `weight` there (numbers or arrays); returns
    the new (value, coverage). Paint: skin not painted before takes the brush value outright (its coverage,
    the weight, is what fades the edge), painted skin moves towards it by the weight against the coverage it
    has (weight / coverage, at most 1); coverage only grows. So black and white both override what is below in
    the mask, and a stroke painted again in another value with the same brush replaces it to its very edge:
    moving by the weight alone, soft black over soft white left (1 - w) x w of the white along the rim (up
    to a quarter of the layer's density, a ring). Erase removes the layer's own paint: coverage
    x (1 - weight), the value stays (it means nothing where the layer has no coverage); it never paints black.
    What is left under COVER_GONE is none: a brush weight of 0.99999994 left 1e-21 after three dabs, and the
    skin still counted as painted."""
    np = _np()
    value, coverage = np.asarray(value, dtype=np.float64), np.asarray(coverage, dtype=np.float64)
    weight = np.asarray(weight, dtype=np.float64)
    if erase:
        left = coverage * (1.0 - weight)
        return value, np.where(left < COVER_GONE, 0.0, left)
    v = np.where(coverage <= 0, paint,
                 value + (paint - value) * np.minimum(1.0, weight / np.maximum(coverage, 1e-12)))
    return np.where(weight > 0, v, value), np.maximum(coverage, weight)


# density (strands / cm2) -> colour. Stops are shares of a reference density (the groom's default): the
# ramp is fine round the set density and still tells 30 x from 50 x (Helen's crown: 5,100 against 7,000 / cm2)
DENSITY_STOPS = (0.0, 0.5, 1.0, 2.0, 8.0, 48.0)
DENSITY_RAMP = ((0.02, 0.02, 0.10), (0.10, 0.25, 0.75), (0.15, 0.70, 0.45), (0.85, 0.75, 0.15),
                (1.00, 0.55, 0.35), (1.00, 1.00, 1.00))      # each stop brighter than the one before
LAYER_UNPAINTED = (0.12, 0.12, 0.13)   # "layer" view: skin the layer does not cover


def density_color(density: float, reference: float) -> tuple[float, float, float]:
    """Colour of the scalp in the "density" view: `density` over `reference` (the groom's default density)
    along DENSITY_STOPS / DENSITY_RAMP: near black at 0, green at the reference, yellow at twice it, white
    from 48 times it."""
    t = min(max(density / max(reference, 1e-9), 0.0), DENSITY_STOPS[-1])
    i = max(k for k in range(len(DENSITY_STOPS) - 1) if DENSITY_STOPS[k] <= t)
    f = (t - DENSITY_STOPS[i]) / (DENSITY_STOPS[i + 1] - DENSITY_STOPS[i])
    return tuple(x + (y - x) * f for x, y in zip(DENSITY_RAMP[i], DENSITY_RAMP[i + 1]))   # type: ignore[return-value]


def layer_color(value: float, coverage: float = 1.0) -> tuple[float, float, float]:
    """Colour of the scalp in the "layer" view (one layer alone): its value as a grey (white 1, black 0) where
    it has coverage, fading into LAYER_UNPAINTED where it has none."""
    k = min(max(coverage, 0.0), 1.0)
    v = min(max(value, 0.0), 1.0)
    return tuple(u + (v - u) * k for u in LAYER_UNPAINTED)   # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Control points and drawn locks (v0.2b; docs/plans/grooming_v0_2.md "v0.2b Lock redraw and control points",
# the spike's rule: VEX_SPINE_EDIT in sandbox tests/t76_redraw_spike/build_proto.py).
#
# A spine is a polyline P (n, 3) with, per point, its tangent T and its width axis A (`tangentu`, `lock_axis`),
# scene units. Its ROOT FRAME: origin P[0], rows tangent t0, width axis a0 (A[0] made square to t0), thickness
# axis m0 = t0 x a0. A lock's control points (`Lock.spine`) are K places in that frame. The edit:
#     m_k = the measured spine at k / (K - 1) of its length;  c_k = the stored place in world;
#     D_k = c_k - m_k  (the move of handle k; a moved root c_0 goes onto the skin first, `snap_root`)
#     each spine point i, at x = s_i / L x (K - 1), moves by the Catmull-Rom (uniform, ends clamped) of the D_k
# and the frame turns with the new tangent (the shortest turn from the old one), so the offsets `fit_to_lock`
# reads carry the mesh along. Handles equal to the measured ones (`measured_handles`) move nothing.
# Every function takes and returns plain sequences or numpy arrays; nothing here knows of `hou`.
# ---------------------------------------------------------------------------

def _arr(points, n_cols: int = 3):
    np = _np()
    out = np.asarray(points, dtype=float)
    return out.reshape(-1, n_cols) if out.size else np.zeros((0, n_cols))


def _unit(v, eps: float = 1e-12):
    np = _np()
    n = np.linalg.norm(v, axis=-1, keepdims=True)
    return v / np.maximum(n, eps)


def arc_lengths(P):
    """Cumulative length along polyline P (n, 3): s_0 = 0 ... s_(n-1) = its length."""
    np = _np()
    P = _arr(P)
    return np.concatenate([[0.0], np.cumsum(np.linalg.norm(np.diff(P, axis=0), axis=1))])


def at_lengths(P, s):
    """The points of polyline P at lengths s along it (clamped to its ends)."""
    np = _np()
    P = _arr(P)
    S = arc_lengths(P)
    s = np.clip(np.asarray(s, dtype=float), 0.0, S[-1])
    j = np.clip(np.searchsorted(S, s, side="right") - 1, 0, len(P) - 2)
    f = ((s - S[j]) / np.maximum(S[j + 1] - S[j], 1e-12))[:, None]
    return P[j] * (1 - f) + P[j + 1] * f


def root_frame(P, T, A):
    """(origin, R) of a spine: R's rows are the tangent, the width axis and the thickness axis at its root, so a
    place p in the frame is origin + p @ R in world."""
    np = _np()
    P, T, A = _arr(P), _arr(T), _arr(A)
    t0 = _unit(T[0])
    a0 = _unit(A[0] - t0 * np.dot(A[0], t0))
    return P[0].copy(), np.stack([t0, a0, np.cross(t0, a0)])


def frame_to_world(points, origin, R):
    """Places in a root frame -> world (scene units)."""
    return _np().asarray(origin, dtype=float) + _arr(points) @ _np().asarray(R, dtype=float)


def world_to_frame(points, origin, R):
    """World places -> the root frame (the inverse of `frame_to_world`, R being a rotation)."""
    np = _np()
    return (_arr(points) - np.asarray(origin, dtype=float)) @ np.asarray(R, dtype=float).T


def direction_to_frame(vector, R):
    """A direction (a rotation axis, a drag on the view plane) from world into the root frame."""
    np = _np()
    return np.asarray(R, dtype=float) @ np.asarray(vector, dtype=float)


def direction_to_world(vector, R):
    np = _np()
    return np.asarray(vector, dtype=float) @ np.asarray(R, dtype=float)


def catmull_rom(D, x):
    """Uniform Catmull-Rom through the rows of D (K, ...), ends clamped, at parameters x in [0, K - 1]: the
    spike's VEX rule."""
    np = _np()
    D = np.asarray(D, dtype=float)
    K = len(D)
    x = np.clip(np.asarray(x, dtype=float), 0.0, K - 1)
    k = np.minimum(np.floor(x).astype(int), K - 2)
    f = (x - k).reshape((-1,) + (1,) * (D.ndim - 1))
    p0, p1, p2, p3 = D[np.maximum(k - 1, 0)], D[k], D[k + 1], D[np.minimum(k + 2, K - 1)]
    return 0.5 * ((2 * p1) + (-p0 + p2) * f + (2 * p0 - 5 * p1 + 4 * p2 - p3) * f * f
                  + (-p0 + 3 * p1 - 3 * p2 + p3) * f ** 3)


def handle_weights(shares, K: int):
    """(len(shares), K): row i holds how much each handle's move adds at share `shares[i]` of the length (the
    Catmull-Rom of `catmull_rom` written as a matrix: moves at the points = weights @ D)."""
    np = _np()
    return catmull_rom(np.eye(K), np.asarray(shares, dtype=float) * (K - 1))


def handle_shares(K: int):
    """Where the K handles sit along the lock: k / (K - 1) of its length."""
    return _np().linspace(0.0, 1.0, K)


def measured_handles(P, T, A, K: int):
    """The measured spine's K handles in its root frame: what "no edit" stores (moves nothing)."""
    S = arc_lengths(P)
    origin, R = root_frame(P, T, A)
    out = world_to_frame(at_lengths(P, S[-1] * handle_shares(K)), origin, R)
    out[0] = 0.0
    return out


def handle_count(length_cm: float, override: int | None = None) -> int:
    """How many handles a lock shows (U1): the artist's number when set, else one every HANDLE_SPACING_CM of its
    length; both kept in HANDLES_MIN..HANDLES_MAX (Helen: fringe 4-5, the 89.6 cm back locks 12)."""
    if override is not None and not isinstance(override, bool):
        n = int(override)
    else:
        n = int(math.ceil(max(float(length_cm), 0.0) / config.HANDLE_SPACING_CM - 1e-9)) + 1
    return min(config.HANDLES_MAX, max(config.HANDLES_MIN, n))


def lock_handle_count(lock, length_cm: float) -> int:
    """The handles a lock has now: an edit's own count, a drawn lock's curve, else `handle_count`."""
    if getattr(lock, "source", config.SOURCE_MESH) == config.SOURCE_DRAWN and getattr(lock, "curve", None):
        return len(lock.curve)
    if getattr(lock, "spine", None):
        return len(lock.spine)
    return handle_count(length_cm, getattr(lock, "handles", None))


def root_moved(handles) -> bool:
    """The root handle is off the root frame's origin: the artist moved it (it then goes onto the skin, U5)."""
    h = _arr(handles)
    return len(h) > 0 and float(_np().linalg.norm(h[0])) > config.ROOT_MOVED_EPS


@dataclass
class EditedSpine:
    """A spine after the edit, per point what the network writes back (`P`, `tangentu`, `lock_axis`,
    `lock_minor`, `curveu`) and per prim `root`, `direction`; `edited` False = the measured spine as given."""
    P: "object"
    tangent: "object"
    axis: "object"
    minor: "object"
    curveu: "object"
    root: "object"
    direction: "object"
    edited: bool


def _turn(v, old, new):
    """v turned by the shortest rotation taking unit `old` to unit `new` (VEX `dihedral` + `qrotate`), per row."""
    np = _np()
    axis = np.cross(old, new)
    s = np.linalg.norm(axis, axis=-1, keepdims=True)
    c = np.sum(old * new, axis=-1, keepdims=True)
    k = axis / np.maximum(s, 1e-12)
    out = v * c + np.cross(k, v) * s + k * np.sum(k * v, axis=-1, keepdims=True) * (1 - c)
    return np.where(s > 1e-12, out, v)


def edited_spine(P, T, A, handles, snap_root=None) -> EditedSpine:
    """The spike's rule (module notes above): the measured spine P with tangents T and width axes A (scene
    units), bent by `handles` (K places in its root frame; fewer than 2 = no edit). `snap_root(world_point) ->
    world_point` puts a moved root on the skin (the network's scalp lookup); without it the root stays where it
    was stored. A root stored at the frame's origin is the measured root, never snapped."""
    np = _np()
    P, T, A = _arr(P), _arr(T), _arr(A)
    H = _arr(handles)
    n, K = len(P), len(H)
    if K < 2 or n < 2:
        t = _unit(T)
        a = _unit(A - t * np.sum(A * t, axis=1, keepdims=True))
        S = arc_lengths(P) if n else np.zeros(0)
        L = S[-1] if n else 0.0
        return EditedSpine(P.copy(), t, a, np.cross(t, a), S / L if L > 0 else np.zeros(n),
                           P[0].copy() if n else None, _unit(P[-1] - P[0]) if n else None, False)
    S = arc_lengths(P)
    L = max(S[-1], 1e-9)
    origin, R = root_frame(P, T, A)
    marks = at_lengths(P, L * handle_shares(K))
    places = frame_to_world(H, origin, R)
    if snap_root is not None and root_moved(H):
        places[0] = np.asarray(snap_root(places[0]), dtype=float)
    D = places - marks
    N = P + catmull_rom(D, S / L * (K - 1))
    tn = _unit(N[np.minimum(np.arange(n) + 1, n - 1)] - N[np.maximum(np.arange(n) - 1, 0)])
    told = _unit(T)
    a = _turn(_unit(A - told * np.sum(A * told, axis=1, keepdims=True)), told, tn)
    a = _unit(a - tn * np.sum(a * tn, axis=1, keepdims=True))
    S2 = arc_lengths(N)
    return EditedSpine(N, tn, a, np.cross(tn, a), S2 / S2[-1] if S2[-1] > 0 else np.zeros(n), N[0].copy(),
                       _unit(N[-1] - N[0]), True)


def _poly_dist(X, C):
    """The distance of each point of X to the polyline C."""
    np = _np()
    a, b = C[:-1], C[1:]
    ab = b - a
    l2 = np.maximum((ab ** 2).sum(1), 1e-18)
    t = np.clip(((X[:, None, :] - a[None]) * ab[None]).sum(-1) / l2[None], 0, 1)
    return np.linalg.norm(X[:, None, :] - (a[None] + t[..., None] * ab[None]), axis=-1).min(1)


def curve_gap(X, C) -> float:
    """How far apart two polylines lie at most, each against the other (scene units)."""
    X, C = _arr(X), _arr(C)
    return float(max(_poly_dist(X, C).max(), _poly_dist(C, X).max()))


def resample_spine(P, T, A, handles, K: int, unit_cm: float):
    """An edit given another handle count (U1: changing the number on an edited lock keeps its shape): the K new
    handles' moves are fitted (least squares over the spine's points, root and tip moves kept exactly) to the
    moves the old handles give, so the edited spine stays where it was. Returns (new handles in the root frame,
    how far the new edited spine lies from the old one at most, cm). No edit -> ([], 0). The root handle is kept
    as stored (a root not moved stays at the origin). Going down in count may not hold a local bend (expect
    more than config.RESAMPLE_TOL_CM then; the caller says so)."""
    np = _np()
    H = _arr(handles)
    if len(H) < 2:
        return np.zeros((0, 3)), 0.0
    K = int(K)
    if K < 2:
        raise ValueError("a lock needs at least 2 handles")
    P, T, A = _arr(P), _arr(T), _arr(A)
    S = arc_lengths(P)
    L = max(S[-1], 1e-9)
    shares = S / L
    origin, R = root_frame(P, T, A)
    D_old = frame_to_world(H, origin, R) - at_lengths(P, L * handle_shares(len(H)))
    moves = handle_weights(shares, len(H)) @ D_old
    W = handle_weights(shares, K)
    D = np.zeros((K, 3))
    D[0], D[-1] = D_old[0], D_old[-1]
    rhs = moves - W[:, :1] @ D[:1] - W[:, -1:] @ D[-1:]
    if K > 2:
        D[1:-1] = np.linalg.lstsq(W[:, 1:-1], rhs, rcond=None)[0]
    new = world_to_frame(at_lengths(P, L * handle_shares(K)) + D, origin, R)
    new[0] = H[0]
    gap = float(np.linalg.norm(edited_spine(P, T, A, new).P - edited_spine(P, T, A, H).P, axis=1).max())
    return new, gap * float(unit_cm)


def rotate_about_root(points, axis, degrees: float):
    """`points` (handles in a root frame, or a drawn lock's curve in world) turned about their first point (the
    root) round `axis` (in the same space), right-handed: the root stays."""
    np = _np()
    X = _arr(points)
    if len(X) == 0:
        return X
    k = _unit(np.asarray(axis, dtype=float))
    a = math.radians(float(degrees))
    v = X - X[0]
    out = v * math.cos(a) + np.cross(k, v) * math.sin(a) + k * (v @ k)[:, None] * (1 - math.cos(a))
    return X[0] + out


def scale_about_root(points, factor: float):
    """`points` scaled about their first point (the root), which stays: a longer or shorter lock."""
    X = _arr(points)
    if len(X) == 0:
        return X
    return X[0] + (X - X[0]) * float(factor)


def _fit_stroke(Q, K: int):
    """K places at equal lengths along polyline Q (the handles a curve through them keeps)."""
    S = arc_lengths(Q)
    return at_lengths(Q, S[-1] * handle_shares(K))


def curve_points(handles, per_segment: int = config.CURVE_SAMPLES):
    """The Catmull-Rom curve through a drawn lock's handles (uniform, ends clamped), sampled densely."""
    np = _np()
    H = _arr(handles)
    if len(H) < 2:
        return H.copy()
    return catmull_rom(H, np.linspace(0, len(H) - 1, per_segment * (len(H) - 1) + 1))


def drawn_spine(handles, n_points: int):
    """A drawn lock's spine: its handles' curve (`curve_points`) at n_points equal lengths, root first."""
    np = _np()
    C = curve_points(handles)
    if len(C) < 2:
        return C
    return at_lengths(C, np.linspace(0.0, arc_lengths(C)[-1], int(n_points)))


def stroke_handles(stroke, unit_cm: float, tol_cm: float = config.STROKE_TOL_CM):
    """A drawn stroke (world, root first) as the fewest handles, config.HANDLES_MIN up, at equal lengths along it,
    whose curve (`curve_points`) lies within tol_cm of the stroke. Returns (handles, gap cm); past
    config.STROKE_HANDLES_MAX it gives that many and the gap they leave."""
    Q = _arr(stroke)
    if len(Q) < 2 or arc_lengths(Q)[-1] <= 0:
        raise ValueError("a stroke needs two points apart")
    for K in range(config.HANDLES_MIN, config.STROKE_HANDLES_MAX + 1):
        H = _fit_stroke(Q, K)
        gap = curve_gap(Q, curve_points(H)) * float(unit_cm)
        if gap <= tol_cm:
            break
    return H, gap


def redraw_handles(P, T, A, stroke, unit_cm: float, tol_cm: float = config.STROKE_TOL_CM, snap_root=None):
    """A lock redrawn along `stroke` (world, root first): the fewest handles (config.HANDLES_MIN up) placed on the
    stroke at k / (K - 1) of its length whose edit (`edited_spine`) lies within tol_cm of it. Returns (handles in
    the root frame, gap cm); past config.STROKE_HANDLES_MAX, that many and the gap. A stroke starting off the
    measured root moves the root (onto the skin with `snap_root`, as the network does)."""
    Q = _arr(stroke)
    if len(Q) < 2 or arc_lengths(Q)[-1] <= 0:
        raise ValueError("a stroke needs two points apart")
    origin, R = root_frame(P, T, A)
    for K in range(config.HANDLES_MIN, config.STROKE_HANDLES_MAX + 1):
        H = world_to_frame(_fit_stroke(Q, K), origin, R)
        if not root_moved(H):
            H[0] = 0.0
        gap = curve_gap(Q, edited_spine(P, T, A, H, snap_root).P) * float(unit_cm)
        if gap <= tol_cm:
            break
    return H, gap


def drawn_footprint_cm(width_cm: float) -> float:
    """The radius round its root of the skin a drawn lock owns (U3; the same rule as a measured lock's
    footprint): config.REGION_FOOTPRINT x its width."""
    return config.REGION_FOOTPRINT * max(float(width_cm), 0.0)


def drawn_profile(curveu, width_cm: float, thick_cm: float, taper: float = config.DRAWN_TAPER_DEFAULT):
    """A drawn lock's width and thickness (cm) along it: the set values at the root, `taper` of them at the tip,
    falling as 1 - (1 - taper) u^2 (the spike's drawn lock)."""
    np = _np()
    u = np.clip(np.asarray(curveu, dtype=float), 0.0, 1.0)
    prof = 1 - (1 - min(1.0, max(0.0, float(taper)))) * u ** 2
    return width_cm * prof, thick_cm * prof


def flat_handles(handles) -> list[float]:
    """Handles as the flat float array the network stores on a spine prim (config.ATTR_EDIT_CP)."""
    return [float(c) for row in _arr(handles) for c in row]


def unflat_handles(values) -> list[tuple[float, float, float]]:
    """The inverse of `flat_handles`; a length that is not a multiple of 3 drops the tail."""
    v = [float(c) for c in values]
    return [tuple(v[i:i + 3]) for i in range(0, len(v) - len(v) % 3, 3)]   # type: ignore[misc]


def reset_locks(locks, ids) -> list[int]:
    """Reset the locks with ids `ids` to their measured spines (`Lock.reset_spine`): the ids that had an edit."""
    wanted = set(ids)
    return [lk.id for lk in locks if lk.id in wanted and lk.reset_spine()]
