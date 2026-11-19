"""tools/fx/look.py: one source for the MonoFX Loader's and the MONO Grooming panel's look helpers; the defaults are
the Loader's (released), each tool's own differences go through parameters or thin subclasses."""

from __future__ import annotations

import pytest


@pytest.fixture(scope="module")
def app():
    QtWidgets = pytest.importorskip("PySide6.QtWidgets")
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def test_both_tools_use_the_shared_helpers(app) -> None:
    from tools.fx import look
    from tools.fx.anim_loader import ui as loader
    from tools.fx.grooming import ui_look

    assert loader._crisp_icon is look.crisp_icon and loader._filled_pixmap is look.filled_pixmap
    assert loader.scale_css is look.scale_css and loader._border_px is look.border_px
    assert issubclass(loader._Props, look.PropsBase) and issubclass(loader._Section, look.SectionBase)
    assert ui_look._filled_pixmap is look.filled_pixmap and ui_look.eye_pixmap is look.eye_pixmap
    assert issubclass(ui_look._Props, look.PropsBase) and issubclass(ui_look._Section, look.SectionBase)
    assert loader.STATES_PRIMARY == "QPushButton:pressed { background: #2f5bd8; }"


def test_scale_css_border_step_is_the_loaders_default_and_off_for_grooming(app) -> None:
    from tools.fx import look
    from tools.fx.grooming import ui_look

    css = "a { padding: 9px; border: 1px solid; border-bottom: 1px solid; }"
    assert look.scale_css(css, 1.5) == "a { padding: 14px; border: 2px solid; border-bottom: 1px solid; }"
    assert ui_look.scale_css(css, 1.5) == "a { padding: 14px; border: 1px solid; border-bottom: 1px solid; }"


def test_crisp_icon_modes_follow_the_parameters(app) -> None:
    from PySide6.QtGui import QIcon
    from tools.fx import look
    from tools.fx.grooming import ui_look

    def bright(icon, mode):
        img = icon.pixmap(16, mode).toImage()
        return max(img.pixelColor(x, y).lightness() for x in range(img.width()) for y in range(img.height())
                   if img.pixelColor(x, y).alpha() > 200)

    plain = look.crisp_icon("plus", 16, "#a3a3ae")
    assert plain.availableSizes(QIcon.Mode.Disabled) == []          # the Loader's icon: Normal pixmaps only
    dim = ui_look._crisp_icon("plus", 16, "#a3a3ae")
    assert bright(dim, QIcon.Mode.Disabled) < bright(dim, QIcon.Mode.Normal) - 40
    assert ui_look._crisp_icon("plus", 16, "#a3a3ae") is dim         # cached for the panel
    assert look.crisp_icon("plus", 16, "#a3a3ae") is not plain       # not for the Loader
