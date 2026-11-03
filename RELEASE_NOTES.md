## [0.1.23] - 2026-11-04

### Houdini
- **Drag & drop**: files dragged from the file browser onto a Network Editor make nodes for that network. OBJ: geo node with File / Alembic / USD Import, FBX import. SOP: File / Alembic / USD Import. LOP: Reference LOPs or one Sublayer LOP (menu at the cursor). COP: File. Frame sequences become one node with `$F4`; each drop is one undo step.
- **Drag & drop**: textures or a texture folder dropped in LOP or inside a Material Library build materials with Auto Material (into the selected Material Library, else `materiallibrary1`; an existing material is updated). Inside a material builder they become MaterialX Image nodes with the colour space set. Images whose name Auto Material cannot read (renders, photos) make a material each with the image as base colour.
- **Drag & drop**: a drop of 3 or more nodes or materials shows a progress bar that can be cancelled. A drop that makes nothing shows a warning in the status bar instead of Houdini trying to open the file as a scene; `.hip` and `.hda` files still open as before.
- **Drag & Drop** shelf tool: settings for the above (on/off, Reference / Sublayer / ask in LOP, Auto Material for textures, base-colour materials, frame-sequence collapse).
- **Auto Material**: loads Substance Painter USD exports (geometry Sublayer, Material Library, Assign Material, prims from Painter's bindings), and finds the Painter USD in a Monos publish.
- **Auto Material**: new window with a Start page (latest publish, texture folder, Painter USD, recent paths, assets in this scene) and a version manager for Painter exports (per-material version, pin, update several at once).
- **Auto Material**: coat maps from Painter's OpenPBR channels (`CoatWeight`, `CoatColor`, `CoatRoughness`, `CoatNormal`...).
- **Auto Material**: UDIM paths are written as `<UDIM>` instead of Houdini's `%(UDIM)d`, which other USD readers do not resolve; materials made before move to `<UDIM>` on the next update.
- **Auto Material**: building many materials is much faster (Houdini updates are paused while building: 16 materials ~1 s instead of ~110 s).
- **Auto Material**: new nodes no longer move the nodes already in the network.

### Installer
- Ships `scripts/` (Houdini's drag & drop hook) and the Drag & Drop shelf icon.

### Shared / tests
- Add drag & drop and Drag & Drop settings tests.