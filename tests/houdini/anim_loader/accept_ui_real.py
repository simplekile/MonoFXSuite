"""The manager window offscreen in hython with the real Houdini backend on sh025 v005 (read only on disk).

hython tests/houdini/anim_loader/accept_ui_real.py <out_dir>
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
if os.path.isdir(r"C:\Windows\Fonts"):
    os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
SUITE = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(SUITE))
OUT = Path(sys.argv[1])

import hou  # noqa: E402
from PySide6 import QtWidgets  # noqa: E402

from apps.houdini import anim_loader_adapter as ad  # noqa: E402
from tools.fx.anim_loader import ui  # noqa: E402

app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
hou.hda.installFile(str(SUITE / "otls/mono_anim_loader.hdalc"))
hou.setFps(30)
backend = ad.HoudiniBackend()
r = ad.load_shot(hou.node("/stage"), "D:/Dropbox/Job/260826_grn_vp97", "sh025", "v005")
print("load", r)
w = ui.AnimLoaderManager(backend)
w.resize(1100, 640)
w.wait()
for _ in range(40):  # thumbnails come in on the worker
    app.processEvents()
    import time
    time.sleep(0.05)
rows = w.ctl.rows()
print("rows", [(x.instance, {k: v[0] for k, v in x.parts.items()}, bool(x.thumb)) for x in rows])
print("headline", w.headline.text(), "|", w.primary.text())
for view in ("list", "grid"):
    w.set_view(view)
    w.grab()  # the first paint asks for the thumbnails; they load on a worker
    for _ in range(40):
        app.processEvents()
        time.sleep(0.05)
    w.grab().save(str(OUT / f"sh025_{view}.png"))
w.shot_box.setCurrentText("sh025")
print("versions offered", [w.version_box.itemText(i) for i in range(w.version_box.count())])
w.load_button.click()
print("second load:", w.result.text())
assert len(ad.find_loaders()) == 4, "Load shot again must create nothing"
print("DONE")
