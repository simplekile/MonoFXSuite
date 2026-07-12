"""Tests for control-bone chain resolution."""

from __future__ import annotations

from monofx_pipeline_common import anim_chains as _chains


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
    assert _chains.parse_control_chain_bone("c_DressFront_00_dupli_002.x") == (
        "c_DressFront_",
        0,
        "_dupli_002.x",
    )


def test_dress_front_chain_from_naming() -> None:
    bones = [f"c_DressFront_{i:02d}_dupli_002.x" for i in range(6)]
    result = _chains.chain_members_from_bone("c_DressFront_03_dupli_002.x", bones)
    assert result == bones


def test_hierarchy_branch_stops_at_fork() -> None:
    rig_root = "c_pos"
    traj = "c_traj"
    dress = [f"c_DressFront_{i:02d}_dupli_002.x" for i in range(6)]
    parent_of = {
        rig_root: None,
        traj: rig_root,
        dress[0]: traj,
    }
    children_of = {rig_root: [traj], traj: [dress[0], "other_branch"]}
    for i in range(1, 6):
        parent_of[dress[i]] = dress[i - 1]
        children_of[dress[i - 1]] = [dress[i]]
    children_of[dress[5]] = []

    full = _chains.chain_members_from_hierarchy(dress[3], parent_of, children_of)
    branch = _chains.chain_members_from_hierarchy_branch(dress[3], parent_of, children_of)
    assert len(full) > len(branch)
    assert branch == dress


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


def test_sort_chain_selection_root_to_leaf() -> None:
    parent_of = {"a": None, "b": "a", "c": "b", "d": None}
    children_of = {"a": ["b"], "b": ["c"], "c": [], "d": []}
    result = _chains.sort_chain_selection(["c", "a", "b"], parent_of, children_of)
    assert result == ["a", "b", "c"]


def test_sort_chain_selection_multiple_roots() -> None:
    parent_of = {"a": None, "b": "a", "x": None, "y": "x"}
    children_of = {"a": ["b"], "b": [], "x": ["y"], "y": []}
    result = _chains.sort_chain_selection(["y", "b", "x", "a"], parent_of, children_of)
    assert result == ["a", "b", "x", "y"]


def test_mirror_control_bone_name() -> None:
    assert _chains.mirror_control_bone_name("c_kilt_01_04.l") == "c_kilt_01_04.r"
    assert _chains.mirror_control_bone_name("c_index1.r") == "c_index1.l"
    assert _chains.mirror_control_bone_name("c_DressFront_03_dupli_002.x") is None


def test_partition_selection_chains() -> None:
    parent_of = {"a": None, "b": "a", "x": None, "y": "x"}
    children_of = {"a": ["b"], "b": [], "x": ["y"], "y": []}
    result = _chains.partition_selection_chains(["b", "y", "a", "x"], parent_of, children_of)
    assert result == [["a", "b"], ["x", "y"]]


def test_multi_chain_seeds_dedupe_order() -> None:
    names = ["c_kilt_01_02.l", "c_kilt_01_04.l", "c_index1.l"]
    assert list(dict.fromkeys(names)) == names
