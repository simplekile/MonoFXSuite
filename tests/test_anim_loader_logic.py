"""Mono Anim Loader 2.2: pure logic (no hou). Spec: docs/plans/anim_loader_v2_2.md."""

from __future__ import annotations

from tools.fx.anim_loader.logic import Output, instance_name, resolve_instance

A = {"char_Robot", "char_Robot_2", "prop_CoralSet_001", "char_Helen"}


def test_instance_name_strips_prefix_and_extension():
    assert instance_name("geo_char_Helen_inst02.usdc") == "char_Helen_inst02"
    assert instance_name("cam_sh010.usd") == "sh010"


def test_meta_wins():
    i = resolve_instance(Output("geo_char_Robot_2.usd", "geo", "char_Robot", 2), A)
    assert (i.name, i.asset, i.instance, i.guessed) == ("char_Robot_2", "char_Robot", 2, False)


def test_new_clone_suffix():
    i = resolve_instance(Output("geo_char_Robot_inst02.usd", "geo"), A)
    assert (i.name, i.asset, i.instance) == ("char_Robot_inst02", "char_Robot", 2)


def test_first_instance_is_one():
    i = resolve_instance(Output("geo_char_Helen.usd", "geo"), A)
    assert (i.asset, i.instance, i.guessed) == ("char_Helen", 1, True)


def test_asset_with_digits():
    i = resolve_instance(Output("geo_prop_CoralSet_001.usd", "geo"), A)
    assert (i.asset, i.instance) == ("prop_CoralSet_001", 1)


def test_old_clone_suffix():
    i = resolve_instance(Output("geo_char_Helen_2.usd", "geo"), A)
    assert (i.name, i.asset, i.instance, i.guessed) == ("char_Helen_2", "char_Helen", 2, True)


def test_ambiguous_old_clone():
    i = resolve_instance(Output("geo_char_Robot_2.usd", "geo"), A)
    assert i.asset is None and set(i.candidates) == {"char_Robot", "char_Robot_2"}


def test_no_asset_name():
    i = resolve_instance(Output("geo_sh011.usd", "geo"), A)
    assert i.asset is None and i.candidates == () and i.name == "sh011"


def test_camera():
    i = resolve_instance(Output("cam_sh010.usd", "cam"), A)
    assert (i.kind, i.asset, i.name) == ("cam", None, "sh010")
