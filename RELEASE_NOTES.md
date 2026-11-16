## [0.1.27] - 2026-11-17

### Installer
- The installer also installs the Blender add-on: a task (on by default) copies it into every Blender 5.0 or newer on the PC and turns it on, so the ZIP no longer has to be installed by hand. Close Blender first; a Blender it cannot turn the add-on on in is named at the end.
- Monos (Settings › Add-ons › Studio tools) shows the installed MonoFX version: the installer writes it to `%LOCALAPPDATA%\Monos\tools\MonoFXSuite\VERSION`, and uninstalling removes it.

### Blender
- The add-on registers in background Blender (`blender -b`): it imports `bpy.utils.previews` itself.