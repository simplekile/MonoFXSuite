"""Tests for node_preset_library.logic (no Houdini)."""

from __future__ import annotations

from pathlib import Path

import pytest

from tools.fx.node_preset_library import config
from tools.fx.node_preset_library.logic import (
    add_category,
    add_preset,
    category_id_from_name,
    delete_category,
    delete_preset,
    ensure_library_root,
    get_preset,
    list_categories,
    list_presets,
    load_index,
    merge_library_from_folder,
    new_preset_id,
    preset_relative_paths,
)


@pytest.fixture
def library_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("MONOFX_NODE_PRESET_LIBRARY", str(tmp_path))
    return ensure_library_root(tmp_path)


def test_category_id_from_name_slug() -> None:
    assert category_id_from_name("FX-Setup") == "fx_setup"
    assert category_id_from_name("SOP Utils") == "sop_utils"


def test_add_category_and_preset(library_root: Path) -> None:
    add_category("SOP Utils", library_root)
    rel_cpio, _ = preset_relative_paths("sop_utils", "abc123")
    add_preset("Preset A", "sop_utils", rel_cpio, 2, library_root=library_root, preset_id="abc123")

    cats = list_categories(library_root)
    assert any(c["id"] == "sop_utils" for c in cats)

    presets = list_presets(category_id="sop_utils", library_root=library_root)
    assert len(presets) == 1
    assert presets[0]["name"] == "Preset A"


def test_delete_preset_removes_files(library_root: Path) -> None:
    add_category("Test", library_root)
    rel_cpio, rel_thumb = preset_relative_paths("test", "del1")
    cpio_path = library_root / rel_cpio
    thumb_path = library_root / rel_thumb
    cpio_path.parent.mkdir(parents=True, exist_ok=True)
    cpio_path.write_text("fake cpio", encoding="utf-8")
    thumb_path.write_text("fake png", encoding="utf-8")

    add_preset(
        "To Delete",
        "test",
        rel_cpio,
        1,
        thumbnail_relative=rel_thumb,
        library_root=library_root,
        preset_id="del1",
    )

    assert delete_preset("del1", library_root)
    assert get_preset("del1", library_root) is None
    assert not cpio_path.is_file()
    assert not thumb_path.is_file()


def test_delete_category_moves_presets_to_uncategorized(library_root: Path) -> None:
    add_category("FX-Setup", library_root)
    add_category("Uncategorized", library_root)

    rel_cpio, _ = preset_relative_paths("fx_setup", "move1")
    cpio_path = library_root / rel_cpio
    cpio_path.parent.mkdir(parents=True, exist_ok=True)
    cpio_path.write_text("preset data", encoding="utf-8")

    add_preset("Moved", "fx_setup", rel_cpio, 1, library_root=library_root, preset_id="move1")

    assert delete_category("fx_setup", library_root)

    preset = get_preset("move1", library_root)
    assert preset is not None
    assert preset["category_id"] == "uncategorized"
    assert preset["file"] == f"categories/uncategorized/preset_move1{config.PRESET_FILE_EXT}"
    assert (library_root / preset["file"]).is_file()
    assert not (library_root / "categories" / "fx_setup").exists()

    cats = list_categories(library_root)
    assert not any(c["id"] == "fx_setup" for c in cats)


def test_merge_library_from_folder(library_root: Path, tmp_path: Path) -> None:
    source = tmp_path / "source_lib"
    ensure_library_root(source)
    add_category("Imported", source)
    rel_cpio, _ = preset_relative_paths("imported", "imp1")
    (source / rel_cpio).parent.mkdir(parents=True, exist_ok=True)
    (source / rel_cpio).write_text("imported", encoding="utf-8")
    add_preset("Imported Preset", "imported", rel_cpio, 1, library_root=source, preset_id="imp1")

    cats_added, presets_added = merge_library_from_folder(source, library_root)
    assert cats_added == 1
    assert presets_added == 1
    assert get_preset("imp1", library_root) is not None


def test_new_preset_id_unique() -> None:
    ids = {new_preset_id() for _ in range(20)}
    assert len(ids) == 20
