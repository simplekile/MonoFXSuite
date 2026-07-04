"""Batch load USD files from a folder into Solaris (Sublayer or Reference LOPs).

Usage (Houdini Python shell)::

    from apps.houdini.usd_batch_loader import run
    run()  # opens MONOS UI

    from apps.houdini.usd_batch_loader import load_usd_folder
    load_usd_folder(
        r"D:/shot/01_anim/publish/v001",
        mode="sublayer",
        strip_name="prop_,publish",
    )

Shelf button::

    from apps.houdini.usd_batch_loader import run; run()
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Literal

import hou

from apps.houdini.lop_usd_helpers import configure_single_file_sublayer
from tools.fx.usd_batch_loader.logic import collect_usd_files, node_name_from_label

LoadMode = Literal["sublayer", "reference"]
NODE_LAYOUT_SPACING_X = 2.5


def _log(msg: str) -> None:
    print(f"[MonoFX usd_batch_loader] {msg}", flush=True)


def _prim_path_from_label(label: str, strip_raw: str, idx: int, used: set[str]) -> str:
    stem = node_name_from_label(label, strip_raw)
    safe = re.sub(r"[^A-Za-z0-9_]", "_", stem).strip("_") or f"ref_{idx}"
    candidate = f"/{safe}"
    n = 1
    while candidate.lower() in used:
        n += 1
        candidate = f"/{safe}_{n}"
    used.add(candidate.lower())
    return candidate


def _unique_node_name(parent: hou.Node, base: str) -> str:
    name = base
    n = 1
    while parent.node(name) is not None:
        n += 1
        name = f"{base}_{n}"
    return name


def _layout_nodes_in_view(nodes: list[hou.Node]) -> None:
    """Place *nodes* in a horizontal row centered in the active Network Editor view."""
    if not nodes:
        return

    count = len(nodes)
    start_x = -((count - 1) * NODE_LAYOUT_SPACING_X) * 0.5
    for i, node in enumerate(nodes):
        node.setPosition((start_x + i * NODE_LAYOUT_SPACING_X, 0.0))

    try:
        pane = hou.ui.paneTabOfType(hou.paneTabType.NetworkEditor)
        if pane is None:
            return
        avg_x = sum(n.position()[0] for n in nodes) / count
        avg_y = sum(n.position()[1] for n in nodes) / count
        vb = pane.visibleBounds()
        center = hou.Vector2(
            (vb.min().x() + vb.max().x()) * 0.5,
            (vb.min().y() + vb.max().y()) * 0.5,
        )
        delta = center - hou.Vector2(avg_x, avg_y)
        for node in nodes:
            pos = node.position()
            node.setPosition(hou.Vector2(pos[0] + delta[0], pos[1] + delta[1]))
    except (hou.OperationFailed, AttributeError, ZeroDivisionError):
        pass


def _configure_reference_lop(ref: hou.Node, filepath: str, prim_path: str) -> bool:
    """Configure Reference LOP (create mode) for one USD file."""
    tried = False
    for base in ("filepath", "file", "filename", "filepattern"):
        for suffix in ("", "1", "0"):
            pname = f"{base}{suffix}" if suffix else base
            p = ref.parm(pname)
            if p is not None and p.parmTemplate().type() == hou.parmTemplateType.String:
                p.set(filepath)
                tried = True
                break
        if tried:
            break

    if not tried:
        _log(f"Could not find file parm on reference LOP {ref.path()}")
        return False

    for pname in ("primpath", "prim_path", "parentprimpath", "referenceprimpath"):
        p = ref.parm(pname)
        if p is not None and p.parmTemplate().type() == hou.parmTemplateType.String:
            p.set(prim_path)
            break
    else:
        _log(f"Could not find prim path parm on reference LOP {ref.path()}")
        return False

    for pname in ("referencetype", "reference_type", "payloadtype"):
        p = ref.parm(pname)
        if p is None or p.parmTemplate().type() != hou.parmTemplateType.Menu:
            continue
        for tok in ("reference", "referencefile", "usdreference", "payload", "payloadfile"):
            try:
                p.set(tok)
                break
            except hou.OperationFailed:
                continue
        break

    return True


def _resolve_parent() -> hou.Node:
    """Network where new LOPs are created — active Network Editor pwd."""
    try:
        pane = hou.ui.paneTabOfType(hou.paneTabType.NetworkEditor)
        if pane is not None:
            pwd = pane.pwd()
            if pwd is not None:
                return pwd
    except hou.OperationFailed:
        pass

    stage = hou.node("/stage")
    if stage is None:
        raise RuntimeError("Open a LOP network in the Network Editor first.")
    return stage


def load_usd_folder(
    folder: str,
    *,
    mode: LoadMode = "sublayer",
    recursive: bool = False,
    parent_prim_prefix: str = "/",
    strip_name: str = "",
) -> tuple[int, str]:
    """
    Batch-create standalone Sublayer or Reference LOPs for every USD file in *folder*.

    Nodes are created in the active Network Editor view (no selection required).
    Not wired to each other. Names from filename after *strip_name*.

    Returns ``(count, message)``.
    """
    layers = collect_usd_files(folder, recursive=recursive)
    if not layers:
        return 0, f"No USD files found in {folder!r}"

    parent = _resolve_parent()
    lop_type = "sublayer" if mode == "sublayer" else "reference"
    created_nodes: list[hou.Node] = []
    used_prim_paths: set[str] = set()
    created = 0

    for idx, (abs_path, label) in enumerate(layers):
        base = node_name_from_label(label, strip_name)
        node_name = _unique_node_name(parent, base)
        try:
            node = parent.createNode(lop_type, node_name=node_name)
        except hou.OperationFailed as exc:
            _log(f"createNode {lop_type} failed: {exc}")
            break

        ok = False
        if mode == "sublayer":
            ok = configure_single_file_sublayer(node, abs_path)
        else:
            prefix = parent_prim_prefix.rstrip("/")
            prim_path = _prim_path_from_label(label, strip_name, idx=idx, used=used_prim_paths)
            if prefix:
                prim_path = f"{prefix}{prim_path}"
            ok = _configure_reference_lop(node, abs_path, prim_path)

        if not ok:
            node.destroy()
            continue

        created_nodes.append(node)
        created += 1

    if created == 0:
        return 0, f"Could not configure any USD LOPs from {folder!r}"

    _layout_nodes_in_view(created_nodes)

    msg = f"Created {created} {lop_type} LOP(s) in {parent.path()}."
    _log(msg)
    return created, msg


def run(
    folder: str | None = None,
    *,
    mode: LoadMode | None = None,
    recursive: bool = False,
    strip_name: str = "",
) -> None:
    """Open MONOS UI (preferred). Programmatic args skip the dialog fields."""
    from tools.fx.usd_batch_loader.controller import run as _run_ui

    if folder is None and mode is None and not recursive and not strip_name:
        _run_ui()
        return

    load_mode: LoadMode = mode or "sublayer"
    count, msg = load_usd_folder(
        folder or "",
        mode=load_mode,
        recursive=recursive,
        strip_name=strip_name,
    )
    if count == 0:
        try:
            hou.ui.displayMessage(msg, severity=hou.severityType.Warning)
        except hou.OperationFailed:
            _log(msg)
    else:
        try:
            hou.ui.displayMessage(msg, severity=hou.severityType.Message)
        except hou.OperationFailed:
            _log(msg)
