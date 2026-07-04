"""Tests for anim USD merge-by-link grouping."""

from __future__ import annotations

import importlib.util
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]


def _load_merge():
    path = (
        _ROOT
        / "tools/fx/monofx_pipeline_blender/monofx_pipeline_blender/pipeline_common/anim_geo_merge.py"
    )
    spec = importlib.util.spec_from_file_location("anim_geo_merge_test", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_merge = _load_merge()
group_publish_geo_by_link = _merge.group_publish_geo_by_link


class _Group:
    def __init__(self, publish_name: str) -> None:
        self.publish_name = publish_name


def test_group_publish_geo_by_link_disabled():
    groups = [_Group("CHAR_A_RIG_PUBLISH"), _Group("CHAR_A_RIG_PUBLISH.001")]
    buckets = group_publish_geo_by_link(groups, merge_by_link=False)
    assert len(buckets) == 2


def test_group_publish_geo_by_link_merges_same_library():
    groups = [
        _Group("CHAR_TACHI_RIG_PUBLISH"),
        _Group("CHAR_TACHI_RIG_PUBLISH.001"),
        _Group("CHAR_KAHLII_RIG_PUBLISH"),
    ]

    def link_key(publish_name: str) -> str:
        if "TACHI" in publish_name:
            return "/project/rig/tachi_publish.blend"
        return f"publish:{publish_name}"

    buckets = group_publish_geo_by_link(
        groups,
        merge_by_link=True,
        link_key_fn=link_key,
    )
    assert len(buckets) == 2
    tachi = next(b for b in buckets if b[0].publish_name.startswith("CHAR_TACHI"))
    assert len(tachi) == 2
