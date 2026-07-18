"""
User prefs for Node Preset Library — library path, recent roots, favorites, recent presets.
Pure pathlib/json (no Qt, no hou).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from tools.fx.node_preset_library import config

MAX_RECENT_LIBRARY_ROOTS = 5
MAX_RECENT_PRESETS = 12
PREFS_FILENAME = "node_preset_library_prefs.json"

# Grid card size as % of design base (196×216). Default ~70%.
DEFAULT_CARD_SCALE = 70
MIN_CARD_SCALE = 50
MAX_CARD_SCALE = 100

PRESET_MIME = "application/x-monofx-preset-id"


def prefs_file_path() -> Path:
    """Override with MONOFX_NODE_PRESET_PREFS for tests."""
    env = os.environ.get("MONOFX_NODE_PRESET_PREFS", "").strip()
    if env:
        return Path(env)
    return Path.home() / ".monofx" / PREFS_FILENAME


def default_library_root() -> Path:
    return config._suite_root() / "library" / "node_preset_library"


def clamp_card_scale(value: Any) -> int:
    try:
        n = int(round(float(value)))
    except (TypeError, ValueError):
        return DEFAULT_CARD_SCALE
    return max(MIN_CARD_SCALE, min(MAX_CARD_SCALE, n))


def _empty_prefs() -> dict[str, Any]:
    return {
        "library_root": "",
        "recent_roots": [],
        "pinned_roots": [],
        "favorite_ids": [],
        "recent_preset_ids": [],
        "card_scale": DEFAULT_CARD_SCALE,
    }


def load_prefs() -> dict[str, Any]:
    path = prefs_file_path()
    if not path.is_file():
        return _empty_prefs()
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return _empty_prefs()
    if not isinstance(data, dict):
        return _empty_prefs()
    base = _empty_prefs()
    base.update({k: data.get(k, base[k]) for k in base})
    if not isinstance(base["recent_roots"], list):
        base["recent_roots"] = []
    if not isinstance(base["pinned_roots"], list):
        base["pinned_roots"] = []
    if not isinstance(base["favorite_ids"], list):
        base["favorite_ids"] = []
    if not isinstance(base["recent_preset_ids"], list):
        base["recent_preset_ids"] = []
    base["card_scale"] = clamp_card_scale(base.get("card_scale"))
    return base


def save_prefs(data: dict[str, Any]) -> None:
    path = prefs_file_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "library_root": str(data.get("library_root") or ""),
        "recent_roots": [str(p) for p in (data.get("recent_roots") or [])],
        "pinned_roots": [str(p) for p in (data.get("pinned_roots") or [])],
        "favorite_ids": [str(x) for x in (data.get("favorite_ids") or [])],
        "recent_preset_ids": [str(x) for x in (data.get("recent_preset_ids") or [])][:MAX_RECENT_PRESETS],
        "card_scale": clamp_card_scale(data.get("card_scale", DEFAULT_CARD_SCALE)),
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)


def get_card_scale() -> int:
    return clamp_card_scale(load_prefs().get("card_scale", DEFAULT_CARD_SCALE))


def set_card_scale(scale: int) -> int:
    data = load_prefs()
    data["card_scale"] = clamp_card_scale(scale)
    save_prefs(data)
    return int(data["card_scale"])


def _normalize(path: Path | str) -> Path:
    return Path(path).expanduser().resolve()


def _path_key(path: Path | str) -> str:
    try:
        return str(_normalize(path)).lower()
    except OSError:
        return str(Path(path)).lower()


def _pinned_key_set(data: dict[str, Any]) -> set[str]:
    keys: set[str] = set()
    for raw in data.get("pinned_roots") or []:
        keys.add(_path_key(raw))
    return keys


def _trim_recent_preserving_pins(recent: list[str], pinned: set[str], *, max_n: int = MAX_RECENT_LIBRARY_ROOTS) -> list[str]:
    """Keep MRU order; drop oldest unpinned until len <= max_n. Never drop pinned."""
    out = list(recent)
    while len(out) > max_n:
        dropped = False
        for i in range(len(out) - 1, -1, -1):
            if _path_key(out[i]) not in pinned:
                out.pop(i)
                dropped = True
                break
        if not dropped:
            break
    return out


def list_pinned_library_roots(*, existing_only: bool = True) -> list[Path]:
    data = load_prefs()
    out: list[Path] = []
    seen: set[str] = set()
    for raw in data.get("pinned_roots") or []:
        try:
            p = _normalize(raw)
        except OSError:
            continue
        key = str(p).lower()
        if key in seen:
            continue
        if existing_only and not p.is_dir():
            continue
        seen.add(key)
        out.append(p)
    return out


def is_pinned_library_root(path: Path | str) -> bool:
    return _path_key(path) in _pinned_key_set(load_prefs())


def toggle_pin_library_root(path: Path | str) -> bool:
    """Pin/unpin a recent root. Returns True if now pinned."""
    try:
        target = _normalize(path)
        target_key = str(target).lower()
        target_str = str(target)
    except OSError:
        target_key = str(Path(path)).lower()
        target_str = str(path)

    data = load_prefs()
    pinned_raw = [str(x) for x in data.get("pinned_roots") or []]
    pinned_keys = {_path_key(x) for x in pinned_raw}
    if target_key in pinned_keys:
        data["pinned_roots"] = [x for x in pinned_raw if _path_key(x) != target_key]
        now = False
    else:
        # Ensure path is on recent list when pinning
        recent = [str(x) for x in data.get("recent_roots") or []]
        if target_key not in {_path_key(x) for x in recent}:
            recent.insert(0, target_str)
        data["recent_roots"] = recent
        data["pinned_roots"] = [target_str] + [x for x in pinned_raw if _path_key(x) != target_key]
        now = True
        # Re-trim unpinned only
        data["recent_roots"] = _trim_recent_preserving_pins(
            data["recent_roots"],
            _pinned_key_set(data),
        )
    save_prefs(data)
    return now


def list_recent_library_roots(*, existing_only: bool = True) -> list[Path]:
    """Return recent roots (most recent first). Drops missing dirs when existing_only."""
    data = load_prefs()
    out: list[Path] = []
    seen: set[str] = set()
    for raw in data.get("recent_roots") or []:
        try:
            p = _normalize(raw)
        except OSError:
            continue
        key = str(p).lower()
        if key in seen:
            continue
        if existing_only and not p.is_dir():
            continue
        seen.add(key)
        out.append(p)
    return out


def prune_recent_prefs() -> list[Path]:
    """Drop non-existent recent/pinned entries from disk prefs; return remaining recent."""
    data = load_prefs()
    kept: list[str] = []
    seen: set[str] = set()
    for raw in data.get("recent_roots") or []:
        try:
            p = _normalize(raw)
        except OSError:
            continue
        if not p.is_dir():
            continue
        key = str(p).lower()
        if key in seen:
            continue
        seen.add(key)
        kept.append(str(p))

    pinned_kept: list[str] = []
    pinned_seen: set[str] = set()
    for raw in data.get("pinned_roots") or []:
        try:
            p = _normalize(raw)
        except OSError:
            continue
        if not p.is_dir():
            continue
        key = str(p).lower()
        if key in pinned_seen:
            continue
        pinned_seen.add(key)
        pinned_kept.append(str(p))
        if key not in seen:
            kept.append(str(p))
            seen.add(key)

    data["pinned_roots"] = pinned_kept
    data["recent_roots"] = _trim_recent_preserving_pins(kept, {_path_key(x) for x in pinned_kept})
    current = (data.get("library_root") or "").strip()
    if current:
        try:
            cur = _normalize(current)
            if not cur.is_dir():
                data["library_root"] = ""
        except OSError:
            data["library_root"] = ""
    save_prefs(data)
    return [Path(p) for p in data["recent_roots"]]


def remember_library_root(path: Path | str) -> Path:
    """
    Set active library root and push onto recent list (max 5, MRU order).
    Pinned roots are never evicted when the list is trimmed.
    Creates the directory if needed.
    """
    root = _normalize(path)
    root.mkdir(parents=True, exist_ok=True)
    data = load_prefs()
    key = str(root).lower()
    recent = []
    for raw in data.get("recent_roots") or []:
        try:
            p = _normalize(raw)
        except OSError:
            continue
        if not p.is_dir():
            continue
        if str(p).lower() == key:
            continue
        recent.append(str(p))
    recent.insert(0, str(root))
    pinned = _pinned_key_set(data)
    data["library_root"] = str(root)
    data["recent_roots"] = _trim_recent_preserving_pins(recent, pinned)
    save_prefs(data)
    return root


def remove_recent_library_root(path: Path | str) -> None:
    """Remove a path from recent + pinned lists. Does not delete the folder on disk."""
    target = _path_key(path)
    data = load_prefs()
    kept = []
    for raw in data.get("recent_roots") or []:
        try:
            p = _normalize(raw)
            if str(p).lower() == target:
                continue
            kept.append(str(p))
        except OSError:
            if str(raw).lower() == target:
                continue
            kept.append(str(raw))
    data["recent_roots"] = kept
    data["pinned_roots"] = [
        x for x in (data.get("pinned_roots") or []) if _path_key(x) != target
    ]
    current = (data.get("library_root") or "").strip()
    if current:
        try:
            if str(_normalize(current)).lower() == target:
                data["library_root"] = ""
        except OSError:
            if current.lower() == target:
                data["library_root"] = ""
    save_prefs(data)


def resolve_library_root() -> Path:
    """
    Active library root priority:
    1. Env MONOFX_NODE_PRESET_LIBRARY (CI / explicit override)
    2. Prefs library_root
    3. Suite default
    """
    env = os.environ.get("MONOFX_NODE_PRESET_LIBRARY", "").strip()
    if env:
        return Path(env).expanduser()

    data = load_prefs()
    preferred = (data.get("library_root") or "").strip()
    if preferred:
        try:
            return _normalize(preferred)
        except OSError:
            return Path(preferred).expanduser()

    return default_library_root()


# --- Favorites & recent presets ---


def list_favorite_ids() -> list[str]:
    return [str(x) for x in load_prefs().get("favorite_ids") or []]


def is_favorite(preset_id: str) -> bool:
    return str(preset_id) in set(list_favorite_ids())


def toggle_favorite(preset_id: str) -> bool:
    """Add/remove favorite. Returns True if now favorited."""
    data = load_prefs()
    pid = str(preset_id)
    favs = [str(x) for x in data.get("favorite_ids") or []]
    if pid in favs:
        favs = [x for x in favs if x != pid]
        now = False
    else:
        favs.insert(0, pid)
        now = True
    data["favorite_ids"] = favs
    save_prefs(data)
    return now


def list_recent_preset_ids() -> list[str]:
    return [str(x) for x in load_prefs().get("recent_preset_ids") or []][:MAX_RECENT_PRESETS]


def remember_recent_preset(preset_id: str) -> None:
    data = load_prefs()
    pid = str(preset_id)
    recent = [str(x) for x in data.get("recent_preset_ids") or [] if str(x) != pid]
    recent.insert(0, pid)
    data["recent_preset_ids"] = recent[:MAX_RECENT_PRESETS]
    save_prefs(data)
