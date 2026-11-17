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
        if with_model and not list_versions(model_publish_dir(folder)):
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
                out[part] = (STATUS_MISSING, later) if (named or found) else (STATUS_NONE, None)
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
    if not list_versions(model_publish_dir(asset_dir)):
        return f"{state.asset} has no UV publish yet.", f"{state.asset}: no model"
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


def mesh_groups(meshes: list[str]) -> dict[str, list[str]]:
    """Meshes by their first two path levels (``Geo/Base_grp``), as the manager's tree shows them."""
    groups: dict[str, list[str]] = {}
    for m in meshes:
        parts = m.strip("/").split("/")
        key = "/".join(parts[:2]) if len(parts) > 2 else "/".join(parts[:-1]) or parts[0]
        groups.setdefault(key, []).append(m)
    return groups
