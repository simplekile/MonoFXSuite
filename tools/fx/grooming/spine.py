"""
MONO Grooming panel, lock shapes (v0.2b, task B4): the controller's part. Mixed into `controller.GroomController`
before `layers.LayersMixin`. Qt-free and hou-free: what the Tool bar and its strip show for a selection, their
texts, the handle count over several locks, and the commands, each one adapter call (one undo step) inside `_run`.

The tools (mockup B of t78, the user's pick 2026-11-20; `ui_spine.py` has the layout and the review's fixes):
Select / Edit points / Draw lock / Paint, one at a time. Edit points and Draw lock are the viewer state of B3
(`apps/houdini/grooming_points_state.py`; its pure part `tools/fx/grooming/points_keys.py`), Paint is v0.2a's
brush (`layers.LayersMixin.paint_on`). Both modules are imported lazily: without them (outside Houdini, or before
B3 lands) the panel keeps the tool as its own view state and the strip's Reset, Handles and the drawn lock's values
still work through the adapter alone.

Words (plan "Design gate"): `edited` on a row = the lock's SHAPE was edited (a moved drawn lock too); `drawn` = a
lock drawn on bare skin; both neutral grey words (review 13). A lock with its own settings keeps its grey dot; its
filter word is `own`.
"""

from __future__ import annotations

import contextlib
import importlib
import math
from typing import Any

from tools.fx.grooming import config, logic, model

# The tools and drag modes: the names of points_keys (B3), kept here so the panel runs without it
TOOL_SELECT, TOOL_POINTS, TOOL_DRAW, TOOL_PAINT = "select", "points", "draw", "paint"
TOOLS = (TOOL_SELECT, TOOL_POINTS, TOOL_DRAW, TOOL_PAINT)
MODES = ("move", "rotate", "scale", "redraw")

# (wide label, narrow label, icon, tooltip)
TOOL_WORDS: dict[str, tuple[str, str, str, str]] = {
    TOOL_SELECT: ("Select", "Select", "pointer", "Select: pick locks in the viewport; ends the tool that is on (Esc)"),
    TOOL_POINTS: ("Edit points", "Points", "spline", "Edit points: the selected locks' control points in the viewport"
                  " (Enter)"),
    TOOL_DRAW: ("Draw lock", "Draw", "pencil", "Draw lock: a new lock on bare skin; it takes its skin at once"),
    TOOL_PAINT: ("Paint", "Paint", "brush", "Paint: the selected paint layer's mask in the viewport"),
}
MODE_WORDS: dict[str, tuple[str, str, str]] = {   # (label, icon, key held for one drag)
    "move": ("Move", "move", ""),
    "rotate": ("Rotate", "rotate-cw", "R"),
    "scale": ("Scale", "scale", "E"),
    "redraw": ("Redraw", "route", "Shift"),
}
SELECT_A_LOCK = "Select a lock"
HANDLES_TIP = (f"Handles: how many control points a lock shows. auto = one every {config.HANDLE_SPACING_CM:g} cm,"
               f" {config.HANDLES_MIN} to {config.HANDLES_MAX}. Minus / plus removes or adds one handle on each"
               " selected lock (− / + keys)")
TAPER_TIP = "Tip taper: the share of the width and thickness left at the tip; 0 = blunt, 1 = pointed"
AT_REST_TIP = "At rest in a shot: no Animated scalp wired into input 4 (drawn locks follow it)"
NOT_INSTALLED = ("the control points' viewer state is not installed in this Houdini: Reset, Handles and the drawn"
                 " lock's values still work from the panel")

SHORTCUTS: tuple[tuple[str, str], ...] = (
    ("Enter", "Edit points on the selected locks (again: Select)"),
    ("R / E / Shift + drag", "In Edit points: rotate, scale about the root, redraw (hold for one drag)"),
    ("− / +", "In Edit points: fewer / more handles on each selected lock"),
    ("Del", "Delete the selected drawn lock (its skin goes back to its neighbours)"),
    ("C in the viewport", "Radial menu: Edit points, Draw lock, Paint, Erase, Display, Isolate"),
)

DRAWN_RANGES: dict[str, tuple[float, float]] = {"width_cm": (0.1, 10.0), "thick_cm": (0.05, 5.0), "taper": (0.0, 1.0)}
DRAWN_LABELS: dict[str, str] = {"width_cm": "Width", "thick_cm": "Thickness", "taper": "Tip taper"}
DRAWN_UNITS: dict[str, str] = {"width_cm": "cm", "thick_cm": "cm", "taper": ""}


# ---------------------------------------------------------------------------
# Pure: texts and numbers
# ---------------------------------------------------------------------------
def _names(names: list[str], most: int = 3) -> str:
    shown = ", ".join(names[:most])
    return shown + (f" +{len(names) - most}" if len(names) > most else "")


def handles_summary(counts: list[int], own: list[int | None]) -> dict:
    """What the Handles field shows for these locks: `auto (5)`, `auto (4 to 6)` (every lock by its length), the
    number set for all of them, or `mixed` (some set their own, or different ones). `own` / `mixed` tell the view to
    show the value bold and the "auto" button (back to auto)."""
    if not counts:
        return {"text": "", "own": False, "mixed": False, "min": False, "max": False}
    lo, hi = min(counts), max(counts)
    out = {"min": hi <= config.HANDLES_MIN, "max": lo >= config.HANDLES_MAX}
    if all(o is None for o in own):
        return {**out, "text": f"auto ({lo})" if lo == hi else f"auto ({lo} to {hi})", "own": False, "mixed": False}
    if len(set(own)) == 1:
        return {**out, "text": f"{own[0]}", "own": True, "mixed": False}
    n = sum(o is not None for o in own)
    return {**out, "text": "mixed", "own": True, "mixed": True, "set": n}


def stepped_counts(counts: dict[int, int], delta: int) -> dict[int, list[int]]:
    """{target count: lock ids} for minus / plus on each lock (clamped to HANDLES_MIN..HANDLES_MAX); locks already at
    the end are left out."""
    out: dict[int, list[int]] = {}
    for lid, n in sorted(counts.items()):
        k = min(config.HANDLES_MAX, max(config.HANDLES_MIN, int(n) + int(delta)))
        if k != n:
            out.setdefault(k, []).append(lid)
    return out


def shape_text(lock: model.Lock, count: int) -> str:
    """The Shape detail of one lock: "measured spine", "edited, 5 handles", "as drawn, 4 handles"."""
    own = " (set here)" if lock.handles is not None else ""
    if lock.drawn:
        return f"{'edited' if lock.edited else 'as drawn'}, {count} handles{own}"
    if lock.edited:
        return f"edited, {count} handles{own}"
    return f"measured spine, {count} handles{own}" if own else "measured spine"


def shapes_text(locks: list[model.Lock]) -> str:
    """The Shape detail of several locks: "2 edited: hair_bang_02, hair_bang_04", "measured spines"."""
    edited = [lk.name for lk in locks if lk.edited]
    drawn = sum(lk.drawn for lk in locks)
    parts = [f"{len(edited)} edited: {_names(edited)}"] if edited else []
    if drawn:
        parts.append(f"{drawn} drawn")
    return "; ".join(parts) if parts else "measured spines"


def who_text(locks: list[model.Lock]) -> str:
    """The strip's first words: what Edit points acts on."""
    if not locks:
        return SELECT_A_LOCK
    edited = sum(lk.edited for lk in locks)
    if len(locks) == 1:
        return locks[0].name + (", edited" if edited else "")
    return f"{len(locks)} locks" + (f", {edited} edited" if edited else "")


def clean_value(key: str, value: Any) -> float | None:
    """A drawn lock's width / thickness (cm, over 0) or tip taper (0..1) as typed; None when it is not one."""
    try:
        v = float(str(value).strip().replace(",", "."))
    except (TypeError, ValueError):
        return None
    if not math.isfinite(v):
        return None
    if key == "taper":
        return min(1.0, max(0.0, v))
    return v if v > 0 else None


def no_lock_layers(data: model.GroomData) -> list[model.MaskLayer]:
    """Density layers that belonged to one lock that is gone with no orphan to hold it (a deleted drawn lock, t80 N4):
    they stay, with no lock; the tree shows them under All locks with "no lock"."""
    orphans = {o.id for o in data.orphans}
    out = []
    for m in data.density_layers():
        if m.scope == "locks" and not any(data.lock(i) is not None or i in orphans for i in m.locks):
            out.append(m)
    return out


# ---------------------------------------------------------------------------
# B3's modules, lazily
# ---------------------------------------------------------------------------
def points_keys():
    """`tools.fx.grooming.points_keys` (B3's pure part) or None."""
    try:
        return importlib.import_module("tools.fx.grooming.points_keys")
    except Exception:
        return None


class SpineMixin:
    """The Tool bar, Edit points, Draw lock and the lock-shape commands of GroomController (it provides adapter, view,
    node, selection, _run, refresh, data, lock_ids_of, _drawn, _infos, unit_cm, paint_layer_id, paint_needs)."""

    tool: str = TOOL_SELECT       # Edit points / Draw lock as the panel knows it (Paint: `paint_layer_id`)
    drag_mode: str = "move"
    _tool_dirty = False
    _spine_known: tuple | None = None   # drawn lock ids last shown (a new one while drawing becomes the selection)
    _scalp_cache: tuple | None = None

    # ------------------------------------------------------------------
    # State that lives on the instance (class attributes stay immutable)
    # ------------------------------------------------------------------
    @property
    def new_lock(self) -> dict:
        """What the next drawn lock gets (the strip's Next lock): view state of the session."""
        if "_new_lock" not in self.__dict__:
            self.__dict__["_new_lock"] = {"width_cm": config.DRAWN_WIDTH_CM, "thick_cm": config.DRAWN_THICK_CM,
                                          "taper": config.DRAWN_TAPER_DEFAULT}
        return self.__dict__["_new_lock"]

    @property
    def skin_from(self) -> dict[int, list[str]]:
        """Drawn lock id -> the locks that gave it skin (from Draw's result, this session): Properties' Skin from."""
        return self.__dict__.setdefault("_skin_from", {})

    def points_state(self):
        """B3's viewer state module, or None: the adapter's `points_state` (tests), else the Houdini module, only
        when the adapter is Houdini's own (outside Houdini the import would need hou)."""
        mod = getattr(self.adapter, "points_state", None)
        if mod is not None:
            return mod
        if getattr(self.adapter, "__name__", "") != "apps.houdini.grooming_adapter":
            return None
        try:
            return importlib.import_module("apps.houdini.grooming_points_state")
        except Exception:
            return None

    def _state_call(self, name: str, *args) -> Any:
        """Call the viewer state's `name`; None (and nothing raised) when there is none or it fails."""
        mod = self.points_state()
        fn = getattr(mod, name, None) if mod is not None else None
        if fn is None:
            return None
        try:
            result = fn(*args)
        except Exception as e:
            self.view.set_message(f"{TOOL_WORDS.get(self.tool, (name,))[0]}: {e}", error=True)
            return None
        return True if result is None else result

    def _key_hooks(self) -> dict | None:
        keys = points_keys()
        hooks = getattr(keys, "HOOKS", None) if keys is not None else None
        if hooks is None:
            hooks = getattr(self.points_state(), "HOOKS", None)
        return hooks if isinstance(hooks, dict) else None

    def _hook_keys(self) -> None:
        """The state tells the panel of a change made in the viewport (Esc, R / E / Shift, the wheel): points_keys'
        `HOOKS["tool"]` (a list of callables, or one), and `HOOKS["write"]` cooks a state's write in the panel's
        loading line."""
        hooks = self._key_hooks()
        if hooks is None:
            return
        got = hooks.get("tool")
        if isinstance(got, list):
            if self._on_tool_record not in got:
                got.append(self._on_tool_record)
        else:
            hooks["tool"] = self._on_tool_record
        hooks["write"] = self._on_state_write

    def _unhook_keys(self) -> None:
        hooks = self._key_hooks()
        if hooks is None:
            return
        got = hooks.get("tool")
        if isinstance(got, list):
            while self._on_tool_record in got:
                got.remove(self._on_tool_record)
        elif got == self._on_tool_record:
            hooks["tool"] = []
        if hooks.get("write") == self._on_state_write:
            hooks["write"] = None

    def _on_tool_record(self, record: Any = None) -> None:
        """A change in the viewer state (B3's `STATE`): shown on the next poll (a drag of the wheel must not rebuild
        the panel per notch)."""
        self.__dict__["_record"] = record
        self._tool_dirty = True

    def _on_state_write(self, node: Any = None, result: Any = None) -> None:
        """The state wrote the node (a drag's release, a draw): cook in the panel's loading line; a draw's result
        names the locks that gave skin (Properties' Skin from)."""
        if isinstance(result, dict) and result.get("id") is not None and result.get("gave"):
            self.skin_from[int(result["id"])] = list(result["gave"])
        with self._busy("Lock shape"):
            pass

    def tool_now(self) -> str:
        return TOOL_PAINT if getattr(self, "paint_layer_id", None) is not None else self.tool

    # ------------------------------------------------------------------
    # What the view shows
    # ------------------------------------------------------------------
    def _length_cm(self, lk: model.Lock) -> float:
        info = getattr(self, "_infos", {}).get(lk.id)
        if info is not None:
            return float(info.length) * self.unit_cm
        return float(lk.length) * self.unit_cm

    def handle_count(self, lk: model.Lock) -> int:
        try:
            return int(logic.lock_handle_count(lk, self._length_cm(lk)))
        except Exception:
            return logic.handle_count(self._length_cm(lk), lk.handles)

    def _selected_locks(self, data: model.GroomData) -> list[model.Lock]:
        return [lk for lk in (data.lock(i) for i in self.lock_ids_of(data, self.selection)) if lk is not None]

    def edit_targets(self, data: model.GroomData) -> tuple[list[int], str]:
        """(the locks Edit points shows handles on, why some selected ones show none): the selection's locks (a group
        counts as its locks) that the viewport draws; hidden or isolated-out ones are left out (review 8)."""
        if self.selection[0] not in ("locks", "group"):
            return [], ""
        ids = self.lock_ids_of(data, self.selection)
        drawn = self._drawn(data, ids)
        left = [i for i in ids if i not in drawn]
        why = ""
        if left:
            names = [data.lock(i).name for i in left if data.lock(i) is not None]
            out = "outside the isolate" if self._read_isolate() else "hidden"
            why = (f"{_names(names)} {'is' if len(names) == 1 else 'are'} {out}: no handles"
                   f" ({'press I to isolate it' if out != 'hidden' else 'turn its eye on to edit it'})")
        return drawn, why

    def tool_cells(self) -> list[dict]:
        """The Tool bar: one cell a tool, the one in hand on. Paint dimmed with the reason unless one paint layer is
        selected; a click on it still says why (review 7)."""
        now = self.tool_now()
        problem = ""
        if self.node is not None and now != TOOL_PAINT:
            try:
                problem = self.paint_needs()
            except Exception:
                problem = ""
        cells = []
        for t in TOOLS:
            wide, short, icon, tip = TOOL_WORDS[t]
            dim = t == TOOL_PAINT and bool(problem)
            cells.append({"id": t, "label": wide, "short": short, "icon": icon, "on": t == now, "dim": dim,
                          "tip": (f"Paint: {problem[0].lower() + problem[1:]}" if dim else tip),
                          "key": "Esc" if t == TOOL_SELECT and now != TOOL_SELECT else ""})
        return cells

    def tool_strip(self, data: model.GroomData | None = None) -> dict:
        """The tinted strip under the Tool bar: the settings of the tool in hand ({"tool": ...} alone: no strip of
        ours; Paint has v0.2a's Scalp strip)."""
        now = self.tool_now()
        if now == TOOL_DRAW:
            return {"tool": now, **self.new_lock, "tip": TAPER_TIP}
        if now != TOOL_POINTS or self.node is None:
            return {"tool": now}
        data = data or self._data or self.data()
        ids, _why = self.edit_targets(data)
        locks = [data.lock(i) for i in ids]
        counts = [self.handle_count(lk) for lk in locks]
        handles = handles_summary(counts, [lk.handles for lk in locks])
        edited = [lk.id for lk in locks if lk.edited]
        n = len(edited)
        auto_tip = "Handles back to auto: one every 8 cm, 4 to 12"
        if handles.get("mixed"):
            auto_tip += f" ({handles['set']} of the {len(locks)} locks have their own number)"
        held = getattr(self.__dict__.get("_record"), "held", "") or ""
        return {"tool": now, "who": who_text(locks), "lock_ids": ids, "mode": self.drag_mode,
                "held": held if held in MODES else "", "handles": handles,
                "handles_tip": HANDLES_TIP, "auto_tip": auto_tip,
                "reset": {"ids": edited, "n": n,
                          "tip": ("Reset shape: back to the measured spine (a drawn lock: the curve as drawn)"
                                  + (f" ({n} edited locks)" if n > 1 else "")) if n else
                          "Reset shape: nothing to reset (no edited lock selected)"}}

    def show_tools(self, data: model.GroomData | None = None) -> None:
        show = getattr(self.view, "show_tools", None)
        if show is None:
            return
        try:
            strip = self.tool_strip(data)
        except Exception:
            strip = {"tool": self.tool_now()}
        show(self.tool_cells(), strip)

    def scalp_info(self, data: model.GroomData) -> dict:
        """`adapter.animated_scalp(node)` while drawn locks exist (U2), kept per data shown: {"message": ...}."""
        drawn = tuple(lk.id for lk in data.locks if lk.drawn)
        read = getattr(self.adapter, "animated_scalp", None)
        if not drawn or read is None or self.node is None:
            return {}
        key = (drawn, getattr(self, "_last_json", None))
        if self._scalp_cache is not None and self._scalp_cache[0] == key:
            return self._scalp_cache[1]
        try:
            info = dict(read(self.node) or {})
        except Exception:
            info = {}
        self._scalp_cache = (key, info)
        return info

    def attach_spine(self, data: model.GroomData, rows: list[dict]) -> list[dict]:
        """Per lock row: `shape_edited`, `drawn`, `at_rest` (a drawn lock that stays at rest in a shot) and
        `editing` (its handles show); under All locks the density layers whose drawn lock was deleted."""
        at_rest = bool(self.scalp_info(data).get("message"))
        editing = set(self.edit_targets(data)[0]) if self.tool_now() == TOOL_POINTS else set()
        for row in rows:
            for child in row.get("children", []):
                if child.get("kind") != "locks":
                    continue
                lk = data.lock(child["id"])
                if lk is None:
                    continue
                child["shape_edited"] = lk.edited
                child["drawn"] = lk.drawn
                child["at_rest"] = lk.drawn and at_rest
                child["editing"] = lk.id in editing
        gone = no_lock_layers(data)
        if gone:
            for row in rows:
                if row.get("kind") == "defaults":
                    extra = []
                    for m in gone:
                        layer = self.layer_row(data, m)
                        layer["no_lock"] = True
                        extra.append(layer)
                    layers = row.setdefault("layers", [])
                    at = next((k for k, r in enumerate(layers) if r.get("layer") == "base"), len(layers))
                    layers[at:at] = extra
        return rows

    def spine_props(self, data: model.GroomData, props: dict) -> dict:
        """Lock / group Properties: the Shape detail, a drawn lock's Kind, Skin from and In shots, the Reset shape
        button (while no tool is on) and the Drawn shape values with Delete lock."""
        kind = props.get("kind")
        if kind not in ("locks", "group"):
            return props
        locks = self._selected_locks(data)
        if not locks:
            return props
        details = list(props.get("details", []))
        shape = shape_text(locks[0], self.handle_count(locks[0])) if len(locks) == 1 else shapes_text(locks)
        at = next((k + 1 for k, d in enumerate(details) if d[0] in ("Group", "Groups")), len(details))
        details.insert(at, ("Shape", shape))
        drawn = [lk for lk in locks if lk.drawn]
        scalp = self.scalp_info(data)
        if kind == "locks" and len(locks) == 1 and drawn:
            details[0] = ("Kind", "Drawn lock")
            gave = self.skin_from.get(drawn[0].id)
            if gave:
                details.append(("Skin from", ", ".join(gave)))
        if drawn and scalp.get("message"):
            details.append(("In shots", "at rest: no Animated scalp wired" if not scalp.get("wired") else
                            "at rest: the animated scalp's points differ", WARN_COLOR))
        props["details"] = details
        state = props.get("state")
        if isinstance(state, dict) and state:
            state["reset_ids"] = [lk.id for lk in locks if lk.edited]
            state["tool"] = self.tool_now()
            state["drawn_ids"] = [lk.id for lk in drawn] if kind == "locks" and len(drawn) == len(locks) else []
        if kind == "locks" and drawn and len(drawn) == len(locks):
            values = {}
            for key in ("width_cm", "thick_cm", "taper"):
                got = {round(float(getattr(lk, key)), 4) for lk in drawn}
                values[key] = {"value": float(getattr(drawn[0], key)), "mixed": len(got) > 1,
                               "range": DRAWN_RANGES[key], "label": DRAWN_LABELS[key], "unit": DRAWN_UNITS[key]}
            props["drawn_shape"] = {"ids": [lk.id for lk in drawn], "values": values,
                                    "note": "the next lock takes these" if self.tool_now() == TOOL_DRAW else ""}
        props["drawn_ids"] = [lk.id for lk in drawn] if kind == "locks" and len(drawn) == len(locks) else []
        return props

    def spine_overview(self, data: model.GroomData, rows: list[tuple[str, str]]) -> list[tuple[str, str]]:
        """Nothing selected: drawn and edited counts on the overview."""
        drawn = sum(lk.drawn for lk in data.locks)
        edited = sum(lk.edited for lk in data.locks)
        out = []
        for row in rows:
            if row[0] == "Locks" and drawn:
                row = ("Locks", f"{len(data.locks)}, {drawn} drawn")
            out.append(row)
        if edited:
            out.insert(1, ("Edited", f"{edited} lock{'s' if edited != 1 else ''}"))
        return out

    # ------------------------------------------------------------------
    # The Tool bar
    # ------------------------------------------------------------------
    def set_tool(self, tool: str) -> bool:
        """A Tool bar cell: the tool takes the viewport, the one that was on ends first (one tool at a time)."""
        if tool not in TOOLS:
            raise ValueError(tool)
        if self.node is None:
            return False
        now = self.tool_now()
        if tool == now:
            self.show_tools()
            return False
        if tool == TOOL_PAINT:
            problem = self.paint_needs()
            if problem:       # the dim cell says why on the message line (review 7)
                self.view.set_message(problem, error=True)
                self.show_tools()
                return False
            return bool(self.paint_on())
        if tool == TOOL_SELECT:
            done = bool(self.paint_off()) or self._end_shape_tool()
            self._show_tool_change()
            return done
        if getattr(self, "paint_layer_id", None) is not None:
            self.paint_off()
        if self.tool in (TOOL_POINTS, TOOL_DRAW):
            self._end_shape_tool(quiet=True)
        self._hook_keys()
        data = self.data()
        self.tool = tool
        installed = self.points_state() is not None
        if tool == TOOL_POINTS:
            ids, why = self.edit_targets(data)
            self._state_call("enter_points", self.node, ids)
            self._state_call("set_mode", self.drag_mode)
            if not ids:
                text = "Edit points: select a lock (a group: its locks)" + (f"; {why}" if why else "")
            else:
                names = [data.lock(i).name for i in ids]
                text = (f"Edit points on {_names(names)}: drag a handle; R rotate, E scale, Shift redraw; − / +"
                        " handles; Esc ends") + (f"; {why}" if why else "")
        else:
            self._state_call("enter_draw", self.node)
            self._state_call("set_new_lock", self.new_lock["width_cm"], self.new_lock["thick_cm"],
                             self.new_lock["taper"])
            self.__dict__["_draw_from"] = tuple(lk.id for lk in data.locks if lk.drawn)
            text = ("Draw lock: drag from the skin in the viewport; the new lock takes its skin at once and stays"
                    " selected; Esc ends")
        if not installed:
            text += f" ({NOT_INSTALLED})"
        self.view.set_message(text)
        self._show_tool_change(data)
        return True

    def toggle_tool(self, tool: str) -> bool:
        """Enter and the radial entries: the tool, or Select when it is already on."""
        return self.set_tool(TOOL_SELECT if self.tool_now() == tool else tool)

    def _end_shape_tool(self, quiet: bool = False) -> bool:
        """Edit points / Draw lock off (the viewer state left); False when neither was on."""
        if self.tool not in (TOOL_POINTS, TOOL_DRAW):
            return False
        self.tool = TOOL_SELECT
        if self.node is not None:
            self._state_call("exit_tool")
        if not quiet:
            self.view.set_message("Select: the viewport picks locks again")
        return True

    def tool_off(self) -> bool:
        """Esc: the shape tool ends first (then Paint, isolate, the selection: `escape`)."""
        if self._end_shape_tool():
            self._show_tool_change()
            return True
        return False

    def _show_tool_change(self, data: model.GroomData | None = None) -> None:
        if self.node is None or not self.node_alive():
            self.show_tools()
            return
        data = data or self.data()
        self.view.show_tree(self.tree_rows(data))      # the editing rows' icons
        self.view.set_selection(self.selection)
        self.view.show_properties(self.properties(data))
        self.show_tools(data)

    def paint_on(self, layer_id: int | None = None, quiet: bool = False) -> bool:
        """Paint ends Edit points / Draw lock first (one tool at a time)."""
        if not self.paint_needs(layer_id):
            self._end_shape_tool(quiet=True)
        ok = super().paint_on(layer_id, quiet)   # type: ignore[misc]
        self.show_tools()
        return ok

    def paint_off(self) -> bool:
        done = super().paint_off()   # type: ignore[misc]
        if done:
            self.show_tools()
        return done

    def _on_paint_exit(self) -> None:
        super()._on_paint_exit()   # type: ignore[misc]
        self.show_tools()

    def spine_follow(self, data: model.GroomData | None = None) -> None:
        """The selection changed: while Edit points is on its handles follow (hidden locks get none, and the
        message says why)."""
        if self.tool != TOOL_POINTS or self.node is None:
            self.show_tools(data)
            return
        data = data or self.data()
        ids, why = self.edit_targets(data)
        self._state_call("set_locks", ids)
        if why:
            self.view.set_message(why)
        self.view.show_tree(self.tree_rows(data))
        self.view.set_selection(self.selection)
        self.show_tools(data)

    def tool_reset(self) -> None:
        """Another node, or none: the shape tool ends (its state belonged to the old node)."""
        self._unhook_keys()
        if self.tool in (TOOL_POINTS, TOOL_DRAW):
            self.tool = TOOL_SELECT
            mod = self.points_state()
            fn = getattr(mod, "exit_tool", None) if mod is not None else None
            if fn is not None:
                try:
                    fn()
                except Exception:
                    pass
        self._scalp_cache = None
        self._spine_known = None

    def set_drag_mode(self, mode: str) -> bool:
        """What a drag does in Edit points (sticky; a held R / E / Shift acts for one drag only)."""
        if mode not in MODES:
            raise ValueError(mode)
        self.drag_mode = mode
        self._state_call("set_mode", mode)
        self.show_tools()
        return True

    def set_new_lock(self, **fields) -> dict:
        """The next drawn lock's width / thickness (cm) and tip taper, from the strip (view state, no undo)."""
        for key, value in fields.items():
            if key not in DRAWN_RANGES:
                raise KeyError(key)
            v = clean_value(key, value)
            if v is None:
                self.view.set_message(f"{DRAWN_LABELS[key]}: a number over 0", error=True)
                continue
            self.new_lock[key] = v
        self._state_call("set_new_lock", self.new_lock["width_cm"], self.new_lock["thick_cm"], self.new_lock["taper"])
        self.show_tools()
        return dict(self.new_lock)

    # ------------------------------------------------------------------
    # Commands: one adapter call each (its own undo step)
    # ------------------------------------------------------------------
    def _spine_call(self, name: str, what: str, *args, **kwargs) -> dict | None:
        fn = getattr(self.adapter, name, None)
        if fn is None:
            self.view.set_message(f"{what} needs a newer MONO Grooming adapter (v0.2b)", error=True)
            return None
        result = self._run(f"{config.HDA_LABEL}: {what}", lambda: fn(self.node, *args, **kwargs))
        if self.node is not None:
            self.refresh()
        return result

    @contextlib.contextmanager
    def _one_step(self, label: str):
        """Several adapter calls as one undo step: the adapter's `undo_group`, else Houdini's through it."""
        group = getattr(self.adapter, "undo_group", None)
        if group is None:
            undos = getattr(getattr(self.adapter, "hou", None), "undos", None)
            group = getattr(undos, "group", None)
        if group is None:
            yield
            return
        with group(label):
            yield

    def reset_shape(self, ids=None) -> bool:
        """Back to the measured spine (a drawn lock: the curve as drawn), one undo step; the hair comes from the
        cache."""
        data = self.data()
        ids = [int(i) for i in ids] if ids else [lk.id for lk in self._selected_locks(data) if lk.edited]
        if not ids:
            self.view.set_message("Reset shape: no edited lock selected")
            return False
        res = self._spine_call("reset_points", "Reset lock", ids)
        if res is None:
            return False
        self.view.set_message(f"{res.get('message', 'Reset')} (Ctrl+Z takes it back)")
        return bool(res.get("locks"))

    def step_handles(self, delta: int) -> bool:
        """Minus / plus: one handle fewer / more on each lock being edited (one undo step)."""
        if self.node is None:
            return False
        data = self.data()
        ids = self.edit_targets(data)[0] if self.tool_now() == TOOL_POINTS else self.lock_ids_of(data, self.selection)
        locks = [data.lock(i) for i in ids if data.lock(i) is not None]
        if not locks:
            self.view.set_message("Handles: select a lock", error=True)
            return False
        plan = stepped_counts({lk.id: self.handle_count(lk) for lk in locks}, delta)
        if not plan:
            end = config.HANDLES_MAX if delta > 0 else config.HANDLES_MIN
            self.view.set_message(f"Handles: {end} is the {'most' if delta > 0 else 'fewest'} a lock has")
            return False
        fn = getattr(self.adapter, "set_handle_count", None)
        if fn is None:
            self.view.set_message("Handles needs a newer MONO Grooming adapter (v0.2b)", error=True)
            return False
        label = config.UNDO_SPINE["handles"]

        def run():
            msgs = []
            with self._one_step(label):
                for count, lock_ids in sorted(plan.items()):
                    msgs.append(fn(self.node, lock_ids, count).get("message", ""))
            return msgs

        msgs = self._run(label, run)
        self.refresh()
        if msgs is None:
            return False
        self.view.set_message("; ".join(m for m in msgs if m) + " (Ctrl+Z takes it back)")
        self._state_call("set_locks", self.edit_targets(self.data())[0])
        return True

    def handles_auto(self) -> bool:
        """Back to the number by length on the selected locks that set their own."""
        data = self.data()
        ids = self.edit_targets(data)[0] if self.tool_now() == TOOL_POINTS else self.lock_ids_of(data, self.selection)
        own = [i for i in ids if data.lock(i) is not None and data.lock(i).handles is not None]
        if not own:
            self.view.set_message("Handles: already auto (one every 8 cm)")
            return False
        res = self._spine_call("set_handle_count", "Set handle count", own, None)
        if res is None:
            return False
        self.view.set_message(f"{res.get('message', 'Handles')}: back to auto (Ctrl+Z takes it back)")
        self._state_call("set_locks", self.edit_targets(self.data())[0])
        return True

    def set_drawn_value(self, key: str, value) -> bool:
        """A drawn lock's width / thickness / tip taper from its Drawn shape section, one undo step; the next lock
        drawn takes it too (review 4)."""
        if key not in DRAWN_RANGES:
            raise KeyError(key)
        v = clean_value(key, value)
        if v is None:
            self.view.set_message(f"{DRAWN_LABELS[key]}: a number over 0", error=True)
            return False
        data = self.data()
        ids = [lk.id for lk in self._selected_locks(data) if lk.drawn]
        if not ids:
            return False
        res = self._spine_call("set_drawn", "Drawn lock settings", ids, **{key: v})
        if res is None:
            return False
        self.new_lock[key] = v
        self._state_call("set_new_lock", self.new_lock["width_cm"], self.new_lock["thick_cm"], self.new_lock["taper"])
        self.show_tools()
        text = res.get("message", "Drawn lock")
        if key == "width_cm" and res.get("locks"):
            text += "; regions out of date (its footprint changed): Update regions"
        self.view.set_message(text)
        return bool(res.get("locks"))

    def drawn_selected(self) -> list[int]:
        if self.node is None or self.selection[0] != "locks":
            return []
        data = self._data or self.data()
        return [i for i in self.selection[1] if data.lock(i) is not None and data.lock(i).drawn]

    def delete_drawn(self, ids=None) -> bool:
        """Delete drawn locks (the tree's trash, Del, the right-click menu, Properties' Delete lock): one undo step
        that gives their skin back to the neighbours; the message names those that took it."""
        ids = [int(i) for i in ids] if ids else self.drawn_selected()
        if not ids:
            self.view.set_message("Delete: only a drawn lock can be deleted (a lock of the hair mesh goes with its"
                                  " mesh piece)", error=True)
            return False
        res = self._spine_call("delete_drawn_locks", "Delete drawn lock", ids)
        if res is None:
            return False
        for i in res.get("locks", []):
            self.skin_from.pop(i, None)
        self.selection = ("none", ())
        self.view.set_selection(self.selection)
        self.view.show_properties(self.properties(self.data()))
        self._state_call("set_locks", [])
        self.show_tools()
        self.view.set_message(f"{res.get('message', 'Deleted')} (Ctrl+Z brings it back)")
        return bool(res.get("locks"))

    # ------------------------------------------------------------------
    # What the viewer state did (poll)
    # ------------------------------------------------------------------
    def poll_spine(self) -> None:
        """The viewer state ended or changed its tool / mode / next lock in the viewport: the panel follows."""
        mod = self.points_state()
        now = getattr(mod, "current_tool", None) if mod is not None else None
        changed = False
        if now is not None and self.tool in (TOOL_POINTS, TOOL_DRAW):
            try:
                got = now()
            except Exception:
                got = self.tool
            if got in (None, "", TOOL_SELECT):
                self.tool = TOOL_SELECT
                changed = True
        if self._tool_dirty:
            self._tool_dirty = False
            rec = self.__dict__.get("_record")
            if rec is not None:
                mode = getattr(rec, "mode", None)
                if mode in MODES:
                    self.drag_mode = mode
                for key in ("width_cm", "thick_cm", "taper"):
                    v = clean_value(key, getattr(rec, key, None))
                    if v is not None:
                        self.new_lock[key] = v
                t = getattr(rec, "tool", None)
                if t in (TOOL_SELECT, TOOL_POINTS, TOOL_DRAW) and t != self.tool:
                    self.tool = t
                    changed = True
                text = getattr(rec, "message", "")
                if text:
                    self.view.set_message(str(text))
            changed = True
        if changed:
            if self.node is not None and self.node_alive():
                self._show_tool_change()
            else:
                self.show_tools()

    def spine_after_refresh(self, data: model.GroomData) -> None:
        """A drawn lock appeared while Draw lock is on: it becomes the selection (review 4) and the line says what
        it took; a drawn lock appeared or the node opened: the U2 line when it stays at rest in a shot."""
        drawn = tuple(lk.id for lk in data.locks if lk.drawn)
        known, self._spine_known = self._spine_known, drawn
        if known is None or self.tool != TOOL_DRAW:
            return
        new = [i for i in drawn if i not in known]
        if not new:
            return
        lk = data.lock(new[-1])
        rec = self.__dict__.get("_record")
        self.selection = ("locks", (lk.id,))
        self.view.set_selection(self.selection)
        self.view.show_properties(self.properties(data))
        text = getattr(rec, "message", "") or f"Drew {lk.name}"
        scalp = self.scalp_info(data).get("message", "")
        self.view.set_message(text + (f". {scalp}" if scalp else ""), error=False)

    def spine_notes(self) -> None:
        """Opening a node with drawn locks: the U2 line when they stay at rest in a shot."""
        if self.node is None:
            return
        try:
            data = self.data()
        except Exception:
            return
        self._spine_known = tuple(lk.id for lk in data.locks if lk.drawn)
        text = self.scalp_info(data).get("message", "")
        if text:
            self._warn(text)

    def _warn(self, text: str) -> None:
        try:
            self.view.set_message(text, warn=True)
        except TypeError:   # a view without the warning tone
            self.view.set_message(text, error=True)


WARN_COLOR = "#f5b14c"   # STATUS_COLORS[STATUS_PINNED]: Qt-free copy for the In shots detail (test holds it equal)

__all__ = ["SpineMixin", "TOOLS", "MODES", "TOOL_SELECT", "TOOL_POINTS", "TOOL_DRAW", "TOOL_PAINT", "TOOL_WORDS",
           "MODE_WORDS", "SHORTCUTS", "handles_summary", "stepped_counts", "shape_text", "shapes_text", "who_text",
           "clean_value", "no_lock_layers", "points_keys"]
