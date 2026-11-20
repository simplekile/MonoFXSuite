"""
MONO Grooming panel: the MonoFX Loader's look (t74, the user's pick "C", 2026-11-19).

The helpers are the suite's shared ones (`tools/fx/look.py`, also the Loader manager's), under the names this panel
uses; where the panel differs from the Loader it says so here: icons keep their colour on a selected row and have
a dim Disabled pixmap, cached (`_crisp_icon`); `scale_css` leaves borders to `round_borders` (the grooming sheet is
written in scaled px already); `_Props` / `_Section` take the panel's `Sz` and role labels; a selected row under
the mouse is #2c395b. The panel-only colours (BUTTON..., DISABLED_ICON) live here. View only: nothing reads or
writes the scene.
"""

from __future__ import annotations

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QLabel, QWidget

from tools.fx import look
from tools.fx.auto_material.ui import LUCIDE, TEXT_PRIMARY
from tools.fx.look import (CHECKED, CHECKED_HOVER, CHECKED_PRESSED, FLAT_HOVER, FLAT_PRESSED, PRESSED,
                           PRIMARY_PRESSED, SELECTED_HOVER, eye_pixmap, round_borders)

LUCIDE.setdefault("eye-off", '<path d="M10.733 5.076a10.744 10.744 0 0 1 11.205 6.575 1 1 0 0 1 0 .696 10.747 10.747 0 0 1'
                             '-1.444 2.49"/><path d="M14.084 14.158a3 3 0 0 1-4.242-4.242"/><path d="M17.479 17.499a10.75'
                             ' 10.75 0 0 1-15.417-5.151 1 1 0 0 1 0-.696 10.75 10.75 0 0 1 4.446-5.143"/><path d="m2 2 20 20"/>')

# A bordered button is FILLED, a field is not (the user, t74: quick picks "0 75 150 300" read as fields). Fields
# stay BG_RAISED #18181d, inset; buttons sit above the pane: fill, a lighter hover, a darker press.
BUTTON = "#25252c"
DISABLED_ICON = "#45454e"   # an icon that cannot be used now (TEXT_LABEL #a3a3ae when it can); WCAG exempts it
BUTTON_HOVER = "#2e2e36"
BUTTON_PRESSED = "#1d1d23"
BUTTON_DISABLED = "#1c1c21"

_border_px = look.border_px
_filled_pixmap = look.filled_pixmap


def scale_css(css: str, scale: float) -> str:
    """Sizes x the scale, 1 px lines kept; borders are `round_borders`' (this sheet is in scaled px already)."""
    return look.scale_css(css, scale, borders=False)


def _crisp_icon(name: str, size: int, color: str) -> QIcon:
    """The shared crisp icon, Selected mode in its own colour (Qt tints it), a dim Disabled pixmap: Houdini's style
    drew the Normal one, so "+ up down delete" looked the same whether they could be used or not (the user, t74)."""
    return look.crisp_icon(name, size, color, selected=True, disabled=DISABLED_ICON, cache=True)


class _Props(look.PropsBase):
    """Rows of label and value (`look.PropsBase`) in the panel's roles: the label in its role's colour
    (TEXT_LABEL), the value in TEXT_PRIMARY or its own colour (the user's rule: never joined by dots)."""

    def __init__(self, z, label_role: str = "small", value_role: str = "small") -> None:
        super().__init__(z.px, left=z.px(2))
        self.z = z
        self._roles = (label_role, value_role)

    def _cell(self, text: str, value: bool, color: str) -> QLabel:
        cell = QLabel(text)
        cell.setProperty("role", self._roles[1 if value else 0])
        if value:
            cell.setStyleSheet(f"color: {color};")
        return cell

    def _shown(self, has_rows: bool) -> None:
        if not has_rows:
            self.hide()
        elif self.parent() is not None:   # never shown on its own: it would be a window that flashes up
            self.show()


class _Section(look.SectionBase):
    """A section title that folds the widget under it (`look.SectionBase`): flat, a hairline under it (the sheet's
    `#Section`), a 24 px target at least; the prefs are the panel's (``inspector_<key>``)."""

    def __init__(self, z, title: str, key: str, body: QWidget, load, save, default_open: bool = True) -> None:
        self.z = z
        super().__init__(title, key, body, z.px, load, save, default_open, min_height=max(24, z.px(28)))
        self.setObjectName("Section")
        self.setAccessibleName(f"{title} section")
        # the body's visibility is set by apply(), once both have a parent (shown alone, a widget is a window of its
        # own that flashes up)

    def chevron(self, name: str) -> QIcon:
        return _crisp_icon(name, self.z.px(14), look.TEXT_LABEL)


__all__ = ["BUTTON", "BUTTON_DISABLED", "BUTTON_HOVER", "BUTTON_PRESSED", "CHECKED", "DISABLED_ICON", "CHECKED_HOVER", "CHECKED_PRESSED", "FLAT_HOVER", "FLAT_PRESSED", "PRESSED", "PRIMARY_PRESSED",
           "SELECTED_HOVER", "_Props", "_Section", "_border_px", "_crisp_icon", "_filled_pixmap", "eye_pixmap",
           "round_borders", "scale_css"]
_ = TEXT_PRIMARY
