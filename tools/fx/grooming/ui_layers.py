"""
MONO Grooming panel, density layers (v0.2a): the view's part. `ui.GroomingUI` calls these; they build Qt widgets
and fire events back through `ui._fire` (the controller's `layers.LayersMixin` answers). No data is kept here.

Mockup A of t70 ("E2 kept", the user's pick, 2026-11-16):
  - the lock tree holds three levels: a lock row > its density layers > each density layer's mask layers
    (paint / fill); the eye column sits at the left edge; Automatic is the last row of All locks' layers,
    a padlock instead of an eye;
  - a row bar above the tree edits the selected layer's blend / opacity (a mask layer) or D / opacity (a
    density layer); Properties hold the rest (D quick picks, owner, a fill's value, the brush);
  - while Paint is on: a strip under the view bar (what the scalp shows: Result / Layer / Roots, the scalp's
    X-ray, the legend), and Properties can be folded to one line.
Everything here is view state (fold, the armed Clear button) or a command to the controller.
"""

from __future__ import annotations

from PySide6.QtCore import QRect, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QLinearGradient, QPainter
from PySide6.QtWidgets import (
    QButtonGroup,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QSizePolicy,
    QToolButton,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from tools.fx.auto_material.ui import ACCENT, LUCIDE, TEXT_LABEL, TEXT_META, TEXT_PRIMARY, _lucide_icon
from tools.fx.grooming import logic
from tools.fx.grooming.layers import GB_RANGE, MODE_LABELS, MODE_SHORT, SEL_LAYER, VIEW_LABELS

LUCIDE.update({
    "brush": '<path d="m9.06 11.9 8.07-8.06a2.85 2.85 0 1 1 4.03 4.03l-8.06 8.08"/><path d="M7.07 14.94c-1.66 0-3 1.35-3'
             ' 3.02 0 1.33-2.5 1.52-2 2.02 1.08 1.1 2.49 2.02 4 2.02 2.2 0 4-1.8 4-4.04a3.01 3.01 0 0 0-3-3.02z"/>',
    "eraser": '<path d="m7 21-4.3-4.3c-1-1-1-2.5 0-3.4l9.6-9.6c1-1 2.5-1 3.4 0l5.6 5.6c1 1 1 2.5 0 3.4L13 21"/>'
              '<path d="M22 21H7"/><path d="m5 11 9 9"/>',
    "paint-bucket": '<path d="m19 11-8-8-8.6 8.6a2 2 0 0 0 0 2.8l5.2 5.2c.8.8 2 .8 2.8 0L19 11Z"/><path d="m5 2 5 5"/>'
                    '<path d="M2 13h15"/><path d="M22 20a2 2 0 1 1-4 0c0-1.6 1.7-2.4 2-4 .3 1.6 2 2.4 2 4Z"/>',
    "lock": '<rect width="18" height="11" x="3" y="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/>',
    "chevron-up": '<path d="m18 15-6-6-6 6"/>',
    "arrow-down": '<path d="M12 5v14"/><path d="m19 12-7 7-7-7"/>',
    "arrow-up": '<path d="m5 12 7-7 7 7"/><path d="M12 19V5"/>',
    "arrow-left": '<path d="m12 19-7-7 7-7"/><path d="M19 12H5"/>',
    "flip-horizontal": '<path d="M8 3H5a2 2 0 0 0-2 2v14c0 1.1.9 2 2 2h3"/><path d="M16 3h3a2 2 0 0 1 2 2v14a2 2 0 0'
                       ' 1-2 2h-3"/><path d="M12 20v2"/><path d="M12 14v2"/><path d="M12 8v2"/><path d="M12 2v2"/>',
})

DENSITY_RAMP_HEX = ["#%02x%02x%02x" % tuple(int(round(c * 255)) for c in rgb) for rgb in logic.DENSITY_RAMP]
UNPAINTED_HEX = "#%02x%02x%02x" % tuple(int(round(c * 255)) for c in logic.LAYER_UNPAINTED)
CLEAR_ARM_MS = 4000


def _ui():
    from tools.fx.grooming import ui as U   # ui imports this module at its top: import it late
    return U


def _fmt_d(value: float) -> str:
    return f"{value:g}" if value < 1000 else f"{value / 1000:.1f}k".replace(".0k", "k")


# ---------------------------------------------------------------------------
# Tree rows
# ---------------------------------------------------------------------------
def layer_parts(row: dict) -> list[tuple[str, str]]:
    """What the status column says on a layer row, right to left: painting, then the numbers."""
    parts: list[tuple[str, str]] = []
    if row.get("painting"):
        parts.append(("painting", TEXT_PRIMARY))   # the word in the text colour: ACCENT on SELECTED is 3.95:1
    kind = row["layer"]
    if kind == "base":
        parts.append(("per lock", TEXT_LABEL))   # the tooltip has the sentence (it was cut to "each lock's D…")
    elif kind == "density":
        # the value alone (the column is narrow: "40.4 /c…" was cut); the unit is in the cell's tooltip
        text = _fmt_d(row['density']) + (f", {round(row['opacity'] * 100)}%" if row["opacity"] < 1 else "")
        parts.append((text, TEXT_PRIMARY))
    else:
        short = MODE_SHORT.get(row["mode"], "")
        bits = ([short] if short else []) + ([f"{round(row['opacity'] * 100)}%"] if short or row["opacity"] < 1 else [])
        if kind == "fill":
            bits.append(f"= {row['value']:g}")
        if bits:
            parts.append((" ".join(bits), TEXT_LABEL))
    return parts


def make_layer_item(ui, row: dict) -> QTreeWidgetItem:
    U = _ui()
    z = ui.z
    item = QTreeWidgetItem()
    kind = row["layer"]
    off = not row.get("on", True) or not row.get("parent_on", True)
    row = dict(row, parts=layer_parts(row), dimmed=off)
    item.setData(U.COL_NAME, U.ROLE_ROW, row)
    item.setText(U.COL_NAME, row["name"])
    item.setFont(U.COL_NAME, z.font("body"))
    flags = item.flags() & ~Qt.ItemFlag.ItemIsDragEnabled & ~Qt.ItemFlag.ItemIsDropEnabled
    if kind != "base":
        flags |= Qt.ItemFlag.ItemIsEditable          # F2 / double click renames
    item.setFlags(flags)
    if kind == "base":
        icon = _lucide_icon("lock", z.px(15), TEXT_LABEL)
        item.setForeground(U.COL_NAME, QColor(TEXT_LABEL))
        item.setToolTip(U.COL_NAME, "Automatic: each lock's own Density, under every density layer. Locked")
    elif kind == "density":
        icon = _lucide_icon("layers", z.px(15), TEXT_META if off else TEXT_LABEL)
        item.setToolTip(U.COL_NAME, f"Density layer: {row['density']:g} strands / cm² where its mask is white"
                                    " (double click or F2 renames)")
        item.setToolTip(U.COL_STATUS, f"Density: {row['density']:g} strands / cm² where its mask is white, opacity"
                                      f" {round(row['opacity'] * 100)}%")
    elif kind == "fill":
        v = max(0.0, min(1.0, float(row["value"])))
        icon = U._swatch((v, v, v), z.px(14), 0.35 if off else 1.0)
        item.setToolTip(U.COL_NAME, f"Fill layer: {row['value']:g} over all the skin, {MODE_LABELS[row['mode']]}")
    else:
        icon = _lucide_icon("brush", z.px(15), ACCENT if row.get("painting") else (TEXT_META if off else TEXT_LABEL))
        item.setToolTip(U.COL_NAME, "Paint layer: select it and press Paint to paint it in the viewport")
    item.setIcon(U.COL_NAME, icon)
    if off:
        item.setForeground(U.COL_NAME, QColor(U.DIM))
    if kind == "base":
        item.setData(U.COL_EYE, U.ROLE_ICON, U._fixed_icon("lock", z.px(14), U.FAINT))
        item.setData(U.COL_EYE, U.ROLE_EYE, ("lock", U.FAINT, z.px(14)))
        item.setToolTip(U.COL_EYE, "Automatic is always on")
    else:
        on = row.get("on", True)
        color = U.FAINT if on and not row.get("parent_on", True) else TEXT_LABEL
        item.setData(U.COL_EYE, U.ROLE_ICON, U._eye_icon(on, z.px(16), color))
        item.setData(U.COL_EYE, U.ROLE_EYE, ("eye" if on else "eye-off", color, z.px(16)))
        item.setToolTip(U.COL_EYE, ("On: click to turn it off" if on else "Off: click to turn it on")
                        + ("" if row.get("parent_on", True) else " (its density layer is off)"))
    item.setData(U.COL_EYE, U.ROLE_QUIET, False)
    ui._rows[(SEL_LAYER, row["id"])] = item
    for mask in row.get("masks", []):
        item.addChild(make_layer_item(ui, mask))
    return item


def add_layers(ui, item: QTreeWidgetItem, row: dict, collapsed: set) -> None:
    """A lock-tree row's density layers as its first children (before its groups or locks)."""
    for layer in row.get("layers", []):
        item.addChild(make_layer_item(ui, layer))


def expand_layers(ui, collapsed: set) -> None:
    """Once the items are in the tree (Qt ignores setExpanded before): layers open unless closed by hand, and a
    lock holding layers too."""
    for key, item in ui._rows.items():
        if item.childCount() and (key[0] == SEL_LAYER or key[0] in ("locks", "orphan")):
            item.setExpanded(key not in collapsed)


# ---------------------------------------------------------------------------
# Tree tools (the head of the tree) and the row bar above the tree
# ---------------------------------------------------------------------------
def build_tree_tools(ui, head: QHBoxLayout) -> None:
    def tool(icon: str, tip: str, event: str, *args) -> QToolButton:
        b = ui._icon_button(icon, tip)
        b.clicked.connect(lambda: ui._fire(event, *args))
        head.addWidget(b)
        return b

    ui._layer_tools = {
        "density": tool("layers", "New density layer: on the selected row (All locks, a group, one lock)",
                        "add_density_layer"),
        "paint": tool("plus", "New paint layer: in the selected density layer's mask (a fill layer: right click)",
                      "add_mask_layer", "paint"),
        "up": tool("chevron-up", "Move up: the layer (the upper layer wins)", "move_layer", True),
        "down": tool("chevron-down", "Move down: the layer", "move_layer", False),
        "delete": tool("trash", "Delete: the layer (Del); a density layer goes with its mask. Ctrl+Z brings it back",
                       "delete_layer"),
    }
    update_tree_tools(ui, {})


def update_tree_tools(ui, props: dict) -> None:
    tools = getattr(ui, "_layer_tools", None)
    if not tools:
        return
    layer = props.get("layer") if props.get("kind") == SEL_LAYER else None
    kind = layer["layer"] if layer else None
    tools["paint"].setEnabled(kind in ("density", "paint", "fill"))
    for name in ("up", "down", "delete"):
        tools[name].setEnabled(kind in ("density", "paint", "fill"))
    tools["density"].setEnabled(not (props.get("kind") == "locks" and len(props.get("state", {}).get("ids", ())) > 1))


class _RowBar(QWidget):
    """The row bar: the layer's icon and name, then its quick values. When the name and the values do not fit on
    one line (the tree pane is ~270 px at 760 px wide) the values go to a second line, so the name keeps the
    pane's width (t71 defect 6: it was cut to 4 characters)."""

    def __init__(self, ui) -> None:
        super().__init__()
        from PySide6.QtWidgets import QBoxLayout
        self._ui = ui
        self.setObjectName("RowBar")
        self._outer = QBoxLayout(QBoxLayout.Direction.LeftToRight, self)
        self._outer.setContentsMargins(4, 0, 2, 0)
        self._outer.setSpacing(6)
        self.head = QWidget()
        self.head_lay = QHBoxLayout(self.head)
        self.head_lay.setContentsMargins(0, 0, 0, 0)
        self.head_lay.setSpacing(6)
        self.tools = QWidget()
        self.tools_lay = QHBoxLayout(self.tools)
        self.tools_lay.setContentsMargins(0, 0, 0, 0)
        self.tools_lay.setSpacing(6)
        self._outer.addWidget(self.head, stretch=1)
        self._outer.addWidget(self.tools)
        self.name = None

    def needed(self) -> int:
        """Width of everything on one line: icon, the whole name, the values."""
        name = self.name.fontMetrics().horizontalAdvance(self.name.text()) if self.name is not None else 0
        return self._ui.z.px(15) + 6 + name + 6 + self.tools.sizeHint().width() + 8

    def fit(self, width: int | None = None) -> None:
        from PySide6.QtWidgets import QBoxLayout
        width = width if width is not None else self.width()
        one = width >= self.needed()
        self._outer.setDirection(QBoxLayout.Direction.LeftToRight if one else QBoxLayout.Direction.TopToBottom)

    def resizeEvent(self, event) -> None:  # noqa: N802
        self.fit(event.size().width())
        super().resizeEvent(event)


def build_row_bar(ui) -> QWidget:
    bar = _RowBar(ui)
    ui._row_bar = bar
    ui._row_bar_lay = bar.tools_lay     # the values (tests find the fields through it)
    bar.setVisible(False)
    return bar


def _field(ui, text: str, width: int, tip: str, commit) -> QLineEdit:
    f = QLineEdit(text)
    f.setFixedWidth(ui.z.px(width))
    f.setAlignment(Qt.AlignmentFlag.AlignRight)
    f.setToolTip(tip)

    def done() -> None:
        raw = f.text().strip().replace(",", ".").rstrip("%").replace("/cm²", "").strip()
        try:
            commit(float(raw))
        except ValueError:
            f.setText(text)
    f.editingFinished.connect(done)
    return f


def show_row_bar(ui, props: dict) -> None:
    """The selected layer's quick values under the tree (Photoshop's blend / opacity bar). Under, not above: shown
    on a click, a bar above pushed every row down under the mouse. The tree gets shorter at its bottom instead,
    and the current row is scrolled into view when the bar would cover it."""
    U = _ui()
    bar = ui._row_bar
    for lay in (bar.head_lay, bar.tools_lay):
        while lay.count():
            w = lay.takeAt(0).widget()
            if w is not None:
                w.hide()
                w.deleteLater()
    bar.name = None
    layer = props.get("layer") if props.get("kind") == SEL_LAYER else None
    was = not bar.isHidden()
    bar.setVisible(layer is not None)
    line = getattr(ui, "_row_bar_line", None)
    if line is not None:
        line.setVisible(layer is not None)
    tree = getattr(ui, "_tree", None)
    if layer is not None and not was and tree is not None:
        def keep() -> None:
            try:
                cur = tree.currentItem()
            except RuntimeError:   # the panel is gone
                return
            if cur is not None:
                tree.scrollToItem(cur, tree.ScrollHint.EnsureVisible)
        QTimer.singleShot(0, keep)
    if layer is None:
        return
    z = ui.z
    icon = QLabel()
    name = {"base": "lock", "density": "layers", "fill": "paint-bucket", "paint": "brush"}[layer["layer"]]
    icon.setPixmap(U._lucide_pixmap(name, z.px(15), ACCENT if layer.get("painting") else TEXT_LABEL))
    bar.head_lay.addWidget(icon)
    title = U._label(layer["name"], "name")
    title.setMinimumWidth(1)
    title.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
    title.setToolTip(layer["name"])
    bar.head_lay.addWidget(title, stretch=1)
    bar.name = title
    lay = bar.tools_lay
    lid = layer["id"]
    if layer["layer"] == "base":
        lay.addWidget(U._label("nothing to blend", "small"))
    elif layer["layer"] == "density":
        lay.addWidget(_field(ui, f"{layer['density']:g}", 64, "D: strands / cm² where the mask is white",
                             lambda v: ui._fire("set_layer", lid, density=v)))
        lay.addWidget(U._label("/cm²", "small"))
    else:
        combo = U._Combo()
        combo.setMinimumContentsLength(6)
        for key, text in MODE_LABELS.items():
            combo.addItem(text, key)
        combo.setCurrentIndex(max(0, combo.findData(layer["mode"])))
        combo.setToolTip("How this layer blends with the mask under it")
        combo.currentIndexChanged.connect(lambda _i: ui._fire("set_layer", lid, mode=combo.currentData()))
        lay.addWidget(combo)
    if layer["layer"] != "base":
        lay.addWidget(_field(ui, f"{round(layer['opacity'] * 100)}%", 62, "Opacity, %",
                             lambda v: ui._fire("set_layer", lid, opacity=max(0.0, min(100.0, v)) / 100.0)))
    bar.fit()


# ---------------------------------------------------------------------------
# Properties of a layer
# ---------------------------------------------------------------------------
class _ValueRow(QWidget):
    """Name, slider, value: a drag writes once on release (one undo step), a typed value on Enter."""

    def __init__(self, ui, label: str, value: float, lo: float, hi: float, commit, unit: str = "",
                 shown_scale: float = 1.0, tip: str = "", label_w: int = 0, clamp: bool = False) -> None:
        super().__init__()
        self._clamp = clamp      # a typed value is kept inside lo..hi too, not only the slider (t71 defect 2)
        U = _ui()
        z = ui.z
        self._lo, self._hi, self._scale, self._commit_cb = lo, hi, shown_scale, commit
        self._value = float(value)
        self.setProperty("setting", True)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(z.px(4), z.px(4), z.px(2), z.px(4))
        lay.setSpacing(z.px(8))
        name = U._label(label, "body")
        name.setFixedWidth(z.px(label_w or (96 if ui._narrow else 120)))
        name.setWordWrap(True)
        if tip:
            name.setToolTip(tip)
        lay.addWidget(name)
        self.slider = U._Slider()
        self.slider.setRange(0, U.SLIDER_STEPS)
        self.slider.setValue(self._steps(self._value))
        self.slider.setMinimumWidth(z.px(40))
        self.slider.valueChanged.connect(self._moved)
        self.slider.sliderReleased.connect(lambda: self._commit(self._from(self.slider.value())))
        lay.addWidget(self.slider, stretch=1)
        self.field = QLineEdit(self._text(self._value))
        self.field.setFixedWidth(z.px(64))
        self.field.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.field.setProperty("inherited", False)
        self.field.editingFinished.connect(self._typed)
        lay.addWidget(self.field)
        if unit:
            lay.addWidget(U._label(unit, "small"))

    def _text(self, v: float) -> str:
        return f"{v * self._scale:.3g}"

    def _steps(self, v: float) -> int:
        U = _ui()
        t = (v - self._lo) / (self._hi - self._lo) if self._hi > self._lo else 0.0
        return int(round(min(max(t, 0.0), 1.0) * U.SLIDER_STEPS))

    def _from(self, steps: int) -> float:
        return self._lo + (self._hi - self._lo) * steps / _ui().SLIDER_STEPS

    def _moved(self, steps: int) -> None:
        self.field.setText(self._text(self._from(steps)))
        if not self.slider.isSliderDown():
            self._commit(self._from(steps))

    def _typed(self) -> None:
        try:
            v = float(self.field.text().strip().replace(",", ".").rstrip("%")) / self._scale
        except ValueError:
            self.field.setText(self._text(self._value))
            return
        if self._clamp:
            v = min(max(v, self._lo), self._hi)
            self.field.setText(self._text(v))
        self._commit(v)

    def _commit(self, v: float) -> None:
        v = round(float(v), 4)
        if abs(v - self._value) < 1e-9:
            return
        self._value = v
        self._commit_cb(v)


def _buttons_row(ui, items: list[tuple], label: str = "", label_w: int = 0) -> QWidget:
    """A row of small buttons: (text, on, tip, callback, danger)."""
    U = _ui()
    holder = QWidget()
    lay = QHBoxLayout(holder)
    lay.setContentsMargins(ui.z.px(4), ui.z.px(4), 0, ui.z.px(4))
    lay.setSpacing(ui.z.px(6))
    if label:
        name = U._label(label, "body")
        name.setFixedWidth(ui.z.px(label_w or (96 if ui._narrow else 120)))
        name.setWordWrap(True)
        lay.addWidget(name)
    for text, on, tip, act, *rest in items:
        b = QToolButton()
        b.setText(text)
        b.setProperty("toggle", True)
        b.setCheckable(on is not None)
        if on is not None:
            b.setChecked(bool(on))
        b.setToolTip(tip)
        if rest and rest[0]:
            b.setStyleSheet(f"color: {U.TEXT_ERROR};")
        b.clicked.connect(act)
        lay.addWidget(b)
    lay.addStretch(1)
    return holder


def _note(ui, text: str) -> QLabel:
    U = _ui()
    n = U._label(text, "small")
    n.setWordWrap(True)
    return n


def _head(ui, props: dict, painting: bool) -> None:
    U = _ui()
    z, lay = ui.z, ui._props_lay
    row = QHBoxLayout()
    row.setSpacing(z.px(8))
    layer = props["layer"]
    icon = QLabel()
    name = {"base": "lock", "density": "layers", "fill": "paint-bucket", "paint": "brush"}[layer["layer"]]
    icon.setPixmap(U._lucide_pixmap(name, z.px(18), ACCENT if painting else TEXT_LABEL))
    row.addWidget(icon)
    title = U._label(props["title"], "title")
    title.setWordWrap(True)
    row.addWidget(title, stretch=1)
    if painting:
        fold = ui._icon_button("arrow-down", "Fold: the brush settings into one line, the tree gets the room (only"
                                             " while painting)")
        fold.clicked.connect(lambda: set_folded(ui, True))
        row.addWidget(fold, alignment=Qt.AlignmentFlag.AlignTop)
    holder = QWidget()
    holder.setLayout(row)
    row.setContentsMargins(0, 0, 0, 0)
    lay.addWidget(holder)
    if props.get("subtitle") and not props.get("details"):
        lay.addSpacing(z.px(2))
        sub = U._label(props["subtitle"], "meta")
        sub.setWordWrap(True)
        lay.addWidget(sub)
    lay.addSpacing(z.px(10))


def set_folded(ui, folded: bool) -> None:
    """Properties folded to one line while painting: a per-session view choice, not saved, not undoable."""
    ui._props_folded = folded
    if ui._props:
        ui.show_properties(ui._props)
    if ui._narrow:
        h = max(ui._body.height(), 1)
        ui._body.setSizes([int(h * 0.82), int(h * 0.18)] if folded else [int(h * 0.45), int(h * 0.55)])


def _folded_line(ui, props: dict) -> None:
    U = _ui()
    z, lay = ui.z, ui._props_lay
    brush = props.get("brush", {})
    line = QHBoxLayout()
    line.setSpacing(z.px(8))
    chip = U._label(f"Painting {props['title']}", "name", ACCENT)
    chip.setMinimumWidth(1)
    chip.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
    line.addWidget(chip, stretch=1)
    show = QToolButton()
    show.setProperty("flat", True)
    show.setText("  Show")
    show.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
    show.setIcon(_lucide_icon("arrow-up", z.px(14), TEXT_LABEL))
    show.clicked.connect(lambda: set_folded(ui, False))
    line.addWidget(show)
    done = QToolButton()
    done.setProperty("flat", True)
    done.setText("Done  Esc")
    done.setToolTip("Paint off")
    done.clicked.connect(lambda: ui._fire("paint_off"))
    line.addWidget(done)
    holder = QWidget()
    holder.setLayout(line)
    line.setContentsMargins(0, 0, 0, 0)
    lay.addWidget(holder)
    erase = ", Eraser" if brush.get("erase") else ""
    values = (f"Grey {brush.get('value', 1):g}, Radius {brush.get('radius_cm', 1):g} cm, Softness "
              f"{round(brush.get('soft', 0.5) * 100)}%{erase}")
    lay.addWidget(_note(ui, values))
    lay.addSpacing(z.px(4))
    lay.addWidget(_rows(ui, KEYS_ROWS))
    lay.addStretch(1)


def _section(ui, title: str, key: str, default_open: bool = True) -> QVBoxLayout:
    """A foldable section of Properties (the Loader's inspector, t74 "C"): its title with a chevron and a hairline,
    then its body; folded or open is the viewer's, kept in the panel's prefs (`inspector_<key>`)."""
    from tools.fx.grooming import ui_look as K
    U = _ui()
    z = ui.z
    body = QWidget()
    lay = QVBoxLayout(body)
    lay.setContentsMargins(0, z.px(4), 0, z.px(8))
    lay.setSpacing(0)
    head = K._Section(z, title, key, body, U.load_prefs, U.save_prefs, default_open)
    ui._props_lay.addWidget(head)
    ui._props_lay.addWidget(body)
    head.apply()
    return lay


def _rows(ui, rows: list) -> QWidget:
    from tools.fx.grooming import ui_look as K
    w = K._Props(ui.z)
    w.set_rows(rows)
    return w


KEYS_ROWS = [("LMB", "paints"), ("Ctrl", "paints the other way"), ("Esc", "ends Paint"),
             ("Ctrl+Z", "takes one stroke back")]


def _clear_button(ui) -> QToolButton:
    """Clear: the first click asks (its text says so), the second clears; it disarms after CLEAR_ARM_MS."""
    U = _ui()
    clear = {"armed": False}
    cl = QToolButton()
    cl.setText("Clear")
    cl.setProperty("toggle", True)
    cl.setStyleSheet(f"color: {U.TEXT_ERROR};")
    cl.setToolTip("Take all of this layer's paint away. The first click asks, the second clears (Ctrl+Z brings it back)")
    timer = QTimer(cl)
    timer.setSingleShot(True)

    def disarm() -> None:
        clear["armed"] = False
        cl.setText("Clear")

    def press() -> None:
        if clear["armed"]:
            timer.stop()
            disarm()
            ui._fire("paint_layer_action", "clear")
            return
        clear["armed"] = True
        cl.setText("Clear: click again")
        timer.start(CLEAR_ARM_MS)
    timer.timeout.connect(disarm)
    cl.clicked.connect(press)
    return cl


def layer_props(ui, props: dict) -> None:
    """Properties of the selected layer, as the Loader's inspector (the user's pick "C", t74): information first
    (Details, label / value rows), then what is set (Values / Brush), foldable sections remembered per viewer.
    One-off layer commands (new paint / fill / density layer) are on the tree's tools and the row's right-click menu;
    Paint, the brush and the whole-layer actions stay here (used on every stroke)."""
    z = ui.z
    layer = props["layer"]
    lid = layer["id"]
    kind = layer["layer"]
    painting = bool(props.get("painting"))
    if painting and getattr(ui, "_props_folded", False):
        _folded_line(ui, props)
        return
    _head(ui, props, painting)
    lay = ui._props_lay
    details = list(props.get("details", []))
    if kind == "base":
        sec = _section(ui, "Details", "details")
        sec.addWidget(_rows(ui, details))
        lay.addSpacing(z.px(6))
        lay.addWidget(_note(ui, "Change Density on All locks, or add a density layer: the tree's New density layer"
                                " button, or right-click a row."))
        lay.addStretch(1)
        return
    if kind == "density":
        sec = _section(ui, "Details", "details")
        sec.addWidget(_rows(ui, details))
        sec = _section(ui, "Values", "values")
        lo, hi = props.get("range", (0.0, 400.0))
        sec.addWidget(_ValueRow(ui, "Density", layer["density"], lo, hi,
                                lambda v: ui._fire("set_layer", lid, density=v), unit="/cm²",
                                tip="D: strands per cm² where the mask is white (0: no hair there)"))
        sec.addWidget(_buttons_row(ui, [(f"{p:g}", abs(p - layer["density"]) < 1e-9, f"Density {p:g} / cm²",
                                         (lambda _c=False, p=p: ui._fire("set_layer", lid, density=p)))
                                        for p in props.get("picks", [])], label="Quick picks"))
        U = _ui()
        row = QHBoxLayout()
        row.setSpacing(z.px(8))
        name = U._label("Owner", "body")
        name.setFixedWidth(z.px(96 if ui._narrow else 120))
        row.addWidget(name)
        combo = U._Combo()
        for text in props.get("owners", []):
            combo.addItem(text)
        combo.setCurrentIndex(props.get("owner_index", 0))
        combo.setToolTip("The lock tree row this layer belongs to: All locks, a group or one lock")
        combo.currentIndexChanged.connect(lambda i: ui._fire("set_layer_owner", lid, i))
        row.addWidget(combo, stretch=1)
        holder = QWidget()
        holder.setLayout(row)
        row.setContentsMargins(z.px(4), z.px(4), 0, z.px(4))
        sec.addWidget(holder)
        sec.addWidget(_note(ui, props.get("owner_help", "")))
        lay.addSpacing(z.px(6))
        lay.addWidget(_note(ui, "Right-click a layer for a new paint or fill layer, to move, rename or delete it."))
        lay.addStretch(1)
        return
    if kind == "fill":
        sec = _section(ui, "Values", "values")
        sec.addWidget(_ValueRow(ui, "Value", layer["value"], 0.0, 1.0, lambda v: ui._fire("set_layer", lid, value=v),
                                tip="The grey of this fill layer over all the skin: 1 white, 0 black", clamp=True))
        sec.addWidget(_buttons_row(ui, [(f"{p:g}", abs(p - layer["value"]) < 1e-9, f"Value {p:g}",
                                         (lambda _c=False, p=p: ui._fire("set_layer", lid, value=p)))
                                        for p in props.get("value_picks", [])], label="Quick picks"))
        sec = _section(ui, "Details", "details")
        sec.addWidget(_rows(ui, details + [("Brush", "paints only into a paint layer")]))
        lay.addStretch(1)
        return
    # a paint layer: Paint and the brush first, the whole-layer actions folded, then its details
    brush = props.get("brush", {})
    sec = _section(ui, "Brush", "brush")
    tools = QHBoxLayout()
    tools.setSpacing(z.px(6))
    paint = QToolButton()
    paint.setText("  Painting" if painting else "  Paint")
    paint.setProperty("toggle", True)
    paint.setCheckable(True)
    paint.setChecked(painting)
    paint.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
    paint.setIcon(_lucide_icon("brush", z.px(15), ACCENT if painting else TEXT_LABEL))
    paint.setToolTip("Paint this layer in the viewport (Esc ends). Each stroke is one undo step")
    paint.clicked.connect(lambda _on: ui._fire("toggle_paint"))
    tools.addWidget(paint)
    eraser = QToolButton()
    eraser.setText("  Eraser")
    eraser.setProperty("toggle", True)
    eraser.setCheckable(True)
    eraser.setChecked(bool(brush.get("erase")))
    eraser.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
    eraser.setIcon(_lucide_icon("eraser", z.px(15), ACCENT if brush.get("erase") else TEXT_LABEL))
    eraser.setToolTip("Take this layer's paint away (it does not paint black)")
    eraser.clicked.connect(lambda on: ui._fire("set_brush", erase=bool(on)))
    tools.addWidget(eraser)
    tools.addStretch(1)
    holder = QWidget()
    holder.setLayout(tools)
    tools.setContentsMargins(0, 0, 0, z.px(4))
    sec.addWidget(holder)
    sec.addWidget(_buttons_row(ui, [(f"{p:g}", abs(p - float(brush.get("value", 1.0))) < 1e-9,
                                     "What the brush paints into the mask: 1 white (the layer applies), 0 black",
                                     (lambda _c=False, p=p: ui._fire("set_brush", value=p)))
                                    for p in props.get("value_picks", [])], label="Grey"))
    lo, hi = props.get("radius_range", (0.1, 5.0))
    sec.addWidget(_ValueRow(ui, "Radius", float(brush.get("radius_cm", 1.0)), lo, hi,
                            lambda v: ui._fire("set_brush", radius_cm=v), unit="cm"))
    sec.addWidget(_ValueRow(ui, "Softness", float(brush.get("soft", 0.5)), 0.0, 1.0,
                            lambda v: ui._fire("set_brush", soft=v), unit="%", shown_scale=100.0,
                            tip="Share of the radius over which a dab fades out", clamp=True))
    sec.addSpacing(z.px(6))
    sec.addWidget(_rows(ui, KEYS_ROWS))
    sec = _section(ui, "Layer", "layer_actions", default_open=False)
    row = QHBoxLayout()
    row.setSpacing(z.px(6))
    for text, action, tip in (("Fill white", "fill", "Paint the whole layer white (one undo step)"),
                              ("Invert", "invert", "Invert the layer where it is painted")):
        b = QToolButton()
        b.setText(text)
        b.setProperty("toggle", True)
        b.setToolTip(tip)
        b.clicked.connect(lambda _c=False, a=action: ui._fire("paint_layer_action", a))
        row.addWidget(b)
    row.addWidget(_clear_button(ui))
    row.addStretch(1)
    holder = QWidget()
    holder.setLayout(row)
    row.setContentsMargins(z.px(4), 0, 0, 0)
    sec.addWidget(holder)
    sec = _section(ui, "Details", "details")
    sec.addWidget(_rows(ui, details))
    lay.addStretch(1)


# ---------------------------------------------------------------------------
# Paint strip: what the scalp shows while painting
# ---------------------------------------------------------------------------
class _Legend(QWidget):
    """The density ramp (logic.DENSITY_STOPS x the groom's Density) or the layer view's grey, with numbers."""

    def __init__(self, ui) -> None:
        super().__init__()
        self._ui = ui
        self.view = "density"
        self.reference = 150.0
        self.setMinimumWidth(ui.z.px(180))
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def sizeHint(self) -> QSize:  # noqa: N802
        z = self._ui.z
        return QSize(z.px(260), z.px(28))

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        z = self._ui.z
        return QSize(z.px(180), z.px(28))

    def paintEvent(self, event) -> None:  # noqa: N802
        z = self._ui.z
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        w = self.width()
        bar = QRect(0, z.px(2), w, z.px(8))
        p.setPen(Qt.PenStyle.NoPen)
        p.setFont(z.font("small"))
        p.setPen(QColor(TEXT_LABEL))
        if self.view == "layer":
            g = QLinearGradient(bar.left(), 0, bar.right(), 0)
            g.setColorAt(0.0, QColor("#000000"))
            g.setColorAt(1.0, QColor("#ffffff"))
            p.fillRect(bar, g)
            ticks = [(0.0, "0 black"), (0.5, "0.5"), (1.0, "1 white")]
        else:
            stops = logic.DENSITY_STOPS
            n = len(stops) - 1
            for i in range(n):        # one equal segment per stop: the low end gets the room
                seg = QRect(int(w * i / n), bar.top(), int(w * (i + 1) / n) - int(w * i / n), bar.height())
                g = QLinearGradient(seg.left(), 0, seg.right(), 0)
                g.setColorAt(0.0, QColor(DENSITY_RAMP_HEX[i]))
                g.setColorAt(1.0, QColor(DENSITY_RAMP_HEX[i + 1]))
                p.fillRect(seg, g)
            ticks = [(i / n, _fmt_d(stops[i] * self.reference)) for i in range(n + 1)]
        fm = p.fontMetrics()
        y = bar.bottom() + z.px(3)
        for t, text in ticks:
            tw = fm.horizontalAdvance(text)
            x = int(t * w - tw / 2)
            x = max(0, min(w - tw, x))
            p.drawText(QRect(x, y, tw, fm.height()), Qt.AlignmentFlag.AlignLeft, text)
        p.end()


def build_paint_strip(ui) -> QWidget:
    U = _ui()
    z = ui.z
    strip = QWidget()
    strip.setObjectName("PaintStrip")
    strip.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
    outer = QVBoxLayout(strip)
    outer.setContentsMargins(14, 6, 12, 7)
    outer.setSpacing(4)
    top = QHBoxLayout()
    top.setSpacing(6)
    ui._paint_label = U._label("Scalp", "small", TEXT_PRIMARY)
    ui._paint_label.setToolTip("What the scalp shows while painting (not saved, no undo)")
    top.addWidget(ui._paint_label)
    group = QButtonGroup(strip)
    group.setExclusive(True)
    ui._view_buttons = {}
    keys = list(VIEW_LABELS)
    seg = QHBoxLayout()
    seg.setSpacing(0)
    for key, text in VIEW_LABELS.items():
        b = QToolButton()
        b.setText(text)
        b.setProperty("toggle", True)
        b.setProperty("seg", "left" if key == keys[0] else ("right" if key == keys[-1] else "mid"))
        b.setCheckable(True)
        b.setToolTip({"density": "The density the groom has now, roots / cm² (choosing it counts the roots)",
                      "layer": "The painted layer alone: white 1, black 0, dark where not painted",
                      "roots": "A dot a root of the full groom (grows locks the cache does not hold in full)"}[key])
        b.clicked.connect(lambda _c=False, k=key: ui._fire("set_brush", view=k))
        group.addButton(b)
        seg.addWidget(b)
        ui._view_buttons[key] = b
    top.addLayout(seg)
    top.addSpacing(z.px(4))
    xr = ui._icon_button("contrast", "Scalp X-ray: the scalp's colours through the hair (a wash)", checkable=True)
    xr.clicked.connect(lambda on: ui._fire("set_brush", xray=bool(on)))
    ui._paint_xray = xr
    top.addWidget(xr)
    top.addStretch(1)
    outer.addLayout(top)
    legend_row = QHBoxLayout()
    legend_row.setSpacing(z.px(10))
    ui._legend = _Legend(ui)
    legend_row.addWidget(ui._legend, stretch=1)
    ui._legend_caption = U._label("", "small")
    ui._legend_caption.setWordWrap(True)
    legend_row.addWidget(ui._legend_caption)
    outer.addLayout(legend_row)
    strip.setVisible(False)
    ui._paint_strip = strip
    return strip


def set_paint_state(ui, on: bool, brush: dict, reference: float | None = None) -> None:
    U = _ui()
    z = ui.z
    ui._paint_strip.setVisible(bool(on))
    if not on:
        ui._props_folded = False
    view = brush.get("view", "density")
    for key, b in ui._view_buttons.items():
        b.setChecked(key == view)
    ui._paint_xray.setChecked(bool(brush.get("xray")))
    ui._recolor_icon(ui._paint_xray, ACCENT if brush.get("xray") else TEXT_LABEL)
    if reference:
        ui._legend.reference = float(reference)
    ui._legend.view = view
    ui._legend.setVisible(view != "roots")
    ui._legend.update()
    ui._legend_caption.setText({
        "density": f"roots / cm², green = {ui._legend.reference:g}",
        "layer": "dark: not painted",
        "roots": "a dot a root of the full groom, on the plain scalp",
    }[view])
    ui._legend_caption.setToolTip("Green is the Density of All locks; the ramp's stops are 0, ½, 1, 2, 8 and 48"
                                  " times it" if view == "density" else "")
    ui._legend_caption.setWordWrap(view == "roots")


# ---------------------------------------------------------------------------
# Right click on a layer row
# ---------------------------------------------------------------------------
def layer_menu(ui, row: dict, menu: QMenu) -> None:
    z = ui.z
    kind = row["layer"]
    lid = row["id"]
    if kind == "base":
        menu.addAction(_lucide_icon("layers", z.px(15)), "New density layer").triggered.connect(
            lambda: ui._fire("add_density_layer"))
        return
    if kind == "paint":
        menu.addAction(_lucide_icon("brush", z.px(15)), "Paint" if not row.get("painting") else "Paint off").triggered.connect(
            lambda: ui._fire("toggle_paint"))
        menu.addAction("Fill white").triggered.connect(lambda: ui._fire("paint_layer_action", "fill", lid))
        menu.addAction("Invert").triggered.connect(lambda: ui._fire("paint_layer_action", "invert", lid))
        menu.addAction("Clear").triggered.connect(lambda: ui._fire("paint_layer_action", "clear", lid))
        menu.addSeparator()
    menu.addAction(_lucide_icon("plus", z.px(15)), "New paint layer").triggered.connect(
        lambda: ui._fire("add_mask_layer", "paint"))
    menu.addAction(_lucide_icon("paint-bucket", z.px(15)), "New fill layer").triggered.connect(
        lambda: ui._fire("add_mask_layer", "fill"))
    if kind == "density":
        menu.addAction(_lucide_icon("layers", z.px(15)), "New density layer").triggered.connect(
            lambda: ui._fire("add_density_layer"))
    menu.addSeparator()
    on = row.get("on", True)
    menu.addAction(_lucide_icon("eye-off" if on else "eye", z.px(15)), "Turn off" if on else "Turn on").triggered.connect(
        lambda: ui._fire("set_layer_on", lid, not on))
    menu.addAction(_lucide_icon("chevron-up", z.px(15)), "Move up").triggered.connect(lambda: ui._fire("move_layer", True, lid))
    menu.addAction(_lucide_icon("chevron-down", z.px(15)), "Move down").triggered.connect(lambda: ui._fire("move_layer", False, lid))
    menu.addAction(_lucide_icon("type", z.px(15)), "Rename    F2").triggered.connect(
        lambda: ui._tree.editItem(ui._rows[(SEL_LAYER, lid)], _ui().COL_NAME))
    menu.addAction(_lucide_icon("trash", z.px(15)), "Delete    Del").triggered.connect(lambda: ui._fire("delete_layer", lid))


# ---------------------------------------------------------------------------
# Settings page (the node's own values, with what the undo cache holds)
# ---------------------------------------------------------------------------
def show_settings(ui, info: dict) -> None:
    """The settings page in the Properties column; Back (or a selection) returns."""
    U = _ui()
    from tools.fx.grooming.layers import LayersMixin
    z, lay = ui.z, ui._props_lay
    ui._settings_open = True
    U.GroomingUI._clear_props(ui)
    head = QHBoxLayout()
    back = ui._icon_button("arrow-left", "Back: to the selection's Properties")
    back.clicked.connect(lambda: close_settings(ui))
    head.addWidget(back)
    head.addWidget(U._label("Settings", "title"), stretch=1)
    holder = QWidget()
    holder.setLayout(head)
    head.setContentsMargins(0, 0, 0, 0)
    lay.addWidget(holder)
    lay.addSpacing(z.px(6))
    lay.addWidget(_note(ui, "Font size and X-ray strength are yours (the Settings menu, saved per user). These"
                            " belong to the node: saved with the scene, Ctrl+Z undoes them."))
    lay.addSpacing(z.px(12))
    lay.addWidget(U._label("THIS NODE", "caps"))
    lay.addWidget(U._line())
    editable = bool(info.get("editable"))
    if "lookup" in info:
        on = bool(info.get("lookup"))
        lay.addWidget(_buttons_row(ui, [("On" if on else "Off", on,
                                         "Each lock looks its strands up on its own mesh piece: a third less to cook"
                                         " per lock. Off: the whole hair mesh, as v0.1 did",
                                         lambda _c=False: ui._fire("set_node_setting", "lookup", not on))],
                                   label="Fit lookup per lock", label_w=110 if ui._narrow else 150))
        lay.addWidget(_note(ui, info.get("lookup_text") if info.get("lookup_kept") else
                            "On and off give the same roots and strand counts; strand points move between them"
                            " (Helen: about half of them, most by under 0.01 mm)."))
        lay.addSpacing(z.px(10))
    use = info.get("usage")
    for key, label, deformed in (("undo_cache_gb", "Undo cache, GB", False),
                                 ("undo_deform_gb", "Deformed undo, GB", True)):
        if key in info:
            lo, hi = GB_RANGE
            row = _ValueRow(ui, label, float(info[key]), lo, hi, lambda v, k=key: ui._fire("set_node_setting", k, v),
                            label_w=110 if ui._narrow else 150, clamp=True,
                            tip=f"{lo:g} to {hi:g} GB; a typed value outside is brought inside")
            row.setEnabled(editable)
            lay.addWidget(row)
        rows = _rows(ui, LayersMixin.usage_rows(use, deformed=deformed))
        rows.setToolTip(LayersMixin.usage_text(use, deformed=deformed))
        lay.addWidget(rows)
        lay.addSpacing(z.px(10))
    if not editable:
        lay.addWidget(_note(ui, "This adapter cannot set the node's values from the panel: set them on the node's"
                                " Advanced tab."))
    lay.addStretch(1)


def close_settings(ui) -> None:
    ui._settings_open = False
    if ui._props:
        ui.show_properties(ui._props)


__all__ = ["add_layers", "expand_layers", "build_paint_strip", "build_row_bar", "build_tree_tools", "layer_menu", "layer_props",
           "make_layer_item", "set_paint_state", "show_row_bar", "show_settings", "update_tree_tools"]

