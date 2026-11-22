"""The Mono Solaris desktop: Houdini 22's Solaris layout with the MonoFX Loaders manager docked alone on the left,
as a Python Panel shipped at the suite root (the package hpath) by the installer."""

from __future__ import annotations

import ast
import os
import re
import xml.etree.ElementTree as ET

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DESK = os.path.join(ROOT, "desktop", "Mono_Solaris.desk")
PYPANEL = os.path.join(ROOT, "python_panels", "monofx_loader.pypanel")
UI = os.path.join(ROOT, "tools", "fx", "anim_loader", "ui.py")


def _read(path: str) -> str:
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def _ui_constants() -> dict:
    tree = ast.parse(_read(UI))
    out = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    out[t.id] = node.value.value
        if isinstance(node, ast.FunctionDef):
            out[node.name] = node
    return out


def test_pypanel_interface_calls_create_panel() -> None:
    consts = _ui_constants()
    doc = ET.fromstring(_read(PYPANEL))
    iface = doc.find("interface")
    assert iface.get("name") == consts["PYPANEL_NAME"]
    assert iface.get("label") == "MonoFX Loaders"
    script = iface.find("script").text
    assert "def onCreateInterface" in script and "ui.create_panel(" in script
    assert "create_panel" in consts and "open_manager" in consts   # the floating window stays


def test_desk_is_solaris_with_the_loader_alone_on_the_left() -> None:
    consts = _ui_constants()
    assert os.path.basename(DESK) == consts["DESK_NAME"] + ".desk"
    desk = _read(DESK)
    assert desk.count("{") == desk.count("}")
    root = desk[desk.index("root {"):]
    tabs = re.findall(r"tabs \d+ \d+ \{(.*?)\}", root, re.S)
    first = [line.strip() for line in tabs[0].strip().splitlines()]
    assert len(first) == 1 and "-m pythonpanel" in first[0] and "-T LOP" in first[0]
    pane = first[0].split()[1]
    assert f"pythonpanel -s on -t off -n {consts['PYPANEL_NAME']} {pane}\n" in desk
    assert root.index(pane) < root.index("-m sceneview") < root.index("-m neteditor")
    for kind in ("sceneview", "parmeditor", "neteditor", "details", "rendergallery"):   # Solaris's panes
        assert f"-m {kind}" in root
    names = re.findall(r"^\s*pane (\S+) ", root, re.M)
    assert len(names) == len(set(names))
    assert "/stage/motionblur" not in desk          # SideFX's saved network, not ours
    split = float(re.search(r"root \{\s*split ([\d.]+) H", root).group(1))
    assert 0.18 <= split <= 0.3                       # ~400-500 px on a 1920 px window: the narrow layout


def test_installer_ships_desktop_and_python_panels() -> None:
    with open(os.path.join(ROOT, "build", "installer", "MonoFXSuite.iss"), encoding="utf-8-sig") as fh:
        iss = fh.read()
    for folder in ("desktop", "python_panels"):
        assert f'Source: "..\\..\\{folder}\\*"; DestDir: "{{app}}\\{folder}"' in iss
