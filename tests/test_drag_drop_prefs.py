"""Tests for Drag & Drop settings (no Qt, no hou)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.fx.drag_drop import prefs


@pytest.fixture
def prefs_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "drag_drop_prefs.json"
    monkeypatch.setenv("MONOFX_DRAG_DROP_PREFS", str(path))
    return path


def test_defaults_when_no_file(prefs_file: Path) -> None:
    assert prefs.load_prefs() == prefs.DEFAULTS


def test_save_and_load_round_trip(prefs_file: Path) -> None:
    data = {"enabled": False, "lop_layer_mode": prefs.LAYER_SUBLAYER,
            "lop_textures_material": False, "collapse_sequences": False}
    prefs.save_prefs(data)
    assert prefs.load_prefs() == data


def test_bad_values_fall_back_to_defaults(prefs_file: Path) -> None:
    prefs_file.write_text(json.dumps({"enabled": "yes", "lop_layer_mode": "copy", "extra": 1}), encoding="utf-8")
    assert prefs.load_prefs() == prefs.DEFAULTS


def test_broken_json_gives_defaults(prefs_file: Path) -> None:
    prefs_file.write_text("{not json", encoding="utf-8")
    assert prefs.load_prefs() == prefs.DEFAULTS
