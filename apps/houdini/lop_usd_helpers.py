"""Shared Solaris LOP helpers — configure Sublayer / Reference (no anim_publish logging)."""

from __future__ import annotations

import hou


def _parm_set_menu_index(parm: hou.Parm, index: int) -> bool:
    if index < 0:
        return False
    try:
        parm.set(index)
        return True
    except hou.OperationFailed:
        pass
    try:
        items = parm.menuItems()
        if index < len(items):
            parm.set(items[index])
            return True
    except hou.OperationFailed:
        pass
    return False


def _parm_set_menu_contains(parm: hou.Parm, substring: str) -> bool:
    try:
        labels = parm.menuLabels()
    except hou.OperationFailed:
        return False
    sub = substring.lower()
    for i, lab in enumerate(labels):
        if sub in lab.lower():
            return _parm_set_menu_index(parm, i)
    return False


def _iter_menu_parms(n: hou.Node):
    for p in n.parms():
        if p.parmTemplate().type() == hou.parmTemplateType.Menu:
            yield p


def _pick_sublayer_files_menu_index(items: list[str], labels: list[str]) -> int | None:
    for i, (tok, lab) in enumerate(zip(items, labels)):
        t = str(tok).lower()
        l = lab.lower()
        if t in ("files", "sublayerfiles", "filesonly", "fromfiles", "disk"):
            if "input" not in t:
                return i
        if "input" in l and "file" in l and (" and " in l or " und " in l):
            continue
        if l.strip() in ("sublayer files", "reference files"):
            return i
        if "file" in l and "input" not in l and "sublayer" in l:
            return i
    n = len(items)
    if n == 3:
        return 1
    if n == 2:
        for i, lab in enumerate(labels):
            if "input" not in lab.lower():
                return i
        return 0
    return None


def _sublayer_file_row_parm_usable(sl: hou.Node) -> bool:
    for name in (
        "filepath1",
        "file1",
        "filename1",
        "sublayerfile1_file",
        "sublayers1_file",
        "sublayerfile1_filepath",
        "sublayerfile1_filepattern",
    ):
        fp = sl.parm(name)
        if fp is None:
            continue
        try:
            if fp.isDisabled():
                continue
        except hou.OperationFailed:
            return True
        return True
    for p in sl.parms():
        if p.parmTemplate().type() != hou.parmTemplateType.String:
            continue
        n = p.name().lower()
        if "findsublayer" in n or "find_sublayer" in n:
            continue
        if "sublayer" in n and "file" in n:
            try:
                if p.isDisabled():
                    continue
            except hou.OperationFailed:
                return True
            return True
    return False


def _iter_sublayertype_parms(sl: hou.Node):
    seen: set[int] = set()
    for pname in (
        "sublayertype",
        "sublayer_type",
        "sublayerkind",
        "layerstype",
        "method",
    ):
        p = sl.parm(pname)
        if p is None or p.parmTemplate().type() != hou.parmTemplateType.Menu:
            continue
        pid = id(p)
        if pid not in seen:
            seen.add(pid)
            yield p
    for p in _iter_menu_parms(sl):
        n = p.name().lower()
        if "sublayertype" in n or n.endswith("_sublayertype"):
            pid = id(p)
            if pid not in seen:
                seen.add(pid)
                yield p
            continue
        lab = (p.parmTemplate().label() or "").lower()
        if "sublayer" in lab and "type" in lab:
            pid = id(p)
            if pid not in seen:
                seen.add(pid)
                yield p


def _sublayer_ensure_one_file_slot(sl: hou.Node) -> None:
    for gname in (
        "sublayerfile_group1",
        "sublayerfile1_group",
        "sublayerfile_group_1",
    ):
        gp = sl.parm(gname)
        if gp is not None:
            try:
                gp.set(1)
            except hou.OperationFailed:
                pass

    for pname in (
        "num_files",
        "numfiles",
        "sublayerfilecount",
        "sublayers",
        "sublayercount",
    ):
        p = sl.parm(pname)
        if p is not None:
            try:
                p.set(1)
            except hou.OperationFailed:
                pass
            return


def _apply_sublayer_files_to_parm(sl: hou.Node, p: hou.Parm) -> bool:
    tokens = (
        "sublayerfiles",
        "sublayer_files",
        "files",
        "filesonly",
        "fileonly",
        "fromfiles",
        "fromdisk",
        "sublayerfromfiles",
        "sublayerfromfile",
        "fileslayers",
        "layersfromfiles",
    )
    for tok in tokens:
        try:
            p.set(tok)
        except hou.OperationFailed:
            continue
        _sublayer_ensure_one_file_slot(sl)
        if _sublayer_file_row_parm_usable(sl):
            return True

    try:
        items = list(p.menuItems())
        labels = list(p.menuLabels())
    except hou.OperationFailed:
        return False

    idx = _pick_sublayer_files_menu_index(items, labels)
    if idx is not None and _parm_set_menu_index(p, idx):
        _sublayer_ensure_one_file_slot(sl)
        if _sublayer_file_row_parm_usable(sl):
            return True

    for i in range(len(items)):
        if not _parm_set_menu_index(p, i):
            continue
        _sublayer_ensure_one_file_slot(sl)
        if _sublayer_file_row_parm_usable(sl):
            return True
    return False


def _sublayer_set_mode_files(sl: hou.Node) -> bool:
    for p in _iter_sublayertype_parms(sl):
        try:
            items = list(p.menuItems())
        except hou.OperationFailed:
            continue

        desired = None
        for it in items:
            tl = str(it).lower()
            if tl in ("files", "sublayerfiles", "sublayer_files", "filesonly"):
                desired = it
                break

        if desired is None:
            for it in items:
                tl = str(it).lower()
                if "files" in tl and "filesandinputs" not in tl and "inputs" not in tl:
                    desired = it
                    break

        if desired is not None:
            try:
                p.set(desired)
            except hou.OperationFailed:
                pass
            _sublayer_ensure_one_file_slot(sl)
            if _sublayer_file_row_parm_usable(sl):
                return True
            try:
                cur = str(p.evalAsString()).lower()
                if "filesandinputs" not in cur and "inputs" not in cur and "files" in cur:
                    return True
            except hou.OperationFailed:
                if _sublayer_file_row_parm_usable(sl):
                    return True

        if _apply_sublayer_files_to_parm(sl, p):
            return True

    return _sublayer_file_row_parm_usable(sl)


def _sublayer_set_weakest_position(sl: hou.Node) -> None:
    for pname in ("sublayerposition", "sublayer_position", "layerposition"):
        p = sl.parm(pname)
        if p is not None:
            _parm_set_menu_contains(p, "weakest")
            return
    for p in sl.parms():
        t = p.parmTemplate()
        if t.type() != hou.parmTemplateType.Menu:
            continue
        label = (t.label() or "").lower()
        if "position" in label and "sublayer" in label:
            _parm_set_menu_contains(p, "weakest")
            return


def configure_single_file_sublayer(sl: hou.Node, filepath: str) -> bool:
    """Configure one Sublayer LOP for a single USD file on disk."""
    _sublayer_set_mode_files(sl)
    _sublayer_ensure_one_file_slot(sl)

    tried = False
    for base in ("file", "filepath", "filename", "filepattern"):
        for suffix in ("1", "0"):
            p = sl.parm(f"{base}{suffix}")
            if p is not None and p.parmTemplate().type() == hou.parmTemplateType.String:
                p.set(filepath)
                tried = True
                break
        if tried:
            break

    if not tried:
        for p in sl.parms():
            n = p.name().lower()
            if p.parmTemplate().type() != hou.parmTemplateType.String:
                continue
            if n in ("findsublayers", "find_sublayers"):
                continue
            if "file" in n and "pattern" not in n:
                p.set(filepath)
                tried = True
                break

    if not tried:
        return False

    _sublayer_set_weakest_position(sl)
    return True
