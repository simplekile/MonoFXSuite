"""Mono Anim Loader 2.2 commands acceptance (plan Task 6): load shot, update, upgrade 2.1, set asset.

hython tests/houdini/anim_loader/accept_commands.py <fake_project> <out_dir>

Uses otls/mono_anim_loader.hdalc and, for the upgrade, the 2.1 library in Dropbox (read only).
"""

from __future__ import annotations

import json
import shutil
import sys
import traceback
from pathlib import Path

SUITE = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(SUITE))

import hou  # noqa: E402

from apps.houdini import anim_loader_adapter as ad  # noqa: E402
from tools.fx.anim_loader import config  # noqa: E402

ROOT = Path(sys.argv[1])
OUT = Path(sys.argv[2])
LIB_21 = "D:/Dropbox/Stock/Plugin/HOU/Mono/hda/lop_mono_anim_loader.2.1.hdalc"
CHECKS: list[dict] = []


def check(name, ok, detail=None):
    CHECKS.append({"name": name, "ok": bool(ok), "detail": detail})
    print(("PASS " if ok else "FAIL ") + name, "" if detail is None else detail, flush=True)


def accept_load_shot_twice(net):
    first = ad.load_shot(net, str(ROOT), "sh900", "v002")
    check("load creates 4", sorted(first.created) == ["char_Robot", "char_Robot_2", "char_Robot_inst02", "sh900"],
          str(first))
    merge = [n for n in net.children() if n.userData(config.MERGE_USER_DATA) == "sh900"]
    check("one merge for the shot", len(merge) == 1 and len(merge[0].inputs()) == 4)
    hou.node("/stage/char_Robot").setName("hero_robot")
    again = ad.load_shot(net, str(ROOT), "sh900", "v002")
    check("second load creates nothing", again.created == [] and len(again.kept) == 4, str(again))
    check("still one merge with 4 inputs", len(merge[0].inputs()) == 4)
    check("find_loaders sees 4", len(ad.find_loaders()) == 4)
    hou.setFrame(12)
    st = merge[0].stage()
    check("merge holds the three instances", all(st.GetPrimAtPath(f"/{n}") for n in
                                                  ("char_Robot", "char_Robot_inst02", "char_Robot_2")))


def accept_no_move(net):
    keep = net.createNode("null", "artist_null")
    keep.setPosition(hou.Vector2(-30, 40))
    before = {n.name(): tuple(n.position()) for n in net.children()}
    ad.load_shot(net, str(ROOT), "sh900", "v001")
    moved = [n for n, p in before.items() if net.node(n) is not None and tuple(net.node(n).position()) != p]
    check("existing nodes do not move", moved == [], moved)
    check("another version adds only what is new", len(ad.find_loaders()) == 5,
          sorted(n.name() for n in ad.find_loaders()))


def accept_load_ambiguous(net):
    from tools.fx.anim_loader.logic import Output

    side = net.createNode("lopnet", "side")
    node = ad.create_loader(side, str(ROOT), "sh900", "v001", Output("geo_char_Robot_2.usd", "geo"))
    check("ambiguous says asset?", "asset?" in node.evalParm(config.P_STATUS), node.evalParm(config.P_STATUS))
    ad.set_asset(node, "char_Robot")
    check("set_asset fills lookdev", "/char_Robot/05_lookdev/" in node.evalParm(config.P_PATH["lookdev"]),
          node.evalParm(config.P_PATH["lookdev"]))


def accept_update_one_undo(net):
    nodes = [n for n in ad.find_loaders() if n.evalParm(config.P_GEO_CAM) == 0][:3]
    for n in nodes:
        n.parm(config.P_VERSION["lookdev"]).set("v001")
        ad.refresh(n)
    lines = ad.update(nodes, ("lookdev",))
    check("update moves lookdev to v002", all(n.evalParm(config.P_VERSION["lookdev"]) == "v002" for n in nodes
                                              if n.evalParm(config.P_ASSET)), lines)
    hou.undos.performUndo()
    check("one undo takes it back", all(n.evalParm(config.P_VERSION["lookdev"]) == "v001" for n in nodes
                                        if n.evalParm(config.P_ASSET)))


def accept_upgrade_21(net):
    hou.hda.installFile(LIB_21)
    old = net.createNode("mono_anim_loader::2.1", "old_robot")
    anim = ROOT / "02_shots/sh900/01_anim/publish/v001/geo_char_Robot.usd"
    for k, v in (("mx_project_root", str(ROOT)), ("mx_shot", "sh900"), ("mx_anim_version", "v001"),
                 ("mx_anim_usd", anim.as_posix()), ("mx_lookdev_version", "v001")):
        old.parm(k).set(v)
    new = ad.upgrade([old])
    n = new[0]
    check("upgraded type", n.type().name() == config.HDA_TYPE)
    check("kept shot / version / lookdev", (n.evalParm("mx_shot"), n.evalParm("mx_anim_version"),
                                            n.evalParm(config.P_VERSION["lookdev"])) == ("sh900", "v001", "v001"))
    check("anim file is a name now", n.evalParm(config.P_ANIM_FILE) == "geo_char_Robot.usd")
    check("instance root", n.evalParm(config.P_INSTANCE) == "char_Robot")
    hou.setFrame(5)
    check("upgraded node loads under /char_Robot", bool(n.stage().GetPrimAtPath("/char_Robot/Geo")))


def accept_upgrade_21_defaults(net):
    old = net.createNode("mono_anim_loader::2.1", "old_defaults")
    anim = ROOT / "02_shots/sh900/01_anim/publish/v001/geo_prop_CoralSet_001.usd"
    for k, v in (("mx_project_root", str(ROOT)), ("mx_shot", "sh900"), ("mx_anim_usd", anim.as_posix())):
        old.parm(k).set(v)  # versions left at 2.1's "select version"
    n = ad.upgrade([old])[0]
    check("2.1 default versions become real ones", (n.evalParm("mx_anim_version"),
                                                    n.evalParm(config.P_VERSION["lookdev"])) == ("v001", "v002"),
          (n.evalParm("mx_anim_version"), n.evalParm(config.P_VERSION["lookdev"])))


def accept_asset_parm_picks_versions(net):
    from tools.fx.anim_loader.logic import Output

    side = net.node("side") or net.createNode("lopnet", "side")
    node = ad.create_loader(side, str(ROOT), "sh900", "v001", Output("geo_char_Robot_2.usd", "geo"))
    node.parm(config.P_ASSET).set("char_Robot")
    ad.cb_parm_changed({"node": node, "parm": node.parm(config.P_ASSET), "parm_name": config.P_ASSET})
    check("asset set on the parm picks lookdev", node.evalParm(config.P_VERSION["lookdev"]) == "v002",
          node.evalParm(config.P_STATUS))


def accept_heavy_shot(net):
    loads = dict(ad.shot_subd_load())
    check("subd load counted per loader", loads.get("hero_robot", 0) > 0 and loads.get("char_Robot_2", -1) >= 0,
          str(loads))
    check("small shot: no heavy message", ad.heavy_message() is None)
    ad.check_heavy_shot()  # no UI in hython: must do nothing and raise nothing
    check("no prompt without a UI", True)


def main():
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)
    hou.hda.installFile(str(SUITE / "otls/mono_anim_loader.hdalc"))
    hou.setFps(24)
    net = hou.node("/stage")
    for step in (accept_load_shot_twice, accept_no_move, accept_load_ambiguous, accept_update_one_undo,
                 accept_upgrade_21, accept_upgrade_21_defaults, accept_asset_parm_picks_versions,
                 accept_heavy_shot):
        try:
            step(net)
        except Exception:
            check(f"{step.__name__} ran", False, traceback.format_exc()[-1500:])


if __name__ == "__main__":
    main()
    (OUT / "accept.json").write_text(json.dumps(CHECKS, indent=2), encoding="utf-8")
    failed = [c["name"] for c in CHECKS if not c["ok"]]
    print(f"{len(CHECKS) - len(failed)}/{len(CHECKS)} passed", failed)
    sys.exit(1 if failed else 0)
