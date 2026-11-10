"""
MONO Grooming panel controller: the panel's actions on one MONO Grooming node, through the adapter only.

The controller holds no copy of the node's data: every action reads `adapter.read_data(node)`, changes
it and stores it back with one `adapter.write_data(node, data, label)` (one undo step). It never imports
Qt or `hou`, so tests drive it with a fake adapter and a recording view. `run()` is the Houdini entry:
it imports `apps.houdini.grooming_adapter` and the Qt panel only then.

What the controller calls on its view (ui.GroomingUI, or a fake in tests):
  show_node(path, asset), show_tree(rows), set_selection(selection), show_properties(props),
  set_message(text, error=False), set_regions_stale(stale), set_display_state(mode, color_by),
  set_publish_version(version, note)
"""

from __future__ import annotations

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
SETTING_LABELS: dict[str, str] = {
    "density": "Density",
    "width_mult": "Width ×",
    "thick_mult": "Thickness ×",
    "twist_add": "Twist +",
    "clump": "Clump",
    "length_mult": "Length ×",
    "frizz": "Frizz",
}
SETTING_UNITS: dict[str, str] = {"density": "/cm²", "twist_add": "rad"}

DISPLAY_LABELS: dict[str, str] = {
    "mesh": "Mesh", "guide": "Guide", "hair_preview": "Hair preview", "hair": "Hair full",
}
COLOR_BY_LABELS: dict[str, str] = {"lock": "Lock", "group": "Group"}

# Selection kinds: what the properties column edits
SEL_NONE, SEL_DEFAULTS, SEL_GROUP, SEL_LOCKS, SEL_ORPHAN = "none", "defaults", "group", "locks", "orphan"

ORPHANS_ROW = "__orphans__"


def lock_color(lock_id: int) -> tuple[float, float, float]:
    """Colour of a lock when colouring by lock: logic.lock_color, the viewport's colour too."""
    return logic.lock_color(lock_id)


def report_text(counts: dict[str, int]) -> str:
    """One line for a DetectReport's counts."""
    total = counts.get("ok", 0) + counts.get("unsure", 0) + counts.get("new", 0)
    parts = [f"{counts.get('ok', 0)} ok"]
    if counts.get("unsure"):
        parts.append(f"{counts['unsure']} unsure (confirm them)")
    if counts.get("new"):
        parts.append(f"{counts['new']} new")
    if counts.get("orphaned"):
        parts.append(f"{counts['orphaned']} orphaned (kept with their settings)")
    return f"Detect: {total} lock{'s' if total != 1 else ''} · " + " · ".join(parts)


def _fmt(value: float) -> str:
    return f"{value:.3g}" if abs(value) < 1000 else f"{value:,.0f}"


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
        if node is not None:
            self.set_node(node)

    # ------------------------------------------------------------------
    # Node and reading
    # ------------------------------------------------------------------
    def set_node(self, node: Any) -> None:
        self.node = node
        self._node_lost = False
        self.selection = (SEL_NONE, ())
        self._viewport_ids = []
        state = getattr(self.adapter, "display_state", None)  # optional: the node's own display parms
        if state is not None:
            try:
                self.display_mode, self.color_by = state(node)
            except Exception:
                pass
        self.refresh()
        self.view.set_display_state(self.display_mode, self.color_by)
        self.refresh_publish_version()

    def data(self) -> model.GroomData:
        return self.adapter.read_data(self.node)

    def node_path(self) -> str:
        path = getattr(self.node, "path", None)
        return path() if callable(path) else str(self.node or "")

    def refresh(self, data: model.GroomData | None = None) -> None:
        """Show the node again: tree, properties, warnings. Measured values are read from the cook."""
        if self.node is None:
            return
        data = data or self.data()
        self._last_json = data.to_json()
        try:
            self._infos = {info.id: info for info in self.adapter.lock_infos(self.node)}
        except Exception:
            self._infos = {}
        self._drop_gone_selection(data)
        self.view.show_node(self.node_path(), data.asset)
        self.view.show_tree(self.tree_rows(data))
        self.view.set_selection(self.selection)
        self.view.show_properties(self.properties(data))
        self.view.set_regions_stale(data.regions_stale)

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
        """Defaults, then group › lock rows, then Orphans. Locks of a group the data does not list
        still get a row (named by the group id), so no lock is out of sight."""
        rows: list[dict] = [{"kind": SEL_DEFAULTS, "id": "", "name": "Defaults", "badges": [],
                             "meta": "all locks"}]
        group_ids = [g.id for g in data.groups]
        group_ids += sorted({lk.group for lk in data.locks} - set(group_ids))
        for gid in group_ids:
            g = data.group(gid)
            locks = [lk for lk in data.locks if lk.group == gid]
            children = [{
                "kind": SEL_LOCKS, "id": lk.id, "name": lk.name or f"lock {lk.id}",
                "color": self.row_color(data, lk), "visible": lk.visible, "display": lk.display,
                "badges": (["edited"] if lk.overrides else []) + ([lk.match] if lk.match in ("unsure", "new") else []),
            } for lk in locks]
            badges = ["edited"] if g and g.overrides else []
            if any("unsure" in c["badges"] for c in children):
                badges.append("unsure")
            if any("new" in c["badges"] for c in children):
                badges.append("new")
            rows.append({
                "kind": SEL_GROUP, "id": gid, "name": (g.name if g else gid) or "(no group)",
                "color": tuple(g.color) if g else (0.6, 0.6, 0.6),
                "visible": g.visible if g else True, "display": g.display if g else None,
                "badges": badges, "meta": f"{len(locks)} lock{'s' if len(locks) != 1 else ''}",
                "children": children,
            })
        if data.orphans:
            rows.append({
                "kind": ORPHANS_ROW, "id": ORPHANS_ROW, "name": "Orphans", "badges": [],
                "meta": f"{len(data.orphans)} gone from the hair mesh",
                "children": [{"kind": SEL_ORPHAN, "id": o.id, "name": o.name or f"lock {o.id}",
                              "badges": ["edited"] if o.overrides else [], "meta": o.group}
                             for o in data.orphans],
            })
        return rows

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

    def _value_and_source(self, data: model.GroomData, key: str) -> tuple[float, str]:
        kind, ids = self.selection
        if kind == SEL_DEFAULTS:
            if key in data.defaults:
                return data.defaults[key], "defaults"
            return model.BUILTIN_DEFAULTS[key], "builtin"
        if kind == SEL_GROUP:
            g = data.group(ids[0])
            if g is not None and key in g.overrides:
                return g.overrides[key], "group"
            if key in data.defaults:
                return data.defaults[key], "defaults"
            return model.BUILTIN_DEFAULTS[key], "builtin"
        values = [(data.resolve(i)[key], data.source_of(i, key)) for i in ids if data.lock(i) is not None]
        value, source = values[0]
        if any(v != value for v, _s in values[1:]):
            return value, "mixed"
        if any(s != source for _v, s in values[1:]):
            return value, "mixed"
        return value, source

    def properties(self, data: model.GroomData | None = None) -> dict:
        """What the properties column shows for the selection: a title, a slider per setting (value,
        where it comes from, whether Reset applies) and the measured values."""
        data = data or self.data()
        kind, ids = self.selection
        if kind == SEL_NONE:
            return {"kind": SEL_NONE, "title": "", "settings": [], "measured": []}
        if kind == SEL_ORPHAN:
            o = next(o for o in data.orphans if o.id == ids[0])
            kept = ", ".join(f"{SETTING_LABELS[k]} {_fmt(v)}" for k, v in o.overrides.items()) or "none"
            return {"kind": kind, "title": o.name or f"lock {o.id}",
                    "subtitle": f"Orphan from {o.group or 'no group'}: gone from the hair mesh",
                    "settings": [], "measured": [("Kept settings", kept)],
                    "targets": [(lk.id, lk.name, lk.match) for lk in data.locks]}
        own, levels = self._own_level(data)
        settings = []
        for key in model.SETTING_KEYS:
            value, source = self._value_and_source(data, key)
            settings.append({
                "key": key, "label": SETTING_LABELS[key], "unit": SETTING_UNITS.get(key, ""),
                "value": value, "source": source, "range": SETTING_RANGES[key],
                "resettable": any(key in lv for lv in levels),
            })
        if kind == SEL_DEFAULTS:
            title, subtitle = "Defaults", f"{len(data.locks)} locks · a group or lock can override each value"
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
            g = data.group(locks[0].group)
            subtitle = "Lock" + (f" · {g.name if g else locks[0].group}" if len(locks) == 1 else "")
            if len(locks) == 1 and locks[0].match != "ok":
                subtitle += f" · {locks[0].match} match"
            infos = [self._infos[i] for i in ids if i in self._infos]
        return {"kind": kind, "title": title, "subtitle": subtitle, "own": own,
                "settings": settings, "measured": self._measured(kind, infos)}

    @staticmethod
    def _measured(kind: str, infos: list[logic.LockInfo]) -> list[tuple[str, str]]:
        if not infos:
            return [("Measured", "not cooked yet")]
        if len(infos) == 1 and kind == SEL_LOCKS:
            i = infos[0]
            return [("Width", _fmt(i.width)), ("Thickness", _fmt(i.thick)), ("Twist", f"{_fmt(i.twist)} rad"),
                    ("Length", _fmt(i.length)), ("Strands", f"{i.strands:,}"),
                    ("Region", f"{_fmt(i.region_area_cm2)} cm²")]
        n = len(infos)
        return [("Width (mean)", _fmt(sum(i.width for i in infos) / n)),
                ("Thickness (mean)", _fmt(sum(i.thick for i in infos) / n)),
                ("Length (mean)", _fmt(sum(i.length for i in infos) / n)),
                ("Strands", f"{sum(i.strands for i in infos):,}"),
                ("Region", f"{_fmt(sum(i.region_area_cm2 for i in infos))} cm²")]

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
            return "defaults"
        if kind == SEL_GROUP:
            g = data.group(ids[0])
            return (g.name if g else ids[0]) or "no group"
        if len(ids) == 1:
            lk = data.lock(ids[0])
            return lk.name if lk else str(ids[0])
        return f"{len(ids)} locks"

    def set_value(self, key: str, value: float) -> bool:
        """Write *value* for *key* at the selection's own level (defaults, the group or every selected lock)."""
        if key not in model.BUILTIN_DEFAULTS:
            raise KeyError(key)
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
            self.view.set_message(f"{SETTING_LABELS[key]} = {_fmt(float(value))} on {holder['name']}")
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
            self.view.set_message(f"Orphan {orphan_id} deleted (Ctrl+Z brings it back)")
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
            return call()
        except Exception as e:
            self.view.set_message(f"{what} failed: {e}", error=True)
            return None

    def detect(self) -> logic.DetectReport | None:
        report = self._run("Detect", lambda: self.adapter.detect(self.node))
        if report is None:
            return None
        self.refresh()
        text = report_text(report.counts)
        if self.data().regions_stale:
            text += " · regions out of date: Split regions"
        self.view.set_message(text, error=False)
        return report

    def split_regions(self) -> bool:
        if self._run("Split regions", lambda: self.adapter.split_regions(self.node) or True) is None:
            return False
        self.refresh()
        self.view.set_message("Regions split again and frozen")
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

    def publish(self, version: str | None) -> logic.PublishResult | None:
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
        self.view.show_properties(self.properties(data))
        lock_ids = self.lock_ids_of(data, self.selection)
        if kind in (SEL_LOCKS, SEL_GROUP):
            self._run("Select", lambda: self.adapter.select_locks(self.node, lock_ids))
            # Remember what the viewport reports now (hidden locks are not in its geometry), so the next
            # poll does not take that subset for a new viewport selection and replace the panel's.
            try:
                self._viewport_ids = sorted(self.adapter.selected_lock_ids(self.node))
            except Exception:
                self._viewport_ids = lock_ids

    def select_locks(self, ids) -> None:
        self.select(SEL_LOCKS, tuple(ids))

    def select_group(self, gid: str) -> None:
        self.select(SEL_GROUP, (gid,))

    def poll(self) -> None:
        """Timer tick: the node's data changed outside (undo, the HDA's parms) → show it again; the
        viewport selection changed → select those locks here."""
        if self.node is None:
            return
        try:
            data = self.data()
        except Exception as e:
            if not self._node_lost:
                self._node_lost = True
                self.view.set_message(f"{self.node_path() or 'The node'} can no longer be read: {e}", error=True)
            return
        self._node_lost = False
        if data.to_json() != self._last_json:
            self.refresh(data)
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


# ----------------------------------------------------------------------
# Houdini entry
# ----------------------------------------------------------------------
_PANELS: list = []  # (ui, controller) of open floating windows, so run() reuses one


def bind(ui: Any, controller: GroomController) -> None:
    """Wire the Qt panel's events to the controller."""
    ui.on("select", controller.select)
    ui.on("set_value", controller.set_value)
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
