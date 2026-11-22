"""
Houdini side of MONO Grooming: the only place that touches `hou` for the tool.

The panel's controller talks to this module only (spec: docs/plans/grooming_v0_1.md, "Adapter API").
Every public function runs on Houdini's main thread. The helpers marked "pure" take plain data and
are tested without Houdini (tests/test_grooming_adapter.py). The HDA network itself is built by
tools/fx/grooming/build_hda.py; its two Python SOPs call `cook_assign` and `cook_frozen_regions`.
"""

from __future__ import annotations

import datetime as _dt
import getpass
import hashlib
import json
import math
import os
import re
import sys
from dataclasses import replace
from typing import Any, Iterable, Sequence

try:
    import hou
except ImportError:
    hou = None  # type: ignore[assignment]

from apps.houdini import grooming_masks
from apps.houdini.grooming_masks import (  # noqa: F401  (the adapter API's mask functions; the HDA's mask_read)
    brush, cook_mask_read, import_masks, mask_add, mask_clear, mask_cover, mask_dropped, mask_fill, mask_invert,
    mask_move, mask_problem,
    mask_rebake, mask_remove, mask_set, mask_stroke, mask_values, masks_from_publish, paint_enter, paint_exit,
    paint_layer, set_brush,
)
from tools.fx.grooming import config, logic, model
from tools.fx.grooming.logic import DetectReport, LockInfo, MeshPiece, PublishResult

# Internal nodes of the HDA the adapter reads (names fixed by build_hda.py).
NODE_SPINES_RAW = "SPINES_RAW"       # one spine per hair-mesh piece, measured, no lock ids yet
NODE_SPINES_LOCKS = "SPINES_LOCKS"   # spines with lock_id / name / group and resolved settings
NODE_SPINES = "SPINES"               # spines after settings (width_mult, twist_add ...), the edit and drawn locks
NODE_SPINES_MEASURED = "SPINES_MEASURED"   # v0.2b: spines after Root to skin, before the edit (handles are on them)
NODE_MESH_CARRIED = "MESH_CARRIED"   # v0.2b: the hair mesh with each edited lock's piece on its edited spine
NODE_ANIM_SCALP = "ANIM_SCALP"       # v0.2b: the animated scalp (input 4) with detail deform_ok / point counts
ATTR_DRAWN = "drawn"                 # v0.2b: prim attribute on spines, 1 for a lock drawn on the skin
ROOT_SAME_CM = 1e-4                  # a handle given within this of where the root is now: the root did not move
NODE_SCALP_FINE = "SCALP_FINE"       # scalp after the bilinear subdivision used for regions
NODE_SCALP_REGIONS = "SCALP_REGIONS" # scalp prims with lock_owners (shared when stacked), share, density, area_cm2
ATTR_OWNER_DIST = "owner_dist"
ATTR_LOCK_OWNERS = "lock_owners"     # int array: every lock growing hair on a scalp prim
NODE_HAIR = "HAIR"                   # strands at the current density (preview or full)
NODE_PUBLISH_USD = "PUBLISH_USD"     # usdexport SOP fed by the rest groom
NODE_GROOM_REST = "GROOM_REST"       # output 1 "Groom" before the shot deform: every lock, full, contract attribs
NODE_GROOM = "GROOM"                 # output 1 "Groom"

NODE_REGION_MESH = "region_mesh"     # per SCALP_FINE prim: distance to each lock's hair mesh (Update regions)
ATTR_REGION_RULE = "region_rule"     # detail on the frozen regions: the rule they were split by
ATTR_WHORL_LOCKS = "whorl_locks"     # detail on the frozen regions: locks that start at a whorl
ATTR_WHORL_CENTRES = "whorl_centres" # ... and their whorl's centre (3 floats each)
PARM_REGIONS = "regions"             # hidden geometry data parm: the frozen region split
PARM_DISPLAY = "display_mode"
PARM_COLOR_BY = "color_by"
PARM_PREVIEW = "preview_fraction"
PARM_PUBLISH_PATH = "publish_path"   # hidden, read by PUBLISH_USD
PARM_PUBLISH_VERSION = "publish_version"
PARM_ISOLATE = "isolate_ids"         # hidden: locks shown alone ("" = none); display only, never undone
PARM_DRAG_PREVIEW = "preview_ids"    # hidden: locks a slider is dragging, grown light; display only
PARM_STRANDS = "strand_ids"          # hidden: locks drawn as strands, not packed ("all": every lock)
STRANDS_ALL = "all"                  # set_strands(node, STRANDS_ALL): the whole groom as strands
PARM_FOCUS = "focus_ids"             # hidden: the panel's selection; the other locks are drawn see-through
PARM_DRAG_FACTOR = "drag_factor"     # hidden: strand fraction of the locks a slider drags (1 = real count)
PARM_XRAY = "xray_opacity"           # hidden: alpha per strand of the locks out of focus (the panel's X-ray)
PARM_COOK_ALL = "cook_all"           # hidden: 1 while publishing: every lock, hidden or isolated out
PARM_DISPLAY_EFF = "display_eff"     # hidden expression: the mode drawn (Display, or While playing)
PARM_PLAYING = "playing"             # hidden: 1 while the timeline plays (playbar callback, undo off)

# Parms whose value never reaches the per-lock hair cook (display, publish, deform, what the geometry
# already carries): left out of the cache key, so changing them recooks no lock.
_KEY_SKIP_PARMS = {config.DATA_PARM, PARM_REGIONS, config.MASK_PARM, config.UNDO_CACHE_PARM, config.UNDO_DEFORM_PARM, PARM_DISPLAY, PARM_COLOR_BY, PARM_PREVIEW, "preview_max",
                   PARM_PUBLISH_PATH, PARM_PUBLISH_VERSION, PARM_ISOLATE, PARM_DRAG_PREVIEW, PARM_STRANDS,
                   PARM_FOCUS, PARM_DRAG_FACTOR, PARM_COOK_ALL, PARM_XRAY,
                   "shot_deform", "deform_active", "anim_wired",   # per lock: do_capture; deform_radius stays
                   PARM_DISPLAY_EFF, PARM_PLAYING, "play_display",
                   "rest_frame", "detect", "split_regions", "publish", "scalp_wired"}
# Spine prim attributes the hair loop does not read (display, filters, cache bookkeeping).
_KEY_SKIP_ATTRIBS = {"visible", "shown", "grows", "lock_cd", "group_cd", "lock_match", "cached", "cache_key",
                     "cache_mode", "disp", "row_display",   # a lock's display reaches its key as its factor
                     "mask_set", "mask_add_n",              # its layers reach it as the digest of their cover
                     "auto_key", "auto_cached"}
_CACHE_ATTR = "_mono_grooming_hair_cache"
_PLAYBAR_ATTR = "_mono_grooming_playbar_callback"
MERGED_LOCK = -1                     # LockCache slot of a whole merge (hair_cache / groom_cache), not a lock
MERGED_MODE = "merged:"
CACHE_NET_VERSION = "partial-1-root-spread-6-mask-23-spine-1"      # bump when the per-lock network changes what it makes

DEFAULT_GROUP = "main"
UNDO_PREFIX = "MONO Grooming: "

_GROUP_PALETTE = (
    (0.90, 0.45, 0.30), (0.30, 0.62, 0.90), (0.45, 0.80, 0.40), (0.85, 0.70, 0.25),
    (0.70, 0.45, 0.85), (0.30, 0.80, 0.75), (0.90, 0.40, 0.60), (0.60, 0.60, 0.60),
)
UNDETECTED_COLOR = (0.25, 0.25, 0.25)


# ---------------------------------------------------------------------------
# Pure helpers (no hou)
# ---------------------------------------------------------------------------

def lock_color(lock_id: int) -> tuple[float, float, float]:
    """Display colour of a lock (logic.lock_color, the panel's colour too); grey before Detect."""
    if lock_id < 0:
        return UNDETECTED_COLOR
    return logic.lock_color(lock_id)


def group_color(index: int) -> tuple[float, float, float]:
    return _GROUP_PALETTE[index % len(_GROUP_PALETTE)]


def group_id_from_mesh_name(name: str) -> str:
    """"Geo_HairBang" -> "hair_bang"; "" -> DEFAULT_GROUP. A mesh name shared by several pieces is a
    region of the groom (Helen's Geo_HairBang, Geo_HairBack), so it gives the group, not the lock name."""
    base = re.sub(r"^(geo|msh|mesh)_", "", (name or "").strip().split("/")[-1], flags=re.IGNORECASE)
    base = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", base)
    base = re.sub(r"[^0-9a-zA-Z]+", "_", base).strip("_").lower()
    return base or DEFAULT_GROUP


def unique_names(mesh_names: Sequence[str]) -> list[str]:
    """Per piece: its mesh name when no other piece has it (then it names the lock), else ""."""
    counts: dict[str, int] = {}
    for n in mesh_names:
        counts[n] = counts.get(n, 0) + 1
    return [n if n and counts[n] == 1 else "" for n in mesh_names]


def asset_from_scene(scene_name: str) -> str:
    """"char_Helen_grooming_v007.hiplc" -> "char_Helen"; a name without "_grooming" loses its _vNNN."""
    base = os.path.splitext(os.path.basename(scene_name or ""))[0]
    m = re.match(r"^(.*?)_grooming(?:$|[._])", base, flags=re.IGNORECASE)
    if m and m.group(1):
        return m.group(1)
    return re.sub(r"[._]v\d+$", "", base, flags=re.IGNORECASE) or "asset"


def preview_factor(expected_strands: float, fraction: float = config.PREVIEW_FRACTION,
                   max_strands: int = config.PREVIEW_MAX_STRANDS) -> float:
    """Density factor for "hair_preview": `fraction` of the strands, at most `max_strands` of them.

    Capped factors snap down to a step of PREVIEW_FACTOR_STEP (0.8^k), the same as the HDA's PREVIEW:
    the factor is part of every lock's cache key, and an exact cap / total moved with any density edit
    and recooked every lock."""
    f = max(0.0, min(1.0, float(fraction)))
    if expected_strands > 0 and expected_strands * f > max_strands:
        f = max_strands / float(expected_strands)
        if f > 0:
            step = config.PREVIEW_FACTOR_STEP
            f = step ** math.ceil(math.log(f) / math.log(step) - 1e-6)
    return f


def parse_isolate(text: str | None) -> list[int]:
    """Lock ids of the `isolate_ids` parm ("3 17 20"); empty = nothing isolated."""
    out = []
    for tok in (text or "").replace(",", " ").split():
        try:
            out.append(int(tok))
        except ValueError:
            continue
    return sorted(set(out))


def format_isolate(lock_ids: Iterable[int] | None) -> str:
    return " ".join(str(i) for i in sorted(set(int(i) for i in (lock_ids or ()))))


def lock_key(parts: Iterable[Any]) -> str:
    """Cache key of one lock's hair: a digest of everything its per-lock cook reads."""
    h = hashlib.blake2b(digest_size=16)
    for p in parts:
        h.update(p if isinstance(p, (bytes, bytearray, memoryview)) else repr(p).encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()


class LockCache:
    """Hair of each lock, cooked once per input state (`lock_key`), per MONO Grooming node and display
    mode. Pure Python: the values are whatever the adapter stores (frozen hou.Geometry in Houdini).

    Limited by memory, not by a count of states (the user, 2026-11-13: a count of 2 made the second undo
    of a row of strokes regrow its locks). Each entry has a size in bytes (`put(size=)`, else `sizer(value)`);
    per node the cache holds at most its limit (`set_limit`, the node's "Undo cache, GB") and drops the
    states used longest ago when a store goes over it. Never dropped, whatever the limit: the state in use,
    which is the key used last in each (node, lock, mode) slot and everything touched since the node's
    cook began (`begin`), so what `lock_keys` saw as cached is still there when `hair_cache` merges it.
    An undo past what the cache holds finds nothing and the lock is cooked again: slower, never wrong."""

    def __init__(self, sizer=None, limit: int | None = None) -> None:
        self._d: dict[tuple[int, int, str], dict[str, Any]] = {}
        self._meta: dict[tuple[int, int, str], dict[str, list]] = {}    # slot -> key -> [bytes, tick, generation]
        self._bytes: dict[int, int] = {}
        self._limit: dict[int, int] = {}
        self._gen: dict[int, int] = {}
        self._dropped: dict[int, int] = {}
        self._tick = 0
        self._sizer = sizer
        self._default = int(config.UNDO_CACHE_GB * 2 ** 30) if limit is None else int(limit)

    # ---- use ----
    def _touch(self, slot: tuple[int, int, str], key: str) -> None:
        self._tick += 1
        m = self._meta[slot][key]
        m[1], m[2] = self._tick, self._gen.get(slot[0], 0)
        d = self._d[slot]
        d[key] = d.pop(key)             # most recently used last

    def has(self, node_id: int, lock_id: int, mode: str, key: str) -> bool:
        """The state is held. Asking counts as using it: it is not dropped before this cook reads it."""
        slot = (node_id, lock_id, mode)
        if key not in self._d.get(slot, {}):
            return False
        self._touch(slot, key)
        return True

    def get(self, node_id: int, lock_id: int, mode: str, key: str) -> Any:
        slot = (node_id, lock_id, mode)
        d = self._d.get(slot)
        if d is None or key not in d:
            return None
        self._touch(slot, key)
        return d[key]

    def put(self, node_id: int, lock_id: int, mode: str, key: str, value: Any, size: int | None = None) -> None:
        slot = (node_id, lock_id, mode)
        self._forget(slot, key)
        if size is None:
            size = int(self._sizer(value)) if self._sizer is not None else 0
        self._d.setdefault(slot, {})[key] = value
        self._meta.setdefault(slot, {})[key] = [int(size), 0, 0]
        self._bytes[node_id] = self._bytes.get(node_id, 0) + int(size)
        self._touch(slot, key)
        self._trim(node_id)

    def put_derived(self, node_id: int, lock_id: int, mode: str, key: str, value: Any, size: int | None = None) -> None:
        """Store something made from a lock's cooked hair, not a cook of the lock: the display's coloured
        copy, a whole merge, output 1's capture. The same store as `put`, under another name so that what
        counts cooks (tests wrap `put`) counts hair grown by the loop and nothing else."""
        LockCache.put(self, node_id, lock_id, mode, key, value, size)

    def _forget(self, slot: tuple[int, int, str], key: str) -> None:
        d = self._d.get(slot)
        if d is None or key not in d:
            return
        del d[key]
        self._bytes[slot[0]] = self._bytes.get(slot[0], 0) - self._meta[slot].pop(key)[0]
        if not d:
            del self._d[slot]
            del self._meta[slot]

    # ---- the limit ----
    def begin(self, node_id: int) -> None:
        """A cook of the node's keys starts: what is touched from here on is in use until the next one."""
        self._gen[node_id] = self._gen.get(node_id, 0) + 1

    def set_limit(self, node_id: int, limit_bytes: float) -> None:
        self._limit[node_id] = max(0, int(limit_bytes))
        self._trim(node_id)

    def limit(self, node_id: int) -> int:
        return self._limit.get(node_id, self._default)

    def _in_use(self, slot: tuple[int, int, str], key: str) -> bool:
        return next(reversed(self._d[slot])) == key or self._meta[slot][key][2] == self._gen.get(slot[0], 0)

    TRIM_TO = 0.95      # once full, room is made down to this share of the limit: not a sort on every store
    # slots held APART from the limit: the display's deformed states have a limit of their own (the node's
    # "Deformed undo, GB", `keep_bytes`), so they never push a hair state out and no hair state pushes them
    APART = ("deformed:",)

    def apart_bytes(self, node_id: int) -> int:
        return sum(m[0] for slot, keys in self._meta.items()
                   if slot[0] == node_id and slot[2].startswith(self.APART) for m in keys.values())

    def _trim(self, node_id: int) -> None:
        limit = self.limit(node_id)
        used = self._bytes.get(node_id, 0) - self.apart_bytes(node_id)
        if used <= limit:
            return
        old = sorted((m[1], slot, key)
                     for slot, keys in self._meta.items() if slot[0] == node_id and not slot[2].startswith(self.APART)
                     for key, m in keys.items() if not self._in_use(slot, key))
        for _tick, slot, key in old:
            if used <= limit * self.TRIM_TO:
                break
            used -= self._meta[slot][key][0]
            self._forget(slot, key)
            self._dropped[node_id] = self._dropped.get(node_id, 0) + 1

    def usage(self, node_id: int) -> dict:
        """What the node's cache holds against its limit: `bytes` in all, of which `live_bytes` the state in
        use (never dropped) and `undo_bytes` the older states an undo or redo can return to (`undo_states` of
        them); `limit_bytes`; `dropped`: states dropped so far to stay inside the limit. The slots held apart
        (`APART`: the deformed display) are not in those: `deformed_bytes`, `deformed_states`."""
        live = undo = states = entries = apart = apart_n = 0
        for slot, keys in self._meta.items():
            if slot[0] != node_id:
                continue
            if slot[2].startswith(self.APART):
                apart += sum(m[0] for m in keys.values())
                apart_n += len(keys)
                continue
            for key, m in keys.items():
                entries += 1
                if self._in_use(slot, key):
                    live += m[0]
                else:
                    undo += m[0]
                    states += 1
        return {"bytes": live + undo, "live_bytes": live, "undo_bytes": undo, "undo_states": states,
                "entries": entries, "limit_bytes": self.limit(node_id), "dropped": self._dropped.get(node_id, 0),
                "deformed_bytes": apart, "deformed_states": apart_n}

    # ---- housekeeping ----
    def keep_only(self, node_id: int, lock_id: int, mode: str, keys) -> None:
        """Drop every state of the slot but `keys`: for what is made from another entry in a moment (the
        display's coloured copy of a lock's strands), which is not worth undo memory."""
        slot = (node_id, lock_id, mode)
        for key in [k for k in self._d.get(slot, {}) if k not in keys]:
            self._forget(slot, key)

    def drop(self, node_id: int, lock_id: int, mode: str) -> None:
        slot = (node_id, lock_id, mode)
        for key in list(self._d.get(slot, {})):
            self._forget(slot, key)

    def keep_bytes(self, node_id: int, lock_id: int, mode: str, max_bytes: float) -> int:
        """Drop the states of one slot used longest ago until the slot holds at most `max_bytes`; the state
        used last always stays. Returns how many went. For a slot whose states are large and made again
        without growing hair (the deformed display): it must not push the hair's own states out."""
        slot = (node_id, lock_id, mode)
        meta = self._meta.get(slot, {})
        total = sum(m[0] for m in meta.values())
        gone = 0
        for key in list(self._d.get(slot, {}))[:-1]:        # oldest first, never the last one used
            if total <= max_bytes:
                break
            total -= meta[key][0]
            self._forget(slot, key)
            gone += 1
        return gone

    def latest(self, node_id: int, lock_id: int, mode: str) -> Any:
        """The state of a slot used last (not counted as a use), None when the slot is empty."""
        d = self._d.get((node_id, lock_id, mode))
        return d[next(reversed(d))] if d else None

    def values(self, node_id: int, mode: str) -> list:
        """Everything held for a node under one mode, every lock and state."""
        return [v for slot, keys in self._d.items() if slot[0] == node_id and slot[2] == mode for v in keys.values()]

    def nodes(self) -> set[int]:
        return {k[0] for k in self._d}

    def drop_node(self, node_id: int) -> None:
        for slot in [k for k in self._d if k[0] == node_id]:
            self.drop(*slot)
        for table in (self._bytes, self._limit, self._gen, self._dropped):
            table.pop(node_id, None)

    def __len__(self) -> int:
        return sum(len(s) for s in self._d.values())


def _geo_bytes(value: Any) -> int:
    """Memory a cached geometry holds, bytes (its `memoryusage` intrinsic); 0 for anything else."""
    try:
        return int(value.intrinsicValue("memoryusage"))
    except Exception:
        return 0


def hair_cache() -> LockCache:
    """The session's one LockCache. Kept on `sys`, not in this module: reloading the adapter (or
    hou.session code) must not lose it while lock_keys still says a lock is cached."""
    cache = getattr(sys, _CACHE_ATTR, None)
    if cache is None or not hasattr(cache, "usage"):      # none yet, or one of a build before the memory limit
        cache = LockCache(sizer=_geo_bytes)
        setattr(sys, _CACHE_ATTR, cache)
    return cache


def undo_cache_usage(node) -> dict:
    """How much hair the node's cache holds against its limit (the node's "Undo cache, GB"), for the panel:
    `bytes`, `live_bytes` (what the node shows now: never dropped), `undo_bytes` / `undo_states` (older
    states an undo or redo returns to without a recook), `limit_bytes`, `dropped`, `gb` / `limit_gb`, and
    `capture_bytes` (the deforms' captures, one a lock, held apart from the limit)."""
    cache = hair_cache()
    use = cache.usage(node.sessionId())
    use["gb"] = use["bytes"] / 2 ** 30
    use["limit_gb"] = use["limit_bytes"] / 2 ** 30
    use["deformed_limit_bytes"] = undo_deform_limit(node)
    # output 1's Point Deform captures (one a lock, only once the deformed output was read): not hair, not
    # in the limit's count
    use["capture_bytes"] = sum(_geo_bytes(g) for mode in ("hair", "hair_preview", "drag")
                               for g in cache.values(node.sessionId(), capture_slot(mode)))
    return use


def undo_cache_limit(top) -> int:
    """The node's undo cache limit in bytes (its `undo_cache_gb`; a node built before the parm: the default)."""
    parm = top.parm(config.UNDO_CACHE_PARM)
    gb = float(parm.eval()) if parm is not None else config.UNDO_CACHE_GB
    return int(max(gb, 0.0) * 2 ** 30)


def undo_deform_limit(top) -> int:
    """The limit of the display's deformed states in bytes (the node's `undo_deform_gb`, "Deformed undo, GB";
    a node built before the parm: the default)."""
    parm = top.parm(config.UNDO_DEFORM_PARM)
    gb = float(parm.eval()) if parm is not None else config.UNDO_DEFORM_GB
    return int(max(gb, 0.0) * 2 ** 30)


def classify_inputs(cands: Sequence[tuple[str, int]]) -> tuple[int, int] | None:
    """(scalp index, hair index) among selected SOPs given as (node name, primitive count), or None
    when it cannot tell. Names decide first ("scalp", "skin", "head" / "hair", "lock", "driver"), then a
    hair mesh with at least twice the primitives of the other."""
    if len(cands) != 2:
        return None
    scalp_words = ("scalp", "skin", "head")
    hair_words = ("hair", "lock", "driver", "groom")

    def kind(name: str) -> str | None:
        low = name.lower()
        s = any(w in low for w in scalp_words)
        h = any(w in low for w in hair_words)
        return "scalp" if s and not h else "hair" if h and not s else None

    k0, k1 = kind(cands[0][0]), kind(cands[1][0])
    if {k0, k1} == {"scalp", "hair"}:
        return (0, 1) if k0 == "scalp" else (1, 0)
    if k0 == "scalp" or k1 == "hair":
        return 0, 1
    if k1 == "scalp" or k0 == "hair":
        return 1, 0
    n0, n1 = cands[0][1], cands[1][1]
    if n1 >= 2 * max(n0, 1):
        return 0, 1
    if n0 >= 2 * max(n1, 1):
        return 1, 0
    return None


def assign_pieces(pieces: Sequence[tuple[str, tuple[float, float, float], float]],
                  locks: Sequence[model.Lock]) -> list[int]:
    """Lock id per cooked spine, from what Detect stored: (unique mesh name or "", root, length).

    Same name first, else the nearest stored root within 5 % of the lock length (Detect stores the
    root it measured, so an unchanged mesh matches exactly). Each lock is used once; a piece the JSON
    does not know (mesh changed since Detect) gets -1 and grows no hair until Detect runs again."""
    out = [-1] * len(pieces)
    free = {lk.id: lk for lk in locks}
    by_name = {lk.name: lk for lk in locks if lk.name}
    for i, (name, _root, _length) in enumerate(pieces):
        lk = by_name.get(name) if name else None
        if lk is not None and lk.id in free:
            out[i] = lk.id
            del free[lk.id]
    cands = []
    for i, (_name, root, length) in enumerate(pieces):
        if out[i] >= 0:
            continue
        for lk in free.values():
            d = math.dist(root, lk.root)
            if d <= 0.05 * max(length, lk.length, 1e-6):
                cands.append((d, i, lk.id))
    for _d, i, lid in sorted(cands):
        if out[i] < 0 and lid in free:
            out[i] = lid
            del free[lid]
    return out


def apply_detect(data: model.GroomData, pieces: Sequence[MeshPiece], piece_groups: Sequence[str],
                 report: DetectReport, asset: str = "") -> model.GroomData:
    """New GroomData after Detect: matched locks keep id and settings and take the new root / length,
    new pieces become locks (name from the mesh, else `logic.lock_name` of the group), locks with no
    piece move to `orphans` with their settings. Regions go stale whenever a lock is added, removed or
    moved. `piece_groups[i]` is the group of `pieces[i]`; `report.matches` refer to `MeshPiece.index`.
    The first Detect (no locks yet) marks nothing "new": every lock would be, and a status on every row
    says nothing."""
    out = model.GroomData.from_json(data.to_json())
    if asset and not out.asset:
        out.asset = asset
    by_index = {p.index: (p, g) for p, g in zip(pieces, piece_groups)}
    old = {lk.id: lk for lk in out.locks}
    first = not old and not out.orphans
    taken = [lk.name for lk in out.locks] + [o.name for o in out.orphans]
    locks: list[model.Lock] = []
    stale = False
    for m in report.matches:
        piece, group = by_index[m.piece]
        # stored unrounded: match_locks' "unchanged" rule compares within 1e-5 x length, and rounding to
        # 6 decimals would already exceed that for a 2 cm lock in a metre scene
        root = tuple(float(c) for c in piece.root)
        length = float(piece.length)
        lk = old.get(m.lock_id)
        if lk is not None and m.status != "new":
            if math.dist(lk.root, root) > 1e-5 or abs(lk.length - length) > 1e-5:
                stale = True
            lk.root, lk.length, lk.match = root, length, m.status  # type: ignore[assignment]
            lk.direction = tuple(round(c, 6) for c in piece.direction)  # type: ignore[assignment]
            locks.append(lk)
            continue
        name = piece.name or logic.lock_name(group, taken)
        taken.append(name)
        locks.append(model.Lock(id=m.lock_id, name=name, group=group, root=root,  # type: ignore[arg-type]
                                length=length, match="ok" if first else "new",
                                direction=tuple(round(c, 6) for c in piece.direction)))  # type: ignore[arg-type]
        stale = True
    for lid in report.orphaned:
        lk = old[lid]
        if lk.drawn:          # a lock drawn on the skin has no mesh piece to miss: Detect leaves it alone
            continue
        # what a missing lock keeps: its settings, flags and control-point edit (v0.2b)
        out.orphans.append(model.Orphan.from_lock(lk))
        stale = True
    # locks drawn on the skin (v0.2b) are not the hair mesh's: kept as they are, never missing, never "new"
    taken_ids = {lk.id for lk in locks}
    locks.extend(lk for lk in old.values() if lk.drawn and lk.id not in taken_ids)
    out.locks = sorted(locks, key=lambda lk: lk.id)
    have = {g.id for g in out.groups}
    for lk in out.locks:
        if lk.group not in have:
            out.groups.append(model.Group(id=lk.group, name=lk.group, color=group_color(len(out.groups))))
            have.add(lk.group)
    if stale:
        n_new = sum(m.status == "new" for m in report.matches)
        parts = ([f"{n_new} new"] if n_new else []) + ([f"{len(report.orphaned)} missing"] if report.orphaned else [])
        out.mark_stale("Detect locks: " + (", ".join(parts) if parts else "roots or lengths moved"))
    if not out.orphans:
        # "new" asks for a decision only while a missing lock's settings could go to it: with none
        # missing, every lock Detect found is simply the groom
        for lk in out.locks:
            if lk.match == "new":
                lk.match = "ok"
    out.note_ids()
    return out


def mesh_locks(data: model.GroomData) -> list[model.Lock]:
    """Pure: the locks of the hair mesh (Detect matches them to its pieces); locks drawn on the skin left out."""
    return [lk for lk in data.locks if not lk.drawn]


def edit_cp_values(data: model.GroomData, lock_ids: Sequence[int]) -> list[list[float]]:
    """Pure: per spine prim (lock id or -1) the stored control points as the flat array `config.ATTR_EDIT_CP`
    (`logic.flat_handles`), [] for a lock not edited (or drawn, or unknown): what cook_assign writes. The array is
    a prim attribute, so it is in that lock's cache key only."""
    out = []
    for lid in lock_ids:
        lk = data.lock(lid) if lid >= 0 else None
        out.append(logic.flat_handles(lk.spine) if lk is not None and lk.edited else [])
    return out


def lock_display_attribs(data: model.GroomData, lock_ids: Sequence[int]) -> dict[str, list]:
    """Per spine prim (lock id or -1): name, group, colours, visibility and every resolved setting.
    What the in-network "assign" Python SOP writes, kept here so it is testable."""
    out: dict[str, list] = {k: [] for k in ("name", "group", "lock_cd", "group_cd", "visible",
                                           "lock_match", "root_flip", "excluded", "row_display",
                                           *model.SETTING_KEYS)}
    for lid in lock_ids:
        lk = data.lock(lid) if lid >= 0 else None
        g = data.group(lk.group) if lk is not None else None
        settings = data.resolve(lid) if lk is not None else dict(model.BUILTIN_DEFAULTS)
        out["name"].append(lk.name if lk else "")
        out["group"].append(lk.group if lk else "")
        out["lock_cd"].append(lock_color(lid))
        out["group_cd"].append(tuple(g.color) if g else UNDETECTED_COLOR)
        out["visible"].append(int(lk is not None and lk.shown(g)))
        out["lock_match"].append(lk.match if lk else "undetected")
        out["root_flip"].append(int(lk is not None and lk.root_flip))
        out["excluded"].append(int(lk is not None and lk.excluded))
        # the row's own Display (lock, else its group), as an index of DISPLAY_MODES; -1 = the node's
        own = (lk.display if lk is not None else None) or (g.display if g is not None else None)
        out["row_display"].append(config.DISPLAY_MODES.index(own) if own in config.DISPLAY_MODES else -1)
        for k in model.SETTING_KEYS:
            out[k].append(float(settings[k]))
    return out


def publish_record(asset: str, version: str, usd: str, scene: str, data: model.GroomData,
                   strands: int, node_path: str, houdini: str = "", masks: dict | None = None) -> dict[str, Any]:
    """What publish.json holds next to grooming_data.json. `masks`: where the painted mask layers are
    (grooming_masks.publish_masks: file, layer ids, points), {} when the groom has none."""
    return {
        "masks": dict(masks or {}),
        "asset": asset, "version": version, "department": "grooming", "usd": usd, "scene": scene,
        "node": node_path, "houdini": houdini, "user": getpass.getuser(),
        "date": _dt.datetime.now().isoformat(timespec="seconds"),
        "locks": len(data.locks), "groups": len(data.groups), "strands": strands,
        "regions_stale": data.regions_stale, "schema": data.schema,
        # v0.2b: which locks carry a control-point edit and which were drawn (grooming_data.json holds them)
        "spines": spine_record(data),
    }


# ---------------------------------------------------------------------------
# hou helpers
# ---------------------------------------------------------------------------

def _require_hou() -> None:
    if hou is None:
        raise RuntimeError("MONO Grooming adapter needs Houdini (hou)")


def _node_type():
    return hou.nodeType(hou.sopNodeTypeCategory(), config.HDA_TYPE)


def _inner(node, name: str):
    inner = node.node(name)
    if inner is None:
        raise RuntimeError(f"{node.path()} has no {name}: not a {config.HDA_LABEL} node of this version")
    return inner


def _cooked(node, name: str):
    inner = _inner(node, name)
    inner.cook()
    return inner.geometry()


def _status(text: str, error: bool = False) -> None:
    if hou is not None and hou.isUIAvailable():
        sev = hou.severityType.Error if error else hou.severityType.Message
        hou.ui.setStatusMessage(text, severity=sev)
    else:
        print(("ERROR: " if error else "") + text)


def _place_new(node) -> None:
    node.moveToGoodPosition(move_inputs=False, move_outputs=False, move_unconnected=False)


def _prim_values(geo, name: str, kind: str) -> list:
    if geo.findPrimAttrib(name) is None:
        return []
    if kind == "s":
        return list(geo.primStringAttribValues(name))
    if kind == "i":
        return list(geo.primIntAttribValues(name))
    if kind == "f":
        return list(geo.primFloatAttribValues(name))
    size = geo.findPrimAttrib(name).size()
    flat = geo.primFloatAttribValues(name)
    return [tuple(flat[i:i + size]) for i in range(0, len(flat), size)]


# ---------------------------------------------------------------------------
# Adapter API
# ---------------------------------------------------------------------------

def find_nodes() -> list:
    """MONO Grooming nodes in the scene, selected ones first."""
    _require_hou()
    nt = _node_type()
    if nt is None:
        return []
    nodes = list(nt.instances())
    return sorted(nodes, key=lambda n: (not n.isSelected(), n.path()))


def create_node(parent=None):
    """New node wired to a selected scalp + hair mesh when it can tell which is which, else unwired."""
    _require_hou()
    if _node_type() is None:  # checked first: nothing is created when the HDA is missing
        raise RuntimeError(f"{config.HDA_LABEL} ({config.HDA_TYPE}) is not installed: otls/mono_grooming.hdalc "
                           "is missing from the MonoFX Suite folder")
    sel = [n for n in hou.selectedNodes() if n.type().category() == hou.sopNodeTypeCategory()]
    if parent is None:
        parent = sel[0].parent() if sel else None
    with hou.undos.group(UNDO_PREFIX + "Create"):
        if parent is None:
            parent = hou.node("/obj").createNode("geo", "grooming")
            _place_new(parent)
        node = parent.createNode(config.HDA_TYPE, "mono_grooming")
        same = [n for n in sel if n.parent() == parent]
        if len(same) == 2:
            counts = []
            for n in same:
                try:
                    counts.append((n.name(), len(n.geometry().iterPrims())))
                except hou.Error:
                    counts.append((n.name(), 0))
            pick = classify_inputs(counts)
            if pick is not None:
                node.setInput(0, same[pick[0]])
                node.setInput(1, same[pick[1]])
        _place_new(node)
        node.setDisplayFlag(True)
        node.setRenderFlag(True)
        node.setSelected(True, clear_all_selected=True)
    return node


def read_data(node) -> model.GroomData:
    return model.GroomData.from_json(node.evalParm(config.DATA_PARM))


def write_data(node, data: model.GroomData, label: str) -> None:
    """Store `groom_data`; one undo step named `label`."""
    with hou.undos.group(label):
        node.parm(config.DATA_PARM).set(data.to_json())


def undo(node, redo: bool = False) -> str:
    """Houdini's undo (or redo) of the last step, from the panel: with the panel focused, Ctrl+Z never
    reaches Houdini's hotkeys. Returns the step's label, "" when there was none."""
    labels = hou.undos.redoLabels() if redo else hou.undos.undoLabels()
    if not labels:
        return ""
    if redo:
        hou.undos.performRedo()
    else:
        hou.undos.performUndo()
    return labels[0]


def write_data_live(node, data: model.GroomData) -> None:
    """Store `groom_data` with no undo step: the ticks of a slider drag. The drag's release writes the
    final value with write_data, after putting the value from before the drag back, so one undo returns
    to where the drag started."""
    with hou.undos.disabler():
        node.parm(config.DATA_PARM).set(data.to_json())


def lock_infos(node) -> list[LockInfo]:
    """From the cooked spines: id, name, group, root, length, width, thick, twist, strands, region area.
    Widths and thicknesses are measured (SPINES_LOCKS); root and length are the spine's after the edit (v0.2b:
    an edited lock's length is the edited one), and a drawn lock is read from SPINES (it has no measured spine)."""
    geo = _cooked(node, NODE_SPINES_LOCKS)
    after = _cooked(node, NODE_SPINES)
    scalp = _cooked(node, NODE_SCALP_REGIONS)
    area: dict[int, float] = {}   # a shared prim counts 1/share for each of its owners
    floating: dict[int, float] = {}   # skin under floating mesh, weighted by the falloff (region_join far_w)
    if scalp.findPrimAttrib(ATTR_LOCK_OWNERS) and scalp.findPrimAttrib("area_cm2"):
        # bulk reads: one attribValue call per scalp prim (24k on Helen) cost 2 s on every panel refresh
        owners = scalp.primIntListAttribValues(ATTR_LOCK_OWNERS)
        areas = scalp.primFloatAttribValues("area_cm2")
        dists = scalp.primFloatListAttribValues(ATTR_OWNER_DIST) if scalp.findPrimAttrib(ATTR_OWNER_DIST) else None
        unit = float(node.evalParm("unit_cm"))
        far = float(node.evalParm("root_far_cm")) if node.parm("root_far_cm") is not None else config.ROOT_FAR_CM
        for k, (own, a) in enumerate(zip(owners, areas)):
            for j, lid in enumerate(own):
                area[lid] = area.get(lid, 0.0) + a / len(own)
                if dists is not None and j < len(dists[k]) and dists[k][j] >= 0 and far > 0:
                    w = logic.falloff(dists[k][j] * unit, far, config.ROOT_FAR_SOFT)
                    if w > 0:
                        floating[lid] = floating.get(lid, 0.0) + w * a / len(own)
    infos = []
    rows: dict[int, dict] = {}
    # v0.2b: the root and length after the edit, and the drawn locks (in SPINES only)
    edited_at: dict[int, tuple] = {}
    drawn_prims = []
    if after.findPrimAttrib(config.ATTR_EDITED) is not None or after.findPrimAttrib(ATTR_DRAWN) is not None:
        for prim in after.iterPrims():
            lid = prim.intAttribValue(config.ATTR_LOCK_ID)
            if lid < 0:
                continue
            if after.findPrimAttrib(ATTR_DRAWN) is not None and prim.intAttribValue(ATTR_DRAWN):
                drawn_prims.append(prim)
            elif after.findPrimAttrib(config.ATTR_EDITED) is not None and prim.intAttribValue(config.ATTR_EDITED):
                edited_at[lid] = (tuple(prim.attribValue("root")), prim.floatAttribValue("length"))
    for prim in list(geo.iterPrims()) + drawn_prims:
        lid = prim.intAttribValue(config.ATTR_LOCK_ID)
        if lid < 0:
            continue
        pts = prim.points()
        widths = [p.floatAttribValue(config.ATTR_LOCK_WIDTH) for p in pts]
        thicks = [p.floatAttribValue(config.ATTR_LOCK_THICK) for p in pts]
        a = area.get(lid, 0.0)
        # the widest band anywhere: same rule as the HDA's region_frame
        section = logic.section_cm2(max(widths, default=0.0), max(thicks, default=0.0), node.evalParm("unit_cm"))
        strands = logic.lock_strands(prim.floatAttribValue("density"), a, section)
        root = tuple(prim.attribValue("root"))
        length = prim.floatAttribValue("length")
        if lid in edited_at:
            root, length = edited_at[lid]
        # region_frame's footprint: REGION_FOOTPRINT x the widest band of the lock's first tenth
        rows[lid] = {"strands": strands, "root": root,
                     "foot": config.REGION_FOOTPRINT * max(widths[:max(1, len(widths) // 10) + 1], default=0.0)}
        infos.append(LockInfo(
            id=lid, name=prim.stringAttribValue(config.ATTR_NAME), group=prim.stringAttribValue(config.ATTR_GROUP),
            root=root, length=length,  # type: ignore[arg-type]
            width=sum(widths) / max(len(widths), 1), thick=sum(thicks) / max(len(thicks), 1),
            twist=pts[-1].floatAttribValue(config.ATTR_LOCK_TWIST) if pts else 0.0,
            strands=int(round(strands)), region_area_cm2=a, floating_cm2=floating.get(lid, 0.0),
            auto_strands=int(round(strands)),
        ))
    # density layers (v0.2a): what the network grows under them. Its automatic roots are kept by the layers'
    # keep where they end up (an estimate of that share, `lock_layer_counts`), and the layers scatter their
    # own roots on its skin (the exact count the network is given)
    cache, sid = hair_cache(), node.sessionId()

    def auto_roots(lock_id):       # the lock's automatic roots as the loop last laid them out, full density
        return cache.latest(sid, lock_id, AUTO_MODE + "hair")

    for lid, (keep, add) in grooming_masks.lock_layer_counts(node, scalp, rows, auto_roots).items():
        for k, info in enumerate(infos):
            if info.id == lid:
                n = int(round(rows[lid]["strands"] * keep + add))
                infos[k] = replace(info, strands=n, layer_strands=int(round(add)), keep_share=float(keep),
                                   mask_share=n / max(rows[lid]["strands"], 1e-9), layered=True)
    return sorted(infos, key=lambda i: i.id)


def _pieces(node) -> tuple[list[MeshPiece], list[str]]:
    geo = _cooked(node, NODE_SPINES_RAW)
    mesh_names = _prim_values(geo, "mesh_name", "s") or [""] * len(geo.iterPrims())
    names = unique_names(mesh_names)
    roots = _prim_values(geo, "root", "v")
    lengths = _prim_values(geo, "length", "f")
    dirs = _prim_values(geo, "direction", "v")
    idx = _prim_values(geo, "piece", "i")
    pieces = [MeshPiece(index=idx[i], name=names[i], root=roots[i], length=lengths[i], direction=dirs[i])
              for i in range(len(idx))]
    groups = [group_id_from_mesh_name(mesh_names[i]) if mesh_names[i] and not names[i] else DEFAULT_GROUP
              for i in range(len(idx))]
    return pieces, groups


def detect(node) -> DetectReport:
    """Detect locks from the hair mesh, match ids against the JSON (logic.match_locks), write the JSON."""
    pieces, groups = _pieces(node)
    data = read_data(node)
    # only the hair mesh's locks are matched to its pieces: a drawn lock has none (v0.2b)
    report = logic.match_locks(pieces, mesh_locks(data), data.next_lock_id())
    asset = asset_from_scene(hou.hipFile.basename())
    new = apply_detect(data, pieces, groups, report, asset=asset)
    first_split = node.parm(PARM_REGIONS) is not None and node.parm(PARM_REGIONS).evalAsGeometry() is None
    with hou.undos.group(UNDO_PREFIX + "Detect locks"):
        write_data(node, new, UNDO_PREFIX + "Detect locks")
        if first_split and new.locks:
            # no split to keep yet: "regions out of date" right after the first Detect only asked for a
            # click every artist had to learn (review t48 P2-6); later Detects never re-split silently
            split_regions(node)
    report.floating = floating_roots(node)
    c = report.counts
    if not data.locks and not data.orphans:
        _status(f"{config.HDA_LABEL}: found {len(pieces)} locks" + (", regions split" if first_split else ""))
    else:
        _status(f"{config.HDA_LABEL}: {len(pieces)} locks - ok {c['ok']}, to check {c['unsure']}, "
                f"new {c['new']}, missing {c['orphaned']}"
                + (" - " + logic.floating_text(report.floating) if report.floating else ""))
    return report


def frame_locks(node, lock_ids: Sequence[int] | None) -> None:
    """Frame these locks (their spines, in world space) in the Scene Viewer, None: every lock. No undo."""
    viewer = _scene_viewer()
    if viewer is None:
        return
    geo = _cooked(node, NODE_SPINES)
    want = None if lock_ids is None else {int(i) for i in lock_ids}
    box = None   # an empty hou.BoundingBox() already holds the origin: start from the first lock's
    lids = geo.primIntAttribValues(config.ATTR_LOCK_ID)
    for prim, lid in zip(geo.iterPrims(), lids):
        if want is None or lid in want:
            if box is None:
                box = hou.BoundingBox(prim.boundingBox())
            else:
                box.enlargeToContain(prim.boundingBox())
    if box is None:
        return
    xf = node.parent().worldTransform() if hasattr(node.parent(), "worldTransform") else None
    if xf is not None:
        corners = [hou.Vector3(x, y, z) * xf for x in (box.minvec()[0], box.maxvec()[0])
                   for y in (box.minvec()[1], box.maxvec()[1]) for z in (box.minvec()[2], box.maxvec()[2])]
        box = hou.BoundingBox(*corners[0], *corners[0])
        for c in corners[1:]:
            box.enlargeToContain(c)
    viewer.curViewport().frameBoundingBox(box)


def preflight(node) -> dict:
    """What can make the groom wrong without an error (review t48 P1-1 / P1-2): mesh pieces Detect has not
    matched to a lock (they grow nothing and are not published), and inputs that break the units: a scalp
    whose size in cm (unit_cm) is not a head's, a scalp without uv, an object transformed or scaled.
    {"undetected": int, "warnings": [str]}."""
    out: dict = {"undetected": 0, "warnings": []}
    assign = node.node("assign_locks")
    if assign is not None:
        try:
            assign.cook()
            ids = assign.geometry().primIntAttribValues(config.ATTR_LOCK_ID)
            out["undetected"] = sum(1 for i in ids if i < 0)
        except hou.Error:
            pass
    scalp = node.node("IN_SCALP")
    try:
        g = scalp.geometry() if scalp is not None else None
    except hou.Error:
        g = None
    if g is not None and len(g.iterPrims()):
        unit = float(node.evalParm("unit_cm")) if node.parm("unit_cm") is not None else 100.0
        size_cm = max(g.boundingBox().sizevec()) * unit
        lo, hi = config.SCALP_SIZE_CM
        if not lo <= size_cm <= hi:
            out["warnings"].append(f"the scalp measures {size_cm:,.3g} cm across (a head is {lo}-{hi} cm):"
                                   f" check Units (cm per scene unit, now {unit:g})")
        if g.findVertexAttrib("uv") is None and g.findPointAttrib("uv") is None:
            out["warnings"].append("the scalp has no uv")
    obj = node.parent()
    try:
        xf = obj.worldTransform() if hasattr(obj, "worldTransform") else None
    except hou.Error:
        xf = None
    if xf is not None and not xf.isAlmostEqual(hou.hmath.identityTransform()):
        out["warnings"].append(f"{obj.name()} is moved or scaled: the groom is made in its own space, so"
                               " density and widths follow its scale")
    problem = deform_problem(node)   # output 1 deforms by itself: a refused anim would cache the rest groom
    if problem:
        out["warnings"].append(problem)
    return out


def floating_roots(node) -> list[tuple[str, float]]:
    """(name, cm) of each lock whose mesh root edge lies over config.ROOT_GAP_CM off the skin (`root_gap`
    on the spines, the root end the user chose)."""
    geo = _cooked(node, NODE_SPINES_LOCKS)
    if geo.findPrimAttrib("root_gap") is None:
        return []
    unit = node.evalParm("unit_cm")
    names = _prim_values(geo, config.ATTR_NAME, "s")
    gaps = _prim_values(geo, "root_gap", "f")
    ids = _prim_values(geo, config.ATTR_LOCK_ID, "i")
    return [(n, g * unit) for n, g, i in zip(names, gaps, ids) if i >= 0 and g * unit > config.ROOT_GAP_CM]


def _roots_on_skin(roots: dict[int, tuple[float, float, float]],
                   centroids: list[tuple[float, float, float]]) -> dict[int, tuple[float, float, float]]:
    """Each root moved to the nearest scalp prim centre: a cap whose root end lies on another cap sits
    ~1 cm off the skin (Helen hair_base_08/11/17), so its footprint (0.7 cm) covered no skin, the cap
    beneath took it, and the first quarter of the cap grew no hair."""
    if not centroids:
        return roots
    import numpy as np
    c = np.asarray(centroids, dtype=float)
    out = {}
    for lid, r in roots.items():
        i = int(np.argmin(((c - np.asarray(r, dtype=float)) ** 2).sum(axis=1)))
        out[lid] = tuple(float(v) for v in c[i])
    return out


def split_regions(node) -> None:
    """Recompute and freeze the growth regions, clear `regions_stale`. One undo step.

    Per prim of the subdivided scalp (`SCALP_FINE`), at its centroid: the locks whose footprint covers
    it (logic.region_owners: radius = REGION_FOOTPRINT x the lock's measured root width), else the
    lock whose hair mesh lies nearest over it (`region_mesh`, layers within REGION_MESH_SHARE_CM
    share), else the nearest lock; stacked locks share. Frozen as one point per prim with `lock_owners`
    (int array) and the detail `region_rule` (config.REGION_RULE)."""
    data = read_data(node)
    centroids, owners, mesh_near, roots = _split(node, data)
    frozen = hou.Geometry()
    frozen.addAttrib(hou.attribType.Global, ATTR_REGION_RULE, 0)
    frozen.setGlobalAttribValue(ATTR_REGION_RULE, config.REGION_RULE)
    # whorls: locks whose roots converge on one spot get extra roots packed there (build_hda root_spread)
    uc = max(float(node.evalParm("unit_cm")), 1e-6)
    whorl = logic.whorls(roots, config.WHORL_RADIUS_CM / uc, config.WHORL_MIN_LOCKS)
    frozen.addArrayAttrib(hou.attribType.Global, ATTR_WHORL_LOCKS, hou.attribData.Int)
    frozen.addArrayAttrib(hou.attribType.Global, ATTR_WHORL_CENTRES, hou.attribData.Float)
    frozen.setGlobalAttribValue(ATTR_WHORL_LOCKS, sorted(whorl))
    frozen.setGlobalAttribValue(ATTR_WHORL_CENTRES, [v for lid in sorted(whorl) for v in whorl[lid]])
    frozen.createPoints(centroids)
    frozen.addArrayAttrib(hou.attribType.Point, ATTR_LOCK_OWNERS, hou.attribData.Int)
    frozen.addAttrib(hou.attribType.Point, config.ATTR_LOCK_OWNER, config.NO_OWNER)
    # how high each owner's mesh lies over the prim (scene units, -1 unknown): the panel's "thin under
    # floating mesh" reads it without cooking region_mesh on every edit
    frozen.addArrayAttrib(hou.attribType.Point, ATTR_OWNER_DIST, hou.attribData.Float)
    for pt, own, nm in zip(frozen.points(), owners, mesh_near):
        pt.setAttribValue(ATTR_LOCK_OWNERS, own)
        pt.setAttribValue(config.ATTR_LOCK_OWNER, own[0] if own else config.NO_OWNER)
        dist_of = {lid: d for d, lid in nm}
        pt.setAttribValue(ATTR_OWNER_DIST, [float(dist_of.get(lid, -1.0)) for lid in own])
    data.clear_stale()
    with hou.undos.group(UNDO_PREFIX + "Update regions"):
        node.parm(PARM_REGIONS).set(frozen)
        node.parm(config.DATA_PARM).set(data.to_json())
    grown = {lid for own in owners for lid in own}
    shared = sum(1 for own in owners if len(own) > 1)
    _status(f"{config.HDA_LABEL}: regions updated for {len(grown)}/{len(roots)} locks, {len(centroids)} skin"
            f" prims, {shared} shared")




def _prim_centres(scalp, has_group: bool):
    """Per prim of a polygon geometry its centre (the mean of its points, summed in vertex order as the per-prim
    loop it replaces did) and the `group` of its first point, read in bulk (the loop made ~250 k hou calls on Helen's
    fine scalp: 3.6 s of every Update regions and of a drawn lock's delete)."""
    import numpy as np
    n = scalp.intrinsicValue("primitivecount")
    if not n:
        return [], []
    P = np.frombuffer(scalp.pointFloatAttribValuesAsString("P"), np.float32).reshape(-1, 3).astype(np.float64)
    vprim, vpoint = grooming_masks._vertex_tables(scalp)
    order = np.argsort(vprim, kind="stable")
    vprim, vpoint = vprim[order], vpoint[order]
    counts = np.bincount(vprim, minlength=n)
    starts = np.concatenate([[0], np.cumsum(counts)[:-1]])
    pts = P[vpoint]
    # sums per prim strictly in vertex order, one vertex slot at a time: the same floats as the old loop, bit for bit
    # (np.add.reduceat did not add in order: 4e-19 off, which may flip a footprint test)
    sums = np.zeros((n, 3))
    for k in range(int(counts.max()) if n else 0):
        has_k = counts > k
        sums[has_k] = sums[has_k] + pts[starts[has_k] + k]
    cen = sums / np.maximum(counts, 1)[:, None]
    centroids = [tuple(float(c) for c in row) for row in cen]
    if has_group:
        names = scalp.pointStringAttribValues(config.ATTR_GROUP)
        groups = [names[vpoint[st]] if c else "" for st, c in zip(starts, counts)]
    else:
        groups = [""] * n
    return centroids, groups


def _split(node, data, only=None):
    """The split rule of Update regions on the spines as cooked (locks not in `data` left out): (prim centres,
    owners per prim, each prim's mesh distances, the locks' roots on the skin). `only`: the prim indices to give
    owners to (v0.2b: a deleted drawn lock's skin back to its neighbours); the whole scalp still places the roots."""
    measured = _cooked(node, NODE_SPINES_LOCKS)
    spines = _cooked(node, NODE_SPINES)        # v0.2b: after the edit (a moved root) and with the drawn locks
    scalp = _cooked(node, NODE_SCALP_FINE)
    roots: dict[int, tuple[float, float, float]] = {}
    radii: dict[int, float] = {}
    excluded = {lk.id for lk in data.locks if lk.excluded}   # grows no hair: takes no scalp from another lock
    for prim in measured.iterPrims():
        lid = prim.intAttribValue(config.ATTR_LOCK_ID)
        if lid < 0 or lid in excluded or data.lock(lid) is None:
            continue
        # The root band of a lock is often tapered to almost nothing, so the footprint takes the widest
        # section near the root (first 10 % of the spine). Not further: Helen's hair_base caps widen
        # to 20 cm a little up, and a 10 cm footprint grew a cone of strands converging on the lock.
        pts0 = prim.points()
        head = pts0[:max(2, len(pts0) // 10)]
        width = max((p.floatAttribValue(config.ATTR_LOCK_WIDTH) for p in head), default=0.0)
        radii[lid] = config.REGION_FOOTPRINT * width
    unit_cm = max(float(node.evalParm("unit_cm")), 1e-6)
    for prim in spines.iterPrims():
        lid = prim.intAttribValue(config.ATTR_LOCK_ID)
        if lid < 0 or lid in excluded:
            continue
        lk = data.lock(lid)
        if lk is None:                    # not in the data (a drawn lock being deleted): takes no skin
            continue
        if lk.drawn:   # its set width (logic.drawn_footprint_cm, the same footprint rule)
            radii[lid] = logic.drawn_footprint_cm(lk.width_cm) / unit_cm
        if lid in radii:
            roots[lid] = tuple(prim.attribValue("root"))  # type: ignore[assignment]
    has_group = scalp.findPointAttrib(config.ATTR_GROUP) is not None
    centroids, prim_groups = _prim_centres(scalp, has_group)
    roots = _roots_on_skin(roots, centroids)
    if has_group:
        groups_of = {lk.id: lk.group for lk in data.locks}
    else:  # scalp without regions: every prim may grow any lock
        groups_of = {lid: "" for lid in roots}
    near = _cooked(node, NODE_REGION_MESH)
    # in bulk: one hou call per prim (24 k on Helen) cost most of a drawn lock's delete (t82: 5 s in the panel)
    mesh_near = [list(zip(d, k)) for d, k in zip(near.primFloatListAttribValues("mesh_dist"),
                                                  near.primIntListAttribValues("mesh_lock"))]
    share = config.REGION_MESH_SHARE_CM / max(float(node.evalParm("unit_cm")), 1e-6)
    if only is not None:
        idx = list(only)
        owners = logic.region_owners([centroids[i] for i in idx], roots, radii, groups_of,
                                     [prim_groups[i] for i in idx], [mesh_near[i] for i in idx], share,
                                     every_lock=False)
        return [centroids[i] for i in idx], owners, [mesh_near[i] for i in idx], roots
    owners = logic.region_owners(centroids, roots, radii, groups_of, prim_groups, mesh_near, share)
    return centroids, owners, mesh_near, roots


def set_display(node, mode: str, color_by: str, preview: float = config.PREVIEW_FRACTION) -> None:
    """`mode` in mesh/guide/hair_preview/hair; `color_by` in lock/group; `preview` = hair_preview fraction."""
    if mode not in config.DISPLAY_MODES or color_by not in config.COLOR_BY:
        raise ValueError(f"display {mode!r} / colour by {color_by!r}")
    with hou.undos.group(UNDO_PREFIX + "Display"):
        node.parm(PARM_DISPLAY).set(config.DISPLAY_MODES.index(mode))
        node.parm(PARM_COLOR_BY).set(config.COLOR_BY.index(color_by))
        node.parm(PARM_PREVIEW).set(float(preview))


def set_isolate(node, lock_ids: Sequence[int] | None) -> None:
    """Show only `lock_ids` (None or empty: back to every shown lock). A temporary view: no undo step,
    cleared when the scene is loaded again (the HDA's OnLoaded), the eyes underneath stay as they are.
    Only those locks cook; isolated locks are drawn even when their eye is off."""
    with hou.undos.disabler():
        node.parm(PARM_ISOLATE).set(format_isolate(lock_ids))


def isolate_ids(node) -> list[int]:
    """The isolated locks, [] when nothing is isolated."""
    return parse_isolate(node.evalParm(PARM_ISOLATE))


def deform_state(node) -> tuple[bool, bool]:
    """(an animated hair mesh is wired in, Shot deform is on)."""
    wired = len(node.inputs()) > 2 and node.inputs()[2] is not None
    p = node.parm("shot_deform")
    return wired, bool(p.eval()) if p is not None else True


def anim_mismatch_text(anim_points: int, rest_points: int) -> str:
    """Why the shot deform is refused, "" when it can run: the animated hair mesh must have the rest hair
    mesh's points (another count would move the wrong points). The same words as the HDA's warning."""
    if anim_points == rest_points and rest_points > 0:
        return ""
    if anim_points <= 0:
        return "Anim hair mesh: no prims named like the rest hair mesh: no deform"
    return f"Anim hair mesh: {anim_points} points, rest hair mesh {rest_points}: no deform"


def deform_problem(node) -> str:
    """With an animated hair mesh wired in: why the deform does not run ("" when it does). Cooks the anim
    input's hair (ANIM_HAIR) once; call it when the deform is turned on, not per frame."""
    if not (len(node.inputs()) > 2 and node.inputs()[2] is not None):
        return ""
    anim, rest = node.node("ANIM_HAIR"), node.node("IN_HAIR")
    try:
        ga, gr = anim.geometry(), rest.geometry()
    except (AttributeError, hou.Error):
        return ""
    if ga is None or gr is None:
        return ""
    return anim_mismatch_text(len(ga.iterPoints()), len(gr.iterPoints()))


def set_shot_deform(node, on: bool) -> None:
    """Shot deform on / off: a view choice, no undo step; in the UI a scene opens with it off
    (OnLoaded); without a UI it stays as saved."""
    p = node.parm("shot_deform")
    if p is not None:
        with hou.undos.disabler():
            p.set(int(bool(on)))
        try:   # turned on or off mid-playback: the While playing display follows at once
            playing = hou.isUIAvailable() and hou.playbar.isPlaying()
        except (AttributeError, hou.Error):
            playing = False
        _set_playing(node, playing_flag(playing, _deforming(node)))


def set_drag_preview(node, lock_ids: Sequence[int] | None, factor: float = 1.0) -> None:
    """While a slider drags: these locks grow at `factor` of their strands (1: their real count,
    `logic.drag_factor`) with DRAG_SEGMENTS points a strand; the rest keep their display. None clears it
    (the release grows them in full). No undo step, never saved (OnLoaded clears it), never during
    publish. A node built before drag_factor grows them at the preview fraction."""
    p = node.parm(PARM_DRAG_PREVIEW)
    if p is None:
        return
    with hou.undos.disabler():
        p.set(format_isolate(lock_ids))
        f = node.parm(PARM_DRAG_FACTOR)
        if f is not None and abs(f.eval() - float(factor)) > 1e-9:
            f.set(float(factor))


def xray_opacity(node) -> float:
    """Alpha per strand of the locks out of focus (config.GHOST_ALPHA on an HDA without the parm)."""
    p = node.parm(PARM_XRAY)
    return float(p.eval()) if p is not None else config.GHOST_ALPHA


def set_xray_opacity(node, alpha: float) -> None:
    """The panel's X-ray strength: a view choice, no undo step, no lock regrows (a ghost copy per lock and
    alpha is made once and kept)."""
    p = node.parm(PARM_XRAY)
    if p is not None and abs(p.eval() - float(alpha)) > 1e-6:
        with hou.undos.disabler():
            p.set(float(alpha))


def set_focus(node, lock_ids: Sequence[int] | None) -> None:
    """The panel's selection: those locks keep their colour, the others are drawn see-through and grey
    (None: every lock in its colour). It replaces Houdini's selection highlight, which painted the
    selected lock over in one colour: the viewport selection of this node is cleared. A view state:
    no undo step, never saved (OnLoaded clears it), no lock recooks."""
    p = node.parm(PARM_FOCUS)
    if p is None:
        return
    text = format_isolate(lock_ids)
    with hou.undos.disabler():
        if p.eval() != text:
            p.set(text)
        viewer = _scene_viewer()
        try:
            sel = viewer.currentGeometrySelection() if viewer is not None else None
            if sel is not None and node in sel.nodes() and any(s.selectionString(node.geometry())
                                                               for s in sel.selections()):
                viewer.setCurrentGeometrySelection(hou.geometryType.Primitives, (node,), (
                    hou.Selection(hou.geometryType.Primitives),))
        except hou.Error:
            pass   # no active selector (a view state): nothing is highlighted there


def focus_ids(node) -> list[int]:
    """The locks in focus, [] when every lock is drawn in its colour."""
    p = node.parm(PARM_FOCUS)
    return parse_isolate(p.eval()) if p is not None else []


def set_strands(node, lock_ids: Sequence[int] | str | None) -> None:
    """Draw these locks as their strands (None: every lock packed; STRANDS_ALL: the whole groom). The
    viewport draws a packed lock's strands as a flat band of one width; unpacked, it draws each strand's
    width, thinning to the tip. A view state like isolate: no undo step, cleared when the scene is loaded
    again. It changes no lock's hair, only how `hair_packed` hands it to the viewport."""
    p = node.parm(PARM_STRANDS)
    if p is None:
        return
    if lock_ids == STRANDS_ALL:
        text = STRANDS_ALL
    else:
        text = format_isolate(sorted(set(int(i) for i in (lock_ids or ()))))
    if p.eval() != text:
        with hou.undos.disabler():
            p.set(text)


def strands_all(node) -> bool:
    """The whole groom is drawn as strands (set_strands(node, STRANDS_ALL))."""
    p = node.parm(PARM_STRANDS)
    return p is not None and p.eval().strip() == STRANDS_ALL


def cook_display(node) -> None:
    """Cook the node now when the viewport draws it, so the panel's loading line covers the wait (the
    viewport would cook it on its next draw anyway). A cook error stays on the node."""
    try:
        if node.isDisplayFlagSet() and node.parent().isDisplayFlagSet():
            node.cook()
    except hou.OperationFailed:
        pass


def strand_ids(node) -> list[int]:
    """The locks drawn as strands by id, [] when every lock is packed or all are (strands_all)."""
    p = node.parm(PARM_STRANDS)
    if p is None or p.eval().strip() == STRANDS_ALL:
        return []
    return parse_isolate(p.eval())


def _set_lock_flag(node, lock_ids: Iterable[int], field_name: str, value: bool, label: str) -> int:
    data = read_data(node)
    want = set(int(i) for i in lock_ids)
    names = []
    for lk in data.locks:
        if lk.id in want and getattr(lk, field_name) != bool(value):
            setattr(lk, field_name, bool(value))
            names.append(lk.name or f"lock {lk.id}")
    changed = len(names)
    if changed:
        # the lock's root moves, or it stops taking scalp: regions are out of date, never re-split silently
        who = names[0] if changed == 1 else f"{changed} locks"
        data.mark_stale(f"{who}: {label.lower()}")
        write_data(node, data, UNDO_PREFIX + label)
    return changed


def set_root_flip(node, lock_ids: Iterable[int], flip: bool) -> int:
    """Root at the mesh piece's other end (`flip`) or back at the end nearer the scalp, for these locks.
    One undo step; kept through re-Detect; marks regions out of date. Returns how many locks changed."""
    return _set_lock_flag(node, lock_ids, "root_flip", flip, "Root flipped" if flip else "Root back at the scalp end")


def set_excluded(node, lock_ids: Iterable[int], excluded: bool) -> int:
    """Leave these locks out of the hair (no strands, not published) or take them back. Mesh and guide
    still show them. One undo step; kept through re-Detect; marks regions out of date (Update regions gives
    their scalp to the other locks). Returns how many locks changed."""
    return _set_lock_flag(node, lock_ids, "excluded", excluded, "Excluded from hair" if excluded else "Grows hair again")


def _scene_viewer():
    if not hou.isUIAvailable():
        return None
    return hou.ui.paneTabOfType(hou.paneTabType.SceneViewer)


def _index_ranges(indices: Iterable[int]) -> str:
    """0 1 2 5 -> "0-2 5": a selection string Houdini resolves in C++, not one hou.Prim per item."""
    out, run = [], None
    for i in sorted(indices):
        if run and i == run[1] + 1:
            run[1] = i
        else:
            if run:
                out.append(f"{run[0]}-{run[1]}" if run[1] > run[0] else str(run[0]))
            run = [i, i]
    if run:
        out.append(f"{run[0]}-{run[1]}" if run[1] > run[0] else str(run[0]))
    return " ".join(out)


def _parse_ranges(text: str) -> list[int]:
    out: list[int] = []
    for part in text.split():
        if "-" in part:
            lo, hi = part.split("-", 1)
            if lo.isdigit() and hi.isdigit():
                out.extend(range(int(lo), int(hi) + 1))
        elif part.isdigit():
            out.append(int(part))
    return out


_LOCK_OF_PRIM: dict[int, tuple] = {}   # node session id -> (cookCount, lock_id per prim, frozen output)


def _lock_of_prim(node) -> tuple[list[int], "hou.Geometry"] | None:
    """lock_id of each output prim, read again only after the node has cooked again. The panel polls
    the viewport selection while Houdini handles events in the middle of a cook (Anim on: ~1.4 s), and
    node.geometry() there cooks the node inside its own cook: "Infinite recursion in evaluation", and
    the cook fails. needsToCook() cannot tell (it stays true on this node)."""
    count = node.cookCount()
    hit = _LOCK_OF_PRIM.get(node.sessionId())
    if hit is not None and hit[0] == count:
        return hit[1], hit[2]
    geo = node.geometry()
    if geo.findPrimAttrib(config.ATTR_LOCK_ID) is None:
        return None
    ids = list(geo.primIntAttribValues(config.ATTR_LOCK_ID))
    frozen = geo.freeze(read_only=True)   # shares the cooked data; resolves selection strings later
    _LOCK_OF_PRIM[node.sessionId()] = (node.cookCount(), ids, frozen)
    return ids, frozen


def selected_lock_ids(node) -> list[int]:
    """Locks whose spines, strands or mesh pieces are selected in the viewport (empty when none).
    Bulk reads: the panel polls this, and one hou.Prim per selected strand made every tick lag."""
    viewer = _scene_viewer()
    if viewer is None:
        return []
    try:
        sel = viewer.currentGeometrySelection()
    except hou.Error:
        return []
    if sel is None or node not in sel.nodes():
        return []
    read = _lock_of_prim(node)
    if read is None:
        return []
    lock_of_prim, geo = read
    ids: set[int] = set()
    for s in sel.selections():
        if s.selectionType() == hou.geometryType.Primitives:
            ids.update(lock_of_prim[i] for i in _parse_ranges(s.selectionString(geo)) if i < len(lock_of_prim))
        else:   # points: few in practice, take their prims
            for pt in s.points(geo):
                ids.update(p.intAttribValue(config.ATTR_LOCK_ID) for p in pt.prims())
    return sorted(i for i in ids if i >= 0)


def select_locks(node, ids: Iterable[int]) -> None:
    """Select those locks' primitives in the viewport (nothing without a UI)."""
    viewer = _scene_viewer()
    if viewer is None:
        return
    # Geometry selection exists only while the viewer shows the node's own network (inside the geo
    # object); at /obj level Houdini refuses it, so the panel's selection simply is not mirrored there.
    if viewer.pwd() != node.parent():
        return
    want = set(ids)
    geo = node.geometry()
    if geo.findPrimAttrib(config.ATTR_LOCK_ID) is None:
        return
    # one bulk read and a range string: a hou.Prim per strand (116 k on Helen) made each selection lag
    picked = [i for i, lid in enumerate(geo.primIntAttribValues(config.ATTR_LOCK_ID)) if lid in want]
    try:
        # no undo step: Houdini records a viewport selection, and the panel selects again after an edit
        # (the prim numbers of locks drawn as strands change), so Ctrl+Z undid that, not the edit
        with hou.undos.disabler():
            node.setCurrent(True, clear_all_selected=True)
            viewer.setCurrentGeometrySelection(hou.geometryType.Primitives, (node,), (
                hou.Selection(geo, hou.geometryType.Primitives, _index_ranges(picked)),))
    except hou.Error:
        # The viewer has no active selector (view state, not a select state): Houdini refuses with
        # "Not available in this context / no active selector found". The panel's selection simply is
        # not mirrored there; that is not an error the user has to see.
        pass


def display_state(node) -> tuple[str, str]:
    """The node's own display mode and colour-by, for the panel to show on open."""
    return (config.DISPLAY_MODES[node.evalParm(PARM_DISPLAY)], config.COLOR_BY[node.evalParm(PARM_COLOR_BY)])


def _existing_versions(hip_dir: str, asset: str) -> list[str]:
    usd0, _ = logic.publish_paths(hip_dir, asset, "v001")
    pub_dir = os.path.dirname(os.path.dirname(usd0))
    return sorted(os.listdir(pub_dir)) if os.path.isdir(pub_dir) else []


def publish_context(node) -> tuple[str, list[str]]:
    """(scene name without extension, versions already published) for logic.publish_version."""
    data = read_data(node)
    scene = hou.hipFile.basename()
    asset = data.asset or asset_from_scene(scene)
    return os.path.splitext(scene)[0], _existing_versions(os.path.dirname(hou.hipFile.path()), asset)


def publish(node, version: str | None = None) -> PublishResult:
    """Write the asset groom USD and `vNNN/_grooming/` (grooming_data.json, publish.json); never overwrite.

    Every file goes to a temp name next to its final one and is renamed only once all are written
    (`logic.StagedFiles`, the USD last); a failure removes this publish's own temp files and the
    folders it made, so nothing half written is left and an earlier publish stays as it was.
    """
    data = read_data(node)
    scene = hou.hipFile.basename()
    asset = data.asset or asset_from_scene(scene)
    hip_dir = os.path.dirname(hou.hipFile.path())
    note = ""
    try:
        if not version:
            version, note = logic.publish_version(os.path.splitext(scene)[0], _existing_versions(hip_dir, asset))
        usd, tool_dir = logic.publish_paths(hip_dir, asset, version)
        version = os.path.basename(os.path.dirname(usd))  # the normalised spelling (v7 -> v007)
    except (ValueError, OSError) as exc:
        return PublishResult(False, "", version or "", f"Cannot publish: {exc}")
    if os.path.exists(usd) or os.path.exists(tool_dir):
        return PublishResult(False, usd, version, f"{version} is already published, not overwritten: {usd}")

    exporter = _inner(node, NODE_PUBLISH_USD)
    staged = logic.StagedFiles()
    try:
        staged.make_dirs(tool_dir)
        usd_tmp = staged.stage(usd, last=True)
        with hou.undos.disabler():  # export settings are not an edit of the groom
            node.parm(PARM_PUBLISH_PATH).set(usd_tmp)
            try:
                # the Groom output's rest path: every lock not excluded, full hair, whatever the view
                hair = _cooked(node, NODE_GROOM_REST)
                strands = hair.intrinsicValue("primitivecount")
                exporter.parm("execute").pressButton()
            finally:
                node.parm(PARM_PUBLISH_PATH).set("")
        errors = exporter.errors()
        if errors or not os.path.isfile(usd_tmp):
            raise RuntimeError("; ".join(errors) or "USD export wrote no file")
        staged.write_text(os.path.join(tool_dir, "grooming_data.json").replace("\\", "/"), data.to_json())
        # the mask layers' painted values, so a later version (or another scene) can read them back
        mask_record = grooming_masks.publish_masks(node, staged, tool_dir)
        record = publish_record(asset, version, usd, hou.hipFile.path(), data, strands, node.path(),
                                hou.applicationVersionString(), masks=mask_record)
        staged.write_text(os.path.join(tool_dir, "publish.json").replace("\\", "/"),
                          json.dumps(record, ensure_ascii=False, indent=1))
        staged.commit()
    except Exception as exc:  # noqa: BLE001 - reported to the panel, never a dialog
        left = staged.abort()
        msg = f"Publish {version} failed, nothing written: {logic.publish_error(exc)}"
        if left:
            msg += f" (could not remove {', '.join(left)})"
        return PublishResult(False, usd, version, msg)
    msg = f"Published {asset} {version}: {strands:,} strands, {len(data.locks)} locks"
    if data.regions_stale:
        msg += " (regions out of date)"
    if note:
        msg += f". {note}"
    _status(f"{config.HDA_LABEL}: {msg}")
    return PublishResult(True, usd, version, msg)


# ---------------------------------------------------------------------------
# Called from inside the HDA
# ---------------------------------------------------------------------------

def on_button(node, action: str) -> None:
    """Parm button callbacks of the HDA: results go to the status bar, never a dialog."""
    try:
        if action == "detect":
            detect(node)
        elif action == "split_regions":
            split_regions(node)
        elif action == "publish":
            res = publish(node, node.evalParm(PARM_PUBLISH_VERSION).strip() or None)
            _status(f"{config.HDA_LABEL}: {res.message}", error=not res.ok)
    except Exception as exc:  # noqa: BLE001
        _status(f"{config.HDA_LABEL}: {action} failed: {exc}", error=True)


def cook_assign(sop) -> None:
    """Python SOP "assign": lock_id, name, group, colours, visibility and resolved settings per spine."""
    top = sop.parent()
    geo = sop.geometry()
    data = read_data(top)
    names = _prim_values(geo, "mesh_name", "s") or [""] * len(geo.iterPrims())
    uniq = unique_names(names)
    pieces = list(zip(uniq, _prim_values(geo, "root", "v"), _prim_values(geo, "length", "f")))
    ids = assign_pieces(pieces, mesh_locks(data))     # a drawn lock (v0.2b) is never a mesh piece
    attrs = lock_display_attribs(data, ids)
    geo.addAttrib(hou.attribType.Prim, config.ATTR_LOCK_ID, -1)
    geo.setPrimIntAttribValues(config.ATTR_LOCK_ID, ids)
    for key in ("name", "group", "lock_match"):
        geo.addAttrib(hou.attribType.Prim, key, "")
        geo.setPrimStringAttribValues(key, attrs[key])
    for key in ("lock_cd", "group_cd"):
        geo.addAttrib(hou.attribType.Prim, key, (0.0, 0.0, 0.0))
        geo.setPrimFloatAttribValues(key, [c for rgb in attrs[key] for c in rgb])
    for key, default in (("visible", 1), ("root_flip", 0), ("excluded", 0), ("row_display", -1)):
        geo.addAttrib(hou.attribType.Prim, key, default)
        geo.setPrimIntAttribValues(key, attrs[key])
    for key in model.SETTING_KEYS:
        geo.addAttrib(hou.attribType.Prim, key, 0.0)
        geo.setPrimFloatAttribValues(key, attrs[key])
    # v0.2b: each lock's control points (spine_edit bends its spine by them), and the drawn flag (0: of the mesh)
    edit = geo.addArrayAttrib(hou.attribType.Prim, config.ATTR_EDIT_CP, hou.attribData.Float, 1)
    for prim, values in zip(geo.prims(), edit_cp_values(data, ids)):
        if values:
            prim.setAttribValue(edit, values)
    geo.addAttrib(hou.attribType.Prim, ATTR_DRAWN, 0)
    missing = ids.count(-1)
    if missing:
        sop.addWarning(f"{missing} locks are not in the groom data yet: press Detect locks")


def loaded_resets(ui: bool) -> tuple[tuple[str, Any], ...]:
    """(parm, value) OnLoaded puts back. View state always; Shot deform only in the UI: grooming is the
    main mode there, but hython / hbatch / a farm job opening a shot scene to cache output 1 must keep
    the deform it was saved with, else every frame of the cache is the rest groom (t56)."""
    resets = ((PARM_ISOLATE, ""), (PARM_DRAG_PREVIEW, ""), (PARM_STRANDS, ""), (PARM_FOCUS, ""), (PARM_PLAYING, 0))
    return resets + (("shot_deform", 0),) if ui else resets


def on_loaded(node) -> None:
    """HDA OnLoaded: isolate is a temporary view, so a scene saved while isolated opens showing all;
    a scene saved while playing opens at its Display; in the UI a scene saved with Shot deform on opens
    at rest (grooming is the main mode: with the deform every lock is drawn as strands and focus cannot
    see through the others). Without a UI (caching a shot) the deform stays as saved."""
    with hou.undos.disabler():
        for name, empty in loaded_resets(hou.isUIAvailable()):
            p = node.parm(name)
            if p is not None and p.eval():
                p.set(empty)
        # the toggle first: mark_old_regions may write the data again, in today's schema (t66 N1)
        kept = keep_old_lookup(node)
        mark_old_regions(node)
    if kept:
        _status(f"{config.HDA_LABEL}: {LOOKUP_KEPT_TEXT}")
    # layers of an older test build's removed kinds are dropped on reading (model.migrate): said once, on
    # the status bar, never in a dialog
    dropped = grooming_masks.mask_dropped(node)
    if dropped:
        _status(f"{config.HDA_LABEL}: {dropped}")
    install_playbar_callback()


LOOKUP_PARM = "lookup_per_piece"         # the node's "Fit lookup per lock"
LOOKUP_SINCE_SCHEMA = 4                  # no build under schema 4 had the parm; every build from 5 on has it
LOOKUP_NOTE = "monofx_fit_lookup"        # node user data: the choice for a scene from before the parm was made
LOOKUP_KEPT_TEXT = ("this scene was saved before \"Fit lookup per lock\": it is off, so the groom is the one "
                    "the scene was saved with. Turn it on on the node for faster strokes (strand points then "
                    "move: by up to 1 cm on the Helen test scene)")


def hip_holds(path: str | None, name: str) -> bool | None:
    """The saved scene file holds a value of the parm: True / False, None when there is no file to read (a
    scene never saved). A hip stores each parm of a node as a record line of its own, `<name>\t[ ...`, in
    plain text, a .hiplc / .hipnc too. The record, not the word: the name in a sticky note, a comment, a node
    name or an expression does not count (t68: a sticky note holding the name opened an old scene with the
    lookup on), and neither does an embedded definition's `name "<name>"`."""
    if not path or not os.path.isfile(path):
        return None
    record, tail = b"\n" + name.encode("ascii") + b"\t[", b"\n"   # the file's first line counts as after a \n
    try:
        with open(path, "rb") as fh:
            while True:
                block = fh.read(1 << 20)
                if not block:
                    return False
                if record in tail + block:
                    return True
                tail = block[-(len(record) - 1):]
    except OSError:
        return None


def scene_before_lookup(stored: str | None, held: bool | None = None) -> bool:
    """Pure: the node comes from a scene saved before "Fit lookup per lock" existed. `held`, whether the
    saved scene file holds the parm (`hip_holds`), is the fact itself and decides whenever it is known,
    whatever the data's schema: the parm came in the middle of the schema 4 test builds (245f480 has it, on;
    two schema 4 commits before it do not), so the schema cannot tell (t66 N2), and the data may have been
    written again in today's schema before this library took over (t67: a scene opened with a library of
    another checkout that has no such parm; its OnLoaded `mark_old_regions` rewrote the data, then OnUpdated
    read schema 6). A v0.1 scene saved again by a build with the parm keeps what it was saved with. Without a
    file to read (None) the schema decides: under 4 no build had it, from 5 on every build had it. A node with
    no data yet is a new node: not such a scene (a node made in this session carries the note from
    `on_created` and is never judged)."""
    if not stored or not stored.strip():
        return False
    try:
        schema = int(json.loads(stored).get("schema", 1))
    except (ValueError, TypeError, AttributeError):
        return False
    if held is not None:
        return not held
    return schema < LOOKUP_SINCE_SCHEMA


def keep_old_lookup(node) -> bool:
    """OnLoaded: a scene saved before "Fit lookup per lock" existed opens with it OFF, written on the node (the
    user's decision, 2026-11-15, t64 B4): such a scene holds no value for the parm, so it would take the
    default, on, and its groom would no longer be the one it was saved and published with (same roots and
    strand counts, strand points moved: up to 0.47 cm on a fresh Helen groom, 0.96 cm on the Helen scene as
    v0.1 saved it, t66). Off, the groom is v0.1's within v0.1's own run-to-run difference (a few strands by
    0.0024 cm over 10 runs, t68). Must run before anything writes `groom_data` again (OnLoaded's
    `mark_old_regions` rewrote a schema 1 scene as today's schema first: N1). Done once a node (user data
    `monofx_fit_lookup`, saved with the hip): after that the parm is the artist's, who may turn it on. A new
    node keeps the default, on. A node merged from another file is judged by the scene it is merged INTO
    (the file Houdini names). True when the parm was set."""
    p = node.parm(LOOKUP_PARM)
    if p is None or node.userData(LOOKUP_NOTE) is not None:
        return False
    if not scene_before_lookup(node.evalParm(config.DATA_PARM), hip_holds(hou.hipFile.path(), LOOKUP_PARM)):
        return False
    with hou.undos.disabler():
        p.set(0)
        node.setUserData(LOOKUP_NOTE, "off: the scene was saved before the parm existed")
    return True


LOOKUP_NOTE_BY_HAND = {1: "on: set by hand", 0: "off: set by hand"}


def on_lookup_changed(node, recorded: bool = False) -> None:
    """The toggle's callback: the artist set "Fit lookup per lock" by hand, so the note says so (it said "off:
    the scene was saved before the parm existed" after the artist had turned it on, t68). Any note means the
    choice is made: OnLoaded / OnUpdated never judge the node again. `recorded`: the note goes into the undo step
    being made (the panel's `set_node_setting`), so one undo puts back the value AND the note; the parm's own
    callback writes it with undo off, as before."""
    p = node.parm(LOOKUP_PARM)
    if p is None:
        return
    note = LOOKUP_NOTE_BY_HAND[1 if p.eval() else 0]
    if recorded:
        node.setUserData(LOOKUP_NOTE, note)
        return
    with hou.undos.disabler():
        node.setUserData(LOOKUP_NOTE, note)


LOOKUP_KEPT_NOTE = "off: the scene was saved before the parm existed"   # what keep_old_lookup writes
NODE_SETTING_PARMS = {"lookup": LOOKUP_PARM, "undo_cache_gb": config.UNDO_CACHE_PARM,
                      "undo_deform_gb": config.UNDO_DEFORM_PARM}
NODE_SETTING_LABELS = {"lookup": "Fit lookup per lock", "undo_cache_gb": "Undo cache, GB",
                       "undo_deform_gb": "Deformed undo, GB"}
NODE_SETTING_GB = (0.01, 16.0)   # the two limits from the panel are clamped to this (a typo of 99999 GB lifted the cap)


def node_settings(node) -> dict:
    """The node's own values the panel's settings page shows: "Fit lookup per lock" (`lookup`, and
    `lookup_kept` with `lookup_text` while it is off because the scene was saved before it existed), "Undo cache,
    GB" and "Deformed undo, GB". A parm the node does not have (an older build) is left out."""
    out: dict = {}
    for key, name in NODE_SETTING_PARMS.items():
        p = node.parm(name)
        if p is not None:
            out[key] = bool(p.eval()) if key == "lookup" else float(p.eval())
    if "lookup" in out:
        out["lookup_kept"] = not out["lookup"] and node.userData(LOOKUP_NOTE) == LOOKUP_KEPT_NOTE
        out["lookup_text"] = LOOKUP_KEPT_TEXT
    return out


def set_node_setting(node, key: str, value) -> None:
    """Set one of `node_settings` from the panel: one undo step named "MONO Grooming: <label>". Only the three
    keys of NODE_SETTING_PARMS (anything else: KeyError). The lookup toggle also records that the artist chose it
    (`on_lookup_changed(recorded=True)`: "on/off: set by hand", in the same undo step; a parm set from Python runs
    no callback). The undo limits are not in a lock's cache key (setting them regrows nothing); the lookup is in
    every lock's key. A lowered "Deformed undo, GB" frees nothing until the next deformed state is stored. The two
    limits are clamped to NODE_SETTING_GB (0.01-16)."""
    if key not in NODE_SETTING_PARMS:
        raise KeyError(f"not a node setting the panel sets: {key!r}")
    name = NODE_SETTING_PARMS[key]
    p = node.parm(name)
    if p is None:
        raise KeyError(f"{node.path()} has no parm {name} (an older build of the node)")
    with hou.undos.group(f"{UNDO_PREFIX}{NODE_SETTING_LABELS[key]}"):
        if key == "lookup":
            p.set(1 if value else 0)
            on_lookup_changed(node, recorded=True)
        else:
            p.set(min(max(float(value), NODE_SETTING_GB[0]), NODE_SETTING_GB[1]))


def on_created(node) -> None:
    """HDA OnCreated: a node made now keeps "Fit lookup per lock" at its default, on, whatever scene it is made
    in (the note marks the choice made, so OnLoaded / OnUpdated never force it off), and the playbar
    callback."""
    try:
        if node.parm(LOOKUP_PARM) is not None and node.userData(LOOKUP_NOTE) is None:
            node.setUserData(LOOKUP_NOTE, "new node: the default")
    except hou.Error:
        pass
    install_playbar_callback()


def on_updated(node) -> None:
    """HDA OnUpdated (the node's definition was replaced: a scene opened with another copy of the library
    before this one took over, so this HDA's OnLoaded never ran for it): the same choice for a scene from
    before "Fit lookup per lock" (`keep_old_lookup`)."""
    if keep_old_lookup(node):
        _status(f"{config.HDA_LABEL}: {LOOKUP_KEPT_TEXT}")


OLD_REGIONS_WHY = "Regions were split by an older rule: Update regions"


def region_rule(frozen) -> int:
    """The rule a stored split was made with (0: before the rule was recorded)."""
    if frozen is None or frozen.findGlobalAttrib(ATTR_REGION_RULE) is None:
        return 0
    return int(frozen.attribValue(ATTR_REGION_RULE))


def mark_old_regions(node) -> bool:
    """A scene whose regions were split by an older rule (config.REGION_RULE) shows them out of date,
    with the reason, until Update regions. No undo step (called while loading). True when marked."""
    frozen = node.parm(PARM_REGIONS).evalAsGeometry() if node.parm(PARM_REGIONS) is not None else None
    if frozen is None or not frozen.intrinsicValue("pointcount") or region_rule(frozen) >= config.REGION_RULE:
        return False
    data = read_data(node)
    if data.regions_stale and OLD_REGIONS_WHY in data.stale_why:
        return False
    data.mark_stale(OLD_REGIONS_WHY)
    with hou.undos.disabler():
        node.parm(config.DATA_PARM).set(data.to_json())
    return True


def playing_state(event_name: str) -> bool | None:
    """Pure: the `playing` value for a playbar event (by name), None when the event changes nothing."""
    if event_name == "Started":
        return True
    if event_name == "Stopped":
        return False
    return None


def playing_flag(playing: bool, deforming: bool) -> int:
    """Pure: the node's `playing` parm. Only a node with Shot deform on draws lighter while playing:
    without the deform nothing cooks per frame (Helen hair full plays at the 30 fps cap), so switching to
    Hair preview only recooked on Start and Stop, and regrew every lock's preview on the first play."""
    return int(playing and deforming)


def _deforming(node) -> bool:
    p = node.parm("deform_active")
    return bool(p.eval()) if p is not None else False


def _set_playing(node, value: int) -> None:
    p = node.parm(PARM_PLAYING)
    if p is not None and p.eval() != value:
        with hou.undos.disabler():
            p.set(value)


def _on_playbar(event_type, frame) -> None:
    state = playing_state(str(event_type).rsplit(".", 1)[-1])
    if state is None:
        return
    try:
        nodes = find_nodes()
    except hou.Error:
        return
    for n in nodes:
        _set_playing(n, playing_flag(state, _deforming(n)))


def install_playbar_callback() -> None:
    """Once per session (kept on `sys`, like the cache): while the timeline plays, every MONO Grooming
    node with Shot deform on draws its While playing mode (`display_eff`). Only with a UI; hython has
    no playbar."""
    if hou is None or not hou.isUIAvailable() or getattr(sys, _PLAYBAR_ATTR, False):
        return
    hou.playbar.addEventCallback(_on_playbar_trampoline)
    setattr(sys, _PLAYBAR_ATTR, True)


def _on_playbar_trampoline(event_type, frame) -> None:
    # registered once; looks the handler up again so a reloaded adapter's code runs
    from apps.houdini import grooming_adapter as current
    current._on_playbar(event_type, frame)


def _definition_stamp(top) -> str:
    try:
        d = top.type().definition()
        return f"{d.libraryFilePath()}@{d.modificationTime()}" if d is not None else ""
    except hou.Error:
        return ""


def _key_parms(top) -> list[tuple[str, str]]:
    out = []
    for p in top.parms():
        name = p.name()
        if name in _KEY_SKIP_PARMS:
            continue
        try:
            out.append((name, p.evalAsString()))
        except hou.Error:
            continue
    return out


def capture_flag(groom: bool, wired: bool, deforming: bool) -> int:
    """Whether a lock's strands are cooked with the Point Deform capture inside the per-lock loop
    (`do_capture`, in the key): never (0), for either output.

    Output 1 stopped in round 3 (t62) and the display with Shot deform on in t65: a lock's hair is the rest
    strands whatever deforms it, one cache entry shared by the display at rest, the display deformed, output 1
    and publish, and the capture a deform needs is made per lock from cached strands (`cook_groom_captured`),
    kept apart (`capture_slot`), one a lock, only once a deformed output is read. Captured in the loop, every
    state of every lock held 800 B a point (Helen: 3.3 GB live, 400 MB a stroke over 6 locks): no undo cache
    limit could hold that, so with Shot deform on every undo regrew its locks, the cache stayed at 7.5 GB
    after the deform was switched off (the captured strands were "what the node shows" in their own slot),
    and switching Shot deform on regrew the whole groom once (t64 B6)."""
    return 0


CAPTURE_MODE = "+capture"


def cache_mode(drag: bool, factor: float, capture: int) -> str:
    """Pure: the LockCache slot of a lock's hair. A dragged lock's coarser strands, its preview and its full
    hair are kept apart, and so are strands cooked with the Point Deform capture: with an anim wired the
    Groom output captures and the display at rest does not, so the same lock has two keys at once. In one
    slot of KEEP 2 those two filled it, and an undo found the hair from before the edit gone and regrew the
    lock (0.65-1.5 s instead of 0.04 s, t57)."""
    mode = "drag" if drag else "hair" if factor >= 1.0 else "hair_preview"
    return mode + CAPTURE_MODE if capture else mode


def cook_lock_keys(sop, groom: bool = False) -> None:
    """Python SOP "lock_keys", hair modes only: per spine `cache_key` (a digest of everything the
    per-lock hair loop reads for that lock: its spine and settings, its region, its mesh piece, the
    parms the loop uses, the display mode and preview factor) and `cached` (its hair is in the cache).

    groom=True ("groom_keys", the Groom output and publish): the view is ignored. Every lock not
    excluded grows, at full density, never as a drag; a lock the display shows as full hair gets the
    same key, so both outputs share its cached strands.

    Inputs: 0 the shown spines (`grows`), 1 PREVIEW (detail `factor`), 2 SURFACE_KEYS (detail
    `surface_keys`: per piece 9 floats of its lookup cloud), 3 SCALP_REGIONS (each lock's region
    fingerprint: grooming_masks.region_keys)."""
    import numpy as np

    top = sop.parent()
    geo = sop.geometry()
    ins = sop.inputs()
    preview = ins[1].geometry()
    surface = ins[2].geometry()
    mode = str(top.evalParm(PARM_DISPLAY_EFF))
    factor = preview.attribValue("factor") if preview.findGlobalAttrib("factor") else 1.0
    light = preview.attribValue("preview_factor") if preview.findGlobalAttrib("preview_factor") else factor
    publishing = groom
    wired = bool(top.evalParm("anim_wired")) if top.parm("anim_wired") is not None else False
    deforming = bool(top.evalParm("deform_active")) if top.parm("deform_active") is not None else False
    dragged = set(parse_isolate(top.evalParm(PARM_DRAG_PREVIEW))) \
        if top.parm(PARM_DRAG_PREVIEW) is not None and not groom else set()
    # dragged locks: their real count (or the panel's fraction) with fewer points a strand; a node
    # built before drag_factor: the preview fraction
    drag_f = top.evalParm(PARM_DRAG_FACTOR) if top.parm(PARM_DRAG_FACTOR) is not None else light
    # each lock's region fingerprint (numpy, kept per split: grooming_masks.region_keys); input 3 SCALP_REGIONS
    rk = grooming_masks.region_keys(top, ins[3].geometry()) if len(ins) > 3 and ins[3] is not None else {}
    # density masks (mask_read): per lock its scope set and a digest of the factor on its own skin; the 9
    # region sums would miss a stroke that moves density inside a region
    mask_sets, mask_hashes, mask_adds = grooming_masks.lock_mask_keys(preview)
    sk = surface.floatListAttribValue("surface_keys") if surface.findGlobalAttrib("surface_keys") else ()
    # the mode is per lock (its `disp`, lock_shown): only its strand factor reaches the hair, so the
    # node's mode is not in the key and a lock keeps its cache when the node's Display changes
    shared = lock_key([CACHE_NET_VERSION, _definition_stamp(top), _key_parms(top)])

    pattrs = [a for a in geo.pointAttribs() if a.dataType() == hou.attribData.Float]
    parrays = [np.frombuffer(geo.pointFloatAttribValuesAsString(a.name()), dtype=np.float32).reshape(-1, a.size())
               for a in pattrs]
    rattrs = sorted((a for a in geo.primAttribs() if a.name() not in _KEY_SKIP_ATTRIBS), key=lambda a: a.name())
    n_prims = geo.intrinsicValue("primitivecount")
    columns = []                    # per attribute its values by prim, read in one call
    for a in rattrs:
        name, size = a.name(), a.size()
        if a.isArrayType() or a.dataType() not in (hou.attribData.Float, hou.attribData.Int, hou.attribData.String):
            columns.append((name, [prim.attribValue(a) for prim in geo.iterPrims()]))
            continue
        flat = (geo.primFloatAttribValues(name) if a.dataType() == hou.attribData.Float
                else geo.primIntAttribValues(name) if a.dataType() == hou.attribData.Int
                else geo.primStringAttribValues(name))
        columns.append((name, list(flat) if size == 1 else [tuple(flat[i * size:(i + 1) * size]) for i in range(n_prims)]))

    def column(name, default):
        return list(geo.primIntAttribValues(name)) if geo.findPrimAttrib(name) is not None else [default] * n_prims

    lock_ids, excluded = column(config.ATTR_LOCK_ID, -1), column("excluded", 0)
    disps, pieces = column("disp", -1), column("piece", -1)
    # each spine's points, from one read of the vertices (prim.points() per lock was 16 ms of every cook)
    vertex_prim, vertex_point = grooming_masks._vertex_tables(geo)
    order = np.argsort(vertex_prim, kind="stable")
    spine_points = np.split(vertex_point[order], np.cumsum(np.bincount(vertex_prim, minlength=n_prims))[:-1])         if n_prims else []
    for name, default in (("cache_key", ""), ("cache_mode", ""), ("cached", 0), ("strand_factor", 1.0),
                          ("do_capture", 0), ("drag_seg", 0)):
        if geo.findPrimAttrib(name) is None:
            geo.addAttrib(hou.attribType.Prim, name, default)
    cache = hair_cache()
    for nid in cache.nodes():           # nodes deleted, or from a scene loaded before
        if hou.nodeBySessionId(nid) is None:
            cache.drop_node(nid)
    sid = top.sessionId()
    cache.begin(sid)                    # what this cook touches is in use: never dropped to make room
    if not groom and not deforming:
        # the display at rest reads neither its deformed hair nor the merge that fed the deform: left in
        # the cache they were "what the node shows" (the last state of their slot is never dropped), 270 MB
        # of Helen's limit gone for good once Shot deform had been on
        cache.drop(sid, MERGED_LOCK, DEFORMED_MODE + "hair")
        cache.drop(sid, MERGED_LOCK, MERGED_MODE + "hair_cache")
    cache.set_limit(sid, undo_cache_limit(top))
    has_disp = geo.findPrimAttrib("disp") is not None
    preview_mode = config.DISPLAY_MODES.index("hair_preview")
    keys, flags, factors, modes, captures, drags, grows, msets, madds = [], [], [], [], [], [], [], [], []
    akeys, aflags = [], []
    has_excluded = geo.findPrimAttrib("excluded") is not None
    for row in range(n_prims):
        lid = lock_ids[row]
        if groom:   # every lock that is not excluded, whatever its eye, isolate or Display
            grows.append(int(not (has_excluded and excluded[row])))
        disp = disps[row] if has_disp else config.DISPLAY_MODES.index(mode) \
            if mode in config.DISPLAY_MODES else len(config.DISPLAY_MODES) - 1
        # hairgen's density x this (strand_factor): the preview fraction for a lock shown as preview or
        # being dragged, else full; publishing is always full
        f = light if disp == preview_mode else 1.0
        drag = lid in dragged and not publishing
        if drag:
            f = min(f, drag_f)
        if publishing:
            f = 1.0
        factors.append(f)
        drags.append(int(drag))
        # captured only where a deform reads it (capture_flag): the display while Shot deform is on,
        # the Groom output whenever an anim is wired (it cooks only when something reads it)
        cap = capture_flag(groom, wired, deforming)
        captures.append(cap)
        # a dragged lock's strands are coarser (DRAG_SEGMENTS): kept apart from its full hair, and
        # captured strands apart from plain ones (cache_mode)
        lock_mode = cache_mode(drag, f, cap)
        modes.append(lock_mode)
        piece = pieces[row]
        idx = spine_points[row]
        parts: list[Any] = [shared, [(name, values[row]) for name, values in columns]]
        parts.extend(arr[idx].tobytes() for arr in parrays)
        parts.append(rk.get(lid, ()))
        parts.append(tuple(sk[piece * 9:piece * 9 + 9]) if piece >= 0 else ())
        parts.append(f)
        parts.append(cap)
        parts.append(int(drag))
        # the lock's automatic roots read everything above and no layer: their own key (cook_auto_store)
        akey = lock_key(parts)
        akeys.append(akey)
        # 0 not kept, 1 kept, 2 kept with the order they are thinned in (thin_u: made the first time a layer
        # covers the lock, thin_store)
        held = cache.get(sid, lid, AUTO_MODE + lock_mode, akey)
        aflags.append(0 if held is None else 2 if held.findPrimAttrib("thin_u") is not None else 1)
        mset = mask_sets[lid] if 0 <= lid < len(mask_sets) else -1
        msets.append(mset)
        madds.append(float(mask_adds[lid]) if mset >= 0 and lid < len(mask_adds) else 0.0)
        parts.append(mask_hashes[lid] if mset >= 0 else "")
        key = lock_key(parts)
        keys.append(key)
        flags.append(int(cache.has(sid, lid, lock_mode, key)))
    geo.setPrimStringAttribValues("cache_key", keys)
    geo.setPrimStringAttribValues("cache_mode", modes)
    geo.setPrimFloatAttribValues("strand_factor", factors)
    geo.setPrimIntAttribValues("do_capture", captures)
    geo.setPrimIntAttribValues("drag_seg", drags)
    geo.setPrimIntAttribValues("cached", flags)
    # density layers: the lock's scope set (mask_skin reads mask_keep_<set> / mask_add_<set>; -1: no layer
    # covers it, the v0.1 nodes alone) and the strands its second scatter lays out
    geo.addAttrib(hou.attribType.Prim, "mask_set", -1)
    geo.setPrimIntAttribValues("mask_set", msets)
    geo.addAttrib(hou.attribType.Prim, "mask_add_n", 0.0)
    geo.setPrimFloatAttribValues("mask_add_n", madds)
    geo.addAttrib(hou.attribType.Prim, "auto_key", "")
    geo.setPrimStringAttribValues("auto_key", akeys)
    geo.addAttrib(hou.attribType.Prim, "auto_cached", 0)
    geo.setPrimIntAttribValues("auto_cached", aflags)
    if groom:
        geo.setPrimIntAttribValues("grows", grows)


AUTO_MODE = "auto:"      # LockCache slot (+ the hair's mode) of a lock's automatic roots, before the layers


def _auto_slot(sop):
    """(node session id, lock id, slot, key) of the automatic roots of the lock a loop node works on."""
    spine = sop.inputs()[-1].geometry().prims()
    if not spine:
        return None
    p = spine[0]
    return (sop.parent().sessionId(), p.intAttribValue(config.ATTR_LOCK_ID),
            AUTO_MODE + p.stringAttribValue("cache_mode"), p.stringAttribValue("auto_key"))


def cook_auto_store(sop) -> None:
    """Python SOP "auto_store" in the per-lock loop, after root_pick: keep the lock's automatic roots
    (hairgen's scatter with the roots root_pick relocated) under its key without layers, and pass them on
    unchanged. One state a lock: a stroke changes no automatic root, an edit of the lock replaces them.
    Input 0 root_pick, input 1 the lock's keyed spine. "thin_store" is the same call after thin_order: the
    entry is replaced by the roots with `thin_u` (only for a lock a layer covers, the first time)."""
    slot = _auto_slot(sop)
    if slot is None or not slot[3]:
        return
    cache = hair_cache()
    cache.put_derived(*slot, sop.geometry().freeze(read_only=True))
    cache.keep_only(slot[0], slot[1], slot[2], (slot[3],))


def cook_auto_load(sop) -> None:
    """Python SOP "auto_load": the lock's automatic roots from the cache (`lock_keys` saw them there:
    `auto_cached`). Input 0 is the lock's keyed spine."""
    slot = _auto_slot(sop)
    geo = sop.geometry()
    geo.clear()
    got = hair_cache().get(*slot) if slot is not None else None
    if got is None:
        raise hou.NodeError("the lock's automatic roots are not in the cache")
    geo.merge(got)


def cook_cache_store(sop) -> None:
    """Python SOP "cache_store", last node of the per-lock loop: keep this lock's strands under its
    key, then output nothing (the merge is hair_cache's, so the strands are copied once)."""
    geo = sop.geometry()
    spine = sop.inputs()[1].geometry()
    prims = spine.prims()
    if prims:
        p = prims[0]
        hair_cache().put(sop.parent().sessionId(), p.intAttribValue(config.ATTR_LOCK_ID),
                         p.stringAttribValue("cache_mode"), p.stringAttribValue("cache_key"),
                         geo.freeze(read_only=True))
    geo.clear()


def _cached_hair(sop, with_prim: bool = False):
    """(lock id, name, frozen strands) of every lock that grows, from the cache; input 1 = keyed spines.
    with_prim: (lock id, name, frozen strands, its keyed spine prim)."""
    keyed = sop.inputs()[1].geometry()
    cache = hair_cache()
    sid = sop.parent().sessionId()
    grows = keyed.findPrimAttrib("grows") is not None
    named = keyed.findPrimAttrib(config.ATTR_NAME) is not None
    missing = 0
    for p in keyed.iterPrims():
        if grows and p.intAttribValue("grows") == 0:
            continue
        lid = p.intAttribValue(config.ATTR_LOCK_ID)
        g = cache.get(sid, lid, p.stringAttribValue("cache_mode"), p.stringAttribValue("cache_key"))
        if g is None:
            missing += 1
        else:
            name = p.stringAttribValue(config.ATTR_NAME) if named else ""
            yield (lid, name, g, p) if with_prim else (lid, name, g)
    if missing:
        sop.addWarning(f"{missing} locks have no hair in the cache: change Display and back to cook them")


def geo_stats(node, lock_ids: Sequence[int] | None = None) -> dict:
    """What the hair of these locks (None: every lock that grows) holds as the node shows it now: locks,
    prims (one strand each), points, and the attribute names by class. Read from the per-lock cache
    (geometry intrinsics, no copy), so it costs nothing to ask on every selection."""
    packed = _HAIR_PACKED_PATHS.get(node.sessionId())
    sop = hou.node(packed) if packed else None
    if sop is None:
        sop = next((n for n in node.allSubChildren() if n.name() == "hair_packed"), None)
        if sop is None:
            return {}
        _HAIR_PACKED_PATHS[node.sessionId()] = sop.path()
    want = None if lock_ids is None else {int(i) for i in lock_ids}
    cache = hair_cache()
    sid = node.sessionId()
    keyed = sop.inputs()[1].geometry()
    if keyed is None or keyed.findPrimAttrib("cache_key") is None:
        return {}
    grows = keyed.findPrimAttrib("grows") is not None
    out = {"locks": 0, "prims": 0, "points": 0, "attribs": {}, "mode": ""}
    for p in keyed.iterPrims():
        lid = p.intAttribValue(config.ATTR_LOCK_ID)
        if (want is not None and lid not in want) or (grows and p.intAttribValue("grows") == 0):
            continue
        g = cache.get(sid, lid, p.stringAttribValue("cache_mode"), p.stringAttribValue("cache_key"))
        if g is None:
            continue
        out["locks"] += 1
        out["prims"] += g.intrinsicValue("primitivecount")
        out["points"] += g.intrinsicValue("pointcount")
        # the panel reads "hair" / "hair_preview" / "drag": whether the strands carry the capture is not its
        out["mode"] = out["mode"] or p.stringAttribValue("cache_mode").replace(CAPTURE_MODE, "")
        if not out["attribs"]:
            out["attribs"] = {
                "point": sorted(a.name() for a in g.pointAttribs()),
                "prim": sorted(a.name() for a in g.primAttribs()),
                "vertex": sorted(a.name() for a in g.vertexAttribs()),
                "detail": sorted(a.name() for a in g.globalAttribs()),
            }
    return out


_HAIR_PACKED_PATHS: dict[int, str] = {}


def cook_hair_cache(sop) -> None:
    """Python SOPs "hair_cache" (the display's strands: every lock shown and not excluded; the display's
    shot deform reads it) and "groom_cache" (output 1 "Groom" and publish: every lock not excluded, full):
    the strands of every lock that grows, from the cache, merged. Input 0 is the per-lock loop (it
    stored the missing ones), input 1 the keyed spines."""
    geo = sop.geometry()
    geo.clear()
    parts = list(_cached_hair(sop, with_prim=True))
    # The merge of every lock (4 M points on Helen, 0.23 s) is kept frozen, by the locks and keys it
    # holds: an eye, isolate or Display change recooks this node with the same locks, and merging the
    # one frozen geometry costs 0.006 s. Only the last merge per node and output is kept.
    which = MERGED_MODE + sop.name()
    key = lock_key([(lid, p.stringAttribValue("cache_mode"), p.stringAttribValue("cache_key"))
                    for lid, _name, _g, p in parts])
    cache = hair_cache()
    sid = sop.parent().sessionId()
    whole = cache.get(sid, MERGED_LOCK, which, key)
    if whole is None:
        merged = hou.Geometry()
        for _lid, _name, g, _p in parts:
            merged.merge(g)
        whole = merged.freeze(read_only=True)
        cache.drop(sid, MERGED_LOCK, which)
        cache.put_derived(sid, MERGED_LOCK, which, key, whole)
    geo.merge(whole)


def _display_copy(g):
    """A lock's cached strands for the packed display, without the shot deform's capture: the packed
    display is never deformed, and pCaptPts / pCaptWeights (~800 B a point at maxpt 100) copied into the
    coloured and see-through versions took Helen to 5.9-9.5 GB with the anim wired (review t48)."""
    out = hou.Geometry()
    out.merge(g)
    for name in ("pCaptPts", "pCaptWeights"):
        a = out.findPointAttrib(name)
        if a is not None:
            a.destroy()
    return out


GROOM_CAPTURE_MODE = "groom:capture"     # LockCache slot of a lock's captured strands (full hair) for a deform
DEFORMED_MODE = "deformed:"              # LockCache slot (MERGED_LOCK) of the display's deformed hair, a state


def capture_slot(hair_mode: str) -> str:
    """The LockCache slot of a lock's captured strands by the slot of the hair they were made from: the full
    hair's (output 1, and the display in Hair) is GROOM_CAPTURE_MODE, a preview's or a drag's its own, so the
    display in Hair preview and output 1 do not take turns in the one capture a lock keeps."""
    return GROOM_CAPTURE_MODE if hair_mode == "hair" else GROOM_CAPTURE_MODE + ":" + hair_mode


def _deform_key(sop, keyed, anim) -> str:
    """Key of the display's deformed hair: the locks that grow with the state of their hair, and what deforms
    them (the animated mesh's points at this frame, the capture radius)."""
    grows = keyed.findPrimAttrib("grows") is not None
    locks = [(p.intAttribValue(config.ATTR_LOCK_ID), p.stringAttribValue("cache_mode"), p.stringAttribValue("cache_key"))
             for p in keyed.iterPrims() if not grows or p.intAttribValue("grows")]
    top = sop.parent()
    radius = top.evalParm("deform_radius") if top.parm("deform_radius") is not None else 0.0
    return lock_key([anim.pointFloatAttribValuesAsString("P"), radius, locks])


def cook_deform_keys(sop) -> None:
    """Python SOP "deform_keys" (display, Shot deform on): the detail `deform_key` (`_deform_key`) and
    `deform_cached`: the deformed hair of exactly this state is in the cache, so the switch after it reads it
    there and neither the capture loop nor the Point Deform cooks. An undo with Shot deform on then costs what
    it costs at rest. Input 0 the keyed spines (`lock_keys`), input 1 ANIM_HAIR."""
    keyed, anim = (i.geometry() for i in sop.inputs()[:2])
    key = _deform_key(sop, keyed, anim)
    if len(sop.inputs()) > 2 and keyed.findPrimAttrib(ATTR_DRAWN) is not None and any(keyed.primIntAttribValues(ATTR_DRAWN)):
        # drawn locks follow the animated scalp (v0.2b U2): its points at this frame are part of the state
        key = lock_key([key, sop.inputs()[2].geometry().pointFloatAttribValuesAsString("P")])
    geo = sop.geometry()
    geo.clear()
    geo.addAttrib(hou.attribType.Global, "deform_key", "")
    geo.setGlobalAttribValue("deform_key", key)
    geo.addAttrib(hou.attribType.Global, "deform_cached", 0)
    geo.setGlobalAttribValue("deform_cached", int(hair_cache().has(sop.parent().sessionId(), MERGED_LOCK, DEFORMED_MODE + "hair", key)))


def cook_deform_store(sop) -> None:
    """Python SOP "deform_store": keep the display's deformed hair (input 0, without the capture) under
    `deform_keys`' key (input 1) and pass it on. States of another frame are dropped first (they can never be
    read again but by going back to that frame), and the states together hold at most the node's "Deformed
    undo, GB" (`undo_deform_limit`; the user's decision on B6, 2026-11-15: memory, not a packed display), the
    oldest going first; the state in use always stays. A state is the whole deformed groom, so it is large;
    it is held apart from "Undo cache, GB" (`LockCache.APART`), so the hair's own states and the deformed ones
    never push each other out, and neither limit is exceeded."""
    keys = sop.inputs()[1].geometry()
    key = keys.attribValue("deform_key")
    cache = hair_cache()
    top = sop.parent()
    sid = top.sessionId()
    slot = DEFORMED_MODE + "hair"
    frame = hou.frame()
    if _DEFORM_FRAME.get(sid) != frame:
        cache.drop(sid, MERGED_LOCK, slot)
        _DEFORM_FRAME[sid] = frame
    cache.put_derived(sid, MERGED_LOCK, slot, key, sop.geometry().freeze(read_only=True))
    cache.keep_bytes(sid, MERGED_LOCK, slot, undo_deform_limit(top))


_DEFORM_FRAME: dict[int, float] = {}     # node session id -> the frame its deformed states are of


def cook_deform_load(sop) -> None:
    """Python SOP "deform_load": the display's deformed hair of this state from the cache (`deform_keys`,
    input 0, saw it there)."""
    geo = sop.geometry()
    key = geo.attribValue("deform_key") if geo.findGlobalAttrib("deform_key") is not None else ""
    geo.clear()
    got = hair_cache().get(sop.parent().sessionId(), MERGED_LOCK, DEFORMED_MODE + "hair", key)
    if got is None:
        raise hou.NodeError("the deformed hair is not in the cache")
    geo.merge(got)


def cook_capture_keys(sop) -> None:
    """Python SOP "groom_capture_keys": the keyed spines of output 1 (input 0, `groom_keys`) with
    `capt_cached` per lock: its captured strands for this state of its hair are in the cache. Input 1 is
    `groom_cache`: read so that every lock's hair is in the cache before the capture loop asks for it."""
    geo = sop.geometry()
    sop.inputs()[1].geometry()
    cache = hair_cache()
    sid = sop.parent().sessionId()
    geo.addAttrib(hou.attribType.Prim, "capt_cached", 0)
    geo.setPrimIntAttribValues("capt_cached", [
        int(cache.has(sid, p.intAttribValue(config.ATTR_LOCK_ID), capture_slot(p.stringAttribValue("cache_mode")),
                      p.stringAttribValue("cache_key")))
        for p in geo.iterPrims()])


def cook_capture_load(sop) -> None:
    """Python SOP "groom_capture_load", first node of the capture loop: this lock's cached strands with the
    contract's attributes only (what GROOM_REST keeps). Input 0 is the lock's keyed spine."""
    geo = sop.geometry()
    prims = geo.prims()
    spine = prims[0] if prims else None
    key = (spine.intAttribValue(config.ATTR_LOCK_ID), spine.stringAttribValue("cache_mode"),
           spine.stringAttribValue("cache_key")) if spine is not None else None
    geo.clear()
    if key is None:
        return
    g = hair_cache().get(sop.parent().sessionId(), *key)
    if g is None:
        sop.addWarning("a lock's hair is not in the cache: read output 1 again")
        return
    geo.merge(g)
    keep = set(config.GROOM_ATTRIBS)
    for attribs in (geo.pointAttribs(), geo.primAttribs(), geo.vertexAttribs(), geo.globalAttribs()):
        for a in attribs:
            if a.name() != "P" and a.name() not in keep:
                a.destroy()


def cook_capture_store(sop) -> None:
    """Python SOP "groom_capture_store", last node of the capture loop: keep this lock's captured strands
    under its hair's key (GROOM_CAPTURE_MODE), then output nothing. Input 1 is the lock's keyed spine.
    Stored with `put_derived`: a capture from cached strands, not a cook of the lock's hair."""
    geo = sop.geometry()
    prims = sop.inputs()[1].geometry().prims()
    if prims:
        p = prims[0]
        sid, lid, key = sop.parent().sessionId(), p.intAttribValue(config.ATTR_LOCK_ID), p.stringAttribValue("cache_key")
        # one capture a lock, outside the undo cache's count (size 0): the captures of a whole groom are
        # larger than any sensible limit (Helen 3.3 GB) and would push every hair state out of it, while a
        # capture is made again from cached strands in a moment. `undo_cache_usage` reports them apart
        cache = hair_cache()
        slot = capture_slot(p.stringAttribValue("cache_mode"))
        cache.put_derived(sid, lid, slot, key, geo.freeze(read_only=True), size=0)
        cache.keep_only(sid, lid, slot, (key,))
    geo.clear()


def cook_groom_captured(sop) -> None:
    """Python SOP "groom_capture_all" (output 1's deform reads it; it cooks only when the deformed output is
    read): every lock of the rest groom with its Point Deform capture to the rest hair mesh, merged.
    Input 0 the capture loop (it stored what was missing), 1 the keyed spines (`groom_capture_keys`).

    A lock is captured once per state of its hair (its cache key) and kept under GROOM_CAPTURE_MODE: an edit
    captures the locks it changed, a frame change nothing. These entries are 800 B a point: only the one of
    the hair's current state is kept per lock (an undo captures its locks again from their cached strands,
    it regrows nothing)."""
    geo = sop.geometry()
    geo.clear()
    keyed = sop.inputs()[1].geometry()
    cache = hair_cache()
    sid = sop.parent().sessionId()
    grows = keyed.findPrimAttrib("grows") is not None
    missing = 0
    for p in keyed.iterPrims():
        if grows and p.intAttribValue("grows") == 0:
            continue
        got = cache.get(sid, p.intAttribValue(config.ATTR_LOCK_ID), capture_slot(p.stringAttribValue("cache_mode")),
                        p.stringAttribValue("cache_key"))
        if got is None:
            missing += 1
        else:
            geo.merge(got)
    if missing:
        sop.addWarning(f"{missing} locks have no capture in the cache: read output 1 again")


def cook_hair_packed(sop) -> None:
    """Python SOP "hair_packed": the display's hair, one packed primitive per lock embedding its cached
    strands (no copy). Merging 4 M points into one geometry made every edit and every hide re-upload the
    whole groom to the viewport; packed, the viewport keeps the locks that did not change.
    Locks in `strand_ids` are drawn as strands (the viewport draws no width ramp inside a packed prim):
    their packed prim stays, empty, so every lock keeps prim number = its place among the packed prims
    and a viewport selection of packed locks still means the same locks; their strands come after."""
    geo = sop.geometry()
    geo.clear()
    lid_attr = geo.addAttrib(hou.attribType.Prim, config.ATTR_LOCK_ID, -1)
    name_attr = geo.addAttrib(hou.attribType.Prim, config.ATTR_NAME, "")
    by_group = int(sop.parent().evalParm("color_by")) == 1
    cache = hair_cache()
    sid = sop.parent().sessionId()
    every = strands_all(sop.parent())
    strands = set(strand_ids(sop.parent()))
    focus = set(focus_ids(sop.parent()))
    alpha = round(xray_opacity(sop.parent()), 4)
    empty = hou.Geometry().freeze(read_only=True) if strands or every else None
    unpacked = []
    for lid, name, g, sp in _cached_hair(sop, with_prim=True):
        # The viewport does not tint embedded geometry with the packed prim's Cd (it drew Helen white):
        # the colour goes inside, on a copy of the lock's strands made once per colour and kept in the
        # cache, so a colour change copies, an edit copies one lock, and nothing regrows.
        cd = tuple(round(c, 4) for c in sp.attribValue("group_cd" if by_group else "lock_cd"))
        mode, key = sp.stringAttribValue("cache_mode") + "#cd", f"{sp.stringAttribValue('cache_key')}|{cd}"
        coloured = cache.get(sid, lid, mode, key)
        if coloured is None:
            tinted = _display_copy(g)
            # the colour is the attribute's default: every strand has it and no value is written per strand
            # (a tuple of 3 floats a strand through Python was most of the 30 ms this node cost after an undo)
            tinted.addAttrib(hou.attribType.Prim, "Cd", cd)
            coloured = tinted.freeze(read_only=True)
            cache.put_derived(sid, lid, mode, key, coloured)
        prim = geo.createPacked("PackedGeometry")
        gkey = f"{key}|ghost|{alpha}"
        # only the copies of the hair shown now are kept: a copy is made in a few ms from the lock's cached
        # strands, so the copies of earlier states (as large as the hair itself, by the count) would only
        # halve what the undo cache holds
        cache.keep_only(sid, lid, mode, (key, gkey))
        if every or lid in strands:   # hair_packed_color gives them their colour, or the see-through grey
            prim.setEmbeddedGeometry(empty)
            unpacked.append(coloured)
        elif focus and lid not in focus:
            # out of focus: see-through grey, a copy made once per colour and kept like the coloured one
            ghost = cache.get(sid, lid, mode, gkey)
            if ghost is None:
                m = config.GHOST_MIX
                gcd = tuple(c * (1 - m) + t * m for c, t in zip(cd, config.GHOST_TINT))
                tinted = _display_copy(g)
                tinted.addAttrib(hou.attribType.Prim, "Cd", gcd)
                tinted.addAttrib(hou.attribType.Prim, "Alpha", float(alpha))
                ghost = tinted.freeze(read_only=True)
                cache.put_derived(sid, lid, mode, gkey, ghost)
            prim.setEmbeddedGeometry(ghost)
        else:
            prim.setEmbeddedGeometry(coloured)
        prim.setAttribValue(lid_attr, lid)
        prim.setAttribValue(name_attr, name)
    for g in unpacked:  # the cached strands carry lock_id and name
        geo.merge(g)


def cook_frozen_regions(sop) -> None:
    """Python SOP "frozen regions": the split stored on the node's `regions` parm, or nothing."""
    geo = sop.geometry()
    geo.clear()
    frozen = sop.parent().parm(PARM_REGIONS).evalAsGeometry()
    if frozen is not None:
        geo.merge(frozen)


# ---------------------------------------------------------------------------
# v0.2b lock redraw and control points (docs/plans/grooming_v0_2.md "v0.2b"; B1's model and logic)
#
# Places are in the node's own space (its SOP geometry, scene units) unless said: a viewer state turns world
# rays into it with the object's transform. A lock of the hair mesh keeps its handles in its ROOT FRAME (B1:
# `Lock.spine`, relative to SPINES_MEASURED, the spine as Root to skin left it); a drawn lock keeps its curve in
# rest scene space (`Lock.curve`). Every change below is ONE undo step named from config.UNDO_SPINE and may act
# on several locks at once.
# ---------------------------------------------------------------------------

def drawn_spine_arrays(curve, n_points: int, unit_cm: float, width_cm: float, thick_cm: float,
                       taper: float = config.DRAWN_TAPER_DEFAULT, width_mult: float = 1.0, thick_mult: float = 1.0,
                       twist_add: float = 0.0, root_on_skin=None, skin_normal=None) -> dict:
    """Pure (numpy): a drawn lock's spine as the network writes it (`cook_drawn_locks`). Its curve through the
    handles at `n_points` equal lengths (`logic.drawn_spine`); the root moved onto the skin (`root_on_skin`), the
    move fading over the first quarter (the spike's drawn lock); the frame from "across the lock, lying on the
    skin" at the root (`skin_normal` x the tangent), carried along without twist, then turned by `twist_add` x u as
    apply_settings turns a measured lock's; width and thickness by `logic.drawn_profile` x the lock's width_mult /
    thick_mult, in scene units. Returns P, tangent, axis, minor, curveu, width, thick, twist (per point) and root,
    direction, length."""
    import numpy as np
    P = np.asarray(logic.drawn_spine(curve, int(n_points)), dtype=float)
    S = logic.arc_lengths(P)
    U = S / S[-1] if S[-1] > 0 else np.zeros(len(P))
    if root_on_skin is not None:
        P = P + (np.asarray(root_on_skin, dtype=float) - P[0]) * (1 - np.clip(U * 4, 0, 1))[:, None]
        S = logic.arc_lengths(P)
        U = S / S[-1] if S[-1] > 0 else np.zeros(len(P))
    n = len(P)
    idx = np.arange(n)
    T = P[np.minimum(idx + 1, n - 1)] - P[np.maximum(idx - 1, 0)]
    T /= np.maximum(np.linalg.norm(T, axis=1, keepdims=True), 1e-12)
    nrm = np.asarray(skin_normal if skin_normal is not None else (0.0, 1.0, 0.0), dtype=float)
    a = np.cross(nrm, T[0])
    if np.linalg.norm(a) < 1e-4:
        a = np.cross(T[0], (0.0, 1.0, 0.0) if abs(T[0][1]) < 0.9 else (1.0, 0.0, 0.0))
    A = np.zeros_like(P)
    for i in range(n):
        a = a - T[i] * np.dot(a, T[i])
        a = a / max(np.linalg.norm(a), 1e-12)
        A[i] = a
    tw = float(twist_add) * U
    A = A * np.cos(tw)[:, None] + np.cross(T, A) * np.sin(tw)[:, None]      # about the tangent, right-handed
    W, TH = logic.drawn_profile(U, width_cm, thick_cm, taper)
    unit = max(float(unit_cm), 1e-9)
    span = P[-1] - P[0]
    return {"P": P, "tangent": T, "axis": A, "minor": np.cross(T, A), "curveu": U,
            "width": W / unit * float(width_mult), "thick": TH / unit * float(thick_mult), "twist": tw,
            "root": P[0].copy(), "direction": span / max(np.linalg.norm(span), 1e-12), "length": float(S[-1])}


def drawn_group(lock_ids: Iterable[int]) -> str:
    """Pure: the Blast group of the strands of these locks (the deform's split, `build_hda._deform_drawn`). No lock:
    a group that matches no strand (an EMPTY Blast group deletes everything: with an edited lock and no drawn one,
    every strand went to the drawn branch and stayed at rest)."""
    return " ".join(f"@lock_id=={int(i)}" for i in lock_ids) or "@lock_id==-1"


def footprint_owners(centres, owners: Sequence[Sequence[int]], root, radius: float) -> tuple[list[int], list[int]]:
    """Pure (numpy): the frozen region points (one per fine scalp prim, its centre) a drawn lock takes as its
    footprint (U3): those within `radius` of its root on the skin, at least the nearest one. Returns (their
    indices, the other locks that owned them before, sorted)."""
    import numpy as np
    c = np.asarray(centres, dtype=float).reshape(-1, 3)
    if not len(c):
        return [], []
    d = np.linalg.norm(c - np.asarray(root, dtype=float), axis=1)
    sel = [int(i) for i in np.nonzero(d <= radius)[0]] or [int(np.argmin(d))]
    gave = sorted({int(o) for i in sel for o in owners[i]})
    return sel, gave


def scalp_text(drawn: int, wired: bool, anim_points: int, rest_points: int) -> str:
    """Pure: the panel's line for the drawn locks in a shot (U2), "" when there is nothing to say (no drawn lock,
    or the animated scalp follows)."""
    if drawn <= 0:
        return ""
    locks = "the drawn lock stays" if drawn == 1 else f"the {drawn} drawn locks stay"
    if not wired:
        return f"No animated scalp wired into input 4: {locks} at rest in a shot (the mesh locks deform as before)"
    if anim_points != rest_points or rest_points <= 0:
        return (f"Animated scalp: {anim_points} points, rest scalp {rest_points}: {locks} at rest "
                "(the mesh locks deform as before)")
    return ""


def _spine_rows(geo) -> dict[int, dict]:
    """{lock id: P, tangent, axis (numpy, scene units), prim number} of a spine geometry, read in bulk."""
    import numpy as np
    if geo.findPrimAttrib(config.ATTR_LOCK_ID) is None:
        return {}

    def pts(name):
        return np.frombuffer(geo.pointFloatAttribValuesAsString(name), np.float32).reshape(-1, 3).astype(np.float64)

    P, T, A = pts("P"), pts("tangentu"), pts("lock_axis")
    vprim, vpoint = grooming_masks._vertex_tables(geo)
    order = np.argsort(vprim, kind="stable")
    n = geo.intrinsicValue("primitivecount")
    rows = np.split(vpoint[order], np.cumsum(np.bincount(vprim, minlength=n))[:-1]) if n else []
    out = {}
    for k, lid in enumerate(geo.primIntAttribValues(config.ATTR_LOCK_ID)):
        if lid >= 0:
            idx = rows[k]
            out[int(lid)] = {"P": P[idx], "tangent": T[idx], "axis": A[idx], "prim": k}
    return out


def _skin_snap(node):
    """A function putting a place (node space) on the rest scalp, as the network's xyzdist does, and the scalp's
    normal there: (snap(p) -> p, normal(p) -> n)."""
    geo = _cooked(node, "IN_SCALP")

    def nearest(p):
        hit = geo.nearestPrim(hou.Vector3(*[float(c) for c in p]))
        return hit[0], hit[1], hit[2]

    def snap(p):
        prim, u, v = nearest(p)
        return tuple(prim.positionAtInterior(u, v)) if prim is not None else tuple(float(c) for c in p)

    def normal(p):
        prim, _u, _v = nearest(p)
        return tuple(prim.normal()) if prim is not None else (0.0, 1.0, 0.0)

    return snap, normal


def _unit(node) -> float:
    return max(float(node.evalParm("unit_cm")), 1e-9)


def _lock_or_raise(data: model.GroomData, lock_id: int) -> model.Lock:
    lk = data.lock(int(lock_id))
    if lk is None:
        raise KeyError(f"no lock {lock_id}")
    return lk


def _handles_now(lk: model.Lock, row: dict | None, unit: float):
    """(handles in the root frame, origin, R) of a lock of the mesh now: its edit, else the measured spine's at its
    count (`logic.handle_count`). `row` is its SPINES_MEASURED row."""
    origin, R = logic.root_frame(row["P"], row["tangent"], row["axis"])
    if lk.edited:
        H = logic._arr(lk.spine)
    else:
        length_cm = float(logic.arc_lengths(row["P"])[-1]) * unit
        H = logic.measured_handles(row["P"], row["tangent"], row["axis"], logic.handle_count(length_cm, lk.handles))
    return H, origin, R


def lock_handles(node, lock_ids: Sequence[int] | None = None) -> dict[int, dict]:
    """The handles of these locks (None: every lock), for the viewer state (B3) and the panel (B4). Per lock id:
    `points` the handles in the node's space (a moved root where the network put it, on the skin), `frame` the
    same in its root frame (a drawn lock: in its drawn spine's root frame), `origin` / `axes` that frame (rows:
    tangent, width axis, thickness axis), `count`, `edited`, `drawn`, `root_moved`, `spine` (the cooked spine after
    the edit, node space), `measured` (the spine before it; a drawn lock: its spine), `length_cm` (the measured
    length; a drawn lock its own), `default_count` (by length), `count_set` (the artist's number or None)."""
    import numpy as np
    data = read_data(node)
    unit = _unit(node)
    measured = _spine_rows(_cooked(node, NODE_SPINES_MEASURED))
    after = _spine_rows(_cooked(node, NODE_SPINES))
    want = [lk.id for lk in data.locks] if lock_ids is None else [int(i) for i in lock_ids]
    out: dict[int, dict] = {}
    for lid in want:
        lk = data.lock(lid)
        if lk is None or lid not in after:
            continue
        cooked = after[lid]
        if lk.drawn:
            origin, R = logic.root_frame(cooked["P"], cooked["tangent"], cooked["axis"])
            world = logic._arr(lk.curve).copy()
            world[0] = cooked["P"][0]                       # on the skin, as the network put it
            H = logic.world_to_frame(world, origin, R)
            length_cm = float(logic.arc_lengths(cooked["P"])[-1]) * unit
            base = cooked["P"]
            moved = False
        else:
            row = measured.get(lid)
            if row is None:
                continue
            H, origin, R = _handles_now(lk, row, unit)
            world = logic.frame_to_world(H, origin, R)
            moved = logic.root_moved(H)
            if moved:
                world[0] = cooked["P"][0]
            length_cm = float(logic.arc_lengths(row["P"])[-1]) * unit
            base = row["P"]
        out[lid] = {
            "points": [tuple(map(float, p)) for p in world], "frame": [tuple(map(float, p)) for p in H],
            "origin": tuple(map(float, origin)), "axes": [tuple(map(float, r)) for r in R], "count": int(len(H)),
            "edited": bool(lk.edited), "drawn": bool(lk.drawn), "root_moved": bool(moved),
            "spine": np.asarray(cooked["P"]).tolist(), "measured": np.asarray(base).tolist(),
            "length_cm": length_cm, "default_count": logic.handle_count(length_cm), "count_set": lk.handles}
    return out


def _measured_rows(node) -> dict[int, dict]:
    return _spine_rows(_cooked(node, NODE_SPINES_MEASURED))


def _store_points(lk: model.Lock, row: dict | None, points, space: str, unit: float, data: model.GroomData,
                  snap=None) -> tuple[bool, bool]:
    """Write new handles on `lk` (in `data`). `space` "points" (node space) or "frame". Returns (changed, root
    moved by this write). A root given where it already is keeps the stored root (a root never moved stays the
    measured one); a moved root marks the regions out of date with its reason (v0.1's rule, U3)."""
    import numpy as np
    same = ROOT_SAME_CM / unit
    if lk.drawn:
        if space == "frame":
            raise ValueError("a drawn lock's points are given in the node's space")
        new = logic._arr(points)
        if len(new) < 2:
            raise ValueError("a lock needs at least 2 handles")
        old = logic._arr(lk.curve)
        # given where the root is stored, or where the network put it on the skin (`row`: its cooked spine): not moved
        root_moved = float(np.linalg.norm(new[0] - old[0])) > same and (
            row is None or float(np.linalg.norm(new[0] - row["P"][0])) > same)
        if root_moved and snap is not None:
            new[0] = snap(new[0])
        if not root_moved:
            new[0] = old[0]
        if len(old) == len(new) and np.array_equal(old, new):
            return False, False
        lk.curve = [tuple(map(float, p)) for p in new]
        lk.root = lk.curve[0]
        lk.length = float(logic.arc_lengths(new)[-1])
        span = new[-1] - new[0]
        lk.direction = tuple(float(c) for c in span / max(np.linalg.norm(span), 1e-12))
        if root_moved:
            data.mark_stale(f"{lk.name}: a root moved")
        return True, root_moved
    H_now, origin, R = _handles_now(lk, row, unit)
    H = logic._arr(points) if space == "frame" else logic.world_to_frame(points, origin, R)
    if len(H) < 2:
        raise ValueError("a lock needs at least 2 handles")
    # where the root is now (frame): the stored root, or the origin (the measured root)
    root_was = H_now[0] if len(H_now) else np.zeros(3)
    root_moved = float(np.linalg.norm(H[0] - root_was)) > same
    if not root_moved:
        H[0] = root_was
    new = [tuple(map(float, p)) for p in H]
    if lk.spine == new:
        return False, False
    lk.spine = new
    if root_moved:
        data.mark_stale(f"{lk.name}: a root moved")
    return True, root_moved


def _spine_result(changed: list[int], roots: list[int], data: model.GroomData, what: str) -> dict:
    names = [(data.lock(i).name if data.lock(i) else str(i)) for i in changed]
    msg = f"{what}: {', '.join(names)}" if names else f"{what}: nothing changed"
    if roots:
        msg += "; regions out of date (a root moved): Update regions"
    return {"locks": changed, "roots_moved": roots, "message": msg}


def set_points(node, points: dict, space: str = "points", step: str = "move") -> dict:
    """Set the handles of one or several locks in ONE undo step (config.UNDO_SPINE[step], "move" by default: a
    viewer-state drag writes once on release). `points`: {lock id: K places}, in the node's space ("points") or the
    lock's root frame ("frame"; locks of the mesh only). A different K re-counts the handles. Returns {"locks":
    ids changed, "roots_moved": ids, "message"}."""
    if space not in ("points", "frame"):
        raise ValueError(f"space {space!r}")
    data = read_data(node)
    unit = _unit(node)
    rows = _measured_rows(node)
    snap = _skin_snap(node)[0]
    drawn_rows = _spine_rows(_cooked(node, NODE_SPINES)) if any(
        (data.lock(int(i)) is not None and data.lock(int(i)).drawn) for i in points) else {}
    changed, roots = [], []
    for lid, pts in points.items():
        lk = _lock_or_raise(data, lid)
        row = drawn_rows.get(lk.id) if lk.drawn else rows.get(lk.id)
        ch, rm = _store_points(lk, row, pts, space, unit, data, snap)
        if ch:
            changed.append(lk.id)
        if rm:
            roots.append(lk.id)
    if changed:
        write_data(node, data, config.UNDO_SPINE[step])
    return _spine_result(changed, roots, data, {"move": "Moved", "rotate": "Turned", "scale": "Scaled",
                                                "redraw": "Redrawn"}.get(step, "Changed"))


def reset_points(node, lock_ids: Iterable[int]) -> dict:
    """Back to the measured spine, or for a drawn lock back to its curve as drawn (`Lock.drawn_curve`), one undo
    step "Reset lock". The hair comes from the cache (no lock regrown). A root that had moved comes back: regions
    out of date."""
    data = read_data(node)
    want = set(int(i) for i in lock_ids)
    moved = [lk.id for lk in data.locks if lk.id in want and lk.edited and (
        (lk.drawn and tuple(lk.curve[0]) != tuple(lk.drawn_curve[0])) or
        (not lk.drawn and logic.root_moved(lk.spine)))]
    done = logic.reset_locks(data.locks, [int(i) for i in lock_ids])
    for lid in moved:
        data.mark_stale(f"{data.lock(lid).name}: a root moved")
    if done:
        write_data(node, data, config.UNDO_SPINE["reset"])
    return _spine_result(done, moved, data, "Reset")


def _transform(node, lock_ids, fn, step: str) -> dict:
    data = read_data(node)
    unit = _unit(node)
    rows = _measured_rows(node)
    changed = []
    for lid in lock_ids:
        lk = _lock_or_raise(data, lid)
        if lk.drawn:
            new = fn(logic._arr(lk.curve), None)
            ch, _ = _store_points(lk, None, new, "points", unit, data)
        else:
            row = rows.get(lk.id)
            if row is None:
                continue
            H, _origin, R = _handles_now(lk, row, unit)
            ch, _ = _store_points(lk, row, fn(H, R), "frame", unit, data)
        if ch:
            changed.append(lk.id)
    if changed:
        write_data(node, data, config.UNDO_SPINE[step])
    return _spine_result(changed, [], data, {"rotate": "Turned", "scale": "Scaled"}[step])


def rotate_points(node, lock_ids: Iterable[int], axis, degrees: float) -> dict:
    """Turn these locks about their roots by `degrees` round `axis` (a direction in the node's space), one undo
    step "Rotate lock". The root stays."""
    import numpy as np
    ax = np.asarray(axis, dtype=float)
    return _transform(node, [int(i) for i in lock_ids],
                      lambda H, R: logic.rotate_about_root(H, ax if R is None else logic.direction_to_frame(ax, R),
                                                           degrees), "rotate")


def scale_points(node, lock_ids: Iterable[int], factor: float) -> dict:
    """Scale these locks about their roots (a longer or shorter lock), one undo step "Scale lock"."""
    if factor <= 0:
        raise ValueError("a scale factor over 0")
    return _transform(node, [int(i) for i in lock_ids], lambda H, R: logic.scale_about_root(H, factor), "scale")


def set_handle_count(node, lock_ids: Iterable[int], count: int | None) -> dict:
    """The number of handles of these locks (U1; None: back to the default by length), one undo step "Set handle
    count". An edited lock keeps its shape: its moves are re-fitted onto the new handles (`logic.resample_spine`);
    a drawn lock's curve is sampled again. Returns {"locks", "gap_cm": {id: how far the spine moved}, "message"}:
    past config.RESAMPLE_TOL_CM the message says how far (the change is still made)."""
    import numpy as np
    if count is not None and not config.HANDLES_MIN <= int(count) <= config.HANDLES_MAX:
        raise ValueError(f"a handle count from {config.HANDLES_MIN} to {config.HANDLES_MAX}")
    data = read_data(node)
    unit = _unit(node)
    rows = _measured_rows(node)
    gaps: dict[int, float] = {}
    changed = []
    for lid in lock_ids:
        lk = _lock_or_raise(data, lid)
        if lk.drawn:
            length_cm = float(logic.arc_lengths(logic.curve_points(lk.curve))[-1]) * unit
            K = logic.handle_count(length_cm, count)
            if K == len(lk.curve) and lk.handles == count:
                continue
            new, gaps[lk.id] = logic.drawn_handle_count(lk.curve, K, unit)      # t80 N6: the public refit
            lk.curve = [tuple(map(float, p)) for p in new]
        else:
            row = rows.get(lk.id)
            if row is None:
                continue
            length_cm = float(logic.arc_lengths(row["P"])[-1]) * unit
            K = logic.handle_count(length_cm, count)
            if lk.edited and K != len(lk.spine):
                new, gap = logic.resample_spine(row["P"], row["tangent"], row["axis"], lk.spine, K, unit)
                lk.spine = [tuple(map(float, p)) for p in new]
                gaps[lk.id] = gap
            elif lk.handles == count:
                continue
            else:
                gaps[lk.id] = 0.0
        lk.handles = None if count is None else int(count)
        changed.append(lk.id)
    if changed:
        write_data(node, data, config.UNDO_SPINE["handles"])
    res = _spine_result(changed, [], data, "Handles")
    far = {i: g for i, g in gaps.items() if g > config.RESAMPLE_TOL_CM}
    if far:
        res["message"] += "; the spine moved " + ", ".join(
            f"{data.lock(i).name} {g:.2f} cm" for i, g in sorted(far.items())) + " (fewer handles cannot hold the edit)"
    res["gap_cm"] = gaps
    return res


def redraw_lock(node, lock_id: int, stroke, tol_cm: float = config.STROKE_TOL_CM) -> dict:
    """The lock redrawn along `stroke` (node space, root first), one undo step "Redraw lock": a lock of the mesh
    takes the fewest handles whose edit lies within `tol_cm` of the stroke (`logic.redraw_handles`), a drawn lock
    the fewest whose curve does (`logic.stroke_handles`). A stroke starting off the root moves the root (on the
    skin). Returns {"locks", "roots_moved", "gap_cm", "count", "message"}."""
    data = read_data(node)
    unit = _unit(node)
    lk = _lock_or_raise(data, lock_id)
    snap = _skin_snap(node)[0]
    if lk.drawn:
        H, gap = logic.stroke_handles(stroke, unit, tol_cm)
        ch, rm = _store_points(lk, None, H, "points", unit, data, snap)
    else:
        row = _measured_rows(node).get(lk.id)
        if row is None:
            raise KeyError(f"lock {lock_id} has no spine (not detected)")
        H, gap = logic.redraw_handles(row["P"], row["tangent"], row["axis"], stroke, unit, tol_cm, snap)
        ch, rm = _store_points(lk, row, H, "frame", unit, data)
    if ch:
        write_data(node, data, config.UNDO_SPINE["redraw"])
    res = _spine_result([lk.id] if ch else [], [lk.id] if rm else [], data, "Redrawn")
    res.update(gap_cm=float(gap), count=int(len(H)))
    res["message"] += _gap_text(gap, len(H), tol_cm)
    return res


def _gap_text(gap: float, count: int, tol_cm: float) -> str:
    """A stroke 12 handles cannot hold is still taken (the manager, 2026-11-21): the message says how far."""
    if gap <= tol_cm:
        return ""
    return f"; {count} handles lie {gap:.2f} cm from the stroke at most (the most a lock has)"


def _default_group(data: model.GroomData, frozen, root) -> str:
    """A drawn lock's group: the group of the lock owning the skin under its root, else the first group."""
    import numpy as np
    if frozen is not None and len(frozen.iterPoints()):
        P = np.frombuffer(frozen.pointFloatAttribValuesAsString("P"), np.float32).reshape(-1, 3)
        i = int(np.argmin(((P - np.asarray(root, dtype=np.float32)) ** 2).sum(1)))
        for lid in frozen.iterPoints()[i].intListAttribValue(ATTR_LOCK_OWNERS):
            lk = data.lock(lid)
            if lk is not None:
                return lk.group
    return data.groups[0].id if data.groups else DEFAULT_GROUP


DRAWN_PREFIX = "drawn"     # a drawn lock's name: drawn_NN (the user, 2026-11-20)


def most_skin_group(data: model.GroomData, owners: Sequence[Sequence[int]]) -> str:
    """Pure: the group of the lock that owned the most of this skin (a shared prim counts 1 / its owners for each),
    "" when none of them is a lock of the data. Ties go to the lower lock id."""
    share: dict[int, float] = {}
    for own in owners:
        for lid in own:
            share[lid] = share.get(lid, 0.0) + 1.0 / max(len(own), 1)
    for lid, _w in sorted(share.items(), key=lambda kv: (-kv[1], kv[0])):
        lk = data.lock(lid)
        if lk is not None:
            return lk.group
    return ""


def draw_lock(node, stroke, width_cm: float = config.DRAWN_WIDTH_CM, thick_cm: float = config.DRAWN_THICK_CM,
              taper: float = config.DRAWN_TAPER_DEFAULT, group: str | None = None, name: str = "",
              tol_cm: float = config.STROKE_TOL_CM) -> dict:
    """A new lock drawn on bare skin along `stroke` (node space, root first; the root goes onto the skin), with
    its width, thickness and tip taper. ONE undo step "Draw lock" that also gives it its footprint (U3: the frozen
    region points within `logic.drawn_footprint_cm(width)` of its root, taken from the locks that owned them), so
    it has hair at once and only the locks that gave skin recook. Returns {"id", "name", "gave": [names of the
    locks that gave skin], "gave_ids", "gap_cm", "count", "message"}."""
    import numpy as np
    data = read_data(node)
    unit = _unit(node)
    snap = _skin_snap(node)[0]
    Q = logic._arr(stroke).copy()
    if len(Q) < 2:
        raise ValueError("a stroke needs two points apart")
    Q[0] = snap(Q[0])
    H, gap = logic.stroke_handles(Q, unit, tol_cm)
    H = np.asarray(H, dtype=float)
    H[0] = Q[0]
    frozen = node.parm(PARM_REGIONS).evalAsGeometry()
    stale_before = (data.regions_stale, list(data.stale_why))
    sel: list[int] = []
    gave_ids: list[int] = []
    owners: list = []
    if frozen is not None and len(frozen.iterPoints()):
        P = np.frombuffer(frozen.pointFloatAttribValuesAsString("P"), np.float32).reshape(-1, 3)
        owners = frozen.pointIntListAttribValues(ATTR_LOCK_OWNERS)
        sel, gave_ids = footprint_owners(P, owners, Q[0], logic.drawn_footprint_cm(width_cm) / unit)
    # its group: the group of the lock that gave it most skin (the user, 2026-11-20; it resolves that group's
    # settings); named drawn_NN
    if group is None:
        group = most_skin_group(data, [owners[i] for i in sel]) or _default_group(data, frozen, Q[0])
    if not name:
        name = logic.lock_name(DRAWN_PREFIX, [x.name for x in data.locks] + [o.name for o in data.orphans])
    lk = data.add_drawn_lock(group, H.tolist(), width_cm, thick_cm, taper, name)
    regions = None
    if frozen is not None and len(frozen.iterPoints()):
        regions = hou.Geometry(frozen)
        pts = regions.points()
        for i in sel:
            pts[i].setAttribValue(ATTR_LOCK_OWNERS, [lk.id])
            pts[i].setAttribValue(config.ATTR_LOCK_OWNER, lk.id)
            if regions.findPointAttrib(ATTR_OWNER_DIST) is not None:
                pts[i].setAttribValue(ATTR_OWNER_DIST, [-1.0])
        # the footprint is given: the regions are as up to date as before the draw
        data.regions_stale, data.stale_why = stale_before
    with hou.undos.group(config.UNDO_SPINE["draw"]):
        if regions is not None:
            node.parm(PARM_REGIONS).set(regions)
        node.parm(config.DATA_PARM).set(data.to_json())
    gave = [data.lock(i).name for i in gave_ids if data.lock(i) is not None]
    msg = f"Drew {lk.name}" + (f"; skin from {', '.join(gave)}" if gave else "") + _gap_text(gap, len(H), tol_cm)
    if regions is None:
        msg += "; no regions yet: Update regions gives it skin"
    return {"id": lk.id, "name": lk.name, "gave": gave, "gave_ids": gave_ids, "gap_cm": float(gap),
            "count": int(len(H)), "message": msg}


def set_drawn(node, lock_ids: Iterable[int], width_cm: float | None = None, thick_cm: float | None = None,
              taper: float | None = None) -> dict:
    """Width, thickness (cm, at the root) and tip taper (0..1) of drawn locks, one undo step (config.UNDO_SPINE
    "drawn"). A new width changes the footprint the lock would get: regions out of date with that reason."""
    data = read_data(node)
    changed = []
    for lid in lock_ids:
        lk = _lock_or_raise(data, lid)
        if not lk.drawn:
            continue
        before = (lk.width_cm, lk.thick_cm, lk.taper)
        if width_cm is not None:
            if width_cm <= 0:
                raise ValueError("a width over 0")
            lk.width_cm = float(width_cm)
        if thick_cm is not None:
            if thick_cm <= 0:
                raise ValueError("a thickness over 0")
            lk.thick_cm = float(thick_cm)
        if taper is not None:
            lk.taper = min(1.0, max(0.0, float(taper)))
        if (lk.width_cm, lk.thick_cm, lk.taper) != before:
            changed.append(lk.id)
            if lk.width_cm != before[0]:
                data.mark_stale(f"{lk.name}: width changed")
    if changed:
        write_data(node, data, config.UNDO_SPINE["drawn"])
    return _spine_result(changed, [], data, "Drawn lock")


def give_back(owners: Sequence[Sequence[int]], gone: set[int]) -> tuple[list[int], list[list[int]]]:
    """Pure: of the frozen region points, (those owned by none but the `gone` locks, every point's owners without
    them). The first need new owners; a shared point just loses the gone locks."""
    freed, kept = [], []
    for i, own in enumerate(owners):
        rest = [o for o in own if o not in gone]
        if len(rest) != len(own) and not rest:
            freed.append(i)
        kept.append(rest)
    return freed, kept


def delete_drawn_locks(node, lock_ids: Iterable[int]) -> dict:
    """Delete drawn locks, ONE undo step "Delete drawn lock" that also gives their skin back (the user,
    2026-11-20): a region point they shared keeps its other owners, one they owned alone goes to the locks the
    rule of Update regions gives it (`_split` on those points only, the deleted locks left out). Their ids are
    never used again. Returns {"locks", "took": [names of the locks that took skin], "took_ids", "message"}."""
    data = read_data(node)
    names = []
    done = []
    stale_before = (data.regions_stale, list(data.stale_why))
    for lid in lock_ids:
        lk = data.lock(int(lid))
        if lk is not None and lk.drawn:
            names.append(lk.name)
            if data.remove_drawn_lock(lk.id):
                done.append(lk.id)
    if not done:
        return {"locks": [], "took": [], "took_ids": [], "message": "Deleted: no drawn lock among these"}
    frozen = node.parm(PARM_REGIONS).evalAsGeometry()
    regions = None
    took: set[int] = set()
    if frozen is not None and len(frozen.iterPoints()):
        regions = hou.Geometry(frozen)
        freed, kept = give_back(regions.pointIntListAttribValues(ATTR_LOCK_OWNERS), set(done))
        new_owners, near = [], []
        if freed:
            _c, new_owners, near, _r = _split(node, data, only=freed)
        pts = regions.points()
        has_dist = regions.findPointAttrib(ATTR_OWNER_DIST) is not None
        for i, own in enumerate(kept):
            if own != list(pts[i].intListAttribValue(ATTR_LOCK_OWNERS)):
                pts[i].setAttribValue(ATTR_LOCK_OWNERS, own)
                pts[i].setAttribValue(config.ATTR_LOCK_OWNER, own[0] if own else config.NO_OWNER)
        for i, own, nm in zip(freed, new_owners, near):
            pts[i].setAttribValue(ATTR_LOCK_OWNERS, list(own))
            pts[i].setAttribValue(config.ATTR_LOCK_OWNER, own[0] if own else config.NO_OWNER)
            if has_dist:
                dist_of = {lid: d for d, lid in nm}
                pts[i].setAttribValue(ATTR_OWNER_DIST, [float(dist_of.get(lid, -1.0)) for lid in own])
            took.update(own)
        data.regions_stale, data.stale_why = stale_before      # the skin is given back: as up to date as before
    with hou.undos.group(config.UNDO_SPINE["delete"]):
        if regions is not None:
            node.parm(PARM_REGIONS).set(regions)
        node.parm(config.DATA_PARM).set(data.to_json())
    took_names = sorted(data.lock(i).name for i in took if data.lock(i) is not None)
    msg = f"Deleted {', '.join(names)}" + (f"; its skin to {', '.join(took_names)}" if took_names else "")
    if regions is None:
        msg += "; no regions yet"
    return {"locks": done, "took": took_names, "took_ids": sorted(took), "message": msg}


def edited_ids(node) -> list[int]:
    """Locks whose control points differ from the measured spine."""
    return read_data(node).edited_locks()


def drawn_ids(node) -> list[int]:
    """Locks drawn on the skin."""
    return [lk.id for lk in read_data(node).locks if lk.drawn]


def scalp_wired(node) -> bool:
    """An animated scalp is wired into input 4 (U2)."""
    return len(node.inputs()) > 3 and node.inputs()[3] is not None


def animated_scalp(node) -> dict:
    """What the drawn locks do in a shot (U2): {"wired", "ok" (they follow it), "anim_points", "rest_points",
    "drawn", "message"} (the panel's line, "" when nothing needs saying). Never an error or a warning on the node:
    unwired or with another point count than the rest scalp they stay at rest. Cooks ANIM_SCALP when wired."""
    drawn = len(drawn_ids(node))
    wired = scalp_wired(node)
    a = r = 0
    if wired:
        try:
            g = _cooked(node, NODE_ANIM_SCALP)
            a, r = int(g.attribValue("anim_points")), int(g.attribValue("rest_points"))
        except (hou.Error, hou.OperationFailed):
            pass
    msg = scalp_text(drawn, wired, a, r)
    return {"wired": wired, "ok": wired and a == r and r > 0, "anim_points": a, "rest_points": r, "drawn": drawn,
            "message": msg}


def spine_record(data: model.GroomData) -> dict:
    """Pure: what publish.json says of the v0.2b edits (grooming_data.json holds them in full)."""
    return {"edited": sorted(lk.name for lk in data.locks if lk.edited),
            "drawn": sorted(lk.name for lk in data.locks if lk.drawn)}


def spines_from_publish(data: model.GroomData, published: model.GroomData) -> tuple[model.GroomData, dict]:
    """Pure: `data` with a publish's control-point edits and drawn locks (its grooming_data.json): an edit goes to
    the lock of the mesh with the same name (its handle count too); a drawn lock comes in with its id when no lock
    here ever had that id (the id seeds its scatter: the same hair), else a new one. Regions are marked out of date.
    Returns (new data, {"edited": names, "drawn": names, "not_found": names})."""
    out = model.GroomData.from_json(data.to_json())
    by_name = {lk.name: lk for lk in out.locks if not lk.drawn}
    got = {"edited": [], "drawn": [], "not_found": []}
    for p in published.locks:
        if p.drawn:
            if any(lk.drawn and lk.name == p.name and lk.curve == p.curve for lk in out.locks):
                continue
            lk = replace(p, curve=list(p.curve), overrides=dict(p.overrides), spine=[])
            if lk.id <= out.id_high or out.lock(lk.id) is not None:
                lk.id = out.next_lock_id()
            if lk.group not in {g.id for g in out.groups}:
                lk.group = out.groups[0].id if out.groups else DEFAULT_GROUP
            out.locks.append(lk)
            out.note_ids()
            got["drawn"].append(lk.name)
        elif p.edited or p.handles is not None:
            lk = by_name.get(p.name)
            if lk is None:
                got["not_found"].append(p.name)
                continue
            lk.spine, lk.handles = list(p.spine), p.handles
            if p.edited:
                got["edited"].append(p.name)
    if got["drawn"] or got["edited"]:
        out.locks.sort(key=lambda x: x.id)
        out.mark_stale("edits from a publish")
    return out, got


def import_spines(node, tool_dir: str) -> dict:
    """A publish's edits and drawn locks (its `_grooming/` folder) into this node, one undo step. Regions out of
    date: Update regions gives the drawn locks their skin (then the hair is the published one)."""
    with open(os.path.join(tool_dir, "grooming_data.json"), encoding="utf-8") as fh:
        published = model.GroomData.from_json(fh.read())
    new, got = spines_from_publish(read_data(node), published)
    if got["drawn"] or got["edited"]:
        write_data(node, new, UNDO_PREFIX + "Edits from a publish")
    return got


def cook_drawn_locks(sop) -> None:
    """Python SOP "drawn_locks" (after spine_edit): every lock drawn on the skin (v0.2b) becomes one more spine,
    shaped like the measured ones (the same point count and attributes), piece -1 (no mesh), `drawn` 1, with its
    own resolved settings (defaults -> group -> lock, `lock_display_attribs`) and its width / thickness / taper.
    The detail attributes the network switches on: `edited_count` (spines the edit moved), `drawn_count`,
    `drawn_group` (the Blast group of the drawn locks' strands). Input 1 the rest scalp (the root on the skin)."""
    import numpy as np
    top = sop.parent()
    geo = sop.geometry()
    data = read_data(top)
    drawn = [lk for lk in data.locks if lk.drawn and len(lk.curve) >= 2]
    flags = geo.primIntAttribValues(config.ATTR_EDITED) if geo.findPrimAttrib(config.ATTR_EDITED) else ()
    edited_ids = [lid for lid, e in zip(geo.primIntAttribValues(config.ATTR_LOCK_ID), flags) if e] if flags else []
    edited = len(edited_ids)
    # edited_group: the Blast group of the edited locks' strands (U4 changed: they ride their spine in a shot)
    for name, value in (("edited_count", edited), ("drawn_count", len(drawn)),
                        ("drawn_group", drawn_group(lk.id for lk in drawn)), ("edited_group", drawn_group(edited_ids))):
        geo.addAttrib(hou.attribType.Global, name, "" if isinstance(value, str) else 0)
        geo.setGlobalAttribValue(name, value)
    if not drawn:
        return
    scalp = sop.inputs()[1].geometry() if len(sop.inputs()) > 1 and sop.inputs()[1] is not None else None
    unit = _unit(top)
    prims = geo.prims()
    n = len(prims[0].vertices()) if prims else int(top.evalParm("spine_points")) + 1
    ids = [lk.id for lk in drawn]
    attrs = lock_display_attribs(data, ids)
    for name, default in (("piece", 0), (ATTR_DRAWN, 0), (config.ATTR_EDITED, 0)):
        if geo.findPrimAttrib(name) is None:
            geo.addAttrib(hou.attribType.Prim, name, default)
    for name, default in (("curveu", 0.0), ("tangentu", (0.0, 0.0, 0.0)), ("lock_axis", (0.0, 0.0, 0.0)),
                          ("lock_minor", (0.0, 0.0, 0.0)), ("lock_width", 0.0), ("lock_thick", 0.0),
                          ("lock_twist", 0.0)):
        if geo.findPointAttrib(name) is None:
            geo.addAttrib(hou.attribType.Point, name, default)
    for k, lk in enumerate(drawn):
        s = data.resolve(lk.id)
        on = nrm = None
        if scalp is not None and len(scalp.iterPrims()):
            hit = scalp.nearestPrim(hou.Vector3(*lk.curve[0]))
            if hit[0] is not None:
                on, nrm = tuple(hit[0].positionAtInterior(hit[1], hit[2])), tuple(hit[0].normal())
        a = drawn_spine_arrays(lk.curve, n, unit, lk.width_cm, lk.thick_cm, lk.taper, s.get("width_mult", 1.0),
                               s.get("thick_mult", 1.0), s.get("twist_add", 0.0), on, nrm)
        pts = geo.createPoints([tuple(p) for p in a["P"]])
        for i, pt in enumerate(pts):
            pt.setAttribValue("curveu", float(a["curveu"][i]))
            pt.setAttribValue("tangentu", tuple(a["tangent"][i]))
            pt.setAttribValue("lock_axis", tuple(a["axis"][i]))
            pt.setAttribValue("lock_minor", tuple(a["minor"][i]))
            pt.setAttribValue("lock_width", float(a["width"][i]))
            pt.setAttribValue("lock_thick", float(a["thick"][i]))
            pt.setAttribValue("lock_twist", float(a["twist"][i]))
        poly = geo.createPolygon(is_closed=False)
        for pt in pts:
            poly.addVertex(pt)
        own: dict[str, Any] = {key: attrs[key][k] for key in attrs}
        own.update({config.ATTR_LOCK_ID: lk.id, "piece": -1, "mesh_name": "", "root": tuple(a["root"]),
                    "direction": tuple(a["direction"]), "length": a["length"], ATTR_DRAWN: 1, config.ATTR_EDITED: 0})
        for key, value in own.items():
            attr = geo.findPrimAttrib(key)
            if attr is None or attr.isArrayType():
                continue
            if isinstance(value, (list, tuple)) and attr.size() != len(value):
                continue
            poly.setAttribValue(attr, value)


def radial_on() -> bool:
    """The viewport's radial menu becomes MONO Grooming while the panel is shown (grooming_workspace)."""
    from apps.houdini import grooming_workspace
    return grooming_workspace.radial_on()


def radial_off() -> bool:
    """The user's radial menu back once no panel is shown (grooming_workspace)."""
    from apps.houdini import grooming_workspace
    return grooming_workspace.radial_off()


__all__ = [
    "radial_on", "radial_off",
    "undo_cache_usage",
    "find_nodes", "create_node", "read_data", "write_data", "write_data_live", "lock_infos", "detect", "split_regions",
    "set_display", "display_state", "selected_lock_ids", "select_locks", "publish_context", "publish",
    "undo", "set_isolate", "isolate_ids", "set_strands", "strand_ids", "frame_locks", "preflight", "geo_stats", "strands_all", "STRANDS_ALL", "cook_display", "set_focus", "focus_ids", "xray_opacity", "set_xray_opacity", "set_drag_preview", "deform_state", "deform_problem", "capture_flag", "set_shot_deform", "set_root_flip",
    "set_excluded",
    # v0.2a density masks (apps/houdini/grooming_masks.py)
    "mask_add", "mask_remove", "mask_move", "mask_set", "mask_fill", "mask_clear", "mask_invert", "mask_values",
    "mask_cover", "mask_dropped",
    "mask_stroke", "mask_problem", "mask_rebake", "set_brush", "brush", "paint_enter", "paint_exit", "paint_layer",
    "import_masks", "masks_from_publish",
    # v0.2b control points and drawn locks (the viewer state B3 and the panel B4)
    "lock_handles", "set_points", "reset_points", "rotate_points", "scale_points", "set_handle_count", "redraw_lock",
    "draw_lock", "set_drawn", "delete_drawn_locks", "edited_ids", "drawn_ids", "scalp_wired", "animated_scalp",
    "import_spines", "spines_from_publish", "spine_record", "NODE_SPINES_MEASURED", "NODE_MESH_CARRIED",
]
