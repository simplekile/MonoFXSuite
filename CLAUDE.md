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
  last run), Auto assign (texture folder), the button. The page title and the window title are the
  library being looked at.
- Reads never hold the window: a Painter export (pxr) and a texture folder scan run on a worker thread
  (`controller.background`, one at a time; opening something else drops the older result), what the
  scene has (hou) is read before on the main thread; thumbnails too (`_Thumbnails`, a QImage off the
  thread, the QPixmap made on the main thread). Only a scene write (Create, Update, Auto assign)
  disables the window, since hou is main-thread only: the action bar shows a thin bar, what is being
  done and Cancel, never a dark overlay. A read's result waits while a write runs. The progress state
  is a flag, not `isVisible()`: the first source is read before the window shows. On open the window shows the first library
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
  under half its height, or Qt draws square corners. EXR thumbnails need OpenImageIO (Houdini
  ships it), else the tile shows a placeholder. Icons: Houdini's own node
  icons for what a row stands for (`_node_icon`: Material Library, MaterialX surface, image; Lucide
  outside Houdini), a Lucide icon per map kind (`_slot_icon`: colour, value, shape, see-through, light,
  skin, layers), a status icon before the headline, an icon on every button.
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

## MONO Grooming (Houdini, `tools/fx/grooming/` + `apps/houdini/grooming_adapter.py`)

- Contract for v0.1: `docs/plans/grooming_v0_1.md` (scope, data model, geometry attributes, processing
  order, adapter API). One SOP HDA `mono::grooming::0.1` built from code by `tools/fx/grooming/build_hda.py`
  into `otls/` (the suite root is the package `hpath`).
- What the user set lives as JSON in the node's hidden `groom_data` parm (`model.GroomData`): a parm, so
  edits are undoable and saved with the hip. Measured lock shape lives on the geometry, never in the JSON.
  Settings resolve built-in → `defaults` → group → lock.
- A lock is spine + `lock_width` / `lock_thick` / `lock_twist` along `curveu`; the hair mesh is only an
  input. `lock_width` is the lock's width; Houdini's `width` stays the strand thickness.
- Growth regions are frozen in the node and change only on "Chia vùng": editing one lock never changes
  another lock's look without telling. Rule (`logic.region_owners`): the scalp is subdivided bilinearly
  (`region_subdiv`), each prim belongs to every lock whose footprint (0.5 x widest head width) covers its
  centroid, else the nearest lock of its group; stacked locks share prims (`lock_owners`, `share`) and
  divide the density. Nearest-root alone left 19/61 Helen fringe locks bare (roots 1-4 mm apart). The
  frozen split is read back by position (`nearpoint`), never by prim number.
- Strands per lock = density x max(its share of the scalp, its own cross-section) (`logic.lock_strands`,
  same rule in the HDA's `region_frame`): fringe locks whose roots converge on one spot still get hair
  matching their mesh. In VEX, type every `prim()` read used in arithmetic (`float a = prim(...)`):
  inside an int expression it returns int and areas of 0.03 cm² became 0.
- Hidden locks (the panel's eye) are display only: they still grow hair and are published.
- Lock ids are never reused (`GroomData.id_high`): frozen regions and old publishes may still name them.
  Detect stores roots unrounded, so an unchanged unnamed mesh re-matches "ok".
- Root end: the root of a ribbon is one END of it, never "every point near the scalp" (that took the
  whole underside of Helen's hair_base caps as root: 20 cm wide roots, strands in a cone, worst lock
  74 mm off its mesh). Two sweeps of distance along the mesh find both ends (`root_seed0` -> `end_a`
  -> `root_end`); the end nearer the scalp is the root, `root_tolerance` widens it to a band. Detect
  stores roots by this rule: a scene detected before it re-matches "unsure"; Detect again.
- Spine and measure (`build_hda.py` `spine_build`): bands by distance along the mesh from the root end,
  not by projection on a straight axis, so bent or folded ribbons still give one
  cross-section per band; per band a 2D principal-axis fit in a parallel-transported frame gives width,
  thickness and twist (a near-round band keeps the previous axis). Lock ids reach the network by the
  root Detect stored (`assign_pieces`), so Detect must run after the hair mesh changes.
- Hair quality is judged by the skill `.claude/skills/grooming-check` (numbers per strand and per lock
  against the approved groom, plus XGen-style shaded viewport shots); run it after any change to the
  network. Medians and averages passed a groom whose every strand had a 150 deg corner and half of
  whose mesh had no hair near it.
- hairgen only scatters roots on the lock's region (no guides); `fit_to_lock` places each strand on the
  lock's own mesh surface. `surface_params` gives every mesh point (along u, across s) and its offset
  from the spine; `SURFACE_CLOUD` keeps the mesh faces at (u x `surface_along_weight`, s, piece x
  `PIECE_GAP`), the underside (dt < 0) another `SHEET_GAP` away: top and underside share (u, s), and one
  lookup for both made strands jump between them (zigzags). `xyzdist` + `primuv` on the faces (not the
  nearest point) gives a continuous offset; top and underside are blended by the strand's t.
  The piece in z replaces a per-lock blast that cost 73 ms a lock.
- Strand shape: spines are smoothed along their length (`spine_smooth`, a wrangle: Attribute Blur pins
  every point of an open curve); each strand's offset from its spine gets a median of 3 and a light blur
  (`strand_smooth`); segments follow the lock's length (`strand_segment_cm`). A strand's place across
  the lock is an even spread (`cross_spread`), not where its root fell in the region (that bunched
  strands mid-lock), and its root is pulled under that spot (`root_pull`, else wide regions fan in).
  `root_blend` (0.05 of the length) eases the root onto the scalp.
- One hairclump for the whole groom, `clumpid` = `lock_id`, so clumps stay in a lock. The lock's clump
  setting drives hairclump's `blend` (per strand `clumpblend`): its tightness alone never switches
  clumping off (tightness 0 still left 27 % of Helen's mesh bare). Default clump 0.3.
  The frozen split lives on the node's hidden geometry parm `regions` (not a stash SOP: inner nodes of a
  locked HDA cannot be set); Python SOPs inside the HDA call `grooming_adapter.cook_assign` / `cook_frozen_regions`.
- hairgen's `skinprim` indexes the per-lock region cut inside the loop; strands get it again from
  `guideskinattriblookup` on the clump skin, else hairclump errors.
- The scalp and rest hair mesh are read at `rest_frame` (timeshift): a USD Import is time dependent even
  for a static file, so the whole groom recooked every frame; now only the shot deform does (0.7 s/frame).
- Inside the HDA every stage is a titled network box, one column each (`_layout_sections`): one
  `layoutChildren` over everything made a knot of crossing wires.
- Helen (sandbox t12/t16): 61/61 locks with hair, 102 k strands, full cook 2.2 s, density edit 1.7 s,
  detect 2.6 s, split 4 s, publish 1.9 s (47–56 s before regions were frozen). GUI checks run Houdini with a startup script on the secondary monitor and grab the panel.
  Quitting Houdini with `hou.exit` from a Qt timer segfaults even in an empty session (fxhoudinimcp
  loaded): not this tool; kill leftover test sessions after a GUI run.
- Shots: Karma's hair procedural (Generate) does not reproduce clump/frizz, so publishes carry full
  strands and shots Point Deform them (sandbox t02).
- Names follow the department: `grooming` (`04_grooming/publish/vNNN/char_<name>_grooming_publish.usd`,
  tool data in `vNNN/_grooming/`). Publish version defaults to the scene's `_vNNN` and never overwrites.

## Release (`release.ps1`, skill `.claude/skills/release`)

- Two steps. `release.ps1 prepare` on the branch going to main: clean tree, tests pass, notes under
  `## [Unreleased]` in `docs/changelog.md`, then `bump_version.ps1` and one commit `docs: release vX.Y.Z`.
  `release.ps1 publish` only at `origin/main` (a detached checkout works in a worktree): every check
  first, the build before the tag (a failed build leaves no tag), then tag, push the tag,
  `publish_release.ps1`. `-DryRun` stops after the build. Patch bumps unless asked otherwise.
- The release commit goes to main through the PR; merging is the user's call.
