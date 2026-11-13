"""
Data model of MONO Grooming: what the user set, stored as JSON in the node's `groom_data` parm.

Measured lock shape (width, thickness, twist, length) lives on the geometry, not here; this module
only holds settings, groups, ids and names, and how settings resolve for a lock. No `hou`.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any

from tools.fx.grooming import config

SCHEMA = 4      # 2: `masks` (v0.2a density mask layers); 3: fill layers, folders; 4: only "= D" fill layers

# Built-in defaults: the bottom of the resolution chain (defaults -> data.defaults -> group -> lock).
BUILTIN_DEFAULTS: dict[str, float] = {
    "density": 150.0,     # strands per cm2
    "width_mult": 1.0,    # x measured lock width
    "thick_mult": 1.0,    # x measured lock thickness
    "twist_add": 0.0,     # + measured twist, radians
    "clump": 0.2,         # 0..1
    "length_mult": 1.0,   # x measured length
    "frizz": 0.0,         # 0..1
    "root_skin": 3.0,     # cm of the spine bent down to the skin, only where the root floats (ROOT_GAP_CM)
}
SETTING_KEYS: tuple[str, ...] = tuple(BUILTIN_DEFAULTS)


def _clean_overrides(raw: dict[str, Any] | None) -> dict[str, float]:
    """Keep only known keys with numeric values; unknown keys from a newer schema are dropped."""
    out: dict[str, float] = {}
    for k, v in (raw or {}).items():
        if k in BUILTIN_DEFAULTS and isinstance(v, (int, float)) and not isinstance(v, bool):
            out[k] = float(v)
    return out


@dataclass
class Group:
    id: str
    name: str
    color: tuple[float, float, float] = (0.6, 0.6, 0.6)
    overrides: dict[str, float] = field(default_factory=dict)
    visible: bool = True
    display: str | None = None  # None = follow the node's display mode


@dataclass
class Lock:
    id: int
    name: str
    group: str
    source: str = "mesh"        # "mesh" (detected from the hair mesh); "drawn" arrives in v0.2
    root: tuple[float, float, float] = (0.0, 0.0, 0.0)  # root position at detection, for re-import matching
    length: float = 0.0          # measured length at detection, for re-import matching
    direction: tuple[float, float, float] | None = None  # unit root -> tip at detection, for shape matching
    overrides: dict[str, float] = field(default_factory=dict)
    visible: bool = True         # its own eye; a hidden group hides it too (`shown`), this is kept
    display: str | None = None
    match: str = "ok"            # "ok" | "unsure" | "new" after a re-import
    root_flip: bool = False      # the root is the mesh piece's other end (Detect takes the one nearer the scalp)
    excluded: bool = False       # the piece grows no hair (an accessory, a floating strand); guide and mesh stay

    def shown(self, group: "Group | None") -> bool:
        """Drawn in the viewport: its own eye and its group's (the group wins, the lock's own state stays)."""
        return self.visible and (group is None or group.visible)


@dataclass
class Orphan:
    """A lock that disappeared on re-import, kept with its settings until reassigned or deleted."""
    id: int
    name: str
    group: str
    overrides: dict[str, float] = field(default_factory=dict)
    root_flip: bool = False
    excluded: bool = False


@dataclass
class MaskLayer:
    """One density layer (v0.2a): a fill layer "= `value` strands / cm2", or a folder of them. What is
    painted (its mask per scalp point: white where it applies, black where the automatic groom stays) lives
    on the node's `mask_layers` geometry parm under this `id`; here only what the panel's layer row shows.
    The layer's order is its place in `GroomData.masks`, bottom first."""
    id: int
    name: str
    on: bool = True
    opacity: float = 1.0         # 0..1
    scope: str = "all"           # the owner, config.MASK_SCOPES: "all", "group" (`group`), "locks" (`locks`)
    group: str = ""              # scope "group": the group id
    locks: list[int] = field(default_factory=list)   # scope "locks": lock ids (kept for missing locks too)
    kind: str = "fill"           # config.MASK_KINDS: "fill" (a density and a mask), "folder"
    value: float = config.MASK_DENSITY_DEFAULT   # a fill layer's density, strands / cm2, where its mask is white
    parent: int | None = None    # the folder this layer is in (one level: a folder is never in a folder)

    def applies(self, lock_id: int, group_id: str) -> bool:
        """This layer changes the density of that lock (whatever `on` says)."""
        if self.scope == "group":
            return group_id == self.group
        if self.scope == "locks":
            return lock_id in self.locks
        return True


def _number(raw, default: float) -> float:
    return float(raw) if isinstance(raw, (int, float)) and not isinstance(raw, bool) else default


def _clean_mask(raw: dict[str, Any]) -> MaskLayer:
    scope = str(raw.get("scope", "all"))
    return MaskLayer(
        id=int(raw["id"]), name=str(raw.get("name", "")), on=bool(raw.get("on", True)),
        opacity=min(1.0, max(0.0, _number(raw.get("opacity"), 1.0))),
        scope=scope if scope in config.MASK_SCOPES else "all",
        group=str(raw.get("group", "")),
        locks=sorted({int(i) for i in raw.get("locks", ())}),
        kind=str(raw.get("kind", "fill")) if raw.get("kind", "fill") in config.MASK_KINDS else "fill",
        value=min(config.MASK_DENSITY_MAX, max(0.0, _number(raw.get("value"), config.MASK_DENSITY_DEFAULT))),
        parent=int(raw["parent"]) if isinstance(raw.get("parent"), int) and not isinstance(raw.get("parent"), bool)
        else None,
    )


def _clean_parents(masks: list[MaskLayer]) -> list[MaskLayer]:
    """A parent that is not a folder of this list (or a folder's own parent) is dropped."""
    folders = {m.id for m in masks if m.kind == "folder"}
    for m in masks:
        if m.parent is not None and (m.parent not in folders or m.kind == "folder"):
            m.parent = None
    return masks


STALE_WHY_KEPT = 6   # reasons the panel lists for regions out of date


@dataclass
class GroomData:
    asset: str = ""
    defaults: dict[str, float] = field(default_factory=dict)
    groups: list[Group] = field(default_factory=list)
    locks: list[Lock] = field(default_factory=list)
    orphans: list[Orphan] = field(default_factory=list)
    regions_stale: bool = False  # set when locks change after the last region split
    stale_why: list[str] = field(default_factory=list)   # what changed since (the panel says it)
    id_high: int = 0             # highest lock id ever given: deleting an orphan never frees its id
    masks: list[MaskLayer] = field(default_factory=list)   # density mask layers, bottom first (v0.2a)
    mask_id_high: int = -1       # highest mask layer id ever given: a deleted layer's attributes are never reused
    schema: int = SCHEMA

    # ---- regions out of date ----
    def mark_stale(self, why: str) -> None:
        """Regions out of date because of *why* ("hair_back_03 root flipped"); the last few are kept."""
        self.regions_stale = True
        if why and why not in self.stale_why:
            self.stale_why = (self.stale_why + [why])[-STALE_WHY_KEPT:]

    def clear_stale(self) -> None:
        self.regions_stale = False
        self.stale_why = []

    # ---- lookup ----
    def group(self, group_id: str) -> Group | None:
        return next((g for g in self.groups if g.id == group_id), None)

    def lock(self, lock_id: int) -> Lock | None:
        return next((lk for lk in self.locks if lk.id == lock_id), None)

    def shown(self, lock_id: int) -> bool:
        """The lock is drawn: neither it nor its group is hidden."""
        lk = self.lock(lock_id)
        return lk is not None and lk.shown(self.group(lk.group))

    def next_lock_id(self) -> int:
        """Never reuses an id, even of a deleted orphan: frozen regions and earlier publishes may still
        name it."""
        used = [lk.id for lk in self.locks] + [o.id for o in self.orphans] + [self.id_high]
        return max(used) + 1

    def note_ids(self) -> None:
        """Raise `id_high` to the ids in use; called whenever locks are added."""
        self.id_high = max([self.id_high] + [lk.id for lk in self.locks] + [o.id for o in self.orphans])

    # ---- density mask layers (v0.2a): order = place in `masks`, bottom first ----
    def mask(self, layer_id: int) -> MaskLayer | None:
        return next((m for m in self.masks if m.id == layer_id), None)

    def add_mask(self, name: str = "", value: float = config.MASK_DENSITY_DEFAULT, opacity: float = 1.0,
                 scope: str = "all", group: str = "", locks=(), kind: str = "fill",
                 parent: int | None = None) -> MaskLayer:
        """A new layer on top of the stack; its id is never one a layer had before."""
        layer_id = max([self.mask_id_high] + [m.id for m in self.masks]) + 1
        taken = {m.name for m in self.masks}
        if not name:
            word = "Folder" if kind == "folder" else "Layer"
            n = len([m for m in self.masks if (m.kind == "folder") == (kind == "folder")]) + 1
            while f"{word} {n}" in taken:
                n += 1
            name = f"{word} {n}"
        layer = _clean_mask({"id": layer_id, "name": name, "opacity": opacity, "scope": scope,
                             "group": group, "locks": list(locks), "kind": kind, "value": value})
        self.masks.append(layer)
        self.mask_id_high = layer_id
        if parent is not None:
            self.set_mask_parent(layer_id, parent)
        return layer

    def set_mask_parent(self, layer_id: int, parent: int | None) -> None:
        """Put a layer into a folder (None: out of any). One level: a folder cannot go into a folder, and
        only a folder holds layers."""
        layer = self.mask(layer_id)
        if layer is None:
            raise KeyError(layer_id)
        if parent is not None:
            folder = self.mask(parent)
            if folder is None or folder.kind != "folder":
                raise ValueError(f"mask layer {parent} is not a folder")
            if layer.kind == "folder":
                raise ValueError("a folder cannot be put into a folder")
        layer.parent = parent

    def remove_mask(self, layer_id: int) -> bool:
        """Delete a layer. A folder's layers stay, out of it (deleting a folder never deletes paint)."""
        n = len(self.masks)
        self.masks = [m for m in self.masks if m.id != layer_id]
        for m in self.masks:
            if m.parent == layer_id:
                m.parent = None
        return len(self.masks) != n

    def move_mask(self, layer_id: int, index: int) -> None:
        """Put the layer at place *index* of the stack (0 = bottom; past the end = top)."""
        layer = self.mask(layer_id)
        if layer is None:
            raise KeyError(layer_id)
        rest = [m for m in self.masks if m.id != layer_id]
        at = max(0, min(int(index), len(rest)))
        self.masks = rest[:at] + [layer] + rest[at:]

    def reassign_mask_lock(self, old_id: int, new_id: int) -> list[str]:
        """Layers owned by lock `old_id` (a missing lock) now belong to `new_id`: the names of those layers.
        A layer that already names the new lock just loses the old id."""
        moved = []
        for m in self.masks:
            if old_id in m.locks:
                m.locks = sorted((set(m.locks) - {old_id}) | {new_id})
                moved.append(m.name)
        return moved

    # ---- settings ----
    def resolve(self, lock_id: int) -> dict[str, float]:
        """Effective settings of a lock: built-ins, then data defaults, then its group, then itself."""
        lk = self.lock(lock_id)
        if lk is None:
            raise KeyError(lock_id)
        out = dict(BUILTIN_DEFAULTS)
        out.update(self.defaults)
        g = self.group(lk.group)
        if g is not None:
            out.update(g.overrides)
        out.update(lk.overrides)
        return out

    def source_of(self, lock_id: int, key: str) -> str:
        """Where a lock's value for `key` comes from: "lock", "group", "defaults" or "builtin"."""
        lk = self.lock(lock_id)
        if lk is None:
            raise KeyError(lock_id)
        if key in lk.overrides:
            return "lock"
        g = self.group(lk.group)
        if g is not None and key in g.overrides:
            return "group"
        if key in self.defaults:
            return "defaults"
        return "builtin"

    # ---- tree order: the order of `groups` and of `locks` (within a group); changes nothing in the hair ----
    def move_locks(self, ids, group: str, before: int | None = None) -> None:
        """Put locks *ids* (keeping their order) into *group*, before lock *before* of that group, or at
        the group's end when *before* is None or not in it."""
        wanted = set(ids)
        moving = [lk for lk in self.locks if lk.id in wanted]
        rest = [lk for lk in self.locks if lk.id not in wanted]
        for lk in moving:
            lk.group = group
        at = next((i for i, lk in enumerate(rest) if lk.id == before and lk.group == group), None)
        if at is None:
            members = [i for i, lk in enumerate(rest) if lk.group == group]
            at = members[-1] + 1 if members else len(rest)
        self.locks = rest[:at] + moving + rest[at:]

    def move_group(self, group_id: str, before: str | None = None) -> None:
        """Put group *group_id* before group *before* (None or unknown = last)."""
        g = self.group(group_id)
        if g is None:
            raise KeyError(group_id)
        rest = [x for x in self.groups if x.id != group_id]
        at = next((i for i, x in enumerate(rest) if x.id == before), len(rest))
        self.groups = rest[:at] + [g] + rest[at:]

    # ---- (de)serialise ----
    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, sort_keys=True, indent=1)

    @classmethod
    def from_json(cls, text: str | None) -> "GroomData":
        if not text or not text.strip():
            return cls()
        raw = migrate(json.loads(text))
        return cls(
            asset=str(raw.get("asset", "")),
            defaults=_clean_overrides(raw.get("defaults")),
            groups=[
                Group(
                    id=str(g["id"]), name=str(g.get("name", g["id"])),
                    color=tuple(float(c) for c in g.get("color", (0.6, 0.6, 0.6)))[:3],  # type: ignore[arg-type]
                    overrides=_clean_overrides(g.get("overrides")),
                    visible=bool(g.get("visible", True)), display=g.get("display"),
                )
                for g in raw.get("groups", [])
            ],
            locks=[
                Lock(
                    id=int(lk["id"]), name=str(lk.get("name", "")), group=str(lk.get("group", "")),
                    source=str(lk.get("source", "mesh")),
                    root=tuple(float(c) for c in lk.get("root", (0.0, 0.0, 0.0)))[:3],  # type: ignore[arg-type]
                    length=float(lk.get("length", 0.0)),
                    direction=(tuple(float(c) for c in lk["direction"])[:3]  # type: ignore[arg-type]
                               if lk.get("direction") else None),
                    overrides=_clean_overrides(lk.get("overrides")),
                    visible=bool(lk.get("visible", True)), display=lk.get("display"),
                    match=str(lk.get("match", "ok")),
                    root_flip=bool(lk.get("root_flip", False)), excluded=bool(lk.get("excluded", False)),
                )
                for lk in raw.get("locks", [])
            ],
            orphans=[
                Orphan(id=int(o["id"]), name=str(o.get("name", "")), group=str(o.get("group", "")),
                       overrides=_clean_overrides(o.get("overrides")),
                       root_flip=bool(o.get("root_flip", False)), excluded=bool(o.get("excluded", False)))
                for o in raw.get("orphans", [])
            ],
            regions_stale=bool(raw.get("regions_stale", False)),
            stale_why=[str(w) for w in raw.get("stale_why", [])][-STALE_WHY_KEPT:],
            id_high=int(raw.get("id_high", 0)),
            masks=_clean_parents([_clean_mask(m) for m in raw.get("masks", [])]),
            mask_id_high=max([int(raw.get("mask_id_high", -1))] + [int(m["id"]) for m in raw.get("masks", [])]),
            schema=SCHEMA,
        )


def migrate(raw: dict[str, Any]) -> dict[str, Any]:
    """Bring older JSON up to SCHEMA. A newer schema than this code knows is refused, never guessed."""
    version = int(raw.get("schema", 1))
    if version > SCHEMA:
        raise ValueError(f"groom_data schema {version} is newer than this tool ({SCHEMA}); update MonoFX Suite")
    if version < 2:
        # v0.1 -> v0.2a: density mask layers. A v0.1 scene has none, so nothing in its hair changes; the
        # JSON on the node is rewritten only by the next edit
        raw = dict(raw)
        raw.setdefault("masks", [])
        raw.setdefault("mask_id_high", -1)
        raw["schema"] = 2
    if int(raw.get("schema", 2)) < 3:
        # 2 -> 3: the layers of the first v0.2a build held a value painted per point ("paint" layers)
        raw = dict(raw)
        raw["masks"] = [dict(m, kind=m.get("kind", "paint")) for m in raw.get("masks", [])]
        raw["schema"] = 3
    if int(raw.get("schema", 3)) < 4:
        # 3 -> 4: one kind of layer, "= D strands / cm2" (the user, 2026-11-13). Schema 2 and 3 were never
        # released: their multiply / add / subtract / min / max layers, factor layers and paint layers are
        # dropped, by name in `masks_dropped` (the panel and OnLoaded say so; the JSON on the node is
        # rewritten only by the next edit). Folders and "= D" layers stay as they are
        raw = dict(raw)
        keep, dropped = [], []
        for m in raw.get("masks", []):
            (keep if _is_density_layer(m) else dropped).append(m)
        raw["masks"] = [{k: v for k, v in m.items() if k not in ("mode", "unit")} for m in keep]
        raw["masks_dropped"] = [str(m.get("name") or m.get("id", "?")) for m in dropped]
        # a dropped layer's id is never given again: its mask may still lie in `mask_layers`
        raw["mask_id_high"] = max([int(raw.get("mask_id_high", -1))] + [int(m["id"]) for m in keep + dropped])
        raw["schema"] = 4
    return raw


def _is_density_layer(raw: dict[str, Any]) -> bool:
    """A schema 3 layer that schema 4 still has: a folder, or a fill layer "= D strands / cm2"."""
    kind = raw.get("kind", "fill")
    return kind == "folder" or (kind == "fill" and raw.get("mode") == "replace" and raw.get("unit") == "density")


def dropped_masks(text: str | None) -> list[str]:
    """Names of the layers a stored `groom_data` holds that this version drops on reading (`migrate`): layers
    of a removed kind or blend mode from an unreleased build. Empty for anything else, unreadable JSON too."""
    if not text or not text.strip():
        return []
    try:
        raw = json.loads(text)
        return list(migrate(raw).get("masks_dropped", [])) if int(raw.get("schema", 1)) < SCHEMA else []
    except (ValueError, TypeError, KeyError, AttributeError):
        return []


def dropped_text(names: list[str]) -> str:
    """What the artist is told when layers were dropped on opening, "" for none."""
    if not names:
        return ""
    shown = ", ".join(names[:4]) + (f" and {len(names) - 4} more" if len(names) > 4 else "")
    return (f"{len(names)} density layer{'s' if len(names) != 1 else ''} from an older test build dropped "
            f"({shown}): only \"= D strands / cm2\" layers are kept")


__all__ = [
    "SCHEMA", "BUILTIN_DEFAULTS", "SETTING_KEYS",
    "Group", "Lock", "Orphan", "MaskLayer", "GroomData", "migrate", "dropped_masks", "dropped_text",
]
