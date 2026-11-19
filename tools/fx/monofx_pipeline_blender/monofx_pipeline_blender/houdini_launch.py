"""Test in Houdini, without bpy (tests load this file on its own).

A publish is opened in a NEW Houdini process every time (the user's pick, 2026-11-19: never a running Houdini),
built by the MonoFX Loader the way lighting reads it, with one check line on Houdini's status bar. Blender only
starts ``houdini.exe`` with the startup script shipped beside this file (``houdini_test_startup.py``); what to open
goes in env vars, because houdini.exe passes no arguments to a script.
"""

from __future__ import annotations

import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

ENV_KIND = "MONOFX_TEST_KIND"  # "model" or "anim"
ENV_PATH = "MONOFX_TEST_PATH"  # model: the USD file; anim: the version folder (or one file in it)
ENV_SUITE = "MONOFX_TEST_SUITE"  # optional: the suite root, when Houdini has no MonoFX package
STARTUP_SCRIPT = "houdini_test_startup.py"
USD_EXTS = (".usd", ".usda", ".usdc")

_HOUDINI_DIR_RE = re.compile(r"^Houdini (\d+)\.(\d+)\.(\d+)$", re.IGNORECASE)
_VERSION_DIR_RE = re.compile(r"^[vV](\d+)$")


def houdini_installs(program_files: Optional[str] = None) -> list[Path]:
    """``houdini.exe`` of every ``Side Effects Software/Houdini X.Y.Z`` install, newest first."""
    base = Path(program_files or os.environ.get("ProgramFiles", r"C:\Program Files")) / "Side Effects Software"
    found = []
    try:
        entries = list(base.iterdir())
    except OSError:
        return []
    for d in entries:
        m = _HOUDINI_DIR_RE.match(d.name)
        exe = d / "bin" / "houdini.exe"
        if m and exe.is_file():
            found.append((tuple(int(x) for x in m.groups()), exe))
    return [exe for _, exe in sorted(found, reverse=True)]


def find_houdini(pref_path: str = "", program_files: Optional[str] = None) -> Optional[Path]:
    """The add-on prefs' path when it is a file (or a folder holding ``bin/houdini.exe``), else the newest install."""
    p = (pref_path or "").strip().strip('"')
    if p:
        path = Path(p)
        for cand in (path, path / "houdini.exe", path / "bin" / "houdini.exe"):
            if cand.is_file():
                return cand
    installs = houdini_installs(program_files)
    return installs[0] if installs else None


def startup_script(package_dir: Path) -> Path:
    return package_dir / STARTUP_SCRIPT


def work_dir(temp: Optional[str] = None) -> Path:
    """Where the Houdini process runs and where a save of the test scene lands: never the project (Monos would take
    a hip there for a work file)."""
    return Path(temp or tempfile.gettempdir()) / "MonoFX" / "houdini_test"


def launch_command(houdini: Path, script: Path, kind: str, path: str, suite_root: str = "",
                   base_env: Optional[dict] = None) -> tuple[list[str], dict]:
    """(argv, env) for ``subprocess.Popen``: ``houdini.exe -foreground <script>`` with the publish in env vars."""
    if kind not in ("model", "anim"):
        raise ValueError(f"kind must be model or anim, not {kind!r}")
    env = dict(os.environ if base_env is None else base_env)
    env[ENV_KIND] = kind
    env[ENV_PATH] = str(Path(path))
    if suite_root:
        env[ENV_SUITE] = str(Path(suite_root))
    else:
        env.pop(ENV_SUITE, None)
    return [str(houdini), "-foreground", str(script)], env


# --- publishes on disk -------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class PublishChoice:
    """One publish the panel offers: ``path`` is what Houdini gets (a model file, an anim version folder)."""

    kind: str
    version: str
    path: str
    label: str


def _versions(publish_root: Path) -> list[tuple[int, Path]]:
    try:
        dirs = [d for d in publish_root.iterdir() if d.is_dir()]
    except OSError:
        return []
    out = [(int(m.group(1)), d) for d in dirs if (m := _VERSION_DIR_RE.match(d.name))]
    return sorted(out, key=lambda x: x[0], reverse=True)


def _usd_files(folder: Path) -> list[Path]:
    try:
        return sorted((f for f in folder.iterdir() if f.is_file() and f.suffix.lower() in USD_EXTS),
                      key=lambda f: f.name.lower())
    except OSError:
        return []


def model_publishes(publish_root: Optional[Path]) -> list[PublishChoice]:
    """Every USD file of every version under a modelling task's ``publish``, newest version first."""
    if publish_root is None:
        return []
    out = []
    for _, vdir in _versions(publish_root):
        for f in _usd_files(vdir):
            out.append(PublishChoice("model", vdir.name, str(f), f"{vdir.name}  {f.name}"))
    return out


def _anim_counts(files: Iterable[Path]) -> tuple[int, int]:
    geo = cam = 0
    for f in files:
        low = f.name.lower()
        geo += low.startswith("geo_")
        cam += low.startswith("cam_")
    return geo, cam


def anim_publishes(publish_root: Optional[Path]) -> list[PublishChoice]:
    """Every version folder under an anim task's ``publish`` holding USD, newest first (Houdini loads the whole
    version, as Load shot does)."""
    if publish_root is None:
        return []
    out = []
    for _, vdir in _versions(publish_root):
        files = _usd_files(vdir)
        if not files:
            continue
        geo, cam = _anim_counts(files)
        what = [f"{geo} geo" if geo else "", f"{cam} camera" if cam == 1 else (f"{cam} cameras" if cam else "")]
        words = ", ".join(w for w in what if w) or f"{len(files)} files"
        out.append(PublishChoice("anim", vdir.name, str(vdir), f"{vdir.name}  ({words})"))
    return out


def anim_test_path(written: Iterable[str]) -> str:
    """What to test after an anim publish: the version folder of the files just written."""
    for p in written:
        if p:
            return str(Path(p).parent)
    return ""
