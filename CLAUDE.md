# MonoFXSuite

## Auto Material (Houdini, `tools/fx/auto_material/` + `apps/houdini/solaris_adapter.py`)

- Texture names follow Monos Painter publishes: `{set}_{name}_{colorspace}.{UDIM}.{ext}`. The colour
  space word (sRGB, Linear, ACEScg, Raw) is what Painter really wrote, so it sets the image's
  filecolorspace; the slot default is only for names without one. `vNNN/publish.json`
  `cleaned.maps` fills the space when a name has none.
- A Monos publish folder (children `v001`, `v002`...) is scanned only at its highest version's `textures/`.
- Subsurface slots accept Painter's OpenPBR names and SSS forms (`SubsurfaceWeight`/`Subsurface`/`SSS`,
  `SubsurfaceColor`/`SSSColor`, `SubsurfaceRadius`/`SSSRadius`). Map names in Monos Settings ›
  Texturing must use one of the names in `config.SLOT_DEFS`, or the tool does not load the map.
- Coat slots use Painter's OpenPBR channel names: `CoatWeight` (also `CoatOpacity`, `Clearcoat`),
  `CoatColor`, `CoatRoughness`, `CoatRoughnessAnisotropy`, `CoatNormal`, wired to mtlxstandard_surface
  `coat*` inputs. Coat IOR and darkening are Painter shader settings, not channels: no map, no slot.
  `config.NORMAL_MAP_SLOTS` (Normal, CoatNormal) go through their own mtlxnormalmap node.
- Create on a material that already exists updates it instead of making a second one. Image nodes
  carry user data (`monofx_slot`, `monofx_file`, `monofx_colorspace`) recording what the tool set; an
  update changes a file or colour space only while it still equals that record, so edits by hand stay.
  A new map gets an image node wired only into a free surface input; nothing is deleted or re-wired,
  and existing builders and LOP nodes are not moved. Auto assign adds to `assign_material_auto`
  instead of making another node, keeping the entries already there.
- Create runs inside `solaris_adapter.manual_update()` (Houdini updates set to Manual, then put
  back): while the Material Library cooks on changes, every node created in it re-translates all its
  materials, so 16 materials took ~110 s instead of ~1 s.
- The window has two pages. **Start**: three source cards (Latest publish from `$HIP`, Texture folder,
  Painter USD), Recent paths, drag and drop, and **In this scene**: one row per asset built from a
  Painter export, with its version chip and a tick to update several at once. **Version manager**: one
  source's materials (checkbox, name, version chip) and the maps of the selected one; Change goes back.
  Latest publish takes the publish's Painter export when its latest `vNNN` holds one
  (`find_painter_usd`: highest `_vNNN` in the file name, `*.material.usda` skipped), else its textures.
- Version manager for Painter exports: every export of the same family (`list_painter_exports`: same
  name without `_vNNN`, in the publish folder and its `vNNN` children) is read; each material can be
  built from any export that has it. Default: the newest, unless the scene pins it. Chip colours:
  emerald up to date, blue will update, violet new, amber pinned, red not in the export the geometry
  comes from (the geometry always comes from the newest export). A pin keeps a material out of
  All to latest and later updates. Create rebuilds only materials that are new or change version.
- SSS and emission maps without their weight map (SubsurfaceColor/Radius, EmissionColor) set
  `subsurface` / `emission` to 1 while that input is free and 0 (`_AUTO_WEIGHTS`); coat is only reported.
- Results and notes of Create go to the line under the window, never a modal dialog: a modal box
  blocks Houdini (and the MCP bridge) until someone closes it.
- Fonts are set in pixels (`_font`, `font-size: …px`): Houdini scales point sizes with its UI scale,
  which overflowed the painted chips. Base 13px, names 14px, chips 12px.
- What the scene has is a JSON record on the asset's Material Library (user data `monofx_substance`:
  asset, export, and per material its version, pin and `left_out`: an unticked material stays off). A library made before the record existed is
  read from the `_vNNN` in the texture folders the tool set (`_infer_record`), so no data is needed
  beyond the nodes. Coming back to the window checks for a newer export and shows a banner
  ("… was just published · Open version manager"); nothing changes until Update.
- A Painter USD export is read with pxr (in the adapter; `logic.py` gets plain
  `SubstanceMaterial` data and stays testable without pxr). The export only sublayers
  `*.material.usda` (Material prims under `/Geo/material` + `over`s carrying `material:binding`) and
  the geometry it was painted on (e.g. the UV publish, which may hold its own materials, e.g.
  `/_materials`). Painter materials = Material prims with an input in `config.SUBSTANCE_INPUT_TO_SLOT`;
  the geometry = the sublayers that author none of them.
  Create then makes `{base}_geo` (Sublayer of the geometry) -> `{base}_materials` (Material Library,
  materials at `/materials/<Painter name>`, not over Painter's `/Geo/material`) -> `{base}_assign`
  (one entry per material, prims from Painter's bindings). `{base}` is the export name without `_vNNN`,
  so a newer export updates the same three nodes the usual way.
- Painter writes `<UDIM>` for a texture set on several tiles and the first tile (`.1001`) for a set on
  one; both become `.<UDIM>`. Its `colorSpace` metadata is always `raw`, so the colour space comes
  from the name's last token (ACEScg, Raw, sRGB, Linear), like the folder scan.
- UDIM paths use `<UDIM>` (MaterialX / USD), for the folder scan too. Houdini writes a parm's
  `%(UDIM)d` verbatim into the stage, which other USD readers do not resolve. Materials built before
  with `%(UDIM)d` move to `<UDIM>` on the next Create / Update, even with no version change
  (`_uses_houdini_udim`); paths changed by hand stay. Reading versions and the UI accept both tokens.

## Drag & drop from the file browser (Houdini, `scripts/externaldragdrop.py` + `apps/houdini/drag_drop.py`)

- Houdini calls `dropAccept(file_list)` in `scripts/externaldragdrop.py` from any `HOUDINI_PATH`
  folder; the suite root is the package `hpath`, and the installer copies `scripts/` there.
  Returning False hands the drop back to Houdini, which opens ANY file as a scene ("Save changes
  ... before clearing all contents?"), so only a drop of Houdini's own files (.hip, .hda/.otl) or
  a drop with the setting off is handed back. Every other drop, even one that makes nothing or
  raises, is kept and gets a status-bar warning.
- What gets made depends on the Network Editor under the cursor: OBJ (geo node + SOP, FBX import),
  SOP (File / Alembic / USD Import), LOP (a menu at the cursor picks Reference LOPs or one Sublayer
  LOP; Escape makes nothing; textures or a folder build Auto Material into the selected Material
  Library, else materiallibrary1),
  VOP (inside a Material Library: Auto Material into that library, by
  `solaris_adapter.build_material`; inside a material builder: MaterialX Image), COP (File).
  Not over a Network Editor → Houdini's default.
- Frame sequences collapse to `$F<pad>`. Textures go through Auto Material's own functions
  (`group_by_prefix`, `scan_and_group`, `_make_udim_path`, `build_material` inside `manual_update()`),
  so UDIMs become `<UDIM>` and Monos colour space words set filecolorspace exactly as in its window;
  a fix there applies to drops too. Images whose name gives no slot
  (renders, photos) make a material each with the image as base colour (8-bit sRGB, float Linear;
  setting `other_images_base_color`). A drop is one undo step. From 3 nodes / materials a drop
  shows Houdini's progress bar (`hou.InterruptableOperation`); cancelling keeps what was made.
- New nodes are placed with `moveToGoodPosition(move_inputs=False, move_outputs=False,
  move_unconnected=False)` (`solaris_adapter._place_new`): Houdini's default moves every other node
  in the network, which looks like the view jumping.
- Settings: shelf tool **Drag & Drop** (`tools/fx/drag_drop/`), saved in `~/.monofx/drag_drop_prefs.json`
  and read on every drop: on/off, LOP layer mode (ask / reference / sublayer), Auto Material for
  textures in LOP, base-colour materials for other images, frame-sequence collapse. `tools.fx.drag_drop` imports Qt only in `run()`, so the
  drop handler and tests read prefs without Qt.

## Release scripts (`bump_version.ps1`, `publish_release.ps1`, `build/build.ps1`)

- They run in Windows PowerShell 5.1, which reads a file without a BOM as ANSI (cp1252). So the
  scripts read and write VERSION, `docs/changelog.md` and `RELEASE_NOTES.md` with
  `[System.IO.File]` and UTF-8 (no BOM), never bare `Get-Content` / `Set-Content`: reading the
  changelog as ANSI and writing it back as UTF-8 doubled every non-ASCII character on each bump
  (the file reached 41 MB and lost the end of v0.1.0).
- A `.ps1` with non-ASCII text (Vietnamese messages) must be saved as UTF-8 *with* BOM. Without it,
  "ồ" (bytes E1 BB 93) is read as `á»“`, and PowerShell treats `“` as a quote: in
  `publish_release.ps1` that swallowed the lines that read `RELEASE_NOTES.md`, so releases
  v0.1.3–v0.1.22 had an empty body.
