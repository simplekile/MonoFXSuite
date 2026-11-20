"""Every name the HDA calls through hou.phm() is exported by the adapter (its PythonModule does
`from apps.houdini.anim_loader_adapter import *`, which takes only __all__): v0.1.36 shipped a Reload button whose
callback, cb_reload, was missing from __all__, and every click raised AttributeError."""

from __future__ import annotations

import ast
import re
from pathlib import Path

SUITE = Path(__file__).resolve().parents[1]


def _adapter_all() -> set[str]:
    tree = ast.parse((SUITE / "apps/houdini/anim_loader_adapter.py").read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", "") == "__all__" for t in node.targets):
            return {elt.value for elt in node.value.elts}
    raise AssertionError("the adapter has no __all__")


def _adapter_defs() -> set[str]:
    tree = ast.parse((SUITE / "apps/houdini/anim_loader_adapter.py").read_text(encoding="utf-8"))
    return {n.name for n in tree.body if isinstance(n, (ast.FunctionDef, ast.ClassDef))}


def test_every_phm_call_of_the_hda_is_exported():
    src = (SUITE / "tools/fx/anim_loader/build_hda.py").read_text(encoding="utf-8")
    called = set(re.findall(r"hou\.phm\(\)\.(\w+)", src))
    assert called, "no hou.phm() call found: the check reads the wrong file"
    exported = _adapter_all()
    assert called <= exported, f"called by the HDA but not in __all__: {sorted(called - exported)}"
    assert exported <= _adapter_defs() | {"LoadResult"}, f"in __all__ but not defined: {sorted(exported - _adapter_defs())}"


def test_root_code_works_on_and_off():
    """Prim Name on / off (2026-11-20): every Python LOP starts with config.ROOT_CODE; the baked codes are %-formatted
    after it is put in, so it holds no "%"."""
    from tools.fx.anim_loader import config

    assert "%" not in config.ROOT_CODE

    class Parm:
        def __init__(self, v):
            self.v = v

        def eval(self):
            return self.v

    class Hda:
        def __init__(self, inst, use):
            self.inst, self.use = inst, use

        def evalParm(self, name):
            return self.inst

        def parm(self, name):
            return None if self.use is None else Parm(self.use)

        def node(self, name):
            return None

    for inst, use, want in (("char_A", 1, "/char_A"), ("char_A", 0, ""), ("", 1, None), ("char_A", None, "/char_A")):
        scope = {"hda": Hda(inst, use)}
        exec(config.ROOT_CODE, scope)
        assert scope["root"] == want, (inst, use)
