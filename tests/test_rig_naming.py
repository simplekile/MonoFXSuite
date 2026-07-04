"""Tests for rig hierarchy prefix naming."""

from __future__ import annotations

from apps.common.rig_naming import (
    RIG_NAMESPACE_SEPARATOR,
    detect_rig_hierarchy_prefix_from_names,
    detect_rig_hierarchy_prefix_from_pairs,
    link_bare_name,
    migrate_prefix_to_canonical,
    namespace_prefixed_name,
    prefixed_name,
    rig_prefix_base_from_asset_folder,
    strip_blender_duplicate_suffix,
    strip_known_rig_prefix,
    unique_rig_hierarchy_prefix,
)


def test_rig_prefix_base_from_char_kahlli() -> None:
    assert rig_prefix_base_from_asset_folder("char_Kahlli") == "kahllirig"


def test_unique_prefix_first_and_duplicate() -> None:
    used: set[str] = set()

    def in_use(prefix: str) -> bool:
        return prefix in used

    first = unique_rig_hierarchy_prefix("char_Kahlli", in_use)
    assert first == f"kahllirig{RIG_NAMESPACE_SEPARATOR}"
    used.add(first)

    second = unique_rig_hierarchy_prefix("char_Kahlli", in_use)
    assert second == f"kahllirig2{RIG_NAMESPACE_SEPARATOR}"


def test_prefixed_name_idempotent() -> None:
    prefix = f"kahllirig{RIG_NAMESPACE_SEPARATOR}"
    assert prefixed_name("root", prefix) == f"kahllirig{RIG_NAMESPACE_SEPARATOR}root"
    assert prefixed_name(f"kahllirig{RIG_NAMESPACE_SEPARATOR}root", prefix) == f"kahllirig{RIG_NAMESPACE_SEPARATOR}root"


def test_detect_prefix_from_mixed_names_after_reload() -> None:
    prefix = f"tachirig{RIG_NAMESPACE_SEPARATOR}"
    names = [
        f"tachirig{RIG_NAMESPACE_SEPARATOR}Geo",
        f"tachirig{RIG_NAMESPACE_SEPARATOR}Geo_Body",
        "Geo_Teeth",
        "Geo_HairDriver",
        f"tachirig{RIG_NAMESPACE_SEPARATOR}Geo_Shirt",
    ]
    assert detect_rig_hierarchy_prefix_from_names(names, "char_Tachi") == prefix


def test_detect_prefix_from_prefixed_unprefixed_pairs() -> None:
    prefix = f"tachirig{RIG_NAMESPACE_SEPARATOR}"
    names = [f"tachirig{RIG_NAMESPACE_SEPARATOR}Geo_Body", "Geo_Body", "Geo_Teeth"]
    assert detect_rig_hierarchy_prefix_from_pairs(names) == prefix


def test_detect_legacy_underscore_prefix() -> None:
    names = ["tachirig_Geo_Body", "Geo_Teeth", "tachirig_Geo_Shirt"]
    assert detect_rig_hierarchy_prefix_from_names(names, "char_Tachi") == f"tachirig{RIG_NAMESPACE_SEPARATOR}"


def test_strip_and_migrate_legacy_to_canonical() -> None:
    prefix = f"tachirig{RIG_NAMESPACE_SEPARATOR}"
    assert strip_known_rig_prefix("tachirig_Geo_Body", "char_Tachi") == "Geo_Body"
    assert namespace_prefixed_name("tachirig_Geo_Body", prefix, "char_Tachi") == f"tachirig{RIG_NAMESPACE_SEPARATOR}Geo_Body"
    assert namespace_prefixed_name("Geo_Teeth", prefix, "char_Tachi") == f"tachirig{RIG_NAMESPACE_SEPARATOR}Geo_Teeth"
    assert migrate_prefix_to_canonical("tachirig_", "char_Tachi") == prefix
    assert migrate_prefix_to_canonical("tachirig2_", "char_Tachi") == f"tachirig2{RIG_NAMESPACE_SEPARATOR}"


def test_strip_blender_duplicate_suffix_on_reload() -> None:
    assert strip_blender_duplicate_suffix("Geo.001") == "Geo"
    assert strip_blender_duplicate_suffix("Geo_Body.002") == "Geo_Body"
    assert strip_blender_duplicate_suffix("Geo") == "Geo"


def test_reload_name_aligns_to_library_source() -> None:
    prefix = f"tachiproprig{RIG_NAMESPACE_SEPARATOR}"
    assert (
        namespace_prefixed_name(
            f"{prefix}Geo.001",
            prefix,
            "char_TachiProp",
            library_source_name="Geo",
        )
        == f"{prefix}Geo"
    )
    assert link_bare_name(f"{prefix}Rig.001", "char_TachiProp", library_source_name="Rig") == "Rig"
