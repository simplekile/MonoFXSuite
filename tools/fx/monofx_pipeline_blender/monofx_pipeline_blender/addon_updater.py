"""
GitHub Releases updater for the installable Blender add-on (ZIP distribution).

Checks https://github.com/simplekile/MonoFXSuite/releases/latest for
``monofx_pipeline_blender_v*.zip``, compares ``bl_info`` versions, and can
download + extract into the active add-ons folder.
"""

from __future__ import annotations

import importlib
import io
import json
import re
import tempfile
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

import bpy
from bpy.types import Context, Operator

GITHUB_REPO = "simplekile/MonoFXSuite"
RELEASE_API_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
ASSET_PREFIX = "monofx_pipeline_blender_v"
ASSET_SUFFIX = ".zip"
ZIP_ROOT = "monofx_pipeline_blender"
USER_AGENT = "MonoFX-Blender-Addon-Updater"

_VERSION_RE = re.compile(
    r'"version":\s*\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)'
)


@dataclass(frozen=True)
class UpdateInfo:
    current: tuple[int, int, int]
    remote: tuple[int, int, int]
    release_tag: str
    asset_name: str
    download_url: str

    @property
    def has_update(self) -> bool:
        return self.remote > self.current

    @property
    def is_ahead(self) -> bool:
        return self.current > self.remote


@dataclass(frozen=True)
class UpdateResult:
    ok: bool
    message: str
    info: Optional[UpdateInfo] = None


_last_check: Optional[UpdateInfo] = None
_last_error: str = ""
_cached_zip_bytes: Optional[bytes] = None
_cached_asset_name: str = ""


def format_version(version: tuple[int, int, int]) -> str:
    return ".".join(str(x) for x in version)


def current_addon_version() -> tuple[int, int, int]:
    pkg = importlib.import_module(__package__)
    return tuple(pkg.bl_info.get("version", (0, 0, 0)))


def addons_install_dir() -> Path:
    """Parent of the installed ``monofx_pipeline_blender`` package folder."""
    return Path(__file__).resolve().parent.parent


def parse_version_from_init_text(text: str) -> Optional[tuple[int, int, int]]:
    match = _VERSION_RE.search(text)
    if not match:
        return None
    return int(match.group(1)), int(match.group(2)), int(match.group(3))


def parse_version_from_zip_bytes(data: bytes) -> Optional[tuple[int, int, int]]:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            init_name = f"{ZIP_ROOT}/__init__.py"
            if init_name not in zf.namelist():
                return None
            text = zf.read(init_name).decode("utf-8", errors="replace")
    except (zipfile.BadZipFile, KeyError, OSError):
        return None
    return parse_version_from_init_text(text)


def _github_request(url: str, timeout: float = 60.0) -> tuple[bool, str, Optional[bytes]]:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/vnd.github+json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return True, "", response.read()
    except urllib.error.HTTPError as exc:
        body = ""
        try:
            body = exc.read().decode("utf-8", errors="replace")
        except Exception:
            pass
        return False, f"HTTP {exc.code}: {body or exc.reason}", None
    except urllib.error.URLError as exc:
        return False, f"Network error: {exc.reason}", None
    except TimeoutError:
        return False, "Request timed out.", None
    except Exception as exc:
        return False, str(exc), None


def _pick_blender_asset(assets: list) -> Optional[dict]:
    matches = [
        asset
        for asset in assets
        if isinstance(asset, dict)
        and str(asset.get("name", "")).startswith(ASSET_PREFIX)
        and str(asset.get("name", "")).endswith(ASSET_SUFFIX)
    ]
    if not matches:
        return None
    matches.sort(key=lambda item: str(item.get("name", "")).lower(), reverse=True)
    return matches[0]


def check_for_updates() -> UpdateResult:
    global _last_check, _last_error, _cached_zip_bytes, _cached_asset_name

    current = current_addon_version()
    ok, err, payload = _github_request(RELEASE_API_URL)
    if not ok or payload is None:
        _last_check = None
        _last_error = err
        _cached_zip_bytes = None
        _cached_asset_name = ""
        return UpdateResult(ok=False, message=err)

    try:
        release = json.loads(payload.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        _last_check = None
        _last_error = f"Invalid GitHub response: {exc}"
        _cached_zip_bytes = None
        _cached_asset_name = ""
        return UpdateResult(ok=False, message=_last_error)

    assets = release.get("assets") or []
    asset = _pick_blender_asset(assets)
    if asset is None:
        _last_check = None
        _last_error = "Latest release has no Blender add-on ZIP asset."
        _cached_zip_bytes = None
        _cached_asset_name = ""
        return UpdateResult(ok=False, message=_last_error)

    download_url = str(asset.get("browser_download_url") or "").strip()
    asset_name = str(asset.get("name") or "").strip()
    release_tag = str(release.get("tag_name") or "").strip()
    if not download_url or not asset_name:
        _last_check = None
        _last_error = "Release asset is missing a download URL."
        _cached_zip_bytes = None
        _cached_asset_name = ""
        return UpdateResult(ok=False, message=_last_error)

    ok, err, zip_bytes = _github_request(download_url, timeout=180.0)
    if not ok or zip_bytes is None:
        _last_check = None
        _last_error = err
        _cached_zip_bytes = None
        _cached_asset_name = ""
        return UpdateResult(ok=False, message=err)

    remote = parse_version_from_zip_bytes(zip_bytes)
    if remote is None:
        _last_check = None
        _last_error = f"Could not read version from {asset_name}."
        _cached_zip_bytes = None
        _cached_asset_name = ""
        return UpdateResult(ok=False, message=_last_error)

    info = UpdateInfo(
        current=current,
        remote=remote,
        release_tag=release_tag,
        asset_name=asset_name,
        download_url=download_url,
    )
    _last_check = info
    _last_error = ""
    _cached_zip_bytes = zip_bytes
    _cached_asset_name = asset_name

    if info.has_update:
        message = (
            f"Update available: v{format_version(current)} -> "
            f"v{format_version(remote)}."
        )
    elif info.is_ahead:
        message = (
            f"Installed v{format_version(current)} is newer than the published "
            f"add-on v{format_version(remote)}."
        )
    else:
        message = f"Already up to date (v{format_version(current)})."
    return UpdateResult(ok=True, message=message, info=info)


def download_release_zip(
    download_url: str,
    dest: Path,
    *,
    progress_callback: Optional[Callable[[int, int], None]] = None,
) -> tuple[bool, str]:
    request = urllib.request.Request(
        download_url,
        headers={"User-Agent": USER_AGENT},
    )
    try:
        with urllib.request.urlopen(request, timeout=300.0) as response:
            total = int(response.headers.get("Content-Length") or 0)
            read = 0
            chunk_size = 256 * 1024
            dest.parent.mkdir(parents=True, exist_ok=True)
            with dest.open("wb") as handle:
                while True:
                    chunk = response.read(chunk_size)
                    if not chunk:
                        break
                    handle.write(chunk)
                    read += len(chunk)
                    if progress_callback is not None:
                        progress_callback(read, total if total > 0 else read)
    except urllib.error.HTTPError as exc:
        return False, f"Download failed (HTTP {exc.code})."
    except urllib.error.URLError as exc:
        return False, f"Download failed: {exc.reason}"
    except TimeoutError:
        return False, "Download timed out."
    except OSError as exc:
        return False, f"Could not write {dest}: {exc}"
    except Exception as exc:
        return False, str(exc)
    return True, ""


def extract_release_zip(zip_path: Path, addons_dir: Path) -> tuple[bool, str]:
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            root_entries = {name.split("/", 1)[0] for name in zf.namelist() if name}
            if ZIP_ROOT not in root_entries:
                return False, f"ZIP does not contain a {ZIP_ROOT}/ folder."
            for member in zf.namelist():
                if member.endswith("/"):
                    continue
                target = addons_dir / member
                target.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(member) as src, target.open("wb") as dst:
                    dst.write(src.read())
    except zipfile.BadZipFile:
        return False, "Downloaded file is not a valid ZIP archive."
    except OSError as exc:
        return False, f"Could not install into {addons_dir}: {exc}"
    except Exception as exc:
        return False, str(exc)
    return True, ""


def extract_release_zip_bytes(data: bytes, addons_dir: Path) -> tuple[bool, str]:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            root_entries = {name.split("/", 1)[0] for name in zf.namelist() if name}
            if ZIP_ROOT not in root_entries:
                return False, f"ZIP does not contain a {ZIP_ROOT}/ folder."
            for member in zf.namelist():
                if member.endswith("/"):
                    continue
                target = addons_dir / member
                target.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(member) as src, target.open("wb") as dst:
                    dst.write(src.read())
    except zipfile.BadZipFile:
        return False, "Downloaded file is not a valid ZIP archive."
    except OSError as exc:
        return False, f"Could not install into {addons_dir}: {exc}"
    except Exception as exc:
        return False, str(exc)
    return True, ""


def reload_addon(context: Context, module_name: str) -> tuple[bool, str]:
    was_enabled = module_name in context.preferences.addons
    try:
        if was_enabled:
            bpy.ops.preferences.addon_disable(module=module_name)
        bpy.ops.preferences.addon_enable(module=module_name)
    except Exception as exc:
        return False, str(exc)
    try:
        bpy.ops.wm.save_userpref()
    except Exception:
        pass
    return True, ""


def _redraw_preferences() -> None:
    screen = getattr(bpy.context, "screen", None)
    if screen is None:
        return
    for area in screen.areas:
        if area.type == "PREFERENCES":
            area.tag_redraw()


def mark_check_up_to_date() -> None:
    """Refresh UI state after a successful install without another network fetch."""
    global _last_check
    if _last_check is None:
        return
    _last_check = UpdateInfo(
        current=_last_check.remote,
        remote=_last_check.remote,
        release_tag=_last_check.release_tag,
        asset_name=_last_check.asset_name,
        download_url=_last_check.download_url,
    )


def draw_preferences(layout) -> None:
    box = layout.box()
    box.label(text="Add-on Updates (GitHub Releases)")
    current = current_addon_version()
    box.label(text=f"Installed: v{format_version(current)}")

    if _last_error:
        row = box.row()
        row.alert = True
        row.label(text=_last_error, icon="ERROR")

    if _last_check is not None:
        remote_text = format_version(_last_check.remote)
        if _last_check.has_update:
            row = box.row()
            row.alert = True
            row.label(text=f"Published add-on: v{remote_text}", icon="IMPORT")
        elif _last_check.is_ahead:
            row = box.row()
            row.label(
                text=f"Published add-on: v{remote_text} (you are ahead)",
                icon="INFO",
            )
        else:
            box.label(text=f"Published add-on: v{remote_text}", icon="CHECKMARK")
        if _last_check.release_tag:
            box.label(
                text=f"From MonoFX Suite release {_last_check.release_tag}",
                icon="NONE",
            )

    row = box.row(align=True)
    row.operator("wm.mono_fx_addon_check_updates", text="Check for Updates", icon="FILE_REFRESH")
    row.operator("wm.mono_fx_addon_install_update", text="Update Now", icon="IMPORT")


class MONOFX_OT_addon_check_updates(Operator):
    bl_idname = "wm.mono_fx_addon_check_updates"
    bl_label = "Check for Updates"
    bl_description = "Check GitHub Releases for a newer MonoFX Pipeline Blender build"
    bl_options = {"REGISTER"}

    def execute(self, _context: Context) -> set[str]:
        result = check_for_updates()
        if result.ok:
            self.report({"INFO"}, result.message)
        else:
            self.report({"ERROR"}, result.message)
        _redraw_preferences()
        return {"FINISHED"}


class MONOFX_OT_addon_install_update(Operator):
    bl_idname = "wm.mono_fx_addon_install_update"
    bl_label = "Update Add-on"
    bl_description = "Download and install the latest release from GitHub"
    bl_options = {"REGISTER"}

    @classmethod
    def poll(cls, _context: Context) -> bool:
        return _last_check is not None and _last_check.has_update

    def execute(self, context: Context) -> set[str]:
        if _last_check is None or not _last_check.has_update:
            self.report({"WARNING"}, "No update available. Check for updates first.")
            return {"CANCELLED"}

        wm = context.window_manager
        module_name = __package__
        addons_dir = addons_install_dir()
        zip_path: Optional[Path] = None
        use_cache = bool(
            _cached_zip_bytes and _cached_asset_name == _last_check.asset_name
        )

        wm.progress_begin(0, 100)
        try:
            context.window.cursor_set("WAIT")
        except Exception:
            pass

        try:
            if not use_cache:
                zip_path = Path(tempfile.gettempdir()) / _last_check.asset_name

                def on_progress(read: int, total: int) -> None:
                    if total > 0:
                        wm.progress_update(int(read * 100 / total))

                ok, err = download_release_zip(
                    _last_check.download_url,
                    zip_path,
                    progress_callback=on_progress,
                )
                if not ok:
                    self.report({"ERROR"}, err)
                    return {"CANCELLED"}

            try:
                bpy.ops.preferences.addon_disable(module=module_name)
            except Exception as exc:
                self.report({"ERROR"}, f"Could not disable add-on: {exc}")
                return {"CANCELLED"}

            if use_cache:
                ok, err = extract_release_zip_bytes(_cached_zip_bytes, addons_dir)
            else:
                assert zip_path is not None
                ok, err = extract_release_zip(zip_path, addons_dir)

            if not ok:
                try:
                    bpy.ops.preferences.addon_enable(module=module_name)
                except Exception:
                    pass
                self.report({"ERROR"}, err)
                return {"CANCELLED"}
        finally:
            if zip_path is not None:
                try:
                    zip_path.unlink(missing_ok=True)
                except OSError:
                    pass
            try:
                wm.progress_end()
            except Exception:
                pass
            try:
                context.window.cursor_set("DEFAULT")
            except Exception:
                pass

        reloaded, reload_err = reload_addon(context, module_name)
        mark_check_up_to_date()
        _redraw_preferences()

        if reloaded:
            self.report({"INFO"}, "Add-on updated. Reloaded successfully.")
        else:
            self.report(
                {"WARNING"},
                f"Files installed, but reload failed: {reload_err}. Restart Blender.",
            )
        return {"FINISHED"}


ADDON_UPDATER_OPERATOR_CLASSES = (
    MONOFX_OT_addon_check_updates,
    MONOFX_OT_addon_install_update,
)
