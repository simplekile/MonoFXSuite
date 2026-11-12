"""
MONO Grooming panel controller: the panel's actions on one MONO Grooming node, through the adapter only.

The controller holds no copy of the node's data: every action reads `adapter.read_data(node)`, changes
it and stores it back with one `adapter.write_data(node, data, label)` (one undo step). It never imports
Qt or `hou`, so tests drive it with a fake adapter and a recording view. `run()` is the Houdini entry:
it imports `apps.houdini.grooming_adapter` and the Qt panel only then.

What the controller calls on its view (ui.GroomingUI, or a fake in tests):
  show_node(path, asset), show_tree(rows), set_selection(selection), show_properties(props),
  set_message(text, error=False), set_regions_stale(stale), set_display_state(mode, color_by),
  set_publish_version(version, note), set_isolate(text), set_publish_warning(text), set_xray_on(on)
"""

from __future__ import annotations

import contextlib

import math
from typing import Any, Callable

from tools.fx.grooming import config, logic, model

# How often the panel reads the viewport selection and the node's data (ms)
SELECTION_POLL_MS = 400

# Slider range of each setting (the value itself is not clamped: a typed value outside stays)
SETTING_RANGES: dict[str, tuple[float, float]] = {
    "density": (0.0, 400.0),
    "width_mult": (0.0, 3.0),
    "thick_mult": (0.0, 3.0),
    "twist_add": (-6.2832, 6.2832),
    "clump": (0.0, 1.0),
    "length_mult": (0.0, 2.0),
    "frizz": (0.0, 1.0),
}
# Names as Houdini uses them: Hair Generate's "Thickness" (and the `width` attribute) is one strand's, so
# the lock's measured cross-section is "Lock width" / "Lock thickness", never plain Width / Thickness.
SETTING_LABELS: dict[str, str] = {
    "density": "Density",
    "width_mult": "Lock width ×",
    "thick_mult": "Lock thickness ×",
    "twist_add": "Twist +",
    "clump": "Clump",
    "length_mult": "Length ×",
    "frizz": "Frizz",
}
SETTING_UNITS: dict[str, str] = {"density": "/cm²", "twist_add": "°"}
# Stored value x scale = the value the panel shows (twist is stored in radians, shown in degrees like the
# measured twist)
SETTING_SCALE: dict[str, float] = {"twist_add": 180.0 / math.pi}
SETTING_TIPS: dict[str, str] = {
    "density": "Strands per cm² of skin (Hair Generate › Density); stacked locks share it",
    "width_mult": "Multiplies the lock's measured width (its hair mesh piece). Not the strand thickness",
    "thick_mult": "Multiplies the lock's measured thickness (the ribbon's depth). Not Hair Generate's strand "
                  "Thickness",
    "twist_add": "Degrees added to the lock's measured twist along its length",
    "clump": "Hair Clump › Blend: 0 no clumping, 1 strands fully gathered into clumps",
    "length_mult": "Multiplies the strands' length",
    "frizz": "Frizz amount (as Guide Process › Frizz): random waves along each strand",
}

DISPLAY_LABELS: dict[str, str] = {
    "mesh": "Mesh", "guide": "Guides", "hair_preview": "Hair preview", "hair": "Hair",
}
COLOR_BY_LABELS: dict[str, str] = {"lock": "Lock", "group": "Group"}
# Match states as the panel words them ("unsure" is the data's word)
MATCH_LABELS: dict[str, str] = {"unsure": "check match", "new": "new", "ok": "ok"}

# The defaults level is the tree's root group: every group sits inside it
ALL_LOCKS = "All locks"
SOURCE_NAMES: dict[str, str] = {"defaults": ALL_LOCKS, "builtin": "tool default", "mixed": "mixed"}

# Keys of the panel, listed while nothing is selected
SHORTCUTS: tuple[tuple[str, str], ...] = (
    ("Click a lock", "Edit it: it shows its real strands, the others x-ray"),
    ("X", "X-ray off / on: see the selection inside the real groom"),
    ("I", "Isolate the selection (again: show all)"),
    ("Esc", "Leave isolate, else deselect: the whole groom as strands"),
    ("Ctrl+Z / Ctrl+Shift+Z", "Undo / redo"),
    ("Shift / Ctrl click", "Select several locks"),
)

# Selection kinds: what the properties column edits
SEL_NONE, SEL_DEFAULTS, SEL_GROUP, SEL_LOCKS, SEL_ORPHAN = "none", "defaults", "group", "locks", "orphan"

ORPHANS_ROW = "__orphans__"

# Drop positions in the tree (the view maps Qt's indicator to these)
DROP_ABOVE, DROP_BELOW, DROP_ON = "above", "below", "on"

# Scene units -> cm when neither the adapter nor the node says (scenes in metres)
DEFAULT_UNIT_CM = 100.0


def lock_color(lock_id: int) -> tuple[float, float, float]:
    """Colour of a lock when colouring by lock: logic.lock_color, the viewport's colour too."""
    return logic.lock_color(lock_id)


def report_text(counts: dict[str, int]) -> str:
    """One line for a DetectReport's counts."""
    total = counts.get("ok", 0) + counts.get("unsure", 0) + counts.get("new", 0)
    parts = [f"{counts.get('ok', 0)} ok"]
    if counts.get("unsure"):
        parts.append(f"{counts['unsure']} to check (Confirm all, or right click › Confirm match)")
    if counts.get("new"):
        parts.append(f"{counts['new']} new")
    if counts.get("orphaned"):
        parts.append(f"{counts['orphaned']} missing (kept with their settings)")
    return f"Detect locks: {total} lock{'s' if total != 1 else ''} · " + " · ".join(parts)


def _fmt(value: float) -> str:
    return f"{value:.3g}" if abs(value) < 1000 else f"{value:,.0f}"


def _cm(value: float) -> str:
    """A length in cm: one decimal from 10 cm, two below (a 4 mm fringe lock still reads)."""
    return f"{value:.1f} cm" if abs(value) >= 10 else f"{value:.2f} cm"


def _names(names: list[str], most: int = 3) -> str:
    """'a, b, c' or 'a, b, c +4'."""
    shown = ", ".join(names[:most])
    return shown + (f" +{len(names) - most}" if len(names) > most else "")


class GroomController:
    """The panel's actions on one node. *view* gets what to show (see the module docstring)."""

    def __init__(self, adapter: Any, view: Any, node: Any = None) -> None:
        self.adapter = adapter
        self.view = view
        self.node = node
        self.selection: tuple[str, tuple] = (SEL_NONE, ())
        self.display_mode = "guide"
        self.color_by = "lock"
        self._last_json: str | None = None
        self._viewport_ids: list[int] = []
        self._infos: dict[int, logic.LockInfo] = {}
        self._node_lost = False
        self._data: model.GroomData | None = None   # last data shown: drag feedback reads it, never writes
        self.isolated: tuple[int, ...] | None = None  # lock ids shown alone in the viewport; None = all
        self.xray = True        # selected: the others see-through bands (False: every lock as strands)
        self._solo_before: dict | None = None   # eyes before an Alt+click, put back by the next one
        self._publish_armed: tuple | None = None      # what the publish warning named; a 2nd click goes on
        self.unit_cm = DEFAULT_UNIT_CM
        self._drag_origin: str | None = None   # groom_data before a slider drag (preview_value)
        self._infos_for: str | None = None    # _infos_key of the data lock_infos was read for
        self._drag_preview = True             # dragged locks grow light (adapter.set_drag_preview)
        self._drag_origin_new = False
        self._drag_warned = False
        self._drag_factor: float | None = None   # the strand fraction a drag shows (logic.drag_factor)
        if node is not None:
            self.set_node(node)

    # ------------------------------------------------------------------
    # Node and reading
    # ------------------------------------------------------------------
    def set_node(self, node: Any) -> None:
        self.focus_off()
        self.node = node
        self._node_lost = False
        self.selection = (SEL_NONE, ())
        self._viewport_ids = []
        self._publish_armed = None
        self.unit_cm = self._read_unit_cm()
        state = getattr(self.adapter, "display_state", None)  # optional: the node's own display parms
        if state is not None:
            try:
                self.display_mode, self.color_by = state(node)
            except Exception:
                pass
        self.refresh()
        self.view.set_display_state(self.display_mode, self.color_by)
        if hasattr(self.view, "set_deform_state"):
            self.view.set_deform_state(*self.deform_state())
        self.refresh_publish_version()
        level = getattr(self.view, "xray_level", None)
        if level is not None:
            self.set_xray(level())

    def set_xray(self, level: str) -> bool:
        """X-ray strength of the locks out of focus (the artist's own choice, kept by the panel)."""
        call = getattr(self.adapter, "set_xray_opacity", None)
        alpha = config.XRAY_LEVELS.get(level)
        if call is None or alpha is None or self.node is None:
            return False
        return self._run("X-ray", lambda: call(self.node, alpha) or True) is not None

    def data(self) -> model.GroomData:
        return self.adapter.read_data(self.node)

    def _read_unit_cm(self) -> float:
        """cm per scene unit: `adapter.unit_cm(node)` when it has it, else the node's `unit_cm` parm."""
        for read in (getattr(self.adapter, "unit_cm", None), lambda n: n.evalParm("unit_cm")):
            if read is None:
                continue
            try:
                value = float(read(self.node))
            except Exception:
                continue
            if value > 0:
                return value
        return DEFAULT_UNIT_CM

    def _read_isolate(self) -> tuple[int, ...] | None:
        read = getattr(self.adapter, "isolate_ids", None)  # session 009's adapter; absent = never isolated
        if read is None or self.node is None:
            return None
        try:
            ids = read(self.node)
        except Exception:
            return None
        return tuple(sorted(ids)) if ids else None

    def node_path(self) -> str:
        path = getattr(self.node, "path", None)
        return path() if callable(path) else str(self.node or "")

    def refresh(self, data: model.GroomData | None = None) -> None:
        """Show the node again: tree, properties, warnings. Measured values are read from the cook."""
        if self.node is None:
            return
        data = data or self.data()
        self._last_json = data.to_json()
        self._data = data
        self.isolated = self._read_isolate()
        key = self._infos_key(data)
        if key != self._infos_for:      # an eye, a display or the order measures nothing new
            try:
                self._infos = {info.id: info for info in self.adapter.lock_infos(self.node)}
                self._infos_for = key
            except Exception:
                self._infos, self._infos_for = {}, None
        self._drop_gone_selection(data)
        self.view.show_node(self.node_path(), data.asset)
        self.view.show_tree(self.tree_rows(data))
        self.view.set_selection(self.selection)
        self.view.show_properties(self.properties(data))
        try:
            self.view.set_regions_stale(data.regions_stale, data.stale_why)
        except TypeError:   # a view without the reasons
            self.view.set_regions_stale(data.regions_stale)
        if hasattr(self.view, "set_review"):
            self.view.set_review(*self.review_counts(data))
        self.view.set_isolate(self.isolate_text(data))
        if hasattr(self.adapter, "set_focus"):
            # an eye or a group's eye may have hidden or shown the selection: focus and strands only on
            # drawn locks (the adapter writes only when they change)
            self._sync_viewport(data, quiet=True)
        if self._publish_armed is not None and self._publish_armed != self._unseen(data):
            self._publish_armed = None  # what was hidden changed: the warning no longer says what is true
            self.view.set_publish_warning("")

    @staticmethod
    def _infos_key(data: model.GroomData) -> str:
        """What the measured values (lock_infos) depend on: the data without eyes, displays and order.
        Reading them costs a cook of the spines and regions, so a hide or a show does not."""
        d = model.GroomData.from_json(data.to_json())
        for row in [*d.locks, *d.groups]:
            row.visible, row.display = True, None
        d.locks.sort(key=lambda lk: lk.id)
        d.groups.sort(key=lambda g: g.id)
        return d.to_json()

    def _drop_gone_selection(self, data: model.GroomData) -> None:
        kind, ids = self.selection
        if kind == SEL_LOCKS:
            kept = tuple(i for i in ids if data.lock(i) is not None)
            self.selection = (SEL_LOCKS, kept) if kept else (SEL_NONE, ())
        elif kind == SEL_GROUP and not any(lk.group == ids[0] for lk in data.locks) and data.group(ids[0]) is None:
            self.selection = (SEL_NONE, ())
        elif kind == SEL_ORPHAN and not any(o.id == ids[0] for o in data.orphans):
            self.selection = (SEL_NONE, ())

    # ------------------------------------------------------------------
    # What the view shows
    # ------------------------------------------------------------------
    def row_color(self, data: model.GroomData, lock: model.Lock) -> tuple[float, float, float]:
        if self.color_by == "group":
            g = data.group(lock.group)
            return tuple(g.color) if g else (0.6, 0.6, 0.6)  # type: ignore[return-value]
        return lock_color(lock.id)

    def tree_rows(self, data: model.GroomData) -> list[dict]:
        """All locks (the defaults: the view shows the groups inside it), then group › lock rows, then
        Missing locks. Locks of a group the data does not list still get a row (named by the group id),
        so no lock is out of sight."""
        rows: list[dict] = [{"kind": SEL_DEFAULTS, "id": "", "name": ALL_LOCKS, "badges":
                             ["edited"] if data.defaults else [],
                             "meta": "Settings every lock takes, unless its group or the lock sets its own"}]
        isolated = set(self.isolated) if self.isolated else None
        for gid in self._group_order(data):
            g = data.group(gid)
            group_visible = g.visible if g else True
            locks = [lk for lk in data.locks if lk.group == gid]
            children = [{
                "kind": SEL_LOCKS, "id": lk.id, "name": lk.name or f"lock {lk.id}",
                "color": self.row_color(data, lk), "visible": lk.visible, "display": lk.display,
                # The group wins: a shown lock of a hidden group is hidden, its own state kept for later
                "hidden_by_group": not group_visible,
                "isolated_out": isolated is not None and lk.id not in isolated,
                "isolated_in": isolated is not None and lk.id in isolated,
                "root_flip": lk.root_flip, "excluded": lk.excluded,
                # "new" only while a missing lock's settings could go to it; "unsure" always asks
                "badges": (["edited"] if lk.overrides else []) + ([lk.match] if lk.match == "unsure" or
                                                                   (lk.match == "new" and data.orphans) else []),
            } for lk in locks]
            badges = ["edited"] if g and g.overrides else []
            if any("unsure" in c["badges"] for c in children):
                badges.append("unsure")
            if any("new" in c["badges"] for c in children):
                badges.append("new")
            rows.append({
                "kind": SEL_GROUP, "id": gid, "name": (g.name if g else gid) or "(no group)",
                "color": tuple(g.color) if g else (0.6, 0.6, 0.6),
                "visible": group_visible, "display": g.display if g else None,
                "isolated_out": isolated is not None and not any(lk.id in isolated for lk in locks),
                "isolated_in": isolated is not None and any(lk.id in isolated for lk in locks),
                "badges": badges, "meta": f"{len(locks)} lock{'s' if len(locks) != 1 else ''}",
                "children": children,
            })
        if data.orphans:
            rows.append({
                "kind": ORPHANS_ROW, "id": ORPHANS_ROW, "name": "Missing locks", "badges": [],
                "meta": f"{len(data.orphans)} no longer in the hair mesh, settings kept",
                "children": [{"kind": SEL_ORPHAN, "id": o.id, "name": o.name or f"lock {o.id}",
                              "badges": ["edited"] if o.overrides else [], "meta": o.group}
                             for o in data.orphans],
            })
        return rows

    @staticmethod
    def _group_order(data: model.GroomData) -> list[str]:
        """Groups as the tree shows them: the data's order, then groups only the locks name."""
        group_ids = [g.id for g in data.groups]
        return group_ids + sorted({lk.group for lk in data.locks} - set(group_ids))

    def _own_level(self, data: model.GroomData) -> tuple[str, list[dict[str, float]]]:
        """(source name of the selection's own level, the override dicts an edit writes into)."""
        kind, ids = self.selection
        if kind == SEL_DEFAULTS:
            return "defaults", [data.defaults]
        if kind == SEL_GROUP:
            return "group", [self._ensure_group(data, ids[0]).overrides]
        if kind == SEL_LOCKS:
            return "lock", [lk.overrides for lk in (data.lock(i) for i in ids) if lk is not None]
        return "", []

    def _value_and_source(self, data: model.GroomData, key: str) -> tuple[float, str, bool]:
        """(value, where it comes from, whether the selected locks differ). Several locks whose values
        differ show "mixed" (the value given is the first lock's, for the slider); sources that differ
        give the source "mixed"."""
        kind, ids = self.selection
        if kind == SEL_DEFAULTS:
            if key in data.defaults:
                return data.defaults[key], "defaults", False
            return model.BUILTIN_DEFAULTS[key], "builtin", False
        if kind == SEL_GROUP:
            g = data.group(ids[0])
            if g is not None and key in g.overrides:
                return g.overrides[key], "group", False
            if key in data.defaults:
                return data.defaults[key], "defaults", False
            return model.BUILTIN_DEFAULTS[key], "builtin", False
        values = [(data.resolve(i)[key], data.source_of(i, key)) for i in ids if data.lock(i) is not None]
        value, source = values[0]
        mixed = any(v != value for v, _s in values[1:])
        if any(s != source for _v, s in values[1:]):
            source = "mixed"
        return value, source, mixed

    def properties(self, data: model.GroomData | None = None) -> dict:
        """What the properties column shows for the selection: a title, a slider per setting (value,
        where it comes from, whether Reset applies) and the measured values."""
        data = data or self.data()
        kind, ids = self.selection
        if kind == SEL_NONE:
            overview, attribs = self._with_geometry(self._overview(data), None)
            return {"kind": SEL_NONE, "title": "", "settings": [], "measured": [],
                    "overview": overview, "attribs": attribs, "shortcuts": SHORTCUTS}
        if kind == SEL_ORPHAN:
            o = next(o for o in data.orphans if o.id == ids[0])
            kept = ", ".join(f"{SETTING_LABELS[k]} {_fmt(v)}" for k, v in o.overrides.items()) or "none"
            return {"kind": kind, "title": o.name or f"lock {o.id}",
                    "subtitle": f"Missing lock from {o.group or 'no group'}: no longer in the hair mesh",
                    "settings": [], "measured": [("Kept settings", kept)],
                    "targets": [(lk.id, lk.name, lk.match) for lk in data.locks]}
        own, levels = self._own_level(data)
        settings = []
        for key in model.SETTING_KEYS:
            value, source, mixed = self._value_and_source(data, key)
            settings.append({
                "key": key, "label": SETTING_LABELS[key], "unit": SETTING_UNITS.get(key, ""),
                "value": value, "source": source, "source_name": self._source_name(data, source),
                "below": self._below(data, key), "mixed": mixed, "range": SETTING_RANGES[key],
                "resettable": any(key in lv for lv in levels), "scale": SETTING_SCALE.get(key, 1.0),
                "tip": SETTING_TIPS.get(key, ""),
            })
        if kind == SEL_DEFAULTS:
            title, subtitle = ALL_LOCKS, f"{len(data.locks)} locks · a group or a lock can set its own value"
            infos = list(self._infos.values())
        elif kind == SEL_GROUP:
            g = data.group(ids[0])
            title = (g.name if g else ids[0]) or "(no group)"
            members = [lk for lk in data.locks if lk.group == ids[0]]
            subtitle = f"Group · {len(members)} locks"
            infos = [self._infos[lk.id] for lk in members if lk.id in self._infos]
        else:
            locks = [data.lock(i) for i in ids]
            title = locks[0].name if len(locks) == 1 else f"{len(locks)} locks"
            groups = sorted({lk.group for lk in locks})
            g = data.group(groups[0])
            in_group = (g.name if g else groups[0]) if len(groups) == 1 else f"{len(groups)} groups"
            subtitle = ("Lock · " if len(locks) == 1 else "Locks · ") + in_group
            if len(locks) == 1 and (locks[0].match == "unsure" or (locks[0].match == "new" and data.orphans)):
                subtitle += f" · {MATCH_LABELS.get(locks[0].match, locks[0].match)}"
            infos = [self._infos[i] for i in ids if i in self._infos]
        state = self._state(data, kind, ids)
        if state.get("note"):
            subtitle += f" · {state['note']}"
        measured, attribs = self._with_geometry(self._measured(kind, infos),
                                                None if kind == SEL_DEFAULTS else self.lock_ids_of(data, self.selection))
        return {"kind": kind, "title": title, "subtitle": subtitle, "own": own, "state": state,
                "settings": settings, "measured": measured, "attribs": attribs}

    def _with_geometry(self, measured: list[tuple[str, str]], lock_ids) -> tuple[list[tuple[str, str]], str]:
        """The measured cells plus what the hair geometry holds (adapter.geo_stats): the real strand
        count replaces the estimate, then points, points a strand; and the attribute names, one line."""
        read = getattr(self.adapter, "geo_stats", None)
        if read is None or self.node is None:
            return measured, ""
        try:
            st = read(self.node, lock_ids)
        except Exception:
            return measured, ""
        if not st or not st.get("prims"):
            return measured, ""
        light = st.get("mode") not in ("", "hair")
        label = "Strands (preview)" if light else "Strands"
        cells = [(k, v) for k, v in measured if k != "Strands"]
        cells += [(label, f"{st['prims']:,}"), ("Points", f"{st['points']:,}"),
                  ("Points / strand", f"{st['points'] / st['prims']:.0f}")]
        attribs = st.get("attribs") or {}
        # what a reader of the publish gets: the deform capture and viewport hints stay out of the list
        shown = {cls: [n for n in names if not n.startswith(("pCapt", "gl_"))] for cls, names in attribs.items()}
        line = " · ".join(f"{cls}: {', '.join(names)}" for cls, names in shown.items() if names)
        return cells, line

    def _below(self, data: model.GroomData, key: str) -> dict | None:
        """On All locks or a group: the levels below that set their own *key* (so an edit here does not
        reach them), or none (every one follows). None for a lock: nothing is below it."""
        kind, ids = self.selection
        if kind == SEL_DEFAULTS:
            groups = [g.name or g.id for g in data.groups if key in g.overrides]
            locks = [lk.name or f"lock {lk.id}" for lk in data.locks if key in lk.overrides]
            total = len(data.groups) + len(data.locks)
        elif kind == SEL_GROUP:
            groups = []
            members = [lk for lk in data.locks if lk.group == ids[0]]
            locks = [lk.name or f"lock {lk.id}" for lk in members if key in lk.overrides]
            total = len(members)
        else:
            return None
        return {"groups": groups, "locks": locks, "total": total}

    def _source_name(self, data: model.GroomData, source: str) -> str:
        """Where an inherited value comes from, as the tree names it: the group's name, All locks, or
        the tool's own default."""
        if source == "group":
            kind, ids = self.selection
            gids = {ids[0]} if kind == SEL_GROUP else {lk.group for lk in (data.lock(i) for i in ids) if lk}
            if len(gids) == 1:
                g = data.group(next(iter(gids)))
                return (g.name if g else next(iter(gids))) or "group"
            return "groups"
        return SOURCE_NAMES.get(source, source)

    def _state(self, data: model.GroomData, kind: str, ids) -> dict:
        """What the viewport does with the selection, for the properties' action row and its subtitle:
        isolated, shown, root flipped, excluded (None when the locks differ), and a
        note when the selection is not drawn (its edits would be invisible)."""
        if kind not in (SEL_GROUP, SEL_LOCKS):
            return {}
        lock_ids = self.lock_ids_of(data, self.selection)
        locks = [lk for lk in (data.lock(i) for i in lock_ids) if lk is not None]
        if not locks:
            return {}

        def same(values):
            values = set(values)
            return values.pop() if len(values) == 1 else None

        if kind == SEL_GROUP:
            g = data.group(ids[0])
            visible = g.visible if g else True
        else:
            visible = same(lk.visible for lk in locks)
        drawn = self._drawn(data, lock_ids)
        isolated = set(self.isolated or ())
        if not drawn:
            note = "outside isolate" if isolated else ("hidden by its group" if all(lk.visible for lk in locks)
                                                         else "hidden")
        elif any(lk.excluded for lk in locks) and kind == SEL_LOCKS and len(locks) == 1:
            note = "excluded from hair"
        else:
            note = ""
        return {"kind": kind, "ids": list(ids), "lock_ids": lock_ids, "visible": visible,
                "isolated": bool(isolated) and set(lock_ids) <= isolated,
                "root_flip": same(lk.root_flip for lk in locks) if kind == SEL_LOCKS else None,
                "excluded": same(lk.excluded for lk in locks) if kind == SEL_LOCKS else None,
                "note": note}

    def _overview(self, data: model.GroomData) -> list[tuple[str, str]]:
        """The whole groom, shown while nothing is selected."""
        infos = list(self._infos.values())
        to_check = sum(lk.match == "unsure" or (lk.match == "new" and bool(data.orphans)) for lk in data.locks)
        hidden = len(self._unseen(data)[0])
        rows = [("Locks", f"{len(data.locks)}"), ("Groups", f"{len(data.groups)}"),
                ("Strands", f"{sum(i.strands for i in infos):,}" if infos else "not cooked yet"),
                ("Regions", ("out of date: " + "; ".join(data.stale_why[-2:]) if data.stale_why else "out of date")
                 if data.regions_stale else "up to date"),
                ("To check", f"{to_check}" if to_check else "none"),
                ("Hidden", f"{hidden}" if hidden else "none")]
        if data.orphans:
            rows.append(("Missing locks", f"{len(data.orphans)}"))
        return rows

    def _measured(self, kind: str, infos: list[logic.LockInfo]) -> list[tuple[str, str]]:
        """Measured shape in cm (scene units x `unit_cm`), twist in degrees."""
        if not infos:
            return [("Measured", "not cooked yet")]
        u = self.unit_cm
        if len(infos) == 1 and kind == SEL_LOCKS:
            i = infos[0]
            return [("Lock width", _cm(i.width * u)), ("Lock thickness", _cm(i.thick * u)),
                    ("Length", _cm(i.length * u)), ("Twist", f"{math.degrees(i.twist):.0f}°"),
                    ("Strands", f"{i.strands:,}"), ("Skin area", f"{_fmt(i.region_area_cm2)} cm²")]
        n = len(infos)
        return [("Lock width, mean", _cm(sum(i.width for i in infos) / n * u)),
                ("Lock thickness, mean", _cm(sum(i.thick for i in infos) / n * u)),
                ("Length, mean", _cm(sum(i.length for i in infos) / n * u)),
                ("Locks", f"{n}"),
                ("Strands", f"{sum(i.strands for i in infos):,}"),
                ("Skin area", f"{_fmt(sum(i.region_area_cm2 for i in infos))} cm²")]

    # ------------------------------------------------------------------
    # Writing: one read, one change, one write (one undo step)
    # ------------------------------------------------------------------
    def _edit(self, label: str, change: Callable[[model.GroomData], Any]) -> bool:
        if self.node is None:
            return False
        try:
            data = self.data()
            if change(data) is False:
                return False
            with self._busy(label):
                self.adapter.write_data(self.node, data, label)
        except Exception as e:
            self.view.set_message(f"{label} failed: {e}", error=True)
            return False
        self.refresh()
        return True

    @staticmethod
    def _ensure_group(data: model.GroomData, gid: str) -> model.Group:
        g = data.group(gid)
        if g is None:  # a group the locks name but the data does not list yet
            g = model.Group(id=gid, name=gid)
            data.groups.append(g)
        return g

    def _selection_name(self, data: model.GroomData) -> str:
        kind, ids = self.selection
        if kind == SEL_DEFAULTS:
            return ALL_LOCKS
        if kind == SEL_GROUP:
            g = data.group(ids[0])
            return (g.name if g else ids[0]) or "no group"
        if len(ids) == 1:
            lk = data.lock(ids[0])
            return lk.name if lk else str(ids[0])
        return f"{len(ids)} locks"

    def preview_value(self, key: str, value: float) -> bool:
        """A slider tick while dragging: the viewport follows at once, with no undo step and no panel
        refresh. The first tick keeps the data from before the drag; set_value (the release) puts it back
        and writes the final value as one undo step."""
        live = getattr(self.adapter, "write_data_live", None)
        if live is None or self.node is None or key not in model.BUILTIN_DEFAULTS:
            return False
        if self.deform_state() == (True, True):
            # Anim on: each tick would deform the whole groom (~1.3-1.8 s) and Houdini's interrupt popup
            # would take the mouse from the slider; the value applies on release instead
            if not self._drag_warned:
                self._drag_warned = True
                self.view.set_message("Deform is on: the value applies when you let go. Turn Deform off to see it live")
            return False
        try:
            data = self.data()
            if self._drag_origin is None:
                self._drag_origin = data.to_json()
                self._drag_origin_new = True
            _own, levels = self._own_level(data)
            if not levels:
                return False
            for lv in levels:
                lv[key] = float(value)
            # While dragging, the locks being changed regrow at their real strand count with fewer points a
            # strand (a tick on one Helen lock ~0.14 s); a selection of more than DRAG_STRAND_BUDGET strands
            # (a group) at a fraction of them, which the panel says. The release restores the data from
            # before the drag, so the locks' own display comes back and they grow in full once.
            first = self._drag_origin_new
            self._drag_origin_new = False
            light = getattr(self.adapter, "set_drag_preview", None)
            if self._drag_preview and light is not None:
                ids = self.lock_ids_of(data, self.selection)
                factor = logic.drag_factor(self._drag_strands(data, ids, key, float(value)))
                if first or factor != self._drag_factor:
                    self._drag_factor = factor
                    try:
                        light(self.node, ids, factor)
                    except TypeError:   # an adapter from before the drag factor
                        light(self.node, ids)
                    self.view.set_message("" if factor >= 1.0 else
                                          f"Dragging {len(ids)} locks: showing 1 in {round(1 / factor)} strands "
                                          "until you let go")
            live(self.node, data)
        except Exception as e:
            self.view.set_message(f"{SETTING_LABELS.get(key, key)} failed: {e}", error=True)
            return False
        return True

    def _drag_strands(self, data: model.GroomData, ids: list[int], key: str, value: float) -> float:
        """Strands the dragged locks have at this tick's value (a density drag changes their count)."""
        total = 0.0
        for i in ids:
            info = self._infos.get(i)
            if info is None:
                continue
            n = float(info.strands)
            if key == "density":
                base = (model.GroomData.from_json(self._drag_origin).resolve(i) if self._drag_origin
                        else data.resolve(i)).get("density", 0.0)
                n = n * value / base if base > 0 else n
            total += n
        return total

    def _end_drag(self) -> None:
        """Put back the data from before a drag (no undo step), so the release's write is the only step."""
        origin, self._drag_origin = self._drag_origin, None
        self._drag_warned = False
        self._drag_factor = None
        light = getattr(self.adapter, "set_drag_preview", None)
        if origin is not None and light is not None and self.node is not None:
            light(self.node, None)          # the release grows them in full
        live = getattr(self.adapter, "write_data_live", None)
        if origin is not None and live is not None and self.node is not None:
            live(self.node, model.GroomData.from_json(origin))

    def set_value(self, key: str, value: float) -> bool:
        """Write *value* for *key* at the selection's own level (defaults, the group or every selected lock)."""
        if key not in model.BUILTIN_DEFAULTS:
            raise KeyError(key)
        self._end_drag()
        holder: dict = {}

        def change(data: model.GroomData):
            _own, levels = self._own_level(data)
            if not levels:
                return False
            for lv in levels:
                lv[key] = float(value)
            holder["name"] = self._selection_name(data)

        data_name = self._label_target()
        ok = self._edit(f"Grooming: {SETTING_LABELS[key]} on {data_name}", change)
        if ok:
            shown = float(value) * SETTING_SCALE.get(key, 1.0)
            degrees = "°" if key == "twist_add" else ""
            below = self._below(self.data(), key)
            keep = (below["groups"] + below["locks"]) if below else []
            note = (f" · {_names(keep)} keep their own (Reset there to follow)" if keep else "")
            self.view.set_message(f"{SETTING_LABELS[key]} = {_fmt(shown)}{degrees} on {holder['name']}{note}")
        return ok

    def reset_value(self, key: str) -> bool:
        """Remove the selection's own override of *key*: the value comes from the level below again."""
        def change(data: model.GroomData):
            _own, levels = self._own_level(data)
            hit = [lv for lv in levels if key in lv]
            if not hit:
                return False
            for lv in hit:
                del lv[key]

        ok = self._edit(f"Grooming: reset {SETTING_LABELS[key]} on {self._label_target()}", change)
        if ok:
            self.view.set_message(f"{SETTING_LABELS[key]} reset on {self._label_target()}")
        return ok

    def _label_target(self) -> str:
        try:
            return self._selection_name(self.data())
        except Exception:
            return "selection"

    def _rows_of(self, data: model.GroomData, kind: str, ids) -> list:
        if kind == SEL_GROUP:
            return [self._ensure_group(data, gid) for gid in ids]
        return [lk for lk in (data.lock(i) for i in ids) if lk is not None]

    def set_visible(self, kind: str, ids, visible: bool) -> bool:
        """Eye toggle of group or lock rows (the HDA leaves hidden ones out of the output)."""
        def change(data: model.GroomData):
            rows = self._rows_of(data, kind, ids)
            if not rows:
                return False
            for row in rows:
                row.visible = visible

        what = "Show" if visible else "Hide"
        return self._edit(f"Grooming: {what} {self._count(kind, ids)}", change)

    def solo_visible(self, kind: str, ids) -> bool:
        """Alt+click on an eye: only these locks (or groups) shown, every other one hidden, as plain eye
        states (saved, one undo step). Again on the same rows while they still are all that is shown: the
        eyes go back to what they were before the first Alt+click (locks hidden then stay hidden); with no
        such record (another session, the scene reopened) everything is shown."""
        ids = list(ids)
        key = (kind, tuple(sorted(ids, key=str)))
        holder: dict = {}

        def change(data: model.GroomData):
            for lk in data.locks:
                self._ensure_group(data, lk.group)
            if kind == SEL_GROUP:
                keep_groups = set(ids)
                keep_locks = {lk.id for lk in data.locks if lk.group in keep_groups}
            else:
                keep_locks = {int(i) for i in ids}
                keep_groups = {lk.group for lk in data.locks if lk.id in keep_locks}
            shown = {lk.id for lk in data.locks if lk.visible and data.group(lk.group).visible}
            eyes = ({g.id: g.visible for g in data.groups}, {lk.id: lk.visible for lk in data.locks})
            before = self._solo_before
            if before is not None and before["key"] == key and before["after"] == eyes:
                for g in data.groups:                  # the second Alt+click: the eyes as they were
                    g.visible = before["groups"].get(g.id, True)
                for lk in data.locks:
                    lk.visible = before["locks"].get(lk.id, True)
                holder["back"] = True
                self._solo_before = None
                return None
            if shown == keep_locks and before is None:  # only these shown already, no record: show all
                for g in data.groups:
                    g.visible = True
                for lk in data.locks:
                    lk.visible = True
                holder["all"] = True
                return None
            for g in data.groups:
                g.visible = g.id in keep_groups
            for lk in data.locks:
                lk.visible = lk.id in keep_locks if kind == SEL_LOCKS else (lk.group in keep_groups and lk.visible)
            self._solo_before = {"key": key, "groups": eyes[0], "locks": eyes[1],
                                 "after": ({g.id: g.visible for g in data.groups},
                                           {lk.id: lk.visible for lk in data.locks})}
            return None

        what = self._count(kind, ids)
        ok = self._edit(f"Grooming: show only {what}", change)
        if ok:
            self.view.set_message("Eyes back as they were" if holder.get("back") else
                                  "Every lock shown again" if holder.get("all") else
                                  f"Showing only {what} (Alt+click its eye again to put the others back)")
        return ok

    def set_row_display(self, kind: str, ids, mode: str | None) -> bool:
        """Per-row display override; None follows the node's display mode."""
        if mode is not None and mode not in config.DISPLAY_MODES:
            raise ValueError(mode)

        def change(data: model.GroomData):
            rows = self._rows_of(data, kind, ids)
            if not rows:
                return False
            for row in rows:
                row.display = mode

        label = DISPLAY_LABELS[mode] if mode else "node display"
        return self._edit(f"Grooming: {self._count(kind, ids)} shows {label}", change)

    def set_group_color(self, gid: str, color: tuple[float, float, float]) -> bool:
        def change(data: model.GroomData):
            self._ensure_group(data, gid).color = tuple(float(c) for c in color)[:3]

        return self._edit(f"Grooming: colour of {gid}", change)

    def confirm_matches(self, ids) -> bool:
        """Accept unsure / new re-import matches: the badges go."""
        def change(data: model.GroomData):
            locks = [lk for lk in (data.lock(i) for i in ids) if lk is not None and lk.match != "ok"]
            if not locks:
                return False
            for lk in locks:
                lk.match = "ok"

        ok = self._edit(f"Grooming: confirm {self._count(SEL_LOCKS, ids)}", change)
        if ok:
            self.view.set_message(f"Confirmed {self._count(SEL_LOCKS, ids)}")
        return ok

    def confirm_all(self) -> bool:
        """The tree's "Confirm all": every new and to-check lock accepted as it is."""
        ids = [lk.id for lk in self.data().locks if lk.match != "ok"]
        return self.confirm_matches(ids) if ids else False

    def review_counts(self, data: model.GroomData) -> tuple[int, int]:
        """(new locks, locks to check): what the tree's Confirm all line offers."""
        new = sum(lk.match == "new" for lk in data.locks) if data.orphans else 0
        return new, sum(lk.match == "unsure" for lk in data.locks)

    def reassign_orphan(self, orphan_id: int, lock_id: int) -> bool:
        """An orphan's settings go to *lock_id* (usually a lock detect marked new), and the orphan
        leaves the list. The lock keeps its id and its name (the hair-mesh piece's name, which the next
        Detect matches by), so the geometry stays matched; its match is ok."""
        holder: dict = {}

        def change(data: model.GroomData):
            orphan = next((o for o in data.orphans if o.id == orphan_id), None)
            lk = data.lock(lock_id)
            if orphan is None or lk is None:
                return False
            lk.overrides = dict(orphan.overrides)
            lk.match = "ok"
            data.orphans.remove(orphan)
            holder["text"] = f"{orphan.name or orphan.id} reassigned to lock {lk.id}"

        ok = self._edit(f"Grooming: reassign orphan {orphan_id}", change)
        if ok:
            self.selection = (SEL_LOCKS, (lock_id,))
            self.refresh()
            self.view.set_message(holder["text"])
        return ok

    def delete_orphan(self, orphan_id: int) -> bool:
        def change(data: model.GroomData):
            orphan = next((o for o in data.orphans if o.id == orphan_id), None)
            if orphan is None:
                return False
            data.orphans.remove(orphan)

        ok = self._edit(f"Grooming: delete orphan {orphan_id}", change)
        if ok:
            self.view.set_message(f"Missing lock {orphan_id} deleted (Ctrl+Z brings it back)")
        return ok

    @staticmethod
    def _count(kind: str, ids) -> str:
        ids = list(ids)
        if kind == SEL_GROUP:
            return f"group {ids[0]}" if len(ids) == 1 else f"{len(ids)} groups"
        return f"lock {ids[0]}" if len(ids) == 1 else f"{len(ids)} locks"

    # ------------------------------------------------------------------
    # Node actions: Detect, Split regions, display, Publish
    # ------------------------------------------------------------------
    def _run(self, what: str, call: Callable[[], Any]) -> Any:
        if self.node is None:
            return None
        try:
            with self._busy(what):
                return call()
        except Exception as e:
            self.view.set_message(f"{what} failed: {e}", error=True)
            return None

    @contextlib.contextmanager
    def _busy(self, what: str):
        """A change and the cook it causes, with the panel's loading line: the view shows it only when
        the work outlasts a moment (Houdini handles Qt events mid-cook). The node is cooked here, not
        when the viewport next draws, so the line covers the wait the user feels."""
        busy = getattr(self.view, "set_busy", None)
        if busy is not None:
            busy(what.removeprefix("Grooming: "))
        try:
            yield
            cook = getattr(self.adapter, "cook_display", None)
            if cook is not None and self.node is not None:
                cook(self.node)
        finally:
            if busy is not None:
                busy(None)

    def detect(self) -> logic.DetectReport | None:
        report = self._run("Detect", lambda: self.adapter.detect(self.node))
        if report is None:
            return None
        self.refresh()
        text = report_text(report.counts)
        if self.data().regions_stale:
            text += " · regions out of date: Update regions"
        self.view.set_message(text, error=False)
        return report

    def split_regions(self) -> bool:
        if self._run("Split regions", lambda: self.adapter.split_regions(self.node) or True) is None:
            return False
        self.refresh()
        self.view.set_message("Regions updated: each lock grows from its own skin area again (kept until the next update)")
        return True

    def set_display(self, mode: str | None = None, color_by: str | None = None) -> bool:
        mode = mode or self.display_mode
        color_by = color_by or self.color_by
        if mode not in config.DISPLAY_MODES or color_by not in config.COLOR_BY:
            raise ValueError((mode, color_by))
        done = self._run("Display", lambda: self.adapter.set_display(
            self.node, mode, color_by, config.PREVIEW_FRACTION) or True)
        if done is None:
            return False
        recolor = color_by != self.color_by
        self.display_mode, self.color_by = mode, color_by
        self.view.set_display_state(mode, color_by)
        if recolor:
            self.view.show_tree(self.tree_rows(self.data()))
            self.view.set_selection(self.selection)
        return True

    def deform_state(self) -> tuple[bool, bool]:
        """(an animated hair mesh is wired in, Shot deform on); (False, False) with an older adapter."""
        read = getattr(self.adapter, "deform_state", None)
        if read is None or self.node is None:
            return False, False
        try:
            return tuple(read(self.node))  # type: ignore[return-value]
        except Exception:
            return False, False

    def set_shot_deform(self, on: bool) -> bool:
        """Follow the animation or stay at rest. Off while grooming: an edit then costs no deform."""
        call = getattr(self.adapter, "set_shot_deform", None)
        if call is None or self.node is None:
            return False
        if self._run("Shot deform", lambda: call(self.node, bool(on)) or True) is None:
            return False
        self.view.set_deform_state(*self.deform_state())
        self.view.set_message("Deform on: the hair follows the animated hair mesh. Every lock is drawn as strands, "
                              "the others are only dimmed (not see-through), each edit deforms it again"
                              if on else "Shot deform off: the hair stays at rest, edits are fast")
        return True

    def refresh_publish_version(self) -> str:
        """Prefill the publish version from logic.publish_version, when the adapter can say what the
        scene is called and what is already published (`publish_context`); else empty = adapter default."""
        version, note = "", "Empty: the adapter picks the scene's version"
        ctx = getattr(self.adapter, "publish_context", None)
        if ctx is not None and self.node is not None:
            try:
                scene_name, existing = ctx(self.node)
                version, note = logic.publish_version(scene_name, list(existing))
            except Exception as e:  # logic not written yet, or no project around the scene
                note = f"No default version: {e}" if str(e) else note
        self.view.set_publish_version(version, note)
        return version

    def _unseen(self, data: model.GroomData) -> tuple:
        """(hidden lock names, isolated or not): what Publish warns about. A lock is hidden by its own
        eye or by its group's."""
        hidden_groups = {g.id for g in data.groups if not g.visible}
        hidden = tuple(lk.name or f"lock {lk.id}" for lk in data.locks
                       if not lk.visible or lk.group in hidden_groups)
        return hidden, self.isolated is not None

    def publish_warning(self, data: model.GroomData) -> str:
        """What the panel says next to Publish before it goes on, or "" when every lock is shown."""
        hidden, isolated = self._unseen(data)
        parts = []
        if hidden:
            parts.append(f"{len(hidden)} hidden lock{'s' if len(hidden) != 1 else ''} ({_names(list(hidden))})")
        if isolated:
            parts.append(f"isolated on {len(self.isolated or ())} lock{'s' if len(self.isolated or ()) != 1 else ''}")
        if not parts:
            return ""
        return " · ".join(parts) + ": Publish writes every lock anyway. Click again to publish"

    def publish(self, version: str | None) -> logic.PublishResult | None:
        """Publish always writes every lock. When some are hidden or the view is isolated, the first click
        only says so next to the button (no dialog: it would block Houdini); a second click with the same
        locks hidden publishes."""
        if self.node is None:
            return None
        data = self.data()
        unseen = self._unseen(data)
        warning = self.publish_warning(data)
        if warning and self._publish_armed != unseen:
            self._publish_armed = unseen
            self.view.set_publish_warning(warning)
            return None
        self._publish_armed = None
        self.view.set_publish_warning("")
        version = (version or "").strip() or None
        result = self._run("Publish", lambda: self.adapter.publish(self.node, version))
        if result is None:
            return None
        if result.ok:
            self.view.set_message(f"Published {result.version}: {result.path}", error=False)
            self.refresh_publish_version()
        else:
            self.view.set_message(f"Not published: {result.message}", error=True)
        return result

    # ------------------------------------------------------------------
    # Isolate: a view state of the adapter (not saved, not undoable); hidden states stay as they are
    # ------------------------------------------------------------------
    def isolate_text(self, data: model.GroomData | None = None) -> str:
        """'' when not isolated, else what is shown alone."""
        if self.isolated is None:
            return ""
        data = data or self._data or self.data()
        names = [lk.name or f"lock {lk.id}" for lk in data.locks if lk.id in set(self.isolated)]
        groups = {lk.group for lk in data.locks if lk.id in set(self.isolated)}
        if len(groups) == 1 and all(lk.id in self.isolated for lk in data.locks if lk.group in groups):
            gid = next(iter(groups))
            g = data.group(gid)
            return f"Isolated: {(g.name if g else gid) or gid} · {len(names)} lock{'s' if len(names) != 1 else ''}"
        return f"Isolated: {_names(names)}"

    def toggle_isolate(self) -> bool:
        """Isolate the selected locks or group; while isolated, other locks selected are isolated in their
        place (no need to show everything first), the same locks again show everything."""
        data = self.data()
        ids = self.lock_ids_of(data, self.selection)
        if self.isolated is not None and (not ids or sorted(ids) == sorted(self.isolated)):
            return self.isolate_off()
        if not ids:
            self.view.set_message("Isolate: select a lock or a group first")
            return False
        return self._set_isolate(ids)

    def isolate_off(self) -> bool:
        if self.isolated is None:
            return False
        return self._set_isolate(None)

    def escape(self) -> bool:
        """Esc / the banner's button: out of isolate first; else nothing selected (the whole groom)."""
        if self.isolate_off():
            return True
        if self.selection[0] == SEL_NONE:
            return False
        self.select(SEL_NONE)
        if hasattr(self.view, "set_selection"):
            self.view.set_selection(self.selection)
        return True

    def focus_off(self) -> None:
        """The panel closes or changes node: every lock in its colour again."""
        focus = getattr(self.adapter, "set_focus", None)
        if focus is not None and self.node is not None:
            try:
                focus(self.node, None)
            except Exception:
                pass

    def undo(self, redo: bool = False) -> bool:
        """Ctrl+Z / Ctrl+Shift+Z (Ctrl+Y) in the panel: Houdini's undo or redo, then the panel follows."""
        call = getattr(self.adapter, "undo", None)
        if call is None or self.node is None:
            return False
        self._end_drag()
        label = self._run("Redo" if redo else "Undo", lambda: call(self.node, redo))
        if label is None:   # failed: _run said why
            return False
        if not label:
            self.view.set_message("Nothing to redo" if redo else "Nothing to undo")
            return False
        self.refresh()
        self.view.set_message(f"{'Redone' if redo else 'Undone'}: {label}")
        return True

    def _set_isolate(self, ids: list[int] | None) -> bool:
        call = getattr(self.adapter, "set_isolate", None)
        if call is None:
            self.view.set_message("Isolate needs a newer MONO Grooming adapter", error=True)
            return False
        if self._run("Isolate", lambda: call(self.node, ids) or True) is None:
            return False
        self.refresh()
        self._sync_viewport()   # the output's prim numbers changed: keep the same locks selected
        # the banner says what is isolated; the message line only says what changed back
        self.view.set_message("" if self.isolated else "Showing every lock again")
        return True

    # ------------------------------------------------------------------
    # How the viewport draws: it follows the work, nothing to switch or remember. Selected (drawn)
    # locks are their real strands and the others x-ray bands (packed, see-through: only packed geometry
    # can be see-through in the viewport); X turns the x-ray off to see the selection among the real
    # groom; nothing selected shows the whole groom as strands. t41 (GUI Helen): select 0.04-0.08 s,
    # a group of 20 0.16 s, back to the whole groom 0.37 s, an edit 0.50 s (x-ray) / 0.84 s (all strands).
    # ------------------------------------------------------------------
    def toggle_xray(self) -> bool:
        """X / the view bar's X-ray: the others as see-through bands (on) or as real strands (off)."""
        self.xray = not self.xray
        if hasattr(self.view, "set_xray_on"):
            self.view.set_xray_on(self.xray)
        self._sync_viewport()
        if self.selection[0] in (SEL_LOCKS, SEL_GROUP):
            self.view.set_message("X-ray on: the locks you are not editing are see-through bands" if self.xray
                                  else "X-ray off: every lock as real strands, the selection still edits"
                                       " (edits are slower: X turns it back on)")
        return True

    # ------------------------------------------------------------------
    # Per lock: which end is the root, and whether it grows hair at all
    # ------------------------------------------------------------------
    def set_root_flip(self, ids, flip: bool) -> bool:
        """Root at the mesh piece's other end, for a loop or a piece Detect read the wrong way round."""
        return self._lock_flag("set_root_flip", ids, flip,
                               "Root flipped" if flip else "Root at the end nearer the scalp")

    def set_excluded(self, ids, excluded: bool) -> bool:
        """No hair for these locks (an accessory, a floating piece); mesh and guide still show them."""
        return self._lock_flag("set_excluded", ids, excluded,
                               "Excluded from hair" if excluded else "Grows hair again")

    def _lock_flag(self, name: str, ids, value: bool, what: str) -> bool:
        call = getattr(self.adapter, name, None)
        ids = [int(i) for i in (ids or [])]
        if call is None or not ids:
            if call is None:
                self.view.set_message(f"{what} needs a newer MONO Grooming adapter", error=True)
            return False
        changed = self._run(what, lambda: call(self.node, ids, value))
        if changed is None:
            return False
        self.refresh()
        n = len(ids)
        self.view.set_message(f"{what}: {n} lock{'s' if n != 1 else ''}. Regions are out of date: Update regions")
        return bool(changed)

    # ------------------------------------------------------------------
    # Drag and drop in the tree: order, and locks into another group
    # ------------------------------------------------------------------
    def plan_drop(self, dragged, target, where: str) -> dict | str:
        """What dropping the rows *dragged* ([(kind, id)]) at *target* ((kind, id), None = below the last
        row) *where* (above / below / on) does: {"locks": ids, "group": gid, "before": id | None} or
        {"group_id": gid, "before": gid | None}, or the reason it is refused. Reads the last data shown,
        so the view can ask on every mouse move."""
        data = self._data
        if data is None:
            return "Nothing to move"
        kinds = {k for k, _i in dragged}
        if not dragged or kinds - {SEL_LOCKS, SEL_GROUP}:
            return "Only locks and groups move"
        if kinds == {SEL_LOCKS, SEL_GROUP}:
            return "Drag locks or one group, not both"
        order = self._group_order(data)
        tkind, tid = target if target is not None else (None, None)
        if kinds == {SEL_GROUP}:
            if len(dragged) != 1:
                return "Drag one group at a time"
            gid = dragged[0][1]
            if tkind is None:
                before = None
            elif tkind == SEL_DEFAULTS:
                if where == DROP_ABOVE:
                    return f"{ALL_LOCKS} stays first"
                before = order[0] if order else None
            elif tkind == SEL_GROUP:
                if tid == gid:
                    return "A group cannot go onto itself"
                if where == DROP_ON:
                    return "Groups do not nest"
                at = order.index(tid) + (1 if where == DROP_BELOW else 0)
                before = order[at] if at < len(order) else None
            elif tkind == SEL_LOCKS:
                return "Groups do not nest: drop it between groups"
            else:  # Orphans
                before = None
            rest = [g for g in order if g != gid]
            if (rest.index(before) if before in rest else len(rest)) == order.index(gid):
                return "Already there"
            return {"group_id": gid, "before": before}
        ids = [i for _k, i in dragged]
        if tkind is None:
            return "Drop locks into a group"
        if tkind == SEL_DEFAULTS:
            return f"{ALL_LOCKS} holds the groups: drop the locks into a group"
        if tkind in (SEL_ORPHAN, ORPHANS_ROW):
            return "Missing locks are no longer in the hair mesh: drop into a group"
        if tkind == SEL_GROUP:
            group, before = tid, None
            if where == DROP_BELOW:  # just under the group's own row: first in it
                first = next((lk.id for lk in data.locks if lk.group == tid and lk.id not in ids), None)
                before = first
            elif where == DROP_ABOVE:  # above a group's row: the end of the group before it
                at = order.index(tid)
                if at == 0:
                    return "Drop locks into a group"
                group = order[at - 1]
        else:
            lk = data.lock(tid)
            if lk is None:
                return "Nothing to move"
            if tid in ids:
                return "A lock cannot go onto itself"
            group = lk.group
            members = [m.id for m in data.locks if m.group == group and m.id not in ids]
            at = members.index(tid) + (0 if where == DROP_ABOVE else 1)
            before = members[at] if at < len(members) else None
        trial = model.GroomData.from_json(data.to_json())
        trial.move_locks(ids, group, before)
        if [(lk.id, lk.group) for lk in trial.locks] == [(lk.id, lk.group) for lk in data.locks]:
            return "Already there"
        return {"locks": ids, "group": group, "before": before}

    def drop(self, dragged, target, where: str) -> bool:
        """Apply a drop (one undo step). Locks moved to another group keep their own settings; values they
        took from the old group now come from the new one, and the message says which changed. Regions
        may depend on the group, so they are marked out of date, never split again silently."""
        plan = self.plan_drop(dragged, target, where)
        if isinstance(plan, str):
            if plan != "Already there":
                self.view.set_message(f"Not moved: {plan}")
            return False
        holder: dict = {}

        def change(data: model.GroomData):
            if "group_id" in plan:
                self._ensure_group(data, plan["group_id"])
                data.move_group(plan["group_id"], plan["before"])
                holder["text"] = f"Moved group {plan['group_id']}"
                return None
            ids, gid = plan["locks"], plan["group"]
            before = {i: data.resolve(i) for i in ids}
            changed_group = any(data.lock(i).group != gid for i in ids)
            self._ensure_group(data, gid)
            data.move_locks(ids, gid, plan["before"])
            g = data.group(gid)
            where_to = (g.name if g else gid) or gid
            text = f"Moved {self._count(SEL_LOCKS, ids)} to {where_to}" if changed_group else \
                f"Reordered {self._count(SEL_LOCKS, ids)}"
            if changed_group:
                data.mark_stale(f"{self._count(SEL_LOCKS, ids)} moved to {where_to}")
                diffs = []
                for key in model.SETTING_KEYS:
                    olds = {before[i][key] for i in ids}
                    new = {data.resolve(i)[key] for i in ids}
                    if olds != new:
                        was = _fmt(next(iter(olds))) if len(olds) == 1 else "mixed"
                        now = _fmt(next(iter(new))) if len(new) == 1 else "mixed"
                        diffs.append(f"{SETTING_LABELS[key]} {was} → {now}")
                text += (" · from the new group: " + ", ".join(diffs)) if diffs else " · settings unchanged"
                text += " · regions out of date"
            holder["text"] = text

        what = "group" if "group_id" in plan else self._count(SEL_LOCKS, plan["locks"])
        ok = self._edit(f"Grooming: move {what}", change)
        if ok:
            self.view.set_message(holder["text"])
        return ok

    # ------------------------------------------------------------------
    # Selection, both ways
    # ------------------------------------------------------------------
    def lock_ids_of(self, data: model.GroomData, selection: tuple[str, tuple]) -> list[int]:
        kind, ids = selection
        if kind == SEL_LOCKS:
            return sorted(ids)
        if kind == SEL_GROUP:
            return sorted(lk.id for lk in data.locks if lk.group == ids[0])
        return []

    def select(self, kind: str, ids=()) -> None:
        """The panel's selection changed: show its properties and select its locks in the viewport."""
        data = self.data()
        if kind == SEL_LOCKS:
            ids = [i for i in ids if data.lock(i) is not None]
        self.selection = (kind, tuple(ids)) if ids or kind == SEL_DEFAULTS else (SEL_NONE, ())
        kind = self.selection[0]
        if any(i not in self._infos for i in self.lock_ids_of(data, self.selection)):
            try:  # the panel opened before the node cooked: measure now
                self._infos = {info.id: info for info in self.adapter.lock_infos(self.node)}
            except Exception:
                pass
        self.view.show_properties(self.properties(data))
        if kind in (SEL_LOCKS, SEL_GROUP) or hasattr(self.adapter, "set_focus"):
            self._sync_viewport(data)   # nothing selected: every lock in its colour again

    def _sync_viewport(self, data: model.GroomData | None = None, quiet: bool = False) -> None:
        """Show the panel's selection in the viewport: the selected locks keep their colour and the others
        go see-through (adapter.set_focus, by lock id, which also clears Houdini's selection highlight that
        painted the lock over). Only drawn locks take focus: a selection that is hidden or outside the
        isolate would leave nothing solid on screen, every lock see-through, so then nothing is ghosted and
        the message says why. An adapter without focus selects the locks' prims instead."""
        data = data or self._data or self.data()
        lock_ids = self.lock_ids_of(data, self.selection)
        focus = getattr(self.adapter, "set_focus", None)
        if focus is not None:
            drawn = self._drawn(data, lock_ids)
            every = self._drawn(data, [lk.id for lk in data.locks])
            # the whole groom as it will render: nothing (drawn) selected, all of it, or X-ray off
            look = not drawn or not self.xray or set(drawn) >= set(every)
            strands = getattr(self.adapter, "set_strands", None)
            whole = getattr(self.adapter, "STRANDS_ALL", "all")
            too_many = not look and len(drawn) > config.STRANDS_MAX

            def show():
                focus(self.node, None if look else drawn)
                if strands is not None:
                    strands(self.node, whole if look else (None if too_many else drawn))
                return True

            self._run("Focus", show)
            self._viewport_ids = []
            if too_many and not quiet:
                self.view.set_message(f"{len(drawn)} locks selected: drawn as bands (strands for up to"
                                      f" {config.STRANDS_MAX}). X shows every lock as strands")
            if lock_ids and not drawn and not quiet:
                names = ", ".join(lk.name for lk in (data.lock(i) for i in lock_ids[:3]) if lk is not None)
                more = f" and {len(lock_ids) - 3} more" if len(lock_ids) > 3 else ""
                why = ("outside the isolate: press I to isolate it" if self._read_isolate()
                       else "hidden: turn its eye on to see it")
                self.view.set_message(f"{names}{more} is {why}")
            return
        if not lock_ids:
            return
        self._run("Select", lambda: self.adapter.select_locks(self.node, lock_ids))
        # Remember what the viewport reports now (hidden locks are not in its geometry), so the next
        # poll does not take that subset for a new viewport selection and replace the panel's.
        try:
            self._viewport_ids = sorted(self.adapter.selected_lock_ids(self.node))
        except Exception:
            self._viewport_ids = lock_ids

    def _drawn(self, data: model.GroomData, lock_ids) -> list[int]:
        """The locks among `lock_ids` the viewport draws: the isolated ones while isolated (even with
        their eye off), else those shown by their eye and their group's."""
        isolated = self._read_isolate()
        if isolated:
            return [i for i in lock_ids if i in isolated]
        return [i for i in lock_ids if data.shown(i)]

    def select_locks(self, ids) -> None:
        self.select(SEL_LOCKS, tuple(ids))

    def select_group(self, gid: str) -> None:
        self.select(SEL_GROUP, (gid,))

    def poll(self) -> None:
        """Timer tick: the node's data changed outside (undo, the HDA's parms) → show it again; the
        viewport selection changed → select those locks here."""
        if self.node is None:
            return
        if self._drag_origin is not None:
            # a slider is being dragged: its ticks change groom_data, and showing it again would rebuild
            # the settings under the mouse and end the drag
            return
        try:
            data = self.data()
        except Exception as e:
            if not self._node_lost:
                self._node_lost = True
                self.view.set_message(f"{self.node_path() or 'The node'} can no longer be read: {e}", error=True)
            return
        self._node_lost = False
        if data.to_json() != self._last_json or self._read_isolate() != self.isolated:
            self.refresh(data)
        elif data.locks and not self._infos:  # opened before the first cook: measure once it has cooked
            try:
                self._infos = {info.id: info for info in self.adapter.lock_infos(self.node)}
            except Exception:
                self._infos = {}
            if self._infos and self.selection[0] != SEL_NONE:
                self.view.show_properties(self.properties(data))
        state = getattr(self.adapter, "display_state", None)  # undo or the HDA's own parms changed it
        if state is not None:
            try:
                mode, color_by = state(self.node)
            except Exception:
                mode, color_by = self.display_mode, self.color_by
            if (mode, color_by) != (self.display_mode, self.color_by):
                recolor = color_by != self.color_by
                self.display_mode, self.color_by = mode, color_by
                self.view.set_display_state(mode, color_by)
                if recolor:
                    self.view.show_tree(self.tree_rows(data))
                    self.view.set_selection(self.selection)
        try:
            ids = sorted(self.adapter.selected_lock_ids(self.node))
        except Exception:
            return
        if ids == self._viewport_ids:
            return
        self._viewport_ids = ids
        known = [i for i in ids if data.lock(i) is not None]
        if known and known != self.lock_ids_of(data, self.selection):
            self.selection = (SEL_LOCKS, tuple(known))
            self.view.set_selection(self.selection)
            self.view.show_properties(self.properties(data))
        if known and hasattr(self.adapter, "set_focus"):
            self._sync_viewport(data)   # a pick in the viewport: focus instead of Houdini's highlight


# ----------------------------------------------------------------------
# Houdini entry
# ----------------------------------------------------------------------
_PANELS: list = []  # (ui, controller) of open floating windows, so run() reuses one


def bind(ui: Any, controller: GroomController) -> None:
    """Wire the Qt panel's events to the controller."""
    ui.on("select", controller.select)
    ui.on("set_value", controller.set_value)
    ui.on("preview_value", controller.preview_value)
    ui.on("reset_value", controller.reset_value)
    ui.on("set_visible", controller.set_visible)
    ui.on("set_row_display", controller.set_row_display)
    ui.on("set_group_color", controller.set_group_color)
    ui.on("confirm", controller.confirm_matches)
    ui.on("reassign_orphan", controller.reassign_orphan)
    ui.on("delete_orphan", controller.delete_orphan)
    ui.on("detect", controller.detect)
    ui.on("split_regions", controller.split_regions)
    ui.on("set_display", controller.set_display)
    ui.on("publish", controller.publish)
    ui.on("isolate", controller.toggle_isolate)
    ui.on("isolate_off", controller.isolate_off)
    ui.on("escape", controller.escape)
    ui.on("undo", controller.undo)
    ui.on("hidden", controller.focus_off)
    ui.on("shown", lambda: controller._sync_viewport() if controller.node is not None else None)
    ui.on("redo", lambda: controller.undo(redo=True))
    ui.on("xray", controller.toggle_xray)
    ui.on("confirm_all", controller.confirm_all)
    ui.on("solo_visible", controller.solo_visible)
    ui.on("set_xray", controller.set_xray)
    ui.on("set_root_flip", controller.set_root_flip)
    ui.on("set_shot_deform", controller.set_shot_deform)
    ui.on("set_excluded", controller.set_excluded)
    ui.on("can_drop", controller.plan_drop)
    ui.on("drop", controller.drop)
    ui.on("poll", controller.poll)
    ui.on("refresh", controller.refresh)


def _adapter():
    import importlib
    import apps.houdini.grooming_adapter as adapter
    return importlib.reload(adapter)


def _shelf_node(adapter: Any) -> Any:
    """The selected MONO Grooming node first, else the first in the scene, else a new one."""
    nodes = adapter.find_nodes()
    return nodes[0] if nodes else adapter.create_node()


def _when_idle(poll: Callable[[], None]) -> Callable[[], None]:
    """The poll's timer, run when Houdini's event loop is idle. Houdini handles Qt events in the middle
    of a long cook (Anim on: ~1.4 s), and the poll then asked the viewer for its selection on the node
    being cooked: a cook inside the cook, "Infinite recursion in evaluation", and the cook failed.
    hdefereval runs the call from the event loop, never inside a cook; one at a time."""
    try:
        import hdefereval
    except ImportError:   # outside Houdini
        return poll
    pending = [False]

    def run_it() -> None:
        pending[0] = False
        poll()

    def tick() -> None:
        if not pending[0]:
            pending[0] = True
            hdefereval.executeDeferred(run_it)
    return tick


def create_panel(adapter: Any = None, node: Any = None, docked: bool = False):
    """A panel widget with its controller; the Python Panel (docked) and run() (floating) both use it."""
    from tools.fx.grooming.ui import GroomingUI

    adapter = adapter or _adapter()
    if node is None:
        nodes = adapter.find_nodes()
        node = nodes[0] if nodes else None
    ui = GroomingUI(docked=docked)
    controller = GroomController(adapter, ui)
    bind(ui, controller)
    ui.on("poll", _when_idle(controller.poll))
    ui.on("dock", lambda: _dock(ui))
    if node is not None:
        controller.set_node(node)
    else:
        ui.set_message("No MONO Grooming node in the scene: run the Grooming shelf tool", error=True)
    ui.start_polling(SELECTION_POLL_MS)
    return ui, controller


def run() -> None:
    """Shelf tool: open the panel on the selected (else first, else a new) MONO Grooming node."""
    adapter = _adapter()
    node = _shelf_node(adapter)
    for ui, controller in list(_PANELS):
        try:
            ui.isVisible()
        except RuntimeError:  # the Qt object is gone
            _PANELS.remove((ui, controller))
            continue
        controller.adapter = adapter
        controller.set_node(node)
        ui.show()
        ui.raise_()
        ui.activateWindow()
        return
    ui, controller = create_panel(adapter, node)
    import hou
    from PySide6.QtCore import Qt

    # Owned by Houdini's main window: stays above Houdini only, not above other apps
    ui.setParent(hou.qt.mainWindow(), ui.windowFlags() | Qt.WindowType.Window)
    _PANELS.append((ui, controller))
    ui.show()


PYPANEL_NAME = "mono_grooming"


def _dock(ui: Any) -> None:
    """Move the floating window into a Python Panel tab next to the Network Editor (Houdini lets the
    user tear it off again)."""
    import os

    import hou

    path = os.path.join(os.path.dirname(__file__), "mono_grooming.pypanel")
    try:
        hou.pypanel.installFile(path)
        interface = hou.pypanel.interfaceByName(PYPANEL_NAME)
        editor = hou.ui.paneTabOfType(hou.paneTabType.NetworkEditor)
        pane = editor.pane() if editor is not None else None
        tab = pane.createTab(hou.paneTabType.PythonPanel) if pane is not None else \
            hou.ui.curDesktop().createFloatingPaneTab(hou.paneTabType.PythonPanel)
        tab.setActiveInterface(interface)
        tab.setIsCurrentTab()
    except Exception as e:
        ui.set_message(f"Dock failed: {e}", error=True)
        return
    for entry in list(_PANELS):
        if entry[0] is ui:
            _PANELS.remove(entry)
    ui.close()


__all__ = [
    "GroomController", "SELECTION_POLL_MS", "SETTING_RANGES", "SETTING_LABELS",
    "bind", "create_panel", "run", "lock_color", "report_text",
]
