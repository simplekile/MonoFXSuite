"""
Node Preset Library logic — index load/save, category and preset CRUD.
No Houdini (hou) imports.
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from tools.fx.node_preset_library import config


def _slug(s: str) -> str:
    """Lowercase, replace spaces with underscore, non-alnum to empty."""
    s = s.strip().lower()
    s = re.sub(r"[^a-z0-9]+", "_", s)
    return s.strip("_") or "uncategorized"


def load_index(library_root: Optional[Path] = None) -> dict[str, Any]:
    root = library_root or config.get_library_root()
    path = root / config.INDEX_FILENAME
    if not path.is_file():
        return {"version": config.INDEX_VERSION, "categories": [], "presets": []}
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    data.setdefault("version", config.INDEX_VERSION)
    data.setdefault("categories", [])
    data.setdefault("presets", [])
    # Backward-compat defaults for new fields
    for p in data["presets"]:
        p.setdefault("description", "")
        # networks: list of strings like ["SOP", "VOP"]
        nets = p.get("networks")
        if isinstance(nets, str):
            nets = [nets] if nets else []
        if not isinstance(nets, list):
            nets = []
        p["networks"] = nets
    return data


def save_index(data: dict[str, Any], library_root: Optional[Path] = None) -> None:
    root = library_root or config.get_library_root()
    root.mkdir(parents=True, exist_ok=True)
    path = root / config.INDEX_FILENAME
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def ensure_library_root(library_root: Optional[Path] = None) -> Path:
    root = library_root or config.get_library_root()
    root.mkdir(parents=True, exist_ok=True)
    (root / config.CATEGORIES_DIR).mkdir(exist_ok=True)
    return root


# --- Categories ---


def add_category(name: str, library_root: Optional[Path] = None) -> Optional[dict[str, Any]]:
    root = ensure_library_root(library_root)
    data = load_index(root)
    cid = _slug(name)
    if not cid:
        cid = "uncategorized"
    for c in data["categories"]:
        if c.get("id") == cid:
            return c
    order = max((c.get("order", 0) for c in data["categories"]), default=-1) + 1
    cat = {"id": cid, "name": name.strip() or cid, "order": order}
    data["categories"].append(cat)
    cat_dir = root / config.CATEGORIES_DIR / cid
    cat_dir.mkdir(parents=True, exist_ok=True)
    save_index(data, root)
    return cat


def list_categories(library_root: Optional[Path] = None) -> list[dict[str, Any]]:
    data = load_index(library_root)
    cats = data.get("categories", [])
    return sorted(cats, key=lambda c: (c.get("order", 0), c.get("id", "")))


def rename_category(category_id: str, new_name: str, library_root: Optional[Path] = None) -> bool:
    root = library_root or config.get_library_root()
    data = load_index(root)
    for c in data["categories"]:
        if c.get("id") == category_id:
            c["name"] = new_name.strip() or category_id
            save_index(data, root)
            return True
    return False


def delete_category(category_id: str, library_root: Optional[Path] = None) -> bool:
    root = library_root or config.get_library_root()
    data = load_index(root)
    data["categories"] = [c for c in data["categories"] if c.get("id") != category_id]
    for p in data["presets"]:
        if p.get("category_id") == category_id:
            p["category_id"] = "uncategorized"
    save_index(data, root)
    cat_dir = root / config.CATEGORIES_DIR / category_id
    if cat_dir.is_dir():
        for f in cat_dir.iterdir():
            f.unlink()
        cat_dir.rmdir()
    return True


# --- Presets ---


def _preset_id() -> str:
    return uuid.uuid4().hex[:12]


def add_preset(
    name: str,
    category_id: str,
    relative_hipnc_path: str,
    node_count: int,
    thumbnail_relative: Optional[str] = None,
    description: str | None = None,
    networks: Optional[list[str]] = None,
    preset_id: Optional[str] = None,
    library_root: Optional[Path] = None,
) -> dict[str, Any]:
    root = ensure_library_root(library_root)
    data = load_index(root)
    pid = preset_id or _preset_id()
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    preset = {
        "id": pid,
        "name": name.strip(),
        "category_id": category_id,
        "file": relative_hipnc_path,
        "thumbnail": thumbnail_relative,
        "created": now,
        "node_count": node_count,
        "description": (description or "").strip(),
        "networks": list(networks or []),
    }
    data["presets"].append(preset)
    save_index(data, root)
    return preset


def update_preset_thumbnail(
    preset_id: str,
    thumbnail_relative: Optional[str],
    library_root: Optional[Path] = None,
) -> bool:
    root = library_root or config.get_library_root()
    data = load_index(root)
    for p in data["presets"]:
        if p.get("id") == preset_id:
            p["thumbnail"] = thumbnail_relative
            save_index(data, root)
            return True
    return False


def list_presets(
    category_id: Optional[str] = None,
    library_root: Optional[Path] = None,
) -> list[dict[str, Any]]:
    data = load_index(library_root)
    presets = data.get("presets", [])
    if category_id is not None:
        presets = [p for p in presets if p.get("category_id") == category_id]
    return sorted(presets, key=lambda p: (p.get("created", ""), p.get("id", "")))


def get_preset(preset_id: str, library_root: Optional[Path] = None) -> Optional[dict[str, Any]]:
    data = load_index(library_root)
    for p in data["presets"]:
        if p.get("id") == preset_id:
            return p
    return None


def delete_preset(preset_id: str, library_root: Optional[Path] = None) -> bool:
    root = library_root or config.get_library_root()
    data = load_index(root)
    preset = None
    for p in data["presets"]:
        if p.get("id") == preset_id:
            preset = p
            break
    if not preset:
        return False
    data["presets"] = [p for p in data["presets"] if p.get("id") != preset_id]
    save_index(data, root)
    # Optionally remove files
    for key in ("file", "thumbnail"):
        rel = preset.get(key)
        if rel:
            fp = root / rel
            if fp.is_file():
                fp.unlink(missing_ok=True)
    return True


def resolve_path(library_root: Path, relative_path: str) -> Path:
    return (library_root / relative_path).resolve()


def category_id_from_name(name: str) -> str:
    return _slug(name)


def count_presets_by_category(library_root: Optional[Path] = None) -> dict[str, int]:
    """Return mapping category_id -> count of presets."""
    data = load_index(library_root)
    counts: dict[str, int] = {}
    for p in data.get("presets", []):
        cid = p.get("category_id") or "uncategorized"
        counts[cid] = counts.get(cid, 0) + 1
    return counts


def preset_relative_paths(category_id: str, preset_id: str) -> tuple[str, str]:
    """Return (relative_file_path, relative_thumbnail_path) for a preset."""
    return (
        f"categories/{category_id}/preset_{preset_id}{config.PRESET_FILE_EXT}",
        f"categories/{category_id}/preset_{preset_id}_thumb{config.THUMB_EXT}",
    )


def merge_library_from_folder(
    source_folder: Path,
    target_root: Optional[Path] = None,
) -> tuple[int, int]:
    """
    Merge another library folder into current library. Copy categories and presets;
    copy preset and thumbnail files. Returns (categories_added, presets_added).
    """
    import shutil

    target_root = target_root or config.get_library_root()
    ensure_library_root(target_root)
    data = load_index(target_root)
    existing_cat_ids = {c.get("id") for c in data["categories"]}
    existing_preset_ids = {p.get("id") for p in data["presets"]}
    source_index_path = source_folder / config.INDEX_FILENAME
    if not source_index_path.is_file():
        return (0, 0)
    with open(source_index_path, encoding="utf-8") as f:
        source_data = json.load(f)
    cats_added = 0
    for c in source_data.get("categories", []):
        cid = c.get("id")
        if cid and cid not in existing_cat_ids:
            data["categories"].append(c)
            existing_cat_ids.add(cid)
            cats_added += 1
            (target_root / config.CATEGORIES_DIR / cid).mkdir(parents=True, exist_ok=True)
    presets_added = 0
    for p in source_data.get("presets", []):
        pid = p.get("id")
        if not pid or pid in existing_preset_ids:
            continue
        cid = p.get("category_id", "uncategorized")
        (target_root / config.CATEGORIES_DIR / cid).mkdir(parents=True, exist_ok=True)
        if cid not in existing_cat_ids:
            data["categories"].append({"id": cid, "name": cid.replace("_", " ").title(), "order": 999})
            existing_cat_ids.add(cid)
        for key in ("file", "thumbnail"):
            rel = p.get(key)
            if not rel:
                continue
            src = source_folder / rel
            dst = target_root / rel
            if src.is_file():
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
        data["presets"].append(p)
        existing_preset_ids.add(pid)
        presets_added += 1
    save_index(data, target_root)
    return (cats_added, presets_added)
