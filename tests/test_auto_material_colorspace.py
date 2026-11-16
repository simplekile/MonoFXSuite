"""Auto Material: fill empty mtlximage colorspace from the texture filename (no Houdini runtime)."""

from __future__ import annotations

import pytest

from apps.houdini import solaris_adapter as sa
from tools.fx.auto_material.logic import colorspace_from_filename


@pytest.mark.parametrize(
    "path, expected",
    [
        ("tex/char_Helen_texturing_v010_textures/M_char_Head_Color_ACEScg.<UDIM>.exr", "ACEScg"),
        ("M_char_Head_Roughness_Raw.<UDIM>.exr", "Raw"),
        ("M_char_Head_Color_ACEScg.1001.exr", "ACEScg"),
        ("M_char_Head_Color_ACEScg.%(UDIM)d.exr", "ACEScg"),
        ("D:\\tex\\M_char_Head_Normal_Raw.<UDIM>.exr", "Raw"),
        ("M_char_Head_Color_ACEScg.exr", "ACEScg"),
        ("single.exr", None),
        ("", None),
    ],
)
def test_colorspace_from_filename(path, expected):
    assert colorspace_from_filename(path) == expected


class _Parm:
    def __init__(self, value):
        self.value = value

    def eval(self):
        return self.value

    def set(self, value):
        self.value = value


class _Type:
    def __init__(self, name):
        self._name = name

    def name(self):
        return self._name


class _Node:
    def __init__(self, name, type_name="mtlximage", file="", colorspace=""):
        self._name = name
        self._type = _Type(type_name)
        self._parms = {"file": _Parm(file), "filecolorspace": _Parm(colorspace)}
        self._children = []

    def name(self):
        return self._name

    def type(self):
        return self._type

    def parm(self, name):
        return self._parms.get(name)

    def setParms(self, mapping):
        for k, v in mapping.items():
            self._parms[k].set(v)

    def allSubChildren(self):
        return list(self._children)

    @property
    def colorspace(self):
        return self._parms["filecolorspace"].value


def _lib(*nodes):
    root = _Node("lib", type_name="materiallibrary")
    root._children = list(nodes)
    return root


def test_fix_sets_empty_from_suffix():
    color = _Node("baseColor_image", file="x/M_Head_Color_ACEScg.<UDIM>.exr")
    rough = _Node("specularRoughness_image", file="x/M_Head_Roughness_Raw.<UDIM>.exr")
    result = sa.fix_empty_texture_colorspaces(_lib(color, rough))
    assert color.colorspace == "ACEScg"
    assert rough.colorspace == "Raw"
    assert result["fixed"] == 2
    assert result["unresolved"] == []


def test_fix_never_overwrites_existing_value():
    keep = _Node("tex_coat_color", file="x/M_Head_CoatColor_ACEScg.<UDIM>.exr", colorspace="srgb_texture")
    result = sa.fix_empty_texture_colorspaces(_lib(keep))
    assert keep.colorspace == "srgb_texture"
    assert result["fixed"] == 0
    assert result["already_set"] == 1


def test_fix_reports_unresolvable_and_leaves_them_empty():
    odd = _Node("mystery_image", file="x/mystery.exr")
    result = sa.fix_empty_texture_colorspaces(_lib(odd))
    assert odd.colorspace == ""
    assert result["fixed"] == 0
    assert result["unresolved"] == ["mystery_image"]


def test_fix_ignores_non_image_nodes():
    other = _Node("standard_surface", type_name="mtlxstandard_surface")
    result = sa.fix_empty_texture_colorspaces(_lib(other))
    assert result == {"fixed": 0, "already_set": 0, "unresolved": []}
