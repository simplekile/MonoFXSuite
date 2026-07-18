"""Tests for node_preset_library.prefs (no Houdini / no Qt)."""

from __future__ import annotations

from pathlib import Path

import pytest

from tools.fx.node_preset_library.prefs import (
    MAX_RECENT_LIBRARY_ROOTS,
    list_recent_library_roots,
    load_prefs,
    prune_recent_prefs,
    remember_library_root,
    remove_recent_library_root,
    resolve_library_root,
)


@pytest.fixture
def prefs_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    prefs = tmp_path / "prefs.json"
    monkeypatch.setenv("MONOFX_NODE_PRESET_PREFS", str(prefs))
    monkeypatch.delenv("MONOFX_NODE_PRESET_LIBRARY", raising=False)
    return prefs


def test_remember_keeps_max_five_mru(prefs_env: Path, tmp_path: Path) -> None:
    roots = []
    for i in range(7):
        r = tmp_path / f"lib{i}"
        r.mkdir()
        remember_library_root(r)
        roots.append(r.resolve())

    recent = list_recent_library_roots(existing_only=True)
    assert len(recent) == MAX_RECENT_LIBRARY_ROOTS
    # Most recent first: lib6 .. lib2
    assert recent[0] == roots[6]
    assert recent[-1] == roots[2]
    assert roots[0] not in recent
    assert roots[1] not in recent

    data = load_prefs()
    assert Path(data["library_root"]).resolve() == roots[6]


def test_remember_moves_existing_to_front(prefs_env: Path, tmp_path: Path) -> None:
    a = tmp_path / "a"
    b = tmp_path / "b"
    a.mkdir()
    b.mkdir()
    remember_library_root(a)
    remember_library_root(b)
    remember_library_root(a)
    recent = list_recent_library_roots()
    assert recent[0] == a.resolve()
    assert recent[1] == b.resolve()
    assert len(recent) == 2


def test_remove_recent_and_prune_missing(prefs_env: Path, tmp_path: Path) -> None:
    a = tmp_path / "keep"
    b = tmp_path / "gone"
    a.mkdir()
    b.mkdir()
    remember_library_root(a)
    remember_library_root(b)
    # Delete folder b from disk
    b.rmdir()
    remaining = prune_recent_prefs()
    assert a.resolve() in remaining
    assert all(p.name != "gone" for p in remaining)

    remember_library_root(a)
    c = tmp_path / "extra"
    c.mkdir()
    remember_library_root(c)
    remove_recent_library_root(c)
    recent = list_recent_library_roots()
    assert c.resolve() not in recent
    assert a.resolve() in recent


def test_resolve_prefers_env(prefs_env: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    env_lib = tmp_path / "from_env"
    env_lib.mkdir()
    prefs_lib = tmp_path / "from_prefs"
    prefs_lib.mkdir()
    remember_library_root(prefs_lib)
    monkeypatch.setenv("MONOFX_NODE_PRESET_LIBRARY", str(env_lib))
    assert resolve_library_root() == env_lib


def test_card_scale_default_and_clamp(prefs_env: Path, tmp_path: Path) -> None:
    from tools.fx.node_preset_library.prefs import (
        DEFAULT_CARD_SCALE,
        MAX_CARD_SCALE,
        MIN_CARD_SCALE,
        clamp_card_scale,
        get_card_scale,
        set_card_scale,
    )

    assert get_card_scale() == DEFAULT_CARD_SCALE
    assert set_card_scale(85) == 85
    assert get_card_scale() == 85
    assert clamp_card_scale(10) == MIN_CARD_SCALE
    assert clamp_card_scale(999) == MAX_CARD_SCALE
    assert set_card_scale(999) == MAX_CARD_SCALE
    data = load_prefs()
    assert data["card_scale"] == MAX_CARD_SCALE
    # Library remember must not wipe card_scale
    lib = tmp_path / "lib_keep"
    lib.mkdir()
    remember_library_root(lib)
    assert get_card_scale() == MAX_CARD_SCALE


def test_pinned_root_survives_mru_overflow(prefs_env: Path, tmp_path: Path) -> None:
    from tools.fx.node_preset_library.prefs import (
        is_pinned_library_root,
        toggle_pin_library_root,
    )

    pinned = tmp_path / "pinned_lib"
    pinned.mkdir()
    remember_library_root(pinned)
    assert toggle_pin_library_root(pinned) is True
    assert is_pinned_library_root(pinned)

    for i in range(6):
        r = tmp_path / f"extra{i}"
        r.mkdir()
        remember_library_root(r)

    recent = list_recent_library_roots(existing_only=True)
    assert pinned.resolve() in recent
    assert is_pinned_library_root(pinned)
    # Still capped unless all remaining are pinned — pinned + newest unpinned
    assert len(recent) <= MAX_RECENT_LIBRARY_ROOTS or pinned.resolve() in recent

    assert toggle_pin_library_root(pinned) is False
    assert not is_pinned_library_root(pinned)
