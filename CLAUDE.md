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
  and existing builders and LOP nodes are not moved. A material is matched by builder name inside
  one Material Library. A Painter export always goes into `{base}_materials`. Auto assign adds to `assign_material_auto`
  instead of making another node, keeping the entries already there.
- Create runs inside `solaris_adapter.manual_update()` (Houdini updates set to Manual, then put
  back): while the Material Library cooks on changes, every node created in it re-translates all its
  materials, so 16 materials took ~110 s instead of ~1 s. Create, Update (all ticked assets) and
  Auto assign are each one undo step (`solaris_adapter.undo_group`), a cancelled Create too.
- One window, scene first (no pages). **Top bar**: the asset, a pill with the latest publish found
  from `$HIP` (a click reviews it; a newer export turns it into "… just published · Open"), Follows
  selection, Open (Texture folder, Painter USD, Recent, Include subfolders, Reload). **Sidebar**: every
  Material Library the tool built or can read (`updater.scene_libraries`), a ring each (share up to
  date, count behind); a click opens it; "Update all (N)" / "Update N selected" updates without
  opening (`updater.update_libraries`, one undo step). A texture folder library is found from its image
  nodes' `monofx_file` (`…/publish/vNNN/…`, `logic.texture_version`); a file changed by hand no longer
  counts. Its update changes only materials whose version changes and creates none. **Main**: a
  headline saying what the button does ("5 materials behind v010"), the source line, the version
  timeline (scene's oldest version, target; for a Painter export a click moves every material that is
  on and not pinned to that version, latest = All to latest), the materials as tiles (base colour
  thumbnail, status colour on the edge, check to leave out, right click: version, pin, leave out,
  folder) and, in a full-height column beside them, the maps of the selected tile (two lines a map: name and
  colour space, then the file). Tiles share the row's width (`_fit_tiles`). **Action bar**: result line, Undo (Houdini's undo of the
  last run), Auto assign (texture folder), the button. On open the window shows the first library
  behind its publish, else the publish when the scene has none, else the first library.
  Latest publish takes the publish's Painter export when its latest `vNNN` holds one
  (`find_painter_usd`: highest `_vNNN` in the file name, `*.material.usda` skipped), else its textures.
- Texture folder target (`logic.pick_library`): the Material Library selected in `/stage` (while
  linked), else the one holding most of the folder's materials, else a new `{asset}_materials`
  (`new_library_name`). Opened from a row, that row's library. It shows as a line ("Updating in X ·
  change"); the box (any library, or a typed new name) only after change or when it follows the
  selection ("from selection"). Libraries built from a Painter export are not offered: they update from
  their export and record. Chips: `v006→v008` update, `v008` up to date (left alone), `+v008` new
  (`folder_status`). "Also used in N other libraries" lists the others holding these materials; ticked
  ones get their existing materials updated in the same Create.
- **Follows selection** (top bar pill, saved in `%APPDATA%/MonoFXSuite/
  auto_material_prefs.json`): while on, the window polls `hou.selectedNodes()` (`SELECTION_POLL_MS`, no
  Houdini callback to clean up): selected libraries are what the sidebar updates ("Update 2 selected"), and on a
  texture folder one selected library becomes the target.
- Node menu (`OPmenu.xml` at the suite root, `tools/fx/auto_material/node_menu.py`) on a Material Library
  in `/stage`: MonoFX › Update materials to latest (every selected library plus the clicked one, by
  `updater`, Houdini's progress bar, result on the status bar) and Open in Auto Material.
- A Painter export: every export of the same family (`list_painter_exports`: same
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
  which overflowed painted text. Every label takes a role (`ui._text`): display 26/600 (headline),
  title 19/600, body 15/400, name 14/600, meta 14/400 in `TEXT_LABEL`, small and caps 13. Two weights
  only; supporting text is never `TEXT_META` (icons, placeholders, disabled). Status colours
  (`STATUS_COLORS`) are the same on rings, tile edges, chips and the legend. A pill's radius stays
  under half its height, or Qt draws square corners. Thumbnails load one per event-loop turn
  (`_Thumbnails`); EXR needs OpenImageIO, else the tile shows a placeholder.
- Versions of a Painter library come from its image files, not only its record (`library_record`):
  a material pasted from another version shows that version. Materials another tool made from a
  Painter export (SideFX's Painter-to-Karma, untagged images) are read and updated in place: the image
  wired into a slot's surface input is that slot's image (`_wired_image`), and a library without a
  record gets one from its texture folders (`_infer_record`, any name). A row's Update or Create
  builds into that library (`apply_painter_plan(library=…)`); a library other than `{base}_materials`
  keeps its geometry and assignment. Export family (`same_family`): the name before `_vNNN`, and the
  same suffix or none (`char_v008_full` then `char_v010`; `_lite` stays apart).
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
