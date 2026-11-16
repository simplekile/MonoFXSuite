"""Mono Anim Loader manager controller (no Qt, no hou): plan Task 8."""

from __future__ import annotations

from tools.fx.anim_loader.controller import Controller, LoaderInfo, Row
from tools.fx.anim_loader.logic import STATUS_ASSET, STATUS_MISSING, STATUS_NEWER, STATUS_OFF, STATUS_OK, LoaderState


def _state(shot, inst, asset="char_X", kind="geo"):
    return LoaderState("P:/proj", shot, "v001", f"geo_{inst}.usd", asset, inst, kind,
                       {"lookdev": True, "groom": True, "cloth": True}, {"lookdev": "v001", "groom": "", "cloth": ""})


OK = (STATUS_OK, None)


class FakeBackend:
    def __init__(self):
        self.infos = [
            LoaderInfo("/stage/b", _state("sh025", "char_Helen", "char_Helen"), False),
            LoaderInfo("/stage/a", _state("sh025", "veh_Spaceship", "veh_Spaceship"), False),
            LoaderInfo("/stage/c", _state("sh025", "sh025", None, "cam"), False),
            LoaderInfo("/stage/d", _state("sh900", "char_Robot_2", None), False),
            LoaderInfo("/stage/old", None, True, legacy_name="old_robot"),
        ]
        self.status = {
            "/stage/b": {"anim": OK, "lookdev": OK, "groom": OK, "cloth": (STATUS_MISSING, None)},
            "/stage/a": {"anim": OK, "lookdev": (STATUS_NEWER, "v003"), "groom": (STATUS_OFF, None), "cloth": (STATUS_OFF, None)},
            "/stage/c": {"anim": (STATUS_NEWER, "v005"), "lookdev": (STATUS_OFF, None), "groom": (STATUS_OFF, None), "cloth": (STATUS_OFF, None)},
            "/stage/d": {"anim": OK, "lookdev": (STATUS_ASSET, None), "groom": (STATUS_ASSET, None), "cloth": (STATUS_ASSET, None)},
        }
        self.calls = []

    def loaders(self):
        return list(self.infos)

    def scan(self, infos):
        return {i.path: self.status[i.path] for i in infos if i.state is not None}

    def thumbnail(self, state):
        return f"thumb/{state.asset}.png" if state.asset else ""

    def update(self, paths, parts):
        self.calls.append(("update", tuple(paths), parts))
        return [f"{p}: moved" for p in paths]

    def load_shot(self, root, shot, version):
        self.calls.append(("load_shot", root, shot, version))
        return (["x", "y", "z"], ["k"])

    def upgrade(self, paths):
        self.calls.append(("upgrade", tuple(paths)))
        return len(paths)

    def set_asset(self, path, asset):
        self.calls.append(("set_asset", path, asset))


def _ctl():
    c = Controller(FakeBackend())
    c.refresh()
    return c


def test_rows_grouped_by_shot():
    rows = _ctl().rows()
    assert [(r.shot, r.instance) for r in rows] == [
        ("sh025", "char_Helen"), ("sh025", "veh_Spaceship"), ("sh025", "sh025"),  # camera last in its shot
        ("sh900", "char_Robot_2"), ("", "old_robot")]
    assert all(isinstance(r, Row) for r in rows)
    assert rows[0].thumb == "thumb/char_Helen.png" and rows[2].thumb == ""


def test_update_all_counts_only_behind():
    c = _ctl()
    assert c.behind_paths() == ["/stage/a", "/stage/c"]
    assert c.primary_label() == "Update 2 behind"
    c.update_all()
    assert c.backend.calls[-1] == ("update", ("/stage/a", "/stage/c"), ("anim", "lookdev", "groom", "cloth"))
    assert "moved" in c.message


def test_update_selected():
    c = _ctl()
    c.selection = ["/stage/a", "/stage/b"]
    assert c.primary_label() == "Update 1 selected"
    c.update_selected()
    assert c.backend.calls[-1][1] == ("/stage/a",)


def test_headline():
    assert _ctl().headline() == "2 behind, 1 needs an asset, 1 old loader"


def test_stale_scan_dropped():
    c = Controller(FakeBackend())
    token, infos = c.begin_scan()
    newer, _ = c.begin_scan()
    c.finish_scan(token, {"/stage/b": {"anim": (STATUS_NEWER, "v9")}})
    assert c.rows() == [] or all(r.parts.get("anim") != (STATUS_NEWER, "v9") for r in c.rows())
    c.finish_scan(newer, c.backend.scan(infos))
    assert len(c.rows()) == 5


def test_legacy_rows_offer_upgrade():
    c = _ctl()
    legacy = [r for r in c.rows() if r.legacy]
    assert [r.node_path for r in legacy] == ["/stage/old"]
    assert c.upgrade_label() == "Upgrade 1 old"
    c.upgrade_all()
    assert c.backend.calls[-1] == ("upgrade", ("/stage/old",))


def test_message_after_load_shot():
    c = _ctl()
    c.load_shot("P:/proj", "sh900", "v002")
    assert c.message == "Loaded sh900 v002: created 3, kept 1."


def test_set_asset():
    c = _ctl()
    c.set_asset("/stage/d", "char_Robot")
    assert c.backend.calls[-1] == ("set_asset", "/stage/d", "char_Robot")
    assert "char_Robot" in c.message


def test_primary_label_when_nothing_is_behind():
    c = Controller(FakeBackend())
    c.backend.status["/stage/a"]["lookdev"] = OK
    c.backend.status["/stage/c"]["anim"] = OK
    c.refresh()
    assert c.primary_label() == "Nothing to update"


def test_commands_do_not_scan_on_their_own():
    c = _ctl()
    scans = []
    c.backend.scan = lambda infos: scans.append(1) or {}
    c.update_all()
    c.load_shot("P:/proj", "sh900", "v002")
    c.upgrade_all()
    c.set_asset("/stage/d", "char_Robot")
    assert scans == []  # the window rescans on its worker thread


def test_thumbnails_come_with_the_scan():
    c = Controller(FakeBackend())
    c.backend.thumbnail = lambda state: (_ for _ in ()).throw(AssertionError("thumbnail on the main thread"))
    token, infos = c.begin_scan()
    c.finish_scan(token, FakeBackend().scan(infos), {"/stage/b": "t/helen.png"})
    assert next(r for r in c.rows() if r.node_path == "/stage/b").thumb == "t/helen.png"
