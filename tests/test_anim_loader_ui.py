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
    assert headers == ["sh025   3", "sh900   1", "old loaders   1"]
    assert w.headline.text() == "2 behind, 1 needs an asset, 1 to upgrade"
    assert w.primary.text() == "Update 2 behind" and w.primary.isEnabled()
    assert w.upgrade_button.text() == "1" and not w.upgrade_button.isHidden()  # icon + count, the tip says it
    assert w.upgrade_button.toolTip().startswith("Upgrade 1")


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
    assert w.headline.text() == "No loaders in the scene" and w.status_meta.text() == ""
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
    assert w.subd_panel.details.rows()["Node"] == "/stage/b" and w.subd_panel.details.rows()["Anim"] == "v001"
    _select(w, ui, "")
    assert w.subd_panel.isHidden()


def test_subd_detail_shows_groups_and_meshes(make):
    w, ui = _subd_window(make)
    _select(w, ui, "/stage/b")
    tree = w.subd_panel.tree
    # every level of the hierarchy, as the scene graph shows it (the user's ask): Geo > Base_grp > Geo_Body
    assert tree.topLevelItemCount() == 1 and tree.topLevelItem(0).text(0) == "Geo"
    assert tree.topLevelItem(0).text(1) == "411.0k"
    # each row draws its prim type's icon, as Houdini's Scene Graph Tree does (the user's ask)
    assert tree.topLevelItem(0).data(0, ui.ROLE_PRIM) == "xform"
    leaf = tree.topLevelItem(0)
    while leaf.childCount():
        leaf = leaf.child(0)
    assert leaf.data(0, ui.ROLE_PRIM) == "mesh" and leaf.parent().data(0, ui.ROLE_PRIM) == "xform"
    assert not ui._prim_icon("mesh", 16).isNull()
    groups = [tree.topLevelItem(0).child(i).text(0) for i in range(tree.topLevelItem(0).childCount())]
    assert groups == ["Base_grp", "Outfit_grp"]
    base = tree.topLevelItem(0).child(0)
    assert base.text(2) == "mixed" and base.childCount() == 2 and base.text(3) == "mixed"
    assert w.subd_panel.details.rows()["Viewport polygons"].startswith("~6.6 M")


def test_subd_scheme_from_the_menu_applies_to_the_selection(make):
    from tools.fx.anim_loader.logic import KEEP

    w, ui = _subd_window(make)
    _select(w, ui, "/stage/b")
    tree = w.subd_panel.tree
    _act(w.subd_panel.menu_for(tree.topLevelItem(0).child(0)), ui.InspectorPanel.MENU_OFF).trigger()   # one row, not selected: that row only
    assert w.backend.calls[-1][:5] == ("set_subd", "/stage/b", ("Geo/Base_grp/**",), "none", KEEP)
    base, outfit = tree.topLevelItem(0).child(0), tree.topLevelItem(0).child(1)            # the rescan rebuilt the tree
    base.setSelected(True)
    outfit.setSelected(True)
    menu = w.subd_panel.menu_for(outfit)                                 # a selected row: the whole selection
    _act(menu, ui.InspectorPanel.MENU_CATMULL).trigger()
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
    menu = w.subd_panel.menu_for(w.subd_panel.tree.topLevelItem(0).child(1))
    _act(menu, ui.InspectorPanel.MENU_CLEAR).trigger()
    assert w.backend.calls[-1] == ("clear_subd", "/stage/b", ["Geo/Outfit_grp/**"])
    # only one char_Helen loader in the scene: nothing to copy to, no item
    menu = w.subd_panel.menu_for(w.subd_panel.tree.topLevelItem(0).child(1))
    assert not any(a.text().startswith("Same overrides") for a in menu.actions())
    w.subd_panel.other_instances = lambda: ["char_Helen_inst02"]
    menu = w.subd_panel.menu_for(w.subd_panel.tree.topLevelItem(0).child(1))
    _act(menu, "Same overrides on the other 1 char_Helen loader").trigger()
    assert w.backend.calls[-1] == ("subd_to_asset", "/stage/b")


def test_subd_columns_say_only_what_differs(make):
    w, ui = _subd_window(make)
    _select(w, ui, "/stage/b")
    tree = w.subd_panel.tree
    outfit = tree.topLevelItem(0).child(1)
    assert outfit.text(2) == "lookdev" and outfit.child(0).text(2) == ""   # same as its group: left blank
    base = tree.topLevelItem(0).child(0)
    assert base.text(2) == "mixed" and {base.child(i).text(2) for i in range(2)} == {"lookdev", "shot"}
    assert not tree.isColumnHidden(4)                                     # Geo_Dress has dicing 0.5


def test_subd_cell_in_rows(make):
    w, ui = _subd_window(make)
    helen = next(r for r in _rows(w.list_view) if r.node_path == "/stage/b")
    assert ui.subd_cell(helen) == ("~6.6 M", ui.STATUS_COLORS[ui.AM_WARN])
    assert ui.subd_chip(helen) == "subd 2, ~6.6 M"


def test_camera_inspector_shows_only_what_a_camera_has(make):
    w, ui = _subd_window(make)
    _select(w, ui, "/stage/c")  # the camera
    p = w.subd_panel
    rows = p.details.rows()
    assert p.tree.isHidden() and "Subdivision" not in rows       # no subdivision at all
    assert rows["Kind"] == "Camera" and "Lookdev" not in rows and rows["Anim"]


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
        "a { padding: 14px 21px; font-size: 22px; border: 2px solid; }"
    # a rounded control's border is 2 px at least (1 px breaks on its corners); dividers stay hairlines
    assert scale_css("a { border: 1px solid; border-bottom: 1px solid; }", 1) == \
        "a { border: 2px solid; border-bottom: 1px solid; }"
    assert scale_css("a { border: 1px solid; }", 2.5) == "a { border: 4px solid; }"


def test_primary_button_follows_the_one_action(make):
    from tools.fx.anim_loader.logic import STATUS_OK

    w, ui = _subd_window(make)
    assert w.primary.text() == "Update 2 behind" and not w.primary.isHidden()
    assert not w.upgrade_button.isHidden()                       # upgrade stays a secondary button here
    b = w.backend
    b.status["/stage/a"]["lookdev"] = (STATUS_OK, None)
    b.status["/stage/c"]["anim"] = (STATUS_OK, None)
    w.refresh(); w.wait()
    assert w.primary.text() == "Upgrade 1" and w.upgrade_button.isHidden()   # not twice
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
    assert "M polygons" in w.heavy_label.text() and not w.hulls_link.isHidden()
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
    acts = [a for a in w.load_menu.actions() if not a.isSeparator()]  # sections and separators are separators
    assert [a.text() for a in acts] == ["Load sh020 v003 (newest)", "Load sh020 v002", "Add assets…"]
    acts[1].trigger()
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
    acts = [a for a in w.load_menu.actions() if not a.isSeparator()]
    assert [a.text() for a in acts] == ["Pick a project first", "Add assets…"] and not acts[1].isEnabled()


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


def test_subd_menu_says_what_it_does_and_every_row_has_an_icon(make):
    """The user's ask: the menu was cryptic (Publish / Off / Catmull-Clark, a Dicing field) and did not line up."""
    w, ui = _subd_window(make)
    _select(w, ui, "/stage/b")
    menu = w.subd_panel.menu_for(w.subd_panel.tree.topLevelItem(0).child(1))
    acts = [a for a in menu.actions() if not a.isSeparator()][1:]  # the first is the head band (a widget)
    assert all(not a.icon().isNull() for a in acts)
    assert not any(a.isCheckable() for a in acts)  # no check column pushing some rows in
    dicing = next(a.menu() for a in acts if a.text() == ui.InspectorPanel.MENU_DICING)
    _act(dicing, "0.5").trigger()
    assert w.backend.calls[-1][2:] == (("Geo/Outfit_grp/**",), None, 0.5)


def test_subd_menu_marks_the_current_choice(make):
    w, ui = _subd_window(make)
    _select(w, ui, "/stage/b")
    geo = w.subd_panel.tree.topLevelItem(0)
    for item in (geo.child(1), geo.child(1).child(0)):  # Outfit_grp and its mesh: from the lookdev, no override
        menu = w.subd_panel.menu_for(item)
        assert [a.text() for a in menu.actions() if a.data() == "current"] == [ui.InspectorPanel.MENU_PUBLISH]



def test_toggles_groom_curves_and_inheritance(make):
    """The user's ask: the eye (visibility), viewport and render (purpose) as three toggles, Blender's outliner;
    a click toggles the row, or the selection it is part of, and leaves the selection alone."""
    from tools.fx.anim_loader import logic as lg

    w, ui = _subd_window(make)
    b = w.backend
    _select(w, ui, "/stage/b")
    detail = w.ctl.subd_detail("/stage/b")
    detail["curves"] = {"/Groom/Hair_Back": 21000, "/Groom/Eyebrows": 1200}
    prims = [m.strip("/") for m in detail["plan"]] + ["Groom/Hair_Back", "Groom/Eyebrows"]
    detail["shown"] = lg.prim_shows(prims, {}, ["Geo/Outfit_grp"], ["Groom/Hair_Back", "Groom/Eyebrows"],
                                    [{"pattern": "Geo/Base_grp", "purpose": "proxy"}])
    b.subd = lambda infos: {"/stage/b": detail}  # what the backend reads again after a toggle
    _select(w, ui, "/stage/a")
    _select(w, ui, "/stage/b")
    tree = w.subd_panel.tree
    tops = {tree.topLevelItem(i).text(0): tree.topLevelItem(i) for i in range(tree.topLevelItemCount())}
    assert set(tops) == {"Geo", "Groom"}

    def mesh_color(it):
        return it.data(6, ui.ROLE_TOGGLE)[1]
    hair = tops["Groom"].child(0)
    assert hair.data(0, ui.ROLE_PRIM) == "basiscurves"
    assert hair.data(6, ui.ROLE_TOGGLE)[0] == "monitor-off" and hair.data(7, ui.ROLE_TOGGLE)[0] == "camera"
    assert hair.data(6, ui.ROLE_TOGGLE)[2] is False  # the loader's own purpose: no dot (only the shot's has one)
    geo = tops["Geo"]
    base, outfit = geo.child(0), geo.child(1)
    assert base.data(6, ui.ROLE_TOGGLE)[2]  # the shot's own value: a dot
    assert base.data(6, ui.ROLE_TOGGLE)[1] == mesh_color(base.child(0))  # one look per state, whoever set it
    mesh = base.child(0)
    assert mesh.data(6, ui.ROLE_TOGGLE)[0] == "monitor" and not mesh.data(6, ui.ROLE_TOGGLE)[2]  # inherited: no dot
    assert outfit.data(5, ui.ROLE_TOGGLE)[0] == "eye-off"
    child = outfit.child(0)
    assert child.data(5, ui.ROLE_TOGGLE)[0] == "eye" and child.data(5, ui.ROLE_TOGGLE)[3]  # kept, dimmed
    b.set_show = lambda path, edits: b.calls.append(("set_show", path, tuple(edits)))
    mesh.setSelected(True)
    hair.setSelected(True)
    mesh_pat, mesh_name = mesh.data(0, ui.ROLE_PATTERN), mesh.text(0)
    w.subd_panel._toggle(hair, 7)  # the change rebuilds the table: the items above are gone  # render off: the clicked row decides, the whole selection follows
    assert b.calls[-1][0] == "set_show"
    edits = dict((p, v) for p, _f, v in b.calls[-1][2])
    # Hair_Back: render only -> neither (guide); the mesh already does not render (its parent's proxy): no rule
    assert edits["Groom/Hair_Back"] == "guide" and edits[mesh_pat] is None
    assert {i.text(0) for i in tree.selectedItems()} == {mesh_name, "Hair_Back"}  # selection kept


def test_camera_settings_on_the_loader(make):
    w, ui = _subd_window(make)
    b = w.backend
    b.cam_parms = lambda path: {"clippingRange1": 0.0001, "clippingRange2": 1e6, "horizontalAperture": 36.0,
                                "aspectratiox": 16.0, "aspectratioy": 9.0, "xn__houdiniguidescale_s3a": 1.0}
    b.set_cam_parm = lambda path, name, value: b.calls.append(("cam", path, name, value)) or True
    _select(w, ui, "/stage/c")
    edit = w.subd_panel.cam_edit
    assert not w.subd_panel.cam_head.isHidden()
    assert edit.fields["clippingRange2"].text() == "1000000" and edit.fields["horizontalAperture"].text() == "36"
    edit.fields["clippingRange1"].setText("0.01")
    edit.fields["clippingRange1"].editingFinished.emit()
    assert b.calls[-1] == ("cam", "/stage/c", "clippingRange1", 0.01)
    _select(w, ui, "/stage/b")
    assert w.subd_panel.cam_head.isHidden()



def test_show_inherits_like_houdini():
    """Hiding a parent hides its children, which keep their own eye; purpose follows the parent unless a child has
    its own; a toggle back to the inherited value takes the rule off."""
    from tools.fx.anim_loader import logic as lg

    kids = ["Geo/Hair_grp/A", "Geo/Hair_grp/B"]
    rules = lg.parse_show_rules(__import__("json").dumps(lg.set_show_rules([], [
        ("Geo/Hair_grp", "vis", "invisible"), ("Geo/Hair_grp/B", "vis", "invisible"),
        ("Geo/Hair_grp/**", "purpose", "render"), ("Geo/Hair_grp/A", "purpose", "proxy")])))
    st = lg.prim_shows(kids, {}, [], [], rules)
    a, b, grp = st["Geo/Hair_grp/A"], st["Geo/Hair_grp/B"], st["Geo/Hair_grp"]
    assert not a.visible and a.own_visible and not b.own_visible
    assert a.purpose == "proxy" and b.purpose == "render" and b.purpose_source == ""
    on = lg.prim_shows(kids, {}, [], [], [r for r in rules if r.get("vis") is None or r["pattern"] != "Geo/Hair_grp"])
    assert on["Geo/Hair_grp/A"].visible and not on["Geo/Hair_grp/B"].visible  # B remembered its own
    # the parent's eye on again over Hide Prims needs a rule; a child's purpose back to its parent's needs none
    assert lg.toggle_edits([("Geo/Hair_grp/**", lg.prim_shows(kids, {}, ["Geo/Hair_grp"], [], [])["Geo/Hair_grp"],
                             None)], "eye") == [("Geo/Hair_grp/**", "vis", "inherited")]
    assert lg.toggle_edits([("Geo/Hair_grp/A", a, grp)], "render") == [("Geo/Hair_grp/A", "purpose", "default")]
    own_default = lg.prim_shows(kids, {}, [], [], [{"pattern": "Geo/Hair_grp", "purpose": "render"},
                                                    {"pattern": "Geo/Hair_grp/A", "purpose": "default"}])
    # A: default (viewport and render) under a render-only parent; viewport off = render = the parent's: no rule
    assert lg.toggle_edits([("Geo/Hair_grp/A", own_default["Geo/Hair_grp/A"], own_default["Geo/Hair_grp"])],
                           "viewport") == [("Geo/Hair_grp/A", "purpose", None)]


def test_a_change_keeps_the_scroll_selection_and_folds(make):
    """The user's report: changing what a row shows reset the list's place and dropped the selection."""
    w, ui = _subd_window(make)
    _select(w, ui, "/stage/b")
    p = w.subd_panel
    geo = p.tree.topLevelItem(0)
    geo.child(0).setExpanded(False)
    geo.child(1).child(0).setSelected(True)
    w.refresh()
    w.wait()
    geo = p.tree.topLevelItem(0)
    assert not geo.child(0).isExpanded() and geo.child(1).isExpanded()
    assert [i.data(0, ui.ROLE_PATTERN) for i in p.tree.selectedItems()] == [geo.child(1).child(0).data(0, ui.ROLE_PATTERN)]



def test_details_of_one_loader_never_stay_under_the_next(make):
    """The user's report: picking the camera after char_Helen drew both loaders' details over each other."""
    w, ui = _subd_window(make)
    _select(w, ui, "/stage/b")
    _select(w, ui, "/stage/c")
    labels = [lab for lab in w.subd_panel.details.findChildren(ui.QLabel) if lab.isVisibleTo(w.subd_panel.details)]
    assert len(labels) == 2 * len(w.subd_panel.details.rows())



def test_display_submenu_says_what_a_click_does(make):
    """The user's ask: Display in the right-click menu, the three toggles as verbs."""
    from tools.fx.anim_loader import logic as lg

    w, ui = _subd_window(make)
    b = w.backend
    _select(w, ui, "/stage/b")
    detail = w.ctl.subd_detail("/stage/b")
    detail["shown"] = lg.prim_shows([m.strip("/") for m in detail["plan"]], {}, ["Geo/Outfit_grp"], [], [])
    _select(w, ui, "/stage/a")
    _select(w, ui, "/stage/b")
    outfit = w.subd_panel.tree.topLevelItem(0).child(1)
    pattern = outfit.data(0, ui.ROLE_PATTERN)
    menu = w.subd_panel.menu_for(outfit)
    display = next(a.menu() for a in menu.actions() if a.text() == ui.InspectorPanel.MENU_DISPLAY)
    texts = [a.text() for a in display.actions()]
    assert texts == ["Show", "Stop drawing in the viewport", "Stop rendering"]
    assert all(not a.icon().isNull() for a in display.actions())
    b.set_show = lambda path, edits: b.calls.append(("set_show", path, tuple(edits)))
    _act(display, "Show").trigger()
    assert b.calls[-1] == ("set_show", "/stage/b", ((pattern, "vis", "inherited"),))



def test_every_click_changes_the_state():
    """The user's report: a prim the loader hides needed two clicks (the shot's rule came off and the loader's
    hiding came back). Each click flips what the row shows; the rule is off whenever the loader's value is wanted."""
    from tools.fx.anim_loader import logic as lg

    prims, hidden = ["Geo/Drv/A"], ["Geo/Drv"]
    rules: list[dict] = []
    seen = []
    for _ in range(4):
        st = lg.prim_shows(prims, {}, hidden, [], rules)
        seen.append(st["Geo/Drv"].own_visible)
        rules = lg.set_show_rules(rules, lg.toggle_edits([("Geo/Drv/**", st["Geo/Drv"], st["Geo"])], "eye"))
    assert seen == [False, True, False, True]
    purpose_seen, rules = [], []
    for _ in range(4):  # Eyebrows: proxy as published; render on, off, on...
        st = lg.prim_shows(["Geo/E"], {"Geo/E": {"purpose": "proxy"}}, [], [], rules)
        purpose_seen.append(st["Geo/E"].render)
        rules = lg.set_show_rules(rules, lg.toggle_edits([("Geo/E", st["Geo/E"], st["Geo"])], "render"))
    assert purpose_seen == [False, True, False, True]



def test_a_toggle_reads_only_that_loader_again(make):
    """The user's report: a toggle took long and held the app; it rescanned the whole project. Now it works out that
    loader's inspector again and nothing else."""
    from tools.fx.anim_loader import logic as lg

    w, ui = _subd_window(make)
    b = w.backend
    _select(w, ui, "/stage/b")
    detail = w.ctl.subd_detail("/stage/b")
    detail["shown"] = lg.prim_shows([m.strip("/") for m in detail["plan"]], {}, [], [], [])
    calls = []
    b.set_show = lambda path, edits: calls.append("set_show")
    real_scan, real_subd = b.scan, b.subd
    b.scan = lambda infos: calls.append("scan") or real_scan(infos)
    b.subd = lambda infos: calls.append(("subd", tuple(i.path for i in infos))) or {"/stage/b": detail}
    _select(w, ui, "/stage/a")
    _select(w, ui, "/stage/b")
    w.subd_panel._toggle(w.subd_panel.tree.topLevelItem(0), 5)
    w.wait()
    assert calls == ["set_show", ("subd", ("/stage/b",))]



def _two_loader_window(make):
    """char_Helen (/stage/b) and veh_Spaceship (/stage/a), each with prims and their show states."""
    from tests.test_anim_loader_controller import _subd_backend
    from tools.fx.anim_loader import logic as lg
    from tools.fx.anim_loader.logic import SubdChoice

    mk, ui = make
    b = _subd_backend()
    plan_b = {"/Geo/Base_grp/Body_grp/Geo_Body": SubdChoice("catmullClark", "lookdev"),
              "/Geo/Outfit_grp/Geo_Dress": SubdChoice("catmullClark", "lookdev")}
    plan_a = {"/Geo/Hull_grp/Geo_Hull": SubdChoice("none", "publish"),
              "/Geo/Hull_grp/Geo_Wing": SubdChoice("none", "publish")}

    def detail(plan):
        return {"plan": plan, "faces": {m: 100 for m in plan}, "curves": {},
                "shown": lg.prim_shows([m.strip("/") for m in plan], {}, [], [], [])}

    data = {"/stage/b": detail(plan_b), "/stage/a": detail(plan_a)}
    b.subd = lambda infos: {i.path: data[i.path] for i in infos if i.path in data}
    b.set_show_many = lambda by: b.calls.append(("set_show_many", {k: tuple(v) for k, v in by.items()}))
    w = mk(b)
    for i in range(w.list_view.count()):
        r = w.list_view.item(i).data(ui.ROLE_ROW)
        w.list_view.item(i).setSelected(bool(r) and r.node_path in ("/stage/a", "/stage/b"))
    return w, ui, b


def test_several_loaders_share_the_inspector_tree(make):
    """The user's ask: the selected assets' trees together in the inspector, a branch each; a toggle over rows of
    both loaders is one call (one undo step), each edit on its own loader."""
    w, ui, b = _two_loader_window(make)
    p = w.subd_panel
    tops = {p.tree.topLevelItem(i).text(0): p.tree.topLevelItem(i) for i in range(p.tree.topLevelItemCount())}
    assert set(tops) == {"char_Helen", "veh_Spaceship"} and p.title.text() == "2 loaders"
    body = next(i for i in p._all_items() if i.text(0) == "Geo_Body")
    hull = next(i for i in p._all_items() if i.text(0) == "Geo_Hull")
    assert body.data(0, ui.ROLE_LOADER) == "/stage/b" and hull.data(0, ui.ROLE_LOADER) == "/stage/a"
    body.setSelected(True)
    hull.setSelected(True)
    p._toggle(body, 5)
    assert b.calls[-1] == ("set_show_many", {"/stage/b": (("Geo/Base_grp/Body_grp/Geo_Body", "vis", "invisible"),),
                                             "/stage/a": (("Geo/Hull_grp/Geo_Hull", "vis", "invisible"),)})
    tops = {p.tree.topLevelItem(i).text(0): p.tree.topLevelItem(i) for i in range(p.tree.topLevelItemCount())}
    menu = p.menu_for(tops["veh_Spaceship"])  # a loader's own row: all its prims (the toggle rebuilt the tree)
    _act(menu, ui.InspectorPanel.MENU_OFF).trigger()
    assert ("set_subd", "/stage/a", ("**",), "none", ui.logic.KEEP) in b.calls


def test_filter_keeps_matches_and_their_groups(make):
    w, ui, b = _two_loader_window(make)
    p = w.subd_panel
    p.filter.setText("wing")
    shown = [i.text(0) for i in p._all_items() if not i.isHidden()]
    assert set(shown) == {"veh_Spaceship", "Geo", "Hull_grp", "Geo_Wing"}
    p.filter.setText("hull_grp")  # a group that matches shows what is under it
    shown = [i.text(0) for i in p._all_items() if not i.isHidden()]
    assert set(shown) == {"veh_Spaceship", "Geo", "Hull_grp", "Geo_Hull", "Geo_Wing"}
    p.filter.setText("")
    assert all(not i.isHidden() for i in p._all_items())



def test_a_loader_row_toggles_its_instance_root(make):
    """The user's ask: the loader's own row has the toggles of its root prim (/<instance>): hiding it hides the
    asset, and the prims under it keep their own eye."""
    from tools.fx.anim_loader import logic as lg

    w, ui, b = _two_loader_window(make)
    p = w.subd_panel
    top = next(p.tree.topLevelItem(i) for i in range(p.tree.topLevelItemCount())
               if p.tree.topLevelItem(i).text(0) == "veh_Spaceship")
    assert top.data(5, ui.ROLE_TOGGLE)[0] == "eye"
    p._toggle(top, 5)
    assert b.calls[-1] == ("set_show_many", {"/stage/a": (("**", "vis", "invisible"),)})
    rules = lg.set_show_rules([], [("**", "vis", "invisible")])
    assert rules == [{"pattern": ".", "vis": "invisible"}]
    st = lg.prim_shows(["Geo/Hull_grp/Geo_Hull"], {}, [], [], rules)
    assert not st["Geo/Hull_grp/Geo_Hull"].visible and st["Geo/Hull_grp/Geo_Hull"].own_visible
