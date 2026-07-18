"""

Scene export targets for Anim USD cache (scrollable list UI).

"""



from __future__ import annotations



from bpy.types import Context, UILayout



from . import anim_usd_cache_asset_list as asset_list





def draw_scene_assets_list(layout: UILayout, context: Context, props) -> int:

    """Draw unified export target list; returns count of enabled targets."""

    enabled_count = asset_list.enabled_export_target_count(props)

    total_count = asset_list.export_target_total_count(props)



    if total_count == 0:

        if asset_list.export_assets_refresh_pending() and not props.anim_usd_export_list_locked:

            layout.label(text="Updating export targets…", icon="FILE_REFRESH")

            return 0

        alert = layout.row()

        alert.alert = True

        alert.label(

            text="No export targets — link *_publish* rig or add cameras",

            icon="ERROR",

        )

        return 0



    list_header = layout.row(align=True)

    list_header.label(

        text=f"Export Targets ({enabled_count}/{total_count})",

        icon="EXPORT",

    )

    lock_row = list_header.row(align=True)

    lock_row.prop(

        props,

        "anim_usd_export_list_locked",

        text="",

        icon="LOCKED" if props.anim_usd_export_list_locked else "UNLOCKED",

        toggle=True,

        emboss=True,

    )

    list_header.operator(

        "wm.mono_fx_refresh_anim_usd_export_list",

        text="",

        icon="FILE_REFRESH",

    )

    layout.template_list(

        "MONOFX_UL_anim_usd_export_assets",

        "anim_usd_export_assets",

        props,

        "anim_usd_export_assets",

        props,

        "anim_usd_export_assets_index",

        rows=4,

    )



    if enabled_count == 0:

        hint = layout.row()

        hint.alert = True

        hint.label(text="Enable at least one target to publish.", icon="ERROR")



    return enabled_count

