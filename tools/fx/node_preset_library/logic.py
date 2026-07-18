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


# Soft tags that stay readable on graphite sidebar
CATEGORY_COLOR_PALETTE: tuple[str, ...] = (
    "#5ec4b6",  # teal (brand)
    "#6ea8fe",  # sky
    "#a78bfa",  # violet
    "#f0abfc",  # pink
    "#fb923c",  # orange
    "#fbbf24",  # amber
    "#34d399",  # emerald
    "#22d3ee",  # cyan
    "#f87171",  # red
    "#94a3b8",  # slate
)

_SPECIAL_CATEGORY_COLORS: dict[str, str] = {
    "__all__": "#9aa3b5",
    "__favorites__": "#fbbf24",
    "__recent__": "#6ea8fe",
    "uncategorized": "#8b93a7",
}


def normalize_category_color(value: Any, *, fallback: str = "#5ec4b6") -> str:
    """Return #RRGGBB or fallback."""
    raw = str(value or "").strip()
    if raw.startswith("#") and len(raw) == 7:
        try:
            int(raw[1:], 16)
            return raw.lower()
        except ValueError:
            pass
    if raw.startswith("#") and len(raw) == 4:
        try:
            r, g, b = raw[1], raw[2], raw[3]
            int(r + g + b, 16)
            return f"#{r}{r}{g}{g}{b}{b}".lower()
        except ValueError:
            pass
    return fallback.lower()


def color_for_category_id(category_id: str) -> str:
    """Stable color for a category id (migration / specials)."""
    cid = (category_id or "").strip() or "uncategorized"
    if cid in _SPECIAL_CATEGORY_COLORS:
        return _SPECIAL_CATEGORY_COLORS[cid]
    # Deterministic pick from palette
    h = 0
    for ch in cid:
        h = (h * 31 + ord(ch)) & 0xFFFFFFFF
    return CATEGORY_COLOR_PALETTE[h % len(CATEGORY_COLOR_PALETTE)]


def random_category_color(*, avoid: Optional[set[str]] = None) -> str:
    """Pick a palette color, preferring ones not already used."""
    import random

    used = {normalize_category_color(c) for c in (avoid or set())}
    choices = [c for c in CATEGORY_COLOR_PALETTE if c not in used]
    if not choices:
        choices = list(CATEGORY_COLOR_PALETTE)
    return random.choice(choices)


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
    for c in data["categories"]:
        cid = c.get("id") or "uncategorized"
        c["color"] = normalize_category_color(
            c.get("color"),
            fallback=color_for_category_id(str(cid)),
        )
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


def add_category(
    name: str,
    library_root: Optional[Path] = None,
    *,
    color: Optional[str] = None,
) -> Optional[dict[str, Any]]:
    root = ensure_library_root(library_root)
    data = load_index(root)
    cid = _slug(name)
    if not cid:
        cid = "uncategorized"
    for c in data["categories"]:
        if c.get("id") == cid:
            # Ensure legacy categories gain a color when touched
            if not c.get("color"):
                c["color"] = normalize_category_color(
                    color,
                    fallback=color_for_category_id(cid),
                )
                save_index(data, root)
            return c
    order = max((c.get("order", 0) for c in data["categories"]), default=-1) + 1
    used = {normalize_category_color(c.get("color")) for c in data["categories"] if c.get("color")}
    if color:
        cat_color = normalize_category_color(color, fallback=color_for_category_id(cid))
    elif cid in _SPECIAL_CATEGORY_COLORS or cid == "uncategorized":
        cat_color = color_for_category_id(cid)
    else:
        cat_color = random_category_color(avoid=used)
    cat = {
        "id": cid,
        "name": name.strip() or cid,
        "order": order,
        "color": cat_color,
    }
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


def set_category_color(
    category_id: str,
    color: str,
    library_root: Optional[Path] = None,
) -> bool:
    root = library_root or config.get_library_root()
    data = load_index(root)
    for c in data["categories"]:
        if c.get("id") == category_id:
            c["color"] = normalize_category_color(
                color,
                fallback=color_for_category_id(category_id),
            )
            save_index(data, root)
            return True
    return False


def get_category(category_id: str, library_root: Optional[Path] = None) -> Optional[dict[str, Any]]:
    for c in list_categories(library_root):
        if c.get("id") == category_id:
            return c
    return None

def _reassign_preset_files(
    preset: dict[str, Any],
    new_category_id: str,
    root: Path,
) -> None:
    """Move preset .cpio / thumbnail into another category folder and update index paths."""
    import shutil

    pid = preset.get("id")
    if not pid:
        return
    new_cpio, new_thumb = preset_relative_paths(new_category_id, pid)
    for key, new_rel in (("file", new_cpio), ("thumbnail", new_thumb)):
        old_rel = preset.get(key)
        if key == "thumbnail" and not old_rel:
            continue
        dst = root / new_rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        if old_rel:
            src = root / old_rel
            if src.is_file():
                if src.resolve() != dst.resolve():
                    shutil.move(str(src), str(dst))
                preset[key] = new_rel
            elif key == "file":
                preset[key] = new_rel
        else:
            preset[key] = new_rel


def delete_category(category_id: str, library_root: Optional[Path] = None) -> bool:
    if not category_id or category_id == "uncategorized":
        return False
    root = library_root or config.get_library_root()
    data = load_index(root)
    if not any(c.get("id") == category_id for c in data["categories"]):
        return False

    add_category("Uncategorized", library_root=root)
    for p in data["presets"]:
        if p.get("category_id") == category_id:
            p["category_id"] = "uncategorized"
            _reassign_preset_files(p, "uncategorized", root)

    data["categories"] = [c for c in data["categories"] if c.get("id") != category_id]
    save_index(data, root)

    cat_dir = root / config.CATEGORIES_DIR / category_id
    if cat_dir.is_dir():
        try:
            for f in cat_dir.iterdir():
                f.unlink()
            cat_dir.rmdir()
        except OSError:
            pass
    return True


# --- Presets ---


def _preset_id() -> str:
    return uuid.uuid4().hex[:12]


def new_preset_id() -> str:
    return _preset_id()


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


def update_preset(
    preset_id: str,
    *,
    name: Optional[str] = None,
    category_id: Optional[str] = None,
    description: Optional[str] = None,
    thumbnail_relative: Any = ...,
    node_count: Optional[int] = None,
    networks: Any = ...,
    library_root: Optional[Path] = None,
) -> bool:
    """
    Update preset metadata. Pass thumbnail_relative=... (ellipsis) to leave unchanged;
    pass None to clear thumbnail path in index (caller may remove file).
    Pass networks=... to leave network tags unchanged.
    Moves .cpio/thumb when category_id changes.
    """
    root = library_root or config.get_library_root()
    data = load_index(root)
    preset = None
    for p in data["presets"]:
        if p.get("id") == preset_id:
            preset = p
            break
    if not preset:
        return False

    if name is not None:
        preset["name"] = name.strip()
    if description is not None:
        preset["description"] = description.strip()
    if thumbnail_relative is not ...:
        preset["thumbnail"] = thumbnail_relative
    if node_count is not None:
        preset["node_count"] = int(node_count)
    if networks is not ...:
        preset["networks"] = list(networks or [])

    if category_id is not None and category_id != preset.get("category_id"):
        # Ensure target category exists in index
        if not any(c.get("id") == category_id for c in data["categories"]):
            data["categories"].append(
                {
                    "id": category_id,
                    "name": category_id.replace("_", " ").title(),
                    "order": 999,
                    "color": color_for_category_id(category_id),
                }
            )
            (root / config.CATEGORIES_DIR / category_id).mkdir(parents=True, exist_ok=True)
        preset["category_id"] = category_id
        _reassign_preset_files(preset, category_id, root)

    save_index(data, root)
    return True


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
            c = dict(c)
            c["color"] = normalize_category_color(
                c.get("color"),
                fallback=color_for_category_id(str(cid)),
            )
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
            data["categories"].append(
                {
                    "id": cid,
                    "name": cid.replace("_", " ").title(),
                    "order": 999,
                    "color": color_for_category_id(str(cid)),
                }
            )
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


def export_library_to_zip(
    zip_path: Path | str,
    library_root: Optional[Path] = None,
) -> Path:
    """
    Zip the whole library folder (index.json + categories/).
    Returns the written zip Path.
    """
    import zipfile
    from datetime import datetime

    root = library_root or config.get_library_root()
    ensure_library_root(root)
    out = Path(zip_path)
    if out.is_dir():
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        out = out / f"node_preset_library_{stamp}.zip"
    out.parent.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        index_path = root / config.INDEX_FILENAME
        if index_path.is_file():
            zf.write(index_path, config.INDEX_FILENAME)
        cats = root / config.CATEGORIES_DIR
        if cats.is_dir():
            for fp in cats.rglob("*"):
                if fp.is_file():
                    zf.write(fp, fp.relative_to(root).as_posix())
    return out


def merge_library_from_zip(
    zip_path: Path | str,
    target_root: Optional[Path] = None,
) -> tuple[int, int]:
    """Extract zip to a temp dir then merge. Returns (categories_added, presets_added)."""
    import shutil
    import tempfile
    import zipfile

    zpath = Path(zip_path)
    if not zpath.is_file():
        raise FileNotFoundError(str(zpath))
    tmp = Path(tempfile.mkdtemp(prefix="npl_import_"))
    try:
        with zipfile.ZipFile(zpath, "r") as zf:
            zf.extractall(tmp)
        # Support zip that wraps a single top-level folder
        src = tmp
        index = tmp / config.INDEX_FILENAME
        if not index.is_file():
            for child in tmp.iterdir():
                if child.is_dir() and (child / config.INDEX_FILENAME).is_file():
                    src = child
                    break
        return merge_library_from_folder(src, target_root)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
