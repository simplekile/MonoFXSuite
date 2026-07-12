"""
Group publish geo export targets by linked library path (no bpy).
"""

from __future__ import annotations

from typing import Callable, Optional, Protocol, Sequence


class PublishGeoLike(Protocol):
    publish_name: str


def group_publish_geo_by_link(
    groups: Sequence[PublishGeoLike],
    *,
    merge_by_link: bool,
    link_key_fn: Optional[Callable[[str], str]] = None,
) -> list[list[PublishGeoLike]]:
    """Bucket publish groups; merge buckets when *merge_by_link* is enabled."""
    if not groups:
        return []
    if not merge_by_link:
        return [[group] for group in groups]

    resolve_key = link_key_fn or (lambda publish_name: f"publish:{publish_name}")
    buckets: dict[str, list[PublishGeoLike]] = {}
    order: list[str] = []
    for group in groups:
        key = resolve_key(group.publish_name)
        if key.startswith("publish:"):
            key = f"publish:{group.publish_name}"
        if key not in buckets:
            buckets[key] = []
            order.append(key)
        buckets[key].append(group)
    return [buckets[key] for key in order]
