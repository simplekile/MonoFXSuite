"""
The tools of lock control points (v0.2b B3): what the Edit points / Draw lock viewer state shows, how its keys and
gestures read, and the one record of the tool in hand that the state, the state bar, the HUD and the panel share.
Pure: no hou and no Qt, so it is tested without Houdini; `apps/houdini/grooming_points_state.py` binds it to the
viewer state (as `brush_keys.py` is to Paint's).

- `STATE` (a `ToolRecord`): `tool` (`TOOL_SELECT` / `TOOL_POINTS` / `TOOL_DRAW` / `TOOL_PAINT`: who has the viewport),
  `mode` (the sticky drag mode, `MODES`), `lock_ids` (the locks whose handles show; after a draw, the new lock),
  `width_cm`, `thick_cm`, `taper` (the next drawn lock's), plus `held` (a mode held by its key for one drag, "" when
  none: the panel lights that cell), `message` (the last sentence for the panel's line) and `node` (the node's path).
  `update(**fields)` changes it and calls every `HOOKS["tool"]` callable with the record when something changed.
- Gestures (the design gate, review_b finding 3): the strip's switch is the sticky mode; R / E / Shift held at the
  press act for that drag only (`drag_mode`). A press on a handle wins over the hair under it; a click (no drag)
  on hair selects that lock, Shift / Ctrl extends or toggles (`click_selection`), on empty space keeps the selection.
- The HUD (`hud_template` / `hud_values`) and the state bar (`BAR`) as mockup B sketched them.
"""

from __future__ import annotations

import math
from typing import Any, Callable, Iterable

from tools.fx.grooming import config

TOOL_SELECT = "select"
TOOL_POINTS = "points"
TOOL_DRAW = "draw"
TOOL_PAINT = "paint"
TOOLS = (TOOL_SELECT, TOOL_POINTS, TOOL_DRAW, TOOL_PAINT)
MODES = ("move", "rotate", "scale", "redraw")
MODE_LABELS = {"move": "Move", "rotate": "Rotate", "scale": "Scale", "redraw": "Redraw"}
MODE_STEP = {"move": "move", "rotate": "rotate", "scale": "scale", "redraw": "redraw"}   # config.UNDO_SPINE keys
KEY_ROTATE, KEY_SCALE = "r", "e"            # held at the press: that drag rotates / scales about the root
HELD_KEYS = {KEY_ROTATE: "rotate", KEY_SCALE: "scale"}
LESS_KEYS = ("-", "minus", "_", "kp_subtract", "keypad-")       # one handle fewer on each lock
MORE_KEYS = ("+", "=", "plus", "equal", "shift+=", "kp_add", "keypad+")   # one handle more

PICK_PX = 14.0          # a press within this of a handle (screen px) takes that handle
HAIR_PICK_PX = 30.0     # a click within this of a lock's spine (screen px) selects that lock
DRAG_PX = 4.0           # a press that moves less than this before release is a click, not a drag
STROKE_STEP_PX = 3.0    # a stroke takes a point every this many px of mouse travel
SCALE_DOUBLE_PX = 200.0  # E + drag: the lock doubles every 200 px to the right (halves to the left)
SCALE_MIN, SCALE_MAX = 0.05, 20.0
WIDTH_MIN_CM, WIDTH_MAX_CM = 0.1, 20.0
THICK_MIN_CM, THICK_MAX_CM = 0.05, 10.0
WHEEL_STEP = 1.1        # one wheel notch: the next lock's width x 1.1 (up) or / 1.1
STEPS_MAX = 200.0

# the state bar: (record field, state parm name, label, tool it shows for)
BAR = (("mode", "drag_mode", "Drag", TOOL_POINTS), ("handles", "handles", "Handles", TOOL_POINTS),
       ("width_cm", "width", "Width", TOOL_DRAW), ("thick_cm", "thickness", "Thickness", TOOL_DRAW),
       ("taper", "taper", "Tip taper", TOOL_DRAW))
HANDLES_AUTO = 0        # the bar's Handles 0 = auto (by length)

HOOKS: dict[str, Any] = {"tool": [], "write": None}
"""`HOOKS["tool"]`: callables called with `STATE` whenever any of it changes (a list; one callable assigned in its
place is called too). `HOOKS["write"](node, result)`: after the state wrote the node (a drag's release, a draw), to
cook inside the panel's loading line; None: the state cooks the node itself."""


def _finite(x, default: float) -> float:
    try:
        x = float(x)
    except (TypeError, ValueError, OverflowError):
        return default
    return x if math.isfinite(x) else default


def clamp(x, lo: float, hi: float, default: float) -> float:
    return min(max(_finite(x, default), lo), hi)


class ToolRecord:
    """The tool in hand, one source for the state, its bar and HUD, and the panel."""

    FIELDS = ("tool", "mode", "lock_ids", "width_cm", "thick_cm", "taper", "held", "message", "node")

    def __init__(self) -> None:
        self.tool = TOOL_SELECT
        self.mode = "move"
        self.lock_ids: list[int] = []
        self.width_cm = float(config.DRAWN_WIDTH_CM)
        self.thick_cm = float(config.DRAWN_THICK_CM)
        self.taper = float(config.DRAWN_TAPER_DEFAULT)
        self.held = ""
        self.message = ""
        self.node = ""

    def as_dict(self) -> dict:
        return {f: (list(getattr(self, f)) if f == "lock_ids" else getattr(self, f)) for f in self.FIELDS}

    def __repr__(self) -> str:
        return f"ToolRecord({self.as_dict()!r})"


STATE = ToolRecord()


def normal_fields(fields: dict, rec: ToolRecord | None = None) -> dict:
    """The fields as the record keeps them (ValueError for a tool or mode it does not know)."""
    rec = STATE if rec is None else rec
    out: dict = {}
    for name, value in fields.items():
        if name == "tool":
            if value not in TOOLS:
                raise ValueError(f"tool {value!r}")
            out[name] = value
        elif name == "mode":
            if value not in MODES:
                raise ValueError(f"drag mode {value!r}")
            out[name] = value
        elif name == "held":
            if value not in ("",) + MODES:
                raise ValueError(f"held mode {value!r}")
            out[name] = value
        elif name == "lock_ids":
            seen: list[int] = []
            for i in value or ():
                if int(i) not in seen:
                    seen.append(int(i))
            out[name] = seen
        elif name == "width_cm":
            out[name] = clamp(value, WIDTH_MIN_CM, WIDTH_MAX_CM, rec.width_cm)
        elif name == "thick_cm":
            out[name] = clamp(value, THICK_MIN_CM, THICK_MAX_CM, rec.thick_cm)
        elif name == "taper":
            out[name] = clamp(value, 0.0, 1.0, rec.taper)
        elif name in ("message", "node"):
            out[name] = "" if value is None else str(value)
        else:
            raise KeyError(f"no field {name!r} in the tool record")
    return out


def _hooks() -> list[Callable]:
    got = HOOKS.get("tool")
    if got is None:
        return []
    if callable(got):
        return [got]
    return list(got)


def update(rec: ToolRecord | None = None, **fields) -> bool:
    """Change the record; every `HOOKS["tool"]` callable hears of it once when something changed. True then."""
    rec = STATE if rec is None else rec
    new = normal_fields(fields, rec)
    changed = False
    for name, value in new.items():
        if getattr(rec, name) != value:
            setattr(rec, name, value)
            changed = True
    if changed and rec is STATE:
        for fn in _hooks():
            try:
                fn(rec)
            except Exception:      # a panel's hook must never break the tool
                pass
    return changed


def reset(rec: ToolRecord | None = None) -> None:
    """Back to Select with no lock (the next lock's width / thickness / taper and the sticky mode stay)."""
    update(rec, tool=TOOL_SELECT, lock_ids=[], held="", node="")


# ---------------------------------------------------------------------------
# gestures
# ---------------------------------------------------------------------------

def drag_mode(sticky: str, held: str = "", shift: bool = False) -> str:
    """The mode of one drag: Shift at the press redraws, a held R / E rotates / scales, else the sticky mode."""
    if shift:
        return "redraw"
    if held in MODES:
        return held
    return sticky if sticky in MODES else "move"


def key_name(key_string: str) -> str:
    """Houdini's keyString ("r", "Shift+=", "Minus" ...) lower case, without spaces."""
    return (key_string or "").strip().lower().replace(" ", "")


def handle_step(key_string: str) -> int:
    """-1 for minus, +1 for plus, 0 for any other key."""
    k = key_name(key_string)
    if k in LESS_KEYS:
        return -1
    if k in MORE_KEYS:
        return 1
    return 0


def next_count(count: int, step: int) -> int:
    """A lock's handle count after one minus / plus, within config.HANDLES_MIN..HANDLES_MAX."""
    return int(min(max(int(count) + int(step), config.HANDLES_MIN), config.HANDLES_MAX))


def bar_handles(value) -> int | None:
    """The bar's Handles field -> `set_handle_count`'s count: 0 (or less) = auto (None), else 4..12."""
    v = int(round(_finite(value, 0.0)))
    if v <= HANDLES_AUTO:
        return None
    return int(min(max(v, config.HANDLES_MIN), config.HANDLES_MAX))


def scale_factor(dx_px: float) -> float:
    """E + drag: the scale about the root from how far the mouse went right (px)."""
    p = min(max(_finite(dx_px, 0.0) / SCALE_DOUBLE_PX, -STEPS_MAX), STEPS_MAX)
    return float(min(max(2.0 ** p, SCALE_MIN), SCALE_MAX))


def wheel_width(width_cm: float, notches: float) -> float:
    p = min(max(_finite(notches, 0.0), -STEPS_MAX), STEPS_MAX)
    return clamp(_finite(width_cm, config.DRAWN_WIDTH_CM) * WHEEL_STEP ** p, WIDTH_MIN_CM, WIDTH_MAX_CM,
                 config.DRAWN_WIDTH_CM)


def signed_angle(a, b, n) -> float:
    """Degrees turning vector a into b about n (right-handed), both projected on the plane normal to n."""
    def dot(u, v):
        return sum(x * y for x, y in zip(u, v))

    def cross(u, v):
        return (u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0])
    nn = math.sqrt(dot(n, n))
    if nn < 1e-12:
        return 0.0
    k = tuple(x / nn for x in n)
    pa = tuple(x - dot(a, k) * y for x, y in zip(a, k))
    pb = tuple(x - dot(b, k) * y for x, y in zip(b, k))
    if dot(pa, pa) < 1e-24 or dot(pb, pb) < 1e-24:
        return 0.0
    return math.degrees(math.atan2(dot(cross(pa, pb), k), dot(pa, pb)))


def is_drag(press_px, now_px) -> bool:
    return math.hypot(now_px[0] - press_px[0], now_px[1] - press_px[1]) >= DRAG_PX


def map_handle(k: int, count_from: int, count_to: int) -> int:
    """Handle k of a lock with `count_from` handles -> the same handle of one with `count_to`: the root and the
    tip map to the root and the tip, the others by their share of the lock."""
    if count_to <= 1 or count_from <= 1:
        return 0
    if k <= 0:
        return 0
    if k >= count_from - 1:
        return count_to - 1
    return int(min(max(round(k / (count_from - 1) * (count_to - 1)), 1), count_to - 2))


def click_selection(current: Iterable[int], hit: int | None, shift: bool = False, ctrl: bool = False) -> list[int]:
    """The selection after a click (no drag) on hair: `hit` the lock under it (None: empty space keeps the
    selection); Shift adds, Ctrl toggles, a plain click selects that lock alone."""
    cur = [int(i) for i in current]
    if hit is None:
        return cur
    hit = int(hit)
    if ctrl:
        return [i for i in cur if i != hit] if hit in cur else cur + [hit]
    if shift:
        return cur if hit in cur else cur + [hit]
    return [hit]


def nearest(dists: dict, limit: float):
    """The key with the smallest distance under `limit` (ties: the smaller key), None when none is."""
    best, got = limit, None
    for key in sorted(dists):
        d = dists[key]
        if d < best:
            best, got = d, key
    return got


# ---------------------------------------------------------------------------
# what the viewport says: HUD rows and values, the state bar
# ---------------------------------------------------------------------------

def handles_text(counts: Iterable[int], set_counts: Iterable) -> str:
    """"auto (4 to 6)", "auto (5)", "8" (the artist's own), "mixed" (some set, differing)."""
    counts = [int(c) for c in counts]
    sets = list(set_counts)
    if not counts:
        return ""
    own = [s for s in sets if s is not None]
    if own and len(own) == len(sets) and len(set(own)) == 1:
        return str(own[0])
    if own:
        return "mixed"
    lo, hi = min(counts), max(counts)
    return f"auto ({lo})" if lo == hi else f"auto ({lo} to {hi})"


def locks_text(n_locks: int, n_edited: int, names: Iterable[str] = ()) -> str:
    names = list(names)
    if n_locks <= 0:
        return "Select a lock"
    if n_locks == 1 and names:
        return names[0] + (", edited" if n_edited else "")
    return f"{n_locks}" + (f", {n_edited} edited" if n_edited else "")


def hud_template(tool: str) -> dict:
    """The HUD's rows of a tool (set on entering and when the tool changes; `hud_values` fills them)."""
    if tool == TOOL_DRAW:
        return {"title": "MONO Grooming", "desc": "Draw lock", "icon": "SOP_curve", "rows": [
            {"id": "draw", "label": "Draw", "key": "LMB from the skin"},
            {"id": "width", "label": "Width", "key": "mousewheel", "value": ""},
            {"id": "thickness", "label": "Thickness", "value": ""},
            {"id": "taper", "label": "Tip taper", "value": ""},
            {"type": "divider"},
            {"id": "last", "label": "Last", "value": ""},
            {"id": "esc", "label": "Done", "key": "esc"},
        ]}
    return {"title": "MONO Grooming", "desc": "Edit points", "icon": "SOP_edit", "rows": [
        {"id": "locks", "label": "Locks", "value": ""},
        {"id": "drag", "label": "Drag", "key": "LMB", "value": ""},
        {"id": "rotate", "label": "Rotate about root", "key": "R + LMB"},
        {"id": "scale", "label": "Scale about root", "key": "E + LMB"},
        {"id": "redraw", "label": "Redraw", "key": "Shift + LMB"},
        {"id": "handles", "label": "Handles", "key": "- / +", "value": ""},
        {"type": "divider"},
        {"id": "pick", "label": "Select lock (Shift / Ctrl adds)", "key": "click hair"},
        {"id": "esc", "label": "Done", "key": "esc"},
    ]}


def cm_text(x: float) -> str:
    return f"{float(x):g} cm"


def hud_values(rec: ToolRecord, locks: dict | None = None) -> dict:
    """The HUD's values for the record and the locks shown ({id: {"name", "edited", "count", "count_set"}})."""
    if rec.tool == TOOL_DRAW:
        return {"width": cm_text(round(rec.width_cm, 2)), "thickness": cm_text(round(rec.thick_cm, 2)),
                "taper": f"{rec.taper:g}", "last": rec.message[:60]}
    locks = locks or {}
    rows = [locks[i] for i in rec.lock_ids if i in locks]
    mode = drag_mode(rec.mode, rec.held)
    return {"locks": locks_text(len(rows), sum(1 for r in rows if r.get("edited")), [r.get("name", "") for r in rows]),
            "drag": MODE_LABELS[mode] + (" (held)" if rec.held else ""),
            "handles": handles_text([r.get("count", 0) for r in rows], [r.get("count_set") for r in rows])}


def bar_values(rec: ToolRecord, locks: dict | None = None) -> dict:
    """The state bar's parm values for the record (Handles: the shared own count, else 0 = auto)."""
    locks = locks or {}
    sets = {locks[i].get("count_set") for i in rec.lock_ids if i in locks}
    handles = next(iter(sets)) if len(sets) == 1 and None not in sets else HANDLES_AUTO
    return {"drag_mode": MODES.index(rec.mode), "handles": int(handles or HANDLES_AUTO),
            "width": float(rec.width_cm), "thickness": float(rec.thick_cm), "taper": float(rec.taper)}


def bar_visible(tool: str) -> dict:
    """Which bar parms show for a tool."""
    return {parm: (shown_for == tool) for _f, parm, _l, shown_for in BAR}


def field_change(parm: str, value, rec: ToolRecord) -> dict:
    """What a bar parm the artist changed asks: {"mode": ...} / {"handles": count or None} / {"width_cm": ...}...;
    {} when it is the value the record has (the bar written from the record must not set it again)."""
    if parm == "drag_mode":
        try:
            i = int(round(float(value)))
        except (TypeError, ValueError):
            i = MODES.index(value) if value in MODES else -1
        if not 0 <= i < len(MODES) or MODES[i] == rec.mode:
            return {}
        return {"mode": MODES[i]}
    if parm == "handles":
        return {"handles": bar_handles(value)}
    field = {"width": "width_cm", "thickness": "thick_cm", "taper": "taper"}.get(parm)
    if field is None:
        return {}
    new = normal_fields({field: value}, rec)[field]
    return {} if math.isclose(new, getattr(rec, field), abs_tol=1e-6) else {field: new}


def status_text(rec: ToolRecord, n_locks: int) -> str:
    """The status bar line while a tool is on."""
    if rec.tool == TOOL_POINTS:
        if n_locks == 0:
            return "MONO Grooming: Edit points. Select a lock (click its hair, or a row in the panel)"
        return ("MONO Grooming: Edit points. Drag a handle; R / E + drag rotate / scale about the root, "
                "Shift + drag redraws; - / + handles; Esc ends")
    if rec.tool == TOOL_DRAW:
        return "MONO Grooming: Draw lock. Drag from the skin; the wheel sets the width; Esc ends"
    return ""


__all__ = ["TOOL_SELECT", "TOOL_POINTS", "TOOL_DRAW", "TOOL_PAINT", "TOOLS", "MODES", "MODE_LABELS", "STATE",
           "HOOKS", "ToolRecord", "update", "reset", "drag_mode", "handle_step", "next_count", "bar_handles",
           "scale_factor", "wheel_width", "signed_angle", "is_drag", "map_handle", "click_selection", "nearest",
           "handles_text", "locks_text", "hud_template", "hud_values", "bar_values", "bar_visible", "field_change",
           "status_text", "BAR", "PICK_PX", "HAIR_PICK_PX", "DRAG_PX", "KEY_ROTATE", "KEY_SCALE", "HELD_KEYS"]
