"""Mono Anim Loader 2.2 decisions, without hou: which instance an anim output is, where its publishes are."""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from pathlib import Path

from tools.fx.anim_loader import config


@dataclass(frozen=True)
class Output:
    """One file of an anim publish version, as publish_meta.json (or the file name) gives it."""

    file: str
    kind: str  # "geo" | "cam"
    asset: str | None = None
    instance: int | None = None


@dataclass(frozen=True)
class Instance:
    """One appearance of an asset in a shot (or the camera). ``asset`` None means "asset?"."""

    name: str  # graft prim name: char_Robot_inst02
    anim_file: str
    kind: str
    asset: str | None
    instance: int
    guessed: bool
    candidates: tuple[str, ...] = ()


def instance_name(anim_file: str) -> str:
    """``geo_char_Helen_inst02.usd`` -> ``char_Helen_inst02``; ``cam_sh010.usd`` -> ``sh010``."""
    stem = Path(anim_file).stem
    for prefix in config.ANIM_PREFIXES:
        if stem.lower().startswith(prefix):
            return stem[len(prefix):]
    return stem


def resolve_instance(output: Output, asset_names: set[str]) -> Instance:
    """Which asset and which appearance an output is (spec section 3: meta, _instNN, exact name, old _N)."""
    name = instance_name(output.file)
    if output.kind == "cam":
        return Instance(name, output.file, "cam", None, 1, False)
    if output.asset:
        return Instance(name, output.file, "geo", output.asset, output.instance or 1, False)

    m = re.search(config.CLONE_RE, name)
    if m and name[: m.start()] in asset_names:
        return Instance(name, output.file, "geo", name[: m.start()], int(m.group(1)), True)

    exact = name if name in asset_names else None
    m = re.search(config.OLD_CLONE_RE, name)
    stripped = name[: m.start()] if m and name[: m.start()] in asset_names else None
    if exact and stripped:
        return Instance(name, output.file, "geo", None, 1, True, tuple(sorted({exact, stripped})))
    if exact:
        return Instance(name, output.file, "geo", exact, 1, True)
    if stripped:
        return Instance(name, output.file, "geo", stripped, int(m.group(1)), True)
    return Instance(name, output.file, "geo", None, 1, True)


# --- publishes on disk -------------------------------------------------------------------------

_SHOT_RE = re.compile(r"^(sh\d{3,}[a-z0-9]*)$", re.IGNORECASE)
_SHOT_ANYWHERE_RE = re.compile(r"(sh\d{3,}[a-z0-9]*)", re.IGNORECASE)
_VERSION_RE = re.compile(r"^v(\d+)$", re.IGNORECASE)
META_NAME = "publish_meta.json"


@dataclass(frozen=True)
class FxMatch:
    """A groom / cloth sequence of one instance; ``folder`` None when none is found (``reason`` says why)."""

    folder: Path | None
    pattern: str = ""  # .../sh010_groom.$F4.usd
    first: int | None = None
    last: int | None = None
    missing: tuple[int, ...] = ()
    reason: str = ""


def find_project_root(path: Path) -> Path | None:
    """The first folder upwards that holds both ``01_assets`` and ``02_shots`` (same as 2.1)."""
    start = path if path.is_dir() else path.parent
    for p in (start, *start.parents):
        try:
            if (p / "01_assets").is_dir() and (p / "02_shots").is_dir():
                return p
        except OSError:
            continue
    return None


def detect_shot(path: Path) -> str | None:
    """A shot token (``sh002``, ``sh003a``) from the path's folders, lower case (same as 2.1)."""
    for part in [path.name] + [p.name for p in path.parents]:
        m = _SHOT_RE.match(part)
        if m:
            return m.group(1).lower()
    m = _SHOT_ANYWHERE_RE.search(str(path))
    return m.group(1).lower() if m else None


def _subdirs(folder: Path) -> list[Path]:
    try:
        return [d for d in folder.iterdir() if d.is_dir()]
    except OSError:
        return []


def list_shots(project_root: Path) -> list[str]:
    """Shots of a project with an anim publish folder (``02_shots/<shot>/01_anim/publish``), by name."""
    return sorted((d.name for d in _subdirs(project_root / "02_shots") if (d / "01_anim" / "publish").is_dir()),
                  key=str.lower)


RECENT_PROJECTS = 8


def remember_project(recent: list[str], root: str) -> list[str]:
    """``root`` first in the recent projects list (paths compared case- and slash-blind), at most 8."""
    def key(p: str) -> str:
        return p.replace("\\", "/").rstrip("/").lower()

    if not root:
        return list(recent)
    return [root, *[p for p in recent if key(p) != key(root)]][:RECENT_PROJECTS]


def list_asset_dirs(project_root: Path) -> dict[str, Path]:
    """Every asset folder: ``01_assets/_<group>/<asset>``."""
    out: dict[str, Path] = {}
    for group in _subdirs(project_root / "01_assets"):
        if group.name.startswith("_"):
            for asset in _subdirs(group):
                out[asset.name] = asset
    return out


def asset_groups(project_root: Path) -> list[str]:
    """The asset group folders of a project (``_characters``, ``_props``...), by name."""
    return sorted((g.name for g in _subdirs(project_root / "01_assets") if g.name.startswith("_")), key=str.lower)


def group_label(group: str) -> str:
    return group.lstrip("_").replace("_", " ").title() or group


def asset_menu(project_root: str, group: str, current: str, with_model: bool) -> list[tuple[str, str]]:
    """(asset, label) of one group ("" = every group); ``with_model``: only assets with a UV publish (Source
    Asset). The current asset stays listed. Long lists were the user's complaint, 2026-11-17."""
    root = Path(project_root) if project_root else None
    if root is None:
        return []
    out = []
    for name, folder in sorted(list_asset_dirs(root).items(), key=lambda kv: kv[0].lower()):
        if group and folder.parent.name != group:
            continue
        if with_model and not (list_versions(model_publish_dir(folder))
                               or list_versions(folder / "05_lookdev" / "publish")):
            continue
        out.append((name, name))
    if current and all(a != current for a, _ in out):
        out.insert(0, (current, current))
    return out


def asset_group_of(project_root: str, asset: str | None) -> str:
    folder = list_asset_dirs(Path(project_root)).get(asset or "") if project_root else None
    return folder.parent.name if folder is not None else ""


def list_versions(publish_dir: Path) -> list[str]:
    """Version folders (``v001``, ``V002``) as named on disk, by number; other folders are left out."""
    named = [(int(m.group(1)), d.name) for d in _subdirs(publish_dir) if (m := _VERSION_RE.match(d.name))]
    return [name for _, name in sorted(named)]


def anim_publish_dir(project_root: Path, shot: str) -> Path:
    return project_root / "02_shots" / shot / "01_anim" / "publish"


def _read_meta(version_dir: Path) -> dict | None:
    import json

    try:
        data = json.loads((version_dir / META_NAME).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def read_outputs(version_dir: Path) -> list[Output]:
    """The anim outputs of a version: publish_meta.json ``outputs`` first, else ``geo_*`` / ``cam_*`` files."""
    meta = _read_meta(version_dir)
    if meta and isinstance(meta.get("outputs"), list):
        outs = []
        for o in meta["outputs"]:
            if isinstance(o, dict) and o.get("file") and o.get("type") in ("geo", "cam"):
                inst = o.get("instance")
                outs.append(Output(str(o["file"]), o["type"], o.get("asset") or None,
                                   int(inst) if isinstance(inst, int) else None))
        return outs
    outs = []
    try:
        files = sorted(f for f in version_dir.iterdir() if f.is_file())
    except OSError:
        return []
    for f in files:
        if f.suffix.lower() not in config.USD_EXTS:
            continue
        for prefix, kind in config.ANIM_PREFIXES.items():
            if f.name.lower().startswith(prefix):
                outs.append(Output(f.name, kind))
    return sorted(outs, key=lambda o: (o.kind != "geo", o.file.lower()))


def read_timeline(version_dir: Path) -> tuple[float, int, int] | None:
    """(fps, first frame, last frame) from publish_meta.json."""
    meta = _read_meta(version_dir)
    try:
        pr = meta["playback_range"]  # type: ignore[index]
        return float(meta["fps"]), int(pr[0]), int(pr[1])  # type: ignore[index]
    except (TypeError, KeyError, ValueError, IndexError):
        return None


def lookdev_file(asset_dir: Path, version: str) -> Path | None:
    """``<asset>/05_lookdev/publish/<version>/<asset>_lookdev_publish.usd*``."""
    folder = asset_dir / "05_lookdev" / "publish" / version
    for ext in config.USD_EXTS:
        p = folder / f"{asset_dir.name}_lookdev_publish{ext}"
        if p.is_file():
            return p
    return None


def model_publish_dir(asset_dir: Path) -> Path:
    return asset_dir / "01_modelling" / "03_uv" / "publish"


def groom_publish_dir(asset_dir: Path) -> Path:
    return asset_dir / "04_grooming" / "publish"


def usd_files(folder: Path) -> list[str]:
    """USD files directly in a folder (no sub folders), by name."""
    try:
        return sorted((f.name for f in folder.iterdir() if f.is_file() and f.suffix.lower() in config.USD_EXTS),
                      key=str.lower)
    except OSError:
        return []


def standard_file(files: list[str], asset: str, kind: str) -> str:
    """``<asset>_<kind>_publish.usd*`` among ``files`` (kind ``uv`` or ``groom``), "" when none."""
    stem = f"{asset}_{kind}_publish".lower()
    return next((f for f in files if f.rsplit(".", 1)[0].lower() == stem), "")


def pick_file(files: list[str], asset: str, kind: str, current: str = "") -> str:
    """The file a version gives: the one already picked if this version has it, else the standard name, else the
    only file; "" when several files and none is standard (the artist picks; the user's rule, 2026-11-17)."""
    if current and current in files:
        return current
    return standard_file(files, asset, kind) or (files[0] if len(files) == 1 else "")


def detect_asset(project_root: Path, path: Path) -> str | None:
    """The asset whose folder holds ``path`` (``01_assets/_<group>/<asset>/...``), else None."""
    try:
        rel = path.resolve().relative_to((project_root / "01_assets").resolve())
    except (ValueError, OSError):
        return None
    parts = rel.parts
    if len(parts) >= 2 and parts[0].startswith("_") and (project_root / "01_assets" / parts[0] / parts[1]).is_dir():
        return parts[1]
    return None


def fx_publish_dir(project_root: Path, shot: str, task: str) -> Path:
    return project_root / "02_shots" / shot / "02_fx" / task / "publish"


def _sequence(folder: Path, shot: str, task: str) -> FxMatch | None:
    rx = re.compile(rf"^({re.escape(shot)}_{re.escape(task)})\.(\d+)(\.usd[ac]?)$", re.IGNORECASE)
    hits = []
    try:
        for f in folder.iterdir():
            m = rx.match(f.name)
            if m and f.is_file():
                hits.append((int(m.group(2)), m))
    except OSError:
        return None
    if not hits:
        return None
    hits.sort(key=lambda h: h[0])
    first_m = hits[0][1]
    numbers = [n for n, _ in hits]
    missing = tuple(sorted(set(range(numbers[0], numbers[-1] + 1)) - set(numbers)))
    pattern = (folder / f"{first_m.group(1)}.$F{len(first_m.group(2))}{first_m.group(3)}").as_posix()
    return FxMatch(folder, pattern, numbers[0], numbers[-1], missing)


def fx_match(root: Path, shot: str, task: str, version: str, inst: Instance, geo_count: int) -> FxMatch:
    """The groom / cloth sequence of exactly this instance; never another instance's folder."""
    if inst.asset is None:
        return FxMatch(None, reason=f"{task}: asset? for {inst.name}")
    ver_dir = fx_publish_dir(root, shot, task) / version
    names = [inst.name]
    kind, _, rest = inst.name.partition("_")
    if kind in config.ASSET_TYPES and rest:
        names.append(rest)
    for name in names:
        found = _sequence(ver_dir / name, shot, task)
        if found:
            return found
    if geo_count == 1:
        found = _sequence(ver_dir, shot, task)
        if found:
            return found
    return FxMatch(None, reason=f"No {task} for {inst.name} in {version}")


# --- loader state ----------------------------------------------------------------------------

STATUS_OK, STATUS_NEWER, STATUS_MISSING, STATUS_OFF, STATUS_ASSET = "ok", "newer", "missing", "off", "asset?"
STATUS_NONE = "none"  # nothing of this part was ever published for the instance (not an error)
PARTS = ("lookdev", "groom", "cloth")
FX_TASKS = ("groom", "cloth")


@dataclass(frozen=True)
class LoaderState:
    """What one loader node holds (its parms). Versions are explicit ``vNNN``; "" = none found."""

    project_root: str
    shot: str
    anim_version: str
    anim_file: str
    asset: str | None
    instance_name: str
    kind: str
    enabled: dict[str, bool]
    versions: dict[str, str]
    source: str = config.SOURCE_SHOT  # SOURCE_ASSET: the asset's model, groom and lookdev, no shot
    model_version: str = ""
    model_file: str = ""


def is_asset(state: LoaderState) -> bool:
    return state.source == config.SOURCE_ASSET


@dataclass(frozen=True)
class Resolved:
    """Paths a state points at ("" when absent); groom / cloth carry ``$F<pad>``."""

    anim: str
    lookdev: str
    groom: str
    cloth: str
    frames: dict[str, tuple[int, int]]
    notes: tuple[str, ...]


def _vnum(name: str) -> int:
    m = _VERSION_RE.match(name or "")
    return int(m.group(1)) if m else -1


def _instance(state: LoaderState) -> Instance:
    return Instance(state.instance_name, state.anim_file, state.kind, state.asset, 1, False)


def _geo_count(root: Path, state: LoaderState) -> int:
    if is_asset(state):
        return 1
    outs = read_outputs(anim_publish_dir(root, state.shot) / state.anim_version)
    return sum(1 for o in outs if o.kind == "geo")


def _part_path(root: Path, state: LoaderState, part: str, version: str, geo_count: int) -> tuple[str, FxMatch | None]:
    if is_asset(state) and part == "groom":  # the asset's groom publish: one file, already at /Groom
        asset_dir = list_asset_dirs(root).get(state.asset or "")
        if not (asset_dir and version):
            return "", None
        folder = groom_publish_dir(asset_dir) / version
        name = pick_file(usd_files(folder), asset_dir.name, "groom")
        return ((folder / name).as_posix() if name else ""), None
    if part == "lookdev":
        asset_dir = list_asset_dirs(root).get(state.asset or "")
        p = lookdev_file(asset_dir, version) if asset_dir and version else None
        return (p.as_posix() if p else ""), None
    m = fx_match(root, state.shot, part, version, _instance(state), geo_count) if version else None
    return (m.pattern if m and m.folder else ""), m


def _part_versions(root: Path, state: LoaderState, part: str) -> list[str]:
    if part == "lookdev":
        asset_dir = list_asset_dirs(root).get(state.asset or "")
        return list_versions(asset_dir / "05_lookdev" / "publish") if asset_dir else []
    if is_asset(state):
        asset_dir = list_asset_dirs(root).get(state.asset or "")
        return list_versions(groom_publish_dir(asset_dir)) if asset_dir and part == "groom" else []
    return list_versions(fx_publish_dir(root, state.shot, part))


def _found_versions(root: Path, state: LoaderState, part: str, geo_count: int) -> list[str]:
    """Versions of a part that hold this instance's file, oldest first."""
    return [v for v in _part_versions(root, state, part) if _part_path(root, state, part, v, geo_count)[0]]


def _asset_dir(root: Path, state: LoaderState) -> Path | None:
    return list_asset_dirs(root).get(state.asset or "") if state.project_root else None


def _anim_versions(root: Path, state: LoaderState) -> list[str]:
    """Versions of the anim file (Source Asset: of the model file; any model when none is picked yet)."""
    if is_asset(state):
        asset_dir = _asset_dir(root, state)
        if asset_dir is None:
            return []
        pub = model_publish_dir(asset_dir)
        if state.model_file:
            return [v for v in list_versions(pub) if (pub / v / state.model_file).is_file()]
        return [v for v in list_versions(pub) if pick_file(usd_files(pub / v), asset_dir.name, "uv")]
    pub = anim_publish_dir(root, state.shot)
    return [v for v in list_versions(pub) if (pub / v / state.anim_file).is_file()]


def _applies(state: LoaderState, part: str) -> bool:
    if is_asset(state) and part == "cloth":  # cloth is a shot cache only
        return False
    return state.kind == "geo" and state.enabled.get(part, True)


def main_version(state: LoaderState) -> str:
    """The anim version, or the model version for Source Asset."""
    return state.model_version if is_asset(state) else state.anim_version


def main_path(root: Path, state: LoaderState) -> Path:
    if is_asset(state):
        asset_dir = _asset_dir(root, state) or root / "01_assets" / "_" / (state.asset or "_")
        return model_publish_dir(asset_dir) / state.model_version / state.model_file
    return anim_publish_dir(root, state.shot) / state.anim_version / state.anim_file


def resolve(state: LoaderState) -> Resolved:
    """The files a state points at. Reads the disk only; the same state always gives the same paths."""
    root = Path(state.project_root)
    anim_p = main_path(root, state)
    paths = {"anim": anim_p.as_posix() if anim_p.is_file() else ""}
    frames: dict[str, tuple[int, int]] = {}
    word = "Model" if is_asset(state) else "Anim"
    notes: list[str] = [] if paths["anim"] else [f"{word} file missing: {anim_p}"]
    geo_count = _geo_count(root, state)
    for part in PARTS:
        paths[part] = ""
        if not _applies(state, part) or state.asset is None:
            continue
        path, m = _part_path(root, state, part, state.versions.get(part, ""), geo_count)
        paths[part] = path
        if m is not None and m.folder is not None:
            frames[part] = (m.first, m.last)  # type: ignore[assignment]
            if m.missing:
                notes.append(f"{part} {state.versions[part]}: missing frames {list(m.missing)}")
        elif m is not None:
            notes.append(m.reason)
    return Resolved(paths["anim"], paths["lookdev"], paths["groom"], paths["cloth"], frames, tuple(notes))


PART_FOLDER_WORDS = {"anim": "Anim", "lookdev": "Lookdev", "groom": "Groom", "cloth": "Cloth"}


def part_word(state: LoaderState, part: str) -> str:
    """What a part's folder is called on a menu or button: the main part is the model for Source Asset."""
    return ("Model" if is_asset(state) else "Anim") if part == "anim" else PART_FOLDER_WORDS.get(part, part.title())


def _nearest(folder: Path, stop: Path) -> Path | None:
    """``folder``, else the closest folder above it that is on disk, never above ``stop`` (a version gone: its
    publish folder)."""
    try:
        folder.relative_to(stop)
    except ValueError:
        return folder if folder.is_dir() else None
    while not folder.is_dir():
        if folder == stop or folder.parent == folder:
            return None
        folder = folder.parent
    return folder


def part_folders(state: LoaderState) -> dict[str, str]:
    """Each part's publish folder on disk, in column order (anim / model, lookdev, groom, cloth): the folder of the
    version on the node (a groom / cloth cache: the instance's own folder in it); a version missing on disk gives
    its part's publish folder. Parts that do not apply (a camera's lookdev, cloth on Source Asset) are left out."""
    if not state.project_root:
        return {}
    root = Path(state.project_root)
    r = resolve(state)
    asset_dir = _asset_dir(root, state)
    out: dict[str, str] = {}
    main = Path(r.anim).parent if r.anim else main_path(root, state).parent
    publish = (model_publish_dir(asset_dir) if asset_dir else None) if is_asset(state) \
        else anim_publish_dir(root, state.shot)
    if publish is not None:
        found = _nearest(main, publish)
        if found is not None:
            out["anim"] = found.as_posix()
    if state.kind != "geo" or state.asset is None:
        return out
    for part in PARTS:
        if part == "cloth" and is_asset(state):
            continue
        version = state.versions.get(part, "")
        path = getattr(r, part)
        if part == "lookdev" or (part == "groom" and is_asset(state)):
            if asset_dir is None:
                continue
            publish = asset_dir / "05_lookdev" / "publish" if part == "lookdev" else groom_publish_dir(asset_dir)
        else:
            publish = fx_publish_dir(root, state.shot, part)
        folder = Path(path).parent if path else (publish / version if version else publish)
        found = _nearest(folder, publish)
        if found is not None:
            out[part] = found.as_posix()
    return out


def _newer(current: str, found: list[str]) -> str | None:
    later = [v for v in found if _vnum(v) > _vnum(current)]
    return later[-1] if later else None


def status(state: LoaderState) -> dict[str, tuple[str, str | None]]:
    """Per part (anim, lookdev, groom, cloth): (status, newer version or None)."""
    root = Path(state.project_root)
    r = resolve(state)
    out: dict[str, tuple[str, str | None]] = {}
    newer = _newer(main_version(state), _anim_versions(root, state))
    out["anim"] = (STATUS_MISSING, newer) if not r.anim else ((STATUS_NEWER, newer) if newer else (STATUS_OK, None))
    geo_count = _geo_count(root, state)
    for part in PARTS:
        if not _applies(state, part):
            out[part] = (STATUS_OFF, None)
        elif state.asset is None:
            out[part] = (STATUS_ASSET, None)
        else:
            found = _found_versions(root, state, part, geo_count)
            later = _newer(state.versions.get(part, ""), found)
            if not getattr(r, part):
                named = state.versions.get(part, "")
                if not named and found:  # nothing picked when the node was made; now there is: newer
                    out[part] = (STATUS_NEWER, found[-1])
                else:
                    out[part] = (STATUS_MISSING, later) if named else (STATUS_NONE, None)
            else:
                out[part] = (STATUS_NEWER, later) if later else (STATUS_OK, None)
    return out


def initial_state(root: Path, shot: str, anim_version: str, output: Output) -> LoaderState:
    """A new loader's state: the newest version of each part, picked once."""
    inst = resolve_instance(output, set(list_asset_dirs(root)))
    st = LoaderState(str(root), shot, anim_version, output.file, inst.asset, inst.name, inst.kind,
                     {p: inst.kind == "geo" for p in PARTS}, {p: "" for p in PARTS})
    return with_latest(st, PARTS)


def initial_asset_state(root: Path, asset: str, base: LoaderState | None = None) -> LoaderState:
    """Source Asset for ``asset``: newest model and groom, lookdev kept when ``base`` is on the same asset, else
    newest; picked once. ``base`` keeps a node's shot fields and settings (switching Source loses nothing)."""
    if base is None:
        base = LoaderState(str(root), "", "", "", asset, asset, "geo", {p: p != "cloth" for p in PARTS},
                           {p: "" for p in PARTS})
    same = base.asset == asset
    st = replace(base, project_root=str(root), source=config.SOURCE_ASSET, asset=asset, instance_name=asset,
                 kind="geo", model_version="", model_file=base.model_file if same else "",
                 versions={**base.versions, "groom": "", "lookdev": base.versions.get("lookdev", "") if same else ""})
    return with_latest(st, ("anim", "groom") if st.versions.get("lookdev") else ("anim", "lookdev", "groom"))


def with_latest(state: LoaderState, parts: tuple[str, ...]) -> LoaderState:
    """The state with the newest version of each named part ("anim" included) that holds this instance."""
    root = Path(state.project_root)
    st = replace(state, enabled=dict(state.enabled), versions=dict(state.versions))
    if "anim" in parts:
        found = _anim_versions(root, state)
        if is_asset(state) and found:
            asset_dir = _asset_dir(root, state)
            files = usd_files(model_publish_dir(asset_dir) / found[-1]) if asset_dir else []
            st = replace(st, model_version=found[-1],
                         model_file=pick_file(files, state.asset or "", "uv", state.model_file))
        elif found:
            st = replace(st, anim_version=found[-1])
    if state.kind != "geo" or state.asset is None:
        return st
    geo_count = _geo_count(root, st)
    for part in PARTS:
        if part in parts:
            found = _found_versions(root, st, part, geo_count)
            if found:
                st.versions[part] = found[-1]
    return st


def retarget_state(state: LoaderState, shot: str) -> tuple[LoaderState | None, str]:
    """A loader copied from another shot, moved to ``shot``: the newest anim version there that holds the same
    instance (the camera: that shot's camera), groom / cloth at their newest there (they are per shot), lookdev and
    the node's settings kept. (None, why) when the shot has no such instance; the same state for the same shot."""
    if state.shot == shot:
        return state, ""
    root = Path(state.project_root)
    pub = anim_publish_dir(root, shot)
    assets = set(list_asset_dirs(root))
    for version in reversed(list_versions(pub)):
        for out in read_outputs(pub / version):
            if out.kind != state.kind:
                continue
            inst = resolve_instance(out, assets)
            if state.kind == "cam" or inst.name == state.instance_name or out.file == state.anim_file:
                moved = LoaderState(state.project_root, shot, version, out.file, state.asset,
                                    inst.name if state.kind == "cam" else state.instance_name, state.kind,
                                    dict(state.enabled), {**state.versions, **{t: "" for t in FX_TASKS}})
                return with_latest(moved, FX_TASKS), ""
    return None, f"{state.instance_name} is not in {shot}"


def switch_shot(state: LoaderState, shot: str) -> LoaderState:
    """The artist changed the shot on the node (``state`` holds the shot it was on, "" when unknown). The same
    instance there moves as Retarget does; else the shot's newest anim version and no anim file yet (never a
    version of the old shot, which made "v001 missing on disk")."""
    if state.shot == shot:
        return state
    if state.anim_file and state.project_root and shot:
        moved, _why = retarget_state(state, shot)
        if moved is not None:
            return moved
    versions = list_versions(anim_publish_dir(Path(state.project_root), shot)) if state.project_root and shot else []
    return LoaderState(state.project_root, shot, versions[-1] if versions else "", "", None, "", state.kind,
                       dict(state.enabled), {p: "" for p in PARTS})


NO_PROJECT = ("Not in a project: set Project Root under Advanced, or open the Manager and pick one in its "
              "Project box.")


def next_step(state: LoaderState) -> tuple[str, str]:
    """(status line, node comment) for the one thing the artist does next while the source is not set; ("", "")
    once it is. One line instead of every part reporting itself missing."""
    root = Path(state.project_root) if state.project_root else None
    if root is None or not (root / "02_shots").is_dir():
        return NO_PROJECT, "no project"
    if is_asset(state):
        return _next_step_asset(root, state)
    if not state.shot:
        return "Pick a shot.", "pick a shot"
    if not (root / "02_shots" / state.shot).is_dir():
        return f"No shot {state.shot} in this project: pick a shot.", f"no shot {state.shot}"
    versions = list_versions(anim_publish_dir(root, state.shot))
    if not versions:
        return f"{state.shot} has no anim publish yet: pick another shot.", f"{state.shot}: no anim"
    if not state.anim_version:
        return "Pick an anim version.", "pick an anim version"
    if not state.anim_file:
        return "Pick an anim file.", "pick an anim file"
    return "", ""


def _next_step_asset(root: Path, state: LoaderState) -> tuple[str, str]:
    if not state.asset:
        return "Pick an asset.", "pick an asset"
    asset_dir = list_asset_dirs(root).get(state.asset)
    if asset_dir is None:
        return f"No asset {state.asset} in this project: pick an asset.", f"no asset {state.asset}"
    if not list_versions(model_publish_dir(asset_dir)) and not list_versions(asset_dir / "05_lookdev" / "publish"):
        return f"{state.asset} has no UV or lookdev publish yet.", f"{state.asset}: no publish"
    if not state.model_version:
        return "Pick a model version.", "pick a model version"
    if not state.model_file:
        return "Pick a model file.", "pick a model file"
    return "", ""


def model_file_choices(state: LoaderState) -> list[tuple[str, str]]:
    """(file, label) of the model version's USD files; the standard name says so. The picked file stays listed."""
    asset_dir = _asset_dir(Path(state.project_root), state) if state.project_root else None
    files = usd_files(model_publish_dir(asset_dir) / state.model_version) if asset_dir and state.model_version else []
    if state.model_file and state.model_file not in files:
        files = sorted(files + [state.model_file], key=str.lower)
    std = standard_file(files, state.asset or "", "uv")
    return [(f, f"{f}  (standard)" if f == std else f) for f in files]


def from_character_loader(values: dict[str, str]) -> tuple[LoaderState | None, dict[str, object], str]:
    """A Character Loader 3.2 node's parm values as Source Asset: (state, other parms of the 2.2 node, why not).
    Its Modify (SOP Modify) is not carried (the user's call, 2026-11-17)."""
    folder = values.get("folder_path", "")
    root = find_project_root(Path(folder)) if folder else None
    asset = values.get("Model_List", "")
    if root is None or not asset:
        return None, {}, "no project or asset on the node"
    on = values.get("Enable_Groom", "0") not in ("0", "", "off")
    versions = {"lookdev": values.get("Version_Lookdev_List", "") if _VERSION_RE.match(
                    values.get("Version_Lookdev_List", "")) else "",
                "groom": values.get("Version_Groom_List", "") if _VERSION_RE.match(
                    values.get("Version_Groom_List", "")) else "",
                "cloth": ""}
    model_v = values.get("Version_List", "")
    st = LoaderState(str(root), "", "", "", asset, asset, "geo",
                     {"lookdev": bool(versions["lookdev"]), "groom": on, "cloth": False}, versions,
                     config.SOURCE_ASSET, model_v if _VERSION_RE.match(model_v) else "", values.get("File_List", ""))
    empty = tuple(p for p in ("lookdev", "groom") if not versions[p])
    st = with_latest(st, (("anim",) if not st.model_version else ()) + empty)
    extra: dict[str, object] = {}
    if values.get("enableScale", "0") not in ("0", "", "off"):
        try:
            extra["scale"] = float(values.get("scale", "1"))
        except ValueError:
            pass
    pattern = values.get("primpattern1", "").strip()
    if values.get("Enable_Prune", "0") not in ("0", "", "off") and pattern:
        # 3.2 pruned anywhere in the stage; 2.2 hides under the instance
        extra["mx_hide_enable"] = 1
        extra["mx_hide_pattern"] = pattern.lstrip("/") if "/" in pattern else f"**/{pattern}"
    return st, extra, ""


def groom_targets(curves: list[str]) -> list[tuple[str, str]]:
    """(path in the groom cache, path under the instance) per curves prim: groom sits at /Groom/<name>, outside
    Geo, where lookdev binds hair (the user's pick, 2026-11-17). A cache already under /Groom stays; two prims
    with one name keep their parent's name too."""
    out, used = [], set()
    root = config.GROOM_ROOT + "/"
    for src in curves:
        if src.startswith(root):
            dst = src
        else:
            bits = src.strip("/").split("/")
            dst = root + bits[-1]
            if dst in used and len(bits) > 1:
                dst = root + f"{bits[-2]}_{bits[-1]}"
        used.add(dst)
        out.append((src, dst))
    return out


def shot_menu(project_root: str, current: str) -> list[tuple[str, str]]:
    """(token, label) per shot of the project; a shot without an anim publish says so. The current shot stays in
    the menu even when the project does not have it."""
    root = Path(project_root) if project_root else None
    shots = list_shots(root) if root is not None and root.is_dir() else []
    if current and current not in shots:
        shots = sorted(shots + [current], key=str.lower)
    out = []
    for shot in shots:
        has = root is not None and bool(list_versions(anim_publish_dir(root, shot)))
        out.append((shot, shot if has else f"{shot}  (no anim)"))
    return out


def list_part_versions(state: LoaderState, part: str) -> list[str]:
    """Versions of a part (lookdev / groom / cloth) on disk, oldest first, whether or not they hold this instance."""
    return _part_versions(Path(state.project_root), state, part)


# --- the parm pane (layout D, the user's pick, 2026-11-17) -------------------------------------------
# A version menu says the status in its labels ("v003  (v004 available)"); the node's comment sums up the parts in
# the network editor; mx_status keeps only what needs the artist (a missing file, an unknown asset) and notes.

def version_menu(versions: list[str], current: str, found: list[str]) -> list[tuple[str, str]]:
    """(token, label) per version on disk; ``found`` = the versions holding this instance, oldest first."""
    items = list(versions)
    if current and current not in items:
        items = sorted(items + [current], key=_vnum)
    later = _newer(current, found)
    out = []
    for v in items:
        if v == current:
            if later:
                label = f"{v}  ({later} available)"
            elif v in found:
                label = f"{v}  latest"
            else:
                label = f"{v}  missing" if found or v not in versions else v
        else:
            label = f"{v}  newest" if found and v == found[-1] else v
        out.append((v, label))
    return out


def version_choices(state: LoaderState, part: str) -> list[tuple[str, str]]:
    """The version menu of ``anim`` or a part, labels carrying its status."""
    root = Path(state.project_root)
    if part == "anim" and is_asset(state):
        asset_dir = _asset_dir(root, state)
        if asset_dir is None:
            return []
        return version_menu(list_versions(model_publish_dir(asset_dir)), state.model_version,
                            _anim_versions(root, state))
    if part == "anim":
        if not (state.project_root and state.shot):
            return []
        return version_menu(list_versions(anim_publish_dir(root, state.shot)), state.anim_version,
                            _anim_versions(root, state) if state.anim_file else [])
    if not state.project_root or state.asset is None:
        return []
    found = (_found_versions(root, state, part, _geo_count(root, state))
             if (state.anim_file or is_asset(state)) else [])
    menu = version_menu(_part_versions(root, state, part), state.versions.get(part, ""), found)
    return menu or [("", "none published")]  # not Houdini's "(no entries)"


def status_comment(st: dict[str, tuple[str, str | None]]) -> str:
    """The node's comment in the network editor: what is behind or broken, else "up to date"."""
    bits = []
    for part, (s, newer) in st.items():
        if s == STATUS_MISSING:
            bits.append(f"{part} missing")
        elif s == STATUS_ASSET:
            if "asset?" not in bits:
                bits.append("asset?")
        elif newer:
            bits.append(f"{part} {newer} available")
    return ", ".join(bits) or "up to date"


def status_problems(st: dict[str, tuple[str, str | None]], versions: dict[str, str]) -> list[str]:
    """Lines for mx_status: only what the artist has to act on (a newer version is in the menu and the comment)."""
    out = []
    for part, (s, _newer_v) in st.items():
        if s == STATUS_MISSING:
            v = versions.get(part, "")
            out.append(f"{part} {v} missing on disk" if v else f"{part}: no file for this instance")
        elif s == STATUS_ASSET and not any(x.startswith("asset?") for x in out):
            out.append("asset? pick the asset this anim file belongs to")
    return out



def asset_thumbnail(asset_dir: Path) -> Path | None:
    """The asset's picture as Monos shows it: ``thumbnail.user.png``, else ``.meta/thumb_lookdev.user.png``,
    else the newest ``.meta/thumb_<department>.user.png``."""
    main = asset_dir / "thumbnail.user.png"
    if main.is_file():
        return main
    meta = asset_dir / ".meta"
    lookdev = meta / "thumb_lookdev.user.png"
    if lookdev.is_file():
        return lookdev
    try:
        others = [f for f in meta.glob("thumb_*.user.png") if f.is_file()]
    except OSError:
        return None
    return max(others, key=lambda f: f.stat().st_mtime) if others else None


# --- subdivision (the user's decision, 2026-11-17) --------------------------------------------------
# Per mesh of an instance, the first that says something wins: a shot rule on the loader node, the lookdev
# publish, the anim publish, else none. USD's own fallback (catmullClark) is never used: it made the viewport
# subdivide whole shots. Opinions are read from the publish files themselves; the grafted stage carries the
# fallback as a value.

SUBD_NONE, SUBD_CATMULL = "none", "catmullClark"
SUBD_SCHEMES = (SUBD_NONE, SUBD_CATMULL, "loop", "bilinear")
SUBD_PUBLISH = "publish"  # a rule that leaves the scheme to lookdev / anim (its dicing still applies)


@dataclass(frozen=True)
class SubdChoice:
    scheme: str
    source: str  # "shot" | "lookdev" | "publish" | "default"
    dicing: float | None = None


def parse_subd_rules(text: str) -> list[dict]:
    """The loader's JSON rules, keeping only well-formed ones: {"pattern", "scheme", optional "dicing"}."""
    import json

    try:
        raw = json.loads(text) if text else []
    except ValueError:
        return []
    rules = []
    for r in raw if isinstance(raw, list) else []:
        if not isinstance(r, dict) or not isinstance(r.get("pattern"), str) or not r["pattern"].strip():
            continue
        if r.get("scheme") not in (SUBD_PUBLISH, *SUBD_SCHEMES):
            continue
        rule = {"pattern": r["pattern"].strip().strip("/"), "scheme": r["scheme"]}
        if isinstance(r.get("dicing"), (int, float)) and r["dicing"] > 0:
            rule["dicing"] = float(r["dicing"])
        rules.append(rule)
    return rules


def _pattern_re(pattern: str) -> re.Pattern:
    out = ""
    for part in re.split(r"(\*\*|\*|\?)", pattern.strip("/")):
        out += {"**": ".*", "*": "[^/]*", "?": "[^/]"}.get(part, re.escape(part))
    return re.compile(rf"^{out}$")


def subd_plan(meshes: list[str], lookdev: dict[str, str], anim: dict[str, str],
              rules: list[dict]) -> dict[str, SubdChoice]:
    """Scheme, where it comes from and dicing for each mesh (paths as in the publish files, ``/Geo/...``).
    Rules match the path without its leading ``/``; a later rule overrides an earlier one."""
    compiled = [(_pattern_re(r["pattern"]), r) for r in rules]
    plan = {}
    for mesh in meshes:
        rel = mesh.strip("/")
        scheme = source = None
        dicing = None
        for rx, r in compiled:
            if rx.match(rel):
                if r["scheme"] != SUBD_PUBLISH:
                    scheme, source = r["scheme"], "shot"
                elif source == "shot":
                    scheme = source = None
                if "dicing" in r:
                    dicing = r["dicing"]
        if scheme is None:
            if mesh in lookdev:
                scheme, source = lookdev[mesh], "lookdev"
            elif mesh in anim:
                scheme, source = anim[mesh], "publish"
            else:
                scheme, source = SUBD_NONE, "default"
        plan[mesh] = SubdChoice(scheme, source, dicing)
    return plan


def subd_polygons(face_counts: dict[str, int], plan: dict[str, SubdChoice], level: int = 2) -> int:
    """About how many polygons the viewport makes for the subdivided meshes (each level x4)."""
    return sum(n * 4 ** level for mesh, n in face_counts.items()
               if plan.get(mesh) and plan[mesh].scheme != SUBD_NONE)


HEAVY_SUBD_POLYGONS = 5_000_000  # above this the viewport gets slow: suggest Draw Hulls Only


def heavy_shot_message(loads: list[tuple[str, int]], threshold: int = HEAVY_SUBD_POLYGONS) -> str | None:
    """The heavy-shot line from (instance, estimated subdivision polygons), or None under the threshold."""
    heavy = sorted([(n, p) for n, p in loads if p > 0], key=lambda x: -x[1])
    total = sum(p for _, p in heavy)
    if total <= threshold:
        return None
    names = [n for n, _ in heavy[:3]] + ([f"+{len(heavy) - 3}"] if len(heavy) > 3 else [])
    return f"Heavy shot: ~{total / 1e6:.1f} M subdivision polygons ({', '.join(names)})"


# --- scene opened with loaders behind (the user's ask, 2026-11-19) -----------------------------------------
# A prompt stacked with the heavy-shot one. Its "Don't show again" holds for what it named only: the signature of
# the loaders, parts and newer versions it listed. A newer publish, or the same one after the scene was brought up to
# date (the dismissal is dropped then), shows it again.

Outdated = list[tuple[str, list[tuple[str, str, str]]]]  # (node name, [(part, on the node, newer)])


def outdated(loaders: list[tuple[str, LoaderState, dict[str, tuple[str, str | None]]]]) -> Outdated:
    """(node name, [(part, version on the node, newer version)]) of every loader with a newer publish."""
    out = []
    for name, state, st in loaders:
        bits = []
        for part, (s, newer) in st.items():
            if s != STATUS_NEWER or not newer:
                continue
            word = ("model" if is_asset(state) else "anim") if part == "anim" else part
            have = main_version(state) if part == "anim" else state.versions.get(part, "")
            bits.append((word, have or "-", newer))
        if bits:
            out.append((name, bits))
    return sorted(out, key=lambda x: x[0].lower())


def outdated_title(items: Outdated) -> str:
    n = len(items)
    return f"{n} loader{'' if n == 1 else 's'} behind: newer publishes found"


def outdated_lines(items: Outdated, limit: int = 4) -> list[str]:
    lines = [f"{name}: " + ", ".join(f"{p} {a} → {b}" for p, a, b in bits) for name, bits in items[:limit]]
    if len(items) > limit:
        lines.append(f"+{len(items) - limit} more")
    return lines


def outdated_signature(items: Outdated) -> str:
    """What a "Don't show again" was given for: loaders, parts and the newer versions."""
    return ";".join(f"{name}:{p}:{b}" for name, bits in items for p, _a, b in bits)


def outdated_shows(items: Outdated, dismissed: str) -> bool:
    """True when something behind was not in what "Don't show again" was given for (a loader updated since keeps
    the rest quiet; a newer version than the one dismissed shows it)."""
    gone = set(filter(None, (dismissed or "").split(";")))
    return bool(items) and not set(outdated_signature(items).split(";")) <= gone


KEEP = object()  # set_subd_rules: leave this field as the pattern's rule has it


def set_subd_rules(rules: list[dict], patterns: list[str], scheme: str | None,
                   dicing: float | None | object = KEEP) -> list[dict]:
    """Rules with one rule per pattern, put last so it wins. ``scheme`` None keeps the pattern's scheme (publish
    when it had none); ``dicing`` KEEP keeps its dicing, None clears it. A rule left with publish and no dicing
    says nothing, so it is dropped."""
    old = {r["pattern"]: r for r in rules}
    keep = [r for r in rules if r["pattern"] not in patterns]
    for p in patterns:
        before = old.get(p, {})
        sch = scheme if scheme is not None else before.get("scheme", SUBD_PUBLISH)
        dic = before.get("dicing") if dicing is KEEP else dicing
        if sch == SUBD_PUBLISH and dic is None:
            continue
        rule = {"pattern": p, "scheme": sch}
        if dic is not None:
            rule["dicing"] = float(dic)
        keep.append(rule)
    return keep


def clear_subd_rules(rules: list[dict], patterns: list[str] | None) -> list[dict]:
    """Rules without those patterns (None: no rules at all)."""
    return [] if patterns is None else [r for r in rules if r["pattern"] not in patterns]


# --- groom curves per shot (the user's pick, layout A, 2026-11-22) ------------------------------------------------
# BasisCurves have no subdivisionScheme and no dicing. What a lighter sets per shot are Karma's render-time curve
# properties, primvars on each curves prim, so the cache (value clips) and the viewport are left alone:
#   basis  primvars:karma:object:curve_basis   Override Curves Basis: the linear groom rendered smooth (B-spline,
#                                              Catmull-Rom) or a cubic one forced linear; cubic needs 4+ CVs a curve.
#                                              Bezier (4 + 3N CVs) is left out: Helen's 9 / 33-CV strands break it.
#   width  primvars:karma:object:width_scale   a multiplier on the published widths
#   style  primvars:karma:object:curve_style   Render Curves As: rounded (Karma's default), flat or oriented ribbons;
#                                              Karma XPU renders rounded only, Karma CPU no oriented linear curves.
# Rules are JSON on the loader (mx_curve_rules), patterns as for subdivision (from /<instance>, no leading "/");
# a later rule wins field by field. The same wording as subdivision: "publish" = what the files say.
CURVE_LINEAR, CURVE_BSPLINE, CURVE_CATMULL, CURVE_BEZIER = "linear", "bspline", "catmullRom", "bezier"
CURVE_BASES = (CURVE_LINEAR, CURVE_BSPLINE, CURVE_CATMULL)  # what a rule may set
CURVE_BASIS_KARMA = {CURVE_LINEAR: 1, CURVE_BEZIER: 2, CURVE_BSPLINE: 3, CURVE_CATMULL: 4}  # Karma's menu order
KARMA_CURVE_BASIS = {v: k for k, v in CURVE_BASIS_KARMA.items()}
CURVE_STYLES = ("flat", "rounded", "oriented")  # Karma's menu order 0, 1, 2 (3 = USD's default behaviour)
CURVE_STYLE_KARMA = {s: i for i, s in enumerate(CURVE_STYLES)}
CURVE_PRIMVARS = {"basis": "karma:object:curve_basis", "width": "karma:object:width_scale",
                  "style": "karma:object:curve_style"}
CURVE_MIN_CUBIC_CVS = 4


@dataclass(frozen=True)
class CurveChoice:
    """How Karma renders one groom curves prim: its basis, width scale and style, and where each comes from."""

    basis: str             # linear | bspline | catmullRom | bezier
    basis_source: str      # "shot" | "lookdev" | "publish"
    width: float = 1.0
    width_source: str = "publish"
    style: str = ""        # "" = Karma's default (rounded)
    style_source: str = ""
    min_cvs: int = 0       # the fewest CVs a curve of the prim has (cubic needs 4)
    published_basis: str = CURVE_LINEAR


def parse_curve_rules(text: str) -> list[dict]:
    """The loader's JSON curve rules, keeping only well-formed fields: {"pattern", "basis", "width", "style"}."""
    import json

    try:
        raw = json.loads(text) if text else []
    except ValueError:
        return []
    rules = []
    for r in raw if isinstance(raw, list) else []:
        if not isinstance(r, dict) or not isinstance(r.get("pattern"), str) or not r["pattern"].strip():
            continue
        rule: dict = {"pattern": r["pattern"].strip().strip("/")}
        if r.get("basis") in CURVE_BASES:
            rule["basis"] = r["basis"]
        if isinstance(r.get("width"), (int, float)) and not isinstance(r.get("width"), bool) and r["width"] > 0:
            rule["width"] = float(r["width"])
        if r.get("style") in CURVE_STYLES:
            rule["style"] = r["style"]
        if len(rule) > 1:
            rules.append(rule)
    return rules


def curve_overrides(path: str, rules: list[dict]) -> dict:
    """What the shot's rules set on one curves prim (path under the instance, ``/Groom/<name>``): a later rule wins
    field by field."""
    rel = path.strip("/")
    out: dict = {}
    for r in rules:
        if _pattern_re(r["pattern"]).match(rel):
            out.update({k: v for k, v in r.items() if k != "pattern"})
    return out


def _published_basis(facts: dict) -> str:
    karma = facts.get("curve_basis")
    if karma in KARMA_CURVE_BASIS:
        return KARMA_CURVE_BASIS[karma]
    if facts.get("type") == "cubic":
        return facts.get("basis") or CURVE_BEZIER  # USD's fallback basis
    return CURVE_LINEAR


def curve_plan(curves: dict[str, dict], lookdev: dict[str, dict], rules: list[dict]) -> dict[str, CurveChoice]:
    """Basis, width and style of each groom curves prim: the shot's rule > lookdev > the groom file. ``curves`` holds
    the groom's facts per prim ({"type", "basis", "min_cvs", and Karma's "curve_basis" / "width_scale" /
    "curve_style" when authored}), ``lookdev`` what the lookdev authors on the same paths.
    The lookdev's type / basis win over the cache's (the user's call, 2026-11-22; groom_topology takes the cache's
    off), except a cubic lookdev over a cache with a curve under 4 CVs: the cache's stay, or Karma drops them."""
    plan = {}
    for path, facts in curves.items():
        look = lookdev.get(path, {})
        if look.get("type") == "cubic" and 0 < int(facts.get("min_cvs") or 0) < CURVE_MIN_CUBIC_CVS:
            look = {k: v for k, v in look.items() if k not in ("type", "basis")}
        merged = {**facts, **{k: v for k, v in look.items() if v is not None}}
        src = "lookdev" if any(k in look for k in ("type", "basis", "curve_basis")) else "publish"
        published = _published_basis(merged)
        width = merged.get("width_scale")
        style = merged.get("curve_style")
        choice = {"basis": published, "basis_source": src,
                  "width": float(width) if isinstance(width, (int, float)) and width > 0 else 1.0,
                  "width_source": "lookdev" if "width_scale" in look else "publish",
                  "style": CURVE_STYLES[style] if isinstance(style, int) and 0 <= style < 3 else "",
                  "style_source": ("lookdev" if "curve_style" in look else "publish") if style is not None else "",
                  "min_cvs": int(facts.get("min_cvs") or 0), "published_basis": published}
        shot = curve_overrides(path, rules)
        if "basis" in shot:
            choice.update(basis=shot["basis"], basis_source="shot")
        if "width" in shot:
            choice.update(width=shot["width"], width_source="shot")
        if "style" in shot:
            choice.update(style=shot["style"], style_source="shot")
        plan[path] = CurveChoice(**choice)
    return plan


def set_curve_rules(rules: list[dict], patterns: list[str], basis=KEEP, width=KEEP, style=KEEP) -> list[dict]:
    """Rules with one rule per pattern, put last so it wins. A field left KEEP keeps the pattern's value, None takes
    it off (the publish decides again); a rule left with no field is dropped."""
    old = {r["pattern"]: r for r in rules}
    keep = [r for r in rules if r["pattern"] not in patterns]
    for p in patterns:
        rule = dict(old.get(p, {"pattern": p}))
        for name, value in (("basis", basis), ("width", width), ("style", style)):
            if value is KEEP:
                continue
            if value is None:
                rule.pop(name, None)
            else:
                rule[name] = float(value) if name == "width" else value
        if len(rule) > 1:
            keep.append(rule)
    return keep


clear_curve_rules = clear_subd_rules  # the same shape: rules without those patterns (None: none at all)


def width_word(width: float) -> str:
    return f"×{width:g}"


# --- what each prim shows: visibility and purpose, apart (the user's ask, 2026-11-17: three toggles as Blender's
# outliner, inheritance as Houdini / USD) ------------------------------------------------------------------------
# A rule names one prim under the instance and sets either or both:
#   "vis":     "invisible" | "inherited"   the eye; hiding a prim hides everything under it, and each child keeps
#                                          its own setting for when the parent shows again
#   "purpose": "default" | "proxy" | "render" | "guide"   the viewport and render toggles: both on = default,
#                                          viewport only = proxy, render only = render, both off = guide; a prim
#                                          without its own purpose follows its parent's
PURPOSES = ("default", "proxy", "render", "guide")
PURPOSE_TOGGLES = {"default": (True, True), "proxy": (True, False), "render": (False, True), "guide": (False, False)}
TOGGLES_PURPOSE = {v: k for k, v in PURPOSE_TOGGLES.items()}
_OLD_SHOW = {"hidden": {"vis": "invisible"}, "render": {"vis": "inherited", "purpose": "render"},
             "proxy": {"vis": "inherited", "purpose": "proxy"}, "both": {"vis": "inherited", "purpose": "default"}}


@dataclass(frozen=True)
class PrimShow:
    """What a prim shows: its own eye and the result under its parents, and its purpose."""

    own_visible: bool        # its own eye, remembered under a hidden parent
    visible: bool            # its parents and itself all visible
    vis_source: str          # where its own eye comes from: "shot" | "loader" | "publish" | "" (not authored)
    purpose: str             # the purpose it ends up with (its own, else its parent's)
    purpose_source: str      # "shot" | "loader" | "publish" | "" (inherited)
    base_visible: bool = True        # its own eye without the shot's rule (the publish's or the loader's, else on)
    base_purpose: str = "default"    # its purpose without the shot's rule on it (own, else its parent's)

    @property
    def viewport(self) -> bool:
        return PURPOSE_TOGGLES.get(self.purpose, (True, True))[0]

    @property
    def render(self) -> bool:
        return PURPOSE_TOGGLES.get(self.purpose, (True, True))[1]


def parse_show_rules(text: str) -> list[dict]:
    """The loader's JSON show rules, well-formed ones only; the first form ({"show": hidden | render | proxy | both})
    reads as its visibility and purpose."""
    import json

    try:
        raw = json.loads(text) if text else []
    except ValueError:
        return []
    out = []
    for r in raw if isinstance(raw, list) else []:
        if not isinstance(r, dict) or not isinstance(r.get("pattern"), str) or not r["pattern"].strip("/ "):
            continue
        rule = {"pattern": r["pattern"].strip("/ "), **_OLD_SHOW.get(r.get("show"), {})}
        if r.get("vis") in ("invisible", "inherited"):
            rule["vis"] = r["vis"]
        if r.get("purpose") in PURPOSES:
            rule["purpose"] = r["purpose"]
        if len(rule) > 1:
            out.append(rule)
    return out


ROOT = "."  # the instance's own root prim (/<instance>): a loader's row in the inspector


def show_target(pattern: str) -> str:
    """The prim a row's pattern names (a group's ``X/**`` is the group ``X``; a loader's own row, ``**``, is the
    instance's root, ``.``)."""
    p = pattern.strip("/")
    if p in ("", "**", ROOT):
        return ROOT
    return p[:-3] if p.endswith("/**") else p


def set_show_rules(rules: list[dict], edits: list[tuple[str, str, object]]) -> list[dict]:
    """Rules after (pattern, field, value) edits: field "vis" or "purpose", value None takes that field off the
    prim's rule (it inherits again); a rule left with nothing is dropped."""
    by = {r["pattern"]: dict(r) for r in rules}
    order = [r["pattern"] for r in rules]
    for pattern, field, value in edits:
        t = show_target(pattern)
        rule = by.setdefault(t, {"pattern": t})
        if t not in order:
            order.append(t)
        if value is None:
            rule.pop(field, None)
        else:
            rule[field] = value
    return [by[t] for t in order if len(by[t]) > 1]


def clear_show_rules(rules: list[dict], patterns: list[str] | None) -> list[dict]:
    """Rules without those rows' (None: none at all)."""
    if patterns is None:
        return []
    targets = {show_target(p) for p in patterns}
    return [r for r in rules if r["pattern"] not in targets]


def prim_shows(prims: list[str], publish: dict[str, dict], hidden: list[str], render_only: list[str],
               rules: list[dict]) -> dict[str, PrimShow]:
    """What each prim (paths under the instance, no leading "/"; the groups above them are added) shows, by USD's
    rules: visibility prunes (a prim under a hidden one is hidden, its own setting kept), purpose inherits unless
    the prim has its own. Opinions, weakest first: the publish files' own (``publish``: {prim: {"visibility",
    "purpose"}}), the loader's Hide Prims (``hidden``) and groom shown for render only (``render_only``), then the
    shot's rules."""
    rule_at = {r["pattern"]: r for r in rules}
    hidden_set, render_set = set(hidden), set(render_only)
    every = set(prims)
    for p in prims:
        bits = p.split("/")
        every.update("/".join(bits[:i]) for i in range(1, len(bits)))
    # the instance's root first: hiding it hides the asset, its purpose is what the top prims inherit
    root_rule = rule_at.get(ROOT, {})
    root_vis = root_rule.get("vis", "inherited") != "invisible"
    out: dict[str, PrimShow] = {ROOT: PrimShow(root_vis, root_vis, "shot" if "vis" in root_rule else "",
                                               root_rule.get("purpose", "default"),
                                               "shot" if "purpose" in root_rule else "", True, "default")}
    for p in sorted(every, key=lambda x: (x.count("/"), x)):
        parent = out.get(p.rsplit("/", 1)[0]) if "/" in p else out[ROOT]
        own_vis, vis_src, own_pur, pur_src = True, "", None, ""
        op = publish.get(p, {})
        if op.get("visibility") in ("invisible", "inherited"):
            own_vis, vis_src = op["visibility"] != "invisible", "publish"
        if op.get("purpose") in PURPOSES:
            own_pur, pur_src = op["purpose"], "publish"
        if p in hidden_set:
            own_vis, vis_src = False, "loader"
        if p in render_set:
            own_pur, pur_src = "render", "loader"
        inherited_pur = parent.purpose if parent else "default"
        base_vis, base_pur = own_vis, own_pur if own_pur is not None else inherited_pur
        rule = rule_at.get(p, {})
        if "vis" in rule:
            own_vis, vis_src = rule["vis"] != "invisible", "shot"
        if "purpose" in rule:
            own_pur, pur_src = rule["purpose"], "shot"
        out[p] = PrimShow(own_vis, own_vis and (parent.visible if parent else True), vis_src,
                          own_pur if own_pur is not None else inherited_pur, pur_src, base_vis, base_pur)
    return out


def toggle_edits(rows: list[tuple[str, PrimShow, PrimShow | None]], which: str) -> list[tuple[str, str, object]]:
    """Rule edits for one click on a toggle ("eye", "viewport" or "render") over rows (pattern, the row, its
    parent). The clicked row, first, decides the new value for all, as in Blender, and every click changes what the
    row shows: a value the row has anyway without the shot's rule (``base_visible`` / ``base_purpose``: the publish,
    the loader, else its parent) takes the rule off, so it inherits again; any other value is the shot's rule.
    (Taking the rule off whenever the value was "on" left a prim the loader hides hidden: two clicks to show it.)"""
    if not rows:
        return []
    first = rows[0][1]
    edits: list[tuple[str, str, object]] = []
    if which == "eye":
        on = not first.own_visible
        for pattern, row, _parent in rows:
            value = "inherited" if on else "invisible"
            edits.append((pattern, "vis", None if on == row.base_visible else value))
        return edits
    flip_view = which == "viewport"
    on = not (first.viewport if flip_view else first.render)
    for pattern, row, _parent in rows:
        pair = (on, row.render) if flip_view else (row.viewport, on)
        purpose = TOGGLES_PURPOSE[pair]
        edits.append((pattern, "purpose", None if purpose == row.base_purpose else purpose))
    return edits


def hide_targets(pattern: str, prims: list[str]) -> list[str]:
    """The prims the loader's Hide Prims pattern names (space-separated, wildcards as Houdini reads them)."""
    out = []
    for part in (pattern or "").split():
        rx = _pattern_re(part.strip("/"))
        out += [p for p in prims if rx.match(p)]
    return out


def sequence_files(pattern: str, first: int | None, last: int | None) -> list[str]:
    """Every frame's file of a ``$F<pad>`` sequence (the pattern itself when it has no ``$F``)."""
    if "$F" not in pattern:
        return [pattern] if pattern else []
    if first is None or last is None:
        return []
    return [re.sub(r"\$F(\d*)", lambda m, f=f: str(f).zfill(int(m.group(1) or 1)), pattern)
            for f in range(int(first), int(last) + 1)]


def loader_files(paths: dict[str, str], frames: dict[str, tuple[int, int]], extra: list[str]) -> list[str]:
    """The files a loader reads, once each, in order: its main file and parts (``paths``: anim / model, lookdev,
    groom, cloth; a groom or cloth sequence frame by frame from ``frames``), then ``extra`` (its sublayer slots,
    the groom topology file)."""
    out: list[str] = []
    for part, path in paths.items():
        first, last = frames.get(part, (None, None))
        out += sequence_files(path, first, last)
    for path in extra:
        out += sequence_files(path, *frames.get("groom", (None, None))) if "$F" in path else [path] if path else []
    seen: set[str] = set()
    return [p for p in out if p and not (p in seen or seen.add(p))]


def first_frame_path(path: str, first: int | None) -> str:
    """A ``$F<pad>`` sequence path at its first frame (the file whose prims stand for the sequence)."""
    if "$F" not in path or first is None:
        return path
    return re.sub(r"\$F(\d*)", lambda m: str(first).zfill(int(m.group(1) or 1)), path)


def mesh_groups(meshes: list[str]) -> dict[str, list[str]]:
    """Meshes by their first two path levels (``Geo/Base_grp``), as the manager's tree shows them."""
    groups: dict[str, list[str]] = {}
    for m in meshes:
        parts = m.strip("/").split("/")
        key = "/".join(parts[:2]) if len(parts) > 2 else "/".join(parts[:-1]) or parts[0]
        groups.setdefault(key, []).append(m)
    return groups


# --- manager A (the user's pick, 2026-11-17): add assets, what is new, shot gaps, links ----------------------

def monos_link(project_root: Path, folder: Path, page: str = "assets") -> str:
    """``monos://open?project=<project>&page=<page>&e=<id>``, the link Monos opens on an asset or shot (its id is
    the first 10 hex of sha256 of the folder's path in the project, as Monos's deep_link builds it)."""
    import hashlib
    from urllib.parse import quote, urlencode

    try:
        rel = folder.resolve().relative_to(project_root.resolve()).as_posix()
    except (OSError, ValueError):
        return ""
    short = hashlib.sha256(rel.strip("/").encode("utf-8")).hexdigest()[:10]
    return "monos://open?" + urlencode({"project": project_root.name, "page": page, "e": short}, quote_via=quote)


PART_DEPARTMENT = {"model": "01_modelling/03_uv", "lookdev": "05_lookdev", "groom": "04_grooming",
                   "anim": "01_anim"}


def work_author(entity_dir: Path, department: str, version: str) -> tuple[str, str] | None:
    """(name, ISO time) of who last saved the work file of ``version`` in ``department``, from Monos's
    ``.monos/authors.json`` and ``.monos/authors/*.json`` (Monos records work files, not publishes; a publish
    vNNN comes from the work file vNNN in File mode)."""
    import json

    tag = f"_{version.lower()}."
    best: tuple[str, str] | None = None
    files = [entity_dir / ".monos" / "authors.json"]
    try:
        files += sorted((entity_dir / ".monos" / "authors").glob("*.json"))
    except OSError:
        pass
    for f in files:
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for path, rec in (data.get("files") or {}).items():
            p = path.replace("\\", "/").lower()
            if not p.startswith(department.lower() + "/") or tag not in p or not isinstance(rec, dict):
                continue
            at = str(rec.get("at", ""))
            if best is None or at > best[1]:
                best = (str(rec.get("name", "")), at)
    return best


@dataclass(frozen=True)
class WhatsNew:
    """What a newer version of a part brings, from the disk: when, who saved its work file, what changed."""

    part: str
    old: str
    new: str
    date: str = ""            # date of the version folder
    author: str = ""          # Monos work file author of the new version, "" when unknown
    lines: tuple[tuple[str, str], ...] = ()  # (what, how): ("Frames", "1-48 → 1-60"); sizes are not news
    old_path: str = ""        # the files a mesh comparison reads (adapter, pxr)
    new_path: str = ""


def _folder_date(folder: Path) -> str:
    from datetime import datetime

    try:
        return datetime.fromtimestamp(folder.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
    except OSError:
        return ""


def size_word(n: int) -> str:
    if n >= 1e9:
        return f"{n / 1e9:.1f} GB"
    return f"{n / 1e6:.1f} MB" if n >= 1e6 else f"{max(n / 1e3, 0.1):.1f} KB"


def whats_new(state: LoaderState, part: str) -> WhatsNew | None:
    """For ``part`` ("anim" = the anim or the model) the newest version holding this instance, if newer than the
    node's: its date, its work file's author and what changed on disk (outputs, frame range, file size). Mesh
    changes need pxr: the adapter adds them from old_path / new_path."""
    root = Path(state.project_root)
    if not state.project_root:
        return None
    if part == "anim":
        current, found = main_version(state), _anim_versions(root, state)
    else:
        if not _applies(state, part) or state.asset is None:
            return None
        current, found = state.versions.get(part, ""), _found_versions(root, state, part, _geo_count(root, state))
    newer = _newer(current, found)
    if newer is None:
        return None
    lines: list[str] = []
    author = None
    word = part
    if part == "anim" and is_asset(state):
        asset_dir = _asset_dir(root, state)
        if asset_dir is None:
            return None
        old_f = model_publish_dir(asset_dir) / current / state.model_file
        new_name = pick_file(usd_files(model_publish_dir(asset_dir) / newer), asset_dir.name, "uv", state.model_file)
        new_f = model_publish_dir(asset_dir) / newer / new_name
        folder, author, word = new_f.parent, work_author(asset_dir, PART_DEPARTMENT["model"], newer), "model"
    elif part == "anim":
        pub = anim_publish_dir(root, state.shot)
        old_f, new_f, folder = pub / current / state.anim_file, pub / newer / state.anim_file, pub / newer
        author = work_author(root / "02_shots" / state.shot, PART_DEPARTMENT["anim"], newer)
        old_out = {o.file for o in read_outputs(pub / current)}
        new_out = {o.file for o in read_outputs(pub / newer)}
        added, removed = sorted(new_out - old_out), sorted(old_out - new_out)
        if added:
            lines.append(("Outputs added", ", ".join(added)))
        if removed:
            lines.append(("Outputs removed", ", ".join(removed)))
        a, b = read_timeline(pub / current), read_timeline(pub / newer)
        if a and b and (a[1], a[2]) != (b[1], b[2]):
            lines.append(("Frames", f"{a[1]}-{a[2]} \u2192 {b[1]}-{b[2]}"))
        if a and b and a[0] != b[0]:
            lines.append(("Fps", f"{a[0]:g} \u2192 {b[0]:g}"))
    else:
        geo = _geo_count(root, state)
        old_p, new_p = _part_path(root, state, part, current, geo)[0], _part_path(root, state, part, newer, geo)[0]
        old_f, new_f = Path(old_p), Path(new_p)
        folder = new_f.parent
        asset_dir = _asset_dir(root, state)
        if asset_dir is not None and (part == "lookdev" or is_asset(state)):
            author = work_author(asset_dir, PART_DEPARTMENT[part], newer)
    mesh_files = part == "anim" and "$F" not in str(new_f)
    return WhatsNew(word, current, newer, _folder_date(folder), author[0] if author else "", tuple(lines),
                    old_f.as_posix() if mesh_files else "", new_f.as_posix() if mesh_files else "")


def mesh_change_lines(old: list[str], new: list[str], limit: int = 4) -> list[tuple[str, str]]:
    """("Meshes added", "Fin_L, Fin_R") / ("Meshes removed", "Tail") from two mesh path lists."""
    out = []
    for what, names in (("Meshes added", sorted(set(new) - set(old))), ("Meshes removed", sorted(set(old) - set(new)))):
        if names:
            leaf = [n.rsplit("/", 1)[-1] for n in names]
            more = f" and {len(leaf) - limit} more" if len(leaf) > limit else ""
            out.append((what, ", ".join(leaf[:limit]) + more))
    return out


def shot_gaps(project_root: str, shot: str, have_files: set[str]) -> tuple[str, list[Output]]:
    """(newest anim version, its outputs no loader stands for) of a shot: characters the scene does not have yet."""
    if not (project_root and shot):
        return "", []
    pub = anim_publish_dir(Path(project_root), shot)
    versions = list_versions(pub)
    if not versions:
        return "", []
    return versions[-1], [o for o in read_outputs(pub / versions[-1]) if o.file not in have_files]


@dataclass(frozen=True)
class CatalogItem:
    """An asset as the Add drawer shows it."""

    name: str
    group: str
    model: str           # newest UV publish version, "" when none
    lookdev: str         # newest lookdev version, "" when none
    thumb: str           # Monos thumbnail, "" when none


def asset_catalog(project_root: str, group: str = "", search: str = "", with_model: bool = True) -> list[CatalogItem]:
    """Assets of a project for the Add drawer: one group ("" = all), names holding ``search`` (case-blind),
    only those with a UV publish when ``with_model``."""
    if not project_root:
        return []
    out = []
    needle = search.strip().lower()
    for name, folder in sorted(list_asset_dirs(Path(project_root)).items(), key=lambda kv: kv[0].lower()):
        if group and folder.parent.name != group:
            continue
        if needle and needle not in name.lower():
            continue
        models = list_versions(model_publish_dir(folder))
        looks = list_versions(folder / "05_lookdev" / "publish")
        if with_model and not (models or looks):  # a prop's lookdev publish is the whole asset
            continue
        thumb = asset_thumbnail(folder)
        out.append(CatalogItem(name, folder.parent.name, models[-1] if models else "", looks[-1] if looks else "",
                               thumb.as_posix() if thumb else ""))
    return out


def handoff_name(instance: str) -> str:
    """The package folder of one instance: ``<instance>_handoff``."""
    return f"{instance}_handoff"


# --- Sublayer / Reference LOPs that read a publish (the user's ask, 2026-11-17) --------------------------------
# A scene built by hand (env_Envi lookdev: 10 Sublayers of prop lookdev publishes) shows in the manager: what it
# reads, whether a newer version exists, Update (the vNNN in the path) and Convert to a MonoFX Loader.

_PUBLISH_RE = re.compile(
    r"^(?P<root>.*?)[\\/](?:(?P<assets>01_assets)[\\/](?P<group>_[^\\/]+)[\\/](?P<asset>[^\\/]+)"
    r"|(?P<shots>02_shots)[\\/](?P<shot>[^\\/]+))[\\/](?P<dept>.+?)[\\/]publish[\\/](?P<ver>[vV]\d+)[\\/]"
    r"(?P<file>.+)$")


@dataclass(frozen=True)
class PublishRef:
    """A file path read as a publish: project, asset (or shot), department folder, version, file under it."""

    root: str
    kind: str          # "asset" or "shot"
    entity: str        # asset or shot name
    dept: str          # department folder, e.g. "05_lookdev", "01_modelling/03_uv", "01_anim"
    version: str
    file: str          # path under the version folder (may hold a sub folder)

    @property
    def part(self) -> str:
        """The manager's column for it: lookdev, groom, cloth, else anim (a model or an anim file)."""
        d = self.dept.replace("\\", "/").lower()
        if "lookdev" in d:
            return "lookdev"
        if "groom" in d:
            return "groom"
        if "cloth" in d:
            return "cloth"
        return "anim"

    @property
    def word(self) -> str:
        """What it is, for people: model, anim, lookdev, groom, cloth, else its department (texturing)."""
        d = self.dept.replace("\\", "/").lower()
        if self.part != "anim":
            return self.part
        if "modelling" in d:
            return "model"
        if d.endswith("anim"):
            return "anim"
        return re.sub(r"^\d+_", "", d.rsplit("/", 1)[-1]) or "publish"

    @property
    def loader_reads(self) -> bool:
        """A MonoFX Loader on Source Asset can take its place: an asset's UV model (01_modelling/03_uv) or lookdev.
        A texturing geo (03_surfacing/02_texturing) is neither: Upgrade made a loader that looked for it in 03_uv,
        "missing" (char_Mermaid_texturing_geo, the user's report 2026-11-20)."""
        d = self.dept.replace("\\", "/").lower()
        return self.kind == "asset" and (self.part == "lookdev" or d == "01_modelling/03_uv")

    def publish_dir(self) -> Path:
        base = Path(self.root) / ("01_assets" if self.kind == "asset" else "02_shots")
        if self.kind == "asset":
            folder = next((p for p in (base.glob(f"_*/{self.entity}")) if p.is_dir()), None)
            base = folder if folder is not None else base / "_" / self.entity
        else:
            base = base / self.entity
        return base / self.dept / "publish"

    def file_in(self, version: str) -> str:
        """The file's name in another version: a vNNN in the file name follows the version (MushroomHuge_uv_v003)."""
        cur = self.version
        return re.sub(re.escape(cur), version, self.file, flags=re.IGNORECASE) if re.search(
            re.escape(cur), self.file, flags=re.IGNORECASE) else self.file

    def path_in(self, version: str) -> str:
        return (self.publish_dir() / version / self.file_in(version)).as_posix()


def parse_publish_path(path: str) -> PublishRef | None:
    """A publish file path (``<project>/01_assets/_<group>/<asset>/<dept>/publish/vNNN/<file>`` or
    ``<project>/02_shots/<shot>/<dept>/publish/vNNN/<file>``) read into its parts; None for anything else (a path
    with a variable or an expression is not read)."""
    if not path or "$" in path or "`" in path:
        return None
    m = _PUBLISH_RE.match(path.strip())
    if not m:
        return None
    if m["assets"]:
        return PublishRef(m["root"].replace("\\", "/"), "asset", m["asset"], m["dept"].replace("\\", "/"),
                          m["ver"], m["file"].replace("\\", "/"))
    return PublishRef(m["root"].replace("\\", "/"), "shot", m["shot"], m["dept"].replace("\\", "/"), m["ver"],
                      m["file"].replace("\\", "/"))


def ref_versions(ref: PublishRef) -> list[str]:
    """Versions of the publish that hold this file (its name followed to each version), oldest first."""
    pub = ref.publish_dir()
    return [v for v in list_versions(pub) if (pub / v / ref.file_in(v)).is_file()]


def ref_status(ref: PublishRef) -> tuple[str, str | None]:
    """(status, newer version or None) of a publish path, as the loaders' parts say it."""
    found = ref_versions(ref)
    newer = _newer(ref.version, found)
    if not (ref.publish_dir() / ref.version / ref.file).is_file():
        return STATUS_MISSING, newer
    return (STATUS_NEWER, newer) if newer else (STATUS_OK, None)


def root_patterns_moved(pattern: str, roots: list[str], prim: str) -> str:
    """A prim pattern after its layer moved under ``/<prim>``: every token that names one of the layer's root prims
    (``/Cliff01_Low``, ``/Cliff01_Low/**``) gets the prefix; other tokens stay."""
    out = []
    for tok in pattern.split():
        body = tok.lstrip("/")
        head = body.split("/", 1)[0]
        out.append(f"/{prim}/{body}" if tok.startswith("/") and head in roots else tok)
    return " ".join(out)


# --- where Add puts new nodes (the user's pick, 2026-11-20) ---------------------------------------------------------
# Beside the selected node, else in the middle of the Network Editor's view. Houdini's moveToGoodPosition put them
# under every node of the network (y -20 in char_Mermaid's lookdev), out of sight.
NODE_STEP_Y = 1.2   # one node under the other
NODE_CLEAR = (2.4, 0.8)  # closer than this to a node already there is a clash


def free_spots(start: tuple[float, float], count: int, taken: list[tuple[float, float]],
               step_y: float = NODE_STEP_Y, clear: tuple[float, float] = NODE_CLEAR) -> list[tuple[float, float]]:
    """``count`` spots in a column from ``start`` downward; the whole column moves one column right until none of its
    spots sits on a node already there (``taken``: node positions)."""
    x, y = start
    for _ in range(50):
        spots = [(x, y - i * step_y) for i in range(count)]
        if not any(abs(sx - tx) < clear[0] and abs(sy - ty) < clear[1] for sx, sy in spots for tx, ty in taken):
            return spots
        x += clear[0]
    return spots


# --- selection between the viewport and the inspector tree (the user's ask, 2026-11-22) ---------------------------
def row_prim(root: str, pattern: str) -> str:
    """The stage prim of an inspector row: ``root`` is the loader's instance root ("/char_Helen", or "" with Prim
    Name off), ``pattern`` the row's (a mesh "Geo/Body", a group "Geo/**", the loader's own row "**"). The loader's
    own row with Prim Name off names no one prim: ""."""
    rel = show_target(pattern)
    if rel == ROOT:
        return root
    return f"{root}/{rel}"


def prims_by_loader(prims: list[str], roots: dict[str, str], tops: dict[str, set[str]]) -> dict[str, list[str]]:
    """Viewport prims to {loader: paths under its instance root} ("" = the root itself). A prim belongs to the
    loader whose root holds it, the longest root first; a loader with Prim Name off (root "") holds the prims under
    its own top prims (``tops``: the first names of its prims, "Geo", "Groom"). A prim of no loader is left out;
    an instance proxy's index ("/x/y[3]") is dropped."""
    order = sorted(roots, key=lambda p: -len(roots[p] or ""))
    out: dict[str, list[str]] = {}
    for prim in prims:
        prim = prim.split("[", 1)[0].rstrip("/")
        for loader in order:
            root = roots[loader] or ""
            if root:
                if prim != root and not prim.startswith(root + "/"):
                    continue
                rel = prim[len(root):].strip("/")
            else:
                rel = prim.strip("/")
                if not rel or rel.split("/", 1)[0] not in tops.get(loader, set()):
                    continue
            if rel not in out.setdefault(loader, []):
                out[loader].append(rel)
            break
    return out


def nearest_row(rel: str, rows: set[str]) -> str | None:
    """The deepest row at or above ``rel`` (a viewport pick can name a prim the tree does not list, a subset under a
    mesh); ``rows`` are the rows' own prims (``show_target`` of their patterns). None: nothing above it."""
    parts = rel.strip("/").split("/") if rel.strip("/") else []
    while parts:
        if "/".join(parts) in rows:
            return "/".join(parts)
        parts.pop()
    return ROOT if ROOT in rows else None


DRAWN_ROOT_DEPTH = 6  # how deep the drawn stage is searched for a loader's root (/World/anim/actors/char_Helen: 4)


def drawn_roots(prims: dict[str, set[str]], loaders: dict[str, tuple[str, list[str]]]) -> dict[str, str]:
    """Where each loader's instance root sits on the stage the viewer draws. ``prims``: {path: names of its
    children} of the drawn stage down to ``DRAWN_ROOT_DEPTH``; ``loaders``: {loader: (root, top names)}. A root
    stays where it is when the stage has it, else it is the one prim of its name holding its top prims (a shot
    layout grafts /char_Helen to /World/anim/actors/char_Helen). With Prim Name off (root "") it is the one prim
    holding all its top prims ("" for the stage's own root). Not found, or more than one place: left out."""
    out: dict[str, str] = {}
    for loader, (root, tops) in loaders.items():
        need = set(tops)
        if root:
            if root in prims:
                out[loader] = root
                continue
            name = root.rsplit("/", 1)[-1]
            found = [p for p, kids in prims.items() if p.rsplit("/", 1)[-1] == name and need <= kids]
        else:
            found = [p for p, kids in prims.items() if need and need <= kids]  # "" (the stage root) among them
        if len(found) == 1:
            out[loader] = found[0]
    return out


# --- picking a part's version from the manager (the user's pick, 2026-11-22: click a version cell) ----------------
@dataclass(frozen=True)
class VersionPick:
    """One version of a part on disk, for the manager's version menu."""

    version: str
    date: str = ""       # the version folder's date
    author: str = ""     # who saved its Monos work file, "" when unknown
    holds: bool = True   # holds this instance's file (a groom / cloth cache of another instance does not)
    current: bool = False


VERSION_PICK_LIMIT = 15  # the newest few; older ones stay on the node's parm menu


def version_picks(state: LoaderState, part: str, limit: int = VERSION_PICK_LIMIT) -> list[VersionPick]:
    """The versions of ``part`` ("anim" = the shot's anim, or the asset's model on Source Asset; "lookdev", "groom",
    "cloth") on disk, newest first, the node's own among them even when it is gone from disk."""
    if not state.project_root:
        return []
    root = Path(state.project_root)
    who: tuple[Path, str] | None = None
    if part == "anim":
        if is_asset(state):
            asset_dir = _asset_dir(root, state)
            if asset_dir is None:
                return []
            pub, current = model_publish_dir(asset_dir), state.model_version
            found = _anim_versions(root, state)
            who = (asset_dir, PART_DEPARTMENT["model"])
        else:
            if not state.shot:
                return []
            pub, current = anim_publish_dir(root, state.shot), state.anim_version
            found = _anim_versions(root, state) if state.anim_file else []
            who = (root / "02_shots" / state.shot, PART_DEPARTMENT["anim"])
        versions = list_versions(pub)
        holds_all = False
    else:
        if not _applies(state, part) or state.asset is None:
            return []
        asset_dir = _asset_dir(root, state)
        if part == "lookdev":
            pub = asset_dir / "05_lookdev" / "publish" if asset_dir else None
        elif is_asset(state):
            pub = groom_publish_dir(asset_dir) if asset_dir else None
        else:
            pub = fx_publish_dir(root, state.shot, part)
        if pub is None:
            return []
        current = state.versions.get(part, "")
        versions = _part_versions(root, state, part)
        found = (_found_versions(root, state, part, _geo_count(root, state))
                 if (state.anim_file or is_asset(state)) else [])
        holds_all = part == "lookdev"  # a lookdev is the asset's: every version applies
        if asset_dir is not None and part in PART_DEPARTMENT and (part == "lookdev" or is_asset(state)):
            who = (asset_dir, PART_DEPARTMENT[part])
    newest = sorted(versions, key=_vnum, reverse=True)[:limit]
    if current and current not in newest:
        newest = sorted([*newest, current], key=_vnum, reverse=True)
    out = []
    for v in newest:
        author = work_author(who[0], who[1], v) if who else None
        out.append(VersionPick(v, _folder_date(pub / v) if v in versions else "", author[0] if author else "",
                               holds_all or v in found or not found, v == current))
    return out


# --- dragging assets out of Add assets (the user's ask, 2026-11-22) -----------------------------------------------
# A drag carries one small file per asset: Houdini hands a drop on a Network Editor or a Scene Viewer to
# scripts/externaldragdrop.py as a list of files, nothing else, so the file names what to load.
ASSET_DRAG_EXT = ".monofx_asset"


def is_asset_drag(path: str) -> bool:
    return str(path).lower().endswith(ASSET_DRAG_EXT)


def write_asset_drags(folder: Path, root: str, names: list[str]) -> list[str]:
    """One ``<asset>.monofx_asset`` per asset in ``folder`` (JSON: project root, asset); their paths."""
    import json

    folder.mkdir(parents=True, exist_ok=True)
    out = []
    for name in names:
        f = folder / f"{name}{ASSET_DRAG_EXT}"
        f.write_text(json.dumps({"root": str(root), "asset": name}), encoding="utf-8")
        out.append(f.as_posix())
    return out


def read_asset_drags(paths: list[str]) -> dict[str, list[str]]:
    """{project root: asset names} of the drag files among ``paths``, in their order; unreadable ones are left out."""
    import json

    out: dict[str, list[str]] = {}
    for path in paths:
        if not is_asset_drag(path):
            continue
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        root, asset = str(data.get("root", "")), str(data.get("asset", ""))
        if root and asset and asset not in out.setdefault(root, []):
            out[root].append(asset)
    return out
