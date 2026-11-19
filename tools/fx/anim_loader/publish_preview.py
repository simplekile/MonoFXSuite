"""Test in Houdini (the Blender add-on's button), the decisions: what to build for a publish and the check line.

No hou, no pxr: ``apps/houdini/publish_preview.py`` reads the files and the stage and builds the nodes.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
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


# --- the check line -------------------------------------------------------------------------------------------

@dataclass
class FileFacts:
    """What one publish file says by itself (read with pxr from the file, not from the loader's stage)."""

    name: str
    meshes: int = 0
    no_scheme: list[str] = field(default_factory=list)   # meshes without an authored subdivisionScheme
    fps: float | None = None                             # framesPerSecond (else timeCodesPerSecond) if authored
    kind: str = ""                                       # the default prim's kind
    default_prim: str = ""
    animated: int = 0                                    # meshes / xforms / cameras with time samples
    camera: bool = False
    error: str = ""


@dataclass
class StageFacts:
    """What the test scene's stage shows after the loader cooked."""

    meshes: int = 0
    broken: list[str] = field(default_factory=list)      # "prim -> target" of bindings to no Material
    node_errors: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def _n(count: int, word: str) -> str:
    if count == 1:
        return f"1 {word}"
    return f"{count} {word}{'es' if word.endswith(('sh', 'ch', 's')) else 's'}"


def problems(kind: str, files: list[FileFacts], stage: StageFacts) -> list[str]:
    """Everything lighting would trip over, worst first; empty when the publish reads clean."""
    out = list(stage.node_errors)
    for f in files:
        if f.error:
            out.append(f"{f.name}: {f.error}")
    if stage.broken:
        out.append(f"{_n(len(stage.broken), 'broken material binding')} ({stage.broken[0]})")
    if stage.meshes == 0 and not any(f.camera for f in files):
        out.append("no mesh in the stage")
    no_scheme = sum(len(f.no_scheme) for f in files)
    if no_scheme:
        first = next(f for f in files if f.no_scheme)
        where = f"{first.name} {first.no_scheme[0]}" if len(files) > 1 else first.no_scheme[0]
        out.append(f"{_n(no_scheme, 'mesh')} without subdivisionScheme ({where})")
    for f in files:
        if f.fps is None and not f.error:
            out.append(f"{f.name} has no fps")
    fps = {f.fps for f in files if f.fps is not None}
    if len(fps) > 1:
        out.append("files disagree on fps (" + ", ".join(f"{x:g}" for x in sorted(fps)) + ")")
    if kind == "model":
        for f in files:
            if not f.error and f.kind != "component":
                out.append(f"{f.name}: default prim {f.default_prim or '(none)'} is kind "
                           f"{f.kind or '(none)'}, not component")
    else:
        for f in files:
            if not f.error and f.animated == 0:
                out.append(f"{f.name} has no time samples")
    return out


def summary(kind: str, files: list[FileFacts], stage: StageFacts) -> str:
    """The facts that are fine, in one clause: meshes, fps, kind / animated files."""
    parts = [_n(stage.meshes, "mesh")]
    fps = sorted({f.fps for f in files if f.fps is not None})
    if len(fps) == 1:
        parts.append(f"{fps[0]:g} fps")
    if kind == "model":
        if files and all(f.kind == "component" for f in files):
            parts.append("kind component")
    else:
        moving = sum(1 for f in files if f.animated)
        parts.append(f"{moving} of {_n(len(files), 'file')} with time samples")
    return ", ".join(parts)


def check_line(title: str, kind: str, files: list[FileFacts], stage: StageFacts) -> tuple[str, bool]:
    """(the status bar line, ok). One line: Houdini's status bar, never a dialog."""
    probs = problems(kind, files, stage)
    if not probs:
        return f"MonoFX test, {title}: reads clean. {summary(kind, files, stage)}.", True
    shown = "; ".join(probs[:3]) + (f"; +{len(probs) - 3} more" if len(probs) > 3 else "")
    return f"MonoFX test, {title}: {_n(len(probs), 'problem')}: {shown}. {summary(kind, files, stage)}.", False


def note_text(title: str, kind: str, files: list[FileFacts], stage: StageFacts, plan_note: str = "") -> str:
    """The sticky note in /stage: every check, one a line."""
    probs = problems(kind, files, stage)
    lines = [f"MonoFX test: {title}", ""]
    lines += [f"PROBLEM  {p}" for p in probs] or ["Reads clean."]
    lines += ["", summary(kind, files, stage)]
    for f in files:
        bits = [_n(f.meshes, "mesh")]
        if f.fps is not None:
            bits.append(f"{f.fps:g} fps")
        if kind == "model":
            bits.append(f"kind {f.kind or '(none)'}")
        else:
            bits.append(f"{_n(f.animated, 'prim')} with time samples")
        lines.append(f"  {f.name}: " + ", ".join(bits))
    for b in stage.broken[:10]:
        lines.append(f"  broken binding {b}")
    lines += [f"  {n}" for n in stage.notes]
    if plan_note:
        lines.append(f"  {plan_note}")
    lines += ["", "This scene is not saved in the project; a save goes to %TEMP%\\MonoFX\\houdini_test."]
    return "\n".join(lines)


HDA_MISSING = (f"MonoFX test: the MonoFX Loader ({config.HDA_TYPE}) is not installed in this Houdini. "
               "Run MonoFXSuite_Setup.exe for this Houdini version.")
