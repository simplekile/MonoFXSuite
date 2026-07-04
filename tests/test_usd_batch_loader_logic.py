"""Tests for usd_batch_loader.logic (no Houdini)."""

from tools.fx.usd_batch_loader.logic import apply_strip_name, node_name_from_label


def test_strip_comma_separated_tokens() -> None:
    stem = "prop_Grass_uv_grass_dry_short_publish"
    assert apply_strip_name(stem, "prop_,publish") == "Grass_uv_grass_dry_short"
    assert node_name_from_label("prop_Grass_uv_grass_dry_short_publish.usd", "prop_,publish") == (
        "Grass_uv_grass_dry_short"
    )


def test_strip_empty_unchanged() -> None:
    assert node_name_from_label("foo_bar.usd", "") == "foo_bar"
