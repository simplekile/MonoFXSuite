"""Mono Anim Loader 2.2 decisions, without hou: which instance an anim output is, where its publishes are."""

from __future__ import annotations

import re
from dataclasses import dataclass
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


def list_asset_dirs(project_root: Path) -> dict[str, Path]:
    """Every asset folder: ``01_assets/_<group>/<asset>``."""
    out: dict[str, Path] = {}
    for group in _subdirs(project_root / "01_assets"):
        if group.name.startswith("_"):
            for asset in _subdirs(group):
                out[asset.name] = asset
    return out


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
    outs = read_outputs(anim_publish_dir(root, state.shot) / state.anim_version)
    return sum(1 for o in outs if o.kind == "geo")


def _part_path(root: Path, state: LoaderState, part: str, version: str, geo_count: int) -> tuple[str, FxMatch | None]:
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
    return list_versions(fx_publish_dir(root, state.shot, part))


def _found_versions(root: Path, state: LoaderState, part: str, geo_count: int) -> list[str]:
    """Versions of a part that hold this instance's file, oldest first."""
    return [v for v in _part_versions(root, state, part) if _part_path(root, state, part, v, geo_count)[0]]


def _anim_versions(root: Path, state: LoaderState) -> list[str]:
    pub = anim_publish_dir(root, state.shot)
    return [v for v in list_versions(pub) if (pub / v / state.anim_file).is_file()]


def _applies(state: LoaderState, part: str) -> bool:
    return state.kind == "geo" and state.enabled.get(part, True)


def resolve(state: LoaderState) -> Resolved:
    """The files a state points at. Reads the disk only; the same state always gives the same paths."""
    root = Path(state.project_root)
    anim_p = anim_publish_dir(root, state.shot) / state.anim_version / state.anim_file
    paths = {"anim": anim_p.as_posix() if anim_p.is_file() else ""}
    frames: dict[str, tuple[int, int]] = {}
    notes: list[str] = [] if paths["anim"] else [f"Anim file missing: {anim_p}"]
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
    newer = _newer(state.anim_version, _anim_versions(root, state))
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


def with_latest(state: LoaderState, parts: tuple[str, ...]) -> LoaderState:
    """The state with the newest version of each named part ("anim" included) that holds this instance."""
    root = Path(state.project_root)
    anim_version = state.anim_version
    if "anim" in parts:
        found = _anim_versions(root, state)
        anim_version = found[-1] if found else anim_version
    st = LoaderState(state.project_root, state.shot, anim_version, state.anim_file, state.asset,
                     state.instance_name, state.kind, dict(state.enabled), dict(state.versions))
    if state.kind != "geo" or state.asset is None:
        return st
    geo_count = _geo_count(root, st)
    for part in PARTS:
        if part in parts:
            found = _found_versions(root, st, part, geo_count)
            if found:
                st.versions[part] = found[-1]
    return st


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
    if part == "anim":
        if not (state.project_root and state.shot):
            return []
        return version_menu(list_versions(anim_publish_dir(root, state.shot)), state.anim_version,
                            _anim_versions(root, state) if state.anim_file else [])
    if not state.project_root or state.asset is None:
        return []
    found = _found_versions(root, state, part, _geo_count(root, state)) if state.anim_file else []
    return version_menu(_part_versions(root, state, part), state.versions.get(part, ""), found)


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


def set_subd_rules(rules: list[dict], patterns: list[str], scheme: str, dicing: float | None = None) -> list[dict]:
    """Rules with one rule per pattern set to ``scheme`` / ``dicing`` (put last, so it wins). ``publish`` without
    dicing removes the override."""
    keep = [r for r in rules if r["pattern"] not in patterns]
    if scheme == SUBD_PUBLISH and dicing is None:
        return keep
    for p in patterns:
        rule = {"pattern": p, "scheme": scheme}
        if dicing is not None:
            rule["dicing"] = float(dicing)
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
