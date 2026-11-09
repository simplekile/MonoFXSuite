## [0.1.24] - 2026-11-09

### Houdini
- **Auto Material**: new window, scene first. A sidebar lists every Material Library in the scene with how many materials are behind their latest publish; the main area says what the button does ("5 materials behind v010"), shows the versions on a timeline (click one to move the materials there), the materials as tiles with a texture thumbnail and their maps beside them.
- **Auto Material**: update from the scene. "Update all" or "Update N selected" moves libraries to their latest publish without opening them, also libraries built from texture folders; only materials whose version changes are touched, edits by hand stay. One undo step, and an Undo button after each run.
- **Auto Material**: right-click a Material Library in `/stage` â€º MonoFX â€º Update materials to latest / Open in Auto Material.
- **Auto Material**: Follows selection: selecting Material Library nodes in `/stage` picks them in the window; for a texture folder the target library is chosen for you (the selected one, else the one holding the materials, else a new `{asset}_materials`) and shown, with Change.
- **Auto Material**: reads materials made by other tools from a Painter export (SideFX Painter-to-Karma) and pasted materials: versions come from the texture files, and an update changes the existing image nodes in place.
- **Auto Material**: Create, Update and Auto assign are each one undo step.
- **Auto Material**: reading exports, folders and thumbnails no longer holds the window; progress shows on the action bar instead of a dark overlay.

### Installer
- Ships `OPmenu.xml` (the MonoFX node menu).