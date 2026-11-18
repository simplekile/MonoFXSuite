"""
MonoFX Suite updates from inside Blender.

The add-on comes with the suite: ``MonoFXSuite_Setup.exe`` installs Houdini's tools and this add-on into every
Blender 5+, and a release ships only that installer (the user's call, 2026-11-19; the add-on ZIP is gone). So
Check for Updates compares the installed suite's version (``suite_updates.installed_suite_version``) with the latest
GitHub release, and Download MonoFX Setup fetches the installer and starts it: close Blender, then finish it.
``bl_info``'s version, which releases never moved, no longer decides (Blender always said up to date).
"""

from __future__ import annotations

import importlib
import json
import os
import sys
import tempfile
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

import bpy
from bpy.types import Context, Operator

from . import suite_updates as su

USER_AGENT = "MonoFX-Blender-Addon-Updater"


@dataclass(frozen=True)
class UpdateInfo:
    installed: Optional[su.Version]
    latest: su.Version
    release_tag: str
    download_url: str

    @property
    def state(self) -> str:
        return su.compare(self.installed, self.latest)

    @property
    def has_update(self) -> bool:
        return self.state in ("update", "unknown")  # unknown: an add-on copied by hand, the Setup makes it known


@dataclass(frozen=True)
class UpdateResult:
    ok: bool
    message: str
    info: Optional[UpdateInfo] = None


_last_check: Optional[UpdateInfo] = None
_last_error: str = ""
_setup_started: str = ""  # the release tag whose installer was started


def addon_package_dir() -> Path:
    """Installed ``monofx_pipeline_blender`` package folder."""
    return Path(__file__).resolve().parent


def current_addon_version() -> tuple[int, int, int]:
    pkg = importlib.import_module(__package__)
    return tuple(pkg.bl_info.get("version", (0, 0, 0)))


def installed_suite_version() -> Optional[su.Version]:
    return su.installed_suite_version(su.version_files(addon_package_dir()))


def version_label() -> str:
    """Short installed version for panel headers: the suite's (``MonoFX v0.1.38``), else the add-on's."""
    try:
        suite = installed_suite_version()
        if suite is not None:
            return f"MonoFX v{su.format_version(suite)}"
        return "v" + su.format_version(current_addon_version())
    except Exception:
        return ""


def draw_version_header(layout) -> None:
    """Show the installed version in a panel header."""
    text = version_label()
    if text:
        layout.label(text=text)


def _github_request(url: str, timeout: float = 60.0) -> tuple[bool, str, Optional[bytes]]:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/vnd.github+json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return True, "", response.read()
    except urllib.error.HTTPError as exc:
        return False, f"HTTP {exc.code}: {exc.reason}", None
    except urllib.error.URLError as exc:
        return False, f"Network error: {exc.reason}", None
    except TimeoutError:
        return False, "Request timed out.", None
    except Exception as exc:
        return False, str(exc), None


def check_for_updates() -> UpdateResult:
    """The latest release against the installed suite (no download: only the release's description)."""
    global _last_check, _last_error

    ok, err, payload = _github_request(su.RELEASE_API_URL)
    if not ok or payload is None:
        _last_check, _last_error = None, err
        return UpdateResult(ok=False, message=err)
    try:
        release = json.loads(payload.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        _last_check, _last_error = None, f"Invalid GitHub response: {exc}"
        return UpdateResult(ok=False, message=_last_error)
    tag = str(release.get("tag_name") or "").strip()
    latest = su.parse_version(tag)
    asset = su.pick_setup_asset(release.get("assets") or [])
    if latest is None or asset is None or not asset.get("browser_download_url"):
        _last_check, _last_error = None, f"The latest release ({tag or '?'}) has no {su.SETUP_ASSET}."
        return UpdateResult(ok=False, message=_last_error)

    info = UpdateInfo(installed_suite_version(), latest, tag, str(asset["browser_download_url"]))
    _last_check, _last_error = info, ""
    latest_text = su.format_version(latest)
    if info.state == "update":
        message = f"MonoFX {tag} is out (installed v{su.format_version(info.installed)})."
    elif info.state == "unknown":
        message = f"MonoFX {tag} is out; this add-on was not installed by the Setup."
    elif info.state == "ahead":
        message = f"Installed v{su.format_version(info.installed)} is newer than the release v{latest_text}."
    else:
        message = f"MonoFX is up to date (v{latest_text})."
    return UpdateResult(ok=True, message=message, info=info)


def download(url: str, dest: Path, progress: Optional[Callable[[int, int], None]] = None) -> tuple[bool, str]:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=300.0) as response:
            total = int(response.headers.get("Content-Length") or 0)
            read = 0
            dest.parent.mkdir(parents=True, exist_ok=True)
            with dest.open("wb") as handle:
                while True:
                    chunk = response.read(256 * 1024)
                    if not chunk:
                        break
                    handle.write(chunk)
                    read += len(chunk)
                    if progress is not None:
                        progress(read, total if total > 0 else read)
    except urllib.error.HTTPError as exc:
        return False, f"Download failed (HTTP {exc.code})."
    except urllib.error.URLError as exc:
        return False, f"Download failed: {exc.reason}"
    except TimeoutError:
        return False, "Download timed out."
    except OSError as exc:
        return False, f"Could not write {dest}: {exc}"
    return True, ""


def _redraw_preferences() -> None:
    screen = getattr(bpy.context, "screen", None)
    for area in getattr(screen, "areas", []) or []:
        if area.type == "PREFERENCES":
            area.tag_redraw()


def draw_preferences(layout) -> None:
    box = layout.box()
    box.label(text="MonoFX Updates (GitHub Releases)")
    installed = installed_suite_version()
    box.label(text=f"Installed MonoFX: v{su.format_version(installed)}" if installed
              else "Installed MonoFX: unknown (this add-on was not installed by the Setup)")
    if _setup_started:
        row = box.row()
        row.alert = True
        row.label(text=f"Close Blender, then finish the MonoFX {_setup_started} installer.", icon="ERROR")
    if _last_error:
        row = box.row()
        row.alert = True
        row.label(text=_last_error, icon="ERROR")
    if _last_check is not None:
        latest = su.format_version(_last_check.latest)
        icon = {"update": "IMPORT", "unknown": "IMPORT", "ahead": "INFO"}.get(_last_check.state, "CHECKMARK")
        row = box.row()
        row.alert = _last_check.has_update
        row.label(text=f"Latest release: v{latest}", icon=icon)
    row = box.row(align=True)
    row.operator("wm.mono_fx_addon_check_updates", text="Check for Updates", icon="FILE_REFRESH")
    row.operator("wm.mono_fx_addon_install_update", text="Download MonoFX Setup", icon="IMPORT")


class MONOFX_OT_addon_check_updates(Operator):
    bl_idname = "wm.mono_fx_addon_check_updates"
    bl_label = "Check for Updates"
    bl_description = "Check GitHub Releases for a newer MonoFX Suite"
    bl_options = {"REGISTER"}

    def execute(self, _context: Context) -> set[str]:
        result = check_for_updates()
        self.report({"INFO"} if result.ok else {"ERROR"}, result.message)
        _redraw_preferences()
        return {"FINISHED"}


class MONOFX_OT_addon_install_update(Operator):
    bl_idname = "wm.mono_fx_addon_install_update"
    bl_label = "Download MonoFX Setup"
    bl_description = (
        "Download MonoFXSuite_Setup.exe of the latest release and start it. It updates Houdini's tools and this "
        "add-on: close Blender, then finish the installer"
    )
    bl_options = {"REGISTER"}

    @classmethod
    def poll(cls, _context: Context) -> bool:
        return _last_check is not None and _last_check.has_update

    def invoke(self, context: Context, event) -> set[str]:
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context: Context) -> set[str]:
        global _setup_started

        if _last_check is None or not _last_check.has_update:
            self.report({"WARNING"}, "No update available. Check for updates first.")
            return {"CANCELLED"}
        if sys.platform != "win32":
            self.report({"ERROR"}, f"{su.SETUP_ASSET} runs on Windows only: download it from the release page.")
            return {"CANCELLED"}
        wm = context.window_manager
        dest = Path(tempfile.gettempdir()) / f"MonoFXSuite_Setup_{_last_check.release_tag}.exe"
        wm.progress_begin(0, 100)
        try:
            ok, err = download(_last_check.download_url, dest,
                               lambda read, total: wm.progress_update(int(read * 100 / total)) if total else None)
        finally:
            wm.progress_end()
        if not ok:
            self.report({"ERROR"}, err)
            return {"CANCELLED"}
        try:
            os.startfile(str(dest))  # noqa: S606 (the installer the user asked for, from the project's own release)
        except OSError as exc:
            self.report({"ERROR"}, f"Could not start {dest}: {exc}")
            return {"CANCELLED"}
        _setup_started = _last_check.release_tag
        _redraw_preferences()
        self.report({"INFO"}, f"MonoFX {_setup_started} installer started: close Blender, then finish it.")
        return {"FINISHED"}


ADDON_UPDATER_OPERATOR_CLASSES = (
    MONOFX_OT_addon_check_updates,
    MONOFX_OT_addon_install_update,
)
