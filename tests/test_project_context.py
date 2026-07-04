"""Tests for pipeline project root resolution."""

from __future__ import annotations

from pathlib import Path

import pytest

from apps.common.project_context import (
    project_context_error,
    resolve_project_root,
    valid_project_root,
)


@pytest.fixture()
def fake_project(tmp_path: Path) -> Path:
    root = tmp_path / "proj"
    (root / "01_assets").mkdir(parents=True)
    (root / "02_shots").mkdir(parents=True)
    return root


def test_valid_project_root(fake_project: Path) -> None:
    assert valid_project_root(str(fake_project)) == fake_project


def test_valid_project_root_rejects_random_dir(tmp_path: Path) -> None:
    assert valid_project_root(str(tmp_path)) is None


def test_resolve_from_scene_path(fake_project: Path) -> None:
    blend = fake_project / "02_shots" / "sh010" / "work.blend"
    blend.parent.mkdir(parents=True, exist_ok=True)
    blend.write_text("fake", encoding="utf-8")

    root, source = resolve_project_root(str(blend))
    assert root == fake_project
    assert source == "scene"


def test_resolve_falls_back_to_stored(fake_project: Path, tmp_path: Path) -> None:
    outside = tmp_path / "outside.blend"
    outside.write_text("fake", encoding="utf-8")

    root, source = resolve_project_root(str(outside), str(fake_project))
    assert root == fake_project
    assert source == "stored"


def test_resolve_falls_back_to_prefs(fake_project: Path, tmp_path: Path) -> None:
    outside = tmp_path / "outside.blend"
    outside.write_text("fake", encoding="utf-8")

    root, source = resolve_project_root(str(outside), None, str(fake_project))
    assert root == fake_project
    assert source == "fallback"


def test_project_context_error_messages() -> None:
    assert "Save the .blend" in project_context_error(None)
    assert "invalid" in project_context_error("/tmp/foo.blend", has_stored=True).casefold()
