"""Checks of a published USD, the same in Houdini and in Blender (Test in Houdini / Test in Blender).

``FileFacts`` comes from each publish file alone, ``StageFacts`` from what the test scene loaded. The line and
the note are plain text, no hou / bpy. ``file_facts`` and ``usd_stage_facts`` need pxr (both hosts ship it) and
import it only when called, so this module loads in pytest.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class FileFacts:
    """What one publish file says by itself (read with pxr from the file, not from the loaded scene)."""

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
    """What the test scene shows: Houdini's loaded stage, or in Blender the publish's own stage plus the import."""

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
    """(the status bar line, ok). One line on the host's status bar, never a dialog."""
    probs = problems(kind, files, stage)
    if not probs:
        return f"MonoFX test, {title}: reads clean. {summary(kind, files, stage)}.", True
    shown = "; ".join(probs[:3]) + (f"; +{len(probs) - 3} more" if len(probs) > 3 else "")
    return f"MonoFX test, {title}: {_n(len(probs), 'problem')}: {shown}. {summary(kind, files, stage)}.", False


def note_text(title: str, kind: str, files: list[FileFacts], stage: StageFacts, plan_note: str = "",
              save_hint: str = "") -> str:
    """Every check, one a line (Houdini's sticky note, Blender's text block)."""
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
    if save_hint:
        lines += ["", save_hint]
    return "\n".join(lines)


# --- pxr --------------------------------------------------------------------------------------------------------

def file_facts(path: str) -> FileFacts:
    """What the publish file says on its own: meshes, subdivisionScheme, fps, default prim kind, time samples."""
    from pxr import Usd, UsdGeom

    facts = FileFacts(Path(path).name)
    try:
        stage = Usd.Stage.Open(str(path), Usd.Stage.LoadAll)
    except Exception as exc:  # a file USD cannot open is the first thing to say
        facts.error = f"USD cannot open it ({str(exc).splitlines()[0][:120]})"
        return facts
    if stage is None:
        facts.error = "USD cannot open it"
        return facts
    layer = stage.GetRootLayer()
    if layer.HasFramesPerSecond():
        facts.fps = float(layer.framesPerSecond)
    elif layer.HasTimeCodesPerSecond():
        facts.fps = float(layer.timeCodesPerSecond)
    dp = stage.GetDefaultPrim()
    if dp:
        facts.default_prim = dp.GetPath().pathString
        facts.kind = Usd.ModelAPI(dp).GetKind() or ""
    for prim in stage.Traverse():
        if prim.IsA(UsdGeom.Mesh):
            facts.meshes += 1
            if not UsdGeom.Mesh(prim).GetSubdivisionSchemeAttr().HasAuthoredValue():
                facts.no_scheme.append(prim.GetPath().pathString)
        if prim.IsA(UsdGeom.Camera):
            facts.camera = True
        if prim.IsA(UsdGeom.Xformable) and any(a.GetNumTimeSamples() > 1 for a in prim.GetAttributes()):
            facts.animated += 1
    return facts


def broken_bindings(stage, prim) -> list[str]:
    """Direct material bindings (any purpose) of a prim that point at no Material."""
    from pxr import UsdShade

    bad = []
    for rel in prim.GetRelationships():
        name = rel.GetName()
        if not name.startswith("material:binding") or ":collection:" in name or name.endswith(":collection"):
            continue
        for target in rel.GetForwardedTargets():
            tp = stage.GetPrimAtPath(target)
            if not tp or not tp.IsA(UsdShade.Material):
                bad.append(f"{prim.GetPath()} -> {target}")
    return bad


def usd_stage_facts(stage, facts: StageFacts | None = None) -> StageFacts:
    """Meshes and bindings to no Material of a composed stage, added to ``facts``."""
    from pxr import UsdGeom

    facts = facts or StageFacts()
    if stage is None:
        return facts
    for prim in stage.Traverse():
        if prim.IsA(UsdGeom.Mesh):
            facts.meshes += 1
        facts.broken.extend(broken_bindings(stage, prim))
    return facts
