"""Names and patterns of Mono Anim Loader 2.2 (no hou)."""

from __future__ import annotations

ASSET_TYPES = ("char", "prop", "veh", "env", "set", "fx")

# A clone in a new publish: geo_char_Robot_inst02.usd (instance 2). Old publishes used _2.
CLONE_RE = r"_inst(\d{2,})$"
OLD_CLONE_RE = r"_(\d+)$"

ANIM_PREFIXES = {"geo_": "geo", "cam_": "cam"}
USD_EXTS = (".usd", ".usda", ".usdc")
