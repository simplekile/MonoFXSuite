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
    pattern = str(folder / f"{first_m.group(1)}.$F{len(first_m.group(2))}{first_m.group(3)}")
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
