"""Batch load USD files from a folder into Solaris (Sublayer or Reference LOPs).

Usage (Houdini Python shell)::

    from apps.houdini.usd_batch_loader import run
    run()  # folder picker + mode menu

    from apps.houdini.usd_batch_loader import load_usd_folder
    load_usd_folder(
        r"D:/shot/01_anim/publish/v001",
        mode="sublayer",
        connect_after=hou.node("/stage/merge1"),
    )

Shelf button::

    from apps.houdini.usd_batch_loader import run; run()
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Literal

import hou

from apps.houdini.hda.anim_publish_loader import _configure_single_file_sublayer

LoadMode = Literal["sublayer", "reference"]
USD_EXTS = (".usd", ".usda", ".usdc")
NODE_PREFIX = "usdload_"


def _log(msg: str) -> None:
    print(f"[MonoFX usd_batch_loader] {msg}", flush=True)


def _safe_node_name(label: str) -> str:
    body = Path(label).stem
    safe = re.sub(r"[^A-Za-z0-9_]", "_", body).strip("_")
    return safe or "usd"


def _prim_path_from_label(label: str, idx: int, used: set[str]) -> str:
    stem = Path(label).stem
    safe = re.sub(r"[^A-Za-z0-9_]", "_", stem).strip("_") or f"ref_{idx}"
    candidate = f"/{safe}"
    n = 1
    while candidate.lower() in used:
        n += 1
        candidate = f"/{safe}_{n}"
    used.add(candidate.lower())
    return candidate


def collect_usd_files(
    folder: str,
    *,
    recursive: bool = False,
    extensions: tuple[str, ...] = USD_EXTS,
) -> list[tuple[str, str]]:
    """Return sorted ``(abs_path, filename)`` pairs from *folder*."""
    root = os.path.normpath(folder)
    if not os.path.isdir(root):
        return []

    paths: list[str] = []
    if recursive:
        for dirpath, _dirnames, filenames in os.walk(root):
            for name in filenames:
                if name.lower().endswith(extensions):
                    paths.append(os.path.join(dirpath, name))
    else:
        for name in os.listdir(root):
            full = os.path.join(root, name)
            if os.path.isfile(full) and name.lower().endswith(extensions):
                paths.append(full)

    paths.sort(key=lambda p: os.path.basename(p).lower())
    return [(p, os.path.basename(p)) for p in paths]


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


def _stage_parent(connect_after: hou.Node | None) -> hou.Node:
    if connect_after is not None:
        return connect_after.parent()
    stage = hou.node("/stage")
    if stage is None:
        raise RuntimeError("No /stage network found. Open Solaris first.")
    return stage


def _rewire_outputs(old_node: hou.Node, new_node: hou.Node) -> None:
    """Point downstream nodes from *old_node* to *new_node*."""
    for child in old_node.parent().children():
        if child == new_node:
            continue
        for idx in range(len(child.inputConnectors())):
            try:
                if child.input(idx) == old_node:
                    child.setInput(idx, new_node)
            except hou.OperationFailed:
                continue


def _apply_display_flag(source: hou.Node | None, target: hou.Node) -> None:
    if source is None:
        return
    try:
        if source.isDisplayFlagSet():
            target.setDisplayFlag(True)
    except hou.OperationFailed:
        pass
    try:
        if source.isRenderFlagSet():
            target.setRenderFlag(True)
    except hou.OperationFailed:
        pass


def load_usd_folder(
    folder: str,
    *,
    mode: LoadMode = "sublayer",
    connect_after: hou.Node | None = None,
    recursive: bool = False,
    parent_prim_prefix: str = "/",
) -> tuple[int, str]:
    """
    Batch-create Sublayer or Reference LOPs for every USD file in *folder*.

    When *connect_after* is set, a **merge** LOP is inserted after it:
    merge input 0 = existing branch, inputs 1..N = new USD branches.
    Downstream wires and display flag move to the merge node.

    Returns ``(count, message)``.
    """
    if connect_after is None:
        connect_after = hou.node("/stage")
        if connect_after is not None:
            for n in connect_after.allSubChildren():
                if n.type().category() != hou.lopNodeTypeCategory():
                    continue
                try:
                    if n.isDisplayFlagSet():
                        connect_after = n
                        break
                except hou.OperationFailed:
                    continue

    if connect_after is not None and connect_after.type().category() != hou.lopNodeTypeCategory():
        return 0, "connect_after must be a LOP node."

    layers = collect_usd_files(folder, recursive=recursive)
    if not layers:
        return 0, f"No USD files found in {folder!r}"

    parent = _stage_parent(connect_after)
    lop_type = "sublayer" if mode == "sublayer" else "reference"
    branch_heads: list[hou.Node] = []
    used_prim_paths: set[str] = set()
    created = 0

    for idx, (abs_path, label) in enumerate(layers):
        base = _safe_node_name(label)
        node_name = f"{NODE_PREFIX}{idx}_{base}"
        try:
            node = parent.createNode(lop_type, node_name=node_name)
        except hou.OperationFailed as exc:
            _log(f"createNode {lop_type} failed: {exc}")
            break

        ok = False
        if mode == "sublayer":
            ok = _configure_single_file_sublayer(node, abs_path)
        else:
            prefix = parent_prim_prefix.rstrip("/")
            prim_path = _prim_path_from_label(label, idx=idx, used=used_prim_paths)
            if prefix:
                prim_path = f"{prefix}{prim_path}"
            ok = _configure_reference_lop(node, abs_path, prim_path)

        if not ok:
            node.destroy()
            continue

        node.moveToGoodPosition()
        branch_heads.append(node)
        created += 1

    if created == 0:
        return 0, f"Could not configure any USD LOPs from {folder!r}"

    if connect_after is None:
        msg = f"Created {created} {lop_type} LOP(s) in {parent.path()}."
        _log(msg)
        return created, msg

    try:
        merge = parent.createNode("merge", node_name=f"{NODE_PREFIX}merge")
    except hou.OperationFailed as exc:
        for n in branch_heads:
            n.destroy()
        return 0, f"Could not create merge LOP: {exc}"

    in_idx = 0
    try:
        merge.setInput(in_idx, connect_after)
        in_idx += 1
    except hou.OperationFailed:
        pass

    for head in branch_heads:
        try:
            merge.setInput(in_idx, head)
            in_idx += 1
        except hou.OperationFailed as exc:
            _log(f"merge setInput failed: {exc}")

    _rewire_outputs(connect_after, merge)
    _apply_display_flag(connect_after, merge)

    pos = connect_after.position()
    merge.setPosition((pos[0], pos[1] - 1.5))
    for i, head in enumerate(branch_heads):
        head.setPosition((pos[0] - 2.0 * (i + 1), pos[1] - 2.5))

    msg = f"Loaded {created} USD file(s) via {mode} into {merge.path()}."
    _log(msg)
    return created, msg


def _pick_folder() -> str | None:
    try:
        picked = hou.ui.selectFile(
            title="Select USD folder",
            file_type=hou.fileType.Directory,
            pattern="*",
        )
    except hou.OperationFailed:
        return None
    if not picked:
        return None
    return os.path.normpath(hou.expandString(picked))


def _pick_mode() -> LoadMode | None:
    try:
        choice = hou.ui.selectFromList(
            ["Sublayer (compose layers)", "Reference (prim per file)"],
            title="USD load mode",
            column_header="Mode",
            exclusive=True,
        )
    except hou.OperationFailed:
        return None
    if not choice:
        return None
    return "sublayer" if choice[0] == 0 else "reference"


def run(
    folder: str | None = None,
    *,
    mode: LoadMode | None = None,
    recursive: bool = False,
) -> None:
    """Interactive entry: folder picker, mode menu, load into selected/display LOP."""
    selected: hou.Node | None = None
    for n in hou.selectedNodes():
        if n.type().category() == hou.lopNodeTypeCategory():
            selected = n
            break

    if folder is None:
        folder = _pick_folder()
    if not folder:
        return

    if mode is None:
        mode = _pick_mode()
    if mode is None:
        return

    count, msg = load_usd_folder(
        folder,
        mode=mode,
        connect_after=selected,
        recursive=recursive,
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
