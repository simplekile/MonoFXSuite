# MonoFX Pipeline Blender

Blender add-on for character asset prep (Geo hierarchy, naming, materials) and asset publish (USD).

## Repository layout

| Path | Purpose |
|------|---------|
| `monofx_pipeline_blender/` | Add-on source (`__init__.py` is the entry point) |
| `releases/` | Built ZIP files for Blender **Install from disk** |
| `archive/` | Old `mono_fx_usd_export_v*.zip` builds (do not install) |
| `build.ps1` / `build.bat` | One-command build (calls `scripts/build_release_zip.py`) |
| `scripts/build_release_zip.py` | Sync `apps/common`, optional bump, ZIP output |

## Install

1. Use the latest file in `releases/` (e.g. `monofx_pipeline_blender_v080.zip`).
2. Blender → Edit → Preferences → Add-ons → Install…
3. Enable **MonoFX Pipeline Blender** → sidebar tab **MonoFX**.

## Build a new release ZIP

From this folder (PowerShell):

```powershell
.\build.ps1
```

Bump patch then build:

```powershell
.\build.ps1 -Bump patch
```

Or `build.bat` / `python scripts/build_release_zip.py --bump patch`.

Output: `releases/monofx_pipeline_blender_v<version>.zip` (version from `bl_info` in `monofx_pipeline_blender/__init__.py`).
