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
  `build.ps1` builds the add-on ZIP first: that vendors `monofx_pipeline_common` into the add-on folder the
  installer ships.

## Blender add-on USD publish (`tools/fx/monofx_pipeline_blender/`)

- Model publish leaves materials where Blender 5.2 writes them, `/_materials` at the stage root (the user's
  decision, 2026-11-17): a move into `/<defaultPrim>/material` shipped in v0.1.26-v0.1.27 and was taken out.
  Whoever wants materials inside the root prim adds the root prim in Blender and exports as usual.
- After `wm.usd_export`, `transform.usd_export` stamps the scene fps (`usd_stage_fps.stamp_fps`: a static
  export keeps 24, and a Houdini Sublayer LOP copies it over the hip's fps) and, for a model publish
  (`asset_kind="component"` from `_run_usd_export`), marks the default prim `kind = component`
  (`usd_asset_kind`; not over a kind already there, not above a grouping kind). Neither ever fails the export.
  Both open the file with `Sdf.Layer.FindOrOpen` + `Reload(force=True)`: a layer still open in the session
  is the one from before the export, and a plain `Reload()` skips a file rewritten in the same second.
  Their tests need pxr: run them with hython (pytest skips them).
- Publish file names (`publish_paths.collection_publish_usd_basename`): one collection -> the plain
  `<asset>_<task>_publish.usd`; several -> the collection name after `publish`, words joined with a
  capital each (`char_Helen_uv_publish_GeoHelen.usd`).
- Version mode File (default for new scenes): the publish version is the open work file's `_vNNN`.
- Anim USD caches points only, never normals (subdivision scheme: next note); per-frame normals cost
  ~5x the file size (Helen 313 MB -> 1.53 GB). Static meshes and transforms keep only first/last samples
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
- A locked LOP HDA makes its inner nodes on first cook: `node.children()` is empty before.
- Subdivision per mesh (the user's decision, 2026-11-17; `logic.subd_plan`, `adapter.author_subd` from the
  `render_only` Python LOP): a shot rule on the loader (hidden `mx_subd_rules`, JSON `pattern` from `/<instance>`,
  `scheme` publish / none / catmullClark, `dicing`; a later rule wins) > lookdev publish > anim publish > `none`.
  Never USD's fallback `catmullClark`: it made Houdini GL subdivide whole shots (sh025 v005 past 45 GB, crash in
  `GR_OSDSubdSurfaceVK`; Helen alone 12.5 GB with a plain Sublayer, 2.5 GB with `none`). Opinions are read from
  the publish files themselves with `TraverseAll` (lookdev holds overs): Graft Stages flattens and writes the
  fallback as a value. Dicing is `primvars:karma:object:dicingquality` (render only).
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
  Only link), never in the result line. Draw Hulls Only makes the viewport lighter to work
  in but does NOT lower memory (Helen catmullClark 12.8 GB -> 19.5 GB when turned on; 13 GB on from the start).
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

## Release (`release.ps1`, skill `.claude/skills/release`)

- Two steps. `release.ps1 prepare` on the branch going to main: clean tree, tests pass, notes under
  `## [Unreleased]` in `docs/changelog.md`, then `bump_version.ps1` and one commit `docs: release vX.Y.Z`.
  `release.ps1 publish` only at `origin/main` (a detached checkout works in a worktree): every check
  first, the build before the tag (a failed build leaves no tag), then tag, push the tag,
  `publish_release.ps1`. `-DryRun` stops after the build. Patch bumps unless asked otherwise.
- The release commit goes to main through the PR; merging is the user's call.
