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
                                               (("Meshes added", "Fin_L, Fin_R"),))]},
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
    assert w.gap_label.text() == "+1 in sh025 v006: char_Ata"
    assert not w.gap_link.isHidden()
    w.gap_link.click()
    assert w.backend.calls[-1] == ("load_shot", w.ctl.target_root, "sh025", "v006")
    assert w.weight_label.text() == "2.1 GB" and not w.weight_icon.isHidden()


def _item(w, ui, path):
    return next(w.list_view.item(i) for i in range(w.list_view.count())
                if (r := w.list_view.item(i).data(ui.ROLE_ROW)) and r.node_path == path)


def _act(menu, text):
    return next(a for a in menu.actions() if a.text() == text)


def test_inspector_is_information_and_actions_are_on_the_row_menu(win):
    w, ui = win
    _select(w, ui, "/stage/a")
    p = w.subd_panel
    news = p.news.rows()
    assert not p.news.isHidden() and news["Lookdev"] == "v002 \u2192 v003"
    assert news["Published"] == "2026-11-16 10:00" and news["Work file by"] == "Mai"
    assert news["Meshes added"] == "Fin_L, Fin_R"
    assert p.details.rows()["Kind"] == "Shot loader" and p.details.rows()["Shot"] == "sh025"
    # Monos: the inspector shows, it does not act; its only buttons fold its sections (view state)
    assert all(isinstance(b, ui._Section) for b in p.findChildren(ui.QPushButton))
    menu = w.row_menu(_item(w, ui, "/stage/a"))
    texts = [a.text() for a in menu.actions() if not a.isSeparator()]
    assert "Update to lookdev v003" in texts and "Switch to Source Asset" in texts
    _act(menu, "Switch to Source Asset").trigger()
    assert ("source", ("/stage/a",), "asset") in w.backend.calls
    for text, call in (("Open folder", "folder"), ("Open in Monos", "monos"), ("Frame in the viewport", "frame")):
        _act(w.row_menu(_item(w, ui, "/stage/a")), text).trigger()
        assert w.backend.calls[-1] == (call, "/stage/a")
    _select(w, ui, "/stage/b")
    assert p.news.isHidden() and p.news_head.isHidden()  # nothing newer: no section


def test_viewport_menu_is_explicit_actions(win):
    w, ui = win
    w._fill_viewport_menu()
    texts = [a.text() for a in w.viewport_menu.actions() if not a.isSeparator()]
    assert texts[:3] == ["Solo the selected loaders", "Hide lookdev in the viewport (every loader)",
                         "Hide groom in the viewport (every loader)"]
    assert not w.viewport_menu.actions()[0].isEnabled()  # nothing selected
    _select(w, ui, "/stage/b")
    w._fill_viewport_menu()
    _act(w.viewport_menu, "Solo the selected loaders").trigger()
    assert w.backend.calls[-1] == ("solo", ("/stage/b",))
    assert w.view_state.text() == "Solo: 1 loader" and not w.solo_off.isHidden()
    w.solo_off.click()
    assert w.backend.calls[-1] == ("solo", ()) and w.solo_off.isHidden()
    w._fill_viewport_menu()
    _act(w.viewport_menu, "Hide groom in the viewport (every loader)").trigger()
    assert w.backend.calls[-1] == ("viewport", "groom", False)
    assert w.view_state.text() == "Groom render only"


def test_list_rows_alternate_and_groups_are_bands(win):
    w, ui = win
    zebra = [w.list_view.item(i).data(ui.ROLE_ZEBRA) for i in range(w.list_view.count())
             if w.list_view.item(i).data(ui.ROLE_ROW)]
    assert zebra[:3] == [False, True, False]  # sh025: three rows alternate; each group starts plain
    assert w.column_header.height() == w.px(30)


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


def test_an_anim_loader_2_2_shows_its_versions_and_offers_upgrade(app, tmp_path, monkeypatch):
    """A 2.2 node has the MonoFX Loader's parms: its row shows its versions (tag 2.2), it still counts for Upgrade,
    and its inspector says what Upgrade does (testing v0.1.33 on sh025: rows said only "Upgrade...")."""
    monkeypatch.setenv("APPDATA", str(tmp_path))
    from tests.test_anim_loader_controller import FakeBackend, LoaderInfo, _state
    from tools.fx.anim_loader import ui

    b = FakeBackend()
    b.infos = [LoaderInfo("/stage/h", _state("sh025", "char_Helen", "char_Helen"), True, "char_Helen")]
    b.status = {"/stage/h": {"anim": (ui.logic.STATUS_OK, None), "lookdev": (ui.logic.STATUS_OK, None),
                             "groom": (ui.logic.STATUS_OFF, None), "cloth": (ui.logic.STATUS_OFF, None)}}
    w = ui.AnimLoaderManager(b)
    w.resize(1100, 700)
    w.wait()
    row = next(w.list_view.item(i).data(ui.ROLE_ROW) for i in range(w.list_view.count())
               if w.list_view.item(i).data(ui.ROLE_ROW))
    assert row.legacy and row.versions["anim"] == "v001" and row.shot == "sh025"
    assert w.primary.text() == "Upgrade 1"
    w.list_view.item(1).setSelected(True)
    assert w.subd_panel.details.rows()["Kind"] == "Old loader"
    w.close()


def test_inspector_slides_out_and_in(win):
    w, ui = win
    from PySide6.QtTest import QTest

    w.show()
    QTest.qWait(50)
    _select(w, ui, "/stage/a")
    clip = w.subd_clip
    assert not w.subd_panel.isHidden() and clip._slide_anim.state() == clip._slide_anim.State.Running
    QTest.qWait(w.DIALOG_IN_MS // 3)
    # sliding: the panel keeps its full width, the clip shows its left part (it moves in, never stretches)
    assert w.subd_panel.width() >= w.px(360) and clip.width() < w.subd_panel.width()
    QTest.qWait(w.DIALOG_IN_MS + 120)
    assert clip.width() >= w.px(300) and clip.minimumWidth() == w.px(360) and clip.full == 0
    _select(w, ui, "")
    QTest.qWait(w.DIALOG_OUT_MS + 120)
    assert w.subd_panel.isHidden()


def test_result_line_stays_short_and_the_rest_is_its_tooltip(win):
    w, ui = win
    w.ctl.message = "Converted 10 sublayers to MonoFX Loaders " + "x" * 200
    w.ctl.details = "Castle -> /Castle\nCliff01 -> /Cliff01"
    w._update_bar()
    assert len(w.result.text()) <= 140 and w.result.text().endswith("\u2026")
    assert w.result.toolTip() == "Castle -> /Castle\nCliff01 -> /Cliff01"


def test_a_first_version_reads_plus(win):
    _, ui = win
    assert ui.chip(ui.logic.STATUS_NEWER, "V001", "")[0] == "+V001"
    assert ui.chip(ui.logic.STATUS_NEWER, "v003", "v002")[0] == "v002 \u2192 v003"


def test_inspector_sections_fold_and_the_fold_is_remembered(win):
    w, ui = win
    _select(w, ui, "/stage/a")
    p = w.subd_panel
    assert not p.details.isHidden() and not p.news.isHidden()
    p.details_head.click()                       # fold the details
    assert p.details.isHidden() and not p.details_head.isHidden()
    assert ui._load_prefs()["inspector_details"] is False
    _select(w, ui, "/stage/b")                   # another loader: still folded
    assert p.details.isHidden()
    p.details_head.click()
    assert not p.details.isHidden() and ui._load_prefs()["inspector_details"] is True


def test_one_upgrade_for_old_loaders_and_publish_sublayers(app, tmp_path, monkeypatch):
    """Convert sublayer and Upgrade old loader were two actions for one thing (the user's report): one Upgrade."""
    monkeypatch.setenv("APPDATA", str(tmp_path))
    from tests.test_anim_loader_controller import FakeBackend, LoaderInfo
    from tools.fx.anim_loader import ui
    from tools.fx.anim_loader.logic import parse_publish_path

    b = FakeBackend()
    ref = parse_publish_path("D:/Job/proj/01_assets/_props/prop_Cliff01/05_lookdev/publish/v001/c.usdc")
    b.infos = [LoaderInfo("/stage/old", None, True, "old_robot"), LoaderInfo("/stage/Cliff01#1", None, False,
                                                                           "Cliff01", "", ref)]
    b.status = {}
    b.convert_layers = lambda paths: (b.calls.append(("convert", tuple(paths))) or ([f"{p} -> x (moved t)"
                                                                                       for p in paths], []))
    w = ui.AnimLoaderManager(b)
    w.wait()
    assert w.primary.text() == "Upgrade 2" and w.headline.text() == "2 to upgrade"
    w.primary.click()
    assert ("upgrade", ("/stage/old",)) in b.calls and ("convert", ("/stage/Cliff01#1",)) in b.calls
    assert w.result.text().startswith("Upgraded 2 to MonoFX Loader, 1 with their xforms")
    item = next(w.list_view.item(i) for i in range(w.list_view.count())
                if (r := w.list_view.item(i).data(ui.ROLE_ROW)) and r.kind == "layer")
    texts = [a.text() for a in w.row_menu(item).actions()]
    assert "Upgrade to MonoFX Loader" in texts and not any("Convert" in t for t in texts)
    w.close()
