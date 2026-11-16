"""Mono Anim Loader manager window: what it shows and what its buttons do (no Qt, no hou).

The window (``ui.py``) draws ``rows()`` in a List or a Grid and calls the commands; a backend does the
scene work (``apps/houdini/anim_loader_adapter.py`` in Houdini, a fake in tests). Reading the loaders is on
the main thread (hou); ``scan`` reads the disk and may run on a worker thread: ``begin_scan`` /
``finish_scan`` drop a result that a newer scan replaced. Spec docs/plans/anim_loader_v2_2.md 5.5.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from tools.fx.anim_loader.logic import STATUS_ASSET, STATUS_MISSING, STATUS_NEWER, LoaderState

ALL_PARTS = ("anim", "lookdev", "groom", "cloth")
Status = dict[str, tuple[str, str | None]]


@dataclass(frozen=True)
class LoaderInfo:
    """A loader node as read on the main thread: its path, its state (None for a 2.1 node) and whether it is 2.1."""

    path: str
    state: LoaderState | None
    legacy: bool
    legacy_name: str = ""


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

    # --- reading ---------------------------------------------------------------------------------
    def begin_scan(self) -> tuple[int, list[LoaderInfo]]:
        """Reads the loaders (main thread). Returns a token and what ``backend.scan`` must read."""
        self._token += 1
        self._infos = self.backend.loaders()
        return self._token, list(self._infos)

    def finish_scan(self, token: int, status: dict[str, Status], thumbs: dict[str, str] | None = None) -> bool:
        """Takes a scan's result (status and thumbnail paths, both read off the main thread) unless a newer scan
        started since; True when taken."""
        if token != self._token:
            return False
        self._status = status
        self._thumbs = thumbs
        self._rows = self._make_rows()
        return True

    def scan_job(self, infos: list[LoaderInfo]) -> tuple[dict[str, Status], dict[str, str]]:
        """Everything a scan reads from disk; safe on a worker thread."""
        return self.backend.scan(infos), {i.path: self.backend.thumbnail(i.state) for i in infos if i.state}

    def refresh(self) -> None:
        """Reads and scans now, on the calling thread (tests; the window scans on its worker)."""
        token, infos = self.begin_scan()
        self.finish_scan(token, *self.scan_job(infos))

    def _make_rows(self) -> list[Row]:
        rows = []
        for info in self._infos:
            st = info.state
            if st is None:
                rows.append(Row(info.path, "", info.legacy_name or info.path.rsplit("/", 1)[-1], "geo", None,
                                legacy=True))
                continue
            rows.append(Row(info.path, st.shot, st.instance_name, st.kind, st.asset,
                            self._status.get(info.path, {}), info.legacy,
                            (self._thumbs or {}).get(info.path, ""), {"anim": st.anim_version, **st.versions}))
        return sorted(rows, key=lambda r: (r.legacy, r.shot, r.kind == "cam", r.instance.lower()))

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
            return "No anim loaders in the scene"
        parts = [f"{behind} behind"] if behind else []
        if asset:
            parts.append(f"{asset} {'needs' if asset == 1 else 'need'} an asset")
        if legacy:
            parts.append(_plural(legacy, "old loader"))
        return ", ".join(parts) if parts else "All up to date"

    def primary_label(self) -> str:
        if self.selection:
            n = len(self.behind_paths(self.selection))
            return f"Update {n} selected" if n else "Nothing selected to update"
        n = len(self.behind_paths())
        return f"Update {n} behind" if n else "Nothing to update"

    def upgrade_label(self) -> str:
        return f"Upgrade {len(self.legacy_paths())} old"

    # --- commands ---------------------------------------------------------------------------------
    def _update(self, paths: list[str]) -> None:
        if not paths:
            self.message = "Nothing to update."
            return
        lines = self.backend.update(paths, ALL_PARTS)
        self.message = "; ".join(lines) if lines else "Already up to date."

    def update_all(self) -> None:
        self._update(self.behind_paths())

    def update_selected(self) -> None:
        self._update(self.behind_paths(self.selection))

    def primary(self) -> None:
        self.update_selected() if self.selection else self.update_all()

    def load_shot(self, root: str, shot: str, version: str) -> None:
        created, kept = self.backend.load_shot(root, shot, version)
        self.message = f"Loaded {shot} {version}: created {len(created)}, kept {len(kept)}."

    def upgrade_all(self) -> None:
        paths = self.legacy_paths()
        n = self.backend.upgrade(paths) if paths else 0
        self.message = f"Upgraded {_plural(n, 'loader')} to 2.2." if n else "No old loaders."

    def set_asset(self, path: str, asset: str) -> None:
        self.backend.set_asset(path, asset)
        self.message = f"{path.rsplit('/', 1)[-1]} is now {asset}."
