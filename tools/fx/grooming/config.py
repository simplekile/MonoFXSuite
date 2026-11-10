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
PREVIEW_FRACTION = 0.10
PREVIEW_MAX_STRANDS = 20_000

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
REGION_SUBDIV = 2              # bilinear subdivisions of the scalp before the split (x4 points each)

LOCK_NAME_DIGITS = 2           # fringe_01
