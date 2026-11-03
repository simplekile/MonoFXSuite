"""
User settings for drag & drop of files into Houdini (apps/houdini/drag_drop.py).
Pure pathlib/json (no Qt, no hou). Read on every drop, so a change applies to the next drop.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

PREFS_FILENAME = "drag_drop_prefs.json"

LAYER_ASK = "ask"
LAYER_REFERENCE = "reference"
LAYER_SUBLAYER = "sublayer"
LAYER_MODES = (LAYER_ASK, LAYER_REFERENCE, LAYER_SUBLAYER)

DEFAULTS: dict[str, Any] = {
    # Off: every drop goes to Houdini's own handling
    "enabled": True,
    # Geo / Alembic / USD dropped in LOP
    "lop_layer_mode": LAYER_ASK,
    # Textures or a texture folder dropped in LOP build Auto Material
    "lop_textures_material": True,
    # Images whose name Auto Material cannot read make a material each, image as base colour
    "other_images_base_color": True,
    # name.0001.ext, name.0002.ext... -> one node with $F4
    "collapse_sequences": True,
}


def prefs_file_path() -> Path:
    """Override with MONOFX_DRAG_DROP_PREFS for tests."""
    env = os.environ.get("MONOFX_DRAG_DROP_PREFS", "").strip()
    if env:
        return Path(env)
    return Path.home() / ".monofx" / PREFS_FILENAME


def normalize(raw: Any) -> dict[str, Any]:
    """Known keys only, wrong types or values replaced by the default."""
    data = raw if isinstance(raw, dict) else {}
    out = dict(DEFAULTS)
    for key in ("enabled", "lop_textures_material", "other_images_base_color", "collapse_sequences"):
        if isinstance(data.get(key), bool):
            out[key] = data[key]
    if data.get("lop_layer_mode") in LAYER_MODES:
        out["lop_layer_mode"] = data["lop_layer_mode"]
    return out


def load_prefs() -> dict[str, Any]:
    try:
        with open(prefs_file_path(), encoding="utf-8") as f:
            return normalize(json.load(f))
    except (OSError, ValueError):
        return dict(DEFAULTS)


def save_prefs(data: dict[str, Any]) -> None:
    path = prefs_file_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(normalize(data), f, indent=2)
