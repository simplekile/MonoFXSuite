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

HDA_TYPE = "mono_anim_loader::2.2"
HDA_LABEL = "Mono Anim Loader"
LEGACY_TYPES = ("mono_anim_loader::2.1", "mono_anim_loader::2")
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

# Shot rules for subdivision (JSON list of {"pattern", "scheme", "dicing"}), see logic.subd_plan.
P_SUBD_RULES = "mx_subd_rules"
