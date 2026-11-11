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
- Partial cook: each lock's hair is cooked once per state of what it reads and kept in a per-lock
  cache (`grooming_adapter.LockCache`, on `sys` so a module reload keeps it). `lock_keys` (Python SOP,
  hair modes only) digests per lock its spine and resolved settings, its region (`region_keys`, 9 sums
  per lock from PREVIEW), its mesh piece (`surface_keys`), the loop's parms, display mode and preview
  factor; colour and visibility are left out, so they recook nothing. Only locks that grow and miss go
  through the For-Each (`to_cook`); `cache_store` keeps each, `hair_cache` merges every growing lock
  (one copy: 4 M points in ~0.25 s, most of what a hide costs). Last 2 keys per lock and mode are
  kept, so undo finds the previous hair. Hairclump, length, frizz run inside the loop on the lock's own
  region (`clump_id` = lock_id x `CLUMP_ID_STRIDE` + its clump): a whole-groom node after the cache
  made every edit pay for 116 k strands again. A capped preview factor snaps to 0.8^k steps (it is in
  every key; cap / total moved with any density edit). Helen hair full: one lock edit 9.5 -> ~1 s,
  hide 9.5 -> 0.3-0.4 s, isolate 0.03 s; a group edit still costs its locks (20 locks ~4.8 s).
- Hidden locks (the lock's eye, or its group's: `Lock.shown`, the group wins and the lock keeps its own
  state) and locks isolated out are not cooked for display at all; publish sets `cook_all` and cooks
  every lock. Hidden locks keep their region (the provisional split ignores visibility), so hiding never
  changes another lock's strands. Isolate (`set_isolate` / `isolate_ids`) is the hidden `isolate_ids`
  parm, set with undo off and cleared by the HDA's OnLoaded: a temporary view, not restored with the
  scene; isolated locks draw even with their eye off.
- Per lock `root_flip` (root at the piece's other end) and `excluded` (no hair, not published, guide
  and mesh stay) are in the model, kept through re-Detect (matching uses the measured root, SPINES_RAW),
  set by `set_root_flip` / `set_excluded` (one undo step, marks regions stale; Chia vùng skips excluded
  locks). A flip reverses the spine after `assign_locks` (`spine_flip`); the surface cloud stays on the
  unflipped spine, so `fit_to_lock` reads it at 1 - u and the other thickness side. In the panel: the
  lock row's right-click menu ("Root at the other end", "Leave out of the hair", several locks at once);
  the row says "flipped" / "no hair" in its status column (neutral colour, the name is never shortened)
  and an excluded lock is dimmed.
- Interactive feel (judge it in GUI Houdini, until the viewport has drawn: `tests/t24_feel/t24_gui.py`
  in the sandbox; hython numbers missed all of the below):
  - Display without a shot deform is one packed prim per lock (`hair_packed`, embedding the cached
    frozen strands, coloured per packed prim). The merged 4 M points re-uploaded the whole groom to the
    viewport on every edit and hide. `HAIR` (merged) stays for publish and the deform; tests read
    strands there, not from the node's output.
  - The viewport draws a packed lock as a flat band of one width: Houdini ignores curve width inside
    any packed prim (Pack SOP fragments, packed disk too). The view follows the work, nothing to switch
    or remember (the user: a strands set of its own, kept while the selection moved on, left grey solid
    locks over the one being edited): the selected, drawn locks are their real strands (unpacked, width
    ramp) and the others see-through bands (packed: only packed geometry can be see-through); **X**
    (view bar X-ray) turns the bands into real strands to judge the selection inside the groom, the
    selection still edits; nothing selected, All locks, or a selection that is all that is drawn shows
    the whole groom as strands (`set_strands(node, STRANDS_ALL)`, hidden parm `strand_ids` = "all").
    Over `config.STRANDS_MAX` (20) selected locks stay bands, the message says so. `controller.
    _sync_viewport` sets focus and strands together on every selection change and refresh. Esc leaves
    isolate, then deselects. No strands icon, button, menu or Enter. Their packed prim stays, empty, so
    prim number = place among the packed prims for every lock. t41/t42 (GUI Helen): select 0.04-0.10 s,
    a group of 20 0.16 s, back to the whole groom 0.37 s, an edit 0.5-0.86 s with X-ray, 0.84-1.18 s
    without. Rejected (t29/t30): one geo object per lock, since with dependencies every edit recooks all
    61 (3.2-3.5 s).
  - Focus, not Houdini's selection highlight (the user: the highlight paints the lock over; the others
    should go x-ray): the panel's selection is the hidden parm `focus_ids` (`set_focus`, by lock id,
    undo off, cleared by OnLoaded and when the panel hides). Locks in focus keep their colour, the
    others get `GHOST_TINT` and `GHOST_ALPHA`: a copy per lock inside its packed prim (cached, like the
    colour), `_vex_ghost` on the mesh, guide and unpacked strands. The viewport draws Alpha inside
    packed geometry only (t35: Alpha on unpacked curves or on the packed prim is ignored) and adds it up
    over the thousands of strands in a lock. The user found 0.04-0.12 too see-through (t40): the strength is
    the hidden parm `xray_opacity` (`set_xray_opacity`, undo off, in the ghost copy's cache key), set by the
    panel from the artist's choice (`config.XRAY_LEVELS` Light 0.08 / Medium 0.15 default / Strong 0.25 /
    Solid 0.4, saved in the panel prefs as `xray`). Ghosts in front of
    the lock still cover it (they write depth). set_focus clears this node's viewport selection, so a
    pick in the viewport becomes the panel's selection and focus. A focus change: ~0.01 s, the first
    0.03 s. Only drawn locks take focus (`controller._drawn`): a selection hidden by its eye or outside
    the isolate would ghost every drawn lock, so then nothing is ghosted and the message says why; eyes
    refocus on every refresh. No "editing" word in the tree (the user: the packed / strands icon says more).
  - Loading: every change through the controller (`_run`, `_edit`) runs in `_busy`: the panel's loading
    line ("Cooking: …", a moving bar) is armed for `BUSY_DELAY_MS` (150), and the node is cooked there
    (`adapter.cook_display`), not on the viewport's next draw. Houdini handles Qt events mid-cook, so the
    line shows during a long cook (t37: a group density edit of 4.3 s showed it at 0.17 s) and never
    for a quick one. A first click on a lock makes the ghost copies of the others once (~0.1 s).
  - Undo keeps working with the panel focused: Ctrl+Z / Ctrl+Shift+Z / Ctrl+Y are panel shortcuts that
    call `hou.undos.performUndo` / `performRedo` (`adapter.undo`): Houdini's own hotkeys never see keys
    sent to the panel. `select_locks` (adapters without focus) runs with undo off: Houdini records a
    viewport selection, and Ctrl+Z undid that instead of the edit.
  - The panel's poll runs from Houdini's idle loop (`controller._when_idle`, hdefereval): Houdini
    handles Qt events mid-cook, and the poll asking the viewer for its selection on a node being cooked
    (Anim on, ~1.4 s) failed the cook with "Infinite recursion in evaluation". `needsToCook()` cannot
    tell (always true on this node). `selected_lock_ids` keeps lock_id per prim by `cookCount()`.
  - Selection reads `lock_id` in bulk and builds a range string (`_index_ranges`); one hou.Prim per
    strand (116 k) made each selection and every poll lag.
  - `lock_infos` reads the scalp areas in bulk, and the panel re-reads it only when settings, regions
    or flags change (`_infos_key`: not eyes, displays, order). It cost 2 s, then 0.12 s, on every edit.
  - A slider drag writes each tick with no undo step (`write_data_live`, at most every 120 ms); the
    dragged locks (`set_drag_preview`, hidden parm `preview_ids`, read by `lock_keys`) grow at their
    real strand count with `DRAG_SEGMENTS` points a strand (cache mode "drag", hairgen's segments read
    `drag_seg`): the preview fraction (a tenth) did not show what the density would look like. Past
    `DRAG_STRAND_BUDGET` strands (a group) at `logic.drag_factor` of them (hidden parm `drag_factor`,
    0.8^k steps), and the panel says "showing 1 in N strands". The release puts the pre-drag data back
    without undo and writes the final value: one undo step, full hair once. A tick on one Helen lock
    (3-5 k strands): cook 0.21-0.23 s, a frame 0.29-0.35 s (preview fraction was 0.07-0.09 s).
  - The "popup that flashes on every change" was the panel's own Reset button: a setting row showed it
    before adding it to its layout, so for a moment it was a window of its own, on every rebuild of the
    settings, and it took the mouse from the slider being dragged (`test_rebuilding_the_settings_shows_no_window_of_its_own`).
    It was first blamed on Houdini's cook-interrupt button: a spy on window Show events in GUI Houdini
    found no other window, Anim on included. Show a widget only once it has a parent. `ui._Slider` also
    follows a drag itself (a 15 ms timer reads the cursor and the system's button state,
    `_left_button_down`), so a window popping up mid-drag no longer ends it; the poll skips while a
    slider is down (a rebuild under the mouse ends it).
  - GUI Helen, hair full: select (focus) 0.06-0.13 s, hide / show 0.08 s, a drag tick ~0.3 s, release
    0.35 s, Ctrl+Z 0.03-0.04 s.
- Per-lock Display: `assign_locks` writes `row_display` (the lock's own Display, else its group's, -1 =
  the node's); `lock_shown` turns it into `disp` (lighter while playing, full hair while publishing) and
  `grows` (only preview and hair grow). `lock_keys` gives each lock its `strand_factor` (preview or
  full; the node's mode is not in the key, so a lock keeps its cache when the node's Display changes).
  The display merges mesh, guide and packed hair (switches `mesh_in_use` / `guide_in_use` skip a branch
  no lock uses: colouring 196 k mesh polygons on every edit doubled the cost). The packed hair carries
  its colour inside (a copy per lock and colour, in the hair cache): the viewport ignores a packed
  prim's Cd and drew the groom white.
- Shot deform: toggle `shot_deform` (panel: the Anim button, shown when an animated hair mesh is wired;
  no undo step). Off is the main mode: the default, and OnLoaded turns it off (the user groomed a scene
  saved with it on: every lock drawn as strands, focus only dimming, so select looked like strands /
  isolate). GUI tests open scenes as saved (t36), not with the deform forced off. Hidden `anim_wired` / `deform_active`. With it on, every edit deforms all 4 M points
  (~1.2 s), so grooming is done with it off (edits 0.1 s); with it on a drag applies on release. Each lock is captured to the rest hair mesh inside the per-lock loop and cached
  with its strands (`lock_capture`, per-lock `do_capture` in the key: always with deform on, full-hair
  locks only with it off, so turning it on regrows nothing and drag ticks skip the ~0.3 s capture);
  capturing the merged 4 M points cost 3-9 s per hide or show. Only mesh / guide parts are captured at
  display time. Two switches (`use_deform`, `deform_ok`): one hscript if() evaluated both sides and
  unpacked the anim USD on every frame with the deform off. Publish strips `pCaptPts` / `pCaptWeights`.
  Test scenes that keep the anim wired (`T24_ANIM=on|off` in t24) show what artists feel; earlier
  measurements had unwired it and missed all of this.
- GUI timings swing with machine load (the same profile ran 1.6-1.9x slower with other apps at 60 %
  CPU): compare against an action whose code did not change (select) before calling a regression.
- Test scripts reload the suite's HDA with `force_use_assets=True` after loading a scene: a hip names
  the library it was saved with (another session's worktree), and Houdini prefers the newest file.
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
- Cross-sections are fitted to `measure_samples` (4000) points spread over each lock's faces, not to the
  mesh's own points: a low-res lock (Helen hair_base_03, 254 points) left ~5 points a band, measured
  1.6 cm across a 4 cm cap and its hair came out a narrow twisted ribbon. Lock shape was not the cause.
- Strand shape: spines have 48 points, smoothed along their length (`spine_smooth`, a wrangle:
  Attribute Blur pins every point of an open curve), which also writes the new `tangentu` (Resample's
  is stale after the blur and turned the frame again). The frame is not blurred as vectors: a band's
  principal axis has no sign and is near random on round bands (crown caps turned 145 deg between
  points); it is an angle around the spine from a parallel-transported frame, doubled, unwrapped,
  smoothed, rebuilt. `ps` (across) is stretched per piece to the mesh's real edges, interpolated along
  the lock. Each strand: `fit_root` (per strand: s, t, root, root placement) then `fit_to_lock` (per
  point; writing points from a prim wrangle was 2.5x slower); its offset from the spine gets a median
  of 3 and a blur, and its first fifth is relaxed with a fading weight (`strand_smooth`). Segments:
  at least 32, more on long locks (`strand_segment_cm`); 12 left curled short locks with 80 deg corners.
  A strand's place across the lock is an even spread (`cross_spread`), not where its root fell in the
  region (that bunched strands mid-lock), and its root is pulled under that spot (`root_pull`, else
  wide regions fan in). Strand count uses the lock's widest band anywhere (the first quarter gave
  long hair_back ribbons 800 strands: see-through). Scenes keep the parm values they saved
  (`spine_points` 24 in older scenes): revert them to the defaults to get this result.
- Hairclump runs per lock (inside the loop), `clumpid` = `lock_id` going in, so clumps stay in a lock. The lock's clump
  setting drives hairclump's `blend` (per strand `clumpblend`): its tightness alone never switches
  clumping off (tightness 0 still left 27 % of Helen's mesh bare). Default clump 0.2.
  The frozen split lives on the node's hidden geometry parm `regions` (not a stash SOP: inner nodes of a
  locked HDA cannot be set); Python SOPs inside the HDA call `grooming_adapter.cook_assign` / `cook_frozen_regions`.
- hairgen's `skinprim` indexes the per-lock region cut inside the loop, which is also hairclump's skin
  there (`v@rest` added), so no skin lookup is needed.
- Strand display colour is a prim `Cd` looked up on the spines after the cache (116 k prims, not 4 M
  points); the cached strands carry no colour.
- The scalp and rest hair mesh are read at `rest_frame` (timeshift): a USD Import is time dependent even
  for a static file, so the whole groom recooked every frame; now only the shot deform does (0.7 s/frame).
- Inside the HDA every stage is a titled network box, one column each (`_layout_sections`): one
  `layoutChildren` over everything made a knot of crossing wires.
- Helen (sandbox t12/t16/t18): 61/61 locks with hair, 116 k strands, 4 M points, hair check PASS (corner
  p95 26 deg vs 43 for v006, mesh uncovered 6 % vs 3.5 %, every lock at least 0.76 of its mesh's width), full cook 5.3 s, density edit 5 s, shot frame 1 s,
  detect 2.6 s, split 4 s, publish 5 s / 50 MB (47–56 s before regions were frozen). GUI checks run Houdini with a startup script on the secondary monitor and grab the panel.
  Quitting Houdini with `hou.exit` from a Qt timer segfaults even in an empty session (fxhoudinimcp
  loaded): not this tool; kill leftover test sessions after a GUI run.
- Anim input (input 2) may be a USD Import left packed (one PackedUSD prim): inside, `unpackusd` to
  gprims as packed prims, keep those whose name / path / last path part is a rest hair mesh prim name
  (`rest_names`; "Hair" alone would take Helen's HairProxy eyebrows), unpack only them to polygons, no
  primvars. Unpacking the whole character cost 0.1-0.3 s a frame; packed per frame on sh020: guide
  0.06 s, mesh 0.10, preview 0.14 (unpacked 0.22 / 0.25 / 0.30). An unpacked input goes through as
  before. The deform runs only when the anim has the rest mesh's point count (`ANIM_HAIR` `deform_ok`,
  else a warning). Point Deform is split: `deform_capture` (mode capture, time independent, once) and
  `deform` (mode deform); hair full is still ~1 s a frame, all of it the deform of 4 M points
  (`maxpt` 100; 32 is 3x faster but moves some points 2.6 cm, so it stays).
- While playing (`play_display`, default Hair preview): during playback the node draws
  min(Display, While playing) through the hidden `display_eff` expression (every inner reference to the
  mode reads it, the cache key too); the adapter's playbar callback (installed once by OnCreated /
  OnLoaded, UI only) sets the hidden `playing`, undo off. Hair full playing: ~0.25 s a frame. Publish
  clears `playing`.
- Shots: Karma's hair procedural (Generate) does not reproduce clump/frizz, so publishes carry full
  strands and shots Point Deform them (sandbox t02).
- Panel (`ui.py` view, `controller.py` logic): three zones on their own surfaces with a line between (tree
  and bars `PANE`, settings on the window colour); one accent (Publish, selection, drop target), status
  colours only for unsure / new / regions out of date / errors. Sizes go through `ui.Sz`: Houdini's UI scale
  (`hou.ui.scaledSize`) x the panel's own UI size (top bar, `%APPDATA%/MonoFXSuite/grooming_prefs.json`);
  type roles 22/16/16/15/14/13 px at 1. Font sizes Small 0.8 / Medium 0.9 (default: the user's old Small) /
  Large 1.0 / Larger / Largest / Huge, pref `font_size`; an old `ui_size` moves by value (`_UI_SIZE_RENAMED`). Style rules are prefixed `QWidget#GroomingWindow` (Houdini's own
  sheet wins over a bare `QLabel[role]`), and the tree's rows, branches and selection have opaque colours:
  Houdini's style paints item views grey under transparent ones. A setting is one row (name, slider, value,
  source as plain text, Reset only when set at this level); several locks that differ show "mixed"; a
  drag writes once on release (one undo step). Sliders and combos ignore the wheel, so it scrolls the panel.
  Measured values in cm (`adapter.unit_cm(node)` when there, else the node's `unit_cm` parm).
- Panel layout (2026-11-12 redesign): top bar (node, asset, Settings ⚙: Font size and X-ray, saved per user; Dock), then a view bar (Display,
  Color by, Deform, Isolate: viewing never sits next to an action that writes), the tree (filter, a Confirm
  all line while locks are new / to check, banner, rows), the settings (title, subtitle with what the
  viewport does with the selection, toggles Strands / Isolate / Hidden / Flip root / Exclude in a `_WrapRow`
  that wraps to the width, measured cells, settings), the action bar (loading, result line that fades
  after `MESSAGE_MS`, Detect locks, Update regions, version, Publish). Nothing selected shows the whole
  groom and the keys. Below `NARROW_PX` (760 x scale) the tree sits above the settings, both bars stack,
  rows go compact and cells two a line; the floating window's minimum is 400 x scale. A width-dependent
  widget wraps itself on resize (`_WrapRow`): building to a measured width failed, the layout had not
  given the column its new width yet. The packed / strands and eye icons are painted by `_IconDelegate`
  (`ROLE_ICON`, `ROLE_QUIET`): the default state (packed, shown by its own eye) only on the hovered or a
  selected row, any other state always. The first Detect marks no lock "new" (every row would say it).
- Inheritance in the panel: the defaults level is the tree's root group **All locks** (`ALL_LOCKS`), the
  groups sit inside it (the data still keeps `defaults` apart; only the view nests). A setting's source
  column names the level an inherited value comes from: the group by its name, All locks, or "tool
  default" (`model.BUILTIN_DEFAULTS`). On All locks or a group a last column says whether the levels
  below follow ("all follow") or how many set their own ("2 set own", tooltip names them; narrow: "↓2"),
  and an edit there says who keeps their own value (`controller._below`).
- Names as Houdini uses them (checked against SideFX's Hair Generate / Hair Clump pages): Thickness and
  `width` are one strand's, so the lock's cross-section is "Lock width" / "Lock thickness" (settings and
  measured); the scalp is "skin" (Skin area); Clump drives Hair Clump's Blend (tooltip); Guides; Hair /
  Hair preview (10%); Color (US spelling); Deform, not "Anim" with a play icon (it read as playback);
  Update regions (pairs with "Regions out of date"), Detect locks, Pack all, Flip root, Exclude from hair,
  check match (the data keeps "unsure"), Missing locks (data: orphans). Twist is shown in degrees
  (`SETTING_SCALE`, stored in radians) like the measured twist. Data keys never changed.
- The eye: its shape says what the viewport draws (open = drawn, crossed = not drawn), its tone says why
  (normal = the row's own eye, faint `FAINT` = its group or isolate decided, accent = drawn because
  isolated); a click always toggles the row's own eye and the tooltip says it. Before, a lock under a
  hidden group showed an open eye and an isolated lock with its eye off a crossed one, while the viewport
  did the opposite. Alt+click on an eye shows only those rows and hides every other lock and group
  (`controller.solo_visible`, eye states, one undo step); again on the same rows shows everything. The isolate button turns its icon accent when on, not only its background; menu
  actions never use the check icon (it reads as a ticked option): Confirm match is `badge-check`.
- A hidden group dims its row and its locks ("hidden by group"; their own eye kept). Isolate (I, Esc) is
  `adapter.set_isolate(node, ids | None)` / `isolate_ids(node)`: a view state, never in `groom_data`.
  I on other locks while isolated isolates them at once; I on the same locks shows everything.
  Drag and drop: the controller's `plan_drop` decides on every mouse move (refusals say why: Defaults,
  onto itself, group into group, locks with a group); Qt never moves items, the drop is one write.
  Tree order = order of `GroomData.groups` / `.locks` (`move_locks`, `move_group`). Locks moved to another
  group keep their overrides; the message lists values that now come from the new group, and regions
  are marked out of date. Publish with hidden locks or while isolated: the first click only warns next to
  the button (names, count), a second click with the same locks hidden publishes everything.
- Names follow the department: `grooming` (`04_grooming/publish/vNNN/char_<name>_grooming_publish.usd`,
  tool data in `vNNN/_grooming/`). Publish version defaults to the scene's `_vNNN` and never overwrites.

## Release (`release.ps1`, skill `.claude/skills/release`)

- Two steps. `release.ps1 prepare` on the branch going to main: clean tree, tests pass, notes under
  `## [Unreleased]` in `docs/changelog.md`, then `bump_version.ps1` and one commit `docs: release vX.Y.Z`.
  `release.ps1 publish` only at `origin/main` (a detached checkout works in a worktree): every check
  first, the build before the tag (a failed build leaves no tag), then tag, push the tag,
  `publish_release.ps1`. `-DryRun` stops after the build. Patch bumps unless asked otherwise.
- The release commit goes to main through the PR; merging is the user's call.
