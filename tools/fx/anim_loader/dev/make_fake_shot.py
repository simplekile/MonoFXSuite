"""Fake project with shot ``sh900`` for the Mono Anim Loader naming cases (clones, asset names with digits).

hython tools/fx/anim_loader/dev/make_fake_shot.py "E:/01 Dev/sandbox/claude/anim_loader/fake_project"

Plan Task 4. Anim v001 is old style (meta without asset), v002 new style (``_instNN`` + asset/instance in
meta). Groom v001 has a time sample at each file's frame, groom v002 default values only.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))
from tools.fx.anim_loader.dev import fake_usd as fu  # noqa: E402

FPS = 24.0
FRAMES = range(1, 25)
ASSETS = {"char_Robot": "_characters", "char_Robot_2": "_characters", "prop_CoralSet_001": "_props"}
COLORS = {"char_Robot": (0.8, 0.2, 0.2), "char_Robot_2": (0.2, 0.3, 0.9), "prop_CoralSet_001": (0.9, 0.6, 0.2)}
BODY = "/Geo/Base_grp/Body_grp/Geo_Body"


def _meta(folder: Path, outputs: list[dict]) -> None:
    data = {"fps": FPS, "playback_range": [FRAMES[0], FRAMES[-1]], "outputs": outputs}
    (folder / "publish_meta.json").write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def main(root: Path) -> None:
    if root.exists():
        shutil.rmtree(root)
    for asset, group in ASSETS.items():
        for v, k in (("v001", 0.5), ("v002", 1.0)):
            color = tuple(c * k for c in COLORS[asset])
            fu.write_lookdev(root / "01_assets" / group / asset / "05_lookdev/publish" / v /
                             f"{asset}_lookdev_publish.usd", asset, color, BODY)
    shot = root / "02_shots/sh900"
    anim = shot / "01_anim/publish"
    old = {"geo_char_Robot.usd": (0.0, 0.0), "geo_char_Robot_2.usd": (2.0, 1.0),
           "geo_prop_CoralSet_001.usd": (-2.0, 2.0)}
    for name, (off, ph) in old.items():
        fu.write_anim_geo(anim / "v001" / name, FPS, FRAMES, off, ph)
    fu.write_camera(anim / "v001/cam_sh900.usd", "sh900", FPS, FRAMES)
    _meta(anim / "v001", [{"file": n, "type": "geo"} for n in old] + [{"file": "cam_sh900.usd", "type": "cam"}])

    new = {"geo_char_Robot.usd": ("char_Robot", 1, 0.0, 0.0), "geo_char_Robot_inst02.usd": ("char_Robot", 2, 3.0, 1.5),
           "geo_char_Robot_2.usd": ("char_Robot_2", 1, -3.0, 0.7)}
    for name, (_, _, off, ph) in new.items():
        fu.write_anim_geo(anim / "v002" / name, FPS, FRAMES, off, ph)
    fu.write_camera(anim / "v002/cam_sh900.usd", "sh900", FPS, FRAMES)
    _meta(anim / "v002", [{"file": n, "type": "geo", "asset": a, "instance": i} for n, (a, i, _, _) in new.items()]
          + [{"file": "cam_sh900.usd", "type": "cam"}])

    groom = shot / "02_fx/groom/publish"
    drivers = ["/Geo/Groom_grp/HairDriver_grp/Geo_HairBase"]
    for v, ts in (("v001", True), ("v002", False)):
        fu.write_groom_frames(anim / "v002/geo_char_Robot.usd", drivers, groom / v / "char_Robot",
                              "sh900", FRAMES, FPS, strands=2000, timesample=ts)
        fu.write_groom_frames(anim / "v002/geo_char_Robot_inst02.usd", drivers, groom / v / "Robot_inst02",
                              "sh900", FRAMES, FPS, strands=2000, timesample=ts)
    fu.write_cloth_frames(anim / "v002/geo_char_Robot_2.usd", ["/Geo/Outfit_grp/Costume_grp/Geo_Dress"],
                          shot / "02_fx/cloth/publish/v001/char_Robot_2", "sh900", FRAMES, FPS)
    print("fake project", root, "files", sum(1 for _ in root.rglob("*") if _.is_file()))


if __name__ == "__main__":
    main(Path(sys.argv[1]))
