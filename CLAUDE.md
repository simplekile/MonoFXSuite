# MonoFXSuite

- Hosts: Houdini and Blender. Maya is no longer supported (the user's decision, 2026-11-17): its
  tools and `apps/maya` were removed; do not add Maya code back. Shared rig library defaults are Blender's.

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
- Fix colorspace (action bar, a Material Library selected in `/stage`): fills an empty `filecolorspace`
  on every `mtlximage` from the file name's last token (`logic.colorspace_from_filename`,
  `solaris_adapter.fix_empty_texture_colorspaces`), for materials Houdini converted from a USD, which
  leaves it empty. A value already there is never changed; one undo step.
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

## Installer and Monos (`build/installer/MonoFXSuite.iss`, `build/build.ps1`)

- Monos reads the installed MonoFX version from `tools/MonoFXSuite/VERSION` beside its exe, the folder in
  `%LOCALAPPDATA%\Monos\install_path.txt`, then `%LOCALAPPDATA%\Monos\tools\MonoFXSuite\VERSION`; the
  installer writes the last one (always writable, removed on uninstall). The old `MonoStudio\install_path.txt`
  path is kept for MonoStudio.
- Task `blenderaddon` installs the Blender add-on like Monos installs its extensions: Blender itself turns it on
  (`blender -b --python-exit-code 3 --python-expr "assert addon_utils.enable(...); save_userpref()"`, no
  `--factory-startup`, which would save factory prefs over the user's). It stays a legacy add-on in
  `%APPDATA%\Blender Foundation\Blender\X.Y\scripts\addons`: as an extension its module would become
  `bl_ext.user_default.monofx_pipeline_blender` and lose its saved preferences and the scripts importing it.
  Every `Program Files\Blender Foundation\Blender X.Y\blender.exe` with X >= 5 (bl_info "blender": (5, 0, 0)).
  `build.ps1` runs the add-on's own build first: that vendors `monofx_pipeline_common` into the add-on folder the
  installer ships, and stamps the suite's VERSION there as `SUITE_VERSION` (git-ignored).
- A release ships only `MonoFXSuite_Setup.exe` (the user's call, 2026-11-19): the add-on ZIP is no longer published,
  the Setup installs Blender too. The add-on's Check for Updates (`addon_updater`, logic in bpy-free `suite_updates`)
  compares the installed suite's version (the add-on folder's `SUITE_VERSION`, else the installer's VERSION for Monos
  under `%LOCALAPPDATA%`) with the latest release tag and offers Download MonoFX Setup, which fetches the installer and
  starts it (close Blender, then finish it). `bl_info`'s version no longer decides: releases never moved it, so the
  old ZIP updater always said up to date (0.9.146 from v0.1.35 to v0.1.37).

## Blender add-on USD publish (`tools/fx/monofx_pipeline_blender/`)

- Model publish leaves materials where Blender 5.2 writes them, `/_materials` at the stage root (the user's
  decision, 2026-11-17): a move into `/<defaultPrim>/material` shipped in v0.1.26-v0.1.27 and was taken out.
  Whoever wants materials inside the root prim adds the root prim in Blender and exports as usual.
- After `wm.usd_export`, `transform.usd_export` stamps the scene fps (`usd_stage_fps.stamp_fps`: a static
  export keeps 24, and a Houdini Sublayer LOP copies it over the hip's fps; Blender 5.2 authors no fps at 24, so the
  stamp checks `HasTimeCodesPerSecond()` / `HasFramesPerSecond()`, never the value alone, which reads USD's fallback 24) and, for a model publish
  (`asset_kind="component"` from `_run_usd_export`), marks the default prim `kind = component`
  (`usd_asset_kind`; not over a kind already there, not above a grouping kind). Neither ever fails the export.
  Both open the file with `Sdf.Layer.FindOrOpen` + `Reload(force=True)`: a layer still open in the session
  is the one from before the export, and a plain `Reload()` skips a file rewritten in the same second.
  Their tests need pxr: run them with hython (pytest skips them).
- Publish file names (`publish_paths.collection_publish_usd_basename`): one collection -> the plain
  `<asset>_<task>_publish.usd`; several -> the collection name after `publish`, words joined with a
  capital each (`char_Helen_uv_publish_GeoHelen.usd`).
- Version mode File (default for new scenes): the publish version is the open work file's `_vNNN`.
- Anim USD caches points only by default (subdivision scheme: next note); per-frame normals cost
  ~5x the file size (Helen 313 MB -> 1.53 GB). The confirm dialog's Include row (and the settings) turns on
  UV maps (`anim_usd_export_uvs`: face-varying primvars at default time, the render-active map named `st`,
  `uv_primvar_names`) and normals (`anim_usd_export_normals`: face-varying, per frame, through the same
  `PointSampleFilter`); both off unless the artist picks them (the user's call, 2026-11-19). Model publish has
  the same Include row (`export_uvmaps` / `export_normals`), both on by default (the user's call). Static meshes and transforms keep only first/last samples
  (`PointSampleFilter`); a layer with one top-level prim sets it as `defaultPrim`.
- Every anim USD mesh authors `subdivisionScheme` (USD's fallback is catmullClark: Houdini GL subdivided
  sh025 to >45 GB). Rule (`anim_usd_cache_subdiv`, Blender's `wm.usd_export` BEST_MATCH, which model
  publishes already use and which writes the scheme on every mesh): a render-enabled Subdivision Surface
  ending the stack -> `catmullClark`, else `none` (Multires too). The cache evaluates the viewport
  depsgraph, so that Subdivision is switched off in the viewport for the export (cage points, no double
  subdivision) and back on in `_restore_frame`; if it cannot be switched off the points stay subdivided
  and the scheme is `none`. Check in Blender: `tests/blender/accept_anim_usd_subdiv.py`.
- `draw()` never writes scene properties (Blender 5.2 raises "Writing to ID classes in this context is not
  allowed"): `_summarize_publish_plan(..., sync=False)` from draw, sync only in `invoke`.

## Test in Houdini / Test in Blender (add-on `publish_check_launch.py` + `publish_check_ops.py`; Houdini `apps/houdini/publish_preview.py`)

- The user's picks (2026-11-19): a NEW process every time: never a running Houdini, and Test in Blender opens a new
  Blender file in its own process (the open work file is never touched). The Model / Anim publish panels draw one row,
  `Test in | Houdini | Blender | menu` ("Test in" once as a label: "Test in Houdini..." on each button was cut
  off in the sidebar, the user's report 2026-11-19): what this scene just published (a WindowManager value, not in the file,
  shown only while it lies under the scene's publish root), else each button picks a version on disk; the menu picks
  another version for either.
- The add-on only starts `houdini.exe -foreground houdini_test_startup.py` (newest `Program Files/Side Effects
  Software/Houdini X.Y.Z`, or the prefs' Houdini path) or `blender.exe --python blender_test_startup.py` (this
  Blender's binary, no `--factory-startup`: the artist's prefs and add-ons come along), both files in the add-on
  folder and never imported by it, with `MONOFX_TEST_KIND` (model / anim) and `MONOFX_TEST_PATH` (a model file, an
  anim version folder): houdini.exe passes no arguments to a script. `MONOFX_TEST_REPORT` also writes the result as
  JSON (automation). For Houdini, `MONOFX_TEST_SUITE` (a checkout) is tried first, then Houdini's MonoFX package, then
  `MONOFX_SUITE`; an older suite without `publish_preview` says to run the Setup. No module of the add-on ends in
  `_test.py` (pytest collects those).
- Houdini builds /stage as lighting reads it (`tools/fx/anim_loader/publish_preview.plan`): a `03_uv` model publish ->
  a MonoFX Loader on Source Asset at that version and file, with the newest lookdev unless the lookdev defines its own
  meshes (then the UV publish alone); a shot's `01_anim` version -> `load_shot` + `apply_timeline`; anything else ->
  a plain Sublayer. A Houdini without the loader type gets the suite's own `otls/monofx_loader.hdalc`. Blender:
  `read_homefile(use_empty=True)`, then `wm.usd_import` of the model file or every geo / camera file of the version
  (publish_meta.json order) with its fps and range; both run from timers, so under a window override (usd_import's
  poll fails without a window). Blender adds one check: it imported as many meshes as each file holds.
- The checks are one module for both, `monofx_pipeline_common.publish_checks` (Houdini has it on PYTHONPATH, the add-on
  from the checkout or `vendor/`): loader / import errors, broken material bindings, meshes without an authored
  `subdivisionScheme`, fps not authored or not the same, the model's default prim not `kind = component`, anim files
  without time samples (read from each publish file, not the loaded stage: the loader writes a scheme on every mesh).
  Houdini adds, for a shot, each loader's lookdev on its anim (`publish_checks.lookdev_facts`, by path under the
  instance prim): a lookdev that binds none of the anim's meshes or adds meshes of its own is a problem (instances
  with the same finding make one). char_Mermaid V001 is made on the texturing geo (`/Mermaid_h`, cm): on sh011 v003
  it gave /Geo no material and three static Mermaids at the origin while the line read clean; Blender, which imports
  only the anim files, never shows that.
  One line on the status bar (never a dialog); the full list in a sticky note in /stage or the text block "MonoFX
  test". Houdini's hip is named into `%TEMP%/MonoFX/houdini_test`; the Blender file stays unsaved (process in
  `%TEMP%/MonoFX/blender_test`). Neither is ever saved in the project (Monos would take it for a work file).
- Checks: `tests/test_publish_check_launch.py`; hython `tests/houdini/anim_loader/accept_publish_preview.py <out>` (fake
  project + two UV publishes, 18 checks).

## Blender add-on tab and rig publish (`department.py`, `rig_publish.py`)

- The MonoFX tab shows one department's panel (the user's pick, 2026-11-19: the tab held too much):
  Auto reads it from the .blend's folder (`publish_paths.department_from_scene`: `NN_modelling` Model,
  `NN_rigging` Rig, `NN_anim` Anim), the Scene panel's switch picks another. The pick is a WindowManager
  property: not saved in the file, back to Auto in a new session. No department in the path -> Model and Anim.
  Model / Rig / Anim are sub-panels of Scene (`bl_parent_id = "MONOFX_PT_scene"`): as panels of their own,
  showing one and hiding another reordered the tab (partly by the order saved in the file), Scene jumped
  above / below, and the switch moved from under the cursor, so a click (or Blender's drag over enum buttons)
  landed on another department (the user's report, 2026-11-19).
  One row, no hint line: `Auto (Rig) | Model | Rig | Anim` (`prop_enum` with the found department in Auto's text).
  The add-on version shows on the Scene panel's header only. Save Version's last message is stored in the scene,
  so it shows only while it names the open file (`_report_is_for_open_file`: v004 showed "Saved ..._v002").
- Rig publish (the user's pick: a cleaned .blend): `<asset>/02_rigging/<NN_task>/publish/vNNN/<asset>_rig_publish.blend`,
  next version, the folder and name Anim > Link scans (`rig_library`: `_rig_` and `_publish` in the stem). The
  work file must hold exactly one publish collection (`is_publish_collection_name`: `_publish` or `-publish`,
  e.g. `CHAR_ATA_RIG_PUBLISH`) with an armature; Link links that collection. The session is saved as a copy
  (`.partial`, not scanned) in the version folder so relative paths stay right, then `blender -b --factory-startup`
  keeps only that collection in the scene, drops other scenes, purges orphans (custom shapes stay: bones use them),
  makes paths relative and saves the final name without `.blend1`. The open file is never changed; a failure
  removes what it made. Before this, riggers saved publishes by hand (char_Ata v001-v005).

## MONO Grooming (Houdini, `tools/fx/grooming/` + `apps/houdini/grooming_adapter.py`)

- Notes live in `tools/fx/grooming/CLAUDE.md`, the contract in `docs/plans/grooming_v0_1.md`. Read both
  before working on the grooming tool, its adapter, its HDA build or the `grooming-check` skill, and add
  new grooming notes there, not here.

## Mono Anim Loader 2.2 (Houdini, `tools/fx/anim_loader/` + `apps/houdini/anim_loader_adapter.py`)

- Spec and decisions: `docs/plans/anim_loader_v2_2.md` (spikes S1/S2 in its section 6); plan
  `docs/plans/anim_loader_v2_2_plan.md`. LOP HDA `mono_anim_loader::2.2` built by `tools/fx/anim_loader/build_hda.py`
  into `otls/mono_anim_loader.hdalc`; its PythonModule only imports the adapter. 2.1 (Dropbox library) keeps working;
  the manager's Upgrade changes a 2.1 node to 2.2 keeping its parms (2.1 parm names are kept where the meaning is the same).
- One node = one instance of an asset in a shot (or the camera). The instance is grafted (Graft Stages,
  `primpath=/<instance>`, `destpath=""`: `"/"` nests the input node's name) on input 0, which passes through:
  `/char_Helen/Geo/...`, clones `/char_Helen_inst02/...` (the user's convention: a Null named after the asset).
  Every anim publish has the root `/Geo`, so instances never share one stage before the graft. Camera: no graft.
- Clones are `geo_<asset>_instNN.usd` (Blender add-on, branch `claude/blender-clone-inst-meta`); `_2` was the
  old suffix and clashes with assets named with a number (`prop_CoralSet_001`). `publish_meta.json` gives
  `asset` / `instance`; without them the loader guesses (`logic.resolve_instance`) and says "asset?" instead of
  guessing between two assets. Groom / cloth come from the grooming department's per-frame caches
  `02_fx/{groom,cloth}/publish/vNNN/<instance folder>/<shot>_{groom,cloth}.####.usd`, only from the instance's
  own folder, never another's.
- Versions on the node are explicit `vNNN`; nothing moves by itself (newest picked once at creation; the status
  and the manager say what is newer). "missing" = the version on the node is gone; "none" = never published.
- Groom / cloth with time samples load as value clips authored AFTER the graft on a new layer (Configure Layer
  `startnewlayer` + Python LOP, no manifest): Graft Stages flattens its branch into one layer, where the first
  frame's samples beat a clip, and a same-layer anim beats a cloth clip. That gives motion blur; a cache without
  time samples falls back to Sublayer `$F` (no blur, said on the node).
- The branch's time codes per second are the anim / geometry file's (the last `mx_layer_N` set), by the Configure
  Layer `branch_fps` after `branch_layers` (a Python expression with hou + pxr only, so bakes keep it). A Sublayer LOP
  takes its strongest layer's, the lookdev's: veh_Spaceship lookdev V001 authors none (USD's fallback 24), so sh002
  v004's 30 fps anim came out on 0-24 against a camera on 0-30. Check: hython
  `tests/houdini/anim_loader/accept_branch_fps.py <fake_project> <out>` (fails with v0.1.43's HDA).
- The node is **MonoFX Loader**, type `monofx::loader::1.0` in `otls/monofx_loader.hdalc` (the user's call, 2026-11-17:
  it must not read "anim loader"; Tab > MonoFX names it `monofx_loader`). `build_hda.py` with no argument builds it
  and the same node as `mono_anim_loader::2.2` (`otls/mono_anim_loader.hdalc`) so scenes saved with 2.2 open; the
  root `OPcustomize` hides 2.2 from Tab (installer ships it). The manager's Upgrade moves 2.2 nodes over with
  `changeNodeType` (same parms). `find_loaders` reads every instance of the loader types, so loaders inside a LOP
  network in /obj (grooming scenes: `/obj/Character_Loader`) show in the manager; opened from a node, Load shot
  builds in that node's network.
- Source Asset parm pane: Asset Type (`mx_asset_group`, a folder of `01_assets`, "All") shortens the Asset menu,
  which then lists only assets with a UV publish; Advanced shows Model Path (Anim Path hides). A part with nothing
  published reads "none published", not Houdini's "(no entries)".
- Manager layout A (the user's pick, 2026-11-17, mockups in the module docstring): "+ Add" = Load shot (versions)
  and Add assets... (a drawer: type chips, search, thumbnails, pick several, Add N); a view bar (Viewport menu of
  explicit actions: solo the selected / show all through Houdini's Solo Geometry, view state; show or hide lookdev /
  groom in the viewport on every loader, one undo step; draw hulls only; what the viewport shows now in words, with
  Show all while soloed; Filter); the status line adds the shot's outputs the scene lacks (Add it) and the textures
  the lookdevs pull; the inspector is information only (Monos rules, reviewed 2026-11-17 with the monos-qml-ui skill):
  source, what is new in a newer version (date, Monos work file author from `.monos/authors.json` of the same vNNN,
  outputs, frames, meshes, size); its actions are on the row's right-click menu (Update to <part> <version>, Switch to
  Source Shot / Asset, Open folder, Open in Monos `monos://open?project&page&e=sha256[:10]`, Frame in the viewport).
  The list is a table: a sticky column header, group bands, zebra rows, column separators, every column but the
  name centred, Textures a column of its own (the user's asks). The top bar's icon buttons (viewport, list / grid, add) are flat
  (`STYLE_ICON_FLAT`, 28 px, no border): a solid fill only on hover, press and the view that is on. Every button has pressed and selected + hover looks
  (Monos states). Fewer words (the user's ask): the top bar is icons (Filter with a search icon, eye = Viewport
  menu, list / grid, plus = Add menu), the view bar row is gone (the viewport state sits on the status line), Hand
  off / Undo / Upgrade are icons (Upgrade with its count), each icon button has a tooltip and an accessible name;
  only the primary keeps words. The inspector is a full-height column from the window's top to the action bar.
  A rounded control's border is 2 px at least and follows the UI scale (`scale_css`): Qt does not anti-alias a
  stylesheet border, and 1 px broke on the corners; dividers stay hairlines. Viewers are found inside Houdini 22's
  ContextViewer too (`scene_viewers`). Hand off... writes `<instance>_handoff/<instance>.usd` (the loader's stage flattened, textures copied,
  relative paths) for people without MonoFX.
- Where new loaders go: a network with the shot layout (`merge_actors`, `merge_cameras`, `merge_environments`,
  skill solaris-shot-stage-layout) gets them wired there (Load shot: geo -> actors, camera -> cameras; Add: characters
  -> actors, the rest -> environments); any other network gets `<shot>_merge` / `assets_merge`. Adding an asset
  already in the network makes another instance, prim `<asset>_inst02` (set dressing places one asset many times).
- Bake to plain nodes (Hand off menu, row menu; `bake_loaders`): a MonoFX Loader becomes a plain subnet in place
  that anyone with Houdini opens: the loader's inner network copied in, its parms as spare parms without callbacks
  or menu scripts, the subdivision Python LOP holding its plan as data (`BAKED_SUBD_CODE`, no `apps.` import). The
  subnet keeps the loader's values and user data `monofx_baked_loader`, so the one Upgrade restores the loader
  (edits made inside are lost). Unlocking the HDA was not enough: its Python LOPs import the adapter and its parms
  call `hou.phm()`. sh025: 4 loaders baked, 50 meshes and 7 curves the same.
- Sublayer / Reference LOPs that read a publish (`find_publish_layers`, `logic.parse_publish_path`: an absolute path
  `<project>/01_assets/_<group>/<asset>/<dept>/publish/vNNN/<file>` or `02_shots/<shot>/...`; a path with a
  variable or an expression is not read) show in the manager's "sublayers" group with their status. Update moves
  the vNNN in the path to the newest version holding the file (a vNNN in the file name follows). Upgrade (the same
  action as for old loaders, one button and one menu item: Convert and Upgrade confused the user) makes a
  MonoFX Loader on Source Asset in its place (same name, place, wires; lookdev or model at the version it read,
  groom and hide off): the loader puts the asset under /<prim>, so prim patterns of the nodes after it up to the
  first merge / graft move there, and `lopinputprims('.', 0)` (the env scene's xforms) becomes the explicit list of
  the layer's root prims under /<prim> (a group-level move acts in another frame); other parms naming those prims
  are listed, not changed. Checked on env_Envi lookdev v005: its 10 sublayers converted, 1040 meshes, 1040
  bindings, identical bounds.
- Manager details (the user's asks, 2026-11-17): the list never drops a column, it scrolls sideways (the column header
  follows the scroll); the inspector slides in 160 ms OutCubic / out 120 ms InCubic (Monos motion) beside the list,
  just shows when stacked; it is a real slide: `_SlideClip` keeps the panel at full width while its clip widens from
  the right edge (no reflow); the Geo column is a shot's anim or an asset's model; the result line is two lines at most, details in its tooltip (`Controller.details`);
  double-click selects the node and frames it in the Network Editor; menus are square (`STYLE_MENU_SQ`) with
  separators between groups; a Source Asset whose lookdev holds the geometry reads "–" for its model (scan).
- The inspector's meshes table runs edge to edge, its name column fills what the others leave (wider only when
  dragged), its scroll bars are thin and inside it, shown when needed (the user's ask). Houdini 22's style paints a
  tree's rows and branch area grey (#303030 / #3a3a3a) whatever its palette or alternate-background-color says, a
  `::item` background beats an item's own and an almost transparent one wiped what was under it; offscreen grabs
  show none of it. So `_MeshDelegate` paints every cell (row colour, hover, lines, elided text) like the main list,
  `_MeshTree` the branch area and the group chevron, and no `::item` rule is left. Check a tree's colours in the live
  window (sample its pixels), not offscreen. The table shows every level of the hierarchy (Geo > Base_grp >
  Body_grp > Geo_Body, as the scene graph does); a group sums its meshes. The name column's width is kept only
  when the artist drags it (mouse down), never from Qt's own resizes.
  One background for every row (the user's "too many colours", 2026-11-17): no zebra, no band per group level; a
  group reads as one by its quieter text and chevron, a selected row by the selection colour.
- Inspector layout B (the user's pick of three mockups, 2026-11-17), then its toggles (the user's ask the same day):
  each prim row has three toggles first, before its name (narrow, no lines between them; the tree's branches stay
  in the name column, `setTreePosition(0)`), as Blender's outliner: the eye (visibility), viewport and
  render (purpose: both on default, viewport only proxy, render only render, both off guide). Inheritance is
  Houdini's / USD's: hiding a prim hides everything under it and each child keeps its own eye for when the parent
  shows again (drawn dimmed meanwhile); a prim without its own purpose follows its parent. One look per state (the
  user's report: blue and white for one state read as two): a dot under the icon marks the shot's override, what
  Remove the shot's overrides takes off (not the publish's or the loader's own values: a dot that stayed after a
  Remove read as a bug); who set a value (this shot, the publish, the loader's Hide Prims / Show in Viewport) is in
  the tooltip. A toggle that is on draws filled (`_filled_pixmap`: the pupil / lens cut out so any row colour shows
  through), off is the outline with its slash; 13 px icons in 21 px columns. A click toggles that row, or the selection it is part of, to the clicked row's new value, keeps the
  selection, one undo step; every click changes the state (`logic.toggle_edits`: the rule comes off only when the
  wanted value is the one the row has without it, `PrimShow.base_visible` / `base_purpose`; taking it off whenever
  the value was "on" left a prim the loader hides hidden, two clicks to show it). A toggle re-reads only that loader
  (`Controller.refresh_detail`, `_run_detail`): a full refresh after each click walked the Dropbox project again
  (~10,000 stat calls, ~1 s on env_Envi, the user's report of a slow, stuck window); now 0.13-0.23 s on Cliff04's
  780 rows.
- Inspector with several loaders selected (the user's ask): one tree, a branch per loader (`show_rows`, the loader's
  own row has the pattern "**" = all its prims, and the toggles of the instance's root prim /<instance>: a show rule
  on `logic.ROOT` ".", which every prim under it inherits; hiding it hides the asset); every row carries its loader (`ROLE_LOADER`), so toggles, the
  menu's subdivision / dicing / Remove act on each row's own loader, and a toggle over several loaders is one undo
  step (`set_show_many`); Same overrides only for one loader. A filter field above the tree (`_apply_filter`) keeps
  the rows whose name holds the text, everything under a matching group, and the groups above (opened).
  Right-click the tree's header: which columns show (the toggles, Faces, From, Scheme, Dice; the name always),
  remembered per viewer in the prefs (`inspector_hidden_columns`; Faces and From off until picked, the user's ask); Dice still shows only when some prim has dicing. The header shows no icons
  (the user's ask); the right-click menu's Display submenu says each toggle as a verb (Hide / Show, Stop drawing
  in the viewport, Stop rendering) and runs the same toggle. Rules live in the hidden
  `mx_show_rules` (JSON {pattern = one prim under the instance, "vis": invisible | inherited, "purpose"}; the first
  form {"show": ...} still reads), authored by the HDA's `show_rules` Python LOP after Hide Prims
  (`adapter.author_show`; no MakeVisible: hiding prunes, the user's rule), so a rule wins over Hide Prims and the
  groom's render purpose; bake writes them as data (`BAKED_SHOW_CODE`). The panel's state comes from the files on
  the worker thread (`shown_for`, `logic.prim_shows`: publish visibility / purpose, Hide Prims, Show in Viewport,
  rules), checked against the stage with hython on sh025. The groom's curves are rows under Groom
  (`groom_curve_counts`, first frame of a cache; not `groom_curves`, the cache's own paths that refresh uses: a second
  function of that name broke every groom loader). Remove the shot's overrides clears subdivision and show rules;
  Same overrides copies both; a change keeps the table's scroll, selection and folds. A camera has "On the loader":
  clipping, aperture, ratio, guide scale as parm fields (Enter sets the parm, one undo step).
- Camera aperture (2026-11-22, `config.P_CAM_APERTURE`, the `cam_aperture` Python LOP): the loader keeps the publish's
  aperture by default. Blender's `wm.usd_export` writes the camera's real sensor (sh011: 20.955 x 11.787 mm, 16:9,
  as `sh011_anim_v003.blend` has it; sh025: 36 x 20.25), so nothing is forced. Up to v0.1.44 `camera_edit` set the
  width alone (Horizontal Aperture, 36 mm by default) and left the height: sh011 came out 36 x 11.787 (3.05:1). The
  Aperture menu can set a width in mm with the height from the publish camera's own ratio (never a hard-coded 16:9),
  or a width and Aspect Ratio. Only the cameras of the loader's file are edited, never input 0's. `cam_aperture`
  sits before `camera_edit`: `cam_x100` scales its input's last modified prims, which a Python LOP does not set.
  `camera_edit` sets clipping and guide scale only. The inspector shows Aperture / Ratio only in a mode that uses
  them. Check: hython `tests/houdini/anim_loader/accept_camera_aperture.py <out>`.
- The HDA's PythonModule is `from apps.houdini.anim_loader_adapter import *`, which takes only `__all__`: every
  `hou.phm().<name>` in `build_hda.py` must be in it (v0.1.36's Reload button raised AttributeError, cb_reload was
  missing; `tests/test_anim_loader_hda_callbacks.py` checks it). A button is tested by `parm.pressButton()` in hython,
  not by calling the adapter's function.
- Selection follows between the Scene Viewer and the inspector tree (the user's ask, 2026-11-22): the manager reads
  each LOP viewer's `currentSceneGraphSelection()` on a timer (`SELECTION_POLL_MS`, no Houdini callback for it;
  `adapter.viewport_prims`) run from Houdini's idle loop (`ui._when_idle`, hdefereval: a read mid-cook fails the
  cook, as Grooming's poll did); the tree's pick sets the viewer's selection with undo off. The viewer draws its network's viewer / display node's stage, not the selected node's
  (the user's case: display on one node, another selected), so only loaders feeding that node take part
  (`adapter.displayed_loaders`), and each loader's root is looked up on that stage (`logic.drawn_roots`, a walk to
  depth 6 cached per cook): the shot layout moves it (sh025: /char_Helen drawn at /World/anim/actors/char_Helen);
  not found, or in more than one place, the loader is left out. env_Envi's sample has the display flag on the
  original set (`mer_lights`), not on `monofx_envi` where the loaders go. A picked prim goes to the loader whose
  drawn root holds it (`logic.prims_by_loader`; Prim Name off: by its top prims) and selects the deepest row at or
  above it (`logic.nearest_row`); prims of other loaders than the selected ones select those loaders in the list
  first. Rows picked in the tree set the viewer's selection in their loader's network (`adapter.select_prims`,
  `logic.row_prim`; prims not on the drawn stage are dropped, a picked loader not drawn is said on the result line);
  a viewer showing another network is left alone. A rebuild of the tree or a sync from the viewport sends nothing
  back (`InspectorPanel._quiet`). View state: no undo step.
- Inspector tree folds (the user's ask, 2026-11-22): Shift+click a group's arrow folds or opens it and every group
  under it, Ctrl+click every group of the tree, to the state the clicked row goes to (`_MeshTree.on_chevron`: the
  last indentation step before the name). A plain click is Qt's own.
- Manager versions (the user's picks, 2026-11-22): the first column is "Anim / Model" (narrow / cards: the row's
  word, `part_word`). A click on a version cell's dropdown arrow (`arrow_rect`, drawn only where the cell shows a
  version or "missing", `has_versions`; the rest of the cell selects as before) opens that part's versions on disk (`logic.version_picks`: newest
  first, `VERSION_PICK_LIMIT` 15, date of the folder, Monos work-file author, greyed when it does not hold this
  instance's file); a pick runs `adapter.set_part_version` (the parm, then the node's own `cb_parm_changed`, one
  undo step). A click on a row that is part of a selection keeps the selection and sets them all. Shift / Ctrl
  clicks still select. ~50 ms on sh025, read on the click.
- The list never switches to its two-line narrow row (`NARROW_ROW_PX` 0): it scrolls sideways (the user's ask).
  Right-click its header: which columns show (`list_hidden_columns` in the prefs). Column menus (`_ToggleMenu`)
  stay open while toggled; a click outside or Esc closes them.
- Inspector tree columns: PRIM fills by default; dragged, it keeps that width (narrower too) and the last column
  shown takes what is left (`_fill_last`, live while dragging); the content columns are Interactive, sized by
  `_fit_name`.
- Camera section: Aperture is the node's `mx_cam_aperture` menu (`adapter.cam_mode` / `set_cam_mode`); the line
  under it is the camera's aperture as the loader puts it out (`Controller.camera`), Width shows only in the width
  modes, Ratio only in "Set width and ratio", Focal length read-only.
- Panel size (the user's report, 2026-11-22: big next to Houdini): `open_manager` scales by Houdini's UI scale
  times `PANEL_SIZES` (prefs `panel_size`): "Like Houdini" (default) 12 / 14, since Houdini's text is 12 px at
  scale 1 (18 px measured at 1.5) and the panel's body text was made at 14; Medium is the size before. Picked from
  the list header's right-click menu; the window opens again at the new size.
- Add assets drawer (the user's review, 2026-11-22): the picks live in the drawer (`AddDrawer._picks`), not in
  the grid's selection, so a chip or the search never drops one ("N picked, M hidden by the filter"); Add and a
  drop that lands clear them. Shift+click picks a range from the last clicked card, Clear unpicks all, a
  double-click adds that asset and keeps the drawer open. A drag from an unpicked card carries it alone (Qt picked
  it on the press: unpicked again), from a picked card every pick. `refresh_badges` rewrites the cards' second line
  after each scan, without filling the grid again (scroll and picks stay).
- Manager menus (2026-11-22): + opens Add assets (no menu); the shot crumb's menu starts with Load <shot> and its
  versions, then the shots. The row menu: Update / Switch source / Reload / Retarget, then Select node / Frame /
  Open folder (the clicked column's part first) / Open in Monos, then Asset (only when the loader needs one) and
  Bake; an icon on every item. The version menu has no header band (one only for several loaders), dates without
  this year (`_short_date`), rows at the small size (`STYLE_MENU_COMPACT`). The top bar has a stretch after the
  Filter field: with the crumbs on their own row Qt otherwise spread the icon buttons over the bar.
- Add assets drag (the user's ask, 2026-11-22): a card drag carries `<asset>.monofx_asset` files (JSON root + asset,
  in `%TEMP%/MonoFX/asset_drag`, `logic.write_asset_drags`): Houdini gives a drop only a file list. `drag_drop
  .handle_drop` sends them to `adapter.drop_assets` before anything else (even with drops off: never opened as a
  scene): over a Network Editor of a LOP network, loaders at the cursor (`add_assets(at=...)`); over a Scene Viewer
  showing one, placed as Add places them; the loaders list takes them too. Checked with the hook called in Houdini
  (loader at the cursor, one undo step); a real mouse drag from the drawer into Houdini's panes is not yet checked.
- Hide Prims is off the parm pane (the user's ask, 2026-11-19): `mx_hide_enable` / `mx_hide_pattern` stay as hidden
  parms, so the hair driver is still hidden by default and scenes keep what they had; the inspector's eye shows it.
  Configure Primitive authors that visibility as a time sample at the current frame (its toggle is an expression):
  read it at a frame, `ComputeVisibility(Usd.TimeCode(f))`; at the default time it reads inherited.
- Publish folders per part (the user's ask, 2026-11-20; `logic.part_folders`): the folder of the version on the node
  (groom / cloth: the instance's own folder in it), the part's publish folder when that version is not on disk or
  none is picked. Manager: a right-click on a Geo / Lookdev / Groom / Cloth cell puts "Open <part> publish folder"
  first (`_ListDelegate.part_at`), and Open folder is a submenu of every part. Node: the Open Folder strip
  (`mx_open_folder`, Geo | Lookdev | Groom | Cloth) under Manager / Refresh / Reload; a StringToggle strip set back
  to 0 by `cb_open_folder`, since a Normal strip does not call back when the same button is clicked again.
- Shot crumb: a saved scene in the project that is no shot's (an asset's lookdev) starts on no shot ("Pick a shot");
  it showed the project's first shot (sh001 in char_Mermaid's lookdev). An unsaved scene still falls back to it.
- The manager refreshes itself: a Refresh icon in the top bar, F5, and coming back to the window (at most every 3 s,
  `REFRESH_ON_FOCUS_S`). Before, it read the scene only on open and after its own actions.
- The headline counts loaders with a part missing on disk ("1 missing"); it read "All up to date" over a red cell.
- Add puts its nodes beside the selected node of the network, else in the middle of the Network Editor's view of it
  (the user's pick, 2026-11-20; `_add_anchor`, `logic.free_spots`: a column moved right past nodes already there),
  then selects them; the result line says where. Houdini's `moveToGoodPosition` put them under every node (y -20 in
  char_Mermaid's lookdev), out of sight. Without a UI (hython) it still falls back to that.
- Upgrade turns a publish Sublayer into a loader only when the loader reads that publish (`PublishRef.loader_reads`:
  an asset's `01_modelling/03_uv` or lookdev). A texturing geo (`03_surfacing/02_texturing`) was made into a loader
  that looked for it in 03_uv ("missing", char_Mermaid_texturing_geo); it now stays a Sublayer, its row says why.
- Prim Name on / off (`mx_use_prim`, the user's ask 2026-11-20): on grafts under /<Prim Name>, off grafts at "/"
  (Graft Stages `primpath="/"`), so the publish's own root prims stay (/Geo, /_materials, /Groom) and the graft still
  flattens the branch (clips and `groom_unanimate` unchanged). Set when a loader is made: off for Source Asset
  (`on_created` in an asset scene, Add assets' first instance; a second instance is on, /<asset>_inst02), on for a shot
  and wherever nodes after the loader expect /<prim> (load_shot, Upgrade of a Sublayer or Character Loader, restoring
  a bake). Switching Source never changes it: the mesh paths stay what the nodes after it name. Hand off with it off
  writes the top prims at their own paths (default prim Geo). The parm's default is on, so
  scenes saved before it keep their graft. Every Python LOP starts with `config.ROOT_CODE` (`root`, `instance_prims`);
  the adapter has `instance_root` / `instance_paths`. Off: the top prims are the branch's own root prims, read from
  the inner `groom_topology` (input 0's prims pass through), Uniform Scale goes on the branch before the graft
  (`branch_scale`), and the "." show rule acts on each top prim.
- Reload from disk (the user's ask, 2026-11-19): the node's Reload button (beside Refresh) and the manager's row menu
  re-read every file a loader uses (`adapter.files_of`: main file, lookdev with its sublayers, every frame of groom /
  cloth, sublayer slots, groom topology; `logic.loader_files`) for a publish written again into the same version,
  then press the inner Sublayer LOPs' own `reload`: `hou.lop.reloadLayer` re-read the file and the inner Sublayer
  showed it, but the graft's flattened copy stayed old and `cook(force=True)` on the HDA does not cook its
  children. Versions never move. On Windows a file USD has open (a crate is memory-mapped) cannot be overwritten in
  place, but one written elsewhere and renamed over can (USD's export, so Blender's publish); checked with hython
  (`assemble/reload_check.py`: points +100 shown only after Reload).
- hython: `hou.hda.installFile` goes into the open hip's library list, which `hipFile.load` replaces: install
  after the load (and `setIsPreferred`) or the scene runs the installed MonoFX's loader, or no loader at all.
  Each row starts with its prim type's icon from Houdini's Scene Graph Tree (`SCENEGRAPH_primtype_xform` for a group,
  `_mesh` for a mesh; `_prim_icon`, Lucide outside Houdini); groups are drawn as Xforms, their real type is not read.
  The meshes' right-click menu (the user's "cryptic", 2026-11-17): verbs (Use the publish's subdivision, Turn
  subdivision off, Subdivide (Catmull-Clark), Remove the shot's overrides, Copy these overrides to every <asset>), an
  icon on every row and no checkable actions (their check column pushed rows in): the current choice shows a check icon.
  Dicing is a submenu of steps (publish's, 0.25 to 4), not a field. A submenu is made as `QMenu(title, menu)`:
  `addMenu(icon, title)`'s submenu was deleted with its Python wrapper.
  Its first row is what it acts on, a band (`_menu_head`: lighter background, firm line under it, the name at the
  items' size, regular, italic, in the label colour: bold and bright stood out too much), not a greyed-out item. "Same subdivision on the other N <asset> loaders" (`subd_to_asset`: this loader's whole rule set onto the
  asset's other loaders) shows only when the scene has other loaders of that asset.
- Inspector of a shot loader (the user's ask, 2026-11-17): Frames and Fps from the anim publish's `publish_meta.json`
  (`Controller.timeline`; an asset loader has none). A camera adds its lens from the loader's stage at the current
  frame (`adapter.camera_info`): USD lens values are tenths of a scene unit (sh025, 1 m a unit: 35 mm is 0.35), so
  they are turned into mm, distances into m; f-stop 0 is USD's "no depth of field" and reads "Depth of field off".
- No "·"-joined facts anywhere in the manager (the user's dislike, 2026-11-17): the inspector is a property list
  (`_Props`: label left, value right) of Node, Kind, Shot / Asset, each part's version, Textures, Subdivision,
  Viewport polygons; a NEWER VERSION section lists the part and version ("V001, first version"), Published, Work
  file by, and only real changes (outputs added / removed, frames, fps, meshes added / removed; never a file size).
  Both sections fold from their titles (`_Section`, view state kept per viewer in the prefs as
  `inspector_details` / `inspector_news`). The list's side margins are 6 px (`LIST_PAD`).
- Manager type: bold only for the inspector's name, the shot crumb and the primary; list names, headers, bands and
  the status line are regular (the user's ask). Icons are drawn for every device-pixel ratio (`_crisp_icon`):
  scaling a small pixmap up broke the search icon; icon-only buttons centre their icon.
- Props and environments publish a complete asset as their lookdev (`def` meshes and materials, root prims at the
  top, e.g. prop_Cliff01: 12 meshes), the UV publish being another mesh (`_uv_publish_Low` / `_zHigh`). Source Asset
  loads such a lookdev alone (`lookdev_defines_geometry`), never with the UV publish (that doubled the geometry);
  subdivision and the inspector's table read its meshes from that lookdev too (`geometry_file`; read from the model,
  Cliff01's 12 meshes were listed as none and none got a scheme);
  Helen's lookdev only overrides, so her UV model stays under it. Checked on env_Envi lookdev v005: its 14
  hand-placed props rebuilt with loaders + the same xform nodes give the same 1040 meshes and the same bounds.
- A locked LOP HDA makes its inner nodes on first cook: `node.children()` is empty before.
- Source Asset (the user's decisions, 2026-11-17; design `docs/plans/anim_loader_asset_source.md`): the node (label
  **MonoFX Loader**, type still `mono_anim_loader::2.2`) loads either a shot's anim (`mx_source` shot) or the asset's
  own publishes (asset): UV model `01_modelling/03_uv/publish/vNNN/` (Model File menu, the standard
  `<asset>_uv_publish.usd*` first; several files and none standard -> the artist picks), groom
  `04_grooming/publish`, lookdev. Both graft under `/<asset>`, so mesh paths match (Helen: all 26) and subdivision
  rules carry over; switching Source keeps the other's parms. A scene in an asset folder (`logic.detect_asset`)
  gets Source Asset on creation. Load shot / Retarget leave Asset nodes alone (`_key` is empty). Upgrade turns a
  Character Loader 3.2 (Dropbox HDA) into an Asset node in its place (`logic.from_character_loader`; its SOP Modify
  is dropped, the user's call).
- Groom sits outside Geo in both sources, at `/<instance>/Groom/<name>`: Helen's lookdev binds hair there
  (`/Groom/Hair_Back` -> `M_Grm_Hair_Back`, empty BasisCurves of those names). The asset's groom publish is already
  at `/Groom`. A shot groom cache is moved there by name (`logic.groom_targets`): the branch's `groom_topology`
  Python LOP copies each curves prim from the first frame (or each frame's file without time samples, `$F` in
  `mx_groom_topo`), and the clips after the graft read the cache's own path (clip `primPath`, tokens `src=dst` in
  `mx_groom_roots`); spike S3 checked blur and binding. With clips (a cache with time samples) nothing under the clips may hold an animated value: a Merge or a
  Graft Stages after the loader puts the loader's layers and the clip metadata into one, where a time sample (or a
  default) beats the clip. Two sources: `groom_topology`'s copy of the first frame, which takes its own animated values
  off, and the lookdev (Helen's holds points and primvars on /Groom/<name> with one sample, widths as a default):
  sh025_lighting_v004's groom stood still at the lookdev's value from merge_actors on, with the lookdev's 1,884,595
  points against the cache's 1,935,433-point topology. So `groom_unanimate`, a Python LOP right after the graft, on the
  graft's own flattened layer, erases every time sample on the groom prims and the default of each attribute the cache
  animates; an attribute the cache lacks keeps its value as a default (a lookdev-only primvar). Measured: a value block
  from a stronger layer does not do it, in one layer it beats the clip too and the groom lost its points; a default in a
  stronger layer beats a clip as well. Check: hython `tests/houdini/anim_loader/accept_groom_graft.py` (a time-sampled
  copy of the fake project, its lookdev given samples on the groom, through Merge and Graft; fails with v0.1.36's HDA).
  `groom_unanimate` also erases the groom's `extent` with clips or a `$F` sublayer (2026-11-22): Helen's lookdev V009
  authors its rest-pose extent on /Groom/<name> (near the origin) and the cache authors none, so the bounds stayed
  there while the points moved with the body at (82, 31, 327); a camera framed on the bounds saw sky. Without an
  extent USD and Hydra compute bounds from the points. A `$F` cache that authors its own extent keeps it. The same
  check covers it (a rest extent in the fake lookdev; fails with the HDA before this).
- Subdivision per mesh (the user's decision, 2026-11-17; `logic.subd_plan`, `adapter.author_subd` from the
  `render_only` Python LOP): a shot rule on the loader (hidden `mx_subd_rules`, JSON `pattern` from `/<instance>`,
  `scheme` publish / none / catmullClark, `dicing`; a later rule wins) > lookdev publish > anim publish > `none`.
  Never USD's fallback `catmullClark`: it made Houdini GL subdivide whole shots (sh025 v005 past 45 GB, crash in
  `GR_OSDSubdSurfaceVK`; Helen alone 12.5 GB with a plain Sublayer, 2.5 GB with `none`). Opinions are read from
  the publish files themselves with `TraverseAll` (lookdev holds overs): Graft Stages flattens and writes the
  fallback as a value. Dicing is `primvars:karma:object:dicingquality` (render only).
- Groom curves per shot (the user's pick of three mockups, layout A, 2026-11-22; `logic.curve_plan`,
  `adapter.author_curves` from the same `render_only` Python LOP): BasisCurves have no subdivisionScheme or dicing, so
  a shot sets on each curves prim its Curve shape (the prim's own type / basis / wrap, see below; Bezier left out: it
  needs 4 + 3N CVs and Helen's 9 / 33-CV strands break it; cubic needs 4 CVs, the menu greys it below that) and two
  Karma primvars, constant: `width_scale` (float, x the published widths) and `curve_style` (0 flat, 1 rounded =
  Karma's default, 2 oriented; Karma XPU renders rounded only, Karma CPU no oriented linear curves). The cache's
  points / widths (value clips) are left alone; the clips carry none of these, so a default beats nothing (sh025:
  values reach `beauty_pass`, points keep 46 samples). Rules: hidden
  `mx_curve_rules`, JSON `pattern` (as subdivision) + `basis` / `width` / `style`, a later rule wins field by field
  (`set_curve_rules`: KEEP keeps a field, None takes it off, an empty rule goes). What the publish says: the groom
  file's type / basis (`groom_curve_facts`, first frame) under the lookdev's (`lookdev_curve_opinions`, Karma
  primvars too). The lookdev's curve shape wins (the user's call, 2026-11-22): `groom_topology` copies the cache
  above the lookdev and used to hide it (sh025 rendered Helen linear although V009 says cubic B-spline pinned; Karma
  close-ups showed "as published" = linear), so it now takes type / basis / wrap off its copy wherever the lookdev
  authors them, except a cubic lookdev over a cache with a curve under 4 CVs (Karma drops those). `pinned` matters:
  a non-periodic B-spline starts at (P0 + 4 P1 + P2) / 6, which leaves Helen's Hair_Back roots ~2 cm (max 2.8) off
  the scalp; pinned starts at P0. A shot's Curve shape is the curves' own type / basis / wrap (cubic + pinned for
  B-spline / Catmull-Rom, linear + non-periodic for Linear; `adapter.karma_curve_values`, "token" values), with
  Karma's curve_basis set back to 0: the Karma override smooths but never pins, wrap pinned or not (one-strand husk
  test, Karma CPU and XPU, 2026-11-22). So the viewport shows the shot's shape too.
  Inspector:
  a curves row's SCHEME is its basis, FROM its source, WIDTH (col 8, `COL_WIDTH`, shown only when the tree has curves)
  its scale; the curves rows' menu has Curve shape / Width (Karma) / Render as (Karma CPU). Clear overrides, Same
  overrides on the other loaders and Bake (`BAKED_SUBD_CODE`'s `CURVES`) include them. No viewport thinning: Houdini GL
  has no "draw a fraction of the curves" setting, and a per-frame proxy copy was turned down (the user's call); the
  viewport toggle and the lookdev's proxy meshes keep the viewport light. Check: hython
  `tests/houdini/anim_loader/accept_curve_rules.py <fake_project> <out>` (10 checks); sh025's char_Helen was checked
  the same way and in the GUI (sandbox copy `sh025_curves_041.hiplc`, groom set to v004: it pointed at a v900 not on
  disk). Seeing curves in the viewport (2026-11-22): Houdini 22's VK viewport in **MatCap** shading draws no
  BasisCurves at all, and the stock SolarisLookDev desk opens its viewer in MatCap; the sh025 copies were saved with
  that desk, so Helen looked bald and framing a groom prim missed. Smooth shading (the Solaris desk) draws them, and
  framing /<instance>/Groom lands on the hair. Helen's lookdev also gives every groom curve `purpose = render`: in the
  viewport they show only with each curve row's viewport toggle on (the Groom row's alone does not reach them).
  Viewport check: published shape = smooth arcs, Linear = straight segments, as in Karma. A viewer inside a
  ContextViewer is found by `adapter.scene_viewers`, not `hou.ui.paneTabOfType`; script it with flipbooks.
- Manager › Subdivision column (the user's pick of three mockups, 2026-11-17: beside List / Grid, under them when
  narrower than 760 px): the selected loader's anim meshes by group (`logic.mesh_groups`, first two path levels),
  faces, where the scheme comes from (shot / lookdev / publish / default; on a mesh only when it differs from its
  group), scheme, dicing (column only when some mesh has dicing). The scheme is a menu on each row: on a selected
  row it sets the whole selection, else that row. Dicing has its own field + Set, which keeps each scheme
  (`logic.set_subd_rules`: scheme None / dicing `KEEP` keep that field; one rule per pattern, put last; Publish
  with no dicing drops the override). Clear overrides and Apply to all instances share a row; each change is one
  undo step. The plan is read by `HoudiniBackend.subd`
  on the scan's worker thread; rows carry "subd N · ~X M".
- Heavy shot (over `logic.HEAVY_SUBD_POLYGONS`, faces x 16): a non-modal prompt after Load shot and on scene
  load (HDA OnLoaded, one check per burst, UI only) offers Draw Hulls Only for every viewport; "Don't ask again"
  is a viewer pref. In the manager the warning lives in one place only, the Subdivision column (line + Draw Hulls
  Only link), never in the result line. Draw Hulls Only lowers memory as well (measured on /stage,
  Helen catmullClark: RAM 12.8 -> 7.2 GB once settled, VRAM +6.7 -> +4.9 GB; the first seconds still peak ~15 GB);
  scheme none lowers it most (2.5 GB). It is set only on viewers showing a LOP network (`_stage_viewers`): /stage
  has its own display options, and a value set while the viewer showed /obj never reached it (that, and reading RAM
  at the peak, gave an earlier wrong "does not lower memory").
- Loaders behind (the user's ask, 2026-11-19): on scene load (OnLoaded, `check_outdated`) a second non-modal prompt lists
  the MonoFX Loaders with a newer publish (`logic.outdated`: part, version on the node -> newer; 2.2 / 2.1 nodes are
  Upgrade's, left out), with Open manager and Update N (one undo step). Parms are read on the main thread, publishes on
  a worker thread. It stacks above the heavy-shot prompt (`ui._restack`, bottom right; one moves down when the other
  goes). Its "Don't show again for these versions" is per scene (`outdated_dismissed` in the prefs, keyed by the hip)
  and holds only for the loader/part/version entries it listed (`logic.outdated_signature`): a newer publish shows it
  again, a partly updated scene stays quiet, and a scene with nothing behind drops the dismissal.
- Lookdev and groom have "Show in Viewport" (on by default). Off: bindings move to `material:binding:full` (Karma
  only) and groom curves get purpose `render`.
- Manager layout R-A (the user's pick, 2026-11-17, after the Monos UI rules in `products/monos/monos/docs/`:
  browse first, act second; the inspector is information, shown only for a selection; actions in context; no combo
  box for a one-shot pick). Top bar: title, project crumb (menu: scene's, loaders', recent projects, Browse...), shot
  crumb (menu), List / Grid, Load shot (menu of the shot's versions). A status line (what the primary does, count;
  heavy-shot note + Draw Hulls Only on its right, never the headline or the primary). List = a table, 40 px rows,
  Anim / Lookdev / Groom / Cloth / Subd columns, "–" for nothing published, colour only for work (behind, missing,
  asset?; #6f9aff on a selected row for contrast); narrow: versions on a second line under the first header's column
  names. Inspector (`InspectorPanel`, fixed ~360 px, under the list when narrow): name, node and versions, meshes
  read-only; scheme / dicing / clear / apply on the meshes' right-click menu. Result line in the action bar (above
  the buttons when narrow). Style rules for item views carry an objectName: Houdini's sheet painted the tree grey.
- Parm pane (layout D, the user's pick 2026-11-17, checked in the Houdini 22 GUI down to 420 px; `_parm_templates`):
  Manager / Refresh, a one-line Status shown only when something needs the artist (missing file, `asset?`, notes),
  then Source / Parts / Geometry or Camera as plain groups and Advanced (project root, resolved paths) closed. The
  status of each version is in its menu label (Normal menus: "v002  (v003 available)", "v004  latest"), cached
  5 s per node and dropped by refresh; the node comment shows it in the network editor ("lookdev v003 available").
  While the source is not set, Status says only the next step (`logic.next_step`: no project -> Project Root or the
  manager's Project box, pick a shot, "<shot> has no anim publish yet", pick an anim file), never every part missing.
  Shot is a menu of the project's shots ("sh030  (no anim)"). Changing the shot or project on the node
  (`logic.switch_shot`) moves the same instance there like Retarget, else the shot's newest anim version and no file:
  a version or file of the old shot is never kept (it showed "anim v001 missing on disk").
  Show in Viewport is one button strip `mx_viewport` (bit 1 lookdev, 2 groom; it replaced PR #21's two toggles).
  Measured: `button_icon` draws label + icon (not a button), a one-icon strip does not draw, `script_action` shows
  on every row, and joined rows wider than checkbox + field overflow a docked pane: none of them is used.
- Desktop **Mono_Solaris** (`desktop/Mono_Solaris.desk`, 2026-11-22): Houdini 22's own `Solaris.desk` (its
  `/stage/motionblur/` paths made `/stage/`) with a left pane of 24 % holding only the Python Panel `monofx_loader`
  (`python_panels/monofx_loader.pypanel` -> `ui.create_panel("/stage")`, a manager of its own per pane, the narrow
  stacked layout at ~450-900 px). The floating `open_manager` window is unchanged and apart from it. Both folders
  are at the suite root (package `hpath`) and the installer already ships them (`tests/test_mono_solaris_desk.py`).
  To rebuild it from a newer Solaris desk: wrap SideFX's `root { ... }` in `split 0.24 H` after the loader's
  `tabs`, keep its pane settings, add `pythonpanel -s on -t off -n monofx_loader panetab20`.
- Manager window (`ui.py` view, `controller.py` no Qt, `HoudiniBackend` in the adapter): List and Grid (the
  user's pick), Monos asset thumbnails (`thumbnail.user.png`, else `.meta/thumb_lookdev.user.png`, else the
  newest `.meta/thumb_*.user.png`), Load shot finds existing loaders by user data `monofx_anim_loader`
  (shot + anim file, any version: never a second `/char_X`), Update / Load shot / Upgrade are one undo step each.
  One primary button, the most important thing to do (`controller.primary_action`: update > upgrade 2.1 > Draw
  Hulls Only for a heavy shot), hidden when there is nothing; the headline says the same; Upgrade shows apart only
  when it is not the primary. Styles go through `scale_css` (every px scaled by the UI scale). Grid cards share the
  row's width (as many as fit at 200 px, Qt keeps room for the scroll bar); a camera card is shorter.
- Retarget (the user's pick, 2026-11-17; `logic.retarget_state`, `adapter.retarget`): loaders copied from another
  shot move to the shot in the Load shot box. Which: the selected loaders from another shot; with nothing selected
  and the box on the scene's own shot (`$HIP`), every loader from another shot (then it is the primary, above
  Update, and the headline says "N loaders from sh025, not sh030"); a scene of no shot may load several shots.
  Each moves to the newest anim version there that holds the same instance (the camera: that shot's camera,
  node renamed when named after its shot), groom / cloth newest there (per shot), lookdev and every node setting
  kept (subd rules too). A shot without that instance, or one already loaded for it, leaves the node and says so.
  A shot merge whose loaders all moved is retagged. One undo step; also on a row's right-click menu.
- Project box (the user's pick, 2026-11-17), first in the Load shot box: the scene's project ($HIP), the loaders'
  projects, then recent ones (`recent_projects` in `anim_loader_prefs.json`, `logic.remember_project`, 8), and
  Browse... (a folder anywhere inside a project finds its root; inside a shot it picks that shot too). Shots come
  from `logic.list_shots` (`02_shots/<shot>/01_anim/publish`), so Load shot works in an unsaved scene. The shot
  box keeps only a shot the artist chose; otherwise it opens on the scene's shot, else the loaders' shot.
  List rows / grid cards are laid out again on their view's own resize (the splitter moves it, not the window).
  Shelf tool "Anim Loaders". Checks: `tests/test_anim_loader_*.py`, hython `tests/houdini/anim_loader/accept_*.py`
  on the fake project from `tools/fx/anim_loader/dev/make_fake_shot.py`.

## Tool panels (skill `.claude/skills/dcc-panel-design`)

- Any new or changed Qt panel inside a DCC (Houdini first) goes through the skill: artist tasks, the
  host's patterns, 2-3 mockups the user picks from, then build on the shared palette and roles, then
  offscreen grabs (`scripts/grab_offscreen.py`, 400 / 760 / 1100 px at scale 1 / 1.5) and the contrast
  check (`scripts/contrast_check.py`, pairs in `references/palette_pairs.json`, guarded by
  `tests/test_dcc_panel_design_scripts.py`) before screenshots go to the user. The panel rules above
  (one accent, px fonts through `Sz`, view bar apart from action bar, no modals, one undo step, view
  state apart from data) are collected there with the review checklist.
- Shared look helpers live in `tools/fx/look.py` (2026-11-19): the Monos state colours, `border_px`,
  `scale_css` / `round_borders`, `crisp_icon`, `filled_pixmap` / `eye_pixmap`, `PropsBase`, `SectionBase`. The
  MonoFX Loader (`anim_loader/ui.py`) and the MONO Grooming panel (`grooming/ui_look.py`) import them under their
  old names; where the tools differ, a parameter or a thin subclass keeps each one's pixels, and the defaults are
  the Loader's (released). A change there is checked by pixel-comparing both tools' offscreen grabs before and
  after (the Loader's thumbnail cell at 1100 px loads asynchronously and can differ between two runs of the same
  code). The palette itself stays in `tools/fx/auto_material/ui.py`.

## Release (`release.ps1`, skill `.claude/skills/release`)

- Two steps. `release.ps1 prepare` on the branch going to main: clean tree, tests pass, notes under
  `## [Unreleased]` in `docs/changelog.md`, then `bump_version.ps1` and one commit `docs: release vX.Y.Z`.
  `release.ps1 publish` only at `origin/main` (a detached checkout works in a worktree): every check
  first, the build before the tag (a failed build leaves no tag), then tag, push the tag,
  `publish_release.ps1`. `-DryRun` stops after the build. Patch bumps unless asked otherwise.
- The release commit goes to main through the PR; merging is the user's call.
- `.ps1` files stay ASCII (`tests/test_release_scripts_ascii.py`): Windows PowerShell 5.1 reads a file without BOM
  as ANSI, and Vietnamese text in a string swallowed the lines setting `$Notes`, so every GitHub Release up to
  v0.1.31 came out with empty notes.
