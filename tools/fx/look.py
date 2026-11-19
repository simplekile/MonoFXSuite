"""
The suite's shared look helpers for tool windows in the MonoFX Loader's style: one source for the MonoFX Loader
manager (`tools/fx/anim_loader/ui.py`) and the MONO Grooming panel (`tools/fx/grooming/ui_look.py`).

The two tools had diverged copies (2026-11-19). Where they really differ, each keeps its own result through a
parameter (`scale_css(borders=)`, `crisp_icon(selected=, disabled=, cache=)`) or a thin subclass (`PropsBase`,
`SectionBase`); the defaults are the Loader's, which is released and must not change.

The palette itself stays in `tools/fx/auto_material/ui.py`; this module holds the Monos interaction states and
the pieces built on the palette. View only: nothing here reads or writes a scene.
"""

from __future__ import annotations

import re

from PySide6.QtCore import QPointF, QSize, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QGridLayout, QPushButton, QWidget

from tools.fx.auto_material.ui import LUCIDE, TEXT_LABEL, TEXT_PRIMARY, _lucide_pixmap

# Monos states (docs/ui_states_rules.md): pressed a step past hover, selected + hover brighter than selected
PRESSED = "#26262d"          # a ghost / bordered button held down
FLAT_HOVER = "#1f1f25"       # BG_HOVER: a flat icon button under the mouse
FLAT_PRESSED = "#2c2c34"
CHECKED = "#1f2a45"          # a checked toggle: the accent over the pane, opaque (ACCENT on it 4.50:1)
CHECKED_HOVER = "#22305a"    # (ACCENT on it 4.05:1)
CHECKED_PRESSED = "#1c2850"
PRIMARY_PRESSED = "#2f5bd8"  # the primary button held down (white on it 5.82:1)
# A selected row under the mouse: the Loader's #2e3c5f gives TEXT_LABEL 4.36:1; the grooming panel takes #2c395b
# (4.56:1). Both are kept as they are: the Loader is released and its pixels do not change.
SELECTED_HOVER_LOADER = "#2e3c5f"
SELECTED_HOVER = "#2c395b"

LUCIDE.setdefault("chevron-right", '<path d="m9 18 6-6-6-6"/>')
LUCIDE.setdefault("chevron-down", '<path d="m6 9 6 6 6-6"/>')


def border_px(scale: float) -> int:
    """Width of a rounded control's border: 2 px at least (1 px breaks on rounded corners, Qt does not anti-alias a
    style sheet border), more under a large UI scale. Dividers stay hairlines."""
    return max(2, round(1.5 * scale))


def round_borders(css: str, scale: float) -> str:
    """`border: 1px` (a rounded control's whole border) -> `border_px(scale)`; `border-bottom: 1px` and the like
    (dividers) are left as they are."""
    return re.sub(r"border:\s*1px", f"border: {border_px(scale)}px", css)


def scale_css(css: str, scale: float, borders: bool = True) -> str:
    """Every size in a style sheet times the UI scale; 1 px lines stay 1 px. `borders` (the Loader's rule): a
    control's whole border then becomes `border_px`, after the scale (no double scaling). The grooming panel takes
    that step on its own (`round_borders`), so it passes False."""
    def one(m):
        v = float(m.group(1))
        return m.group(0) if v <= 1 else f"{round(v * scale)}px"

    css = css if scale == 1 else re.sub(r"(\d+(?:\.\d+)?)px", one, css)
    return round_borders(css, scale) if borders else css


_crisp_cache: dict = {}


def crisp_icon(name: str, size: int, color: str, *, selected: bool = False, disabled: str | None = None,
               cache: bool = False) -> QIcon:
    """A Lucide icon drawn at ``size`` logical px for every device-pixel ratio Houdini may use: scaling one small
    pixmap up broke the strokes (the Loader's search icon, the user's report 2026-11-17).
    `selected`: the Selected mode keeps the colour (Qt tints it on a selected row). `disabled`: a colour for the
    Disabled mode (Houdini's style drew the Normal pixmap, so disabled buttons looked usable, the user on the
    grooming panel). `cache`: one QIcon per (name, size, colour, modes). The defaults are the Loader's icon."""
    key = (name, size, color, selected, disabled)
    if cache and key in _crisp_cache:
        return _crisp_cache[key]
    icon = QIcon()
    for ratio in (1.0, 1.25, 1.5, 1.75, 2.0, 2.5, 3.0):
        pm = _lucide_pixmap(name, size, color, ratio)
        icon.addPixmap(pm, QIcon.Mode.Normal)
        if selected:
            icon.addPixmap(pm, QIcon.Mode.Selected)
        if disabled:
            icon.addPixmap(_lucide_pixmap(name, size, disabled, ratio), QIcon.Mode.Disabled)
    if cache:
        _crisp_cache[key] = icon
    return icon


# A toggle that is on draws filled (the user's ask): the shape solid, its inner part (the pupil, the lens) cut out
# so the row shows through; off stays the outline with its slash. Shapes from Lucide (ISC), in its 24-unit box.
FILLED = {
    "eye": ('<path d="M2.062 12.348a1 1 0 0 1 0-.696 10.75 10.75 0 0 1 19.876 0 1 1 0 0 1 0 .696 10.75 10.75 0 0 1'
            '-19.876 0"/>', (12.0, 12.0, 3.4)),
    "monitor": ('<rect width="20" height="14" x="2" y="3" rx="2"/><path d="M8 21h8M12 17v4" fill="none"/>', None),
    "camera": ('<path d="M14.5 4h-5L7 7H4a2 2 0 0 0-2 2v9a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2V9a2 2 0 0 0-2-2h-3l-2.5-3z"/>',
               (12.0, 13.0, 3.4)),
}
_filled_cache: dict = {}


def filled_pixmap(name: str, size: int, color: str, ratio: float = 2.0) -> QPixmap:
    """`FILLED[name]` solid in `color`, its hole cut out (transparent), at `ratio` device pixels per px."""
    from PySide6.QtSvg import QSvgRenderer

    key = (name, size, color, ratio)
    if key not in _filled_cache:
        body, hole = FILLED[name]
        phys = max(1, int(size * ratio))
        svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{phys}" height="{phys}" viewBox="0 0 24 24" '
               f'fill="{color}" stroke="{color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
               f"{body}</svg>")
        pm = QPixmap(phys, phys)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        QSvgRenderer(svg.encode("utf-8")).render(p)
        if hole is not None:  # the pupil / the lens: cut out, not painted, so it reads on any row colour
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
    """An eye cell: drawn = the filled eye, not drawn = the outline with its slash (one look per state)."""
    if on:
        return filled_pixmap("eye", size, color, ratio)
    return _lucide_pixmap("eye-off", size, color, ratio)


class PropsBase(QWidget):
    """Rows of label and value in a grid, the label column on the left, the value wrapping (details as a list,
    never joined by dots: the user's rule, 2026-11-17). A tool's subclass makes the two labels (`_cell`) and says
    when the block shows (`_shown`); rows are (label, value) or (label, value, colour), '' colour = TEXT_PRIMARY."""

    def __init__(self, px, left: int = 0) -> None:
        super().__init__()
        self.grid = QGridLayout(self)
        self.grid.setContentsMargins(left, 0, 0, 0)
        self.grid.setHorizontalSpacing(px(12))
        self.grid.setVerticalSpacing(px(4))
        self.grid.setColumnStretch(1, 1)

    def _cell(self, text: str, value: bool, color: str):   # pragma: no cover - each tool's own
        raise NotImplementedError

    def _shown(self, has_rows: bool) -> None:
        self.setVisible(has_rows)

    def set_rows(self, rows: list) -> None:
        while self.grid.count():
            w = self.grid.takeAt(0).widget()
            if w is not None:  # off at once: taken out of the grid it stayed painted over the new rows until deleted
                w.hide()
                w.setParent(None)
                w.deleteLater()
        for i, row in enumerate(rows):
            label, value = row[0], row[1]
            color = row[2] if len(row) > 2 and row[2] else TEXT_PRIMARY
            k = self._cell(label, False, TEXT_LABEL)
            k.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
            v = self._cell(value, True, color)
            v.setWordWrap(True)
            v.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            self.grid.addWidget(k, i, 0)
            self.grid.addWidget(v, i, 1)
        self._shown(bool(rows))

    def rows(self) -> dict[str, str]:
        """{label: value} as shown (tests)."""
        out = {}
        for i in range(self.grid.rowCount()):
            k, v = self.grid.itemAtPosition(i, 0), self.grid.itemAtPosition(i, 1)
            if k and v and k.widget() and v.widget():
                out[k.widget().text()] = v.widget().text()
        return out


class SectionBase(QPushButton):
    """A section title that folds the widget under it: chevron + caps label. Folded or open is view state, kept
    per viewer in the tool's prefs (``inspector_<key>``, through `load` / `save`), never in the scene. A tool's
    subclass styles it and decides in `apply()` what shows."""

    def __init__(self, title: str, key: str, body: QWidget, px, load, save, default_open: bool = True,
                 min_height: int = 24) -> None:
        super().__init__(title.upper())
        self.key, self.body, self._px = key, body, px
        self._load, self._save = load, save
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setCheckable(True)
        stored = load().get(f"inspector_{key}")
        self.setChecked(default_open if stored is None else stored is not False)
        self.setMinimumHeight(min_height)
        self.setIconSize(QSize(px(14), px(14)))
        self.toggled.connect(self._toggled)
        self._paint_icon()

    def apply(self) -> None:
        self.body.setVisible(self.isChecked())

    def chevron(self, name: str) -> QIcon:
        """The fold icon (a tool may draw it its own way)."""
        return crisp_icon(name, self._px(14), TEXT_LABEL)

    def _paint_icon(self) -> None:
        self.setIcon(self.chevron("chevron-down" if self.isChecked() else "chevron-right"))
        self.setToolTip("Fold this section" if self.isChecked() else "Show this section")

    def _toggled(self, on: bool) -> None:
        prefs = self._load()
        prefs[f"inspector_{self.key}"] = on
        self._save(prefs)
        self._paint_icon()
        self.apply()


_ = TEXT_PRIMARY
