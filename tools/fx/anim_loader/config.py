"""Names and patterns of Mono Anim Loader 2.2 (no hou)."""

from __future__ import annotations

ASSET_TYPES = ("char", "prop", "veh", "env", "set", "fx")

# A clone in a new publish: geo_char_Robot_inst02.usd (instance 2). Old publishes used _2.
CLONE_RE = r"_inst(\d{2,})$"
OLD_CLONE_RE = r"_(\d+)$"

ANIM_PREFIXES = {"geo_": "geo", "cam_": "cam"}
USD_EXTS = (".usd", ".usda", ".usdc")

# Groom / cloth sequences (spike S1/S2, docs/plans/anim_loader_v2_2.md section 6): value clips authored after
# the graft on a new layer when the cache holds time samples, else a Sublayer of the $F path (no motion blur).
FX_MODE_CLIP = "clip"
FX_MODE_SUBLAYER = "sublayer"

# MonoFX Loader (the user's call, 2026-11-17: the node must not read "anim loader"). The 2.2 type is still built,
# hidden from the Tab menu (OPcustomize), so saved scenes open; the manager's Upgrade moves 2.2 nodes over.
HDA_TYPE = "monofx::loader::1.0"
HDA_FILE = "monofx_loader.hdalc"
HDA_NODE_NAME = "monofx_loader"
OLD_TYPE = "mono_anim_loader::2.2"
OLD_FILE = "mono_anim_loader.hdalc"
HDA_LABEL = "MonoFX Loader"  # the user's pick, 2026-11-17; the type name stays (saved scenes)
LEGACY_TYPES = ("mono_anim_loader::2.2", "mono_anim_loader::2.1", "mono_anim_loader::2")
# Character Loader (Dropbox HDA): Upgrade makes a 2.2 node with Source Asset (docs/plans/anim_loader_asset_source.md)
CHARACTER_LOADER_PREFIX = "mono_character_loader"
USER_DATA = "monofx_anim_loader"  # JSON {"shot", "anim_file"}: finds a shot's loaders whatever their names
MERGE_USER_DATA = "monofx_anim_loader_merge"  # the shot's Merge LOP made by Load shot

# Parms (2.1 names kept where the meaning is the same).
P_ROOT, P_SHOT, P_ANIM_VERSION, P_ANIM_FILE = "mx_project_root", "mx_shot", "mx_anim_version", "mx_anim_usd"
P_ASSET, P_INSTANCE, P_GEO_CAM, P_STATUS = "mx_asset", "mx_instance_name", "mx_geo_cam", "mx_status"
P_ANIM_PATH = "mx_selected_anim_usd_path"
P_ENABLE = {"lookdev": "mx_enable_lookdev", "groom": "mx_enable_groom", "cloth": "mx_enable_cloth"}
P_VERSION = {"lookdev": "mx_lookdev_version", "groom": "mx_groom_version", "cloth": "mx_cloth_version"}
P_PATH = {"lookdev": "mx_selected_lookdev_usd_path", "groom": "mx_selected_groom_usd_path",
          "cloth": "mx_selected_cloth_usd_path"}
# Hidden, written by refresh: the branch's sublayers (strongest first) and the clips authored after the graft.
P_LAYERS = tuple(f"mx_layer_{i}" for i in range(1, 5))
P_FX = {t: {k: f"mx_{t}_{k}" for k in ("mode", "template", "first", "last", "roots")} for t in ("groom", "cloth")}

# Show in Viewport: a button strip, one bit per part (on = the viewport draws it; off = Karma only).
P_VIEWPORT = "mx_viewport"
VIEWPORT_BITS = {"lookdev": 1, "groom": 2}

# Shot rules for subdivision (JSON list of {"pattern", "scheme", "dicing"}), see logic.subd_plan.
P_SUBD_RULES = "mx_subd_rules"
# Hidden: what the shot shows of each prim (the user's pick, layout B, 2026-11-17): JSON [{"pattern": <prim under the
# instance, no leading "/">, "show": hidden | render | proxy | both}], authored by the show_rules Python LOP last
P_SHOW_RULES = "mx_show_rules"
P_HIDE_ENABLE = "mx_hide_enable"
P_HIDE_PATTERN = "mx_hide_pattern"

# Source (docs/plans/anim_loader_asset_source.md): a shot's anim, or the asset's own publishes (UV model, groom,
# lookdev) for grooming / lookdev scenes. Both graft under /<asset>, so prim paths match.
P_SOURCE = "mx_source"
SOURCE_SHOT, SOURCE_ASSET = "shot", "asset"
P_MODEL_VERSION, P_MODEL_FILE = "mx_model_version", "mx_model_file"
P_MODEL_PATH = "mx_model_path"  # Advanced: the resolved model file (Anim Path is for Source Shot)
P_ASSET_GROUP = "mx_asset_group"  # Source Asset: filters the Asset menu (01_assets/_characters, _props...)
# Groom sits outside Geo in both sources (the user's pick): /<asset>/Groom/<name>, where lookdev binds hair.
GROOM_ROOT = "/Groom"
P_GROOM_TOPO = "mx_groom_topo"  # file the branch copies the groom topology from (first frame, or $F without samples)
