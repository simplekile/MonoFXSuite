"""
Work-file version description presets grouped by pipeline department.

Pure pathlib — no bpy imports.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

_DEPT_SEGMENT_RE = re.compile(r"^\d{2}_([a-z0-9]+)$", re.IGNORECASE)

# (id, label, tooltip, filename suffix — empty string = no description)
VersionDescPreset = tuple[str, str, str, str]

DEPARTMENT_ITEMS: tuple[tuple[str, str, str], ...] = (
    ("modelling", "Modelling", "Asset files under 01_modelling/..."),
    ("rigging", "Rigging", "Asset files under 02_rigging/..."),
    ("grooming", "Grooming", "Asset files under 04_grooming/..."),
    ("lookdev", "Lookdev", "Asset files under 05_lookdev/..."),
    ("anim", "Animation", "Shot files under 01_anim/..."),
    ("shot_fx", "Shot FX", "Shot files under 02_fx/..."),
    ("generic", "Other", "Files outside a known pipeline folder"),
)

# Static bpy EnumProperty items — must stay 3-tuples (id, name, description).
DEPARTMENT_ENUM_ITEMS: tuple[tuple[str, str, str], ...] = DEPARTMENT_ITEMS

_PRESETS_BY_DEPARTMENT: dict[str, tuple[VersionDescPreset, ...]] = {
    "modelling": (
        ("wip", "WIP", "Work in progress", "wip"),
        ("sculpt", "Sculpt", "Sculpt pass", "sculpt"),
        ("retopo", "Retopo", "Retopology pass", "retopo"),
        ("modelling", "Modelling", "Modelling update", "modelling"),
        ("uv", "UV", "UV layout pass", "uv"),
        ("baseMesh", "Base Mesh", "Base mesh pass", "baseMesh"),
        ("proxy", "Proxy", "Proxy mesh pass", "proxy"),
        ("cleanup", "Cleanup", "Mesh cleanup pass", "cleanup"),
        ("review", "Review", "Ready for review", "review"),
        ("final", "Final", "Final work file", "final"),
    ),
    "rigging": (
        ("wip", "WIP", "Work in progress", "wip"),
        ("buildRig", "Build Rig", "Rig build pass", "buildRig"),
        ("skinning", "Skinning", "Skinning pass", "skinning"),
        ("ctrlUpdate", "Control Update", "Control rig update", "ctrlUpdate"),
        ("matchPose", "Match Pose", "Match-pose pass", "matchPose"),
        ("deformTest", "Deform Test", "Deformation test pass", "deformTest"),
        ("rigTest", "Rig Test", "Rig functionality test", "rigTest"),
        ("polish", "Polish", "Rig polish pass", "polish"),
        ("review", "Review", "Ready for review", "review"),
        ("final", "Final", "Final work file", "final"),
    ),
    "grooming": (
        ("wip", "WIP", "Work in progress", "wip"),
        ("groomBlock", "Groom Block", "Groom blocking pass", "groomBlock"),
        ("guideSetup", "Guide Setup", "Guide setup pass", "guideSetup"),
        ("sim", "Simulation", "Groom simulation pass", "sim"),
        ("cache", "Cache", "Cached groom output", "cache"),
        ("renderTest", "Render Test", "Groom render test", "renderTest"),
        ("polish", "Polish", "Groom polish pass", "polish"),
        ("fix", "Fix", "Groom fix pass", "fix"),
        ("review", "Review", "Ready for review", "review"),
        ("final", "Final", "Final work file", "final"),
    ),
    "lookdev": (
        ("wip", "WIP", "Work in progress", "wip"),
        ("shader", "Shader", "Shader development pass", "shader"),
        ("texture", "Texture", "Texture pass", "texture"),
        ("lightRig", "Light Rig", "Lighting setup pass", "lightRig"),
        ("turntable", "Turntable", "Turntable lookdev pass", "turntable"),
        ("polish", "Polish", "Lookdev polish pass", "polish"),
        ("fix", "Fix", "Lookdev fix pass", "fix"),
        ("variant", "Variant", "Material variant pass", "variant"),
        ("review", "Review", "Ready for review", "review"),
        ("final", "Final", "Final work file", "final"),
    ),
    "anim": (
        ("wip", "WIP", "Work in progress", "wip"),
        ("layout", "Layout", "Layout pass", "layout"),
        ("layoutPass", "Layout Pass", "Layout blocking pass", "layoutPass"),
        ("blockedCam", "Blocked Cam", "Blocked camera pass", "blockedCam"),
        ("camUpdate", "Camera Update", "Camera update pass", "camUpdate"),
        ("animBlock", "Anim Block", "Animation blocking pass", "animBlock"),
        ("updateRig", "Update Rig", "Rig update pass", "updateRig"),
        ("spline", "Spline", "Spline animation pass", "spline"),
        ("review", "Review", "Ready for review", "review"),
        ("final", "Final", "Final work file", "final"),
    ),
    "shot_fx": (
        ("wip", "WIP", "Work in progress", "wip"),
        ("groom", "Groom", "Shot groom FX pass", "groom"),
        ("cloth", "Cloth", "Cloth simulation pass", "cloth"),
        ("sim", "Simulation", "FX simulation pass", "sim"),
        ("cache", "Cache", "Cached FX output", "cache"),
        ("rnd", "RND", "FX research pass", "rnd"),
        ("polish", "Polish", "FX polish pass", "polish"),
        ("fix", "Fix", "FX fix pass", "fix"),
        ("review", "Review", "Ready for review", "review"),
        ("final", "Final", "Final work file", "final"),
    ),
    "generic": (
        ("wip", "WIP", "Work in progress", "wip"),
        ("note", "Note", "General note", "note"),
        ("draft", "Draft", "Draft version", "draft"),
        ("update", "Update", "General update", "update"),
        ("fix", "Fix", "Fix pass", "fix"),
        ("polish", "Polish", "Polish pass", "polish"),
        ("temp", "Temp", "Temporary save", "temp"),
        ("backup", "Backup", "Backup save", "backup"),
        ("review", "Review", "Ready for review", "review"),
        ("final", "Final", "Final work file", "final"),
    ),
}

_DEFAULT_DEPARTMENT = "generic"


def department_ids() -> tuple[str, ...]:
    return tuple(item[0] for item in DEPARTMENT_ITEMS)


def department_label(dept_id: str) -> str:
    for did, label, _desc in DEPARTMENT_ITEMS:
        if did == dept_id:
            return label
    return dept_id


def presets_for_department(dept_id: str) -> tuple[VersionDescPreset, ...]:
    return _PRESETS_BY_DEPARTMENT.get(dept_id or _DEFAULT_DEPARTMENT, _PRESETS_BY_DEPARTMENT["generic"])


def description_for_preset(dept_id: str, preset_id: str) -> Optional[str]:
    if not preset_id or preset_id == "NONE":
        return ""
    for pid, _label, _tip, value in presets_for_department(dept_id):
        if pid == preset_id:
            return value
    return None


def match_preset_for_description(dept_id: str, description: str) -> str:
    desc = (description or "").strip()
    if not desc:
        return "NONE"
    for pid, _label, _tip, value in presets_for_department(dept_id):
        if value == desc:
            return pid
    return "NONE"


def detect_department_from_scene(scene_path: Path) -> str:
    """Infer pipeline department from a saved .blend path."""
    parts = list(scene_path.parts)
    low = [p.casefold() for p in parts]

    try:
        i_shots = low.index("02_shots")
        if i_shots + 2 < len(parts):
            for seg in parts[i_shots + 2 :]:
                m = _DEPT_SEGMENT_RE.match(seg)
                if not m:
                    continue
                code = m.group(1).casefold()
                if code == "anim":
                    return "anim"
                if code == "fx":
                    return "shot_fx"
    except ValueError:
        pass

    try:
        i_assets = low.index("01_assets")
        for seg in parts[i_assets + 3 :]:
            cf = seg.casefold()
            if cf == "01_modelling":
                return "modelling"
            if cf == "02_rigging":
                return "rigging"
            if cf == "04_grooming":
                return "grooming"
            if cf == "05_lookdev":
                return "lookdev"
    except ValueError:
        pass

    return _DEFAULT_DEPARTMENT
