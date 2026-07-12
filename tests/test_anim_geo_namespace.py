"""Tests for anim geo namespace mesh matching."""

from __future__ import annotations

from monofx_pipeline_common import anim_geo_namespace as _ns


def test_namespace_prefixes_from_geo_collections():
    prefixes = _ns.namespace_prefixes_from_geo_collections(
        ["tachirig::Geo", "tachirig2::Geo", "tachirig::Rig", "Other"]
    )
    assert prefixes == ("tachirig", "tachirig2")


def test_mesh_names_matching_namespace_prefixes():
    names = _ns.mesh_names_matching_namespace_prefixes(
        [
            "tachirig::Geo_Belt",
            "tachirig2::Geo_Belt",
            "tachirig::Tachi_rig",
            "Body",
        ],
        ("tachirig", "tachirig2"),
    )
    assert set(names) == {
        "tachirig::Geo_Belt",
        "tachirig2::Geo_Belt",
        "tachirig::Tachi_rig",
    }
