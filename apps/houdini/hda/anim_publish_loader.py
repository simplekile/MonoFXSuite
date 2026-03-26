"""HDA helpers: load shot **anim publish** USD layers from a version folder (e.g. ``.../01_anim/publish/v001``).

Reads ``publish_meta.json`` when present (``outputs[].file``, ``fps``, ``playback_range``). Optionally
merges USD files on disk whose names start with ``geo_`` or ``cam_``.

**HDA layout (recommended):** Subnet LOP (saved as HDA is OK — type name is no longer ``subnet``)
with an internal **output** LOP (type name ``output``; display name ``OUT`` is fine).
A **Reload** button calls :func:`cb_rebuild` to rebuild, per USD file: **sublayer** → **restructurescenegraph**
(reparent roots under ``/{stem}`` where *stem* is the filename without ``geo_``/``cam_`` prefix or extension),
then all branches into a **merge** LOP → **output**. Existing non-``animload_`` input to ``OUT`` becomes
**merge** input 0 so you can stack a lookdev branch ahead of the published anim layers.

**Parms**

- ``anim_publish_dir`` — absolute path to the version folder (contains ``publish_meta.json`` and USD files).
- ``anim_publish_parent`` — optional; parent ``publish`` folder containing ``v001``, ``v002``, …
- ``anim_version`` — string; menu from :func:`menu_anim_version_list` when using ``anim_publish_parent``.
- ``use_publish_meta`` — default on: include files listed in ``publish_meta.json`` ``outputs``.
- ``scan_geo_cam_prefix`` — default on: add ``geo_*.usd`` / ``cam_*.usd`` (and ``.usdc``) in the folder.
- ``apply_timeline`` — set Houdini FPS / playback range from meta when possible.
- ``reload`` / callback — :func:`cb_rebuild`

**Python Module** on the HDA (example)::

    from apps.houdini.hda.anim_publish_loader import *

Menu (single-line expression)::

    hou.phm().menu_anim_version_list(hou.pwd())

Reload callback::

    hou.phm().cb_rebuild(kwargs)

Additional helper API (compute-only; does not create any LOP/subLayer nodes)
-------------------------------------------------------------------------------
For the new HDA variant that you described ("1 HDA loads 1 USD file", and "do not create new sublayer nodes"):
- Use the functions:
  - ``cb_autofill_anim_publish_from_hip(kwargs)``: auto-resolve ``anim_publish_parent``/``anim_version`` from the current ``.hiplc`` path.
  - ``menu_anim_geo_usd_list(node)`` / ``menu_anim_cam_usd_list(node)``: menus for USD files inside the active version.
  - ``cb_on_geo_usd_change(kwargs)`` / ``cb_on_cam_usd_change(kwargs)``: set string parms with resolved paths (anim + lookdev for geo).
  - ``cb_apply_anim_timeline(kwargs)``: apply ``fps`` / ``playback_range`` from ``publish_meta.json``.

These callbacks only write into *string parameters* if those parms exist on your HDA:
- Anim selected path candidates:
  - ``anim_sublayer_path``, ``selected_anim_usd_path``, ``geo_anim_sublayer_path``, ``cam_anim_sublayer_path``
- Lookdev selected path candidates (geo only):
  - ``lookdev_sublayer_path``, ``selected_lookdev_usd_path``, ``geo_lookdev_sublayer_path``
"""

from __future__ import annotations

import json
import os
import re
from typing import Any

import hou

ANIM_PUBLISH_CONSOLE_LOG = True
ANIMLOAD_PREFIX = "animload_"
META_NAME = "publish_meta.json"
USD_EXTS = (".usd", ".usda", ".usdc")
KNOWN_LOOKDEV_ASSET_TYPES = ("char", "prop", "env", "veh")
# Reparent: Houdini prim pattern for prims to move under the new parent (default = root children).
RESTRUCTURE_PRIM_PATTERN = "/*"
MERGE_NODE_NAME = f"{ANIMLOAD_PREFIX}merge"
_STRIP_FILENAME_PREFIXES = ("geo_", "cam_")


def _log(msg: str) -> None:
    if ANIM_PUBLISH_CONSOLE_LOG:
        print(f"[MonoFX anim_publish_loader] {msg}", flush=True)


def _version_key(v: str) -> int:
    m = re.search(r"(\d+)", v)
    return int(m.group(1)) if m else -1


def _expanded_dir(node: hou.Node, raw: str) -> str:
    s = raw.strip() if raw else ""
    if not s:
        return ""
    try:
        return os.path.normpath(hou.expandString(s))
    except Exception:
        return os.path.normpath(os.path.expandvars(s))


def resolve_publish_folder(node: hou.Node) -> str:
    """Return absolute path to the active version folder (``anim_publish_dir`` or parent + version)."""
    direct = _expanded_dir(node, node.evalParm("anim_publish_dir") if node.parm("anim_publish_dir") else "")
    if direct and os.path.isdir(direct):
        return direct
    parent_parm = node.parm("anim_publish_parent")
    ver_parm = node.parm("anim_version")
    if parent_parm and ver_parm:
        parent = _expanded_dir(node, parent_parm.evalAsString())
        ver = ver_parm.evalAsString().strip()
        if parent and ver:
            joined = os.path.normpath(os.path.join(parent, ver))
            if os.path.isdir(joined):
                return joined
    return direct


def load_publish_meta(folder: str) -> dict[str, Any] | None:
    path = os.path.join(folder, META_NAME)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except (OSError, json.JSONDecodeError) as e:
        _log(f"Could not read {path}: {e}")
        return None


def _outputs_from_meta(meta: dict[str, Any], folder: str) -> list[tuple[str, str]]:
    """Return list of (abs_path, label) from ``outputs[].file``."""
    out: list[tuple[str, str]] = []
    outputs = meta.get("outputs")
    if not isinstance(outputs, list):
        return out
    for item in outputs:
        if not isinstance(item, dict):
            continue
        fn = item.get("file")
        if not fn or not isinstance(fn, str):
            continue
        abs_path = os.path.normpath(os.path.join(folder, fn))
        if os.path.isfile(abs_path):
            out.append((abs_path, fn))
        else:
            _log(f"Meta output missing on disk: {abs_path}")
    return out


def _scan_prefix_usd(folder: str) -> list[tuple[str, str]]:
    """USD files in folder starting with geo_ or cam_ (any supported extension)."""
    found: list[tuple[str, str]] = []
    try:
        names = os.listdir(folder)
    except OSError as e:
        _log(f"listdir failed {folder!r}: {e}")
        return found
    for name in names:
        lower = name.lower()
        if not lower.startswith("geo_") and not lower.startswith("cam_"):
            continue
        if not any(lower.endswith(ext.lstrip(".")) for ext in (".usd", ".usda", ".usdc")):
            continue
        full = os.path.join(folder, name)
        if os.path.isfile(full):
            found.append((os.path.normpath(full), name))
    found.sort(key=lambda x: (not x[1].lower().startswith("cam_"), x[1].lower()))
    return found


def collect_usd_layers(
    folder: str,
    *,
    use_meta: bool,
    scan_prefix: bool,
) -> list[tuple[str, str]]:
    """Ordered (abs_path, label) list: meta outputs first (disk order), then prefix scan (cam before geo)."""
    seen: set[str] = set()
    ordered: list[tuple[str, str]] = []
    if use_meta:
        meta = load_publish_meta(folder)
        if meta:
            for pair in _outputs_from_meta(meta, folder):
                ap = pair[0]
                if ap not in seen:
                    seen.add(ap)
                    ordered.append(pair)
    if scan_prefix:
        for pair in _scan_prefix_usd(folder):
            ap = pair[0]
            if ap not in seen:
                seen.add(ap)
                ordered.append(pair)
    return ordered


def menu_anim_version_list(node: hou.Node) -> list[str]:
    p = node.parm("anim_publish_parent")
    if not p:
        return ["", "Set anim_publish_parent"]
    root = _expanded_dir(node, p.evalAsString())
    if not root or not os.path.isdir(root):
        return ["", "Invalid anim_publish_parent"]
    try:
        names = [n for n in os.listdir(root) if os.path.isdir(os.path.join(root, n))]
    except OSError:
        return ["", "Cannot read folder"]
    versions = [n for n in names if re.match(r"^v\d+", n, re.I)]
    if not versions:
        return ["", "No v### folders"]
    versions.sort(key=_version_key)
    menu: list[str] = []
    for v in versions:
        menu.extend([v, v])
    return menu


def set_latest_anim_version(node: hou.Node) -> None:
    p = node.parm("anim_version")
    if not p:
        return
    items = p.menuItems()
    if not items:
        return
    p.set(items[-1])


def apply_timeline_from_meta(node: hou.Node, folder: str) -> None:
    p = node.parm("apply_timeline")
    if p is None or int(p.eval()) == 0:
        return
    meta = load_publish_meta(folder)
    if not meta:
        return
    fps = meta.get("fps")
    if fps is not None:
        try:
            hou.setFps(float(fps))
        except (TypeError, ValueError, hou.OperationFailed):
            pass
    pr = meta.get("playback_range")
    if isinstance(pr, (list, tuple)) and len(pr) >= 2:
        try:
            a, b = int(pr[0]), int(pr[1])
            hou.playbar.setPlaybackRange(a, b)
            hou.playbar.setFrameRange(a, b)
        except (TypeError, ValueError, hou.OperationFailed):
            pass


def _find_subnet_output(subnet: hou.Node) -> hou.Node | None:
    for c in subnet.children():
        if c.type().name() == "output":
            return c
    return None


def _resolve_anim_subnet(node: hou.Node) -> hou.Node:
    """
    Callbacks may run with ``kwargs['node']`` as a child (e.g. output) instead of the subnet.
    Walk up until we find a LOP whose children include an ``output``-type node.
    """
    n: hou.Node | None = node
    for _ in range(32):
        if n is None:
            break
        try:
            if n.type().category() == hou.lopNodeTypeCategory() and _find_subnet_output(n) is not None:
                return n
        except hou.OperationFailed:
            pass
        n = n.parent()
    return node


def _can_create_child_lop(subnet: hou.Node) -> tuple[bool, str]:
    """Detect locked / non-editable HDAs that block ``createNode`` inside the subnet."""
    try:
        probe = subnet.createNode("merge", f"{ANIMLOAD_PREFIX}__probe__")
    except hou.OperationFailed as e:
        return False, str(e)
    try:
        probe.destroy()
    except hou.OperationFailed:
        pass
    return True, ""


def _safe_node_name(label: str) -> str:
    stem = os.path.splitext(os.path.basename(label))[0]
    s = re.sub(r"[^A-Za-z0-9_]", "_", stem)
    return s[:48] if s else "layer"


def _strip_geo_cam_prefix_from_stem(stem: str) -> str:
    """Filename stem without ``geo_`` / ``cam_`` (case-insensitive)."""
    s = stem.strip()
    low = s.lower()
    for p in _STRIP_FILENAME_PREFIXES:
        pl = p.lower()
        if low.startswith(pl):
            return s[len(p) :]
    return s


def _new_parent_prim_path_from_filename(filename: str, *, idx: int, used: set[str]) -> str:
    """USD absolute prim path: ``/Name_grp`` from basename, prefixes stripped, sanitized; de-duplicated."""
    stem = os.path.splitext(os.path.basename(filename))[0]
    body = _strip_geo_cam_prefix_from_stem(stem)
    safe = re.sub(r"[^A-Za-z0-9_]", "_", body).strip("_") or f"layer_{idx}"
    base = safe
    if not base.lower().endswith("_grp"):
        base = f"{base}_grp"
    candidate = f"/{base}"
    n = 1
    while candidate.lower() in used:
        n += 1
        candidate = f"/{base}_{n}"
    used.add(candidate.lower())
    return candidate


def _preserved_upstream_before_out(out: hou.Node) -> hou.Node | None:
    """If ``OUT`` is wired to something we did not create, keep it as merge input 0."""
    inp = out.input(0)
    if inp is None:
        return None
    if inp.name().startswith(ANIMLOAD_PREFIX):
        return None
    return inp


def _destroy_animload_children(subnet: hou.Node, out: hou.Node) -> None:
    """Clear ``OUT`` input and remove every child named ``animload_*``."""
    try:
        out.setInput(0, None)
    except hou.OperationFailed:
        pass
    for c in list(subnet.children()):
        if not c.name().startswith(ANIMLOAD_PREFIX):
            continue
        try:
            c.destroy()
        except hou.OperationFailed:
            pass


def _parm_set_menu_contains(parm: hou.Parm, substring: str) -> bool:
    try:
        labels = parm.menuLabels()
        items = parm.menuItems()
    except hou.OperationFailed:
        return False
    sub = substring.lower()
    for i, lab in enumerate(labels):
        if sub in lab.lower():
            return _parm_set_menu_index(parm, i)
    return False


def _parm_set_menu_index(parm: hou.Parm, index: int) -> bool:
    """Set a menu parm by index; try raw index then menu token string."""
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


def _iter_menu_parms(n: hou.Node):
    for p in n.parms():
        if p.parmTemplate().type() == hou.parmTemplateType.Menu:
            yield p


def _pick_sublayer_files_menu_index(items: list[str], labels: list[str]) -> int | None:
    """
    Pick menu index for *files from disk only* (not *… and Inputs*, not *Inputs* only).

    Works when UI is localized (labels not English) by token / layout heuristics.
    """
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


def _pick_reparent_operation_index(items: list[str], labels: list[str]) -> int | None:
    for i, (tok, lab) in enumerate(zip(items, labels)):
        t, l = str(tok).lower(), lab.lower()
        if "reparent" in t or "reparent" in l:
            return i
    if items:
        return 0
    return None


def _sublayer_file_row_parm_usable(sl: hou.Node) -> bool:
    """True if a *File* row for sublayering from disk looks enabled (mode is not inputs-only)."""
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


def _apply_sublayer_files_to_parm(sl: hou.Node, p: hou.Parm) -> bool:
    """Set one *Sublayer Type* menu to *files from disk*; verify via enabled file parms."""
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
    if idx is not None:
        if _parm_set_menu_index(p, idx):
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
    """
    Set Sublayer Type to *Files* (token 'files').

    Your build shows menu items like: ('filesandinputs', 'files', 'inputs').
    In that case we must explicitly pick token 'files'.
    """
    for p in _iter_sublayertype_parms(sl):
        try:
            items = list(p.menuItems())
        except hou.OperationFailed:
            continue

        desired = None
        for it in items:
            if str(it).lower() == "files":
                desired = it
                break

        if desired is None:
            # Fallback: first token containing 'files' but not 'filesandinputs' and not 'inputs'
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
            # Accept if current token isn't inputs-only or files+inputs
            try:
                cur = str(p.evalAsString()).lower()
                if "filesandinputs" not in cur and "inputs" not in cur and "files" in cur:
                    return True
            except hou.OperationFailed:
                return True

        # Last resort: heuristic-based setter
        if _apply_sublayer_files_to_parm(sl, p):
            return True

    return False


def _operation_parm_eval_is_reparent(p: hou.Parm) -> bool:
    try:
        s = p.evalAsString().lower()
        if "reparent" in s:
            return True
    except hou.OperationFailed:
        pass
    try:
        raw = str(p.eval()).lower()
        if "reparent" in raw:
            return True
    except hou.OperationFailed:
        pass
    return False


def _apply_reparent_operation_to_parm(p: hou.Parm) -> bool:
    """Set Restructure *operation* to reparent; verify via eval."""
    tokens = (
        "reparent",
        "reparentprims",
        "reparent_prims",
        "reparentprimitives",
        "reparent_primitives",
        "reparentprim",
        "namespaceeditreparent",
        "reparent_primitives_op",
    )
    for tok in tokens:
        try:
            p.set(tok)
        except hou.OperationFailed:
            continue
        if _operation_parm_eval_is_reparent(p):
            return True

    try:
        items = list(p.menuItems())
        labels = list(p.menuLabels())
    except hou.OperationFailed:
        return False

    idx = _pick_reparent_operation_index(items, labels)
    if idx is not None:
        if _parm_set_menu_index(p, idx) and _operation_parm_eval_is_reparent(p):
            return True

    for i in range(len(items)):
        if not _parm_set_menu_index(p, i):
            continue
        if _operation_parm_eval_is_reparent(p):
            return True
    if items and _parm_set_menu_index(p, 0):
        return True
    return False


def _iter_restructure_operation_parms(rs: hou.Node):
    seen: set[int] = set()
    for pname in ("operation", "restructureop", "op", "editoperation"):
        p = rs.parm(pname)
        if p is None or p.parmTemplate().type() != hou.parmTemplateType.Menu:
            continue
        pid = id(p)
        if pid not in seen:
            seen.add(pid)
            yield p
    for p in _iter_menu_parms(rs):
        lab = (p.parmTemplate().label() or "").strip().lower()
        name = p.name().lower()
        if lab == "operation" or name == "operation" or name.endswith("_operation"):
            pid = id(p)
            if pid not in seen:
                seen.add(pid)
                yield p


def _sublayer_ensure_one_file_slot(sl: hou.Node) -> None:
    # Enable the first sublayer file row when the node uses group toggles
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
            # Even if num_files parm is disabled in the current mode,
            # setting group1 above helps enabling filepath1 / file1.
            return


def _sublayer_set_weakest_position(sl: hou.Node) -> None:
    """Prefer weakest stack position so downstream lookdev/light LOPs can win."""
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


def _configure_single_file_sublayer(sl: hou.Node, filepath: str) -> bool:
    """Configure one Sublayer LOP for a single USD file on disk (best-effort across builds)."""
    mode_set = _sublayer_set_mode_files(sl)

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
        _log(f"Could not find File parm on sublayer LOP {sl.path()}")
        return False

    # On some Houdini builds the mode token can still report as unresolved while
    # file parms are writable and work correctly (files/inputs UI quirks).
    if not mode_set:
        _log(
            f"Sublayer type not explicitly confirmed on {sl.path()}, "
            "but file parm is writable; continuing."
        )

    _sublayer_set_weakest_position(sl)
    return True


def _norm_menu_text(s: str) -> str:
    return s.lower().replace(" ", "").replace("_", "")


def _pick_menu_index_usdgeom_xform(items: list[str], labels: list[str]) -> int | None:
    """Index of UsdGeom / Xform entry; skip plain **scope** default."""
    pairs: list[tuple[str, str]] = [(str(tok), lab) for tok, lab in zip(items, labels)]

    for i, (tok, lab) in enumerate(pairs):
        blob = _norm_menu_text(tok + lab)
        if "usdgeomxform" in blob:
            return i

    for i, (tok, lab) in enumerate(pairs):
        tl = str(tok).strip().lower()
        if tl in ("scope", "usdgeomscopes", "scopes"):
            continue
        if tl in ("usdgeomxform", "xform", "xformprim", "transform"):
            return i
        if "xform" in tl and "scope" not in tl:
            return i

    return None


def _iter_restructure_parent_prim_type_parms(rs: hou.Node):
    """Menu parms for *Create parent* prim type (Restructure Scene Graph: ``parentprimtype``)."""
    seen: set[int] = set()
    for pname in (
        "parentprimtype",
        "parentprimetype",
        "parent_prim_type",
        "primparenttype",
    ):
        p = rs.parm(pname)
        if p is None or p.parmTemplate().type() != hou.parmTemplateType.Menu:
            continue
        pid = id(p)
        if pid not in seen:
            seen.add(pid)
            yield p

    for p in rs.parms():
        if p.parmTemplate().type() != hou.parmTemplateType.Menu:
            continue
        n = p.name().lower()
        if "parentprimtype" in n:
            pid = id(p)
            if pid not in seen:
                seen.add(pid)
                yield p


def _set_parent_primtype_usdgeom_xform(p: hou.Parm) -> bool:
    """Set ``parentprimtype`` menu using Tf token ``UsdGeomXform`` (menu first entry is often ``''``)."""
    try:
        p.set("UsdGeomXform")
        return True
    except hou.OperationFailed:
        pass
    try:
        items = list(p.menuItems())
    except hou.OperationFailed:
        return False
    for token in ("UsdGeomXform", "usdgeomxform"):
        if token in items:
            return _parm_set_menu_index(p, items.index(token))
    idx = _pick_menu_index_usdgeom_xform(items, list(p.menuLabels()))
    if idx is not None:
        return _parm_set_menu_index(p, idx)
    return False


def _set_restructure_parent_prim_type_usdgeom_xform(rs: hou.Node) -> None:
    """Set Create Parent **Primitive Type** to ``UsdGeomXform`` (SideFX token, not label *Xform* alone)."""
    for p in _iter_restructure_parent_prim_type_parms(rs):
        if _set_parent_primtype_usdgeom_xform(p):
            return


def _configure_restructure_reparent(rs: hou.Node, new_parent_prim: str) -> bool:
    """Restructure Scene Graph: reparent prims under ``new_parent_prim``; parent kind Xform."""
    for pname in (
        "flattennodeinputlayers",
        "flattenlayers",
        "flattennodeinput",
    ):
        p = rs.parm(pname)
        if p is not None:
            try:
                p.set(1)
            except hou.OperationFailed:
                pass
            break

    op_set = False
    op_parm_seen = False
    for p in _iter_restructure_operation_parms(rs):
        op_parm_seen = True
        if _apply_reparent_operation_to_parm(p):
            op_set = True
            break
    if not op_set:
        for p in _iter_menu_parms(rs):
            try:
                nitems = len(p.menuItems())
            except hou.OperationFailed:
                continue
            if nitems < 4:
                continue
            op_parm_seen = True
            if _apply_reparent_operation_to_parm(p):
                op_set = True
                break
    # Don't warn noisily here: many builds/localizations keep Reparent as default
    # but menu token introspection can fail. The branch still works.
    if not op_set and not op_parm_seen:
        _log(f"No operation menu parm found on {rs.path()}; relying on node defaults.")

    for pname in (
        "primnewparent",
        "newparentprim",
        "new_parent_prim",
        "parentprim",
        "newparent",
    ):
        p = rs.parm(pname)
        if p is not None:
            p.set(new_parent_prim)
            break
    else:
        for p in rs.parms():
            lab = (p.parmTemplate().label() or "").lower()
            if "new parent prim" in lab and p.parmTemplate().type() == hou.parmTemplateType.String:
                p.set(new_parent_prim)
                break
        else:
            _log(f"Could not find New Parent Prim on {rs.path()}")
            return False

    for pname in ("primitives", "primitivepaths", "primpattern"):
        p = rs.parm(pname)
        if p is not None and p.parmTemplate().type() == hou.parmTemplateType.String:
            p.set(RESTRUCTURE_PRIM_PATTERN)
            break

    for pname in ("createparentprims", "createparentprim", "createparents"):
        p = rs.parm(pname)
        if p is not None:
            try:
                p.set(1)
            except hou.OperationFailed:
                pass
            break

    # After Create Parent Prims is on, **parent** prim type parm exists / is writable (not default Scope).
    _set_restructure_parent_prim_type_usdgeom_xform(rs)

    # Do not fail the whole branch if only the Operation menu failed to match (localized UI).
    return True


def rebuild_anim_publish(node: hou.Node) -> tuple[int, str]:
    """
    Rebuild ``animload_*`` network: for each file **sublayer** → **restructurescenegraph** → **merge** → **output**.

    .. note::
        After saving a Subnet as an HDA, ``node.type().name()`` is the asset name, not ``subnet``.
        This function only requires LOP category + internal **output** node + ability to create children.

    Returns (count, message).
    """
    if node.type().category() != hou.lopNodeTypeCategory():
        return 0, "Node is not a LOP."

    if not node.children():
        return (
            0,
            "HDA has no internal nodes: create the asset from a Subnet LOP and put an Output LOP inside.",
        )

    ok, err = _can_create_child_lop(node)
    if not ok:
        return (
            0,
            "Cannot create LOPs inside this subnet (asset may be locked). "
            "In Asset Editor: Basic → turn on **Allow Editing of Contents**, or match a dev definition. "
            f"Detail: {err}",
        )

    folder = resolve_publish_folder(node)
    if not folder or not os.path.isdir(folder):
        return 0, f"Invalid publish folder: {folder!r}"

    use_meta = True
    scan_p = node.parm("scan_geo_cam_prefix")
    if scan_p is not None:
        scan_prefix = int(scan_p.eval()) != 0
    else:
        scan_prefix = True
    um = node.parm("use_publish_meta")
    if um is not None:
        use_meta = int(um.eval()) != 0

    layers = collect_usd_layers(folder, use_meta=use_meta, scan_prefix=scan_prefix)
    if not layers:
        return 0, f"No USD layers found in {folder}"

    out = _find_subnet_output(node)
    if out is None:
        return (
            0,
            "Inside the HDA network, add a LOP node whose type is **output** (Solaris / Stage output). "
            "Name can be OUT or anything; type must be `output`.",
        )

    preserved = _preserved_upstream_before_out(out)
    _destroy_animload_children(node, out)

    merge_node: hou.Node | None = None
    try:
        merge_node = node.createNode("merge", node_name=MERGE_NODE_NAME)
    except hou.OperationFailed as e:
        _log(f"createNode merge failed: {e}")
        try:
            out.setInput(0, preserved)
        except hou.OperationFailed:
            pass
        return 0, f"Could not create merge LOP: {e}"

    branch_heads: list[hou.Node] = []
    used_parent_paths: set[str] = set()
    created = 0

    for idx, (abs_path, label) in enumerate(layers):
        base = _safe_node_name(label)
        sl_name = f"{ANIMLOAD_PREFIX}{idx}_sub_{base}"
        rs_name = f"{ANIMLOAD_PREFIX}{idx}_rs_{base}"
        try:
            sl = node.createNode("sublayer", node_name=sl_name)
        except hou.OperationFailed as e:
            _log(f"createNode sublayer failed: {e}")
            break
        if not _configure_single_file_sublayer(sl, abs_path):
            sl.destroy()
            continue

        try:
            rs = node.createNode("restructurescenegraph", node_name=rs_name)
        except hou.OperationFailed as e:
            _log(f"createNode restructurescenegraph failed: {e}")
            sl.destroy()
            break

        parent_path = _new_parent_prim_path_from_filename(label, idx=idx, used=used_parent_paths)
        try:
            rs.setInput(0, sl)
        except hou.OperationFailed:
            sl.destroy()
            rs.destroy()
            continue

        if not _configure_restructure_reparent(rs, parent_path):
            sl.destroy()
            rs.destroy()
            continue

        sl.moveToGoodPosition()
        rs.moveToGoodPosition()
        branch_heads.append(rs)
        created += 1

    in_idx = 0
    if preserved is not None:
        try:
            merge_node.setInput(in_idx, preserved)
        except hou.OperationFailed:
            pass
        in_idx += 1

    for rs in branch_heads:
        try:
            merge_node.setInput(in_idx, rs)
            in_idx += 1
        except hou.OperationFailed as e:
            _log(f"merge setInput failed: {e}")

    if created == 0:
        try:
            merge_node.destroy()
        except hou.OperationFailed:
            pass
        try:
            out.setInput(0, preserved)
        except hou.OperationFailed:
            pass
        try:
            out.setDisplayFlag(True)
        except hou.OperationFailed:
            pass
        return 0, f"No USD layers could be built from {folder}."

    try:
        out.setInput(0, merge_node)
    except hou.OperationFailed:
        pass

    try:
        out.setDisplayFlag(True)
    except hou.OperationFailed:
        pass

    apply_timeline_from_meta(node, folder)
    node.setUserData("anim_publish_last_folder", folder)
    node.setUserData("anim_publish_layer_count", str(created))

    _log(f"Rebuilt {created} branch(es) (sublayer+restructure) + merge from {folder}")
    return created, f"Loaded {created} USD layer(s) from {os.path.basename(folder)}."


def cb_rebuild(kwargs: dict) -> None:
    raw = kwargs.get("node")
    node = _resolve_anim_subnet(raw) if raw is not None else hou.pwd()
    n, msg = rebuild_anim_publish(node)
    if n == 0 and msg:
        try:
            hou.ui.displayMessage(msg, severity=hou.severityType.Warning)
        except hou.OperationFailed:
            _log(msg)


def cb_set_latest_anim_version(kwargs: dict) -> None:
    set_latest_anim_version(kwargs["node"])


def cb_on_anim_version_change(kwargs: dict) -> None:
    """Optional: sync anim_publish_dir when using parent + version menus."""
    node = kwargs["node"]
    folder = resolve_publish_folder(node)
    p = node.parm("anim_publish_dir")
    if p is not None and folder:
        p.set(folder)


# ============================================================
# Compute-only API: 1 HDA instance loads 1 USD file
# (no LOP/subLayer node creation; only resolves and writes paths)
# ============================================================


def _set_first_existing_parm(node: hou.Node, names: tuple[str, ...], value: str) -> bool:
    """Set the first existing string parm in ``names``."""
    for n in names:
        p = node.parm(n)
        if p is None:
            continue
        try:
            p.set(value)
            return True
        except hou.OperationFailed:
            continue
    return False


def _get_callback_string_value(kwargs: dict) -> str:
    """
    Houdini may pass ``kwargs['parm']`` for parameter callbacks.
    When unavailable, we try a small set of common parm names.
    """
    parm = kwargs.get("parm")
    if parm is not None:
        try:
            return parm.evalAsString()
        except hou.OperationFailed:
            return ""

    node = kwargs.get("node")
    if not isinstance(node, hou.Node):
        return ""

    for cand in (
        "geo_usd_file",
        "cam_usd_file",
        "Geo_File_List",
        "Cam_File_List",
        "geo_selected_usd_path",
        "cam_selected_usd_path",
    ):
        p = node.parm(cand)
        if p is None:
            continue
        try:
            v = p.evalAsString()
            if v:
                return v
        except hou.OperationFailed:
            continue
    return ""


def _split_path_parts(path: str) -> list[str]:
    raw = os.path.normpath(path)
    parts = re.split(r"[\\/]+", raw)
    return [p for p in parts if p]


def _find_shot_root_from_hip_path(hip_path: str) -> str:
    """Infer shot root ".../02_shots/<shot>" from a saved hip file path."""
    if not hip_path:
        return ""
    parts = _split_path_parts(hip_path)
    shot_idx = -1
    for i, seg in enumerate(parts):
        if seg.lower() == "02_shots":
            shot_idx = i
            break
    if shot_idx < 0 or shot_idx + 1 >= len(parts):
        return ""
    return os.path.join(*parts[: shot_idx + 2])


def _infer_assets_root_from_shot_root(shot_root: str) -> str:
    """Infer ".../01_assets" sibling of shot root ".../02_shots/<shot>"."""
    if not shot_root:
        return ""
    parts = _split_path_parts(shot_root)
    shots_idx = -1
    for i, seg in enumerate(parts):
        if seg.lower() == "02_shots":
            shots_idx = i
            break
    if shots_idx < 0:
        return ""
    project_root = os.path.join(*parts[:shots_idx])
    return os.path.join(project_root, "01_assets")


def _list_versions_under(folder: str) -> list[str]:
    if not folder or not os.path.isdir(folder):
        return []
    try:
        names = [n for n in os.listdir(folder) if os.path.isdir(os.path.join(folder, n))]
    except OSError:
        return []
    versions = [n for n in names if re.match(r"^v\d+", n, re.I)]
    versions.sort(key=_version_key)
    return versions


def _latest_version_name(folder: str) -> str:
    versions = _list_versions_under(folder)
    return versions[-1] if versions else ""


def resolve_anim_publish_parent_and_latest_version_from_hip(node: hou.Node) -> tuple[str, str, str]:
    """
    Return (shot_root, anim_publish_parent, latest_anim_version).

    anim_publish_parent is ".../01_anim/publish" that contains v### folders.
    """
    hip_path = ""
    try:
        hip_path = hou.hipFile.path()
    except hou.OperationFailed:
        hip_path = ""

    shot_root = _find_shot_root_from_hip_path(hip_path)
    if not shot_root:
        return "", "", ""

    anim_publish_parent = os.path.join(shot_root, "01_anim", "publish")
    latest = _latest_version_name(anim_publish_parent)
    return shot_root, anim_publish_parent, latest


def cb_autofill_anim_publish_from_hip(kwargs: dict) -> None:
    """Auto-resolve anim publish folder/version from the current hip path."""
    node = kwargs.get("node")
    if not isinstance(node, hou.Node):
        return

    _shot_root, parent, latest = resolve_anim_publish_parent_and_latest_version_from_hip(node)
    if not parent or not latest:
        try:
            hou.ui.displayMessage(
                "Could not infer shot/publish folder from current hip path. "
                "Please set anim_publish_parent/anim_version manually.",
                severity=hou.severityType.Warning,
            )
        except hou.OperationFailed:
            _log("Could not infer shot/publish folder from hip path.")
        return

    p_parent = node.parm("anim_publish_parent")
    if p_parent is not None:
        try:
            p_parent.set(parent)
        except hou.OperationFailed:
            pass

    p_ver = node.parm("anim_version")
    if p_ver is not None:
        try:
            p_ver.set(latest)
        except hou.OperationFailed:
            pass

    p_dir = node.parm("anim_publish_dir")
    if p_dir is not None:
        try:
            p_dir.set(os.path.join(parent, latest))
        except hou.OperationFailed:
            pass


def _resolve_assets_root_for_current_anim(node: hou.Node, version_folder: str) -> str:
    """Infer assets root from an anim version folder path, or fall back to an explicit parm."""
    p_assets = node.parm("assets_root")
    if p_assets is not None:
        try:
            v = p_assets.evalAsString()
            if v:
                return _expanded_dir(node, v)
        except hou.OperationFailed:
            pass

    if not version_folder:
        return ""
    parts = _split_path_parts(version_folder)
    shot_idx = -1
    for i, seg in enumerate(parts):
        if seg.lower() == "02_shots":
            shot_idx = i
            break
    if shot_idx < 0 or shot_idx + 1 >= len(parts):
        return ""
    shot_root = os.path.join(*parts[: shot_idx + 2])
    return _infer_assets_root_from_shot_root(shot_root)


def _parse_asset_from_geo_filename(geo_usd_path: str) -> tuple[str, str]:
    """
    geo file basename example: geo_char_Zephys.usd -> ("char", "Zephys")
    """
    base = os.path.splitext(os.path.basename(geo_usd_path))[0]
    if not base.lower().startswith("geo_"):
        return "", ""
    rest = base[len("geo_") :]
    parts = rest.split("_", 1)
    if len(parts) == 2 and parts[0].lower() in KNOWN_LOOKDEV_ASSET_TYPES:
        return parts[0].lower(), parts[1]
    low = rest.lower()
    for t in KNOWN_LOOKDEV_ASSET_TYPES:
        prefix = f"{t.lower()}_"
        if low.startswith(prefix):
            return t, rest[len(prefix) :]
    return "", ""


def _find_latest_v_folder(folder: str) -> str:
    """Pick latest V### folder under folder."""
    versions: list[str] = []
    try:
        names = [n for n in os.listdir(folder) if os.path.isdir(os.path.join(folder, n))]
    except OSError:
        names = []
    for n in names:
        if re.match(r"^[Vv]\d+$", n):
            versions.append(n)
    versions.sort(key=_version_key)
    return os.path.join(folder, versions[-1]) if versions else ""


def _find_lookdev_publish_file(lookdev_publish_base_dir: str, expected_stem: str) -> str:
    if not lookdev_publish_base_dir or not os.path.isdir(lookdev_publish_base_dir):
        return ""
    latest_v_dir = _find_latest_v_folder(lookdev_publish_base_dir)
    if not latest_v_dir:
        return ""

    expected_stem_low = expected_stem.lower()
    try:
        names = os.listdir(latest_v_dir)
    except OSError:
        return ""

    for name in names:
        low = name.lower()
        if not low.endswith(USD_EXTS):
            continue
        stem = os.path.splitext(name)[0].lower()
        if stem == expected_stem_low:
            return os.path.normpath(os.path.join(latest_v_dir, name))

    # Fallback: try .usd directly.
    direct = os.path.join(latest_v_dir, f"{expected_stem}.usd")
    if os.path.isfile(direct):
        return os.path.normpath(direct)
    return ""


def resolve_geo_lookdev_path_from_geo_usd(geo_usd_path: str, assets_root: str) -> str:
    """
    Given a geo USD path:
    - parse asset token ("char/prop/env/veh" + name) from filename,
    - find latest lookdev publish USD for that asset under the assets root.
    """
    asset_type, asset_name = _parse_asset_from_geo_filename(geo_usd_path)
    if not asset_type or not asset_name:
        return ""
    if not assets_root or not os.path.isdir(assets_root):
        return ""

    expected_stem = f"{asset_type}_{asset_name}_lookdev_publish"

    # Fast first-level search: try any "_*" group that contains the asset folder.
    try:
        groups = [
            n
            for n in os.listdir(assets_root)
            if os.path.isdir(os.path.join(assets_root, n)) and n.startswith("_")
        ]
    except OSError:
        groups = []
    if not groups:
        groups = ["_characters"]

    for group in groups:
        publish_base = os.path.join(
            assets_root, group, f"{asset_type}_{asset_name}", "05_lookdev", "publish"
        )
        if not os.path.isdir(publish_base):
            continue
        fp = _find_lookdev_publish_file(publish_base, expected_stem=expected_stem)
        if fp:
            return fp

    # Direct try using the most common group name.
    publish_base = os.path.join(
        assets_root, "_characters", f"{asset_type}_{asset_name}", "05_lookdev", "publish"
    )
    if os.path.isdir(publish_base):
        return _find_lookdev_publish_file(publish_base, expected_stem=expected_stem)
    return ""


def _menu_anim_usd_list_by_prefix(node: hou.Node, *, prefix: str, empty_label: str) -> list[str]:
    folder = resolve_publish_folder(node)
    if not folder or not os.path.isdir(folder):
        return ["", f"Invalid publish folder for {prefix}"]

    use_meta = True
    um = node.parm("use_publish_meta")
    if um is not None:
        try:
            use_meta = int(um.eval()) != 0
        except hou.OperationFailed:
            use_meta = True

    scan_prefix = True
    scan_p = node.parm("scan_geo_cam_prefix")
    if scan_p is not None:
        try:
            scan_prefix = int(scan_p.eval()) != 0
        except hou.OperationFailed:
            scan_prefix = True

    layers = collect_usd_layers(folder, use_meta=use_meta, scan_prefix=scan_prefix)
    prefix_low = prefix.lower()

    filtered: list[tuple[str, str]] = []
    for abs_path, label in layers:
        base = os.path.basename(abs_path).lower()
        if base.startswith(prefix_low):
            filtered.append((abs_path, label))

    if not filtered:
        return ["", empty_label]

    # Menu token is abs path; label is basename for readability.
    menu: list[str] = []
    for abs_path, label in filtered:
        menu.extend([abs_path, os.path.basename(label) if label else os.path.basename(abs_path)])
    return menu


def menu_anim_geo_usd_list(node: hou.Node) -> list[str]:
    """Menu token = selected geo USD absolute path (filtered from meta/scan)."""
    return _menu_anim_usd_list_by_prefix(node, prefix="geo_", empty_label="No Geo USD Files")


def menu_anim_cam_usd_list(node: hou.Node) -> list[str]:
    """Menu token = selected cam USD absolute path (filtered from meta/scan)."""
    return _menu_anim_usd_list_by_prefix(node, prefix="cam_", empty_label="No Cam USD Files")


def _status_set(node: hou.Node, msg: str) -> None:
    _set_first_existing_parm(
        node,
        (
            "anim_publish_status",
            "publish_status",
            "geo_lookdev_status",
            "lookdev_status",
            "timeline_status",
            "version_status",
        ),
        msg,
    )


def cb_on_geo_usd_change(kwargs: dict) -> None:
    """Set resolved anim+lookdev paths from selected geo USD file (compute-only)."""
    node = kwargs.get("node")
    if not isinstance(node, hou.Node):
        return

    selected_geo = _get_callback_string_value(kwargs)
    if not selected_geo or not os.path.isfile(selected_geo):
        _set_first_existing_parm(node, ("geo_anim_sublayer_path", "cam_anim_sublayer_path"), "")
        _set_first_existing_parm(
            node, ("geo_lookdev_sublayer_path", "lookdev_sublayer_path", "selected_lookdev_usd_path"), ""
        )
        _status_set(node, "Geo USD selection is empty or missing on disk.")
        return

    selected_geo = os.path.normpath(selected_geo)
    _set_first_existing_parm(
        node,
        (
            "geo_anim_sublayer_path",
            "anim_sublayer_path",
            "selected_anim_usd_path",
        ),
        selected_geo,
    )

    version_folder = resolve_publish_folder(node)
    assets_root = _resolve_assets_root_for_current_anim(node, version_folder)
    lookdev_path = resolve_geo_lookdev_path_from_geo_usd(selected_geo, assets_root)

    _set_first_existing_parm(
        node,
        (
            "geo_lookdev_sublayer_path",
            "lookdev_sublayer_path",
            "selected_lookdev_usd_path",
        ),
        os.path.normpath(lookdev_path) if lookdev_path else "",
    )

    if lookdev_path:
        _status_set(node, f"Geo loaded: {os.path.basename(selected_geo)} | Lookdev found.")
    else:
        _status_set(node, f"Geo loaded: {os.path.basename(selected_geo)} | Lookdev not found.")


def cb_on_cam_usd_change(kwargs: dict) -> None:
    """Set resolved anim path from selected cam USD file (compute-only)."""
    node = kwargs.get("node")
    if not isinstance(node, hou.Node):
        return

    selected_cam = _get_callback_string_value(kwargs)
    if not selected_cam or not os.path.isfile(selected_cam):
        _set_first_existing_parm(node, ("cam_anim_sublayer_path", "anim_sublayer_path"), "")
        _status_set(node, "Cam USD selection is empty or missing on disk.")
        return

    selected_cam = os.path.normpath(selected_cam)
    _set_first_existing_parm(
        node,
        (
            "cam_anim_sublayer_path",
            "anim_sublayer_path",
            "selected_anim_usd_path",
        ),
        selected_cam,
    )

    # Clear lookdev outputs when loading cam-only.
    _set_first_existing_parm(
        node, ("geo_lookdev_sublayer_path", "lookdev_sublayer_path", "selected_lookdev_usd_path"), ""
    )
    _status_set(node, f"Cam loaded: {os.path.basename(selected_cam)}.")


def cb_apply_anim_timeline(kwargs: dict) -> None:
    """Apply fps / playback range from publish_meta.json (compute-only)."""
    node = kwargs.get("node")
    if not isinstance(node, hou.Node):
        return

    folder = resolve_publish_folder(node)
    if not folder or not os.path.isdir(folder):
        _status_set(node, "Invalid publish folder for timeline apply.")
        return

    meta = load_publish_meta(folder)
    if meta is None:
        _status_set(node, "publish_meta.json missing or invalid; timeline not applied.")
        apply_timeline_from_meta(node, folder)  # keeps existing gating behavior
        return

    apply_timeline_from_meta(node, folder)  # respects apply_timeline parm

    fps = meta.get("fps")
    pr = meta.get("playback_range")
    if fps is not None or pr is not None:
        _status_set(node, "Timeline applied from publish_meta.json.")
    else:
        _status_set(node, "publish_meta.json loaded but has no fps/playback_range.")


def _eval_type_token(node: hou.Node) -> str:
    """Read dropdown token from parm `Type` (best-effort)."""
    p = node.parm("Type")
    if p is None:
        return ""
    try:
        v = p.evalAsString()
    except hou.OperationFailed:
        v = ""
    return (v or "").strip().lower()


def menu_anim_usd_list_by_type(node: hou.Node) -> list[str]:
    """
    Menu builder for a single dropdown+menu setup.

    - Reads dropdown `Type` ("geo"/"cam")
    - Returns USD items for that type only
    - If Type is unknown/missing, returns a merged geo+cam menu (dedup by abs path)
    """
    t = _eval_type_token(node)
    if "geo" in t:
        return menu_anim_geo_usd_list(node)
    if "cam" in t:
        return menu_anim_cam_usd_list(node)

    # Fallback: merge geo+cam menu.
    geo_menu = menu_anim_geo_usd_list(node)
    cam_menu = menu_anim_cam_usd_list(node)

    # Menu format: [token1,label1, token2,label2, ...]
    seen_tokens: set[str] = set()
    merged: list[str] = []
    for menu in (geo_menu, cam_menu):
        for i in range(0, len(menu), 2):
            if i + 1 >= len(menu):
                break
            tok = str(menu[i])
            lab = str(menu[i + 1])
            if tok in seen_tokens:
                continue
            seen_tokens.add(tok)
            merged.extend([tok, lab])
    return merged


def cb_on_selected_usd_change(kwargs: dict) -> None:
    """
    Unified callback for both geo and cam selections.

    It detects selected USD prefix by basename:
    - geo_ -> cb_on_geo_usd_change
    - cam_ -> cb_on_cam_usd_change
    - otherwise: uses dropdown `Type` as fallback (if it contains 'geo'/'cam')
    """
    node = kwargs.get("node")
    if not isinstance(node, hou.Node):
        return

    selected = _get_callback_string_value(kwargs)
    if not selected or not os.path.isfile(selected):
        # Clear likely outputs.
        _set_first_existing_parm(node, ("geo_anim_sublayer_path", "anim_sublayer_path", "selected_anim_usd_path"), "")
        _set_first_existing_parm(node, ("cam_anim_sublayer_path",), "")
        _set_first_existing_parm(node, ("geo_lookdev_sublayer_path", "lookdev_sublayer_path", "selected_lookdev_usd_path"), "")
        _status_set(node, "USD selection is empty or missing on disk.")
        return

    base = os.path.basename(selected).lower()
    if base.startswith("geo_"):
        cb_on_geo_usd_change(kwargs)
        return
    if base.startswith("cam_"):
        cb_on_cam_usd_change(kwargs)
        return

    # Fallback: use dropdown.
    t = _eval_type_token(node)
    if "geo" in t:
        cb_on_geo_usd_change(kwargs)
    else:
        cb_on_cam_usd_change(kwargs)
