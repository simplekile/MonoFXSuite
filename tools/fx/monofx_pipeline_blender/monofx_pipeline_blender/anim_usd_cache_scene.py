"""
Scene export targets for Anim USD cache (scrollable list UI).
"""

from __future__ import annotations

from bpy.types import Context, UILayout

from . import anim_usd_cache_asset_list as asset_list
from . import ui_style
from .anim_usd_cache_asset_list import compute_export_assets_signature


def draw_scene_assets_list(layout: UILayout, context: Context, props) -> int:
    """Draw unified export target list; returns count of enabled targets."""
    asset_list.ensure_export_assets_refresh(context, props)

    items = props.anim_usd_export_assets
    if not items:
        pending_sig = (
            compute_export_assets_signature(context, props)
            != props.anim_usd_export_assets_signature
        )
        if pending_sig and not props.anim_usd_export_running:
            layout.label(text="Updating export targets…", icon="FILE_REFRESH")
            return 0
        alert = layout.row()
        alert.alert = True
        alert.label(
            text="No export targets — link *_publish* rig or add cameras",
            icon="ERROR",
        )
        return 0

    enabled_count = sum(1 for item in items if item.enabled)
    ui_style.label_row_right(
        layout,
        "Export Targets",
        str(enabled_count),
        left_icon="EXPORT",
    )

    layout.template_list(
        "MONOFX_UL_anim_usd_export_assets",
        "anim_usd_export_assets",
        props,
        "anim_usd_export_assets",
        props,
        "anim_usd_export_assets_index",
        rows=6,
    )

    if enabled_count == 0:
        alert = layout.row()
        alert.alert = True
        alert.label(text="Nothing enabled for export", icon="ERROR")

    return enabled_count
