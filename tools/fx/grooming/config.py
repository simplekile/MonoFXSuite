"""
Constants of MONO Grooming: attribute names, node names, limits. No `hou`. Spec: docs/plans/grooming_v0_1.md
"""

from __future__ import annotations

HDA_TYPE = "mono::grooming::0.1"
HDA_LABEL = "MONO Grooming"
DATA_PARM = "groom_data"            # hidden multi-line string parm holding GroomData JSON
WINDOW_TITLE = "MONO Grooming"

# Geometry attributes (the contract between the HDA network and the tool).
ATTR_LOCK_ID = "lock_id"
ATTR_NAME = "name"
ATTR_GROUP = "group"
ATTR_CURVEU = "curveu"
ATTR_LOCK_WIDTH = "lock_width"       # lock cross-section width; Houdini's `width` stays strand thickness
ATTR_LOCK_THICK = "lock_thick"
ATTR_LOCK_TWIST = "lock_twist"
ATTR_LOCK_OWNER = "lock_owner"       # on scalp points: lock id growing hair there, -1 none
ATTR_DENSITY = "density"
ATTR_CLUMP_ID = "clump_id"

NO_OWNER = -1

DISPLAY_MODES: tuple[str, ...] = ("mesh", "guide", "hair_preview", "hair")
COLOR_BY: tuple[str, ...] = ("lock", "group")
PLAY_DISPLAY: tuple[str, ...] = ("same", "guide", "hair_preview")  # index = the DISPLAY_MODES index it caps at
PREVIEW_FRACTION = 0.10
PREVIEW_MAX_STRANDS = 20_000
PREVIEW_FACTOR_STEP = 0.8      # a capped preview factor snaps down to 0.8^k (it is in every lock's cache key)
# A strand gathers from its root on the region into its lock's shape over this many times the root's
# distance from the mesh root (build_hda fit_root; at least root_blend of the lock, at most half)
ROOT_CONVERGE = 3.0
ROOT_CONVERGE_START = 1.0   # the strands that start a lock gather into it quicker
# Skin with its lock's mesh over ROOT_FAR_CM above it roots its strands round the lock's root (build_hda
# region_join / root_pick), fading over +-ROOT_FAR_SOFT of it: the strands crossing that gap were Helen's spike /
# fuzz / fin. Taken from the hand groom v006, its density over what the regions ask against the mesh's height
# over the skin: <0.3 cm 1.7, 0.3-0.5 0.50, 0.5-0.7 0.35, 0.7-0.9 0.11, over 1.1 cm ~0 (t52)
ROOT_FAR_CM = 0.5
ROOT_FAR_SOFT = 0.5
# A lock whose mesh root edge lies over ROOT_GAP_CM off the skin floats at its root (a mesh fault: hair does
# not grow out of the air): Detect lists it, and Root to skin (setting root_skin, cm) bends its spine's start
# down to the skin
ROOT_GAP_CM = 0.3
# a lock's start extras lie on a disc round its root, wide enough to stay under this x the lock's density
START_DENSITY_MAX = 6.0
# A scalp's size across (cm) that Detect accepts without a units warning
SCALP_SIZE_CM = (8.0, 60.0)
# Prim attributes only the per-lock loop needs (hairgen, fit_to_lock, hairclump): dropped before the cache
LOOP_ONLY_ATTRIBS = ("tightness", "clumpblend", "fit_s", "fit_t", "fit_u0", "fit_c0", "fit_root", "fit_blend", "root_at", "rx", "ry", "start_k", "start_cnt", "start_pos", "thin_u", "mask_root", "length_mult", "frizz",
                     "clumpid", "skinprim", "skinprimuv")
# The HDA's output 1 "Groom" (and the publish) carry only these besides P, in whatever class the cache has
# them (docs/plans/grooming_v0_1.md, Geometry contract); output 0 "Display" is what the viewport draws
GROOM_ATTRIBS = ("width", "lock_id", "name", "group", "clump_id", "id")
OUTPUT_LABELS = ("Display", "Groom")
# A slider drag grows the dragged locks at their real strand count, with fewer points a strand (a drag
# tick on one Helen lock: 0.14 s, its largest 0.36 s); past this many strands (a group) a fraction of
# them, snapped to PREVIEW_FACTOR_STEP, and the panel says which fraction
DRAG_STRAND_BUDGET = 10_000
DRAG_SEGMENTS = 12
# Focus (the panel's selection): the selected locks keep their colour, the others are drawn see-through
GHOST_ALPHA = 0.15            # per strand: a lock is thousands of strands deep, so it adds up; 0.04-0.12
                              # read as too faint to place a lock against its neighbours (the user, t40)
# X-ray strength the artist picks in the view bar (alpha per strand of the locks out of focus)
XRAY_LEVELS: dict[str, float] = {"Light": 0.08, "Medium": 0.15, "Strong": 0.25, "Solid": 0.4}
XRAY_DEFAULT = "Medium"
GHOST_TINT = (0.30, 0.31, 0.35)
GHOST_MIX = 0.5               # how far the others' colour goes to GHOST_TINT
CLUMP_ID_STRIDE = 100_000      # clump_id = lock_id x this + hairclump's clump: clumped per lock, unique per groom

# Publish layout (department name "grooming").
DEPARTMENT_DIR = "04_grooming"
PUBLISH_FILE_TEMPLATE = "{asset}_grooming_publish.usd"   # asset = "char_Helen"
TOOL_DATA_DIR = "_grooming"

# Re-import matching (logic.match_locks). Distances are fractions of the lock's length, so the rule is the
# same for a 2 cm fringe lock and a 40 cm back lock, in any scene unit.
MATCH_NAME_ROOT_TOL = 0.5      # same name, root moved <= 0.5 x length -> "ok"; farther -> "unsure"
MATCH_ROOT_TOL = 0.25          # no name match: root moved <= 0.25 x length ...
MATCH_ROOT_LENGTH_RATIO = 1.5  # ... and length within x1.5 either way -> "unsure"
MATCH_SHAPE_ROOT_TOL = 1.0     # shape only: root moved <= 1 x length ...
MATCH_SHAPE_LENGTH_RATIO = 1.1  # ... length within x1.1 ...
MATCH_SHAPE_MIN_DOT = 0.9      # ... and direction within ~25 degrees (when the lock knows its direction)

MATCH_UNCHANGED_TOL = 1e-5     # root and length within 1e-5 x length: the mesh did not change -> "ok"

# Region split (logic.region_owners): a lock's footprint radius = this x its measured root width.
REGION_FOOTPRINT = 0.5
# Past the footprints a scalp prim goes to the lock whose hair mesh lies nearest over it; locks whose
# meshes are within this (cm) of the nearest share it (layers lying on each other)
REGION_MESH_SHARE_CM = 0.1
# Rule the stored split was made with (detail `region_rule` on the frozen regions): older splits are
# marked out of date when the scene loads. 2 = footprint, then the mesh lying over the scalp
REGION_RULE = 3     # 3: footprints on the skin, whorls recorded
# Whorl (logic.whorls): a lock whose root has WHORL_MIN_LOCKS - 1 other roots within WHORL_RADIUS_CM starts
# at a whorl; it gets extra roots inside WHORL_DISK_CM of the whorl's centre, enough for its start's
# cross-section at the set density (build_hda root_spread). The approved Helen v006: 17.5 % of its roots
# within 1 cm of its crown whorl, ~4,800 / cm2
WHORL_RADIUS_CM = 1.5
WHORL_MIN_LOCKS = 3
WHORL_DISK_CM = 0.7
# Start extras (build_hda region_frame): strands rooted round a lock's root on top of its count, as many as
# bring the hair in its first 3/10 to START_TARGET x the mesh's share there: v006's worst start share (t52, 0.47).
# With roots under floating mesh starting their lock, Helen needs none (worst 0.56 without any, t53)
START_TARGET = 0.47
WHORL_FILL = 0.3     # extra strands at a whorl, x the lock's start cross-section
REGION_SUBDIV = 2              # bilinear subdivisions of the scalp before the split (x4 points each)
SECTION_MIN_THICK_RATIO = 0.3  # cross-section floor of a lock: thickness counted as >= 30 % of its width

LOCK_NAME_DIGITS = 2           # fringe_01

# ---- v0.2a density layers (docs/plans/grooming_v0_2.md) ----
# The model (the user, final, 2026-11-15: "the automatic density is a density layer of its own; the user makes
# a new density layer with another number and a mask, to override the density"). It replaces the one 0..1 mask
# x the lock's own Density of 2026-11-14, where a layer could never be denser than the automatic groom and
# black meant "no hair".
#   A DENSITY LAYER has its own number D (strands / cm2, absolute), an opacity, an eye, an owner (all locks, a
#   group, a lock) and a MASK: a stack of paint and fill layers, values 0..1, blended bottom to top as the layer
#   stack of a mask in Substance Painter, starting from black. At a skin point, layer over what lies below:
#       density = below + (D - below) x mask x opacity
#   Black in a mask = the layer does not apply there (the density below shows); no hair = a layer with D = 0
#   painted white. The bottom of the stack is the BASE layer, the automatic groom (D = each lock's own Density
#   setting, mask full): never deleted, never moved; with no other layer the groom is v0.1's.
#   Density layers stack as Normal only, in this order: all locks, then the lock's group, then the lock; inside
#   one owner the upper layer wins.
# Blend modes of a MASK layer (logic.mask_stack): m = below + (blend(below, value) - below) x coverage x opacity
MASK_MODES: tuple[str, ...] = ("normal", "multiply", "add", "subtract", "min", "max")
MASK_SCOPES: tuple[str, ...] = ("all", "group", "locks")   # a density layer's owner: every lock, a group, a lock
#   "base"    the automatic groom, always first in the list (id MASK_BASE_ID); holds no mask layer
#   "density" a density layer: `density` (D), opacity, owner; its mask layers name it as their `parent`
#   "paint"   a mask layer: the brush paints a value and a coverage per skin point; unpainted skin is transparent
#   "fill"    a mask layer: one value over all the skin, full coverage
MASK_KINDS: tuple[str, ...] = ("base", "density", "paint", "fill")
MASK_BASE_ID = -1
MASK_DENSITY_MAX = 20000.0     # a layer's density is kept inside 0..this (Helen's crown: 7,000 / cm2)
MASK_DENSITY_DEFAULT = 150.0   # a new density layer's number
MASK_DENSITY_PICKS: tuple[float, ...] = (0.0, 75.0, 150.0, 300.0)   # the panel's quick picks for a layer's density
MASK_VALUE_PICKS: tuple[float, ...] = (0.0, 0.5, 1.0)     # ... and for the grey the brush paints into a mask
MASK_PARM = "mask_layers"      # hidden geometry parm: per fine-scalp point P, uv, mask_<id>_v, mask_<id>_a
MASK_VALUE_ATTR = "mask_%d_v"  # a paint layer's value per scalp point, 0..1
MASK_COVER_ATTR = "mask_%d_a"  # ... and its coverage there: 0 not painted, 1 painted, a dab's soft edge between
# on SCALP_REGIONS, per scope set (logic.mask_scope_sets): density of a lock = automatic x keep + add.
# `keep` (point): how much of the automatic groom stays; `add` (VERTEX: a prim's corner): the density the layers
# ask of one lock of the set there, strands / cm2, already divided among the locks a layer's D is shared by
MASK_KEEP_ATTR = "mask_keep_%d"
MASK_ADD_ATTR = "mask_add_%d"
BRUSH_RADIUS_CM = 1.0
BRUSH_SOFT = 0.5               # share of the radius over which a dab fades out
BRUSH_VALUE = 1.0              # what the brush paints into a mask: 1 white (the layer applies), 0 black
# A dab reaches only skin connected to the point under the cursor and facing its way: the angle between a
# point's normal and the hit's stays under this (the skin behind an ear is not painted through it)
BRUSH_FACING_DEG = 75.0
# What the scalp shows while painting (set_brush(view=...)); decided with the user, 2026-11-13 (Substance
# Painter's way: the final result, or one mask alone by Alt+click on it):
#   "density" the result: roots / cm2 as the groom has them (counted from the cooked hair, so relocated
#             roots are in it); while a stroke is down, what the layers ask of that count (automatic x keep +
#             the layers' density); before any hair is known, the density asked
#   "layer"   the painted layer alone: its value (white 1, black 0) where it has coverage, dark elsewhere
#   "roots"   a dot at every root of the full groom on a plain scalp
MASK_VIEWS: tuple[str, ...] = ("density", "layer", "roots")
ROOT_DENSITY_CELL_CM = 0.5     # roots and skin are counted in boxes of 3 cells of this size across
PAINT_STATE = "mono_grooming_mask_paint"   # the Python viewer state (apps/houdini/grooming_paint_state.py)
UNDO_CACHE_PARM = "undo_cache_gb"   # how much hair the per-lock cache may hold (GB): what undo finds without a recook
UNDO_CACHE_GB = 2.0
# the display's deformed states (Shot deform on): one a stroke, each the WHOLE deformed groom, held apart from the
# limit above with a limit of their own (the user, 2026-11-15, t66 B6). The default and what it holds on Helen:
# tools/fx/grooming/CLAUDE.md, "t67"
UNDO_DEFORM_PARM = "undo_deform_gb"
UNDO_DEFORM_GB = 4.0

# ---- v0.2b lock redraw and control points (docs/plans/grooming_v0_2.md "v0.2b"; logic.py "Control points") ----
# Field names in `groom_data` (model.Lock / model.Orphan, schema 7) are the contract for the network (B2), the
# viewer state (B3) and the panel (B4): `spine` (K control points in the root frame, [] = the measured spine),
# `handles` (the artist's count, None = by length), and for a drawn lock `source` SOURCE_DRAWN, `curve`,
# `width_cm`, `thick_cm`, `taper`.
SOURCE_MESH = "mesh"           # a lock detected from a hair mesh piece
SOURCE_DRAWN = "drawn"         # a lock drawn on the skin (no mesh; Detect leaves it alone)
LOCK_SOURCES: tuple[str, ...] = (SOURCE_MESH, SOURCE_DRAWN)
# How many handles a lock shows (the user, U1, 2026-11-20): one every HANDLE_SPACING_CM of its length, at least
# HANDLES_MIN, at most HANDLES_MAX (Helen: fringe 4-5, the 89.6 cm back locks 12); a per-lock number (`handles`)
# overrides it, in the same range
HANDLE_SPACING_CM = 8.0
HANDLES_MIN = 4
HANDLES_MAX = 12
# A redrawn or drawn curve keeps as few control points as hold it within this of the stroke (spike t76 Q4:
# 4 to 15 a lock on curves like Helen's), at most HANDLES_MAX (the manager, 2026-11-21: 12 everywhere); a stroke
# 12 cannot hold is still taken, and the gap it leaves goes into the message
STROKE_TOL_CM = 0.25
# Changing the handle count of an edited lock re-fits its moves (logic.resample_spine); the edited spine is
# expected to stay within this. Fewer handles than the edit was made with may not hold it (a local bend needs
# handles close together): the function returns the distance so the caller can say so
RESAMPLE_TOL_CM = 0.25
# A stored root at the root frame's origin (within this, scene units) was never moved: it stays the measured root
# (the spike's VEX rule); a moved root goes onto the skin (U5)
ROOT_MOVED_EPS = 1e-7
# Handles within this (scene units) of where they are now change nothing: the network's spine_edit leaves a spine
# whose every handle lies this close to the measured one untouched (the per-lock loop is chaotic in the last bit:
# 1e-7 in P moved hair 0.04 cm), and the adapter writes nothing for a result this close to what is stored or
# measured (t84 minor 1: no undo step, "nothing changed"). 1e-4 cm in Helen's metres
SPINE_STILL = 1e-6
# A handle given within this of where the root is now (cm): the root did not move (it stays the measured one)
ROOT_SAME_CM = 1e-4
# A drawn lock's root goes onto the skin, the move fading out over this share of its length (the spike's drawn lock)
DRAWN_ROOT_FADE = 0.25
# A drawn lock (U3: it gets its footprint, REGION_FOOTPRINT x its width round its root, in the same undo step)
DRAWN_WIDTH_CM = 2.0           # the panel's first values for a new drawn lock (spike t76 Q5's test lock)
DRAWN_THICK_CM = 0.6
DRAWN_TAPER_DEFAULT = 0.3      # share of the width and thickness left at the tip
# Limits of what an edit may ask for (t84 B-2: a scale of 1e9 crashed the cook, a width of 1e6 cm or a stroke
# 1e6 cm off the skin ran for minutes). Past them the adapter raises ValueError naming the limit and writes nothing.
# Chosen from what an artist can mean, with room (Helen: locks 12.6-89.6 cm, a drawn lock 2 x 0.6 cm):
# - LOCK_REACH_MAX_CM: every handle (and stroke point) within this of the lock's root. Floor-length hair on a 2 m
#   character is under 2 m; 3 m leaves room for a lock laid out and back. Cost measured on Helen (t79 limits.out).
# - STROKE_SKIN_MAX_CM: a stroke (draw, redraw) starts this close to the skin: the viewer state starts it on the
#   skin; a few cm allows a start over the hair. Its root goes onto the skin, so further off the lock gets a jump
#   (t84 minor 4: an 80 cm one was taken).
# - SCALE_RANGE: one Scale is one drag; 0.1 x to 10 x (a 12.6 cm fringe lock to 126 cm), the result still within
#   the reach.
# - DRAWN_WIDTH_RANGE_CM / DRAWN_THICK_RANGE_CM: a drawn lock from a few strands to 10 cm wide. Its footprint is
#   REGION_FOOTPRINT x the width round its root: on Helen 10 cm took skin from 5 locks, 20 cm from 42 of 61 (half
#   the head) and 40 cm from all of them, which no artist means by one lock (t79 limits.out).
# - STROKE_POINTS_MAX: a stroke (draw, redraw) of more points is thinned to this many of its own points, evenly by
#   index, before the fit (`grooming_adapter.thin_stroke`). The fit (`logic.stroke_handles`) measured on a 40 cm
#   stroke with 0.05 cm of hand noise: 200 points 0.08 s, 1,000 0.10 s, 2,000 0.27 s, 4,000 0.39 s, 8,000 0.78 s,
#   16,000 5.6 s (t84 recheck: 400,000 took 159 s). A mouse or pen stroke is a few hundred points; 2,000 keeps a
#   point every 0.02 cm on a 40 cm lock, far under STROKE_TOL_CM, and the fit under 0.3 s.
# - STROKE_TOL_RANGE_CM: the tolerance a fit may be given (t84 recheck: 0, negative, NaN and inf were taken). Below
#   0.01 cm every stroke takes HANDLES_MAX (a hand's noise is larger), past 10 cm every one HANDLES_MIN.
LOCK_REACH_MAX_CM = 300.0
STROKE_SKIN_MAX_CM = 5.0
STROKE_POINTS_MAX = 2000
STROKE_TOL_RANGE_CM = (0.01, 10.0)
SCALE_RANGE = (0.1, 10.0)
DRAWN_WIDTH_RANGE_CM = (0.05, 10.0)
DRAWN_THICK_RANGE_CM = (0.02, 5.0)
# prim attributes the network writes on a spine (B2): the stored control points as a flat float array (in each
# lock's cache key like any prim attribute), and 1 on a lock whose spine the edit moved
ATTR_EDIT_CP = "edit_cp"
ATTR_EDITED = "edited"
POINTS_STATE = "mono_grooming_control_points"   # the Python viewer state of the handles (B3)
# The shot deform (v0.2b, B-3 decided 2026-11-22: v0.1's Point Deform gave a strand point the motion of every rest
# mesh point within 2 cm, whatever lock it belongs to, and folded fringe locks whose piece does not fold). Each lock
# follows ITS OWN piece by place along it (`pu`): PIECE_SAMPLES places along the piece, each the centre and best
# rotation of the piece's points in a Gaussian window of PIECE_SIGMA_BINS samples by `pu` (t79 report 9.5: 48 / 1.5
# gave 0 folds on sh020 and sh025 at every graded frame). Near the skin a strand takes the translation of the rest
# mesh points within ROOT_ANCHOR_CM of its root (every piece: roots stay on the skin as v0.1's; own piece only left
# fringe roots up to 0.3 cm further off) with the piece's rotation there, blending into the place-along-the-piece
# deform over its first ROOT_BLEND of length (0.2 stretched strands rooted under a far part of their lock: 1.19 p95
# on hair_bang_20, 0.35 1.17, 0.5 1.15).
PIECE_SAMPLES = 48
PIECE_SIGMA_BINS = 1.5
ROOT_ANCHOR_CM = 1.5
ROOT_ANCHOR_POINTS = 48
ROOT_BLEND = 0.35
# Undo step names (one undo step each, docs/plans/grooming_v0_2.md "Done when")
UNDO_SPINE: dict[str, str] = {
    "move": "MONO Grooming: Move control points",
    "rotate": "MONO Grooming: Rotate lock",
    "scale": "MONO Grooming: Scale lock",
    "redraw": "MONO Grooming: Redraw lock",
    "reset": "MONO Grooming: Reset lock",
    "handles": "MONO Grooming: Set handle count",
    "draw": "MONO Grooming: Draw lock",
    "delete": "MONO Grooming: Delete drawn lock",
    "drawn": "MONO Grooming: Drawn lock settings",     # width, thickness, taper of drawn locks
}
# a drawn lock's curve through its handles is sampled this many times a segment (the spike's Q4 fit)
CURVE_SAMPLES = 40
