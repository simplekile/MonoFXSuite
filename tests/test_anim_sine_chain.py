"""Tests for sine-chain driver helpers."""

from __future__ import annotations

from monofx_pipeline_common import anim_chains as _chains
from monofx_pipeline_common import anim_sine_chain as _sine


def test_channel_data_path_rotation_z() -> None:
    prop_path, index = _sine.channel_data_path("ROTATION", "Z")
    assert prop_path == "rotation_euler"
    assert index == 2


def test_channel_data_path_location_x() -> None:
    prop_path, index = _sine.channel_data_path("LOCATION", "x")
    assert prop_path == "location"
    assert index == 0


def test_build_sine_driver_expression_bakes_index() -> None:
    expr0 = _sine.build_sine_driver_expression(0, 6, ramp_factor=0.0)
    expr3 = _sine.build_sine_driver_expression(3, 6, ramp_factor=0.6)
    assert "-freq * 0" in expr0
    assert "phase + 0" in expr0
    assert "-freq * 3" in expr3
    assert "radians((amp * 0))" in expr0 or "radians((amp * 0.0))" in expr0
    assert "radians((amp * 0.6))" in expr3
    assert "frame / 24" in expr3
    assert "2 * pi * speed" in expr3


def test_build_sine_driver_expression_location_skips_radians_amp() -> None:
    expr = _sine.build_sine_driver_expression(1, 4, ramp_factor=0.5, channel="LOCATION")
    assert "(amp * 0.5)" in expr
    assert "radians((amp" not in expr


def test_build_sine_driver_expression_chain_phase() -> None:
    expr = _sine.build_sine_driver_expression(2, 5, chain_phase=45.0)
    assert "phase + 45" in expr


def test_build_sine_driver_expression_noise() -> None:
    expr = _sine.build_sine_driver_expression(1, 4, wave_mode="NOISE")
    assert "sin(" in expr
    assert "/ 3" in expr
    assert "2.17" in expr


def test_build_sine_driver_expression_root_tip() -> None:
    expr = _sine.build_sine_driver_expression(3, 6, ramp_mode="ROOT_TIP")
    assert "amp_root" in expr
    assert "amp_tip" in expr
    assert "0.6" in expr
    assert "radians(" in expr


def test_chain_amp_t() -> None:
    assert _sine.chain_amp_t(0, 6) == 0.0
    assert _sine.chain_amp_t(5, 6) == 1.0
    assert _sine.chain_amp_t(0, 1) == 0.0


def test_encode_decode_sine_rna() -> None:
    encoded = _sine.encode_sine_rna("rotation_euler", 2)
    decoded = _sine.decode_sine_rna(encoded)
    assert decoded == ("rotation_euler", 2)


def test_scene_sine_prop_paths() -> None:
    paths = _sine.scene_sine_prop_paths("ROTATION", "Z")
    assert paths["amp"].endswith("anim_sine_rot_z.amplitude")
    assert paths["speed"].endswith("anim_sine_rot_z.speed")
    assert "period" not in paths
    loc_paths = _sine.scene_sine_prop_paths("LOCATION", "X")
    assert loc_paths["freq"].endswith("anim_sine_loc_x.frequency")


def test_sine_axis_prop_prefix() -> None:
    assert _sine.sine_axis_prop_prefix("ROTATION", "Y") == "anim_sine_rot_y"
    assert _sine.sine_axis_prop_prefix("LOCATION", "z") == "anim_sine_loc_z"
    assert _sine.sine_axis_prop_prefix("ROTATION", "Z") == "anim_sine_rot_z"


def test_read_axis_float_deferred_fallback() -> None:
    class _Deferred:
        pass

    class _Prop:
        default = 180.0

    class _Props:
        def __getitem__(self, key):
            return _Prop()

        def __contains__(self, key):
            return key == "chain_offset"

    class _Axis:
        bl_rna = type("RNA", (), {"properties": _Props()})()

        @property
        def chain_offset(self):
            return type("_PropertyDeferred", (), {})()

    assert _sine.read_axis_float(_Axis(), "chain_offset", 0.0) == 180.0
    assert _sine.read_axis_float(_Axis(), "missing", 42.0) == 42.0


def test_sine_owner_prop_and_slots() -> None:
    assert _sine.sine_owner_prop("monofx_sine_base", "rot_z") == "monofx_sine_base_rot_z"
    assert _sine.encode_sine_slots(["rot_z", "rot_x"]) == "rot_x,rot_z"
    assert _sine.parse_sine_slots("rot_z, rot_x") == ["rot_z", "rot_x"]


def test_list_sine_axis_keys_legacy() -> None:
    owner = {
        "monofx_sine_rna": "rotation_euler|2",
        "monofx_sine_axis_key": "rot_z",
    }
    assert _sine.list_sine_axis_keys(owner) == ["rot_z"]
    owner2 = {"monofx_sine_slots": "rot_x,rot_z"}
    assert _sine.list_sine_axis_keys(owner2) == ["rot_x", "rot_z"]
    assert _sine.owner_has_sine_driver(owner2) is True


def test_object_hierarchy_chain_from_mid_object() -> None:
    names = [f"link_{i:02d}" for i in range(6)]
    parent_of = {names[0]: None}
    children_of = {names[0]: [names[1]]}
    for i in range(1, 6):
        parent_of[names[i]] = names[i - 1]
        children_of[names[i]] = [names[i + 1]] if i < 5 else []
    result = _chains.chain_members_from_hierarchy(names[3], parent_of, children_of)
    assert result == names
