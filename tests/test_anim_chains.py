"""Tests for control-bone chain resolution."""

from __future__ import annotations

import importlib.util
from pathlib import Path

_MOD = (
    Path(__file__).resolve().parents[1]
    / "tools/fx/monofx_pipeline_blender/monofx_pipeline_blender/pipeline_common/anim_chains.py"
)
_spec = importlib.util.spec_from_file_location("monofx_anim_chains", _MOD)
assert _spec and _spec.loader
_chains = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_chains)


def test_kilt_chain_from_mid_bone() -> None:
    bones = [f"c_kilt_01_{i:02d}.l" for i in range(1, 7)]
    result = _chains.chain_members_from_bone("c_kilt_01_04.l", bones)
    assert result == bones


def test_index_finger_controls_only() -> None:
    bones = [
        "index1_rot.l",
        "c_index1.l",
        "index1.l",
        "index2_rot.l",
        "c_index2.l",
        "index3_rot.l",
        "c_index3.l",
    ]
    result = _chains.chain_members_from_bone("c_index1.l", bones)
    assert result == ["c_index1.l", "c_index2.l", "c_index3.l"]


def test_non_control_returns_single() -> None:
    bones = ["index1_rot.l", "c_index1.l"]
    assert _chains.chain_members_from_bone("index1_rot.l", bones) == ["index1_rot.l"]


def test_parse_control_chain_bone() -> None:
    assert _chains.parse_control_chain_bone("c_index1.l") == ("c_index", 1, ".l")
    assert _chains.parse_control_chain_bone("c_kilt_01_04.l") == ("c_kilt_01_", 4, ".l")


def test_hierarchy_chain_from_mid_bone() -> None:
    names = [f"c_DressFront_{i:02d}_dupli_002.x" for i in range(6)]
    parent_of = {names[0]: None}
    children_of = {names[0]: [names[1]]}
    for i in range(1, 6):
        parent_of[names[i]] = names[i - 1]
        children_of[names[i]] = [names[i + 1]] if i < 5 else []
    result = _chains.chain_members_from_hierarchy(names[3], parent_of, children_of)
    assert result == names


def test_hierarchy_chain_from_root_with_branch() -> None:
    root, a1, a2, b1 = "root", "a1", "a2", "b1"
    parent_of = {root: None, a1: root, a2: a1, b1: root}
    children_of = {root: [a1, b1], a1: [a2], a2: [], b1: []}
    assert _chains.chain_members_from_hierarchy(root, parent_of, children_of) == [root, a1, a2]
    assert _chains.chain_members_from_hierarchy(a2, parent_of, children_of) == [root, a1, a2]
