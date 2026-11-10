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
