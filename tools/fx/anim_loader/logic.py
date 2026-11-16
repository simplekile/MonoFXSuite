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
