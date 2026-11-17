"""MonoFX Loaders manager layout A (the user's pick, 2026-11-17), offscreen with a fake backend: Add drawer, view bar,
what is new, Source, links, shot gaps, hand off."""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtWidgets = pytest.importorskip("PySide6.QtWidgets")

from tests.anim_loader_tree import make as make_tree  # noqa: E402
from tests.test_anim_loader_controller import FakeBackend  # noqa: E402
from tools.fx.anim_loader.logic import Output, WhatsNew  # noqa: E402


class BackendA(FakeBackend):
    def __init__(self):
        super().__init__()
        self.parts_on = {"lookdev": True, "groom": True}

    def extras(self, infos, root, shot):
        return {"news": {"/stage/a": [WhatsNew("lookdev", "v002", "v003", "2026-11-16 10:00", "Mai",
                                               ("+ 2 meshes: Fin_L, Fin_R", "1.0 MB -> 2.0 MB"))]},
                "weight": {"/stage/b": 2_100_000_000},
                "gaps": ("v006", [Output("geo_char_Ata.usd", "geo")])}

    def add_assets(self, root, names):
        self.calls.append(("add_assets", root, tuple(names)))
        return list(names), []

    def solo(self, paths):
        self.calls.append(("solo", tuple(paths)))
        return len(paths)

    def viewport_part_on(self, part):
        return self.parts_on[part]

    def set_viewport_part(self, part, on):
        self.calls.append(("viewport", part, on))
        self.parts_on[part] = on
        return 3

    def set_source(self, paths, source):
        self.calls.append(("source", tuple(paths), source))
        return len(paths)

    def frame(self, path):
        self.calls.append(("frame", path))
        return True

    def open_folder(self, path):
        self.calls.append(("folder", path))
        return True

    def open_monos(self, path):
        self.calls.append(("monos", path))
        return True

    def handoff(self, paths, out_dir):
        self.calls.append(("handoff", tuple(paths), out_dir))
        return [f"{p}: written" for p in paths]


@pytest.fixture(scope="module")
def app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


@pytest.fixture
def win(app, tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    import importlib

    from tools.fx.anim_loader import ui as ui_mod

    importlib.reload(ui_mod)
    w = ui_mod.AnimLoaderManager(BackendA())
    w.resize(1100, 700)
    w.ctl.target_shot, w.ctl.target_root = "sh025", str(tmp_path)
    w.refresh()
    w.wait()
    yield w, ui_mod
    w.close()


def _select(w, ui, path):
    for i in range(w.list_view.count()):
        r = w.list_view.item(i).data(ui.ROLE_ROW)
        w.list_view.item(i).setSelected(bool(r) and r.node_path == path)


def test_status_line_offers_the_shot_gap_and_textures(win):
    w, _ = win
    assert w.gap_label.text() == "\u00b7 sh025 v006 has 1 output not in the scene: char_Ata"
    assert not w.gap_link.isHidden()
    w.gap_link.click()
    assert w.backend.calls[-1] == ("load_shot", w.ctl.target_root, "sh025", "v006")
    assert w.weight_label.text() == "textures 2.1 GB"


def test_inspector_shows_what_is_new_source_and_links(win):
    w, ui = win
    _select(w, ui, "/stage/a")
    p = w.subd_panel
    assert not p.news_box.isHidden()
    assert p.news_title.text() == "What is new in lookdev v003"
    assert p.news_meta.text() == "2026-11-16 10:00 \u00b7 work file by Mai"
    assert "+ 2 meshes: Fin_L, Fin_R" in p.news_text.text() and "1.0 MB \u2192 2.0 MB" in p.news_text.text()
    assert p.source_buttons["shot"].isChecked() and not p.source_buttons["asset"].isChecked()
    p.source_buttons["asset"].click()
    assert ("source", ("/stage/a",), "asset") in w.backend.calls
    for key, call in (("folder", "folder"), ("monos", "monos"), ("frame", "frame")):
        p.link_buttons[key].click()
        assert w.backend.calls[-1] == (call, "/stage/a")
    _select(w, ui, "/stage/b")
    assert p.news_box.isHidden()  # nothing newer: no box


def test_view_bar_solo_and_viewport_parts(win):
    w, ui = win
    assert w.part_buttons["lookdev"].isChecked()
    w.solo_button.click()
    assert "Select the loaders" in w.result.text()  # nothing selected
    _select(w, ui, "/stage/b")
    w.solo_button.click()
    assert w.backend.calls[-1] == ("solo", ("/stage/b",)) and w.solo_button.isChecked()
    w.solo_button.click()
    assert w.backend.calls[-1] == ("solo", ()) and not w.solo_button.isChecked()
    w.part_buttons["groom"].click()
    assert w.backend.calls[-1] == ("viewport", "groom", False) and not w.part_buttons["groom"].isChecked()


def test_filter_keeps_matching_rows(win):
    w, ui = win
    w.filter_edit.setText("helen")
    names = [w.list_view.item(i).data(ui.ROLE_ROW).instance for i in range(w.list_view.count())
             if w.list_view.item(i).data(ui.ROLE_ROW)]
    assert names == ["char_Helen"]
    w.filter_edit.setText("")


def test_add_drawer_lists_assets_and_adds_the_picked_ones(win, tmp_path):
    w, ui = win
    root = make_tree(tmp_path / "proj", [
        "01_assets/_props/prop_Rock/01_modelling/03_uv/publish/v001/prop_Rock_uv_publish.usdc",
        "01_assets/_props/prop_Shell/01_modelling/03_uv/publish/v002/prop_Shell_uv_publish.usd",
        "01_assets/_characters/char_Ata/05_lookdev/",
        "02_shots/sh025/01_anim/publish/"])
    w._project = str(root)
    w.open_drawer()
    d = w.drawer
    assert not d.isHidden() and w.subd_panel.isHidden() and w.primary.isHidden()  # one primary: the drawer's
    chips = [d.chips.itemAt(i).widget().text() for i in range(d.chips.count()) if d.chips.itemAt(i).widget()]
    assert chips == ["All 2", "Props 2"]                     # char_Ata has no model: not offered
    assert d.list.count() == 2 and not d.add_button.isEnabled()
    d.model_only.setChecked(False)
    assert d.list.count() == 3
    d.model_only.setChecked(True)
    d.search.setText("rock")
    assert d.list.count() == 1
    d.list.item(0).setSelected(True)
    assert d.add_button.text() == "Add 1" and d.add_button.isEnabled()
    d.add_button.click()
    assert w.backend.calls[-1] == ("add_assets", str(root), ("prop_Rock",))
    assert d.isHidden()
    assert "Added 1 asset" in w.result.text()


def test_hand_off_writes_the_selection(win, monkeypatch):
    w, ui = win
    monkeypatch.setattr(ui.QFileDialog, "getExistingDirectory", staticmethod(lambda *a, **k: "D:/out"))
    _select(w, ui, "/stage/b")
    w.handoff_button.click()
    assert w.backend.calls[-1] == ("handoff", ("/stage/b",), "D:/out")
    assert w.result.text().startswith("Handed off /stage/b: written")
