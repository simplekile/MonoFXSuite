"""Mono Anim Loader manager window: what it shows and what its buttons do (no Qt, no hou).

The window (``ui.py``) draws ``rows()`` in a List or a Grid and calls the commands; a backend does the
scene work (``apps/houdini/anim_loader_adapter.py`` in Houdini, a fake in tests). Reading the loaders is on
the main thread (hou); ``scan`` reads the disk and may run on a worker thread: ``begin_scan`` /
``finish_scan`` drop a result that a newer scan replaced. Spec docs/plans/anim_loader_v2_2.md 5.5.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from tools.fx.anim_loader import logic
from tools.fx.anim_loader.logic import KEEP, STATUS_ASSET, STATUS_MISSING, STATUS_NEWER, LoaderState

ALL_PARTS = ("anim", "lookdev", "groom", "cloth")
Status = dict[str, tuple[str, str | None]]


@dataclass(frozen=True)
class LoaderInfo:
    """A loader node as read on the main thread: its path, its state (None for a 2.1 node) and whether it is 2.1."""

    path: str
    state: LoaderState | None
    legacy: bool
    legacy_name: str = ""
    subd_rules: str = ""
    layer: Any = None  # a Sublayer / Reference file reading a publish (logic.PublishRef); its node is no loader


@dataclass(frozen=True)
class Row:
    node_path: str
    shot: str
    instance: str
    kind: str
    asset: str | None
    parts: Status = field(default_factory=dict)
    legacy: bool = False
    thumb: str = ""
    versions: dict[str, str] = field(default_factory=dict)
    subd: tuple[int, int] | None = None  # (subdivided meshes, estimated viewport polygons)
    asset_source: bool = False  # Source Asset: the asset's model (no shot); Load shot and Retarget leave it
    weight: int = 0  # bytes of the files its lookdev pulls (textures), 0 when unknown
    layer: str = ""  # a Sublayer / Reference reading a publish: what it reads ("lookdev v001 of prop_Cliff01")

    @property
    def behind(self) -> bool:
        return any(s == STATUS_NEWER for s, _ in self.parts.values())

    @property
    def needs_asset(self) -> bool:
        return any(s == STATUS_ASSET for s, _ in self.parts.values())

    @property
    def missing(self) -> bool:
        return any(s == STATUS_MISSING for s, _ in self.parts.values())


class Backend(Protocol):
    def loaders(self) -> list[LoaderInfo]: ...
    def scan(self, infos: list[LoaderInfo]) -> dict[str, Status]: ...
    def thumbnail(self, state: LoaderState) -> str: ...
    def update(self, paths: list[str], parts: tuple[str, ...]) -> list[str]: ...
    def load_shot(self, root: str, shot: str, version: str) -> tuple[list[str], list[str]]: ...
    def upgrade(self, paths: list[str]) -> int: ...
    def set_asset(self, path: str, asset: str) -> None: ...


def _plural(n: int, one: str, many: str | None = None) -> str:
    return f"{n} {one if n == 1 else (many or one + 's')}"


class Controller:
    def __init__(self, backend: Any) -> None:
        self.backend = backend
        self.selection: list[str] = []
        self.message = ""
        self._infos: list[LoaderInfo] = []
        self._status: dict[str, Status] = {}
        self._token = 0
        self._rows: list[Row] = []
        self._thumbs: dict[str, str] | None = None
        self._subd: dict[str, dict] = {}
        self.target_shot = ""  # the shot in the window's Load shot box
        self.target_root = ""  # the project of that box
        self.soloed: list[str] = []  # view state: loaders soloed in the viewport (never saved)
        self._extras: dict = {}
        self.scene_shot = ""   # the shot of the open scene ($HIP), "" when it is no shot's

    # --- reading ---------------------------------------------------------------------------------
    def begin_scan(self) -> tuple[int, list[LoaderInfo]]:
        """Reads the loaders (main thread). Returns a token and what ``backend.scan`` must read."""
        self._token += 1
        self._infos = self.backend.loaders()
        return self._token, list(self._infos)

    def finish_scan(self, token: int, status: dict[str, Status], thumbs: dict[str, str] | None = None,
                    subd: dict[str, dict] | None = None, extras: dict | None = None) -> bool:
        """Takes a scan's result (status and thumbnail paths, both read off the main thread) unless a newer scan
        started since; True when taken."""
        if token != self._token:
            return False
        self._status = status
        self._thumbs = thumbs
        self._subd = subd or {}
        self._extras = extras or {}
        self._rows = self._make_rows()
        return True

    def scan_job(self, infos: list[LoaderInfo]) -> tuple[dict[str, Status], dict[str, str]]:
        """Everything a scan reads from disk; safe on a worker thread."""
        subd = self.backend.subd(infos) if hasattr(self.backend, "subd") else {}
        extras = (self.backend.extras(infos, self.target_root, self.target_shot)
                  if hasattr(self.backend, "extras") else {})
        return (self.backend.scan(infos), {i.path: self.backend.thumbnail(i.state) for i in infos if i.state}, subd,
                extras)

    def refresh(self) -> None:
        """Reads and scans now, on the calling thread (tests; the window scans on its worker)."""
        token, infos = self.begin_scan()
        self.finish_scan(token, *self.scan_job(infos))

    def _make_rows(self) -> list[Row]:
        rows = []
        for info in self._infos:
            st = info.state
            ref = getattr(info, "layer", None)
            if ref is not None:  # a Sublayer / Reference reading a publish: kind "layer"
                rows.append(Row(info.path, "", info.legacy_name or info.path.rsplit("/", 1)[-1], "layer", ref.entity,
                                self._status.get(info.path, {}), False, "", {ref.part: ref.version},
                                layer=f"{ref.word} {ref.version} of {ref.entity}"))
                continue
            if st is None:
                rows.append(Row(info.path, "", info.legacy_name or info.path.rsplit("/", 1)[-1], "geo", None,
                                legacy=True))
                continue
            asset_source = logic.is_asset(st)
            rows.append(Row(info.path, "" if asset_source else st.shot, st.instance_name, st.kind, st.asset,
                            self._status.get(info.path, {}), info.legacy,
                            (self._thumbs or {}).get(info.path, ""), {"anim": logic.main_version(st), **st.versions},
                            self._subd_summary(info.path), asset_source,
                            self._extras.get("weight", {}).get(info.path, 0)))
        return sorted(rows, key=lambda r: (r.legacy, r.kind == "layer", r.asset_source, r.shot, r.kind == "cam",
                                           r.instance.lower()))

    def rows(self) -> list[Row]:
        return list(self._rows)

    def shots(self) -> list[str]:
        return sorted({r.shot for r in self._rows if r.shot})

    # --- what the bar says ------------------------------------------------------------------------
    def behind_paths(self, only: list[str] | None = None) -> list[str]:
        return [r.node_path for r in self._rows if r.behind and not r.legacy
                and (only is None or r.node_path in only)]

    def legacy_paths(self) -> list[str]:
        return [r.node_path for r in self._rows if r.legacy]

    def headline(self) -> str:
        behind = len(self.behind_paths())
        asset = sum(1 for r in self._rows if r.needs_asset)
        legacy = len(self.legacy_paths())
        if not self._rows:
            return "No loaders in the scene"
        parts = [f"{behind} behind"] if behind else []
        if legacy and not behind:
            parts.append(_plural(legacy, "old loader") + " to upgrade")
        if asset:
            parts.append(f"{asset} {'needs' if asset == 1 else 'need'} an asset")
        if legacy and behind:
            parts.append(_plural(legacy, "old loader"))
        action = self.primary_action()
        if action and action[0] == "retarget":  # the headline says what the primary button does
            paths = set(self.retarget_paths())
            shots = sorted({r.shot for r in self._rows if r.node_path in paths})
            parts.insert(0, _plural(len(paths), "loader") + f" from {', '.join(shots)}, not {self.target_shot}")
        return ", ".join(parts) if parts else "All up to date"

    def heavy_polygons(self) -> int:
        """The shot's estimated viewport subdivision polygons when over the threshold and Draw Hulls Only is off."""
        from tools.fx.anim_loader.logic import HEAVY_SUBD_POLYGONS

        total = sum(r.subd[1] for r in self._rows if r.subd)
        hulls = getattr(self.backend, "hulls_on", None)
        if total <= HEAVY_SUBD_POLYGONS or (hulls is not None and hulls()):
            return 0
        return total

    def retarget_paths(self) -> list[str]:
        """Loaders to move to ``target_shot``: the selected ones from another shot; with nothing selected and the box
        on the scene's own shot, every loader from another shot (nodes copied over from that shot)."""
        if not self.target_shot:
            return []
        off = [r.node_path for r in self._rows if not r.legacy and r.shot and r.shot != self.target_shot]
        if self.selection:
            return [p for p in off if p in self.selection]
        return off if self.target_shot == self.scene_shot else []

    def retarget_label(self) -> str:
        return f"Retarget {len(self.retarget_paths())} to {self.target_shot}"

    def primary_action(self) -> tuple[str, str] | None:
        """The one thing worth doing now, most important first: retarget loaders copied from another shot, update,
        upgrade 2.1 loaders. (A heavy shot is a note with Draw Hulls Only on the status line, not a primary.)"""
        if self.retarget_paths() and not self.selection:
            return "retarget", self.retarget_label()
        if self.selection:
            n = len(self.behind_paths(self.selection))
            if n:
                return "update", f"Update {n} selected"
            if self.retarget_paths():
                return "retarget", self.retarget_label()
        n = len(self.behind_paths())
        if n:
            return "update", f"Update {n} behind"
        if self.legacy_paths():
            return "upgrade", self.upgrade_label()
        return None

    def primary_label(self) -> str:
        if self.selection:
            n = len(self.behind_paths(self.selection))
            return f"Update {n} selected" if n else "Nothing to update"
        n = len(self.behind_paths())
        return f"Update {n} behind" if n else "Nothing to update"

    def upgrade_label(self) -> str:
        return f"Upgrade {len(self.legacy_paths())} old"

    # --- commands ---------------------------------------------------------------------------------
    def layer_paths(self, only: list[str] | None = None) -> list[str]:
        return [r.node_path for r in self._rows if r.kind == "layer" and (only is None or r.node_path in only)]

    def _update(self, paths: list[str]) -> None:
        if not paths:
            self.message = "Nothing to update."
            return
        layers = set(self.layer_paths(paths))
        lines = []
        if layers and hasattr(self.backend, "update_layers"):
            lines += self.backend.update_layers([p for p in paths if p in layers])
        rest = [p for p in paths if p not in layers]
        if rest:
            lines += self.backend.update(rest, ALL_PARTS)
        self.message = "; ".join(lines) if lines else "Already up to date."

    def update_all(self) -> None:
        self._update(self.behind_paths())

    def update_selected(self) -> None:
        self._update(self.behind_paths(self.selection))

    def primary(self) -> None:
        action = self.primary_action()
        kind = action[0] if action else None
        if kind == "update":
            self.update_selected() if self.selection and self.behind_paths(self.selection) else self.update_all()
        elif kind == "upgrade":
            self.upgrade_all()
        elif kind == "retarget":
            self.retarget()
        elif kind == "hulls":
            self.draw_hulls()

    def draw_hulls(self) -> None:
        """Draw Hulls Only on the viewports showing /stage (they keep display options of their own)."""
        n = self.backend.set_hulls_only()
        if not n:
            self.message = "No viewer shows /stage: open the stage in a Scene Viewer, then Draw Hulls Only."
            return
        self.message = (f"Draw Hulls Only on in {n} viewport{'s' if n != 1 else ''}: lighter to draw "
                        "and less memory (Helen 12.8 GB -> 7.2 GB).")

    def load_shot(self, root: str, shot: str, version: str) -> None:
        created, kept = self.backend.load_shot(root, shot, version)
        self.message = f"Loaded {shot} {version}: created {len(created)}, kept {len(kept)}."

    def upgrade_all(self) -> None:
        paths = self.legacy_paths()
        n = self.backend.upgrade(paths) if paths else 0
        self.message = f"Upgraded {_plural(n, 'loader')} to 2.2." if n else "No old loaders."

    def retarget(self, paths: list[str] | None = None) -> None:
        paths = paths if paths is not None else self.retarget_paths()
        if not paths:
            self.message = "Nothing to retarget."
            return
        moved, left = self.backend.retarget(paths, self.target_shot)
        self.message = "; ".join([f"Retargeted {len(moved)} to {self.target_shot}", *left])

    def convert_layers(self, paths: list[str]) -> None:
        """Sublayers reading an asset publish -> MonoFX Loaders (Source Asset), patterns after them moved."""
        paths = self.layer_paths(paths)
        if not paths:
            self.message = "Pick the sublayers to convert."
            return
        done, notes = self.backend.convert_layers(paths)
        self.message = "; ".join([f"Converted {_plural(len(done), 'sublayer')}: " + ", ".join(done), *notes]) \
            if done else ("; ".join(notes) or "Nothing converted.")

    def set_asset(self, path: str, asset: str) -> None:
        self.backend.set_asset(path, asset)
        self.message = f"{path.rsplit('/', 1)[-1]} is now {asset}."

    # --- manager A: add, view, links, what is new, hand off (the user's pick, 2026-11-17) ---------------------
    def news(self, path: str) -> list:
        """What is new for a loader (logic.WhatsNew per behind part), as the last scan read it."""
        return list(self._extras.get("news", {}).get(path, []))

    def gaps(self) -> tuple[str, list]:
        """(newest anim version, outputs no loader stands for) of the shot in the box."""
        return self._extras.get("gaps", ("", []))

    def gap_line(self) -> str:
        version, missing = self.gaps()
        if not missing:
            return ""
        names = ", ".join(o.file.rsplit(".", 1)[0].removeprefix("geo_").removeprefix("cam_") for o in missing[:3])
        more = f" +{len(missing) - 3}" if len(missing) > 3 else ""
        return f"+{len(missing)} in {self.target_shot} {version}: {names}{more}"

    def add_missing(self) -> None:
        version, missing = self.gaps()
        if not missing:
            self.message = "The scene has every output of the shot."
            return
        created, kept = self.backend.load_shot(self.target_root, self.target_shot, version)
        self.message = f"Added {_plural(len(created), 'loader')} from {self.target_shot} {version}."

    def add_assets(self, names: list[str]) -> None:
        if not names:
            self.message = "Pick the assets to add."
            return
        created, kept = self.backend.add_assets(self.target_root, names)
        bits = [f"Added {_plural(len(created), 'asset')}"]
        if kept:
            bits.append(f"{', '.join(kept)} already in the network")
        self.message = "; ".join(bits) + "."

    def weight_total(self) -> int:
        return sum(r.weight for r in self._rows)

    def toggle_solo(self) -> None:
        """Solo the selected loaders in the viewport, or clear the solo (view state, not undoable)."""
        if self.soloed:
            self.backend.solo([])
            self.soloed = []
            self.message = "Solo off."
            return
        if not self.selection:
            self.message = "Select the loaders to solo."
            return
        self.backend.solo(self.selection)
        self.soloed = list(self.selection)
        self.message = f"Solo: {_plural(len(self.soloed), 'loader')} in the viewport."

    def viewport_part_on(self, part: str) -> bool:
        fn = getattr(self.backend, "viewport_part_on", None)
        return bool(fn(part)) if fn else True

    def toggle_viewport_part(self, part: str) -> None:
        on = not self.viewport_part_on(part)
        n = self.backend.set_viewport_part(part, on)
        self.message = f"{part.title()} {'shown' if on else 'hidden'} in the viewport on {_plural(n, 'loader')}."

    def set_source(self, source: str, paths: list[str] | None = None) -> None:
        paths = paths if paths is not None else list(self.selection)
        n = self.backend.set_source(paths, source)
        self.message = (f"{_plural(n, 'loader')} on Source {source.title()}." if n
                        else f"Already on Source {source.title()}.")

    def frame(self, path: str) -> None:
        self.message = "" if self.backend.frame(path) else "No Scene Viewer to frame it in."

    def open_folder(self, path: str) -> None:
        self.message = "" if self.backend.open_folder(path) else "No folder for this loader."

    def open_monos(self, path: str) -> None:
        self.message = "" if self.backend.open_monos(path) else "Monos could not open this loader's asset or shot."

    def handoff(self, out_dir: str, paths: list[str] | None = None) -> None:
        paths = paths if paths is not None else (list(self.selection) or
                                                 [r.node_path for r in self._rows if not r.legacy and r.kind == "geo"])
        if not out_dir or not paths:
            self.message = "Nothing to hand off."
            return
        lines = self.backend.handoff(paths, out_dir)
        self.message = "Handed off " + "; ".join(lines) if lines else "Nothing was written."

    # --- subdivision ----------------------------------------------------------------------------------
    def _subd_summary(self, path: str) -> tuple[int, int] | None:
        from tools.fx.anim_loader.logic import SUBD_NONE, subd_polygons

        d = self._subd.get(path)
        if not d:
            return None
        n = sum(1 for c in d["plan"].values() if c.scheme != SUBD_NONE)
        return (n, subd_polygons(d["faces"], d["plan"])) if n else None

    def subd_detail(self, path: str) -> dict | None:
        """{"plan": {mesh: SubdChoice}, "faces": {mesh: n}} of a loader, as the last scan read it."""
        return self._subd.get(path)

    def set_subd(self, path: str, patterns: list[str], scheme: str | None, dicing: Any = KEEP) -> None:
        """``scheme`` None keeps each pattern's scheme; ``dicing`` left out keeps its dicing, None clears it."""
        self.backend.set_subd(path, patterns, scheme, dicing)
        n = len(patterns)
        what = _plural(n, "item")
        parts = []
        if scheme is not None:
            parts.append({"none": "Off", "catmullClark": "Catmull-Clark", "publish": "Publish"}.get(scheme, scheme))
        if dicing is not KEEP:
            parts.append(f"dicing {dicing:g}" if dicing is not None else "dicing cleared")
        self.message = f"{path.rsplit('/', 1)[-1]}: {', '.join(parts)} on {what} (shot override)."

    def clear_subd(self, path: str, patterns: list[str] | None) -> None:
        self.backend.clear_subd(path, patterns)
        self.message = f"{path.rsplit('/', 1)[-1]}: overrides cleared, lookdev / publish decide again."

    def subd_to_asset(self, path: str) -> None:
        n = self.backend.subd_to_asset(path)
        self.message = f"Subdivision overrides copied to {n} other instance{'s' if n != 1 else ''} of the asset."
