"""
MONO Grooming panel, lock shapes (v0.2b, task B4): the view's part. `ui.GroomingUI` calls these; they build Qt widgets
and fire events back through `ui._fire` (the controller's `spine.SpineMixin` answers). No data is kept here.

Design gate (t78, the user's pick 2026-11-20): mockup B, `sandbox/.../tests/t78_redraw_mockups/b_toolbar.html`, with
the fixes of its review (`review_b.md` there; where the two differ the review wins):
  - a Tool bar at the panel's head (under the top bar; narrow, under the view bar): Select / Edit points / Draw
    lock / Paint, one on at a time. Narrow (< NARROW_PX) the cells say Select / Points / Draw / Paint (tooltips keep
    the full names). The Select cell shows its key, Esc, while another tool is on ("Done" went: review 6). The
    Paint cell REPLACES the Paint button of a paint layer's Properties (the user, 2026-11-20: one way in); without
    one paint layer selected it is dimmed, its tooltip and a click say why (review 7);
  - under it a tinted strip with the tool in hand: Edit points = who (wide only), the drag mode Move / Rotate /
    Scale / Redraw (sticky; a held R / E / Shift lights its cell for one drag; Redraw has its own icon `route`,
    review 3; wide, each cell shows its key), Handles `auto (N)` / `auto (4 to 6)` / own number bold / `mixed` with
    minus / plus on each selected lock and "auto" back (review 5), Reset shape (an icon when narrow; one name,
    review 2). No lock to edit: "Select a lock" (the tool is never refused, the user 2026-11-20). Draw lock = Next
    lock: Width, Thickness (cm), Tip taper. Paint's strip is v0.2a's Scalp strip. The strip lays itself on one
    line, and on two when its groups do not fit (a larger font size), never clipped;
  - rows: `edited` (shape) and `drawn` as neutral words in the status column (review 13), an amber warning icon
    before `drawn` while the lock stays at rest in a shot (review 10); the rows whose handles show have the
    control-points icon in the accent instead of their swatch;
  - Properties: Shape, Skin from, In shots in Details; Reset shape beside Hidden / Flip root / Exclude while no
    tool is on; a drawn lock's Drawn shape section (Width, Thickness, Tip taper) ending in Delete lock (review 12);
    the tree's trash, Del and the right-click menu delete a drawn lock too.
Departures from the mockup are listed in the t82 report (sandbox `tests/t82_spine_panel/report.md`).
"""

from __future__ import annotations

from PySide6.QtCore import QRect, QSize, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QKeySequence, QPainter, QShortcut
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from tools.fx.auto_material.ui import ACCENT, LINE, LUCIDE, TEXT_ERROR, TEXT_LABEL, TEXT_META, TEXT_PRIMARY, \
    _lucide_icon, _lucide_pixmap
from tools.fx.grooming import spine as S
from tools.fx.grooming import ui_look as K

LUCIDE.update({
    "pointer": '<path d="M12.586 12.586 19 19"/><path d="M3.688 3.037a.497.497 0 0 0-.651.651l6.5 15.999a.501.501 0 0 0'
               ' .947-.062l1.569-6.083a2 2 0 0 1 1.448-1.479l6.124-1.579a.5.5 0 0 0 .063-.947z"/>',
    "spline": '<circle cx="19" cy="5" r="2"/><circle cx="5" cy="19" r="2"/><path d="M5 17A12 12 0 0 1 17 5"/>',
    "pencil": '<path d="M13 21h8"/><path d="m15 5 4 4"/><path d="M21.174 6.812a1 1 0 0 0-3.986-3.987L3.842 16.174a2 2 0'
              ' 0 0-.5.83l-1.321 4.352a.5.5 0 0 0 .623.622l4.353-1.32a2 2 0 0 0 .83-.497z"/>',
    "move": '<path d="M12 2v20"/><path d="m15 19-3 3-3-3"/><path d="m19 9 3 3-3 3"/><path d="M2 12h20"/>'
            '<path d="m5 9-3 3 3 3"/><path d="m9 5 3-3 3 3"/>',
    "rotate-cw": '<path d="M21 12a9 9 0 1 1-9-9c2.52 0 4.93 1 6.74 2.74L21 8"/><path d="M21 3v5h-5"/>',
    "scale": '<path d="M12 3H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M14 15H9v-5"/>'
             '<path d="M16 3h5v5"/><path d="M21 3 9 15"/>',
    "route": '<circle cx="6" cy="19" r="3"/><path d="M9 19h8.5a3.5 3.5 0 0 0 0-7h-11a3.5 3.5 0 0 1 0-7H15"/>'
             '<circle cx="18" cy="5" r="3"/>',
    "minus": '<path d="M5 12h14"/>',
    "plus": '<path d="M5 12h14"/><path d="M12 5v14"/>',
})

STRIP_BG = "#151a28"      # the tinted strip (Paint's Scalp strip has the same)
KEY_BG = "#2a2a32"        # a key chip inside a cell
OFF_TEXT = TEXT_META      # the dimmed Paint cell (on BUTTON_DISABLED: 5.23:1, pairs_t78)


def _ui():
    from tools.fx.grooming import ui as U   # ui imports this module at its top: import it late
    return U


def sheet(z) -> str:
    """The Tool bar's and the strip's rules, appended to the window's sheet (`ui._sheet`)."""
    p = z.px
    b = K._border_px(z.scale)
    return f"""
    QWidget#ToolBar {{ background: {_ui().PANE}; }}
    QWidget#ToolStrip {{ background: {STRIP_BG}; }}
    QToolButton[cell="true"] {{ padding: {p(4)}px {p(9)}px; font-size: {p(15)}px; border-radius: {p(6)}px; }}
    QToolButton[cell="true"]:checked {{ background: {K.CHECKED}; border-color: {_ui().ACCENT_LINE}; color: {TEXT_PRIMARY}; }}
    QToolButton[cell="true"]:checked:hover {{ background: {K.CHECKED_HOVER}; border-color: {ACCENT}; }}
    QToolButton[cell="true"][dim="true"] {{ background: {K.BUTTON_DISABLED}; color: {OFF_TEXT}; border-color: {LINE}; }}
    QToolButton[held="true"] {{ border-color: {ACCENT}; }}
    QLabel#HandlesValue {{ background: {_ui().BG_RAISED}; border: {b}px solid #2e2e36; border-radius: {p(6)}px;
                           padding: 0px {p(7)}px; color: {TEXT_LABEL}; font-size: {p(15)}px; }}
    QLabel#HandlesValue[own="true"] {{ color: {TEXT_PRIMARY}; font-weight: 600; }}
    QToolButton#DeleteLock {{ color: {TEXT_ERROR}; }}
    QLineEdit[strip="true"] {{ padding: {p(2)}px {p(5)}px; font-size: {p(15)}px; }}
    """


class _Cell(QToolButton):
    """A segment of the Tool bar or the drag switch: icon and words, and a key chip at its right ("Esc", "R") drawn in
    the button's right padding."""

    def __init__(self, ui) -> None:
        super().__init__()
        self._ui = ui
        self.key = ""
        self.setProperty("toggle", True)
        self.setProperty("cell", True)
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)

    def _chip_w(self) -> int:
        if not self.key:
            return 0
        z = self._ui.z
        return QFontMetrics(z.font("small")).horizontalAdvance(self.key) + z.px(10)

    def set_key(self, key: str) -> None:
        if key == self.key:
            return
        self.key = key
        z = self._ui.z
        extra = self._chip_w()
        self.setStyleSheet(f"QToolButton {{ padding-right: {z.px(9) + extra + (z.px(5) if extra else 0)}px; }}"
                           if extra else "")
        self.updateGeometry()

    def paintEvent(self, event) -> None:  # noqa: N802
        super().paintEvent(event)
        if not self.key:
            return
        z = self._ui.z
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        font = z.font("small")
        p.setFont(font)
        w = self._chip_w()
        h = QFontMetrics(font).height() + z.px(2)
        r = QRect(self.width() - z.px(8) - w, (self.height() - h) // 2, w, h)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(KEY_BG))
        p.drawRoundedRect(r, z.px(4), z.px(4))
        p.setPen(QColor(TEXT_LABEL))
        p.drawText(r, Qt.AlignmentFlag.AlignCenter, self.key)
        p.end()


def _seg(cells: list[QToolButton]) -> QWidget:
    holder = QWidget()
    lay = QHBoxLayout(holder)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(0)
    for k, c in enumerate(cells):
        c.setProperty("seg", "left" if k == 0 else ("right" if k == len(cells) - 1 else "mid"))
        lay.addWidget(c)
    return holder


class _Flow(QWidget):
    """Groups of widgets on one line, or on as many as the width needs (a larger font size): never clipped. A group
    marked `stretch` takes what is left on its line."""

    def __init__(self, groups: list[tuple[QWidget, bool]], spacing: int) -> None:
        super().__init__()
        self._groups = groups
        self._spacing = spacing
        self._outer = QVBoxLayout(self)
        self._outer.setContentsMargins(0, 0, 0, 0)
        self._outer.setSpacing(spacing)
        self._rows: list[list[int]] = []
        for w, _s in groups:
            w.setParent(self)
        self._place(self._plan(10 ** 6))

    def _shown(self) -> list[int]:
        return [k for k, (w, _s) in enumerate(self._groups) if not w.isHidden()]

    def _plan(self, width: int) -> list[list[int]]:
        rows, row, used = [], [], 0
        for k in self._shown():
            need = self._groups[k][0].sizeHint().width()
            if row and used + self._spacing + need > width:
                rows.append(row)
                row, used = [], 0
            used += (self._spacing if row else 0) + need
            row.append(k)
        if row:
            rows.append(row)
        return rows

    def _place(self, rows: list[list[int]]) -> None:
        self._rows = rows
        while self._outer.count():
            item = self._outer.takeAt(0)
            lay = item.layout()
            if lay is not None:
                while lay.count():
                    lay.takeAt(0)
                lay.setParent(None)
        for row in rows:
            line = QHBoxLayout()
            line.setContentsMargins(0, 0, 0, 0)
            line.setSpacing(self._spacing)
            stretched = False
            for k in row:
                w, stretch = self._groups[k]
                line.addWidget(w, 1 if stretch else 0)
                stretched = stretched or stretch
            if not stretched:
                line.addStretch(1)
            self._outer.addLayout(line)

    def refit(self) -> None:
        rows = self._plan(max(self.width(), 1))
        if rows != self._rows:
            self._place(rows)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self.refit()

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        widest = max((self._groups[k][0].minimumSizeHint().width() for k in self._shown()), default=0)
        return QSize(widest, super().minimumSizeHint().height())


# ---------------------------------------------------------------------------
# The Tool bar
# ---------------------------------------------------------------------------
def build_tool_bar(ui) -> QWidget:
    U = _ui()
    bar = QWidget()
    bar.setObjectName("ToolBar")
    bar.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
    lay = QHBoxLayout(bar)
    lay.setContentsMargins(14, 5, 10, 5)
    lay.setSpacing(8)
    label = U._label("Tool", "small", TEXT_PRIMARY)
    label.setToolTip("One tool at a time has the viewport")
    lay.addWidget(label)
    ui._tool_cells = {}
    cells = []
    for t in S.TOOLS:
        c = _Cell(ui)
        c.clicked.connect(lambda _on=False, t=t: _tool_clicked(ui, t))
        ui._tool_cells[t] = c
        cells.append(c)
    seg = _seg(cells)
    seg.setToolTip("One tool at a time has the viewport")
    lay.addWidget(seg)
    lay.addStretch(1)
    ui._tool_bar = bar
    ui._tool_state = (None, None)
    return bar


def _tool_clicked(ui, tool: str) -> None:
    cells, strip = ui._tool_state
    # the exclusive look: a click on the cell that is on keeps it on; the controller then shows the truth
    if cells:
        for c in cells:
            ui._tool_cells[c["id"]].setChecked(c["on"])
    ui._fire("set_tool", tool)


# ---------------------------------------------------------------------------
# The strip of the tool in hand
# ---------------------------------------------------------------------------
def _small(text: str, color: str = TEXT_LABEL) -> QLabel:
    return _ui()._label(text, "small", color)


def _row(*widgets, spacing: int = 5) -> QWidget:
    holder = QWidget()
    lay = QHBoxLayout(holder)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(spacing)
    for w in widgets:
        lay.addWidget(w)
    return holder


def _step_button(ui, icon: str, tip: str, event: str, *args) -> QToolButton:
    b = QToolButton()
    b.setProperty("flat", True)
    b.setProperty("iconflat", True)
    b.setToolTip(tip)
    b.setAccessibleName(tip.split(":")[0])
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    ui._icon(b, icon, TEXT_LABEL, 14)
    b.setFixedSize(ui.z.px(24), ui.z.px(28))
    ui._icon_buttons_small = getattr(ui, "_icon_buttons_small", []) + [b]
    b.clicked.connect(lambda: ui._fire(event, *args))
    return b


def build_tool_strip(ui) -> QWidget:
    U = _ui()
    z = ui.z
    strip = QWidget()
    strip.setObjectName("ToolStrip")
    strip.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
    outer = QVBoxLayout(strip)
    outer.setContentsMargins(14, 5, 10, 5)
    outer.setSpacing(0)

    # Edit points
    ui._strip_who = _small("", TEXT_PRIMARY)
    ui._strip_who.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
    ui._mode_cells = {}
    cells = []
    for m in S.MODES:
        label, icon, key = S.MODE_WORDS[m]
        c = _Cell(ui)
        c.setToolTip(f"{label}: " + ("drag a handle" if not key else f"hold {key} for one drag, or click to keep it"))
        c.setAccessibleName(label)
        c.clicked.connect(lambda _on=False, m=m: ui._fire("set_drag_mode", m))
        ui._mode_cells[m] = c
        cells.append(c)
    ui._mode_seg = _seg(cells)
    ui._mode_seg.setToolTip("What a drag does: Move a handle; Rotate (R) or Scale (E) the lock about its root;"
                            " Redraw (Shift) the whole curve from the root")
    ui._handles_value = QLabel("")
    ui._handles_value.setObjectName("HandlesValue")
    ui._handles_value.setAlignment(Qt.AlignmentFlag.AlignCenter)
    ui._handles_value.setToolTip(S.HANDLES_TIP)
    ui._handles_minus = _step_button(ui, "minus", "Fewer handles: one fewer on each selected lock (−)", "step_handles", -1)
    ui._handles_plus = _step_button(ui, "plus", "More handles: one more on each selected lock (+)", "step_handles", 1)
    auto = QToolButton()
    auto.setText("auto")
    auto.setProperty("toggle", True)
    auto.setCursor(Qt.CursorShape.PointingHandCursor)
    auto.clicked.connect(lambda: ui._fire("handles_auto"))
    ui._handles_auto = auto
    ui._handles_box = _row(_small("Handles"), ui._handles_value, ui._handles_minus, ui._handles_plus, auto)
    reset = QToolButton()
    reset.setProperty("toggle", True)
    reset.setCursor(Qt.CursorShape.PointingHandCursor)
    reset.clicked.connect(lambda: ui._fire("reset_shape"))
    ui._icon(reset, "rotate-ccw", TEXT_LABEL, 14)
    ui._strip_reset = reset
    ui._points_flow = _Flow([(ui._strip_who, False), (ui._mode_seg, False), (ui._handles_box, True), (reset, False)],
                            z.px(10))

    # Draw lock: what the next lock gets
    ui._next_label = _small("Next lock", TEXT_PRIMARY)
    ui._next_label.setToolTip("What the next lock drawn gets; it follows what you set on the lock just drawn")
    ui._next_fields = {}
    groups = [(ui._next_label, False)]
    for key in ("width_cm", "thick_cm", "taper"):
        field = QLineEdit()
        field.setProperty("strip", True)
        field.setAlignment(Qt.AlignmentFlag.AlignRight)
        field.setFixedWidth(z.px(52))
        field.editingFinished.connect(lambda k=key, f=field: _new_lock_typed(ui, k, f))
        name = _small(S.DRAWN_LABELS[key])
        parts = [name, field] + ([_small("cm")] if S.DRAWN_UNITS[key] else [])
        box = _row(*parts, spacing=4)
        if key == "taper":
            box.setToolTip(S.TAPER_TIP)
            field.setToolTip(S.TAPER_TIP)
        ui._next_fields[key] = (field, name)
        groups.append((box, False))
    ui._draw_flow = _Flow(groups, z.px(10))
    outer.addWidget(ui._points_flow)
    outer.addWidget(ui._draw_flow)
    strip.setVisible(False)
    ui._tool_strip = strip
    return strip


def _new_lock_typed(ui, key: str, field: QLineEdit) -> None:
    cells, strip = ui._tool_state
    if strip and strip.get(key) is not None and field.text().strip() == f"{strip[key]:g}":
        return
    ui._fire("set_new_lock", **{key: field.text()})


def show_tools(ui, cells: list[dict], strip: dict) -> None:
    """What the controller says: the cells (one on, Paint dimmed with its reason) and the strip of the tool in hand."""
    ui._tool_state = (cells, strip)
    narrow = bool(ui._narrow)
    z = ui.z
    for c in cells:
        b = ui._tool_cells[c["id"]]
        b.setText(f" {c['short'] if narrow else c['label']}")
        b.setChecked(bool(c["on"]))
        b.setToolTip(c["tip"])
        b.setAccessibleName(c["label"])
        color = ACCENT if c["on"] else (OFF_TEXT if c["dim"] else TEXT_LABEL)
        b.setIcon(K._crisp_icon(c["icon"], z.px(14), color))
        b.setIconSize(QSize(z.px(14), z.px(14)))
        if bool(b.property("dim")) != bool(c["dim"]):
            b.setProperty("dim", bool(c["dim"]))
            b.style().unpolish(b)
            b.style().polish(b)
        b.set_key("" if narrow else c.get("key", ""))
    tool = strip.get("tool")
    ui._tool_strip.setVisible(tool in (S.TOOL_POINTS, S.TOOL_DRAW))
    ui._points_flow.setVisible(tool == S.TOOL_POINTS)
    ui._draw_flow.setVisible(tool == S.TOOL_DRAW)
    if tool == S.TOOL_POINTS:
        _show_points(ui, strip, narrow)
        ui._points_flow.refit()
    elif tool == S.TOOL_DRAW:
        ui._next_label.setText("Next" if narrow else "Next lock")
        short = {"width_cm": "W", "thick_cm": "T", "taper": "Taper"}
        for key, (field, name) in ui._next_fields.items():
            if not field.hasFocus():
                field.setText(f"{float(strip.get(key, 0.0)):g}")
            name.setText(short[key] if narrow else S.DRAWN_LABELS[key])
        ui._draw_flow.refit()


def _show_points(ui, strip: dict, narrow: bool) -> None:
    z = ui.z
    ids = strip.get("lock_ids") or []
    who = strip.get("who", S.SELECT_A_LOCK)
    ui._strip_who.setText(who)
    ui._strip_who.setToolTip(who)
    # narrow: who is said by the rows and Properties, unless there is no lock (review 1)
    ui._strip_who.setVisible(not narrow or not ids)
    held = strip.get("held", "")
    for m, c in ui._mode_cells.items():
        label, icon, key = S.MODE_WORDS[m]
        on = strip.get("mode") == m
        c.setChecked(on)
        c.setText("" if narrow else f" {label}")
        c.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly if narrow else
                             Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        c.setIcon(K._crisp_icon(icon, z.px(14), ACCENT if (on or held == m) else TEXT_LABEL))
        c.setIconSize(QSize(z.px(14), z.px(14)))
        if bool(c.property("held")) != (held == m):
            c.setProperty("held", held == m)
            c.style().unpolish(c)
            c.style().polish(c)
        c.set_key("" if narrow else key)
    h = strip.get("handles") or {}
    ui._handles_box.setVisible(bool(ids))
    ui._handles_value.setText(h.get("text", ""))
    if bool(ui._handles_value.property("own")) != bool(h.get("own")):
        ui._handles_value.setProperty("own", bool(h.get("own")))
        ui._handles_value.style().unpolish(ui._handles_value)
        ui._handles_value.style().polish(ui._handles_value)
    ui._handles_value.setMinimumWidth(z.px(56))
    ui._handles_value.setFixedHeight(z.px(28))
    ui._handles_minus.setEnabled(not h.get("min"))
    ui._handles_plus.setEnabled(not h.get("max"))
    ui._handles_auto.setVisible(bool(h.get("own")))
    ui._handles_auto.setToolTip(strip.get("auto_tip", ""))
    reset = strip.get("reset") or {}
    ui._strip_reset.setVisible(bool(ids))
    ui._strip_reset.setEnabled(bool(reset.get("n")))
    ui._strip_reset.setToolTip(reset.get("tip", ""))
    ui._strip_reset.setAccessibleName("Reset shape")
    n = reset.get("n", 0)
    if narrow:
        ui._strip_reset.setText("")
        ui._strip_reset.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
    else:
        ui._strip_reset.setText(" Reset shape" + (f" ({n})" if n > 1 else ""))
        ui._strip_reset.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)


def relayout(ui) -> None:
    """Narrow / wide changed: the cells' words and the strip again."""
    cells, strip = getattr(ui, "_tool_state", (None, None))
    if cells is not None:
        show_tools(ui, cells, strip)


# ---------------------------------------------------------------------------
# Keys: Enter, minus / plus (a text field keeps its own)
# ---------------------------------------------------------------------------
def install_keys(ui) -> None:
    def typing() -> bool:
        from PySide6.QtWidgets import QApplication
        return isinstance(QApplication.focusWidget(), QLineEdit)

    def points_on() -> bool:
        cells, _strip = ui._tool_state
        return bool(cells) and any(c["id"] == S.TOOL_POINTS and c["on"] for c in cells)

    for seq in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
        sc = QShortcut(QKeySequence(seq), ui)
        sc.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        sc.activated.connect(lambda: None if typing() else ui._fire("toggle_tool", S.TOOL_POINTS))
    for seq, step in (("-", -1), ("+", 1), ("=", 1)):
        sc = QShortcut(QKeySequence(seq), ui)
        sc.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        sc.activated.connect(lambda s=step: None if typing() or not points_on() else ui._fire("step_handles", s))


# ---------------------------------------------------------------------------
# Rows, Properties, the tree's trash and the right-click menu
# ---------------------------------------------------------------------------
def row_icon(ui, row: dict):
    """The control-points icon in the accent on a row whose handles show (Edit points on it), else None."""
    if row.get("editing"):
        return U_fixed_icon("spline", ui.z.px(14), ACCENT)
    return None


def U_fixed_icon(name: str, size: int, color: str):
    return _ui()._fixed_icon(name, size, color)


def status_parts(row: dict) -> list[tuple[str, str]]:
    """The row's shape words, after the others: a warning icon (WARN_ICON) then `drawn`, then `edited`."""
    parts: list[tuple[str, str]] = []
    if row.get("shape_edited"):
        parts.append(("edited", TEXT_LABEL))
    if row.get("drawn"):
        parts.append(("drawn", TEXT_LABEL))
        if row.get("at_rest"):
            parts.append((WARN_ICON, _ui().WARN))
    return parts


WARN_ICON = "\x00warn"   # a part that the delegate draws as the triangle icon


def status_help(row: dict) -> list[str]:
    out = []
    if row.get("shape_edited"):
        out.append("edited: its shape was edited (Reset shape puts the measured spine back)")
    if row.get("drawn"):
        out.append("drawn: a lock drawn on bare skin, with no hair mesh")
    if row.get("at_rest"):
        out.append(S.AT_REST_TIP)
    if row.get("no_lock"):
        out.append("no lock: its lock was a drawn lock, deleted; the layer stays (Ctrl+Z brings the lock back)")
    return out


def action_buttons(ui, state: dict) -> list[QToolButton]:
    """Reset shape beside Hidden / Flip root / Exclude while no tool is on (in the strip while Edit points is,
    review 2)."""
    ids = state.get("reset_ids") or []
    if not ids or state.get("tool") == S.TOOL_POINTS:
        return []
    z = ui.z
    b = QToolButton()
    b.setText("  Reset shape" + (f" ({len(ids)})" if len(ids) > 1 else ""))
    b.setProperty("toggle", True)
    b.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
    b.setIcon(_lucide_icon("rotate-ccw", z.px(15), TEXT_LABEL))
    b.setIconSize(QSize(z.px(15), z.px(15)))
    b.setToolTip("Reset shape: back to the measured spine (a drawn lock: the curve as drawn); one undo step")
    b.clicked.connect(lambda: ui._fire("reset_shape", list(ids)))
    return [b]


def drawn_section(ui, props: dict) -> None:
    """A drawn lock's Drawn shape: Width, Thickness, Tip taper (one undo step each), then Delete lock at its end."""
    shape = props.get("drawn_shape")
    if not shape:
        return
    U = _ui()
    L = U.L
    z = ui.z
    lay = ui._props_lay
    head = QHBoxLayout()
    head.addWidget(U._label("DRAWN SHAPE", "caps"))
    head.addStretch(1)
    if shape.get("note") and not ui._compact():
        head.addWidget(U._label(shape["note"], "small"))
    holder = QWidget()
    holder.setLayout(head)
    head.setContentsMargins(z.px(4), 0, 0, z.px(4))
    lay.addWidget(holder)
    lay.addWidget(U._line())
    for key, v in shape["values"].items():
        lo, hi = v["range"]
        label = v["label"] + (" (mixed)" if v["mixed"] else "")
        row = L._ValueRow(ui, label, v["value"], lo, hi, lambda value, k=key: ui._fire("set_drawn_value", k, value),
                          unit=v["unit"], tip=S.TAPER_TIP if key == "taper" else
                          f"{v['label']} at the root, cm (the footprint follows the width: Update regions)",
                          clamp=key == "taper")
        lay.addWidget(row)
    delete = QToolButton()
    delete.setObjectName("DeleteLock")
    delete.setText("  Delete lock")
    delete.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
    delete.setIcon(_lucide_icon("trash", z.px(15), TEXT_ERROR))
    delete.setIconSize(QSize(z.px(15), z.px(15)))
    delete.setToolTip("Delete lock (Del): its skin goes back to its neighbours; one undo step")
    delete.setCursor(Qt.CursorShape.PointingHandCursor)
    ids = list(shape["ids"])
    delete.clicked.connect(lambda: ui._fire("delete_drawn", ids))
    row = QHBoxLayout()
    row.addStretch(1)
    row.addWidget(delete)
    holder = QWidget()
    holder.setLayout(row)
    row.setContentsMargins(0, z.px(8), 0, 0)
    lay.addWidget(holder)
    lay.addSpacing(z.px(14))


def install_tree_tools(ui) -> None:
    """The tree's trash and Del delete a drawn lock too (they deleted only layers)."""
    trash = getattr(ui, "_layer_tools", {}).get("delete")
    if trash is not None:
        try:
            trash.clicked.disconnect()
        except (RuntimeError, TypeError):
            pass
        trash.clicked.connect(lambda: delete_selected(ui))


def delete_selected(ui) -> None:
    props = ui._props or {}
    if props.get("kind") == "layer":
        ui._fire("delete_layer")
    elif props.get("drawn_ids"):
        ui._fire("delete_drawn", list(props["drawn_ids"]))


def update_tree_tools(ui, props: dict) -> None:
    trash = getattr(ui, "_layer_tools", {}).get("delete")
    if trash is None or props.get("kind") == "layer":
        return
    drawn = props.get("drawn_ids") or []
    trash.setEnabled(bool(drawn))
    trash.setToolTip("Delete drawn lock (Del): its skin goes back to its neighbours; Ctrl+Z brings it back" if drawn
                     else "Delete: the layer (Del); a density layer goes with its mask; a drawn lock. Ctrl+Z brings"
                          " it back")


def row_menu(ui, row: dict, menu: QMenu, ids: list[int]) -> None:
    """A lock row's right-click: Edit points, Reset shape, Delete drawn lock."""
    z = ui.z
    menu.addSeparator()
    menu.addAction(_lucide_icon("spline", z.px(15)), "Edit points    Enter").triggered.connect(
        lambda: (ui._fire("select", "locks", tuple(ids)), ui._fire("set_tool", S.TOOL_POINTS)))
    edited = [r["id"] for r in ui._selected_rows() if r.get("kind") == "locks" and r.get("shape_edited")
              and r["id"] in ids] or ([row["id"]] if row.get("shape_edited") else [])
    act = menu.addAction(_lucide_icon("rotate-ccw", z.px(15)), "Reset shape")
    act.setEnabled(bool(edited))
    act.triggered.connect(lambda: ui._fire("reset_shape", edited))
    drawn = [r["id"] for r in ui._selected_rows() if r.get("kind") == "locks" and r.get("drawn") and r["id"] in ids] \
        or ([row["id"]] if row.get("drawn") else [])
    if drawn:
        menu.addAction(_lucide_icon("trash", z.px(15), TEXT_ERROR), "Delete drawn lock    Del").triggered.connect(
            lambda: ui._fire("delete_drawn", drawn))


def warn_pixmap(size: int):
    return _lucide_pixmap("triangle-alert", size, _ui().WARN)


__all__ = ["build_tool_bar", "build_tool_strip", "show_tools", "relayout", "install_keys", "row_icon",
           "status_parts", "status_help", "action_buttons", "drawn_section", "install_tree_tools", "delete_selected",
           "update_tree_tools", "row_menu", "sheet", "WARN_ICON"]
_ = (QFont, TEXT_META)
