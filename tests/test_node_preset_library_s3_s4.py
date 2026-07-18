"""Tests for export/import zip and favorites prefs."""

from __future__ import annotations

from pathlib import Path

import pytest

from tools.fx.node_preset_library.logic import (
    add_category,
    add_preset,
    ensure_library_root,
    export_library_to_zip,
    get_preset,
    merge_library_from_zip,
    preset_relative_paths,
)
from tools.fx.node_preset_library.prefs import (
    is_favorite,
    list_favorite_ids,
    list_recent_preset_ids,
    remember_recent_preset,
    toggle_favorite,
)


@pytest.fixture
def library_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("MONOFX_NODE_PRESET_LIBRARY", str(tmp_path / "lib"))
    monkeypatch.setenv("MONOFX_NODE_PRESET_PREFS", str(tmp_path / "prefs.json"))
    root = ensure_library_root(tmp_path / "lib")
    add_category("SOP Utils", root)
    rel, _ = preset_relative_paths("sop_utils", "z1")
    (root / rel).parent.mkdir(parents=True, exist_ok=True)
    (root / rel).write_bytes(b"cpio")
    add_preset("ZipMe", "sop_utils", rel, 1, library_root=root, preset_id="z1")
    return root


def test_export_and_import_zip(library_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    zip_path = tmp_path / "out" / "lib.zip"
    written = export_library_to_zip(zip_path, library_root)
    assert written.is_file()

    dest = tmp_path / "dest_lib"
    monkeypatch.setenv("MONOFX_NODE_PRESET_LIBRARY", str(dest))
    ensure_library_root(dest)
    cats, presets = merge_library_from_zip(written, dest)
    assert cats >= 1
    assert presets == 1
    assert get_preset("z1", dest) is not None
    assert (dest / get_preset("z1", dest)["file"]).is_file()


def test_favorites_and_recent_presets(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MONOFX_NODE_PRESET_PREFS", str(tmp_path / "prefs.json"))
    assert toggle_favorite("a") is True
    assert is_favorite("a")
    assert toggle_favorite("a") is False
    assert not is_favorite("a")
    toggle_favorite("b")
    toggle_favorite("c")
    assert list_favorite_ids()[0] == "c"

    remember_recent_preset("p1")
    remember_recent_preset("p2")
    remember_recent_preset("p1")
    assert list_recent_preset_ids()[0] == "p1"
    assert list_recent_preset_ids()[1] == "p2"
