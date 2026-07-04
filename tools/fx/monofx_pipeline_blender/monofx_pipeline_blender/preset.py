"""
Hierarchy preset: JSON + Blender PropertyGroup / UIList.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

import bpy
from bpy.props import BoolProperty, CollectionProperty, IntProperty, StringProperty

from . import config


@dataclass
class HierarchyPresetNode:
    name: str
    parent: str
    match_keywords: str
    is_leaf: bool = False


@dataclass
class HierarchyPreset:
    name: str
    nodes: List[HierarchyPresetNode]


def parse_keywords(raw: str) -> List[str]:
    out: List[str] = []
    for part in (raw or "").split(","):
        t = part.strip().lower()
        if t:
            out.append(t)
    return out


def load_preset_from_json(path: Path) -> HierarchyPreset:
    data = json.loads(path.read_text(encoding="utf-8"))
    nodes = [
        HierarchyPresetNode(
            name=n["name"],
            parent=n.get("parent", "") or "",
            match_keywords=n.get("match_keywords", "") or "",
            is_leaf=bool(n.get("is_leaf", False)),
        )
        for n in data.get("nodes", [])
    ]
    return HierarchyPreset(name=data.get("name", path.stem), nodes=nodes)


def save_preset_to_json(preset: HierarchyPreset, path: Path) -> None:
    payload = {
        "name": preset.name,
        "nodes": [
            {
                "name": n.name,
                "parent": n.parent,
                "match_keywords": n.match_keywords,
                "is_leaf": n.is_leaf,
            }
            for n in preset.nodes
        ],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def default_preset_json_path() -> Path:
    return config.DEFAULT_PRESET_JSON


def load_default_character_preset() -> HierarchyPreset:
    return load_preset_from_json(default_preset_json_path())


def reload_default_character_preset(props: bpy.types.PropertyGroup) -> Path:
    """Load default JSON into scene preset list and overwrite the file on disk."""
    path = default_preset_json_path()
    preset = load_preset_from_json(path)
    apply_preset_to_scene_nodes(props, preset)
    save_preset_to_json(preset, path)
    return path


def preset_from_scene_nodes(props: bpy.types.PropertyGroup) -> HierarchyPreset:
    nodes: List[HierarchyPresetNode] = []
    for item in props.preset_nodes:
        nodes.append(
            HierarchyPresetNode(
                name=item.empty_name,
                parent=item.parent_name or "",
                match_keywords=item.match_keywords or "",
                is_leaf=bool(item.is_leaf),
            )
        )
    return HierarchyPreset(name="scene", nodes=nodes)


def apply_preset_to_scene_nodes(props: bpy.types.PropertyGroup, preset: HierarchyPreset) -> None:
    props.preset_nodes.clear()
    for n in preset.nodes:
        item = props.preset_nodes.add()
        item.empty_name = n.name
        item.parent_name = n.parent
        item.match_keywords = n.match_keywords
        item.is_leaf = n.is_leaf
    props.preset_index = 0


def validate_preset_keywords(preset: HierarchyPreset) -> List[str]:
    warnings: List[str] = []
    for n in preset.nodes:
        if not n.is_leaf:
            continue
        for kw in parse_keywords(n.match_keywords):
            if kw in config.BANNED_AUTO_KEYWORDS:
                warnings.append(f"{n.name}: banned keyword '{kw}'")
    return warnings


class MonoFXPresetNodeItem(bpy.types.PropertyGroup):
    empty_name: StringProperty(name="Empty Name", default="")
    parent_name: StringProperty(name="Parent", default="")
    match_keywords: StringProperty(
        name="Match Keywords",
        description="Comma-separated tokens matched against mesh name (after geo_ prefix stripped)",
        default="",
    )
    is_leaf: BoolProperty(
        name="Leaf Group",
        description="Receive auto-parented meshes; used for material assignment",
        default=False,
    )


class MONOFX_UL_preset_nodes(bpy.types.UIList):
    bl_idname = "MONOFX_UL_preset_nodes"

    def draw_item(
        self,
        context,
        layout,
        data,
        item,
        icon,
        active_data,
        active_propname,
        index,
        flt_flag,
    ):
        if self.layout_type in {"DEFAULT", "COMPACT"}:
            row = layout.row(align=True)
            row.prop(item, "empty_name", text="", emboss=False)
            if item.is_leaf:
                row.label(text="", icon="OUTLINER_OB_MESH")
        elif self.layout_type == "GRID":
            layout.alignment = "CENTER"
            layout.label(text=item.empty_name or "?")


def init_scene_preset_if_empty(props) -> None:
    if len(props.preset_nodes) > 0:
        return
    apply_preset_to_scene_nodes(props, load_default_character_preset())
