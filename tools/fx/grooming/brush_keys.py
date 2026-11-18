"""
What the Paint state shows and how its keys change the brush (v0.2a last task, decided 2026-11-19: like
Houdini's Attribute Paint). Pure: no hou, so it is tested without Houdini; `apps/houdini/grooming_paint_state.py`
binds it to the viewer state.

- the hint overlay (HUD, `hud_template` / `hud_values`): the keys and the live radius, softness, grey, mode;
  Houdini's Shift+F1 hides it, like every state's hints;
- the parameter bar above the viewport (`BAR`): Radius, Softness, Grey, Eraser, the same fields as the
  panel's Properties (one source: `grooming_masks.BRUSH` through `set_brush`);
- the mouse wheel (`wheel_radius`) and Ctrl+Shift+LMB drag (`drag_radius`) change the radius, F swaps paint /
  erase, the right-click menu (`MENU`, `menu_fields`) holds the same and radius / grey picks.
"""

from __future__ import annotations

import math

from tools.fx.grooming import config

RADIUS_MIN_CM, RADIUS_MAX_CM = 0.05, 50.0   # what grooming_masks.set_brush keeps the radius within
RADIUS_BAR_MAX_CM = 5.0                     # the bar's slider and the HUD's bar end here (the panel's range)
WHEEL_STEP = 1.1                            # one wheel notch: the radius x 1.1 (up) or / 1.1 (down)
DRAG_DOUBLE_PX = 120.0                      # Ctrl+Shift drag: the radius doubles every 120 px to the right
RADIUS_PICKS_CM = (0.25, 0.5, 1.0, 2.0, 4.0)
GREY_PICKS = tuple(config.MASK_VALUE_PICKS)

# the bar: (BRUSH field, state parm name, label)
BAR = (("radius_cm", "radius", "Radius"), ("soft", "soft", "Softness"), ("value", "grey", "Grey"),
       ("erase", "eraser", "Eraser"))
PARM_TO_FIELD = {parm: field for field, parm, _label in BAR}

SWAP = "swap"           # menu item and hotkey: paint <-> erase
SWAP_KEY = "f"
LMB, CTRL_LMB, DRAG_KEY = "LMB", "Ctrl + LMB", "Ctrl + Shift + LMB"


STEPS_MAX = 200.0     # wheel notches / drag doublings taken at once at most: past it the radius is at a limit anyway


def _finite(x, default: float) -> float:
    try:
        x = float(x)
    except (TypeError, ValueError, OverflowError):
        return default
    return x if math.isfinite(x) else (default if math.isnan(x) else math.copysign(1e300, x))


def clamp_radius(radius_cm) -> float:
    """A radius inside the brush's limits, finite whatever comes in (NaN: the default radius; +-inf: a limit)."""
    return min(max(_finite(radius_cm, config.BRUSH_RADIUS_CM), RADIUS_MIN_CM), RADIUS_MAX_CM)


def _scaled(radius_cm, base: float, power) -> float:
    p = min(max(_finite(power, 0.0), -STEPS_MAX), STEPS_MAX)
    return clamp_radius(clamp_radius(radius_cm) * base ** p)


def wheel_radius(radius_cm: float, notches: float) -> float:
    """The radius after `notches` wheel notches (Houdini gives +1 / -1 a notch; up = larger)."""
    return _scaled(radius_cm, WHEEL_STEP, notches)


def drag_radius(start_cm: float, dx_px: float) -> float:
    """Ctrl+Shift+LMB drag: the radius from the one at the press and how far the mouse went right (px)."""
    return _scaled(start_cm, 2.0, _finite(dx_px, 0.0) / DRAG_DOUBLE_PX)


def mode_name(erase: bool) -> str:
    return "Erase" if erase else "Paint"


def hud_template() -> dict:
    """The HUD's rows (set once on entering the state; `hud_values` fills them)."""
    return {
        "title": "MONO Grooming", "desc": "Paint mask", "icon": "SOP_paint",
        "rows": [
            {"id": "layer", "label": "Layer", "value": ""},
            {"id": "mode", "label": "Mode", "key": SWAP_KEY.upper(), "value": "Paint"},
            {"id": "mode_g", "type": "choicegraph", "count": 2},
            {"id": "radius", "label": "Radius", "key": "mousewheel", "value": ""},
            {"id": "radius_g", "type": "bargraph", "value": 0.0},
            {"id": "radius_drag", "label": "Radius, by drag", "key": DRAG_KEY},
            {"id": "soft", "label": "Softness", "value": ""},
            {"id": "grey", "label": "Grey", "value": ""},
            {"type": "divider"},
            {"id": "lmb", "label": "Paint", "key": LMB},
            {"id": "ctrl_lmb", "label": "Erase", "key": CTRL_LMB},
            {"id": "rmb", "label": "Radius, grey, mode", "key": "RMB"},
            {"id": "esc", "label": "Leave Paint", "key": "esc"},
        ],
    }


def radius_text(radius_cm: float) -> str:
    return f"{float(radius_cm):.2f} cm"


def hud_values(brush: dict, layer_name: str = "") -> dict:
    """The HUD's values for these brush settings (strings, as hudInfo takes them; graphs 0..1 / an index)."""
    erase = bool(brush.get("erase"))
    radius = clamp_radius(brush.get("radius_cm", config.BRUSH_RADIUS_CM))
    return {
        "layer": layer_name,
        "mode": mode_name(erase),
        "mode_g": 1 if erase else 0,
        "radius": radius_text(radius),
        "radius_g": min(max(radius / RADIUS_BAR_MAX_CM, 0.0), 1.0),
        "soft": f"{round(float(brush.get('soft', config.BRUSH_SOFT)) * 100):d} %",
        "grey": f"{float(brush.get('value', config.BRUSH_VALUE)):g}",
        "lmb": {"label": mode_name(erase)},
        "ctrl_lmb": {"label": mode_name(not erase)},
    }


def bar_values(brush: dict) -> dict:
    """The bar's parm values for these brush settings."""
    return {parm: (bool(brush.get(field)) if field == "erase" else float(brush.get(field, 0.0)))
            for field, parm, _label in BAR}


def field_change(parm: str, value, brush: dict) -> dict:
    """`set_brush` keywords for a bar parm the artist changed, {} when it is the value the brush has (the bar
    written from the brush must not set it again)."""
    field = PARM_TO_FIELD.get(parm)
    if field is None:
        return {}
    if field == "erase":
        new = bool(value) if not isinstance(value, str) else value.lower() in ("1", "on", "true")
        return {} if new == bool(brush.get("erase")) else {"erase": new}
    new = _finite(value, math.nan)
    if math.isnan(new):
        return {}                     # nothing a brush can take: the bar is written back from the brush
    new = clamp_radius(new) if field == "radius_cm" else min(max(new, 0.0), 1.0)
    return {} if math.isclose(new, _finite(brush.get(field, 0.0), 0.0), abs_tol=1e-6) else {field: new}


def menu_items() -> list[tuple[str, str, str]]:
    """The right-click menu: (submenu or "", item id, label), in order."""
    items = [("", SWAP, "Paint / Erase")]
    items += [("Radius", "radius_down", "Smaller (/ 1.25)"), ("Radius", "radius_up", "Larger (x 1.25)")]
    items += [("Radius", f"radius_{r:g}", radius_text(r)) for r in RADIUS_PICKS_CM]
    items += [("Grey", f"grey_{g:g}", f"{g:g}") for g in GREY_PICKS]
    return items


def menu_fields(item: str, brush: dict) -> dict:
    """`set_brush` keywords for a right-click menu item (or the F hotkey), {} for an item it does not know."""
    radius = clamp_radius(brush.get("radius_cm", config.BRUSH_RADIUS_CM))
    if item == SWAP:
        return {"erase": not bool(brush.get("erase"))}
    if item == "radius_down":
        return {"radius_cm": clamp_radius(radius / 1.25)}
    if item == "radius_up":
        return {"radius_cm": clamp_radius(radius * 1.25)}
    for prefix, field in (("radius_", "radius_cm"), ("grey_", "value")):
        if item.startswith(prefix):
            value = _finite(item[len(prefix):], math.nan)
            if math.isnan(value):
                return {}
            return {field: clamp_radius(value) if field == "radius_cm" else min(max(value, 0.0), 1.0)}
    return {}


__all__ = ["BAR", "PARM_TO_FIELD", "SWAP", "SWAP_KEY", "WHEEL_STEP", "DRAG_DOUBLE_PX", "RADIUS_PICKS_CM",
           "GREY_PICKS", "clamp_radius", "wheel_radius", "drag_radius", "mode_name", "hud_template", "hud_values",
           "radius_text", "bar_values", "field_change", "menu_items", "menu_fields"]
