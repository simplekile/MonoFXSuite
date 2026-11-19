"""Test in Houdini (the Blender add-on's button), the decisions: what to build for a publish and the check line.

No hou, no pxr: ``apps/houdini/publish_preview.py`` reads the files and the stage and builds the nodes.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from tools.fx.anim_loader import config, logic

_VERSION_RE = re.compile(r"^[vV]\d+$")


@dataclass(frozen=True)
class Plan:
    """What the test scene loads. ``mode``: "asset" (a MonoFX Loader on Source Asset), "shot" (Load shot of a
    version) or "sublayer" (a publish the loader cannot read: a plain Sublayer LOP of each file)."""

    kind: str
    mode: str
    title: str
    files: tuple[str, ...]
    root: str = ""
    asset: str = ""
    model_version: str = ""
    model_file: str = ""
    shot: str = ""
    anim_version: str = ""
    note: str = ""


def _usd_files(folder: Path) -> list[str]:
    return [str(folder / f) for f in logic.usd_files(folder)]


def plan(kind: str, path: str) -> Plan:
    """The test scene for a model file or an anim version folder (or one file in it)."""
    p = Path(path)
    if kind == "anim":
        folder = p if p.is_dir() or not p.suffix else p.parent
        files = tuple(_usd_files(folder))
        ref = logic.parse_publish_path((folder / "x.usd").as_posix())
        title = f"{ref.entity} anim {ref.version}" if ref else f"anim {folder.name}"
        if ref and ref.kind == "shot" and ref.dept.lower().endswith("01_anim"):
            return Plan("anim", "shot", title, files, root=ref.root, shot=ref.entity, anim_version=ref.version)
        return Plan("anim", "sublayer", title, files,
                    note="Not a shot's 01_anim publish: each file in a plain Sublayer, not a MonoFX Loader.")
    ref = logic.parse_publish_path(p.as_posix())
    title = f"{ref.entity} model {ref.version}" if ref else p.name
    if ref and ref.kind == "asset" and ref.dept.replace("\\", "/").lower() == "01_modelling/03_uv" \
            and "/" not in ref.file:
        return Plan("model", "asset", title, (str(p),), root=ref.root, asset=ref.entity,
                    model_version=ref.version, model_file=ref.file)
    return Plan("model", "sublayer", title, (str(p),),
                note="Not a 03_uv publish, which is what the MonoFX Loader reads: a plain Sublayer instead.")


def asset_state(pl: Plan) -> logic.LoaderState:
    """The loader's state for an "asset" plan: the asset's newest lookdev and groom, this model version and file."""
    from dataclasses import replace

    st = logic.initial_asset_state(Path(pl.root), pl.asset)
    return replace(st, model_version=pl.model_version, model_file=pl.model_file)


# --- the check line: shared with Test in Blender ------------------------------------------------------------

from monofx_pipeline_common.publish_checks import (  # noqa: E402,F401
    FileFacts, StageFacts, check_line, note_text, problems, summary,
)

SAVE_HINT = r"This scene is not saved in the project; a save goes to %TEMP%\MonoFX\houdini_test."

HDA_MISSING = (f"MonoFX test: the MonoFX Loader ({config.HDA_TYPE}) is not installed in this Houdini. "
               "Run MonoFXSuite_Setup.exe for this Houdini version.")
