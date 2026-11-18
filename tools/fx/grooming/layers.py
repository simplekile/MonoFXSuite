"""
MONO Grooming panel: density layers (v0.2a), the controller's part. Mixed into `controller.GroomController`.

The lock tree has three levels (plan v0.2a, "Panel"): a lock row (All locks / a group / a lock) > its density
layers > each density layer's mask layers (paint / fill). The base "Automatic" sits at the bottom of All locks'
layers, locked. Every command goes through the adapter's layer functions (`mask_add`, `mask_set`, ...; each is
one undo step of its own) inside `_run` (the loading line and the display cook), then the panel is shown again.
The selected paint layer is what the brush paints into (`paint_enter`); a density layer paints nothing.

What is view state and never written to the node: the brush (`set_brush`: grey, eraser, radius, softness, the
scalp's view and X-ray) and whether Paint is on.

Picked mockup (t70, the user, 2026-11-16): A, "E2 kept": all three levels as rows, the selected row's blend /
opacity (a mask layer) or D / opacity (a density layer) in a bar above the tree, Properties below (narrow) or
beside (wide) the tree.
"""

from __future__ import annotations

from typing import Any

from tools.fx.grooming import config, model

SEL_LAYER = "layer"
MODE_LABELS: dict[str, str] = {"normal": "Normal", "multiply": "Multiply", "add": "Add", "subtract": "Subtract",
                               "min": "Min", "max": "Max"}
MODE_SHORT: dict[str, str] = {"normal": "", "multiply": "×", "add": "+", "subtract": "−", "min": "min", "max": "max"}
KIND_WORDS: dict[str, str] = {"density": "Density layer", "paint": "Paint layer", "fill": "Fill layer",
                              "base": "Automatic"}
VIEW_LABELS: dict[str, str] = {"density": "Result", "layer": "Layer", "roots": "Roots"}
OPACITY_RANGE = (0.0, 1.0)
DENSITY_RANGE = (0.0, 400.0)       # the slider's span; a typed value up to config.MASK_DENSITY_MAX stays
RADIUS_RANGE = (0.1, 5.0)          # cm
SETTING_LOOKUP, SETTING_UNDO, SETTING_DEFORM_UNDO = "lookup", "undo_cache_gb", "undo_deform_gb"
NODE_SETTINGS = (SETTING_LOOKUP, SETTING_UNDO, SETTING_DEFORM_UNDO)
NODE_SETTING_LABELS = {SETTING_LOOKUP: "Fit lookup per lock", SETTING_UNDO: "Undo cache, GB",
                       SETTING_DEFORM_UNDO: "Deformed undo, GB"}
GB_RANGE = (0.01, 16.0)   # what the settings page offers for the two limits, typed or dragged (t71 defect 2)


def owner_key(layer: model.MaskLayer) -> tuple:
    """The lock-tree row a density layer sits under: ("all",), ("group", gid), ("locks", first lock id)."""
    if layer.scope == "group":
        return ("group", layer.group)
    if layer.scope == "locks":
        return ("locks", layer.locks[0] if layer.locks else None)
    return ("all",)


def owner_name(data: model.GroomData, layer: model.MaskLayer) -> str:
    key = owner_key(layer)
    if key[0] == "group":
        g = data.group(key[1])
        return (g.name if g else key[1]) or "(no group)"
    if key[0] == "locks":
        lk = data.lock(key[1]) if key[1] is not None else None
        if lk is not None:
            return lk.name or f"lock {lk.id}"
        orphan = next((o for o in data.orphans if o.id == key[1]), None)
        return f"{orphan.name or key[1]} (missing)" if orphan else f"lock {key[1]}"
    return "All locks"


def _gb(n_bytes: float) -> str:
    return f"{n_bytes / 2 ** 30:.2f}"


class LayersMixin:
    """The density-layer actions of GroomController (it provides adapter, view, node, selection, _run,
    refresh, data, display_mode, set_display, _sync_viewport)."""

    paint_layer_id: int | None = None
    _display_before_paint: str | None = None
    _hooks_set = False

    # ------------------------------------------------------------------
    # What the tree and Properties show
    # ------------------------------------------------------------------
    def layer_row(self, data: model.GroomData, layer: model.MaskLayer) -> dict:
        row = {"kind": SEL_LAYER, "id": layer.id, "layer": layer.kind, "name": layer.name, "on": layer.on,
               "density": layer.density, "opacity": layer.opacity, "mode": layer.mode, "value": layer.value,
               "legacy": layer.legacy, "painting": layer.id == self.paint_layer_id, "masks": []}
        if layer.kind == "density":
            row["masks"] = [self.layer_row(data, m) for m in reversed(data.mask_layers(layer.id))]
            row["parent_on"] = True
        if layer.kind in ("paint", "fill"):
            parent = data.mask(layer.parent) if layer.parent is not None else None
            row["parent_on"] = bool(parent.on) if parent else True
        return row

    def layers_of(self, data: model.GroomData, key: tuple) -> list[dict]:
        """The density layers under one lock-tree row, top first (the upper one wins); All locks ends with the
        locked Automatic row."""
        rows = [self.layer_row(data, d) for d in reversed(data.density_layers()) if owner_key(d) == key]
        if key == ("all",):
            base = next((m for m in data.masks if m.kind == "base"), None) or model.base_layer()
            rows.append(self.layer_row(data, base))
        return rows

    def attach_layers(self, data: model.GroomData, rows: list[dict]) -> list[dict]:
        """Put each row's density layers on it (`"layers"`) for the tree."""
        for row in rows:
            kind = row["kind"]
            if kind == "defaults":
                row["layers"] = self.layers_of(data, ("all",))
            elif kind == "group":
                row["layers"] = self.layers_of(data, ("group", row["id"]))
            for child in row.get("children", []):
                if child["kind"] in ("locks", "orphan"):
                    child["layers"] = self.layers_of(data, ("locks", child["id"]))
        return rows

    def owner_choices(self, data: model.GroomData) -> list[tuple[str, dict]]:
        """(label, owner) a density layer can be given: All locks, each group, each lock."""
        out: list[tuple[str, dict]] = [("All locks", {"scope": "all", "group": "", "locks": []})]
        for g in data.groups:
            out.append((f"Group {g.name or g.id}", {"scope": "group", "group": g.id, "locks": []}))
        for lk in data.locks:
            out.append((lk.name or f"lock {lk.id}", {"scope": "locks", "group": "", "locks": [lk.id]}))
        return out

    def layer_properties(self, data: model.GroomData) -> dict:
        lid = self.selection[1][0]
        layer = data.mask(lid)
        if layer is None:
            return {"kind": "none", "title": "", "settings": [], "measured": []}
        row = self.layer_row(data, layer)
        props: dict[str, Any] = {"kind": SEL_LAYER, "layer": row, "title": layer.name, "settings": [],
                                 "measured": []}
        if layer.kind == "base":
            props["subtitle"] = "Bottom of All locks · the automatic groom"
            props["note"] = ("Each lock grows its own Density setting here (All locks, or a group or lock that sets"
                             " its own). A density layer above changes it only where its mask is white. This row"
                             " cannot be painted, moved, deleted or turned off: change Density on All locks, or"
                             " add a density layer.")
            return props
        if layer.kind == "density":
            owners = self.owner_choices(data)
            key = owner_key(layer)
            index = next((i for i, (_l, o) in enumerate(owners) if o["scope"] == layer.scope and (
                layer.scope == "all" or (layer.scope == "group" and o["group"] == layer.group)
                or (layer.scope == "locks" and o["locks"][:1] == [key[1]]))), None)
            if index is None:   # a missing lock's layer: its owner is not a row any more, show it as it is
                owners.append((owner_name(data, layer), {"scope": layer.scope, "group": layer.group,
                                                         "locks": list(layer.locks)}))
                index = len(owners) - 1
            props.update({
                "subtitle": f"{KIND_WORDS['density']} · {owner_name(data, layer)} · its mask: "
                            f"{len(data.mask_layers(layer.id))} layer{'s' if len(data.mask_layers(layer.id)) != 1 else ''}"
                            + (" · from an older build" if layer.legacy else ""),
                "owners": [label for label, _o in owners], "owner_index": index,
                "owner_help": {"all": "every lock on the skin gives D together",
                               "group": "the group's locks on the skin give D together",
                               "locks": "this lock alone gives D"}[layer.scope],
                "picks": list(config.MASK_DENSITY_PICKS), "range": DENSITY_RANGE,
                "note": "Result: below + (D − below) × mask × opacity. Black in the mask: this layer does not apply"
                        " there, the density below shows. D 0 painted white: no hair.",
            })
            return props
        parent = data.mask(layer.parent) if layer.parent is not None else None
        props.update({
            "subtitle": f"{KIND_WORDS[layer.kind]} · mask of {parent.name if parent else '?'}"
                        + (f" ({parent.density:g} / cm²)" if parent else "")
                        + (f" · {owner_name(data, parent)}" if parent else ""),
            "modes": [(k, MODE_LABELS[k]) for k in config.MASK_MODES],
            "value_picks": list(config.MASK_VALUE_PICKS),
        })
        if layer.kind == "paint":
            props["painting"] = self.paint_layer_id == layer.id
            props["brush"] = self.brush_state()
            props["radius_range"] = RADIUS_RANGE
        else:
            props["note"] = "One grey over all the skin. The brush paints only into a paint layer."
        return props

    # ------------------------------------------------------------------
    # Selection
    # ------------------------------------------------------------------
    def select_layer(self, layer_id: int) -> None:
        data = self.data()
        layer = data.mask(layer_id)
        if layer is None:
            self.selection = ("none", ())
            self.view.show_properties(self.properties(data))
            return
        self.selection = (SEL_LAYER, (layer_id,))
        if self.paint_layer_id is not None and self.paint_layer_id != layer_id:
            # the brush follows the selection: another paint layer takes it, anything else ends Paint
            if layer.kind == "paint":
                self.paint_on(layer_id, quiet=True)
            else:
                self.paint_off()
        self.view.show_properties(self.properties(data))
        self._sync_viewport(data)

    def layer_lock_ids(self, data: model.GroomData, layer_id: int) -> list[int]:
        """The locks a layer's owner row stands for (focus in the viewport): [] for All locks."""
        layer = data.mask(layer_id)
        if layer is not None and layer.kind in ("paint", "fill") and layer.parent is not None:
            layer = data.mask(layer.parent)
        if layer is None or layer.kind != "density":
            return []
        if layer.scope == "group":
            return sorted(lk.id for lk in data.locks if lk.group == layer.group)
        if layer.scope == "locks":
            return sorted(i for i in layer.locks if data.lock(i) is not None)
        return []

    def _selected_layer(self, data: model.GroomData | None = None) -> model.MaskLayer | None:
        if self.selection[0] != SEL_LAYER:
            return None
        return (data or self.data()).mask(self.selection[1][0])

    # ------------------------------------------------------------------
    # Commands (each one adapter call: one undo step)
    # ------------------------------------------------------------------
    def _call(self, name: str):
        fn = getattr(self.adapter, name, None)
        if fn is None:
            self.view.set_message(f"This MONO Grooming adapter has no {name}: update the suite", error=True)
        return fn

    def _layer_run(self, what: str, call) -> Any:
        """One layer command: the adapter's own undo step, cooked inside the loading line, then shown again."""
        result = self._run(f"{config.HDA_LABEL}: {what}", call)
        if self.node is not None:
            self.refresh()
        return result

    def _new_owner(self, data: model.GroomData) -> dict | str:
        """The owner of a new density layer: the selected lock row, or the owner of the selected layer."""
        kind, ids = self.selection
        layer = self._selected_layer(data)
        if layer is not None:
            if layer.kind in ("paint", "fill") and layer.parent is not None:
                layer = data.mask(layer.parent)
            if layer is not None and layer.kind == "density":
                return {"scope": layer.scope, "group": layer.group, "locks": list(layer.locks)}
            return {"scope": "all", "group": "", "locks": []}
        if kind == "group":
            return {"scope": "group", "group": ids[0], "locks": []}
        if kind == "locks":
            if len(ids) != 1:
                return "Select one lock (or its group) for a density layer of its own"
            return {"scope": "locks", "group": "", "locks": [ids[0]]}
        return {"scope": "all", "group": "", "locks": []}

    def add_density_layer(self) -> int | None:
        add = self._call("mask_add")
        if add is None or self.node is None:
            return None
        data = self.data()
        owner = self._new_owner(data)
        if isinstance(owner, str):
            self.view.set_message(owner, error=True)
            return None
        lid = self._layer_run("New density layer", lambda: add(
            self.node, kind="density", density=config.MASK_DENSITY_DEFAULT, **owner))
        if lid is None:
            return None
        data = self.data()
        layer = data.mask(lid)
        self.select_layer(lid)
        self.view.set_selection(self.selection)
        self.view.set_message(f"New density layer {layer.name} on {owner_name(data, layer)}, "
                              f"{layer.density:g} / cm². Its mask is black, so it changes nothing until a mask"
                              " layer is painted or filled: add a paint layer")
        return lid

    def add_mask_layer(self, kind: str = "paint") -> int | None:
        add = self._call("mask_add")
        if add is None or self.node is None:
            return None
        data = self.data()
        layer = self._selected_layer(data)
        parent = None
        if layer is not None and layer.kind == "density":
            parent = layer
        elif layer is not None and layer.kind in ("paint", "fill") and layer.parent is not None:
            parent = data.mask(layer.parent)
        if parent is None:
            self.view.set_message("Select a density layer (or one of its mask layers) to add a mask layer to",
                                  error=True)
            return None
        lid = self._layer_run(f"New {kind} layer", lambda: add(self.node, kind=kind, parent=parent.id, value=1.0))
        if lid is None:
            return None
        new = self.data().mask(lid)
        self.select_layer(lid)
        self.view.set_selection(self.selection)
        if kind == "paint":
            self.view.set_message(f"New paint layer {new.name} in the mask of {parent.name}: nothing painted yet."
                                  " Paint turns the viewport's tool into the brush")
        else:
            self.view.set_message(f"New fill layer {new.name} in the mask of {parent.name}: white over all the"
                                  f" skin, so {parent.name} now applies everywhere ({parent.density:g} / cm²)")
        return lid

    def delete_layer(self, layer_id: int | None = None) -> bool:
        remove = self._call("mask_remove")
        data = self.data()
        layer = data.mask(layer_id) if layer_id is not None else self._selected_layer(data)
        if remove is None or layer is None:
            return False
        if layer.kind == "base":
            self.view.set_message("Automatic cannot be deleted: it is the groom every density layer changes",
                                  error=True)
            return False
        gone = {layer.id} | ({m.id for m in data.mask_layers(layer.id)} if layer.kind == "density" else set())
        if self.paint_layer_id in gone:
            self.paint_off()
        parent = layer.parent
        owner = data.mask(parent) if parent is not None else layer
        if self._layer_run(f"Delete {layer.name}", lambda: remove(self.node, layer.id)) is None:
            return False
        # the selection goes to what held the layer: its density layer, or its lock row
        if layer.kind in ("paint", "fill") and parent is not None:
            self.select_layer(parent)
        else:
            key = owner_key(owner)
            sel = {"all": ("defaults", ()), "group": ("group", (key[-1],)),
                   "locks": ("locks", (key[-1],))}[key[0]]
            self.select(*sel)
        self.view.set_selection(self.selection)
        self.view.set_message(f"Deleted {layer.name}" + (" and its mask" if layer.kind == "density" else "")
                              + " (Ctrl+Z brings it back)")
        return True

    def move_layer(self, up: bool, layer_id: int | None = None) -> bool:
        """One step up or down among the layers of the same row (the upper layer wins)."""
        move = self._call("mask_move")
        data = self.data()
        layer = data.mask(layer_id) if layer_id is not None else self._selected_layer(data)
        if move is None or layer is None:
            return False
        if layer.kind == "base":
            self.view.set_message("Automatic stays at the bottom: it is what every layer changes", error=True)
            return False
        if layer.kind == "density":
            same = [d.id for d in data.density_layers()]
            mine = [d.id for d in data.density_layers() if owner_key(d) == owner_key(layer)]
            k = mine.index(layer.id)
            other = (mine[k + 1] if k + 1 < len(mine) else None) if up else (mine[k - 1] if k > 0 else None)
            index = same.index(other) if other is not None else None
        else:
            mine = [m.id for m in data.mask_layers(layer.parent)]
            k = mine.index(layer.id)
            index = (k + 1 if k + 1 < len(mine) else None) if up else (k - 1 if k > 0 else None)
        if index is None:
            self.view.set_message(f"{layer.name} is already at the {'top' if up else 'bottom'} of its row")
            return False
        if self._layer_run(f"Move {layer.name} {'up' if up else 'down'}",
                           lambda: move(self.node, layer.id, index) or True) is None:
            return False
        self.view.set_selection(self.selection)
        self.view.set_message(f"{layer.name} moved {'up' if up else 'down'}"
                              + (": the upper layer wins" if layer.kind == "density" else ""))
        return True

    def set_layer(self, layer_id: int, **fields) -> bool:
        """Change a layer's row: name, on, opacity, density (D), mode, value, owner (scope / group / locks)."""
        put = self._call("mask_set")
        data = self.data()
        layer = data.mask(layer_id)
        if put is None or layer is None:
            return False
        if layer.kind == "base":
            self.view.set_message("Automatic has no settings of its own: its density is each lock's Density",
                                  error=True)
            return False
        what = ", ".join(sorted(fields))
        changed = self._layer_run(f"{layer.name}: {what}", lambda: put(self.node, layer_id, **fields))
        if not changed:
            return False
        self.view.set_selection(self.selection)
        new = self.data().mask(layer_id)
        self.view.set_message(self._layer_said(self.data(), new, fields))
        return True

    @staticmethod
    def _layer_said(data: model.GroomData, layer: model.MaskLayer, fields: dict) -> str:
        if "on" in fields:
            return f"{layer.name} is {'on' if layer.on else 'off: the groom grows as if it were not there'}"
        if "name" in fields:
            return f"Renamed to {layer.name}"
        parts = []
        if "density" in fields:
            parts.append(f"density {layer.density:g} / cm²")
        if "opacity" in fields:
            parts.append(f"opacity {round(layer.opacity * 100):d} %")
        if "mode" in fields:
            parts.append(f"blend {MODE_LABELS.get(layer.mode, layer.mode)}")
        if "value" in fields:
            parts.append(f"value {layer.value:g}")
        if {"scope", "group", "locks"} & set(fields):
            parts.append(f"owner {owner_name(data, layer)}")
        return f"{layer.name}: " + ", ".join(parts)

    def set_layer_owner(self, layer_id: int, index: int) -> bool:
        owners = self.owner_choices(self.data())
        if not 0 <= index < len(owners):
            return False
        return self.set_layer(layer_id, **owners[index][1])

    def rename_layer(self, layer_id: int, name: str) -> bool:
        name = (name or "").strip()
        if not name:
            # the row was edited to "": show the node's name again (t71 defect 1); nothing is written
            data = self.data()
            layer = data.mask(layer_id)
            self.view.show_tree(self.tree_rows(data))
            self.view.set_selection(self.selection)
            self.view.set_message(f"A layer needs a name: it stays {layer.name}" if layer else "A layer needs a name",
                                  error=True)
            return False
        return self.set_layer(layer_id, name=name)

    def set_layer_on(self, layer_id: int, on: bool) -> bool:
        return self.set_layer(layer_id, on=bool(on))

    def paint_layer_action(self, action: str, layer_id: int | None = None) -> bool:
        """Fill white / Clear / Invert on a paint layer (one undo step each)."""
        name = {"fill": "mask_fill", "clear": "mask_clear", "invert": "mask_invert"}[action]
        fn = self._call(name)
        data = self.data()
        layer = data.mask(layer_id) if layer_id is not None else self._selected_layer(data)
        if fn is None or layer is None or layer.kind != "paint":
            return False
        words = {"fill": "filled white", "clear": "cleared (nothing painted)", "invert": "inverted where painted"}
        if self._layer_run(f"{action.capitalize()} {layer.name}", lambda: fn(self.node, layer.id) or True) is None:
            return False
        self.view.set_selection(self.selection)
        self.view.set_message(f"{layer.name} {words[action]}")
        return True

    # ------------------------------------------------------------------
    # Paint: the viewer state on the selected paint layer
    # ------------------------------------------------------------------
    def _hooks(self) -> dict | None:
        hooks = getattr(self.adapter, "HOOKS", None)
        if hooks is None:
            hooks = getattr(getattr(self.adapter, "grooming_masks", None), "HOOKS", None)
        return hooks

    def _install_hooks(self) -> None:
        hooks = self._hooks()
        if hooks is not None:
            hooks["stroke"] = self._on_stroke
            hooks["exit"] = self._on_paint_exit

    def _on_stroke(self, node) -> None:
        """The state stored a stroke: cook in the panel's loading line (the state does not cook then)."""
        with self._busy("Stroke"):
            pass
        layer = self.data().mask(self.paint_layer_id) if self.paint_layer_id is not None else None
        self.view.set_message(f"Stroke on {layer.name if layer else 'the layer'}: Ctrl+Z takes it back")

    def _on_paint_exit(self) -> None:
        """Paint ended in the viewport (Esc, another tool, another node)."""
        if self.paint_layer_id is None:
            return
        self.paint_layer_id = None
        self._restore_display()
        self._show_paint()
        # the line said "Painting ..." (t71 note 3)
        self.view.set_message("Paint ended in the viewport (Esc, another tool or another node)")

    def paint_on(self, layer_id: int | None = None, quiet: bool = False) -> bool:
        enter = self._call("paint_enter")
        data = self.data()
        layer = data.mask(layer_id) if layer_id is not None else self._selected_layer(data)
        if enter is None or layer is None:
            return False
        if layer.kind != "paint":
            self.view.set_message("The brush paints only into a paint layer: select one (or add one)", error=True)
            return False
        self._install_hooks()
        if self.paint_layer_id is None and self.display_mode == "hair":
            # while painting the panel shows Hair preview: the brush draws on the skin under the hair
            self._display_before_paint = "hair"
            self.set_display("hair_preview")
        ok = self._run("Paint", lambda: bool(enter(self.node, layer.id)))
        if not ok:
            exit_ = getattr(self.adapter, "paint_exit", None)
            if exit_ is not None:
                exit_(self.node)
            self.paint_layer_id = None
            self._restore_display()
            self._show_paint()
            if ok is not None:
                self.view.set_message("Paint needs a Scene Viewer showing this node", error=True)
            return False
        self.paint_layer_id = layer.id
        self._show_paint()
        if not quiet:
            self.view.set_message(f"Painting {layer.name}: LMB paints, Ctrl the other way, Esc ends. Each stroke"
                                  " is one undo step")
        return True

    def paint_off(self) -> bool:
        if self.paint_layer_id is None:
            return False
        exit_ = getattr(self.adapter, "paint_exit", None)
        self.paint_layer_id = None
        if exit_ is not None:
            self._run("Paint off", lambda: exit_(self.node) or True)
        self._restore_display()
        self._show_paint()
        return True

    def toggle_paint(self) -> bool:
        return self.paint_off() if self.paint_layer_id is not None else self.paint_on()

    def _restore_display(self) -> None:
        before, self._display_before_paint = self._display_before_paint, None
        if before and self.display_mode == "hair_preview":
            self.set_display(before)

    def _show_paint(self) -> None:
        if hasattr(self.view, "set_paint_state"):
            self.view.set_paint_state(self.paint_layer_id is not None, self.brush_state())
        if self.node is not None:
            data = self.data()
            self.view.show_tree(self.tree_rows(data))
            self.view.set_selection(self.selection)
            self.view.show_properties(self.properties(data))

    def poll_paint(self) -> None:
        """Paint may end without the panel (the hook covers it; this catches an adapter reloaded under it)."""
        read = getattr(self.adapter, "paint_layer", None)
        if read is None or self.node is None or self.paint_layer_id is None:
            return
        try:
            now = read(self.node)
        except Exception:
            return
        if now != self.paint_layer_id:
            self._on_paint_exit()

    # ------------------------------------------------------------------
    # Brush and the scalp's view (session state: not saved, no undo)
    # ------------------------------------------------------------------
    def brush_state(self) -> dict:
        read = getattr(self.adapter, "brush", None)
        state = {"radius_cm": config.BRUSH_RADIUS_CM, "value": config.BRUSH_VALUE, "soft": config.BRUSH_SOFT,
                 "erase": False, "xray": False, "view": "density"}
        if read is not None:
            try:
                state.update(read())
            except Exception:
                pass
        return state

    def set_brush(self, **fields) -> dict:
        put = self._call("set_brush")
        if put is None:
            return self.brush_state()
        view = fields.get("view")
        what = f"Scalp shows {VIEW_LABELS.get(view, view)}" if view else "Brush"
        # choosing Result or Roots counts the groom's roots (it may grow locks): in the loading line
        state = self._run(what, lambda: put(**fields)) if view else put(**fields)
        if hasattr(self.view, "set_paint_state"):
            self.view.set_paint_state(self.paint_layer_id is not None, self.brush_state())
        if view == "roots":
            self.view.set_message("Scalp shows a dot a root of the full groom")
        elif view == "layer":
            self.view.set_message("Scalp shows the painted layer alone: white 1, black 0, dark where not painted")
        return state or self.brush_state()

    # ------------------------------------------------------------------
    # Settings of the node (undo cache, lookup) and notes for the message line
    # ------------------------------------------------------------------
    def settings_info(self) -> dict:
        """What the settings page shows: the node's values (None when this adapter cannot read them) and what
        the undo cache holds."""
        info: dict[str, Any] = {"editable": hasattr(self.adapter, "set_node_setting")}
        read = getattr(self.adapter, "node_settings", None)
        if read is not None and self.node is not None:
            try:
                info.update(read(self.node))
            except Exception:
                pass
        usage = getattr(self.adapter, "undo_cache_usage", None)
        if usage is not None and self.node is not None:
            try:
                info["usage"] = usage(self.node)
            except Exception:
                info["usage"] = None
        return info

    @staticmethod
    def usage_text(use: dict | None, deformed: bool = False) -> str:
        if not use:
            return "Nothing held yet (the node has not cooked in this session)"
        if deformed:
            held, limit, n = use.get("deformed_bytes", 0), use.get("deformed_limit_bytes", 0), use.get("deformed_states", 0)
            if not n:
                text = f"Holds 0 of {_gb(limit)} GB: no deformed state held (Shot deform off, or not read yet)"
            else:
                text = (f"Holds {_gb(held)} of {_gb(limit)} GB: {n} deformed state{'s' if n != 1 else ''} of the"
                        " whole groom")
            # plan B6: the limit is applied when a state is stored, never on its own
            return text + ". A lowered limit frees nothing until the next deformed state is stored"
        text = (f"Holds {_gb(use.get('bytes', 0))} of {_gb(use.get('limit_bytes', 0))} GB: shown now "
                f"{_gb(use.get('live_bytes', 0))} GB, {use.get('undo_states', 0)} earlier states "
                f"{_gb(use.get('undo_bytes', 0))} GB")
        if use.get("capture_bytes"):
            text += f". Deform captures {_gb(use['capture_bytes'])} GB (outside the limit)"
        if use.get("dropped"):
            text += f". {use['dropped']} dropped: an undo past them grows the hair again"
        return text

    def set_node_setting(self, name: str, value) -> bool:
        if name not in NODE_SETTINGS:
            raise KeyError(name)
        put = self._call("set_node_setting")
        if put is None or self.node is None:
            return False
        label = NODE_SETTING_LABELS[name]
        if name != SETTING_LOOKUP:
            value = min(max(float(value), GB_RANGE[0]), GB_RANGE[1])
        if self._run(f"{config.HDA_LABEL}: {label}", lambda: put(self.node, name, value) or True) is None:
            return False
        shown = ("on" if value else "off") if name == SETTING_LOOKUP else f"{float(value):g}"
        self.view.set_message(f"{label}: {shown}" + (
            ". Strand points move a little; roots and strand counts stay" if name == SETTING_LOOKUP else ""))
        if hasattr(self.view, "show_settings"):
            self.view.show_settings(self.settings_info())
        return True

    def load_notes(self) -> None:
        """Opening a node: what the artist should know about it, on the message line (never a dialog)."""
        notes = []
        for name in ("mask_dropped", "mask_problem"):
            fn = getattr(self.adapter, name, None)
            if fn is None or self.node is None:
                continue
            try:
                text = fn(self.node)
            except Exception:
                text = ""
            if text:
                notes.append(text)
        info = self.settings_info()
        if info.get("lookup_kept") and info.get("lookup_text"):
            notes.append(info["lookup_text"][0].upper() + info["lookup_text"][1:])
        if notes:
            self.view.set_message(" · ".join(notes), error=True)
