"""Fake groom and cloth caches for the real shot sh025 (Helen, anim v005), at full-ish size.

hython tools/fx/anim_loader/dev/make_fake_sh025_fx.py

Writes only ``02_fx/{groom,cloth}/publish/v900/char_Helen/`` of sh025 (the place the user chose,
2026-11-17), each with ``_FAKE_README.txt``. v900 keeps v001 free for the first real publish.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))
from tools.fx.anim_loader.dev import fake_usd as fu  # noqa: E402

SHOT = Path("D:/Dropbox/Job/260826_grn_vp97/02_shots/sh025")
ANIM = SHOT / "01_anim/publish/v005/geo_char_Helen.usd"
FPS = 30.0
FRAMES = range(0, 46)
STRANDS = 20000  # x 8 points; ~4 MB a frame, kept small because the folder syncs through Dropbox
HAIR = ["/Geo/Groom_grp/HairDriver_grp/Geo_HairBase", "/Geo/Groom_grp/HairDriver_grp/Geo_HairBang"]
CLOTH = ["/Geo/Outfit_grp/Costume_grp/Geo_Dress", "/Geo/Outfit_grp/Costume_grp/Geo_DressSide"]


def main() -> None:
    t = time.time()
    g = SHOT / "02_fx/groom/publish/v900/char_Helen"
    c = SHOT / "02_fx/cloth/publish/v900/char_Helen"
    for folder in (g, c):
        if folder.exists() and any(f.name != "_FAKE_README.txt" and not f.name.startswith("sh025_")
                                   for f in folder.iterdir()):
            raise SystemExit(f"{folder} holds files this script did not write; stopping")
    fu.write_groom_frames(ANIM, HAIR, g, "sh025", FRAMES, FPS, strands=STRANDS)
    fu.write_cloth_frames(ANIM, CLOTH, c, "sh025", FRAMES, FPS)
    size = sum(f.stat().st_size for f in (*g.iterdir(), *c.iterdir())) / 1e6
    print(f"sh025 fake fx: {len(FRAMES)} frames, {size:.0f} MB, {time.time() - t:.1f} s")


if __name__ == "__main__":
    main()
