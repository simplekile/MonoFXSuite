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
LOOP_ONLY_ATTRIBS = ("tightness", "clumpblend", "fit_s", "fit_t", "fit_u0", "fit_c0", "fit_root", "fit_blend", "root_at", "rx", "ry", "start_k", "start_cnt", "start_pos", "length_mult", "frizz",
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
