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

SCHEMA = 6      # 2: `masks` (v0.2a); 3: fill layers, folders; 4: only "= D" layers; 5: one 0..1 mask, blend modes;
                # 6: density layers, each with its own number and its own mask stack

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
    """One row of the density layers (v0.2a; config.MASK_MODES has the model). `kind`:
    "base" the automatic groom, always first, one of it; "density" a density layer (`density`, opacity, owner);
    "paint" / "fill" a layer of a density layer's mask (`parent`: that density layer; `mode`, opacity, `value`).
    What a paint layer holds per scalp point (value and coverage) lives on the node's `mask_layers` geometry
    parm under this `id`. Order = place in `GroomData.masks`, bottom first: the base, then each density layer
    followed by its mask layers."""
    id: int
    name: str
    on: bool = True
    mode: str = "normal"         # a mask layer's blend mode, config.MASK_MODES
    opacity: float = 1.0         # 0..1
    scope: str = "all"           # a density layer's owner, config.MASK_SCOPES: "all", "group", "locks"
    group: str = ""              # scope "group": the group id
    locks: list[int] = field(default_factory=list)   # scope "locks": lock ids (kept for missing locks too)
    kind: str = "paint"          # config.MASK_KINDS
    value: float = 1.0           # 0..1. A fill layer's value; a paint layer's where only its coverage is stored
    parent: int | None = None    # a mask layer's density layer
    density: float = config.MASK_DENSITY_DEFAULT   # a density layer's number D, strands / cm2
    # a density layer read from a file of an older test build (schema 2 / 3 / 5): its mask layers blend as that
    # build's 0..1 mask did (`logic.legacy_mask`: black = no hair, white = D, Multiply / Min thin what is below)
    legacy: bool = False

    def applies(self, lock_id: int, group_id: str) -> bool:
        """This density layer is owned by a row that lock is under (whatever `on` says)."""
        if self.scope == "group":
            return group_id == self.group
        if self.scope == "locks":
            return lock_id in self.locks
        return True

    def owner(self) -> tuple:
        """The owner as one value: layers with the same one sit on the same row of the lock tree."""
        if self.scope == "group":
            return ("group", self.group)
        if self.scope == "locks":
            return ("locks", tuple(self.locks))
        return ("all",)


def base_layer() -> MaskLayer:
    """The automatic groom as the bottom density layer: each lock's own Density setting, mask full."""
    return MaskLayer(id=config.MASK_BASE_ID, name="Automatic", kind="base")


def _number(raw, default: float) -> float:
    return float(raw) if isinstance(raw, (int, float)) and not isinstance(raw, bool) else default


def _clean_mask(raw: dict[str, Any]) -> MaskLayer:
    scope = str(raw.get("scope", "all"))
    mode = str(raw.get("mode", "normal"))
    return MaskLayer(
        id=int(raw["id"]), name=str(raw.get("name", "")), on=bool(raw.get("on", True)),
        mode=mode if mode in config.MASK_MODES else "normal",
        opacity=min(1.0, max(0.0, _number(raw.get("opacity"), 1.0))),
        scope=scope if scope in config.MASK_SCOPES else "all",
        group=str(raw.get("group", "")),
        locks=sorted({int(i) for i in raw.get("locks", ())}),
        kind=str(raw.get("kind", "paint")) if raw.get("kind", "paint") in config.MASK_KINDS else "paint",
        value=min(1.0, max(0.0, _number(raw.get("value"), 1.0))),
        parent=int(raw["parent"]) if isinstance(raw.get("parent"), int) and not isinstance(raw.get("parent"), bool)
        else None,
        density=min(config.MASK_DENSITY_MAX, max(0.0, _number(raw.get("density"), config.MASK_DENSITY_DEFAULT))),
        legacy=bool(raw.get("legacy", False)) and raw.get("kind") == "density",
    )


def _normalize(masks: list[MaskLayer]) -> list[MaskLayer]:
    """The list in its one order: the base, then each density layer (in the order given) followed by its mask
    layers (in the order given). A mask layer whose parent is not a density layer of the list is dropped; the
    base is made when it is missing."""
    base = next((m for m in masks if m.kind == "base"), None) or base_layer()
    base.id, base.on, base.opacity, base.parent = config.MASK_BASE_ID, True, 1.0, None
    out = [base]
    for d in masks:
        if d.kind != "density":
            continue
        d.parent = None
        out.append(d)
        out.extend(m for m in masks if m.kind in ("paint", "fill") and m.parent == d.id)
    return out


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
    # density layers and their mask layers, bottom first (v0.2a; `MaskLayer`): always the base first
    masks: list[MaskLayer] = field(default_factory=lambda: [base_layer()])
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

    # ---- density layers (v0.2a): order = place in `masks`, bottom first ----
    def mask(self, layer_id: int) -> MaskLayer | None:
        return next((m for m in self.masks if m.id == layer_id), None)

    def density_layers(self) -> list[MaskLayer]:
        """The density layers the artist made, bottom first (the base is not one of them)."""
        return [m for m in self.masks if m.kind == "density"]

    def mask_layers(self, parent: int) -> list[MaskLayer]:
        """The mask stack of density layer `parent`, bottom first."""
        return [m for m in self.masks if m.kind in ("paint", "fill") and m.parent == parent]

    def has_layers(self) -> bool:
        return any(m.kind != "base" for m in self.masks)

    def add_mask(self, name: str = "", mode: str = "normal", opacity: float = 1.0, scope: str = "all",
                 group: str = "", locks=(), kind: str = "paint", value: float = 1.0,
                 parent: int | None = None, density: float = config.MASK_DENSITY_DEFAULT) -> MaskLayer:
        """A new layer; its id is never one a layer had before. `kind` "density": a density layer on top of the
        stack (`density`, opacity, owner); "paint" / "fill": a mask layer on top of density layer `parent`'s
        mask (`mode`, opacity, a fill layer's `value`)."""
        if kind not in ("density", "paint", "fill"):
            raise ValueError(f"layer kind {kind!r}")
        if kind != "density":
            owner = self.mask(parent) if parent is not None else None
            if owner is None or owner.kind != "density":
                raise ValueError(f"a {kind} layer belongs to a density layer's mask: {parent!r} is not one")
        layer_id = max([self.mask_id_high] + [m.id for m in self.masks]) + 1
        taken = {m.name for m in self.masks}
        if not name:
            word = {"density": "Density", "paint": "Paint", "fill": "Fill"}[kind]
            n = len([m for m in self.masks if m.kind == kind and (kind == "density" or m.parent == parent)]) + 1
            while f"{word} {n}" in taken:
                n += 1
            name = f"{word} {n}"
        layer = _clean_mask({"id": layer_id, "name": name, "mode": mode, "opacity": opacity, "scope": scope,
                             "group": group, "locks": list(locks), "kind": kind, "value": value,
                             "parent": None if kind == "density" else parent, "density": density})
        if kind != "density":
            layer.scope, layer.group, layer.locks = "all", "", []
        self.masks = _normalize(self.masks + [layer])
        self.mask_id_high = layer_id
        return layer

    def remove_mask(self, layer_id: int) -> list[int]:
        """Delete a layer: the ids that went (a density layer goes with its mask layers), [] when there is no
        such layer. The base cannot be deleted."""
        layer = self.mask(layer_id)
        if layer is None:
            return []
        if layer.kind == "base":
            raise ValueError("the automatic layer cannot be deleted")
        gone = [layer_id] + ([m.id for m in self.mask_layers(layer_id)] if layer.kind == "density" else [])
        self.masks = _normalize([m for m in self.masks if m.id not in gone])
        return gone

    def move_mask(self, layer_id: int, index: int, parent: int | None | str = "keep") -> None:
        """Put the layer at place *index* among its like (0 = bottom; past the end = top): a density layer
        among the density layers (the base stays under them all), a mask layer in its density layer's mask,
        or, with `parent`, in another density layer's."""
        layer = self.mask(layer_id)
        if layer is None:
            raise KeyError(layer_id)
        if layer.kind == "base":
            raise ValueError("the automatic layer cannot be moved")
        if layer.kind == "density":
            if parent not in ("keep", None):
                raise ValueError("a density layer is not part of another layer's mask")
            rest = [m for m in self.density_layers() if m.id != layer_id]
            at = max(0, min(int(index), len(rest)))
            order = rest[:at] + [layer] + rest[at:]
            self.masks = _normalize(order + [m for m in self.masks if m.kind in ("paint", "fill")])
            return
        if parent != "keep":
            owner = self.mask(parent) if parent is not None else None
            if owner is None or owner.kind != "density":
                raise ValueError(f"mask layer {parent!r} is not a density layer")
            layer.parent = owner.id
        rest = [m for m in self.mask_layers(layer.parent) if m.id != layer_id]
        at = max(0, min(int(index), len(rest)))
        mine = rest[:at] + [layer] + rest[at:]
        others = [m for m in self.masks if m.kind in ("paint", "fill") and m.parent != layer.parent]
        self.masks = _normalize([m for m in self.masks if m.kind in ("base", "density")] + others + mine)

    def reassign_orphan(self, orphan_id: int, lock_id: int) -> list[str] | None:
        """A missing lock's settings go to lock `lock_id` (usually one Detect marked new: the same hair come
        back under a new id) and the missing lock leaves the list: its overrides, and the density layers it
        owned, which now belong to the lock. Returns the names of those layers, None when either id is
        unknown (nothing changes). The lock keeps its id and name; its match is ok."""
        orphan = next((o for o in self.orphans if o.id == orphan_id), None)
        lk = self.lock(lock_id)
        if orphan is None or lk is None:
            return None
        lk.overrides = dict(orphan.overrides)
        lk.match = "ok"
        self.orphans.remove(orphan)
        return self.reassign_mask_lock(orphan_id, lock_id)

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
            masks=_normalize([_clean_mask(m) for m in raw.get("masks", [])]),
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
    if int(raw.get("schema", 3)) < 6:
        # -> 6: density layers, each with its own number and its own mask stack (config.MASK_MODES has the
        # model). Schemas 2 to 5 were never released (dev files only); `_density_layers` says how each kind of
        # layer comes over. Dropped layers are named in `masks_dropped`, the others in `masks_converted` (the
        # panel and OnLoaded say so; the JSON on the node is rewritten only by the next edit)
        raw = dict(raw)
        keep, dropped, converted, high = _density_layers(raw, int(raw.get("schema", 3)))
        raw["masks"] = keep
        raw["masks_dropped"] = dropped
        raw["masks_converted"] = converted
        raw["mask_id_high"] = high
        raw["schema"] = 6
    return raw


def _owner_density(raw: dict[str, Any], layer: dict[str, Any]) -> float:
    """The Density setting of a layer's owner in stored JSON: the lock's (the first one named), its group's,
    else the groom's."""
    def number(d, fallback):
        v = (d or {}).get("density")
        return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else fallback
    out = number(raw.get("defaults"), BUILTIN_DEFAULTS["density"])
    groups = {str(g.get("id")): g for g in raw.get("groups", [])}
    scope = layer.get("scope", "all")
    if scope == "group":
        return number((groups.get(str(layer.get("group", ""))) or {}).get("overrides"), out)
    if scope == "locks":
        ids = [int(i) for i in layer.get("locks", ())]
        lock = next((lk for lk in raw.get("locks", []) if int(lk.get("id", -1)) in ids), None)
        if lock is not None:
            out = number((groups.get(str(lock.get("group", ""))) or {}).get("overrides"), out)
            return number(lock.get("overrides"), out)
    return out


def _layer_name(m: dict[str, Any]) -> str:
    return str(m.get("name") or m.get("id", "?"))


def _density_layers(raw: dict[str, Any], version: int) -> tuple[list[dict], list[str], list[str], int]:
    """The layers of a schema 2 to 5 file as schema 6 rows: (rows, names dropped, names converted, the highest
    layer id now in use). What a stored layer becomes:
      - "= D strands / cm2" under a painted mask (every schema 4 layer; a schema 3 fill layer in strands / cm2,
        Replace): a density layer of that D, opacity and owner, whose mask is one paint layer holding the
        stored mask (it keeps the old id, so the paint on the node is found). The same result as before.
      - a layer of the 0..1 mask (schema 5; schema 2 / 3 paint layers and factor fills 0..1, read as schema 5
        read them): the layers of one owner become the mask stack of ONE density layer of that owner, marked
        `legacy`, whose D is the owner's Density setting when the file is read. A legacy layer's mask blends by
        the older build's own rule (`logic.legacy_mask`), so it gives what it gave: white the owner's Density,
        black no hair, Multiply / Min / a grey fill the automatic groom thinned (a factor m over unpainted skin
        is exactly a layer of D = 0 with the mask 1 - m: m x the density below). What differs: the older build
        blended the layers of every owner that reach a lock as ONE stack in the list's order, here each
        owner's stack starts on its own and the owners apply all locks, group, lock; Normal, Multiply, Add and
        Subtract give the same either way, a Min or Max layer of a group or lock over skin an all-locks layer
        also painted compares with its own stack only.
      - a folder: gone; its opacity is multiplied into its layers', its eye switches them off.
      - dropped: a factor over 1 and a strands / cm2 layer in another blend mode than Replace (schema 3)."""
    stored = list(raw.get("masks", []))
    high = max([int(raw.get("mask_id_high", -1))] + [int(m["id"]) for m in stored])
    folders = {int(m["id"]): m for m in stored if m.get("kind") == "folder"}
    dropped, converted, rows = [], [], []
    by_owner: dict[tuple, dict] = {}

    def through_folder(m, row):
        folder = folders.get(m.get("parent")) if isinstance(m.get("parent"), int) else None
        if folder is not None:
            row["opacity"] = _number(row.get("opacity"), 1.0) * _number(folder.get("opacity"), 1.0)
            row["on"] = bool(row.get("on", True)) and bool(folder.get("on", True))
        return row

    for m in stored:
        kind = m.get("kind", "paint" if version < 4 else "fill")
        if kind == "folder":
            continue
        absolute = version == 4 or (version < 4 and kind == "fill" and m.get("unit") == "density")
        if absolute:
            if version < 4 and m.get("mode", "replace") != "replace":
                dropped.append(_layer_name(m))
                continue
            high += 1
            rows.append(through_folder(m, {
                "id": high, "kind": "density", "name": _layer_name(m), "on": m.get("on", True),
                "opacity": m.get("opacity", 1.0), "density": m.get("value", config.MASK_DENSITY_DEFAULT),
                "scope": m.get("scope", "all"), "group": m.get("group", ""), "locks": list(m.get("locks", ()))}))
            rows.append({"id": int(m["id"]), "kind": "paint", "name": "Mask", "parent": high, "value": 1.0})
            converted.append(_layer_name(m))
            continue
        row = _carry_mask(m, version) if version < 5 else dict(m)
        if row is None:
            dropped.append(_layer_name(m))
            continue
        key = (row.get("scope", "all"), row.get("group", ""), tuple(sorted(int(i) for i in row.get("locks", ()))))
        owner = by_owner.get(key)
        if owner is None:
            high += 1
            owner = {"id": high, "kind": "density", "name": f"Older build {len(by_owner) + 1}", "on": True,
                     "opacity": 1.0, "density": _owner_density(raw, row), "scope": key[0], "group": key[1],
                     "locks": list(key[2]), "legacy": True}
            by_owner[key] = owner
            rows.append(owner)
        rows.append(through_folder(m, {
            "id": int(row["id"]), "kind": "fill" if row.get("kind") == "fill" else "paint", "name": _layer_name(row),
            "on": row.get("on", True), "mode": row.get("mode", "normal"), "opacity": row.get("opacity", 1.0),
            "value": row.get("value", 1.0), "parent": owner["id"]}))
        converted.append(_layer_name(m))
    return rows, dropped, converted, high


def _carry_mask(raw: dict[str, Any], version: int) -> dict[str, Any] | None:
    """A 0..1 layer of schema 2 or 3 as schema 5 read it, None when it has no meaning as a mask value: a paint
    layer stays (its values were factors, used up to 8: stored values are read clamped to 0..1; "replace" is
    Normal); a fill layer with a factor in 0..1 becomes a paint layer of that one value under the mask it had
    (its stored mask is its coverage). None: a factor over 1."""
    kind = raw.get("kind", "paint")
    out = {k: v for k, v in raw.items() if k != "unit"}
    mode = raw.get("mode", "multiply")
    out["mode"] = "normal" if mode == "replace" else mode
    if kind == "paint":
        return dict(out, kind="paint", value=1.0)
    value = raw.get("value", 1.0)
    if raw.get("unit", "factor") != "factor" or not isinstance(value, (int, float)) or not 0.0 <= value <= 1.0:
        return None
    return dict(out, kind="paint", value=float(value))


def dropped_masks(text: str | None) -> list[str]:
    """Names of the layers a stored `groom_data` holds that this version drops on reading (`migrate`). Empty
    for anything else, unreadable JSON too."""
    return _migration_names(text, "masks_dropped")


def converted_masks(text: str | None) -> list[str]:
    """Names of the layers of an older test build that this version reads as density layers (`migrate`)."""
    return _migration_names(text, "masks_converted")


def _migration_names(text: str | None, key: str) -> list[str]:
    if not text or not text.strip():
        return []
    try:
        raw = json.loads(text)
        return list(migrate(raw).get(key, [])) if int(raw.get("schema", 1)) < SCHEMA else []
    except (ValueError, TypeError, KeyError, AttributeError):
        return []


def _names(names: list[str]) -> str:
    return ", ".join(names[:4]) + (f" and {len(names) - 4} more" if len(names) > 4 else "")


def dropped_text(names: list[str], converted: list[str] | None = None) -> str:
    """What the artist is told when a scene of an older test build was opened: layers dropped, layers read
    as density layers. "" for none."""
    parts = []
    if names:
        parts.append(f"{len(names)} layer{'s' if len(names) != 1 else ''} from an older test build dropped "
                     f"({_names(names)})")
    if converted:
        parts.append(f"{len(converted)} layer{'s' if len(converted) != 1 else ''} from an older test build "
                     f"{'are' if len(converted) != 1 else 'is'} now in density layers ({_names(converted)}): "
                     'a "= D" layer became a density layer of D under its mask; 0..1 mask layers are kept in '
                     '"Older build" layers that blend as before (white = the Density setting, black = no hair, '
                     "Multiply and Min thin the automatic groom)")
    return "; ".join(parts)


__all__ = [
    "SCHEMA", "BUILTIN_DEFAULTS", "SETTING_KEYS",
    "Group", "Lock", "Orphan", "MaskLayer", "GroomData", "migrate", "dropped_masks", "converted_masks",
    "dropped_text", "base_layer",
]
