"""
MONO Grooming panel: the MonoFX Loader's look (t74, the user's pick "C", 2026-11-19).

Small pieces the Loader manager window has on main (`tools/fx/anim_loader/ui.py`) and this branch does not: the
same names (`_border_px`, `scale_css`, `_crisp_icon`, `_filled_pixmap`, `_Props`, `_Section`, `STATES_*`), so the two
can become one shared module once the branch meets main. `tools.fx.anim_loader` is not imported: it is not on this
branch. Everything here is view only; nothing reads or writes the scene.
"""

from __future__ import annotations

import re

from PySide6.QtCore import QPointF, QSize, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QGridLayout, QLabel, QPushButton, QWidget

from tools.fx.auto_material.ui import LUCIDE, TEXT_LABEL, TEXT_PRIMARY, _lucide_pixmap

LUCIDE.setdefault("eye-off", '<path d="M10.733 5.076a10.744 10.744 0 0 1 11.205 6.575 1 1 0 0 1 0 .696 10.747 10.747 0 0 1'
                             '-1.444 2.49"/><path d="M14.084 14.158a3 3 0 0 1-4.242-4.242"/><path d="M17.479 17.499a10.75'
                             ' 10.75 0 0 1-15.417-5.151 1 1 0 0 1 0-.696 10.75 10.75 0 0 1 4.446-5.143"/><path d="m2 2 20 20"/>')
LUCIDE.setdefault("chevron-right", '<path d="m9 18 6-6-6-6"/>')
LUCIDE.setdefault("chevron-down", '<path d="m6 9 6 6 6-6"/>')

# Monos states (the Loader's STATES_*): pressed a step past hover, selected + hover brighter than selected
PRESSED = "#26262d"         # a ghost / bordered button held down
FLAT_HOVER = "#1f1f25"      # BG_HOVER: a flat icon button under the mouse
FLAT_PRESSED = "#2c2c34"
CHECKED = "#1f2a45"         # a checked toggle: the accent over the pane, opaque (ACCENT on it 4.50:1)
CHECKED_HOVER = "#22305a"   # (ACCENT on it 4.05:1)
CHECKED_PRESSED = "#1c2850"
PRIMARY_PRESSED = "#2f5bd8"  # Publish held down (white on it 5.82:1)
SELECTED_HOVER = "#2c395b"  # a selected row under the mouse (TEXT_LABEL on it 4.56:1; the Loader's #2e3c5f is 4.36:1)


def _border_px(scale: float) -> int:
    """Width of a rounded control's border: 2 px at least (1 px breaks on rounded corners, Qt does not anti-alias a
    style sheet border), more under a large UI scale. Dividers stay hairlines."""
    return max(2, round(1.5 * scale))


def scale_css(css: str, scale: float) -> str:
    """Every size in a style sheet times the UI scale; 1 px lines stay 1 px; a whole border (`border: 1px`) becomes
    `_border_px` (the Loader's rule). The grooming sheet is written in scaled px already, so it only takes the
    border step (scale 1 here, the real scale for the width)."""
    def one(m):
        v = float(m.group(1))
        return m.group(0) if v <= 1 else f"{round(v * scale)}px"

    return re.sub(r"(\d+(?:\.\d+)?)px", one, css) if scale != 1 else css


def round_borders(css: str, scale: float) -> str:
    """`border: 1px` (a rounded control's whole border) -> `_border_px(scale)`; `border-bottom: 1px` and the like
    (dividers) are left as they are."""
    return re.sub(r"border:\s*1px", f"border: {_border_px(scale)}px", css)


_crisp_cache: dict = {}


def _crisp_icon(name: str, size: int, color: str) -> QIcon:
    """A Lucide icon drawn at ``size`` logical px for every device-pixel ratio Houdini may use (one small pixmap
    scaled up broke the strokes, the Loader's search icon). Selected mode keeps the colour (Qt tints it)."""
    key = (name, size, color)
    if key not in _crisp_cache:
        icon = QIcon()
        for ratio in (1.0, 1.25, 1.5, 1.75, 2.0, 2.5, 3.0):
            pm = _lucide_pixmap(name, size, color, ratio)
            icon.addPixmap(pm, QIcon.Mode.Normal)
            icon.addPixmap(pm, QIcon.Mode.Selected)
        _crisp_cache[key] = icon
    return _crisp_cache[key]


# A toggle that is on draws filled: the shape solid, its inner part (the pupil) cut out so the row shows through;
# off stays the outline with its slash. Shapes from Lucide (ISC), in its 24-unit box.
_FILLED = {
    "eye": ('<path d="M2.062 12.348a1 1 0 0 1 0-.696 10.75 10.75 0 0 1 19.876 0 1 1 0 0 1 0 .696 10.75 10.75 0 0 1'
            '-19.876 0"/>', (12.0, 12.0, 3.4)),
}
_filled_cache: dict = {}


def _filled_pixmap(name: str, size: int, color: str, ratio: float = 2.0) -> QPixmap:
    from PySide6.QtSvg import QSvgRenderer

    key = (name, size, color, ratio)
    if key not in _filled_cache:
        body, hole = _FILLED[name]
        phys = max(1, int(size * ratio))
        svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{phys}" height="{phys}" viewBox="0 0 24 24" '
               f'fill="{color}" stroke="{color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
               f"{body}</svg>")
        pm = QPixmap(phys, phys)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        QSvgRenderer(svg.encode("utf-8")).render(p)
        if hole is not None:   # cut out, not painted, so it reads on any row colour
            p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(0, 0, 0))
            k = phys / 24.0
            p.drawEllipse(QPointF(hole[0] * k, hole[1] * k), hole[2] * k, hole[2] * k)
        p.end()
        pm.setDevicePixelRatio(ratio)
        _filled_cache[key] = pm
    return _filled_cache[key]


def eye_pixmap(on: bool, size: int, color: str, ratio: float = 2.0) -> QPixmap:
    """The eye cell: drawn = filled eye, not drawn = the outline with its slash (one look per state)."""
    if on:
        return _filled_pixmap("eye", size, color, ratio)
    return _lucide_pixmap("eye-off", size, color, ratio)


class _Props(QWidget):
    """Rows of label and value, the label in TEXT_LABEL, the value in TEXT_PRIMARY (or its own colour): details
    as a list, never joined by dots (the user's rule on the Loader, 2026-11-17, and here 2026-11-19)."""

    def __init__(self, z, label_role: str = "small", value_role: str = "small") -> None:
        super().__init__()
        self.z = z
        self._roles = (label_role, value_role)
        self.grid = QGridLayout(self)
        self.grid.setContentsMargins(z.px(2), 0, 0, 0)
        self.grid.setHorizontalSpacing(z.px(12))
        self.grid.setVerticalSpacing(z.px(4))
        self.grid.setColumnStretch(1, 1)

    def set_rows(self, rows: list) -> None:
        """(label, value) or (label, value, colour) rows; '' colour = TEXT_PRIMARY."""
        while self.grid.count():
            w = self.grid.takeAt(0).widget()
            if w is not None:
                w.hide()
                w.setParent(None)
                w.deleteLater()
        for i, row in enumerate(rows):
            label, value = row[0], row[1]
            color = row[2] if len(row) > 2 and row[2] else TEXT_PRIMARY
            k = QLabel(label)
            k.setProperty("role", self._roles[0])
            k.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
            v = QLabel(value)
            v.setProperty("role", self._roles[1])
            v.setStyleSheet(f"color: {color};")
            v.setWordWrap(True)
            v.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            self.grid.addWidget(k, i, 0)
            self.grid.addWidget(v, i, 1)
        if not rows:
            self.hide()
        elif self.parent() is not None:   # never shown on its own: it would be a window that flashes up
            self.show()

    def rows(self) -> dict[str, str]:
        """{label: value} as shown (tests)."""
        out = {}
        for i in range(self.grid.rowCount()):
            k, v = self.grid.itemAtPosition(i, 0), self.grid.itemAtPosition(i, 1)
            if k and v and k.widget() and v.widget():
                out[k.widget().text()] = v.widget().text()
        return out


class _Section(QPushButton):
    """A section title that folds the widget under it: chevron + caps label, flat, a hairline under it. Folded or
    open is view state, kept per viewer in the panel's prefs (``inspector_<key>``), never in the scene."""

    def __init__(self, z, title: str, key: str, body: QWidget, load, save, default_open: bool = True) -> None:
        super().__init__(title.upper())
        self.z, self.key, self.body = z, key, body
        self._load, self._save = load, save
        self.setObjectName("Section")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setCheckable(True)
        stored = load().get(f"inspector_{key}")
        self.setChecked(default_open if stored is None else stored is not False)
        self.setMinimumHeight(max(24, z.px(28)))   # a 24 px target at least
        self.setIconSize(QSize(z.px(14), z.px(14)))
        self.setAccessibleName(f"{title} section")
        self.toggled.connect(self._toggled)
        self._paint_icon()   # the body's visibility is set by apply(), once both have a parent (shown alone, a widget
                             # is a window of its own that flashes up)

    def apply(self) -> None:
        self.body.setVisible(self.isChecked())

    def _paint_icon(self) -> None:
        self.setIcon(_crisp_icon("chevron-down" if self.isChecked() else "chevron-right", self.z.px(14), TEXT_LABEL))
        self.setToolTip("Fold this section" if self.isChecked() else "Show this section")

    def _toggled(self, on: bool) -> None:
        prefs = self._load()
        prefs[f"inspector_{self.key}"] = on
        self._save(prefs)
        self._paint_icon()
        self.body.setVisible(on)


__all__ = ["CHECKED", "CHECKED_HOVER", "CHECKED_PRESSED", "FLAT_HOVER", "FLAT_PRESSED", "PRESSED", "PRIMARY_PRESSED",
           "SELECTED_HOVER", "_Props", "_Section", "_border_px", "_crisp_icon", "_filled_pixmap", "eye_pixmap",
           "round_borders", "scale_css"]
_ = TEXT_PRIMARY
