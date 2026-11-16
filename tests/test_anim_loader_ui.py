"""Mono Anim Loader manager window, offscreen with a fake backend (plan Task 9)."""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtWidgets = pytest.importorskip("PySide6.QtWidgets")

from tests.test_anim_loader_controller import FakeBackend  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


@pytest.fixture
def make(app, tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    import importlib

    from tools.fx.anim_loader import ui as ui_mod

    importlib.reload(ui_mod)  # PREFS follows APPDATA
    windows = []

    def _make(backend=None):
        w = ui_mod.AnimLoaderManager(backend or FakeBackend())
        w.resize(1100, 640)
        w.wait()
        windows.append(w)
        return w

    yield _make, ui_mod
    for w in windows:
        w.close()


def _rows(view):
    from tools.fx.anim_loader.ui import ROLE_ROW

    return [view.item(i).data(ROLE_ROW) for i in range(view.count()) if view.item(i).data(ROLE_ROW)]


def test_list_shows_every_loader_grouped(make):
    mk, ui = make
    w = mk()
    rows = _rows(w.list_view)
    assert [r.instance for r in rows] == ["char_Helen", "veh_Spaceship", "sh025", "char_Robot_2", "old_robot"]
    headers = [w.list_view.item(i).data(ui.ROLE_HEADER) for i in range(w.list_view.count())
               if w.list_view.item(i).data(ui.ROLE_HEADER)]
    assert headers == ["sh025 · 3", "sh900 · 1", "old loaders · 1"]
    assert w.headline.text() == "2 behind, 1 needs an asset, 1 old loader"
    assert w.primary.text() == "Update 2 behind" and w.primary.isEnabled()
    assert w.upgrade_button.text() == "Upgrade 1 old" and not w.upgrade_button.isHidden()


def test_grid_and_list_hold_the_same_rows_and_the_view_is_remembered(make):
    mk, ui = make
    w = mk()
    w.set_view("grid")
    assert w.stack.currentWidget() is w.grid_view
    assert [r.node_path for r in _rows(w.grid_view)] == [r.node_path for r in _rows(w.list_view)]
    again = mk()
    assert again._view_key == "grid"  # per viewer, from %APPDATA%


def test_selection_changes_the_primary_button(make):
    mk, ui = make
    w = mk()
    target = next(i for i in range(w.list_view.count())
                  if (r := w.list_view.item(i).data(ui.ROLE_ROW)) and r.node_path == "/stage/a")
    w.list_view.item(target).setSelected(True)
    assert w.primary.text() == "Update 1 selected"
    w.primary.click()
    assert w.backend.calls[-1][0] == "update" and w.backend.calls[-1][1] == ("/stage/a",)
    assert "moved" in w.result.text()


def test_cells_say_it_in_words(make):
    _, ui = make
    from tools.fx.anim_loader import logic

    assert ui.chip(logic.STATUS_NEWER, "v003", "v002")[0] == "v002 \u2192 v003"
    assert ui.chip(logic.STATUS_MISSING, None, "")[0] == "missing"
    assert ui.chip(logic.STATUS_ASSET, None, "")[0] == "asset?"
    assert ui.chip(logic.STATUS_OFF, None, "")[0] == "\u2013"            # nothing published: a dash, not a word
    assert ui.chip(logic.STATUS_NONE, None, "")[0] == "\u2013"


def test_ok_versions_are_plain_text(make):
    mk, ui = make
    w = mk()
    helen = next(r for r in _rows(w.list_view) if r.node_path == "/stage/b")
    assert ui.part_cell(helen, "anim") == ("v001", ui.TEXT_PRIMARY)       # colour only when there is work
    assert ui.part_cell(helen, "cloth")[0] == "missing"


def test_empty_scene(make):
    mk, _ = make
    b = FakeBackend()
    b.infos = []
    w = mk(b)
    assert w.stack.currentWidget() is w.empty
    assert w.headline.text() == "No anim loaders in the scene" and w.status_meta.text() == ""
    assert w.primary.isHidden() and w.upgrade_button.isHidden()  # nothing to do: no primary button
    assert w.subd_panel.isHidden()                                # no selection: no inspector


def test_paints_at_both_scales(make):
    mk, ui = make
    for scale in (1.0, 1.5):
        w = ui.AnimLoaderManager(FakeBackend(), scale=scale)
        w.resize(400, 760)
        w.wait()
        for view in ("list", "grid"):
            w.set_view(view)
            assert not w.grab().isNull()
        w.close()


def _subd_window(make):
    from tests.test_anim_loader_controller import _subd_backend

    mk, ui = make
    return mk(_subd_backend()), ui


def _select(w, ui, path):
    for i in range(w.list_view.count()):
        r = w.list_view.item(i).data(ui.ROLE_ROW)
        w.list_view.item(i).setSelected(bool(r) and r.node_path == path)


def _act(menu, text):
    return next(a for a in menu.actions() if a.text() == text)


def test_inspector_shows_only_for_a_selection(make):
    w, ui = _subd_window(make)
    assert w.subd_panel.isHidden()
    _select(w, ui, "/stage/b")
    assert not w.subd_panel.isHidden() and w.subd_panel.title.text() == "char_Helen"
    assert w.subd_panel.meta.text().startswith("/stage/b \u00b7 anim v001")
    _select(w, ui, "")
    assert w.subd_panel.isHidden()


def test_subd_detail_shows_groups_and_meshes(make):
    w, ui = _subd_window(make)
    _select(w, ui, "/stage/b")
    tree = w.subd_panel.tree
    groups = [tree.topLevelItem(i).text(0) for i in range(tree.topLevelItemCount())]
    assert groups == ["Base_grp", "Outfit_grp"]
    base = tree.topLevelItem(0)
    assert base.text(2) == "mixed" and base.childCount() == 2 and base.text(3) == "mixed"
    assert "~6.6 M" in w.subd_panel.load.text()


def test_subd_scheme_from_the_menu_applies_to_the_selection(make):
    from tools.fx.anim_loader.logic import KEEP

    w, ui = _subd_window(make)
    _select(w, ui, "/stage/b")
    tree = w.subd_panel.tree
    _act(w.subd_panel.menu_for(tree.topLevelItem(0)), "Off").trigger()   # one row, not selected: that row only
    assert w.backend.calls[-1][:5] == ("set_subd", "/stage/b", ("Geo/Base_grp/**",), "none", KEEP)
    base, outfit = tree.topLevelItem(0), tree.topLevelItem(1)            # the rescan rebuilt the tree
    base.setSelected(True)
    outfit.setSelected(True)
    menu = w.subd_panel.menu_for(outfit)                                 # a selected row: the whole selection
    _act(menu, "Catmull-Clark").trigger()
    assert set(w.backend.calls[-1][2]) == {"Geo/Base_grp/**", "Geo/Outfit_grp/**"}
    assert w.backend.calls[-1][3] == "catmullClark"


def test_subd_dicing_keeps_the_scheme(make):
    w, ui = _subd_window(make)
    _select(w, ui, "/stage/b")
    w.subd_panel.set_dicing(["Geo/Base_grp/**"], "0.5")
    assert w.backend.calls[-1][2:] == (("Geo/Base_grp/**",), None, 0.5)
    w.subd_panel.set_dicing(["Geo/Base_grp/**"], "abc")
    assert "number" in w.result.text()
    w.subd_panel.set_dicing(["Geo/Base_grp/**"], "")
    assert w.backend.calls[-1][2:] == (("Geo/Base_grp/**",), None, None)  # empty clears it


def test_subd_menu_clear_and_apply(make):
    w, ui = _subd_window(make)
    _select(w, ui, "/stage/b")
    menu = w.subd_panel.menu_for(w.subd_panel.tree.topLevelItem(1))
    _act(menu, "Clear override").trigger()
    assert w.backend.calls[-1] == ("clear_subd", "/stage/b", ["Geo/Outfit_grp/**"])
    menu = w.subd_panel.menu_for(w.subd_panel.tree.topLevelItem(1))
    _act(menu, "Apply overrides to every char_Helen").trigger()
    assert w.backend.calls[-1] == ("subd_to_asset", "/stage/b")


def test_subd_columns_say_only_what_differs(make):
    w, ui = _subd_window(make)
    _select(w, ui, "/stage/b")
    tree = w.subd_panel.tree
    outfit = tree.topLevelItem(1)
    assert outfit.text(2) == "lookdev" and outfit.child(0).text(2) == ""   # same as its group: left blank
    base = tree.topLevelItem(0)
    assert base.text(2) == "mixed" and {base.child(i).text(2) for i in range(2)} == {"lookdev", "shot"}
    assert not tree.isColumnHidden(4)                                     # Geo_Dress has dicing 0.5


def test_subd_cell_in_rows(make):
    w, ui = _subd_window(make)
    helen = next(r for r in _rows(w.list_view) if r.node_path == "/stage/b")
    assert ui.subd_cell(helen) == ("2 \u00b7 ~6.6 M", ui.STATUS_COLORS[ui.AM_WARN])
    assert ui.subd_chip(helen) == "subd 2 \u00b7 ~6.6 M"


def test_camera_has_nothing_to_subdivide(make):
    w, ui = _subd_window(make)
    _select(w, ui, "/stage/c")  # the camera
    assert w.subd_panel.tree.isHidden() and "nothing to subdivide" in w.subd_panel.load.text()


def test_every_style_follows_the_ui_scale(make):
    _, ui = make
    from tests.test_anim_loader_controller import FakeBackend

    w = ui.AnimLoaderManager(FakeBackend(), scale=1.5)
    w.wait()
    assert "font-size: 22px" in w.primary.styleSheet()        # 15 px body x 1.5
    assert "font-size: 21px" in w.load_button.styleSheet()    # 14 px meta x 1.5
    assert "font-size: 21px" in w.project_button.styleSheet()
    w.close()


def test_scale_css():
    from tools.fx.anim_loader.ui import scale_css

    assert scale_css("a { padding: 9px 14px; font-size: 15px; border: 1px solid; }", 1.5) == \
        "a { padding: 14px 21px; font-size: 22px; border: 1px solid; }"


def test_primary_button_follows_the_one_action(make):
    from tools.fx.anim_loader.logic import STATUS_OK

    w, ui = _subd_window(make)
    assert w.primary.text() == "Update 2 behind" and not w.primary.isHidden()
    assert not w.upgrade_button.isHidden()                       # upgrade stays a secondary button here
    b = w.backend
    b.status["/stage/a"]["lookdev"] = (STATUS_OK, None)
    b.status["/stage/c"]["anim"] = (STATUS_OK, None)
    w.refresh(); w.wait()
    assert w.primary.text() == "Upgrade 1 old" and w.upgrade_button.isHidden()   # not twice
    b.infos = [i for i in b.infos if not i.legacy]
    w.refresh(); w.wait()
    assert w.primary.isHidden()                                  # nothing worth doing: no primary button
    assert w.headline.text() == "1 needs an asset"


def test_heavy_shot_is_a_note_on_the_status_line(make):
    from tools.fx.anim_loader.logic import STATUS_OK

    w, ui = _subd_window(make)
    b = w.backend
    calls = []
    b.hulls_on = lambda: False
    b.set_hulls_only = lambda: calls.append(1) or 1
    plan = b.subd(None)["/stage/b"]
    plan["faces"]["/Geo/Base_grp/Body_grp/Geo_Body"] = 1_000_000   # 1 M faces x 16 > 5 M polygons
    b.subd = lambda infos: {"/stage/b": plan}
    b.infos = [i for i in b.infos if not i.legacy]
    b.status["/stage/a"]["lookdev"] = (STATUS_OK, None)
    b.status["/stage/c"]["anim"] = (STATUS_OK, None)
    w.refresh(); w.wait()
    assert "M subdivision polygons" in w.heavy_label.text() and not w.hulls_link.isHidden()
    assert w.primary.isHidden() and "Heavy" not in w.headline.text()   # a note, not the primary
    w.hulls_link.click()
    assert calls == [1] and "memory" in w.result.text()
    b.hulls_on = lambda: True
    w.refresh(); w.wait()
    assert w.heavy_label.isHidden() and w.hulls_link.isHidden()


def test_retarget_copied_loaders_to_the_scene_shot(make):
    mk, ui = make
    b = FakeBackend()
    b.project_and_shot = lambda: ("P:/proj", "sh025")    # the scene is sh025's: the sh900 loader was copied in
    b.retarget = lambda paths, shot: b.calls.append(("retarget", tuple(paths), shot)) or ([f"{p}" for p in paths], [])
    w = mk(b)
    assert w.shot_button.text() == "sh025 \u25be"
    assert w.primary.text() == "Retarget 1 to sh025" and w.headline.text().startswith("1 loader from sh900")
    assert w.retarget_button.isHidden()                 # it is the primary: not twice
    w.primary.click()
    assert b.calls[-1] == ("retarget", ("/stage/d",), "sh025") and w.result.text() == "Retargeted 1 to sh025"
    _select(w, ui, "/stage/b")                          # a sh025 loader picked: nothing to retarget
    _act(w.shot_menu, "sh900").trigger()                # ...until the crumb names another shot
    assert w.primary.text() == "Retarget 1 to sh900" and w.retarget_button.isHidden()
    _select(w, ui, "/stage/a")                          # behind: Update stays first, Retarget beside it
    assert w.primary.text() == "Update 1 selected"
    assert not w.retarget_button.isHidden() and w.retarget_button.text() == "Retarget 1 to sh900"


def test_project_menu_loads_a_shot_in_an_unsaved_scene(make, tmp_path, monkeypatch):
    from tests.anim_loader_tree import make as make_tree

    mk, ui = make
    proj = make_tree(tmp_path / "proj", ["01_assets/", "02_shots/sh010/01_anim/publish/v001/cam_sh010.usd",
                                         "02_shots/sh020/01_anim/publish/v002/cam_sh020.usd",
                                         "02_shots/sh020/01_anim/publish/v003/cam_sh020.usd"])
    other = make_tree(tmp_path / "other", ["01_assets/", "02_shots/sh500/01_anim/publish/v001/cam_sh500.usd"])
    ui._save_prefs({"recent_projects": [proj.as_posix()]})
    b = FakeBackend()
    b.infos = []                                          # an empty, unsaved scene
    b.project_and_shot = lambda: ("", "")
    w = mk(b)
    assert w.project_button.text() == "proj \u203a" and w.shots == ["sh010", "sh020"]
    _act(w.shot_menu, "sh020").trigger()
    assert w.versions == ["v003", "v002"]
    assert [a.text() for a in w.load_menu.actions()] == ["sh020 v003  \u00b7  newest", "sh020 v002"]
    w.load_menu.actions()[1].trigger()
    assert b.calls[-1] == ("load_shot", proj.as_posix(), "sh020", "v002")
    monkeypatch.setattr(ui.QFileDialog, "getExistingDirectory", lambda *a, **k: str(other / "02_shots"))
    _act(w.project_menu, "Browse...").trigger()
    assert w._project == other.as_posix() and w.shot_button.text() == "sh500 \u25be"  # the folder finds its project
    monkeypatch.setattr(ui.QFileDialog, "getExistingDirectory", lambda *a, **k: str(proj / "02_shots/sh020"))
    _act(w.project_menu, "Browse...").trigger()
    assert w._project == proj.as_posix() and w.ctl.target_shot == "sh020"           # a shot folder picks the shot
    assert ui._load_prefs()["recent_projects"][:2] == [proj.as_posix(), other.as_posix()]
    _act(w.project_menu, "other").trigger()                                          # recent projects in the menu
    assert w._project == other.as_posix()


def test_no_project_yet_says_so(make):
    mk, ui = make
    b = FakeBackend()
    b.infos = []
    b.project_and_shot = lambda: ("", "")
    w = mk(b)
    assert w.project_button.text() == "Pick a project \u203a" and w.shot_button.isHidden()
    assert [a.text() for a in w.load_menu.actions()] == ["Pick a project first"]


def test_unsaved_scene_shot_starts_on_the_loaders_shot(make, tmp_path):
    from tests.anim_loader_tree import make as make_tree

    mk, ui = make
    proj = make_tree(tmp_path / "proj", ["01_assets/", "02_shots/sh001/01_anim/publish/",
                                         "02_shots/sh900/01_anim/publish/v001/cam_sh900.usd"])
    b = FakeBackend()
    b.infos = [i for i in b.infos if i.state is None or i.state.shot == "sh900"]
    b.infos = [i if i.state is None else type(i)(i.path, __import__("dataclasses").replace(
        i.state, project_root=proj.as_posix()), i.legacy) for i in b.infos]
    b.project_and_shot = lambda: ("", "")
    w = mk(b)
    assert w._project == proj.as_posix() and w.ctl.target_shot == "sh900"
