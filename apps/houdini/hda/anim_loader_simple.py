"""
Simple anim publish loader (temporary).

Two layers:

1) Pure compute layer (no `hou` import):
   - Given a .hip/.hiplc path, infer:
     - project root (contains `01_assets` and `02_shots`)
     - shot token (e.g. `sh002`)
     - anim publish directory:
       `<project_root>/02_shots/<shot>/01_anim/publish`
     - version folders inside publish (e.g. `v001`, `v002`, ...)
     - USD files found under publish (recursively)

2) Optional HDA helpers:
   - Menu functions take `node` and return menu token/label list.
   - Callback functions take `kwargs` and write resolved paths into string parms.

HDA helpers should follow the same interaction conventions as the repo:
- Single-line menu: return `menu` list directly.
- Parm callbacks: use `kwargs` pattern and call via `hou.phm()`.

### Proposed HDA parm names (you can copy these into your HDA)

Core:
- `mx_project_root` (string): project root folder. Auto-filled from hip when possible.
- `mx_shot` (menu/string): selected shot token (e.g. "sh002").

Anim:
- `mx_anim_publish_parent` (string): resolved `<project_root>/02_shots/<shot>/01_anim/publish`
- `mx_anim_version` (menu/string): version folder name under anim publish parent (e.g. "v001")

Lookdev (shot-level):
- `mx_lookdev_publish_parent` (string): resolved lookdev publish folder for the selected asset:
  `<mx_project_root>/01_assets/<group>/<asset_type>_<asset_name>/05_lookdev/publish`
- `mx_lookdev_version` (menu/string): latest (or user-selected) `v###` under that publish folder

USD selection:
- `mx_anim_usd` (menu/string): token = absolute USD file path under selected anim version folder
- `mx_selected_anim_usd_path` (string): resolved selected USD abs path (written by callback)
- `mx_selected_lookdev_usd_path` (string): resolved lookdev USD abs path (written by callback; geo-only)
- `mx_geo_cam` (int): `0` = selected USD basename starts with `geo_`, `1` = `cam_`, `-1` = other/empty

Groom (shot FX publish, USD sequence):
- `mx_groom_publish_parent` (string): `<project_root>/02_shots/<shot>/02_fx/groom/publish`
- `mx_groom_version` (menu/string): `v001` / `V001`-style folder under groom publish
- `mx_groom_asset` (menu/string): subfolder under version (e.g. `Zephys`); token `` (empty) = USD directly under version
- `mx_selected_groom_usd_path` (string): path with Houdini frame var, e.g. ``.../sh003a_groom.$F4.usd``
- `mx_enable_groom` (toggle): when off, groom outputs cleared

Cloth (shot FX publish, USD sequence — same layout as groom under ``02_fx/cloth``):
- `mx_cloth_publish_parent`, `mx_cloth_version`, `mx_cloth_asset`, `mx_selected_cloth_usd_path`, `mx_enable_cloth`

Optional status:
- `mx_status` (string): status message written by callbacks (if present).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Optional

try:
    import hou  # type: ignore
except ImportError:  # running outside Houdini
    hou = None  # type: ignore[assignment]

_HDA_STATUS_PARMS = (
    "anim_publish_status",
    "publish_status",
    "timeline_status",
    "version_status",
    "status",
    "mx_status",
)

_MX_PROJECT_ROOT = "mx_project_root"
_MX_SHOT = "mx_shot"
_MX_ANIM_PUBLISH_PARENT = "mx_anim_publish_parent"
_MX_ANIM_VERSION = "mx_anim_version"
_MX_LOOKDEV_PUBLISH_PARENT = "mx_lookdev_publish_parent"
_MX_LOOKDEV_VERSION = "mx_lookdev_version"
_MX_ANIM_USD = "mx_anim_usd"
_MX_SELECTED_ANIM_USD_PATH = "mx_selected_anim_usd_path"
_MX_SELECTED_LOOKDEV_USD_PATH = "mx_selected_lookdev_usd_path"
_MX_ENABLE_LOOKDEV = "mx_enable_lookdev"
_MX_GROOM_PUBLISH_PARENT = "mx_groom_publish_parent"
_MX_GROOM_VERSION = "mx_groom_version"
_MX_GROOM_ASSET = "mx_groom_asset"
_MX_SELECTED_GROOM_USD_PATH = "mx_selected_groom_usd_path"
_MX_ENABLE_GROOM = "mx_enable_groom"
_MX_CLOTH_PUBLISH_PARENT = "mx_cloth_publish_parent"
_MX_CLOTH_VERSION = "mx_cloth_version"
_MX_CLOTH_ASSET = "mx_cloth_asset"
_MX_SELECTED_CLOTH_USD_PATH = "mx_selected_cloth_usd_path"
_MX_ENABLE_CLOTH = "mx_enable_cloth"
_MX_GEO_CAM = "mx_geo_cam"
_META_NAME = "publish_meta.json"


# e.g. sh001, sh002, sh003a (split / variant suffix after 3+ digit body)
_SHOT_RE = re.compile(r"^(sh\d{3,}[a-z0-9]*)$", re.IGNORECASE)
_SHOT_ANYWHERE_RE = re.compile(r"(sh\d{3,}[a-z0-9]*)", re.IGNORECASE)
_VERSION_RE = re.compile(r"^v(\d+)$", re.IGNORECASE)
_USD_SUFFIXES = (".usd", ".usda", ".usdc")


@dataclass(frozen=True)
class AnimPublishScanResult:
    hip_path: Path
    project_root: Optional[Path]
    shot: Optional[str]
    shot_root: Optional[Path]
    anim_publish_dir: Optional[Path]
    version_dirs: tuple[Path, ...]
    usd_files: tuple[Path, ...]


def _is_project_root(candidate: Path) -> bool:
    return (candidate / "01_assets").is_dir() and (candidate / "02_shots").is_dir()


def find_project_root(path: Path) -> Optional[Path]:
    """
    Walk upwards from a file or directory path to find the project root.
    A project root is defined as a folder containing both `01_assets` and `02_shots`.
    """
    start = path if path.is_dir() else path.parent
    for p in (start, *start.parents):
        try:
            if _is_project_root(p):
                return p
        except OSError:
            continue
    return None


def detect_shot_from_path(path: Path) -> Optional[str]:
    """
    Detect a shot token like 'sh002' or 'sh003a' from any segment of the given path.
    Returns normalized lowercase or None.
    """
    parts = [path.name] + [p.name for p in path.parents]
    for part in parts:
        m = _SHOT_RE.match(part)
        if m:
            return m.group(1).lower()
    joined = str(path)
    m2 = _SHOT_ANYWHERE_RE.search(joined)
    if m2:
        return m2.group(1).lower()
    return None


def get_shot_root(project_root: Path, shot: str) -> Path:
    return project_root / "02_shots" / shot


def get_anim_publish_dir(project_root: Path, shot: str) -> Path:
    return get_shot_root(project_root, shot) / "01_anim" / "publish"


def get_fx_shot_task_publish_dir(project_root: Path, shot: str, fx_task: str) -> Path:
    """``<project_root>/02_shots/<shot>/02_fx/<fx_task>/publish`` (e.g. ``groom``, ``cloth``)."""
    return get_shot_root(project_root, shot) / "02_fx" / fx_task / "publish"


def _fx_shot_seq_re(fx_task: str):
    return re.compile(rf"^(.+)_{re.escape(fx_task)}\.(\d+)\.(usd|usda|usdc)$", re.IGNORECASE)


def pick_fx_shot_sequence_entry_frame(scan_dir: Path, shot: str, fx_task: str) -> str:
    """
    Lowest frame file matching ``{shot}_{fx_task}.####.usd`` (non-recursive).
    ``shot`` compared case-insensitively to the filename prefix.
    """
    if not scan_dir.is_dir():
        return ""
    shot_cf = shot.strip().lower()
    pat = _fx_shot_seq_re(fx_task)
    best: tuple[int, Path] | None = None
    try:
        for p in scan_dir.iterdir():
            if not p.is_file():
                continue
            m = pat.match(p.name)
            if not m or m.group(1).lower() != shot_cf:
                continue
            try:
                fr = int(m.group(2))
            except ValueError:
                continue
            if best is None or fr < best[0]:
                best = (fr, p)
    except OSError:
        return ""
    return str(best[1]) if best else ""


def fx_shot_sequence_usd_path_with_f4(abs_path: str, fx_task: str) -> str:
    """
    From ``.../sh003a_{task}.0000.usd`` -> ``.../sh003a_{task}.$F4.usd``.
    If the basename does not match the pattern, return ``abs_path`` unchanged.
    """
    if not abs_path:
        return ""
    p = Path(abs_path)
    m = _fx_shot_seq_re(fx_task).match(p.name)
    if not m:
        return str(p)
    shot_part, _digits, ext = m.group(1), m.group(2), m.group(3)
    new_name = f"{shot_part}_{fx_task}.$F4.{ext}"
    return str(p.parent / new_name)


def resolve_fx_shot_task_publish_and_usd(
    project_root: str,
    shot: str,
    fx_task: str,
    *,
    geo_usd_path: str = "",
    fx_version: str | None = None,
    fx_asset_token: str | None = None,
) -> tuple[str, str, str, str]:
    """
    Shared resolver for ``02_fx/<task>/publish`` USD sequences.

    Returns ``(publish_parent, version_name, asset_subfolder_token, usd_path_with_$F4)``.
    """
    shot_l = (shot or "").strip().lower()
    if not (project_root or "").strip() or not shot_l:
        return ("", "", "", "")
    pub = get_fx_shot_task_publish_dir(Path(project_root.strip()), shot_l, fx_task)
    pstr = str(pub)
    if not pub.is_dir():
        return (pstr, "", "", "")
    vdirs = list_version_dirs(pub)
    if not vdirs:
        return (pstr, "", "", "")
    ver_name = (fx_version or "").strip()
    if not ver_name or not (pub / ver_name).is_dir():
        ver_name = vdirs[-1].name
    ver_dir = pub / ver_name

    inferred_asset = ""
    if geo_usd_path:
        _t, an = _parse_asset_from_geo_filename(geo_usd_path)
        if an:
            inferred_asset = an

    asset_tok = ""
    target = ver_dir

    if fx_asset_token is not None:
        gat = fx_asset_token.strip()
        if gat:
            target = ver_dir / gat
            asset_tok = gat
        else:
            target = ver_dir
            asset_tok = ""
    else:
        if inferred_asset:
            cand = ver_dir / inferred_asset
            if cand.is_dir() and pick_fx_shot_sequence_entry_frame(cand, shot_l, fx_task):
                target = cand
                asset_tok = inferred_asset
        if not pick_fx_shot_sequence_entry_frame(target, shot_l, fx_task):
            if pick_fx_shot_sequence_entry_frame(ver_dir, shot_l, fx_task):
                target = ver_dir
                asset_tok = ""
            else:
                try:
                    for d in sorted(ver_dir.iterdir(), key=lambda x: x.name.lower()):
                        if d.is_dir() and pick_fx_shot_sequence_entry_frame(d, shot_l, fx_task):
                            target = d
                            asset_tok = d.name
                            break
                except OSError:
                    pass

    usd_raw = pick_fx_shot_sequence_entry_frame(target, shot_l, fx_task) if target.is_dir() else ""
    usd = fx_shot_sequence_usd_path_with_f4(usd_raw, fx_task) if usd_raw else ""
    return (pstr, ver_name, asset_tok, usd)


def get_groom_publish_dir(project_root: Path, shot: str) -> Path:
    """`<project_root>/02_shots/<shot>/02_fx/groom/publish`"""
    return get_fx_shot_task_publish_dir(project_root, shot, "groom")


def pick_groom_sequence_entry_frame(groom_dir: Path, shot: str) -> str:
    """Lowest frame ``{shot}_groom.####.*`` under ``groom_dir``."""
    return pick_fx_shot_sequence_entry_frame(groom_dir, shot, "groom")


def groom_usd_path_with_f4(abs_path: str) -> str:
    """Wraps :func:`fx_shot_sequence_usd_path_with_f4` for ``task="groom"``."""
    return fx_shot_sequence_usd_path_with_f4(abs_path, "groom")


def resolve_groom_publish_and_usd(
    project_root: str,
    shot: str,
    *,
    geo_usd_path: str = "",
    groom_version: str | None = None,
    groom_asset_token: str | None = None,
) -> tuple[str, str, str, str]:
    """
    Resolve groom publish layout.

    Returns ``(groom_publish_parent, version_name, groom_asset_token, groom_usd_path)``.
    ``groom_usd_path`` uses ``$F4`` (see :func:`groom_usd_path_with_f4`).
    """
    return resolve_fx_shot_task_publish_and_usd(
        project_root,
        shot,
        "groom",
        geo_usd_path=geo_usd_path,
        fx_version=groom_version,
        fx_asset_token=groom_asset_token,
    )


def get_cloth_publish_dir(project_root: Path, shot: str) -> Path:
    """`<project_root>/02_shots/<shot>/02_fx/cloth/publish`"""
    return get_fx_shot_task_publish_dir(project_root, shot, "cloth")


def pick_cloth_sequence_entry_frame(cloth_dir: Path, shot: str) -> str:
    """Lowest frame ``{shot}_cloth.####.*`` under ``cloth_dir``."""
    return pick_fx_shot_sequence_entry_frame(cloth_dir, shot, "cloth")


def cloth_usd_path_with_f4(abs_path: str) -> str:
    """Wraps :func:`fx_shot_sequence_usd_path_with_f4` for ``task="cloth"``."""
    return fx_shot_sequence_usd_path_with_f4(abs_path, "cloth")


def resolve_cloth_publish_and_usd(
    project_root: str,
    shot: str,
    *,
    geo_usd_path: str = "",
    cloth_version: str | None = None,
    cloth_asset_token: str | None = None,
) -> tuple[str, str, str, str]:
    """
    Resolve cloth publish (``{shot}_cloth.####.usd``). Same layout rules as groom.

    Returns ``(cloth_publish_parent, version_name, cloth_asset_token, cloth_usd_path)`` with ``$F4``.
    """
    return resolve_fx_shot_task_publish_and_usd(
        project_root,
        shot,
        "cloth",
        geo_usd_path=geo_usd_path,
        fx_version=cloth_version,
        fx_asset_token=cloth_asset_token,
    )


def _iter_version_dirs(publish_dir: Path) -> Iterable[Path]:
    if not publish_dir.is_dir():
        return []
    try:
        return (p for p in publish_dir.iterdir() if p.is_dir() and _VERSION_RE.match(p.name))
    except OSError:
        return []


def list_version_dirs(publish_dir: Path) -> list[Path]:
    """
    Return version folders under publish (v001, v002, ...), sorted by version number.
    """
    out: list[tuple[int, Path]] = []
    for d in _iter_version_dirs(publish_dir):
        m = _VERSION_RE.match(d.name)
        if not m:
            continue
        try:
            out.append((int(m.group(1)), d))
        except ValueError:
            continue
    out.sort(key=lambda x: x[0])
    return [p for _, p in out]


def find_usd_files(root_dir: Path) -> list[Path]:
    """
    Recursively find USD files under root_dir (usd/usda/usdc).
    Sorted by path.
    """
    if not root_dir.is_dir():
        return []
    files: list[Path] = []
    try:
        for suffix in _USD_SUFFIXES:
            files.extend(root_dir.rglob(f"*{suffix}"))
    except OSError:
        return []
    files = [p for p in files if p.is_file()]
    files.sort(key=lambda p: str(p).lower())
    return files


def scan_from_hip_path(hip_path: str | Path) -> AnimPublishScanResult:
    """
    Main entry: scan based on a hip path (string or Path).
    """
    hip = Path(hip_path)
    project_root = find_project_root(hip)
    shot = detect_shot_from_path(hip)

    shot_root = None
    anim_publish_dir = None
    version_dirs: tuple[Path, ...] = ()
    usd_files: tuple[Path, ...] = ()

    if project_root is not None and shot is not None:
        shot_root = get_shot_root(project_root, shot)
        anim_publish_dir = get_anim_publish_dir(project_root, shot)
        vdirs = list_version_dirs(anim_publish_dir)
        version_dirs = tuple(vdirs)
        usd_files = tuple(find_usd_files(anim_publish_dir))

    return AnimPublishScanResult(
        hip_path=hip,
        project_root=project_root,
        shot=shot,
        shot_root=shot_root,
        anim_publish_dir=anim_publish_dir,
        version_dirs=version_dirs,
        usd_files=usd_files,
    )


def scan_from_current_hip() -> AnimPublishScanResult:
    """
    Convenience: scan based on the currently opened Houdini hip file.
    If not running in Houdini or hip isn't saved, hip_path will be '.' and other fields None/empty.
    """
    from apps.houdini import adapter

    hip_path = adapter.get_hip_path()
    if not hip_path:
        return AnimPublishScanResult(
            hip_path=Path("."),
            project_root=None,
            shot=None,
            shot_root=None,
            anim_publish_dir=None,
            version_dirs=(),
            usd_files=(),
        )
    return scan_from_hip_path(hip_path)


# ============================================================
# HDA helper layer (menu + callbacks)
# ============================================================


def _get_callback_string_value(kwargs: dict) -> str:
    """
    Houdini may pass `kwargs['parm']` for parameter callbacks.
    When unavailable, try a small set of common parameter names.
    """

    parm = kwargs.get("parm")
    if parm is not None:
        try:
            return parm.evalAsString()
        except Exception:
            return ""

    node = kwargs.get("node")
    if hou is not None and not isinstance(node, hou.Node):
        return ""
    if node is None:
        return ""

    # Common parm candidates used by HDA variants.
    for cand in (
        "geo_usd_file",
        "cam_usd_file",
        "Geo_File_List",
        "Cam_File_List",
        "geo_selected_usd_path",
        "cam_selected_usd_path",
        "selected_usd_path",
    ):
        try:
            p = node.parm(cand)
        except Exception:
            p = None
        if p is None:
            continue
        try:
            v = p.evalAsString()
            if v:
                return v
        except Exception:
            continue
    return ""


def _set_first_existing_parm(node: Any, names: tuple[str, ...], value: str) -> bool:
    """Set the first existing string parm by name. Returns True if set."""
    if node is None:
        return False
    for n in names:
        try:
            p = node.parm(n)
        except Exception:
            p = None
        if p is None:
            continue
        try:
            p.set(value)
            return True
        except Exception:
            continue
    return False


def _status_set(node: Any, msg: str) -> None:
    _set_first_existing_parm(node, _HDA_STATUS_PARMS, msg)


def _set_mx_geo_cam_parm(node: Any, usd_path: str) -> None:
    """
    `mx_geo_cam` int: 0 = geo_*, 1 = cam_*, -1 = other or empty path.
    No-op if parm does not exist on the HDA.
    """
    if node is None:
        return
    try:
        p = node.parm(_MX_GEO_CAM)
    except Exception:
        p = None
    if p is None:
        return
    val = -1
    if usd_path and Path(usd_path).is_file():
        low = Path(usd_path).name.lower()
        if low.startswith("geo_"):
            val = 0
        elif low.startswith("cam_"):
            val = 1
    try:
        p.set(val)
    except Exception:
        pass


def _clear_mx_groom_parms(node: Any, *, clear_publish_parent: bool = False) -> None:
    _set_first_existing_parm(node, (_MX_SELECTED_GROOM_USD_PATH,), "")
    _set_first_existing_parm(node, (_MX_GROOM_VERSION,), "")
    _set_first_existing_parm(node, (_MX_GROOM_ASSET,), "")
    if clear_publish_parent:
        _set_first_existing_parm(node, (_MX_GROOM_PUBLISH_PARENT,), "")


def _clear_mx_cloth_parms(node: Any, *, clear_publish_parent: bool = False) -> None:
    _set_first_existing_parm(node, (_MX_SELECTED_CLOTH_USD_PATH,), "")
    _set_first_existing_parm(node, (_MX_CLOTH_VERSION,), "")
    _set_first_existing_parm(node, (_MX_CLOTH_ASSET,), "")
    if clear_publish_parent:
        _set_first_existing_parm(node, (_MX_CLOTH_PUBLISH_PARENT,), "")


def _mx_groom_version_folder(node: Any) -> str:
    """Resolve ``<mx_groom_publish_parent>/<mx_groom_version>``."""
    try:
        p_parent = node.parm(_MX_GROOM_PUBLISH_PARENT)
        p_ver = node.parm(_MX_GROOM_VERSION)
    except Exception:
        return ""
    if p_parent is None or p_ver is None:
        return ""
    try:
        parent = p_parent.evalAsString().strip()
        ver = p_ver.evalAsString().strip()
    except Exception:
        return ""
    if not parent or not ver:
        return ""
    folder = Path(parent) / ver
    return str(folder) if folder.is_dir() else ""


def _apply_mx_groom_resolve(
    node: Any,
    *,
    project_root: str,
    shot: str,
    geo_usd_path: str,
    groom_version: str | None,
    groom_asset_token: str | None,
) -> None:
    gpg, gv, ga, gp = resolve_groom_publish_and_usd(
        project_root,
        shot,
        geo_usd_path=geo_usd_path,
        groom_version=groom_version,
        groom_asset_token=groom_asset_token,
    )
    _set_first_existing_parm(node, (_MX_GROOM_PUBLISH_PARENT,), gpg)
    _set_first_existing_parm(node, (_MX_GROOM_VERSION,), gv)
    _set_first_existing_parm(node, (_MX_GROOM_ASSET,), ga)
    _set_first_existing_parm(node, (_MX_SELECTED_GROOM_USD_PATH,), gp)


def _mx_cloth_version_folder(node: Any) -> str:
    """Resolve ``<mx_cloth_publish_parent>/<mx_cloth_version>``."""
    try:
        p_parent = node.parm(_MX_CLOTH_PUBLISH_PARENT)
        p_ver = node.parm(_MX_CLOTH_VERSION)
    except Exception:
        return ""
    if p_parent is None or p_ver is None:
        return ""
    try:
        parent = p_parent.evalAsString().strip()
        ver = p_ver.evalAsString().strip()
    except Exception:
        return ""
    if not parent or not ver:
        return ""
    folder = Path(parent) / ver
    return str(folder) if folder.is_dir() else ""


def _apply_mx_cloth_resolve(
    node: Any,
    *,
    project_root: str,
    shot: str,
    geo_usd_path: str,
    cloth_version: str | None,
    cloth_asset_token: str | None,
) -> None:
    cpb, cv, ca, cp = resolve_cloth_publish_and_usd(
        project_root,
        shot,
        geo_usd_path=geo_usd_path,
        cloth_version=cloth_version,
        cloth_asset_token=cloth_asset_token,
    )
    _set_first_existing_parm(node, (_MX_CLOTH_PUBLISH_PARENT,), cpb)
    _set_first_existing_parm(node, (_MX_CLOTH_VERSION,), cv)
    _set_first_existing_parm(node, (_MX_CLOTH_ASSET,), ca)
    _set_first_existing_parm(node, (_MX_SELECTED_CLOTH_USD_PATH,), cp)


def _resolve_version_folder_from_node(node: Any) -> str:
    """
    Resolve the active version folder for scanning USD:
    - prefer `anim_publish_dir` if it's an existing directory
    - else join `anim_publish_parent` + `anim_version`
    """
    try:
        p_dir = node.parm("anim_publish_dir")
    except Exception:
        p_dir = None
    if p_dir is not None:
        try:
            d = p_dir.evalAsString().strip()
            if d and Path(d).is_dir():
                return str(Path(d))
        except Exception:
            pass

    try:
        parent = node.parm("anim_publish_parent")
        ver = node.parm("anim_version")
    except Exception:
        parent = None
        ver = None
    if parent is None or ver is None:
        return ""
    try:
        parent_s = parent.evalAsString().strip()
        ver_s = ver.evalAsString().strip()
    except Exception:
        return ""
    if not parent_s or not ver_s:
        return ""
    joined = Path(parent_s) / ver_s
    return str(joined) if joined.is_dir() else ""


def _infer_publish_parent_and_latest_from_current_hip(node: Any) -> tuple[str, str, str]:
    """
    Returns (anim_publish_parent, anim_version, anim_publish_dir_version_folder).
    """
    try:
        from apps.houdini import adapter as houdini_adapter

        hip_path = houdini_adapter.get_hip_path() or ""
    except Exception:
        hip_path = ""

    if not hip_path:
        return "", "", ""

    res = scan_from_hip_path(hip_path)
    if res.anim_publish_dir is None:
        return "", "", ""

    parent = str(res.anim_publish_dir)
    latest_version = res.version_dirs[-1].name if res.version_dirs else ""
    version_folder = str(res.version_dirs[-1]) if res.version_dirs else ""
    return parent, latest_version, version_folder


KNOWN_LOOKDEV_ASSET_TYPES = ("char", "prop", "env", "veh")


def _version_key(name: str) -> int:
    m = re.search(r"(\d+)", name)
    return int(m.group(1)) if m else -1


def _parse_asset_from_geo_filename(geo_usd_path: str) -> tuple[str, str]:
    """
    Basename example:
    - geo_char_Zephys.usd -> ("char", "Zephys")
    - cam_char_Zephys.usd -> ("char", "Zephys")
    """
    base = Path(geo_usd_path).name
    stem = Path(base).stem
    low = stem.lower()
    if low.startswith("geo_"):
        rest = stem[len("geo_") :]
    elif low.startswith("cam_"):
        rest = stem[len("cam_") :]
    else:
        return ("", "")
    parts = rest.split("_", 1)
    if len(parts) == 2 and parts[0].lower() in KNOWN_LOOKDEV_ASSET_TYPES:
        return (parts[0].lower(), parts[1])
    low = rest.lower()
    for t in KNOWN_LOOKDEV_ASSET_TYPES:
        prefix = f"{t}_"
        if low.startswith(prefix):
            return (t, rest[len(prefix) :])
    return ("", "")


def _find_latest_v_folder(publish_base_dir: Path) -> Optional[Path]:
    if not publish_base_dir.is_dir():
        return None
    try:
        dirs = [d for d in publish_base_dir.iterdir() if d.is_dir() and _VERSION_RE.match(d.name)]
    except OSError:
        return None
    if not dirs:
        return None
    dirs.sort(key=lambda p: _version_key(p.name))
    return dirs[-1]


def _find_lookdev_publish_file(latest_v_dir: Path, expected_stem: str) -> str:
    if not latest_v_dir or not latest_v_dir.is_dir():
        return ""
    expected_low = expected_stem.lower()
    try:
        names = [p for p in latest_v_dir.iterdir() if p.is_file()]
    except OSError:
        return ""
    for p in names:
        if p.suffix.lower() not in _USD_SUFFIXES:
            continue
        if p.stem.lower() == expected_low:
            return str(p)
    # Fallback: exact .usd
    direct = latest_v_dir / f"{expected_stem}.usd"
    return str(direct) if direct.is_file() else ""


def resolve_geo_lookdev_path_from_geo_usd(geo_usd_path: str, project_root: str) -> tuple[str, str, str]:
    """
    Given a geo USD path and project root, resolve latest lookdev USD:
    Returns (lookdev_publish_parent, lookdev_version, lookdev_usd_path).
    """
    asset_type, asset_name = _parse_asset_from_geo_filename(geo_usd_path)
    if not asset_type or not asset_name:
        return ("", "", "")
    assets_root = Path(project_root) / "01_assets"
    if not assets_root.is_dir():
        return ("", "", "")

    expected_stem = f"{asset_type}_{asset_name}_lookdev_publish"

    # Search groups starting with "_" (common: _characters, _props, ...)
    try:
        groups = [d for d in assets_root.iterdir() if d.is_dir() and d.name.startswith("_")]
    except OSError:
        groups = []
    if not groups:
        groups = [assets_root / "_characters"]

    for group_dir in groups:
        publish_base = group_dir / f"{asset_type}_{asset_name}" / "05_lookdev" / "publish"
        if not publish_base.is_dir():
            continue
        latest_v_dir = _find_latest_v_folder(publish_base)
        if not latest_v_dir:
            continue
        fp = _find_lookdev_publish_file(latest_v_dir, expected_stem=expected_stem)
        if fp:
            return (str(publish_base), latest_v_dir.name, fp)
    return ("", "", "")


def cb_autofill_anim_publish_from_hip(kwargs: dict) -> None:
    """Auto-resolve anim publish folder/version from the current hip path."""
    node = kwargs.get("node")
    if hou is not None and (node is None or not isinstance(node, hou.Node)):
        return
    if node is None:
        return

    parent, latest, version_folder = _infer_publish_parent_and_latest_from_current_hip(node)
    if not parent or not latest or not version_folder:
        _status_set(
            node,
            "Could not infer shot/publish folder from current hip path. Set anim_publish_parent/anim_version manually.",
        )
        return

    _set_first_existing_parm(node, ("anim_publish_parent",), parent)
    _set_first_existing_parm(node, ("anim_version",), latest)
    _set_first_existing_parm(node, ("anim_publish_dir",), version_folder)


def cb_autofill_mx_from_hip(kwargs: dict) -> None:
    """
    Autofill our proposed parm set:
    - mx_project_root
    - mx_shot
    - mx_anim_publish_parent + mx_anim_version
    - mx_lookdev_publish_parent + mx_lookdev_version
    - mx_groom_publish_parent / mx_cloth_publish_parent (from shot; USD filled when anim resolves)
    """
    node = kwargs.get("node")
    if hou is not None and (node is None or not isinstance(node, hou.Node)):
        return
    if node is None:
        return

    try:
        from apps.houdini import adapter as houdini_adapter

        hip_path = houdini_adapter.get_hip_path() or ""
    except Exception:
        hip_path = ""

    if not hip_path:
        _status_set(node, "Hip file is not saved; cannot infer project/shot.")
        return

    res = scan_from_hip_path(hip_path)
    # If hip is not inside the project tree, project_root may be None.
    # Fallback to user-provided `mx_project_root` parm.
    project_root: str = ""
    shot: str = ""

    if res.project_root is not None:
        project_root = str(res.project_root)

    if res.shot is not None:
        shot = res.shot

    # Fallback to current parm values if inference failed.
    try:
        if not project_root:
            p_pr = node.parm(_MX_PROJECT_ROOT)
            if p_pr is not None:
                project_root = p_pr.evalAsString().strip()
    except Exception:
        pass

    try:
        if not shot:
            p_sh = node.parm(_MX_SHOT)
            if p_sh is not None:
                shot = p_sh.evalAsString().strip().lower()
    except Exception:
        pass

    if not project_root or not shot:
        _status_set(
            node,
            "Could not infer project root/shot from hip path. "
            "Please set mx_project_root and mx_shot manually.",
        )
        return

    _set_first_existing_parm(node, (_MX_PROJECT_ROOT,), project_root)
    _set_first_existing_parm(node, (_MX_SHOT,), shot)

    anim_parent = str(get_anim_publish_dir(Path(project_root), shot))
    _set_first_existing_parm(node, (_MX_ANIM_PUBLISH_PARENT,), anim_parent)
    _set_first_existing_parm(
        node,
        (_MX_GROOM_PUBLISH_PARENT,),
        str(get_groom_publish_dir(Path(project_root), shot)),
    )
    _set_first_existing_parm(
        node,
        (_MX_CLOTH_PUBLISH_PARENT,),
        str(get_cloth_publish_dir(Path(project_root), shot)),
    )

    # Latest anim version (if any)
    anim_vdirs = list_version_dirs(Path(anim_parent))
    anim_latest = anim_vdirs[-1].name if anim_vdirs else ""
    _set_first_existing_parm(node, (_MX_ANIM_VERSION,), anim_latest)

    # Clear stale outputs; we'll recompute right after setting mx_anim_usd.
    _set_first_existing_parm(node, (_MX_SELECTED_ANIM_USD_PATH,), "")
    _set_first_existing_parm(node, (_MX_SELECTED_LOOKDEV_USD_PATH,), "")
    _set_first_existing_parm(node, (_MX_LOOKDEV_PUBLISH_PARENT,), "")
    _set_first_existing_parm(node, (_MX_LOOKDEV_VERSION,), "")
    _clear_mx_groom_parms(node, clear_publish_parent=True)
    _clear_mx_cloth_parms(node, clear_publish_parent=True)
    _set_first_existing_parm(node, ("mx_meta_summary", "mx_timeline_meta_summary", "mx_meta_text"), "")
    _set_first_existing_parm(node, ("mx_meta_fps", "mx_timeline_meta_fps"), "")
    _set_first_existing_parm(node, ("mx_meta_playback_range", "mx_timeline_meta_playback_range"), "")
    _set_first_existing_parm(node, ("mx_meta_raw_json", "mx_timeline_meta_raw_json"), "")
    _set_mx_geo_cam_parm(node, "")

    # Auto-select preferred USD in the resolved anim version folder (geo first).
    first_token = _pick_first_anim_usd_token(node, prefer_geo=True)
    if not first_token:
        _status_set(node, f"Inferred project={Path(project_root).name} | shot={shot} (but no USD found).")
        return

    try:
        p_usd = node.parm(_MX_ANIM_USD)
        if p_usd is not None:
            p_usd.set(first_token)
            # Manually run the resolver so selected anim path + lookdev get updated immediately.
            cb_on_mx_anim_usd_change({"node": node, "parm": p_usd})
    except Exception:
        # Even if setting mx_anim_usd fails, keep inferred project/shot.
        pass

    _status_set(node, f"Inferred project={Path(project_root).name} | shot={shot}")


def menu_mx_shot_list(node: Any) -> list[str]:
    """Menu for `mx_shot` based on `mx_project_root` (or infer from hip)."""
    if hou is not None and (node is None or not isinstance(node, hou.Node)):
        return ["", "Not in Houdini node"]
    if node is None:
        return ["", "Invalid node"]

    project_root = ""
    try:
        p = node.parm(_MX_PROJECT_ROOT)
        if p is not None:
            project_root = p.evalAsString().strip()
    except Exception:
        project_root = ""

    if not project_root or not Path(project_root).is_dir():
        try:
            from apps.houdini import adapter as houdini_adapter

            hip_path = houdini_adapter.get_hip_path() or ""
        except Exception:
            hip_path = ""
        if hip_path:
            pr = find_project_root(Path(hip_path))
            project_root = str(pr) if pr else ""

    if not project_root or not Path(project_root).is_dir():
        return ["", "Set mx_project_root"]

    shots_dir = Path(project_root) / "02_shots"
    if not shots_dir.is_dir():
        return ["", "Invalid 02_shots"]

    shots: list[str] = []
    try:
        for d in shots_dir.iterdir():
            if d.is_dir() and _SHOT_RE.match(d.name):
                shots.append(d.name.lower())
    except OSError:
        return ["", "Cannot read shots"]

    if not shots:
        return ["", "No shots found"]

    shots.sort(key=str.lower)
    menu: list[str] = []
    for s in shots:
        menu.extend([s, s])
    return menu


def menu_mx_anim_version_list(node: Any) -> list[str]:
    """Menu for `mx_anim_version` based on `mx_anim_publish_parent`."""
    if hou is not None and (node is None or not isinstance(node, hou.Node)):
        return ["", "Not in Houdini node"]
    if node is None:
        return ["", "Invalid node"]

    parent = ""
    try:
        p = node.parm(_MX_ANIM_PUBLISH_PARENT)
        if p is not None:
            parent = p.evalAsString().strip()
    except Exception:
        parent = ""

    if not parent or not Path(parent).is_dir():
        # Try resolve from project_root + shot
        try:
            pr = node.parm(_MX_PROJECT_ROOT)
            sh = node.parm(_MX_SHOT)
            project_root = pr.evalAsString().strip() if pr is not None else ""
            shot = sh.evalAsString().strip() if sh is not None else ""
        except Exception:
            project_root, shot = "", ""
        if project_root and shot:
            parent = str(get_anim_publish_dir(Path(project_root), shot.lower()))
            _set_first_existing_parm(node, (_MX_ANIM_PUBLISH_PARENT,), parent)

    if not parent or not Path(parent).is_dir():
        return ["", "Invalid mx_anim_publish_parent"]

    vdirs = list_version_dirs(Path(parent))
    if not vdirs:
        return ["", "No v### folders"]

    menu: list[str] = []
    for vd in vdirs:
        menu.extend([vd.name, vd.name])
    return menu


def menu_mx_lookdev_version_list(node: Any) -> list[str]:
    """Menu for `mx_lookdev_version` based on `mx_lookdev_publish_parent` (asset-level, set on USD selection)."""
    if hou is not None and (node is None or not isinstance(node, hou.Node)):
        return ["", "Not in Houdini node"]
    if node is None:
        return ["", "Invalid node"]

    parent = ""
    try:
        p = node.parm(_MX_LOOKDEV_PUBLISH_PARENT)
        if p is not None:
            parent = p.evalAsString().strip()
    except Exception:
        parent = ""

    if not parent or not Path(parent).is_dir():
        return ["", "Invalid mx_lookdev_publish_parent"]

    vdirs = list_version_dirs(Path(parent))
    if not vdirs:
        return ["", "No v### folders"]

    menu: list[str] = []
    for vd in vdirs:
        menu.extend([vd.name, vd.name])
    return menu


def menu_mx_groom_version_list(node: Any) -> list[str]:
    """Menu for ``mx_groom_version`` from ``mx_groom_publish_parent`` (or project + ``mx_shot``)."""
    if hou is not None and (node is None or not isinstance(node, hou.Node)):
        return ["", "Not in Houdini node"]
    if node is None:
        return ["", "Invalid node"]

    parent = ""
    try:
        p = node.parm(_MX_GROOM_PUBLISH_PARENT)
        if p is not None:
            parent = p.evalAsString().strip()
    except Exception:
        parent = ""

    if not parent or not Path(parent).is_dir():
        try:
            pr = node.parm(_MX_PROJECT_ROOT)
            sh = node.parm(_MX_SHOT)
            project_root = pr.evalAsString().strip() if pr is not None else ""
            shot = sh.evalAsString().strip().lower() if sh is not None else ""
        except Exception:
            project_root, shot = "", ""
        if project_root and shot:
            parent = str(get_groom_publish_dir(Path(project_root), shot))
            _set_first_existing_parm(node, (_MX_GROOM_PUBLISH_PARENT,), parent)

    if not parent or not Path(parent).is_dir():
        return ["", "Invalid mx_groom_publish_parent"]

    vdirs = list_version_dirs(Path(parent))
    if not vdirs:
        return ["", "No v### folders"]

    menu: list[str] = []
    for vd in vdirs:
        menu.extend([vd.name, vd.name])
    return menu


def menu_mx_groom_asset_list(node: Any) -> list[str]:
    """Menu for ``mx_groom_asset``: subfolder under groom version, or empty token = files in version root."""
    if hou is not None and (node is None or not isinstance(node, hou.Node)):
        return ["", "Not in Houdini node"]
    if node is None:
        return ["", "Invalid node"]

    shot = ""
    try:
        p_sh = node.parm(_MX_SHOT)
        shot = p_sh.evalAsString().strip().lower() if p_sh is not None else ""
    except Exception:
        shot = ""

    ver_folder = _mx_groom_version_folder(node)
    if not ver_folder:
        return ["", "Invalid groom version folder"]
    if not shot:
        return ["", "Missing mx_shot"]

    vpath = Path(ver_folder)
    menu: list[str] = []
    if pick_groom_sequence_entry_frame(vpath, shot):
        menu.extend(["", "(version root)"])
    try:
        for d in sorted(vpath.iterdir(), key=lambda x: x.name.lower()):
            if not d.is_dir():
                continue
            if pick_groom_sequence_entry_frame(d, shot):
                menu.extend([d.name, d.name])
    except OSError:
        pass
    if not menu:
        return ["", "No groom sequences"]
    return menu


def menu_mx_cloth_version_list(node: Any) -> list[str]:
    """Menu for ``mx_cloth_version`` from ``mx_cloth_publish_parent`` (or project + ``mx_shot``)."""
    if hou is not None and (node is None or not isinstance(node, hou.Node)):
        return ["", "Not in Houdini node"]
    if node is None:
        return ["", "Invalid node"]

    parent = ""
    try:
        p = node.parm(_MX_CLOTH_PUBLISH_PARENT)
        if p is not None:
            parent = p.evalAsString().strip()
    except Exception:
        parent = ""

    if not parent or not Path(parent).is_dir():
        try:
            pr = node.parm(_MX_PROJECT_ROOT)
            sh = node.parm(_MX_SHOT)
            project_root = pr.evalAsString().strip() if pr is not None else ""
            shot = sh.evalAsString().strip().lower() if sh is not None else ""
        except Exception:
            project_root, shot = "", ""
        if project_root and shot:
            parent = str(get_cloth_publish_dir(Path(project_root), shot))
            _set_first_existing_parm(node, (_MX_CLOTH_PUBLISH_PARENT,), parent)

    if not parent or not Path(parent).is_dir():
        return ["", "Invalid mx_cloth_publish_parent"]

    vdirs = list_version_dirs(Path(parent))
    if not vdirs:
        return ["", "No v### folders"]

    menu: list[str] = []
    for vd in vdirs:
        menu.extend([vd.name, vd.name])
    return menu


def menu_mx_cloth_asset_list(node: Any) -> list[str]:
    """Menu for ``mx_cloth_asset``: subfolder under cloth version; empty token = USD in version root."""
    if hou is not None and (node is None or not isinstance(node, hou.Node)):
        return ["", "Not in Houdini node"]
    if node is None:
        return ["", "Invalid node"]

    shot = ""
    try:
        p_sh = node.parm(_MX_SHOT)
        shot = p_sh.evalAsString().strip().lower() if p_sh is not None else ""
    except Exception:
        shot = ""

    ver_folder = _mx_cloth_version_folder(node)
    if not ver_folder:
        return ["", "Invalid cloth version folder"]
    if not shot:
        return ["", "Missing mx_shot"]

    vpath = Path(ver_folder)
    menu: list[str] = []
    if pick_cloth_sequence_entry_frame(vpath, shot):
        menu.extend(["", "(version root)"])
    try:
        for d in sorted(vpath.iterdir(), key=lambda x: x.name.lower()):
            if not d.is_dir():
                continue
            if pick_cloth_sequence_entry_frame(d, shot):
                menu.extend([d.name, d.name])
    except OSError:
        pass
    if not menu:
        return ["", "No cloth sequences"]
    return menu


def _mx_anim_version_folder(node: Any) -> str:
    """Resolve `<mx_anim_publish_parent>/<mx_anim_version>`."""
    try:
        p_parent = node.parm(_MX_ANIM_PUBLISH_PARENT)
        p_ver = node.parm(_MX_ANIM_VERSION)
    except Exception:
        return ""
    if p_parent is None or p_ver is None:
        return ""
    try:
        parent = p_parent.evalAsString().strip()
        ver = p_ver.evalAsString().strip()
    except Exception:
        return ""
    if not parent or not ver:
        return ""
    folder = Path(parent) / ver
    return str(folder) if folder.is_dir() else ""


def _pick_first_anim_usd_token(node: Any, *, prefer_geo: bool = True) -> str:
    """Pick a USD token from the active anim version folder.

    If `prefer_geo=True`, choose the first `geo_*.usd/usda/usdc` file by sorted order.
    """
    folder = _mx_anim_version_folder(node)
    if not folder:
        return ""
    usd_files = find_usd_files(Path(folder))
    if not usd_files:
        return ""
    if prefer_geo:
        geo_files = [p for p in usd_files if p.name.lower().startswith("geo_")]
        if geo_files:
            return str(geo_files[0])
    return str(usd_files[0])


def menu_mx_anim_usd_list(node: Any) -> list[str]:
    """Menu for `mx_anim_usd`: token = abs path of USD files under selected anim version folder."""
    if hou is not None and (node is None or not isinstance(node, hou.Node)):
        return ["", "Not in Houdini node"]
    if node is None:
        return ["", "Invalid node"]

    folder = _mx_anim_version_folder(node)
    if not folder:
        return ["", "Invalid anim version folder"]

    usd_files = find_usd_files(Path(folder))
    if not usd_files:
        return ["", "No USD Files"]

    # Keep stable ordering; show basename.
    menu: list[str] = []
    for p in usd_files:
        menu.extend([str(p), p.name])
    return menu


def cb_on_mx_anim_usd_change(kwargs: dict) -> None:
    """
    Callback for `mx_anim_usd` menu parm:
    - writes `mx_selected_anim_usd_path`
    - if selected file is geo_*, resolves lookdev and writes:
      - mx_lookdev_publish_parent
      - mx_lookdev_version (latest)
      - mx_selected_lookdev_usd_path
    - if `mx_enable_groom` on: resolves groom sequence (``{shot}_groom.####.usd``) and related parms
    - if `mx_enable_cloth` on: same for cloth (``{shot}_cloth.####.usd`` under ``02_fx/cloth``)
    """
    node = kwargs.get("node")
    if hou is not None and (node is None or not isinstance(node, hou.Node)):
        return
    if node is None:
        return

    selected = _get_callback_string_value(kwargs)
    if not selected or not Path(selected).is_file():
        _set_first_existing_parm(node, (_MX_SELECTED_ANIM_USD_PATH,), "")
        _set_first_existing_parm(node, (_MX_SELECTED_LOOKDEV_USD_PATH,), "")
        _set_first_existing_parm(node, (_MX_LOOKDEV_PUBLISH_PARENT,), "")
        _set_first_existing_parm(node, (_MX_LOOKDEV_VERSION,), "")
        _clear_mx_groom_parms(node, clear_publish_parent=True)
        _clear_mx_cloth_parms(node, clear_publish_parent=True)
        _set_mx_geo_cam_parm(node, "")
        _status_set(node, "Selected USD is empty or missing on disk.")
        return

    selected = str(Path(selected))
    _set_first_existing_parm(node, (_MX_SELECTED_ANIM_USD_PATH,), selected)
    _set_mx_geo_cam_parm(node, selected)

    try:
        p_pr = node.parm(_MX_PROJECT_ROOT)
        project_root = p_pr.evalAsString().strip() if p_pr is not None else ""
    except Exception:
        project_root = ""

    # Lookdev (optional gate)
    enabled_ld = True
    try:
        p_en = node.parm(_MX_ENABLE_LOOKDEV)
        if p_en is not None:
            enabled_ld = int(p_en.eval()) != 0
    except Exception:
        enabled_ld = True

    look_path = ""
    look_ver = ""
    if enabled_ld:
        look_parent, look_ver, look_path = resolve_geo_lookdev_path_from_geo_usd(selected, project_root)
        _set_first_existing_parm(node, (_MX_LOOKDEV_PUBLISH_PARENT,), look_parent)
        _set_first_existing_parm(node, (_MX_LOOKDEV_VERSION,), look_ver)
        _set_first_existing_parm(node, (_MX_SELECTED_LOOKDEV_USD_PATH,), look_path)
    else:
        _set_first_existing_parm(node, (_MX_SELECTED_LOOKDEV_USD_PATH,), "")
        _set_first_existing_parm(node, (_MX_LOOKDEV_PUBLISH_PARENT,), "")
        _set_first_existing_parm(node, (_MX_LOOKDEV_VERSION,), "")

    # Groom (optional gate; infer asset folder from geo/cam basename)
    enabled_gr = True
    try:
        p_gr = node.parm(_MX_ENABLE_GROOM)
        if p_gr is not None:
            enabled_gr = int(p_gr.eval()) != 0
    except Exception:
        enabled_gr = True

    try:
        p_sh = node.parm(_MX_SHOT)
        shot = p_sh.evalAsString().strip().lower() if p_sh is not None else ""
    except Exception:
        shot = ""

    if enabled_gr and project_root and shot:
        _apply_mx_groom_resolve(
            node,
            project_root=project_root,
            shot=shot,
            geo_usd_path=selected,
            groom_version=None,
            groom_asset_token=None,
        )
    else:
        _clear_mx_groom_parms(node, clear_publish_parent=True)

    enabled_cl = True
    try:
        p_cl = node.parm(_MX_ENABLE_CLOTH)
        if p_cl is not None:
            enabled_cl = int(p_cl.eval()) != 0
    except Exception:
        enabled_cl = True

    if enabled_cl and project_root and shot:
        _apply_mx_cloth_resolve(
            node,
            project_root=project_root,
            shot=shot,
            geo_usd_path=selected,
            cloth_version=None,
            cloth_asset_token=None,
        )
    else:
        _clear_mx_cloth_parms(node, clear_publish_parent=True)

    # Immediately display timeline metadata (if available).
    # This is intentionally not gated by the "Apply Timeline" button.
    _maybe_update_mx_timeline_meta_from_current_anim(node)

    # Status: anim + lookdev + groom + cloth
    parts: list[str] = [f"Anim USD: {Path(selected).name}"]
    if not enabled_ld:
        parts.append("Lookdev off")
    elif look_path:
        parts.append(f"Lookdev ({look_ver})")
    else:
        parts.append("Lookdev not found")

    gp = ""
    try:
        p_gp = node.parm(_MX_SELECTED_GROOM_USD_PATH)
        gp = p_gp.evalAsString().strip() if p_gp is not None else ""
    except Exception:
        gp = ""

    if not enabled_gr:
        parts.append("Groom off")
    elif gp:
        parts.append("Groom OK")
    else:
        parts.append("Groom not found")

    cp = ""
    try:
        p_cp = node.parm(_MX_SELECTED_CLOTH_USD_PATH)
        cp = p_cp.evalAsString().strip() if p_cp is not None else ""
    except Exception:
        cp = ""

    if not enabled_cl:
        parts.append("Cloth off")
    elif cp:
        parts.append("Cloth OK")
    else:
        parts.append("Cloth not found")

    _status_set(node, " | ".join(parts))


def cb_on_mx_enable_lookdev_change(kwargs: dict) -> None:
    """
    Optional callback: when checkbox toggles:
    - disabled => clear lookdev parms
    - enabled => resolve lookdev for current selected anim USD (if it's geo_)
    """
    node = kwargs.get("node")
    if hou is not None and (node is None or not isinstance(node, hou.Node)):
        return
    if node is None:
        return

    enabled = False
    try:
        p_en = node.parm(_MX_ENABLE_LOOKDEV)
        if p_en is not None:
            enabled = int(p_en.eval()) != 0
        else:
            enabled = False
    except Exception:
        enabled = False

    if not enabled:
        _set_first_existing_parm(node, (_MX_SELECTED_LOOKDEV_USD_PATH,), "")
        _set_first_existing_parm(node, (_MX_LOOKDEV_PUBLISH_PARENT,), "")
        _set_first_existing_parm(node, (_MX_LOOKDEV_VERSION,), "")
        _status_set(node, "Lookdev disabled (mx_enable_lookdev=0). Cleared lookdev outputs.")
        return

    # Enabled: resolve based on current selected anim usd path.
    try:
        p_sel = node.parm(_MX_SELECTED_ANIM_USD_PATH)
        selected = p_sel.evalAsString().strip() if p_sel is not None else ""
    except Exception:
        selected = ""

    if not selected or not Path(selected).is_file():
        _status_set(node, "Lookdev enabled but selected anim USD is empty/missing on disk.")
        return

    # Resolve lookdev for geo USD.
    try:
        p_pr = node.parm(_MX_PROJECT_ROOT)
        project_root = p_pr.evalAsString().strip() if p_pr is not None else ""
    except Exception:
        project_root = ""

    look_parent, look_ver, look_path = resolve_geo_lookdev_path_from_geo_usd(selected, project_root)
    _set_first_existing_parm(node, (_MX_LOOKDEV_PUBLISH_PARENT,), look_parent)
    _set_first_existing_parm(node, (_MX_LOOKDEV_VERSION,), look_ver)
    _set_first_existing_parm(node, (_MX_SELECTED_LOOKDEV_USD_PATH,), look_path)

    if look_path:
        _status_set(node, f"Lookdev resolved ({look_ver}) for {Path(selected).name}.")
    else:
        _status_set(node, f"Lookdev not found for {Path(selected).name}.")


def cb_on_mx_enable_groom_change(kwargs: dict) -> None:
    """
    When ``mx_enable_groom`` toggles: clear groom parms if off; else resolve from current anim USD + shot.
    """
    node = kwargs.get("node")
    if hou is not None and (node is None or not isinstance(node, hou.Node)):
        return
    if node is None:
        return

    enabled = False
    try:
        p_en = node.parm(_MX_ENABLE_GROOM)
        if p_en is not None:
            enabled = int(p_en.eval()) != 0
    except Exception:
        enabled = False

    if not enabled:
        _clear_mx_groom_parms(node, clear_publish_parent=True)
        _status_set(node, "Groom disabled (mx_enable_groom=0). Cleared groom outputs.")
        return

    try:
        p_sel = node.parm(_MX_SELECTED_ANIM_USD_PATH)
        selected = p_sel.evalAsString().strip() if p_sel is not None else ""
    except Exception:
        selected = ""

    if not selected or not Path(selected).is_file():
        _status_set(node, "Groom enabled but selected anim USD is empty/missing on disk.")
        return

    try:
        p_pr = node.parm(_MX_PROJECT_ROOT)
        project_root = p_pr.evalAsString().strip() if p_pr is not None else ""
        p_sh = node.parm(_MX_SHOT)
        shot = p_sh.evalAsString().strip().lower() if p_sh is not None else ""
    except Exception:
        project_root, shot = "", ""

    if not project_root or not shot:
        _status_set(node, "Groom enabled but project_root or mx_shot is missing.")
        return

    _apply_mx_groom_resolve(
        node,
        project_root=project_root,
        shot=shot,
        geo_usd_path=selected,
        groom_version=None,
        groom_asset_token=None,
    )

    gp = ""
    try:
        p_gp = node.parm(_MX_SELECTED_GROOM_USD_PATH)
        gp = p_gp.evalAsString().strip() if p_gp is not None else ""
    except Exception:
        gp = ""

    if gp:
        _status_set(node, f"Groom resolved for {Path(selected).name}.")
    else:
        _status_set(node, f"Groom not found for {Path(selected).name}.")


def cb_on_mx_groom_version_change(kwargs: dict) -> None:
    """Re-resolve groom USD when ``mx_groom_version`` changes (keeps ``mx_groom_asset`` if parm exists)."""
    node = kwargs.get("node")
    if hou is not None and (node is None or not isinstance(node, hou.Node)):
        return
    if node is None:
        return

    try:
        p_gr = node.parm(_MX_ENABLE_GROOM)
        if p_gr is not None and int(p_gr.eval()) == 0:
            _clear_mx_groom_parms(node, clear_publish_parent=True)
            return
    except Exception:
        pass

    try:
        p_pr = node.parm(_MX_PROJECT_ROOT)
        project_root = p_pr.evalAsString().strip() if p_pr is not None else ""
        p_sh = node.parm(_MX_SHOT)
        shot = p_sh.evalAsString().strip().lower() if p_sh is not None else ""
        p_sel = node.parm(_MX_SELECTED_ANIM_USD_PATH)
        geo = p_sel.evalAsString().strip() if p_sel is not None else ""
        p_ver = node.parm(_MX_GROOM_VERSION)
        ver = p_ver.evalAsString().strip() if p_ver is not None else ""
        p_ast = node.parm(_MX_GROOM_ASSET)
    except Exception:
        return

    if not project_root or not shot:
        _clear_mx_groom_parms(node, clear_publish_parent=True)
        return

    ast: str | None
    if p_ast is None:
        ast = None
    else:
        ast = p_ast.evalAsString()

    _apply_mx_groom_resolve(
        node,
        project_root=project_root,
        shot=shot,
        geo_usd_path=geo,
        groom_version=ver or None,
        groom_asset_token=ast,
    )


def cb_on_mx_groom_asset_change(kwargs: dict) -> None:
    """Re-resolve groom USD when ``mx_groom_asset`` changes."""
    cb_on_mx_groom_version_change(kwargs)


def cb_on_mx_enable_cloth_change(kwargs: dict) -> None:
    """When ``mx_enable_cloth`` toggles: clear cloth parms if off; else resolve from current anim USD + shot."""
    node = kwargs.get("node")
    if hou is not None and (node is None or not isinstance(node, hou.Node)):
        return
    if node is None:
        return

    enabled = False
    try:
        p_en = node.parm(_MX_ENABLE_CLOTH)
        if p_en is not None:
            enabled = int(p_en.eval()) != 0
    except Exception:
        enabled = False

    if not enabled:
        _clear_mx_cloth_parms(node, clear_publish_parent=True)
        _status_set(node, "Cloth disabled (mx_enable_cloth=0). Cleared cloth outputs.")
        return

    try:
        p_sel = node.parm(_MX_SELECTED_ANIM_USD_PATH)
        selected = p_sel.evalAsString().strip() if p_sel is not None else ""
    except Exception:
        selected = ""

    if not selected or not Path(selected).is_file():
        _status_set(node, "Cloth enabled but selected anim USD is empty/missing on disk.")
        return

    try:
        p_pr = node.parm(_MX_PROJECT_ROOT)
        project_root = p_pr.evalAsString().strip() if p_pr is not None else ""
        p_sh = node.parm(_MX_SHOT)
        shot = p_sh.evalAsString().strip().lower() if p_sh is not None else ""
    except Exception:
        project_root, shot = "", ""

    if not project_root or not shot:
        _status_set(node, "Cloth enabled but project_root or mx_shot is missing.")
        return

    _apply_mx_cloth_resolve(
        node,
        project_root=project_root,
        shot=shot,
        geo_usd_path=selected,
        cloth_version=None,
        cloth_asset_token=None,
    )

    cp = ""
    try:
        p_cp = node.parm(_MX_SELECTED_CLOTH_USD_PATH)
        cp = p_cp.evalAsString().strip() if p_cp is not None else ""
    except Exception:
        cp = ""

    if cp:
        _status_set(node, f"Cloth resolved for {Path(selected).name}.")
    else:
        _status_set(node, f"Cloth not found for {Path(selected).name}.")


def cb_on_mx_cloth_version_change(kwargs: dict) -> None:
    """Re-resolve cloth USD when ``mx_cloth_version`` changes."""
    node = kwargs.get("node")
    if hou is not None and (node is None or not isinstance(node, hou.Node)):
        return
    if node is None:
        return

    try:
        p_cl = node.parm(_MX_ENABLE_CLOTH)
        if p_cl is not None and int(p_cl.eval()) == 0:
            _clear_mx_cloth_parms(node, clear_publish_parent=True)
            return
    except Exception:
        pass

    try:
        p_pr = node.parm(_MX_PROJECT_ROOT)
        project_root = p_pr.evalAsString().strip() if p_pr is not None else ""
        p_sh = node.parm(_MX_SHOT)
        shot = p_sh.evalAsString().strip().lower() if p_sh is not None else ""
        p_sel = node.parm(_MX_SELECTED_ANIM_USD_PATH)
        geo = p_sel.evalAsString().strip() if p_sel is not None else ""
        p_ver = node.parm(_MX_CLOTH_VERSION)
        ver = p_ver.evalAsString().strip() if p_ver is not None else ""
        p_ast = node.parm(_MX_CLOTH_ASSET)
    except Exception:
        return

    if not project_root or not shot:
        _clear_mx_cloth_parms(node, clear_publish_parent=True)
        return

    ast: str | None
    if p_ast is None:
        ast = None
    else:
        ast = p_ast.evalAsString()

    _apply_mx_cloth_resolve(
        node,
        project_root=project_root,
        shot=shot,
        geo_usd_path=geo,
        cloth_version=ver or None,
        cloth_asset_token=ast,
    )


def cb_on_mx_cloth_asset_change(kwargs: dict) -> None:
    """Re-resolve cloth USD when ``mx_cloth_asset`` changes."""
    cb_on_mx_cloth_version_change(kwargs)


def cb_on_mx_anim_publish_parent_change(kwargs: dict) -> None:
    """
    Callback when `mx_anim_publish_parent` changes:
    - clear selected USD + lookdev outputs
    - set mx_anim_version to latest v### under new parent (if available)
    - set mx_anim_usd to first USD in that version folder
    - then re-run `cb_on_mx_anim_usd_change` to resolve lookdev (if enabled)
    """
    node = kwargs.get("node")
    if hou is not None and (node is None or not isinstance(node, hou.Node)):
        return
    if node is None:
        return

    # Clear stale outputs first.
    _set_first_existing_parm(node, (_MX_SELECTED_ANIM_USD_PATH,), "")
    _set_first_existing_parm(node, (_MX_SELECTED_LOOKDEV_USD_PATH,), "")
    _set_first_existing_parm(node, (_MX_LOOKDEV_PUBLISH_PARENT,), "")
    _set_first_existing_parm(node, (_MX_LOOKDEV_VERSION,), "")
    _clear_mx_groom_parms(node, clear_publish_parent=True)
    _clear_mx_cloth_parms(node, clear_publish_parent=True)
    _set_first_existing_parm(node, ("mx_meta_summary", "mx_timeline_meta_summary", "mx_meta_text"), "")
    _set_first_existing_parm(node, ("mx_meta_fps", "mx_timeline_meta_fps"), "")
    _set_first_existing_parm(node, ("mx_meta_playback_range", "mx_timeline_meta_playback_range"), "")
    _set_first_existing_parm(node, ("mx_meta_raw_json", "mx_timeline_meta_raw_json"), "")
    _set_mx_geo_cam_parm(node, "")

    # Set latest anim version under new parent.
    try:
        p_parent = node.parm(_MX_ANIM_PUBLISH_PARENT)
        parent = p_parent.evalAsString().strip() if p_parent is not None else ""
    except Exception:
        parent = ""

    if parent and Path(parent).is_dir():
        vdirs = list_version_dirs(Path(parent))
        if vdirs:
            _set_first_existing_parm(node, (_MX_ANIM_VERSION,), vdirs[-1].name)

    # Auto-pick preferred USD from the new resolved version folder (geo first).
    first_token = _pick_first_anim_usd_token(node, prefer_geo=True)
    if first_token:
        p_usd = node.parm(_MX_ANIM_USD)
        if p_usd is not None:
            try:
                p_usd.set(first_token)
            except Exception:
                pass

        cb_on_mx_anim_usd_change({"node": node, "parm": node.parm(_MX_ANIM_USD)})
    else:
        _set_mx_geo_cam_parm(node, "")
        _status_set(node, "No USD found in selected anim version; outputs cleared.")


def cb_on_mx_anim_version_change(kwargs: dict) -> None:
    """
    Callback when `mx_anim_version` changes:
    - clear selected USD + lookdev outputs
    - set mx_anim_usd to first USD in that new version folder
    - then resolve lookdev (if enabled)
    """
    node = kwargs.get("node")
    if hou is not None and (node is None or not isinstance(node, hou.Node)):
        return
    if node is None:
        return

    # Clear stale outputs first.
    _set_first_existing_parm(node, (_MX_SELECTED_ANIM_USD_PATH,), "")
    _set_first_existing_parm(node, (_MX_SELECTED_LOOKDEV_USD_PATH,), "")
    _set_first_existing_parm(node, (_MX_LOOKDEV_PUBLISH_PARENT,), "")
    _set_first_existing_parm(node, (_MX_LOOKDEV_VERSION,), "")
    _clear_mx_groom_parms(node, clear_publish_parent=True)
    _clear_mx_cloth_parms(node, clear_publish_parent=True)
    _set_first_existing_parm(node, ("mx_meta_summary", "mx_timeline_meta_summary", "mx_meta_text"), "")
    _set_first_existing_parm(node, ("mx_meta_fps", "mx_timeline_meta_fps"), "")
    _set_first_existing_parm(node, ("mx_meta_playback_range", "mx_timeline_meta_playback_range"), "")
    _set_first_existing_parm(node, ("mx_meta_raw_json", "mx_timeline_meta_raw_json"), "")
    _set_mx_geo_cam_parm(node, "")

    # Auto-pick preferred USD from the resolved version folder (geo first).
    first_token = _pick_first_anim_usd_token(node, prefer_geo=True)
    if first_token:
        p_usd = node.parm(_MX_ANIM_USD)
        if p_usd is not None:
            try:
                p_usd.set(first_token)
            except Exception:
                pass

        cb_on_mx_anim_usd_change({"node": node, "parm": node.parm(_MX_ANIM_USD)})
    else:
        _set_mx_geo_cam_parm(node, "")
        _status_set(node, "No USD found in selected anim version; outputs cleared.")


def cb_on_mx_shot_change(kwargs: dict) -> None:
    """
    Callback when `mx_shot` changes.

    Expected behavior:
    - clear selected USD + lookdev outputs
    - set mx_anim_publish_parent from project_root + shot
    - set mx_anim_version to latest v### under that parent
    - set mx_anim_usd to preferred first USD (geo first)
    - trigger cb_on_mx_anim_usd_change to populate selected anim + lookdev
    """
    node = kwargs.get("node")
    if hou is not None and (node is None or not isinstance(node, hou.Node)):
        return
    if node is None:
        return

    # Clear stale outputs first.
    _set_first_existing_parm(node, (_MX_SELECTED_ANIM_USD_PATH,), "")
    _set_first_existing_parm(node, (_MX_SELECTED_LOOKDEV_USD_PATH,), "")
    _set_first_existing_parm(node, (_MX_LOOKDEV_PUBLISH_PARENT,), "")
    _set_first_existing_parm(node, (_MX_LOOKDEV_VERSION,), "")
    _clear_mx_groom_parms(node, clear_publish_parent=True)
    _clear_mx_cloth_parms(node, clear_publish_parent=True)
    _set_first_existing_parm(node, ("mx_meta_summary", "mx_timeline_meta_summary", "mx_meta_text"), "")
    _set_first_existing_parm(node, ("mx_meta_fps", "mx_timeline_meta_fps"), "")
    _set_first_existing_parm(node, ("mx_meta_playback_range", "mx_timeline_meta_playback_range"), "")
    _set_first_existing_parm(node, ("mx_meta_raw_json", "mx_timeline_meta_raw_json"), "")
    _set_mx_geo_cam_parm(node, "")

    # Read required inputs.
    shot = ""
    project_root = ""
    try:
        p_shot = node.parm(_MX_SHOT)
        shot = p_shot.evalAsString().strip() if p_shot is not None else ""
    except Exception:
        shot = ""

    try:
        p_pr = node.parm(_MX_PROJECT_ROOT)
        project_root = p_pr.evalAsString().strip() if p_pr is not None else ""
    except Exception:
        project_root = ""

    if not project_root:
        # Fallback: infer from hip if possible.
        try:
            from apps.houdini import adapter as houdini_adapter

            hip_path = houdini_adapter.get_hip_path() or ""
            if hip_path:
                pr = find_project_root(Path(hip_path))
                project_root = str(pr) if pr else ""
        except Exception:
            project_root = ""

    if not project_root or not shot:
        _status_set(node, "Shot changed but project_root/shot missing; outputs cleared.")
        return

    anim_parent = str(get_anim_publish_dir(Path(project_root), shot.lower()))
    _set_first_existing_parm(node, (_MX_ANIM_PUBLISH_PARENT,), anim_parent)
    _set_first_existing_parm(
        node,
        (_MX_GROOM_PUBLISH_PARENT,),
        str(get_groom_publish_dir(Path(project_root), shot.lower())),
    )
    _set_first_existing_parm(
        node,
        (_MX_CLOTH_PUBLISH_PARENT,),
        str(get_cloth_publish_dir(Path(project_root), shot.lower())),
    )

    vdirs = list_version_dirs(Path(anim_parent))
    anim_latest = vdirs[-1].name if vdirs else ""
    _set_first_existing_parm(node, (_MX_ANIM_VERSION,), anim_latest)

    # Set preferred USD token for this version.
    first_token = _pick_first_anim_usd_token(node, prefer_geo=True)
    p_usd = node.parm(_MX_ANIM_USD)
    if p_usd is not None and first_token:
        try:
            p_usd.set(first_token)
        except Exception:
            pass
        cb_on_mx_anim_usd_change({"node": node, "parm": node.parm(_MX_ANIM_USD)})
    else:
        _set_mx_geo_cam_parm(node, "")
        _status_set(node, "Shot changed but no USD found in the resolved anim version.")


def menu_anim_version_list(node: Any) -> list[str]:
    """
    Menu versions under `anim_publish_parent` (if valid), otherwise infer from hip.
    Menu format: [token1, label1, token2, label2, ...]
    """
    if hou is not None and (node is None or not isinstance(node, hou.Node)):
        return ["", "Not in Houdini node"]
    if node is None:
        return ["", "Invalid node"]

    publish_parent = ""
    try:
        p_parent = node.parm("anim_publish_parent")
        if p_parent is not None:
            publish_parent = p_parent.evalAsString().strip()
    except Exception:
        publish_parent = ""

    if not publish_parent or not Path(publish_parent).is_dir():
        parent, _, _ = _infer_publish_parent_and_latest_from_current_hip(node)
        publish_parent = parent

    if not publish_parent or not Path(publish_parent).is_dir():
        return ["", "Invalid anim_publish_parent"]

    vdirs = list_version_dirs(Path(publish_parent))
    if not vdirs:
        return ["", "No v### folders"]

    menu: list[str] = []
    for vd in vdirs:
        menu.extend([vd.name, vd.name])
    return menu


def _menu_usd_list_by_suffix_and_prefix(node: Any, *, prefix: str | None) -> list[str]:
    """
    Menu token = abs USD path, label = basename.
    If prefix is provided, filter basename startswith it (case-insensitive).
    """
    version_folder = _resolve_version_folder_from_node(node)
    if not version_folder:
        return ["", "Invalid publish folder"]

    usd_files = find_usd_files(Path(version_folder))
    if not usd_files:
        return ["", "No USD Files"]

    plow = prefix.lower() if prefix else None
    filtered: list[Path] = []
    for p in usd_files:
        name = p.name
        if plow is None:
            filtered.append(p)
        else:
            if name.lower().startswith(plow):
                filtered.append(p)

    if not filtered:
        return ["", f"No USD Files ({prefix})"] if prefix else ["", "No USD Files"]

    menu: list[str] = []
    for p in filtered:
        menu.extend([str(p), p.name])
    return menu


def menu_anim_usd_list(node: Any) -> list[str]:
    """Menu token = selected USD absolute path (any USD under the active version)."""
    return _menu_usd_list_by_suffix_and_prefix(node, prefix=None)


def menu_anim_geo_usd_list(node: Any) -> list[str]:
    """Menu token = selected geo USD absolute path (filtered from publish)."""
    return _menu_usd_list_by_suffix_and_prefix(node, prefix="geo_")


def menu_anim_cam_usd_list(node: Any) -> list[str]:
    """Menu token = selected cam USD absolute path (filtered from publish)."""
    return _menu_usd_list_by_suffix_and_prefix(node, prefix="cam_")


def cb_on_geo_usd_change(kwargs: dict) -> None:
    """Set anim USD string parms when selected geo USD changes (compute-only)."""
    node = kwargs.get("node")
    if hou is not None and (node is None or not isinstance(node, hou.Node)):
        return
    if node is None:
        return

    selected = _get_callback_string_value(kwargs)
    if not selected or not Path(selected).is_file():
        _set_first_existing_parm(node, ("geo_anim_sublayer_path", "anim_sublayer_path", "selected_anim_usd_path"), "")
        _status_set(node, "Geo USD selection is empty or missing on disk.")
        return

    selected = str(Path(selected))
    _set_first_existing_parm(
        node,
        ("geo_anim_sublayer_path", "anim_sublayer_path", "selected_anim_usd_path"),
        selected,
    )
    _status_set(node, f"Geo USD selected: {Path(selected).name}")


def cb_on_cam_usd_change(kwargs: dict) -> None:
    """Set anim USD string parms when selected cam USD changes (compute-only)."""
    node = kwargs.get("node")
    if hou is not None and (node is None or not isinstance(node, hou.Node)):
        return
    if node is None:
        return

    selected = _get_callback_string_value(kwargs)
    if not selected or not Path(selected).is_file():
        _set_first_existing_parm(node, ("cam_anim_sublayer_path", "anim_sublayer_path", "selected_anim_usd_path"), "")
        _status_set(node, "Cam USD selection is empty or missing on disk.")
        return

    selected = str(Path(selected))
    _set_first_existing_parm(
        node,
        ("cam_anim_sublayer_path", "anim_sublayer_path", "selected_anim_usd_path"),
        selected,
    )
    _status_set(node, f"Cam USD selected: {Path(selected).name}")


def cb_apply_mx_timeline(kwargs: dict) -> None:
    """
    Button callback:
    - read `<anim version folder>/publish_meta.json`
    - apply `fps` + `playback_range` to Houdini timeline

    Respects optional bool parm `mx_apply_timeline` if it exists.
    """
    node = kwargs.get("node")
    if hou is None or node is None or not isinstance(node, hou.Node):
        return

    # Optional gate parm.
    try:
        p_apply = node.parm("mx_apply_timeline")
        if p_apply is not None and int(p_apply.eval()) == 0:
            _status_set(node, "Timeline apply skipped (mx_apply_timeline=0).")
            return
    except Exception:
        pass

    folder = _mx_anim_version_folder(node)
    if not folder:
        _set_first_existing_parm(node, ("mx_meta_summary", "mx_timeline_meta_summary", "mx_meta_text"), "")
        _set_first_existing_parm(node, ("mx_meta_fps", "mx_timeline_meta_fps"), "")
        _set_first_existing_parm(node, ("mx_meta_playback_range", "mx_timeline_meta_playback_range"), "")
        _set_first_existing_parm(node, ("mx_meta_raw_json", "mx_timeline_meta_raw_json"), "")
        _status_set(node, "Cannot apply timeline: invalid anim version folder.")
        return

    meta_path = Path(folder) / _META_NAME
    if not meta_path.is_file():
        _set_first_existing_parm(node, ("mx_meta_summary", "mx_timeline_meta_summary", "mx_meta_text"), "")
        _set_first_existing_parm(node, ("mx_meta_fps", "mx_timeline_meta_fps"), "")
        _set_first_existing_parm(node, ("mx_meta_playback_range", "mx_timeline_meta_playback_range"), "")
        _set_first_existing_parm(node, ("mx_meta_raw_json", "mx_timeline_meta_raw_json"), "")
        _status_set(node, f"{_META_NAME} missing in {folder}.")
        return

    # Also fill metadata string parms for consistency.
    meta = _load_mx_timeline_meta_from_folder(folder)
    if meta is None:
        _set_first_existing_parm(node, ("mx_meta_summary", "mx_timeline_meta_summary", "mx_meta_text"), "")
        _set_first_existing_parm(node, ("mx_meta_fps", "mx_timeline_meta_fps"), "")
        _set_first_existing_parm(node, ("mx_meta_playback_range", "mx_timeline_meta_playback_range"), "")
        _set_first_existing_parm(node, ("mx_meta_raw_json", "mx_timeline_meta_raw_json"), "")
        _status_set(node, f"Invalid or missing {_META_NAME} in {folder}.")
        return

    # Apply FPS
    fps = meta.get("fps")
    if fps is not None:
        try:
            hou.setFps(float(fps))
        except Exception:
            pass

    # Apply playback range: expected [start, end]
    pr = meta.get("playback_range")
    if isinstance(pr, (list, tuple)) and len(pr) >= 2:
        try:
            a, b = int(pr[0]), int(pr[1])
            hou.playbar.setPlaybackRange(a, b)
            hou.playbar.setFrameRange(a, b)
        except Exception:
            pass

    _status_set(node, "Timeline applied from publish_meta.json.")


def _load_mx_timeline_meta_from_folder(anim_version_folder: str) -> dict[str, Any] | None:
    """Load publish_meta.json from a resolved anim version folder."""
    folder = anim_version_folder
    if not folder:
        return None
    meta_path = Path(folder) / _META_NAME
    if not meta_path.is_file():
        return None
    try:
        import json

        with open(meta_path, "r", encoding="utf-8") as f:
            meta = json.load(f)
    except Exception:
        return None
    return meta if isinstance(meta, dict) else None


def _maybe_update_mx_timeline_meta_from_current_anim(node: Any) -> None:
    """
    If publish_meta.json exists for current anim version folder, write metadata
    into string parms immediately.
    """
    if node is None or hou is None or not isinstance(node, hou.Node):
        # Still allow compute-only usage, but only write when in Houdini.
        return

    folder = _mx_anim_version_folder(node)
    meta = _load_mx_timeline_meta_from_folder(folder) if folder else None
    if meta is None:
        # Clear metadata fields if any exist.
        _set_first_existing_parm(node, ("mx_meta_summary", "mx_timeline_meta_summary", "mx_meta_text"), "")
        _set_first_existing_parm(node, ("mx_meta_fps", "mx_timeline_meta_fps"), "")
        _set_first_existing_parm(node, ("mx_meta_playback_range", "mx_timeline_meta_playback_range"), "")
        _set_first_existing_parm(node, ("mx_meta_raw_json", "mx_timeline_meta_raw_json"), "")
        return

    fps_val = meta.get("fps")
    pr_val = meta.get("playback_range")

    # Summary string (short) without "publish_meta.json" prefix.
    # Example: "fps=24 playback_range=[1,120]"
    parts: list[str] = []
    if fps_val is not None:
        parts.append(f"fps={fps_val}")
    if isinstance(pr_val, (list, tuple)) and len(pr_val) >= 2:
        parts.append(f"playback_range=[{pr_val[0]},{pr_val[1]}]")
    summary = " ".join(parts)

    raw_json = None
    try:
        import json

        raw_json = json.dumps(meta, ensure_ascii=False, indent=2)
    except Exception:
        raw_json = None

    _set_first_existing_parm(
        node,
        ("mx_meta_summary", "mx_timeline_meta_summary", "mx_meta_text"),
        summary,
    )
    _set_first_existing_parm(
        node,
        ("mx_meta_fps", "mx_timeline_meta_fps"),
        str(fps_val) if fps_val is not None else "",
    )
    if isinstance(pr_val, (list, tuple)) and len(pr_val) >= 2:
        _set_first_existing_parm(
            node,
            ("mx_meta_playback_range", "mx_timeline_meta_playback_range"),
            f"{pr_val[0]},{pr_val[1]}",
        )
    else:
        _set_first_existing_parm(
            node,
            ("mx_meta_playback_range", "mx_timeline_meta_playback_range"),
            "",
        )

    if raw_json is not None:
        _set_first_existing_parm(
            node,
            ("mx_meta_raw_json", "mx_timeline_meta_raw_json"),
            raw_json,
        )


def cb_mx_create_hdas_from_anim_version(kwargs: dict) -> None:
    """
    Button callback:
    - Scan all USD files under the active anim version folder:
      `<mx_anim_publish_parent>/<mx_anim_version>`
    - Create 1 instance of *this same HDA type* per USD found
    - Set parms on each instance (mx_anim_usd, mx_anim_publish_parent, mx_anim_version, ...)
    - Call `cb_on_mx_anim_usd_change` to populate selected anim + lookdev outputs

    Notes:
    - Nodes are created as siblings under `node.parent()`.
    - If your subnet/container disallows editing, node creation will raise hou.OperationFailed.
    """
    node = kwargs.get("node")
    if hou is None or not isinstance(node, hou.Node):
        return

    # Resolve target anim version folder.
    folder = _mx_anim_version_folder(node)
    if not folder:
        _status_set(node, "Cannot create instances: invalid anim version folder.")
        return

    usd_files = find_usd_files(Path(folder))
    if not usd_files:
        _status_set(node, f"Cannot create instances: no USD files found in {folder}.")
        return

    parent_net = node.parent()
    if parent_net is None:
        _status_set(node, "Cannot create instances: node has no parent network.")
        return

    def _safe_node_name(s: str) -> str:
        s2 = re.sub(r"[^0-9A-Za-z_]+", "_", s)
        # Avoid very long names.
        return s2[:60].strip("_") or "instance"

    def _set_parm_if_exists(src_node: Any, dst_node: Any, parm_name: str) -> None:
        p_src = src_node.parm(parm_name) if src_node is not None else None
        if p_src is None:
            return
        p_dst = dst_node.parm(parm_name)
        if p_dst is None:
            return
        try:
            p_dst.set(p_src.evalAsString())
        except Exception:
            try:
                p_dst.set(p_src.eval())
            except Exception:
                pass

    hda_type_name = node.type().name()
    created = 0
    for idx, p in enumerate(usd_files):
        token = str(p)
        # Prefer filename-based name:
        # - geo_char_Zephys.usd / cam_char_Zephys.usd -> "char_Zephys"
        asset_type, asset_name = _parse_asset_from_geo_filename(str(p))
        if asset_type and asset_name:
            desired = f"{asset_type}_{asset_name}"
        else:
            desired = p.stem

        candidate = _safe_node_name(desired)
        try:
            if parent_net.node(candidate) is not None:
                candidate = _safe_node_name(f"{candidate}_{idx}")
        except Exception:
            # If node() lookup fails for some reason, fallback to unique-ish name.
            candidate = _safe_node_name(f"{candidate}_{idx}")

        child_name = candidate

        try:
            child = parent_net.createNode(hda_type_name, node_name=child_name)
        except hou.OperationFailed as e:
            _status_set(node, f"Create node failed: {e}")
            continue

        # Copy relevant parms from the source node.
        for parm_name in (
            _MX_PROJECT_ROOT,
            _MX_SHOT,
            _MX_ANIM_PUBLISH_PARENT,
            _MX_ANIM_VERSION,
            _MX_ENABLE_LOOKDEV,
            _MX_ENABLE_GROOM,
            _MX_ENABLE_CLOTH,
        ):
            _set_parm_if_exists(node, child, parm_name)

        # Set USD token for this instance.
        p_usd = child.parm(_MX_ANIM_USD)
        if p_usd is not None:
            try:
                p_usd.set(token)
            except Exception:
                pass

        # Ensure resolver runs so outputs are populated.
        try:
            cb_on_mx_anim_usd_change({"node": child, "parm": child.parm(_MX_ANIM_USD)})
        except Exception:
            pass

        try:
            child.moveToGoodPosition()
        except Exception:
            pass

        created += 1

    _status_set(node, f"Created {created} HDA instance(s) from {Path(folder).name}.")

