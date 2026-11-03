"""Auto Material: SSS slots and updating a material built earlier, on fake hou nodes."""

from __future__ import annotations

from typing import Any

import pytest

from apps.houdini import solaris_adapter as sa
from tools.fx.auto_material.logic import SlotInfo, auto_parse, scan_and_group

# ---------------------------------------------------------------------------
# Fake hou nodes: only what solaris_adapter calls
# ---------------------------------------------------------------------------

SURFACE_DEFAULTS: dict[str, tuple] = {
    "base_color": (0.8, 0.8, 0.8),
    "metalness": (0.0,),
    "specular_roughness": (0.2,),
    "normal": (0.0, 0.0, 0.0),
    "opacity": (1.0, 1.0, 1.0),
    "emission_color": (1.0, 1.0, 1.0),
    "specular": (1.0,),
    "transmission": (0.0,),
    "subsurface": (0.0,),
    "subsurface_color": (1.0, 1.0, 1.0),
    "subsurface_radius": (1.0, 1.0, 1.0),
    "coat": (0.0,),
    "coat_color": (1.0, 1.0, 1.0),
    "coat_roughness": (0.1,),
    "coat_anisotropy": (0.0,),
    "coat_normal": (0.0, 0.0, 0.0),
}


class FakeParm:
    def __init__(self, name: str, value: Any = "", default: Any = None) -> None:
        self._name = name
        self.value = value
        self.default = value if default is None else default

    def name(self) -> str:
        return self._name

    def set(self, value: Any) -> None:
        self.value = value

    def eval(self) -> Any:
        return self.value

    def evalAsString(self) -> str:
        return str(self.value)

    def unexpandedString(self) -> str:
        return str(self.value)

    def isAtDefault(self) -> bool:
        return self.value == self.default


class FakeParmTuple:
    def __init__(self, parms: list[FakeParm]) -> None:
        self.parms = parms

    def eval(self) -> tuple:
        return tuple(p.value for p in self.parms)

    def isAtDefault(self) -> bool:
        return all(p.isAtDefault() for p in self.parms)


class FakeType:
    def __init__(self, name: str) -> None:
        self._name = name

    def name(self) -> str:
        return self._name


class FakeNode:
    def __init__(self, type_name: str, name: str, parent: FakeNode | None = None) -> None:
        self._type = FakeType(type_name)
        self._name = name
        self.parent = parent
        self._children: list[FakeNode] = []
        self._parms: dict[str, FakeParm] = {}
        self._tuples: dict[str, list[str]] = {}
        self._user: dict[str, str] = {}
        self.input_names: list[str] = []
        self.inputs: dict[int, FakeNode] = {}
        self._outputs: list[FakeNode] = []
        self.pos = (0.0, 0.0)
        self._setup()

    def _setup(self) -> None:
        t = self._type.name()
        if t == "mtlximage":
            for n, v in (("file", ""), ("signature", "default"), ("filecolorspace", "")):
                self._parms[n] = FakeParm(n, v)
        elif t == "mtlxstandard_surface":
            self.input_names = list(SURFACE_DEFAULTS)
            for n, values in SURFACE_DEFAULTS.items():
                if len(values) == 1:
                    self._parms[n] = FakeParm(n, values[0])
                    self._tuples[n] = [n]
                else:
                    names = [f"{n}{c}" for c in "rgb"]
                    for pn, v in zip(names, values):
                        self._parms[pn] = FakeParm(pn, v)
                    self._tuples[n] = names
        elif t == "mtlxnormalmap":
            self.input_names = ["in"]
        elif t == "assignmaterial":
            self._parms["nummaterials"] = FakeParm("nummaterials", 0)

    # --- hou.Node API ---
    def name(self) -> str:
        return self._name

    def type(self) -> FakeType:
        return self._type

    def children(self) -> list[FakeNode]:
        return list(self._children)

    def node(self, name: str) -> FakeNode | None:
        return next((c for c in self._children if c.name() == name), None)

    def createNode(self, type_name: str, node_name: str | None = None) -> FakeNode:
        base = node_name or f"{type_name}1"
        name, i = base, 1
        while self.node(name) is not None:  # Houdini makes the name unique
            name = f"{base}{i}"
            i += 1
        child = FakeNode(type_name, name, self)
        self._children.append(child)
        return child

    def parm(self, name: str) -> FakeParm | None:
        if self._type.name() == "assignmaterial" and name[-1:].isdigit() and name not in self._parms:
            idx = int("".join(ch for ch in name if ch.isdigit()))
            if idx <= int(self._parms["nummaterials"].value) and name.rstrip("0123456789") in (
                "primpattern", "matspecpath",
            ):
                self._parms[name] = FakeParm(name, "")
        return self._parms.get(name)

    def parms(self) -> list[FakeParm]:
        return list(self._parms.values())

    def parmTuple(self, name: str) -> FakeParmTuple | None:
        names = self._tuples.get(name)
        return FakeParmTuple([self._parms[n] for n in names]) if names else None

    def setParms(self, values: dict) -> None:
        for k, v in values.items():
            self._parms[k].set(v)

    def userData(self, key: str) -> str | None:
        return self._user.get(key)

    def setUserData(self, key: str, value: str) -> None:
        self._user[key] = value

    def inputIndex(self, name: str) -> int:
        return self.input_names.index(name) if name in self.input_names else -1

    def input(self, idx: int) -> FakeNode | None:
        return self.inputs.get(idx)

    def setInput(self, idx: int, node: FakeNode | None, out: int = 0) -> None:
        if node is None:
            self.inputs.pop(idx, None)
            return
        self.inputs[idx] = node
        node._outputs.append(self)

    def setNamedInput(self, name: str, node: FakeNode, out: str) -> None:
        self.setInput(self.inputIndex(name), node)

    def setNextInput(self, node: FakeNode) -> None:
        self.setInput(len(self.inputs), node)

    def outputs(self) -> list[FakeNode]:
        return list(self._outputs)

    def moveToGoodPosition(self) -> None:
        pass

    def position(self) -> tuple[float, float]:
        return self.pos

    def setPosition(self, pos: tuple[float, float]) -> None:
        self.pos = tuple(pos)

    def layoutChildren(self) -> None:
        pass

    # --- test helpers ---
    def connected(self, input_name: str) -> FakeNode | None:
        return self.inputs.get(self.inputIndex(input_name))


def _slots(version: str, names: list[str]) -> dict[str, SlotInfo]:
    out = {}
    for n in names:
        r = auto_parse(f"/publish/{version}/textures/M_char_Body_{n}.1001.png")
        assert r is not None, n
        out[r.slot] = SlotInfo(filepath=f"/publish/{version}/textures/M_char_Body_{n}.<UDIM>.png",
                               colorspace=r.colorspace, udim=True)
    return out


@pytest.fixture
def stage() -> FakeNode:
    return FakeNode("lopnet", "stage")


def _builder(stage: FakeNode) -> FakeNode:
    return stage.node("materiallibrary1").node("M_char_Body")


def _surface(builder: FakeNode) -> FakeNode:
    return next(c for c in builder.children() if c.type().name() == "mtlxstandard_surface")


def _image(builder: FakeNode, slot: str) -> FakeNode:
    return sa.find_image_node(builder, slot)


def test_scan_writes_the_usd_udim_token(tmp_path) -> None:
    tex = tmp_path / "textures"
    tex.mkdir()
    for tile in (1001, 1002):
        (tex / f"M_char_Body_BaseColor_sRGB.{tile}.exr").write_bytes(b"")
    groups, _ = scan_and_group(str(tex))
    path = groups["M_char_Body"].slots["base_color"].filepath
    assert path.endswith("M_char_Body_BaseColor_sRGB.<UDIM>.exr") and "%(UDIM)d" not in path


def test_update_moves_old_houdini_udim_token_to_usd_token(stage: FakeNode) -> None:
    # A material built before the switch: the tool set and recorded Houdini's %(UDIM)d.
    old = {k: SlotInfo(v.filepath.replace("<UDIM>", "%(UDIM)d"), v.colorspace, True)
           for k, v in _slots("v001", ["BaseColor_sRGB"]).items()}
    sa.build_material(stage, "M_char_Body", old)
    assert _image(_builder(stage), "base_color").parm("file").eval().endswith(".%(UDIM)d.png")
    sa.build_material(stage, "M_char_Body", _slots("v001", ["BaseColor_sRGB"]))
    assert _image(_builder(stage), "base_color").parm("file").eval().endswith("M_char_Body_BaseColor_sRGB.<UDIM>.png")


# ---------------------------------------------------------------------------
# SSS names
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("filename", "slot"),
    [
        ("M_char_Body_SubsurfaceWeight_Raw.1001.png", "subsurface"),
        ("M_char_Body_Subsurface_Raw.1001.png", "subsurface"),
        ("M_char_Body_SSS_Raw.1001.png", "subsurface"),
        ("M_char_Body_SssWeight_Raw.1001.png", "subsurface"),
        ("M_char_Body_SubsurfaceColor_sRGB.1001.png", "subsurface_color"),
        ("M_char_Body_SSSColor_sRGB.1001.png", "subsurface_color"),
        ("M_char_Body_SubsurfaceRadius_Raw.1001.png", "subsurface_radius"),
        ("M_char_Body_SssRadius_Raw.1001.png", "subsurface_radius"),
        ("body_sss.png", "subsurface"),
        ("body_subsurface_4k.png", "subsurface"),
        ("body_ssscolor.png", "subsurface_color"),
        ("body_SubsurfaceRadius.png", "subsurface_radius"),
    ],
)
def test_sss_names(filename: str, slot: str) -> None:
    r = auto_parse(filename)
    assert r is not None
    assert r.slot == slot


def test_sss_tokens() -> None:
    assert sa.colorspace_token_for_slot("subsurface_color", None) == "srgb_texture"
    assert sa.colorspace_token_for_slot("subsurface", None) == "Raw"
    assert sa.colorspace_token_for_slot("subsurface_radius", None) == "Raw"


# ---------------------------------------------------------------------------
# Create, then update
# ---------------------------------------------------------------------------

def test_first_build_wires_sss_and_tags_images(stage: FakeNode) -> None:
    res = sa.build_material(stage, "M_char_Body", _slots("v001", [
        "BaseColor_ACEScg", "SubsurfaceWeight_Raw", "SubsurfaceColor_sRGB",
    ]))
    assert res is not None and not res.updated
    assert res.path == "/materials/M_char_Body"
    b = _builder(stage)
    surface = _surface(b)
    for slot in ("base_color", "subsurface", "subsurface_color"):
        img = _image(b, slot)
        assert img.userData(sa.SLOT_TAG) == slot
        assert surface.connected(sa.SURFACE_INPUT_MAP[slot]) is img
    assert _image(b, "base_color").parm("filecolorspace").eval() == "ACEScg"


def test_sss_color_without_weight_sets_weight_to_one(stage: FakeNode) -> None:
    res = sa.build_material(stage, "M_char_Body", _slots("v001", ["BaseColor_sRGB", "SubsurfaceColor_sRGB"]))
    assert _surface(_builder(stage)).parm("subsurface").eval() == 1.0
    assert any(n.startswith("subsurface: set to 1") for n in res.notes)


def test_update_keeps_user_edits_and_adds_new_map(stage: FakeNode) -> None:
    sa.build_material(stage, "M_char_Body", _slots("v001", [
        "BaseColor_sRGB", "Roughness_Raw", "Metallic_Raw", "Specular_Raw",
    ]))
    b = _builder(stage)
    surface = _surface(b)
    user_node = b.createNode("mtlxconstant", "my_tweak")
    # The user: sets roughness's colour space by hand, unplugs metallic, gives SSS a value.
    _image(b, "roughness").parm("filecolorspace").set("srgb_texture")
    surface.setInput(surface.inputIndex("metalness"), None)
    surface.parm("subsurface").set(0.3)

    res = sa.build_material(stage, "M_char_Body", _slots("v002", [
        "BaseColor_sRGB", "Roughness_Raw", "Metallic_Raw", "SubsurfaceWeight_Raw",
    ]))
    assert res is not None and res.updated
    assert [c.name() for c in stage.node("materiallibrary1").children()] == ["M_char_Body"]

    assert "v002" in _image(b, "base_color").parm("file").eval()
    rough = _image(b, "roughness")
    assert "v002" in rough.parm("file").eval()
    assert rough.parm("filecolorspace").eval() == "srgb_texture"
    assert "roughness: kept the colour space set by hand (srgb_texture)" in res.notes
    metal = _image(b, "metallic")
    assert "v002" in metal.parm("file").eval()
    assert surface.connected("metalness") is None  # unplugged by the user, stays unplugged
    assert b.node("my_tweak") is user_node

    sss = _image(b, "subsurface")
    assert surface.connected("subsurface") is sss
    assert "subsurface: new map, wired to subsurface" in res.notes
    assert "subsurface: the map replaces the value (0.3)" in res.notes
    assert "specular: not in this publish, node kept" in res.notes
    assert _image(b, "specular") is not None


def test_update_does_not_wire_into_a_used_input(stage: FakeNode) -> None:
    sa.build_material(stage, "M_char_Body", _slots("v001", ["BaseColor_sRGB"]))
    b = _builder(stage)
    surface = _surface(b)
    own = b.createNode("mtlxconstant", "my_sss")
    surface.setNamedInput("subsurface", own, "out")

    res = sa.build_material(stage, "M_char_Body", _slots("v002", ["BaseColor_sRGB", "SSS_Raw"]))
    assert surface.connected("subsurface") is own
    assert _image(b, "subsurface") is not None
    assert "subsurface: new map, image node added, not wired (subsurface is already connected)" in res.notes


def test_update_keeps_a_file_set_by_hand(stage: FakeNode) -> None:
    sa.build_material(stage, "M_char_Body", _slots("v001", ["BaseColor_sRGB"]))
    img = _image(_builder(stage), "base_color")
    img.parm("file").set("/my/own/paint.exr")
    res = sa.build_material(stage, "M_char_Body", _slots("v002", ["BaseColor_sRGB"]))
    assert img.parm("file").eval() == "/my/own/paint.exr"
    assert "base_color: kept the file set by hand (/my/own/paint.exr)" in res.notes


def test_update_material_built_before_tags(stage: FakeNode) -> None:
    sa.build_material(stage, "M_char_Body", _slots("v001", ["BaseColor_sRGB"]))
    img = _image(_builder(stage), "base_color")
    img._user.clear()  # as built by the tool before it tagged nodes
    res = sa.build_material(stage, "M_char_Body", _slots("v002", ["BaseColor_ACEScg"]))
    assert "v002" in img.parm("file").eval()
    assert img.parm("filecolorspace").eval() == "ACEScg"
    assert img.userData(sa.SLOT_TAG) == "base_color"
    assert res.notes == []


def test_layout_places_only_new_builders(stage: FakeNode) -> None:
    lib = stage.createNode("materiallibrary", "materiallibrary1")
    old = lib.createNode("subnet", "M_char_Zed")
    old.setPosition((5.0, 2.0))
    new = lib.createNode("subnet", "M_char_Arm")
    sa.layout_material_library(lib, new_names=["M_char_Arm"])
    assert old.position() == (5.0, 2.0)
    assert new.position() == (5.0, 2.0 - 1.8)


# ---------------------------------------------------------------------------
# Auto assign
# ---------------------------------------------------------------------------

def test_merge_assign_keeps_entries_and_adds_new() -> None:
    node = FakeNode("assignmaterial", "assign_material_auto")
    sa._set_assign_count(node, 1)
    sa._set_assign_entry(node, 1, "/world/geo/Body_grp", "/materials/M_char_Body_custom")
    added = sa.merge_assign_material(node, [
        ("/world/geo/Body_grp", "/materials/M_char_Body"),
        ("/world/geo/Eye_grp", "/materials/M_char_Eye"),
    ])
    assert added == [("/world/geo/Eye_grp", "/materials/M_char_Eye")]
    assert node.parm("nummaterials").eval() == 2
    assert node.parm("matspecpath1").eval() == "/materials/M_char_Body_custom"
    assert node.parm("primpattern2").eval() == "/world/geo/Eye_grp"
    assert node.parm("matspecpath2").eval() == "/materials/M_char_Eye"


# ---------------------------------------------------------------------------
# Coat (Painter OpenPBR channels)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("filename", "slot"),
    [
        ("armor_CoatWeight_Raw.1001.png", "coat"),
        ("armor_CoatOpacity_Raw.1001.png", "coat"),
        ("armor_Clearcoat_Raw.1001.png", "coat"),
        ("armor_CoatColor_sRGB.1001.png", "coat_color"),
        ("armor_CoatRoughness_Raw.1001.png", "coat_roughness"),
        ("armor_CoatRoughnessAnisotropy_Raw.1001.png", "coat_anisotropy"),
        ("armor_CoatNormal_Raw.1001.png", "coat_normal"),
        ("armor_Normal_Raw.1001.png", "normal"),
        ("armor_clearcoat.png", "coat"),
        ("armor_coatnormal_4k.png", "coat_normal"),
    ],
)
def test_coat_names(filename: str, slot: str) -> None:
    r = auto_parse(filename)
    assert r is not None
    assert r.slot == slot
    if r.parse_mode == "pipeline":
        assert r.prefix == "armor"


def test_coat_tokens() -> None:
    assert sa.colorspace_token_for_slot("coat_color", None) == "srgb_texture"
    assert sa.colorspace_token_for_slot("coat_color", "ACEScg") == "ACEScg"
    for slot in ("coat", "coat_roughness", "coat_anisotropy", "coat_normal"):
        assert sa.colorspace_token_for_slot(slot, None) == "Raw"


def _normal_map_feeding(surface: FakeNode, input_name: str) -> FakeNode:
    nrm = surface.connected(input_name)
    assert nrm is not None and nrm.type().name() == "mtlxnormalmap"
    return nrm


def test_first_build_wires_coat(stage: FakeNode) -> None:
    res = sa.build_material(stage, "M_char_Body", _slots("v001", [
        "BaseColor_sRGB", "Normal_Raw", "CoatWeight_Raw", "CoatColor_sRGB", "CoatRoughness_Raw", "CoatNormal_Raw",
    ]))
    assert res is not None and res.notes == []
    b = _builder(stage)
    surface = _surface(b)
    for slot in ("coat", "coat_color", "coat_roughness"):
        assert surface.connected(sa.SURFACE_INPUT_MAP[slot]) is _image(b, slot)
    assert _image(b, "coat_color").parm("filecolorspace").eval() == "srgb_texture"
    assert _image(b, "coat_normal").parm("signature").eval() == "vector3"

    base_nrm = _normal_map_feeding(surface, "normal")
    coat_nrm = _normal_map_feeding(surface, "coat_normal")
    assert base_nrm is not coat_nrm
    assert coat_nrm.name() == "mtlxnormalmap_coat_normal"
    assert coat_nrm.connected("in") is _image(b, "coat_normal")
    assert base_nrm.connected("in") is _image(b, "normal")


def test_coat_maps_without_weight_are_reported(stage: FakeNode) -> None:
    res = sa.build_material(stage, "M_char_Body", _slots("v001", ["BaseColor_sRGB", "CoatRoughness_Raw"]))
    assert any(n.startswith("coat: no CoatWeight map") for n in res.notes)


def test_update_adds_coat_and_keeps_edits(stage: FakeNode) -> None:
    sa.build_material(stage, "M_char_Body", _slots("v001", ["BaseColor_sRGB", "Normal_Raw"]))
    b = _builder(stage)
    surface = _surface(b)
    surface.parm("coat_roughness").set(0.05)  # set by hand
    own = b.createNode("mtlxconstant", "my_coat_color")
    surface.setNamedInput("coat_color", own, "out")

    res = sa.build_material(stage, "M_char_Body", _slots("v002", [
        "BaseColor_sRGB", "Normal_Raw", "CoatWeight_Raw", "CoatColor_sRGB", "CoatRoughness_Raw", "CoatNormal_Raw",
    ]))
    assert res.updated
    assert surface.connected("coat") is _image(b, "coat")
    assert surface.connected("coat_color") is own
    assert "coat_color: new map, image node added, not wired (coat_color is already connected)" in res.notes
    assert surface.connected("coat_roughness") is _image(b, "coat_roughness")
    assert "coat_roughness: the map replaces the value (0.05)" in res.notes
    coat_nrm = _normal_map_feeding(surface, "coat_normal")
    assert coat_nrm.connected("in") is _image(b, "coat_normal")
    assert "coat_normal: new map, wired to coat_normal" in res.notes
    assert "v002" in _image(b, "normal").parm("file").eval()


def test_aces_exr_publish_builds_acescg_images(stage: FakeNode, tmp_path) -> None:
    tex = tmp_path / "publish" / "v001" / "textures"
    tex.mkdir(parents=True)
    for name in ("BaseColor_ACEScg.1001.exr", "EmissionColor_ACEScg.1001.exr", "Metallic_Raw.1001.png",
                 "Displacement_Raw.1001.exr", "CoatColor_sRGB.1001.png"):
        (tex / f"M_char_Body_{name}").write_bytes(b"")
    groups, unmatched = scan_and_group(str(tmp_path / "publish"))
    assert unmatched == []
    sa.build_material(stage, "M_char_Body", groups["M_char_Body"].slots)
    b = _builder(stage)
    assert _image(b, "base_color").parm("filecolorspace").eval() == "ACEScg"
    assert _image(b, "base_color").parm("file").eval().endswith("M_char_Body_BaseColor_ACEScg.<UDIM>.exr")
    assert _image(b, "emission_color").parm("filecolorspace").eval() == "ACEScg"
    assert _image(b, "metallic").parm("filecolorspace").eval() == "Raw"
    assert _image(b, "displacement").parm("filecolorspace").eval() == "Raw"
    assert _image(b, "coat_color").parm("filecolorspace").eval() == "srgb_texture"
