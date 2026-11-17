# Changelog

## [Unreleased]

### Houdini
- **MonoFX Loaders** manager: each prim in the inspector has three toggles, as in Blender's outliner: show / hide, drawn in the viewport, rendered. Hiding a group hides what is under it and each child keeps its own setting for when the group shows again; viewport and render follow the parent unless a child has its own. A dot marks a prim that overrides its parent; the accent marks what this shot set. The groom's curves are listed under Groom. A camera's clipping, aperture, ratio and guide scale on the loader are edited in the inspector.
- **MonoFX Loaders** manager: the meshes' right-click menu says what each item does ("Use the publish's subdivision", "Turn subdivision off", "Subdivide (Catmull-Clark)", "Remove the shot's overrides", "Copy these overrides to every char_Helen"), every item has an icon and they line up; dicing is picked from a submenu of steps.
- **MonoFX Loaders** manager: the inspector's meshes table runs the full width with no strips beside it, its name column fills the room, its thin scroll bar sits inside it, and its rows are dark like the main list (Houdini painted them grey). It shows every level of the hierarchy, as the scene graph does (Geo, Base_grp, Body_grp, Geo_Body), each group with its meshes' faces summed, and Houdini's own Xform / Mesh icon before each name.
- **MonoFX Loaders** manager: the inspector of a camera shows its lens (focal length in mm, aperture and ratio, clipping in m, f-stop and focus distance or "Depth of field: off"), read from the stage at the current frame; a shot's loader shows its frame range and fps from the anim publish. An asset's loader shows neither.
- **MonoFX Loaders** manager: **Bake to plain nodes** (hand-off menu, right-click) turns loaders into plain Houdini subnets that open without MonoFX, for someone with Houdini only; the scene stays the same. **Upgrade** turns them back into MonoFX Loaders.
- **MonoFX Loaders** manager: one **Upgrade** turns old loaders and publish sublayers alike into MonoFX Loaders (there were Upgrade and Convert for the same thing). The inspector is a list of labels and values; its Details and Newer version sections fold, and the fold is remembered.
- **MonoFX Loaders** manager: a prop whose lookdev holds the whole asset shows "–" for its model (some said "missing"); a first version reads "+V001"; the result line keeps to two lines, the rest in its tooltip; double-click selects the node and shows it in the Network Editor; menus have square corners and separators, an old loader's menu offers Upgrade; the list scrolls sideways instead of dropping columns; the inspector slides in and out; the crumbs move to their own row when the list column is narrow.
- **MonoFX Loaders** manager finds Sublayer and Reference nodes that read a publish (a scene built by hand): a "sublayers" group with what each reads and whether a newer version exists, **Update** (the version in the path), and **Convert to MonoFX Loader** from the right-click menu, which keeps the node's place and wires and moves the prim patterns of the xforms after it, so the scene stays where it was (env_Envi lookdev: 10 sublayers converted, same 1040 meshes and bounds).
- **MonoFX Loaders** manager: fewer bold and big words, icons drawn sharp at any UI scale and centred in their buttons.
- **MonoFX Loaders** manager reads Anim Loader 2.2 nodes like MonoFX Loaders (versions, status; tagged 2.2, still offered for Upgrade). Before, a scene of 2.2 nodes showed them as unknown, reported every output of the shot as missing (Add would have doubled them) and lookdev / groom as render only. Columns give way (Textures, then Subd) before names are cut; the title label is gone (the window title says it).
- **MonoFX Loaders** manager, fewer words: the top bar is icons (filter, viewport menu, list / grid, add), the separate viewport row is gone, Hand off / Undo / Upgrade are icons with tooltips. The inspector runs the full height on the right. Rounded borders are 2 px and follow Houdini's UI scale (1 px looked broken on the corners).
- **MonoFX Loader**: Draw Hulls Only and Frame find the Scene Viewer inside Houdini 22's Context Viewer pane; before, they said "No viewer shows /stage" while one did.
- **MonoFX Loaders** manager: a part that had nothing published when the loader was made, and has a version now, shows as newer ("– → V001") with Update, not as missing. Textures get their own column (Subd was cut off); small files read in KB, not "0.0 MB"; shots are listed before assets. A camera's inspector shows only what a camera has (its anim), and what is new in its anim.


## [0.1.33] - 2026-11-17

### Houdini
- **MonoFX Loaders** manager (layout A, picked from mockups): **+ Add** holds Load shot and **Assets...**, a drawer of the project's assets (type chips, search, thumbnails; pick several, Add N). A **view bar**: Solo selected (Houdini's Solo Geometry, not saved), Lookdev / Groom in the viewport for every loader, Filter. The status line says what the shot has that the scene lacks (**Add it**) and how many GB of textures the lookdevs pull. The selected loader shows **what is new** in a newer version (date, who saved its work file in Monos, outputs, frame range, meshes, size), Source Shot / Asset, and Open folder, Open in Monos, Frame. **Hand off...** writes a self-contained USD per loader with its textures, for people without MonoFX.
- **MonoFX Loader**: in a lighting scene laid out with merge_actors / merge_cameras / merge_environments, Load shot and Add put the new loaders there (characters with the actors, props and sets with the environments). Adding an asset already placed makes another instance (`prop_Cliff01_inst02`) for set dressing.
- **MonoFX Loader**, Source Asset: props and environments whose lookdev publish holds the whole asset load that alone; before, the UV mesh was loaded under it as well (double geometry).

### Houdini
- **MonoFX Loader** is its own node now (Tab > MonoFX > MonoFX Loader, named `monofx_loader`), no longer an "anim loader" in name, file or type. Scenes with the 2.2 node still open; the manager's **Upgrade** moves those nodes over, keeping every setting.
- **MonoFX Loader** manager (shelf **MonoFX Loaders**) finds loaders in every LOP network, also inside /obj (grooming scenes), not only /stage; opened from a node, Load shot builds next to it.
- **MonoFX Loader**, Source Asset: an **Asset Type** menu (Characters, Props...) shortens the Asset list, which shows only assets that have a UV publish; Advanced shows the **Model Path**; a part with nothing published says "none published".


## [0.1.32] - 2026-11-17

### Houdini
- **MonoFX Loader** (the Mono Anim Loader, renamed): a **Source** menu. Shot loads a shot's anim as before; **Asset** loads the asset's own UV model, groom and lookdev, for grooming and lookdev scenes. Both put the character at the same prim paths (`/char_Helen/Geo/...`), so one node replaces the Character Loader + Anim Loader pair and switching Source needs no rewiring; each side keeps its settings. A node put down in an asset's folder starts on Asset with the newest versions. A model version with several files offers a Model File menu, the standard `<asset>_uv_publish.usd` first.
- **MonoFX Loader**: groom sits outside Geo, at `/char_Helen/Groom/...`, where lookdev binds the hair materials, for the asset's groom and for shot groom caches (motion blur kept).
- **MonoFX Loader** manager: **Upgrade** also turns Character Loader 3.2 nodes into MonoFX Loader nodes on Source Asset, in place (same name and wires; model, groom, lookdev, scale and hidden prims kept; its SOP Modify is not carried). Their prims move from `/Geo` to `/<asset>/Geo`.


## [0.1.31] - 2026-11-17

### Houdini
- **Mono Anim Loader** node put down by hand: **Shot** is a menu of the project's shots (shots with no anim say so), and changing the shot moves the same character to the newest anim there, or picks that shot's newest version with no file yet, instead of keeping the old shot's version ("anim v001 missing on disk"). While nothing is picked, Status says just the next step: outside a project, where to set one (Project Root under Advanced, or the manager's Project box); then pick a shot, "sh030 has no anim publish yet", pick an anim file.


## [0.1.30] - 2026-11-17

### Houdini
- **Mono Anim Loader**: the camera's Clipping Range defaults to 0.0001 - 1e6 (near clip was 0.001).


## [0.1.29] - 2026-11-17

### Houdini
- **Mono Anim Loader 2.2** (`mono_anim_loader::2.2`, built from code into `otls/`): one node per character, clone or camera of a shot, grafted under `/<asset>` (clones `/<asset>_instNN`) so several characters and clones load together; lookdev, groom and cloth found for that instance only; groom / cloth caches with time samples load as value clips (motion blur); versions never change by themselves. Manager window and shelf tool **Anim Loaders**: every loader in the scene as a list or a grid with Monos thumbnails, what is behind, Update (one undo step), Load shot, Upgrade 2.1 nodes.
- **Mono Anim Loader**: subdivision per mesh comes from a shot rule on the loader, else the lookdev publish, else the anim publish, else none. USD reads a missing scheme as Catmull-Clark, so the viewport subdivided whole shots (sh025: over 45 GB, then a crash). Rules can also set Karma dicing quality.
- **Mono Anim Loader** manager: a **Subdivision** column beside the list shows the selected character's meshes by group, where each scheme comes from and its dicing; set Publish / Off / Catmull-Clark and dicing on a selection, clear overrides, or apply them to every instance of the asset. Rows show "subd N · ~X M".
- **Mono Anim Loader**: a heavy shot (lots of subdivision) shows a small non-modal prompt offering **Draw Hulls Only** for the viewport (lighter to draw and less memory: Helen 12.8 GB -> 7.2 GB), with Don't ask again.
- **Mono Anim Loader**: Lookdev and Groom get **Show in Viewport** (on). Off loads them for render only (Karma).
- **Mono Anim Loader** manager polish: one primary button, the thing worth doing now (Retarget, else Update, else Upgrade 2.1 nodes), hidden when there is nothing to do. The heavy-shot warning lives only in the Subdivision column, with Draw Hulls Only beside it. The scheme is a menu on each Subdivision row (on a selected row it sets the whole selection); dicing has its own field and keeps the scheme. From shows only where a mesh differs from its group, Dice only when there is dicing. Grid cards fill the width, camera cards are shorter, the splitter handle shows, and every size follows Houdini's UI scale.
- **Mono Anim Loader** manager: **Retarget** moves loaders copied from another shot to this one: the newest anim there with the same character (the camera: that shot's camera), groom and cloth from that shot, lookdev and node settings kept, one undo step. In a scene saved in a shot it is offered for every loader from another shot; otherwise for the selected ones (also on the right-click menu). Characters the shot does not have are named and left as they were.
- **Mono Anim Loader** manager: a **Project** box beside the shot: the scene's project, recent ones, or Browse for a folder (anywhere inside a project; inside a shot it picks that shot). Its shots are listed from the project, so Load shot works in a scene that is not saved yet. Also: list rows no longer overlap when the Subdivision column is dragged wider.
- **Mono Anim Loader** manager redesigned on the Monos UI rules: project and shot as crumbs with menus and **Load shot** as a menu (no combo boxes); a slim status line instead of the big headline, with the heavy-shot note and Draw Hulls Only on it; the list is a table (one row per loader, a column per part, "–" where nothing is published, colour only where there is something to do); the details and subdivision show only for a selected loader, and scheme / dicing are set from the meshes' right-click menu.
- **Mono Anim Loader**: cleaner parameters. Each version menu says its status ("v002  (v003 available)", "v004  latest") and the node shows it under its name in the network editor; the Status line appears only when something needs you (a missing file, an unknown asset). Source, Parts, Geometry or Camera as groups, a checkbox beside each part, **Show in Viewport** as one Lookdev / Groom strip, file paths under Advanced. Show in Viewport is a new parm: a loader saved with it off shows both parts in the viewport again.
- **Mono Anim Loader**: the camera's **Clipping Range** works again (its parms were named `clippingRangex/y`; the camera read `clippingRange1/2`, as in 2.1), and defaults to 0.001 - 1e6.

### Blender
- **Anim USD**: a second rig of the same asset is named `geo_<asset>_inst02.usd` (then `_inst03`...), not `_2`, which clashed with assets whose names end in a number (`char_Robot_2`, `prop_CoralSet_001`). `publish_meta.json` now gives each geo output its `asset` and `instance` when the name is an asset folder of the project. Read by Mono Anim Loader 2.2.
- **Anim USD**: every mesh writes its `subdivisionScheme`. Without one, USD reads a mesh as Catmull-Clark, so Houdini's viewport subdivided every character and set (sh025: over 45 GB, then a crash). A mesh is `catmullClark` only when a Subdivision Surface enabled for render ends its modifier stack, like a model publish; it is then exported as its cage (the Subdivision is switched off in the viewport during the export and back on after), so the file is also lighter. Anything else is `none`, Multires too.

### Maya — removed
- MonoFX no longer supports Maya. Taken out: `apps/maya` and the Maya tools Reference Manager, USD Export, Render Preview, Position / Scale and Scale from Last, with their tests. None of them was in the installer or the Houdini shelf.

### Shared / tests
- The shared rig library scan (`monofx_pipeline_common.rig_library`) defaults to Blender rigs (`.blend`, `02_build_rig/blender/work`); the Maya defaults are gone. The Blender add-on passed these itself, so it works as before. The shared scan tests moved to `tests/test_rig_library.py`.


## [0.1.28] - 2026-11-17

### Blender
- **Model publish**: materials stay where Blender writes them (`/_materials`, beside the asset root), as before v0.1.26: the move into `/<root>/material` is taken out.
- **Model publish**: the asset root is marked `kind = component` (USD asset structure). A kind already there, or a component / group / assembly below the root, is left alone.
- **USD fps**: every publish (model, UV, camera) carries the scene fps. A static export used to keep 24, and a Houdini Sublayer copied that over the hip's fps (30 fps scenes rendered at 24). Anim USD also writes `framesPerSecond`.


## [0.1.27] - 2026-11-17

### Installer
- The installer also installs the Blender add-on: a task (on by default) copies it into every Blender 5.0 or newer on the PC and turns it on, so the ZIP no longer has to be installed by hand. Close Blender first; a Blender it cannot turn the add-on on in is named at the end.
- Monos (Settings › Add-ons › Studio tools) shows the installed MonoFX version: the installer writes it to `%LOCALAPPDATA%\Monos\tools\MonoFXSuite\VERSION`, and uninstalling removes it.

### Blender
- The add-on registers in background Blender (`blender -b`): it imports `bpy.utils.previews` itself.


## [0.1.26] - 2026-11-17

### Houdini
- **Auto Material**: Fix colorspace button. Select a Material Library LOP and click it: every MaterialX image with an empty colour space gets the one in its file name (`_ACEScg`, `_Raw`, `_sRGB`, `_Linear`). Materials Houdini converts from a USD leave it empty, which made base colours look washed out; images that already have a value are not changed. One undo step.
- **MONO Grooming** (v0.2a): density layers. Paint a density mask on the scalp in the viewport; each layer sets its own strands per cm² under its own mask stack, stacked over the base density. Scenes saved by v0.1 open with their groom unchanged.

### Blender
- **Model publish**: materials go under the asset root (`/<defaultPrim>/material`) instead of `/_materials` at the top of the file, with every binding moved with them, so a reference to the asset brings its materials.
- **Model publish**: file names by collection. One collection publishes `char_Helen_uv_publish.usd`; several collections add the collection name after `publish`, words joined with a capital (`char_Helen_uv_publish_GeoHelen.usd`).
- **Model publish**: the Publish dialog no longer fails with "Writing to ID classes in this context is not allowed" (Blender 5.2).
- **Publish version**: new mode File (the default for new scenes): the publish version is the `_vNNN` of the open work file. Geo and anim USD.
- **Anim USD**: the file declares a `defaultPrim`, so Solaris Reference / Sublayer attach it without a prim path.
- **Anim USD**: faster export: meshes that do not move keep only their first and last sample, points are read in one call (shot sh025 ~57 s).
- **Anim USD**: object transforms are written every frame (rigs animated only by transforms), and translated / rotated rig roots come out at the right place (the matrix was written transposed).
- **Anim USD**: a warning when a mesh exports with all points at the origin, empty or NaN, naming its active modifiers (e.g. a wrap modifier with no source object).
- The add-on version shows in the Scene, Model and Anim panel headers.

### Shared / tests
- Tests for the material scope move (needs pxr, run with hython), collection file names, point sampling, degenerate points and the colour space fix.


## [0.1.25] - 2026-11-13

### Houdini
- **MONO Grooming** (new, v0.1): a SOP node that turns a hair card mesh into strands. Detect finds the locks and their roots on the scalp, Split regions gives each lock its patch of skin; each lock grows strands evenly at the set density that gather into the lock's shape (Helen: 61 locks, ~119,000 strands, full cook ~11 s).
- **MONO Grooming**: a panel (MonoFX shelf) with the locks in a tree (groups, hide, isolate, exclude), per-lock and global settings with sliders, Guides / Hair views, Color by lock or group; hidden locks do not cook, so working on a few locks stays fast.
- **MONO Grooming**: skin under hair mesh that floats over the scalp is left thin on purpose, as in a hand groom, and the panel says so; a lock whose mesh root floats off the skin is listed by Detect and Root to skin bends its start down.
- **MONO Grooming**: output 1 "Groom" is the full groom whatever the view; Publish writes it as USD with the groom data in `vNNN/_grooming/`, never overwrites a version, and never leaves a half-written file (a failure says why in the panel).

### Installer
- Ships `otls/` (the MONO Grooming HDA).

### Shared / tests
- Grooming logic, controller and publish tests; `grooming-check` skill (hair QC numbers and shaded shots against an approved groom).


## [0.1.24] - 2026-11-09

### Houdini
- **Auto Material**: new window, scene first. A sidebar lists every Material Library in the scene with how many materials are behind their latest publish; the main area says what the button does ("5 materials behind v010"), shows the versions on a timeline (click one to move the materials there), the materials as tiles with a texture thumbnail and their maps beside them.
- **Auto Material**: update from the scene. "Update all" or "Update N selected" moves libraries to their latest publish without opening them, also libraries built from texture folders; only materials whose version changes are touched, edits by hand stay. One undo step, and an Undo button after each run.
- **Auto Material**: right-click a Material Library in `/stage` › MonoFX › Update materials to latest / Open in Auto Material.
- **Auto Material**: Follows selection: selecting Material Library nodes in `/stage` picks them in the window; for a texture folder the target library is chosen for you (the selected one, else the one holding the materials, else a new `{asset}_materials`) and shown, with Change.
- **Auto Material**: reads materials made by other tools from a Painter export (SideFX Painter-to-Karma) and pasted materials: versions come from the texture files, and an update changes the existing image nodes in place.
- **Auto Material**: Create, Update and Auto assign are each one undo step.
- **Auto Material**: reading exports, folders and thumbnails no longer holds the window; progress shows on the action bar instead of a dark overlay.

### Installer
- Ships `OPmenu.xml` (the MonoFX node menu).


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


## [0.1.22] - 2026-11-02

### Houdini
- **Auto Material**: read the colour space from Monos Painter texture names (`{set}_{name}_{colorspace}.{UDIM}.{ext}`: sRGB, Linear, ACEScg, Raw); `Linear` maps to `lin_rec709`, so float BaseColor maps in ACEScg or Linear no longer load as sRGB. `vNNN/publish.json` `cleaned.maps` fills the space for names without one.
- **Auto Material**: scan only the highest `vNNN/textures` folder of a Monos publish.
- **Auto Material**: Subsurface slots (weight, colour, radius) accept `SubsurfaceWeight`/`Subsurface`/`SSS` names and wire to `mtlxstandard_surface`; a colour or radius map without a weight is reported.
- **Auto Material**: Create on an existing material updates it and keeps edits made by hand (files and colour spaces changed by the user stay; new maps go only into free inputs; nothing is deleted, re-wired or moved). Auto assign adds to `assign_material_auto` instead of creating another node.

### Shared / tests
- Add Auto Material publish and update tests.


## [0.1.21] - 2026-07-21

### Installer / Houdini
- Copy shelf/icons only into **selected** Houdini versions that received a full install (avoid orphan shelf buttons).
- Point `monofx.json` `hpath` / `MONOFX_SUITE` at `$HOUDINI_USER_PREF_DIR/monofx`.
- Shelf `_find_suite_root` resolves installer `Documents/houdini*/monofx` layouts more reliably.

### Blender
- Multi-axis **sine chain** drivers (per-axis slots, wave modes, chain phase).
- Anim USD Cache: custom mesh export list (add/remove selected), richer asset list UI.
- Resolve anim publish under any `NN_anim` task folder (shot or asset). Bump add-on to **0.9.132**.

### Shared / tests
- Extend `anim_sine_chain` multi-axis helpers and USD cache path tests.


## [0.1.20] - 2026-07-18

### Houdini
- **Node Preset Library**: insert dragged presets at the mouse network position; find open windows via `objectName` (avoids shiboken property errors).
- Adapter: resolve network insert point from screen mouse via `screenToNetwork`.


## [0.1.19] - 2026-07-18

### Houdini
- **Node Preset Library**: persist window size/position, reopen as a single instance after reload, and polish scrollbars.


## [0.1.18] - 2026-07-18

### Houdini
- **Node Preset Library**: category colors, richer UI, and drop Houdini network nodes into the library via MIME.
- Adapter helpers for Houdini node-path drag MIME (parse/select).

### Installer
- Exclude Blender add-on sources from the Houdini `monofx` install payload (shipped as separate ZIP only).

### Tests
- Add MIME payload and Node Preset Library logic coverage.


## [0.1.17] - 2026-07-18

### Blender
- Extract shared logic via **monofx_pipeline_common** (vendored in ZIP); fix Rig Scene list crash when a linked rig is outdated.
- Add **Manual / Current / Next** publish version modes for Geo USD and Anim USD Cache.
- Improve anim transform / sine chain tools and USD cache export/list UI. Bump add-on to **0.9.122**.

### Houdini
- Expand **Node Preset Library** (prefs, preview, favorites/recent roots, larger UI).
- Adapter: network-editor insert position helpers for tool placement.

### Shared / tests
- Broaden `anim_chains` numbering patterns and multi-chain seed helpers.
- Add/extend tests for anim chains, USD cache paths, and node preset library.


## [0.1.16] - 2026-07-05

### Installer
- Fix **Inno Setup AppId** collision with MonoStudio26 — updating Mono Studio no longer installs into `Documents\houdiniXX.X\monofx` after MonoFX Suite was installed first.

### Blender
- Bump add-on to **0.9.88**.


## [0.1.15] - 2026-07-05

### Blender
- Add **GitHub Releases updater** in add-on preferences (check/install from `monofx_pipeline_blender_v*.zip`); bump add-on to **0.9.86**.


## [0.1.14] - 2026-07-04

### Houdini
- Refactor **USD Batch Load** into `tools/fx/usd_batch_loader` (logic/ui/config) with shared `lop_usd_helpers`; independent horizontal LOP layout.
- Add **Node Preset Library** and **Restart Houdini** shelf tools (`library`, `restart` icons).
- Slim `anim_publish_loader` by moving shared LOP setup into `lop_usd_helpers`.

### Blender
- Fix material bake session `config` import; bump add-on to **0.9.84**.

### Tests
- Add logic tests for USD batch loader and node preset library.


## [0.1.13] - 2026-07-04

### Houdini
- Add **USD Batch Load** shelf tool and `file_usd` icon.

### Release
- GitHub releases attach Blender add-on ZIP (`monofx_pipeline_blender_v*.zip`) alongside `MonoFXSuite_Setup.exe`.


## [0.1.12] - 2026-07-04

### Maya tools
- Add Reference Manager, Position/Scale, Scale From Last, Render Preview, and USD Export updates.
- Shared Maya adapter improvements.

### Houdini
- Add USD Batch Loader (`apps/houdini/usd_batch_loader.py`, `tools/fx/usd_batch_loader`).
- Update anim loader HDA script.

### Blender
- Add `monofx_pipeline_blender` addon (pipeline tools, anim USD cache, rig linking).

### Shared / tests
- Add `apps/common` shared pipeline modules; `apps/blender` adapter.
- Add pytest suite for pipeline naming, paths, and tool logic.


## [0.1.11] - 2026-03-11

### Changes
- (describe changes)


## [0.1.10] - 2026-03-09

### Node Preset Library
- Improve UI layout and interactions (category/preset list, thumbnail handling) for better usability in Houdini.


## [0.1.9] - 2026-03-09

### Installer
- Switch to Modeler-style install: default to `Documents\houdiniXX.X\monofx` instead of Program Files / MonoStudio tools.
- Add Houdini version selection page with checkboxes; allow installing to multiple `houdiniXX.X` folders in one run.
- Install `packages/monofx.json` into each selected `Documents\houdiniXX.X\packages` so SideFX Launcher picks it up without env vars.
- Drop docs payload from installer (keep empty `docs` folder in install root for future usage guide only).


## [0.1.8] - 2026-03-09

### Docs
- Rules: add 13_icons.md; plans: node_preset_library updates.


## [0.1.7] - 2026-03-09

### Installer
- Set install path in NextButtonClick when leaving Install location page so Option A path persists on Select Destination Location.


## [0.1.6] - 2026-03-09

### Installer
- [Dirs]: explicitly create `{app}` so Option A path (`...\tools\MonoFXSuite`) and parent `tools` folder are created before copying files.


## [0.1.5] - 2026-03-09

### Installer
- Option A: if path from install_path.txt ends with `\_internal`, strip it so target is `{MonoStudio root}\tools\MonoFXSuite`.


## [0.1.4] - 2026-03-09

### Installer
- Option A (Under MonoStudio): read `%LOCALAPPDATA%\MonoStudio\install_path.txt`; if valid, pre-fill `{path}\tools\MonoFXSuite`, else `{pf}\MonoStudio26\tools\MonoFXSuite`.


## [0.1.3] - 2026-03-09

### Installer & MonoStudio integration
- Installer: add **Install location** page — Option A (under MonoStudio), Option B (user folder), Option C (standalone). Enables MonoStudio Settings → Updates to detect version and offer Download.
- Installer: include **VERSION** file in app root so MonoStudio can read installed version.
- Docs: `docs/plans/monostudio_extra_tool_feasibility.md` — checklist and implementation notes.


## [0.1.2] - 2026-03-07

### Changes
- (describe changes)


## [0.1.1] - 2026-03-07

### Changes
- (describe changes)


## [0.1.0] — 2025-03-07

### Installer & setup
- Installer tạo folder riêng `monofx` trong user Houdini (giống modeler): `Documents\houdiniXX.X\monofx\` với `config\Icons\`, `toolbar\MonoFX.shelf`; ghi `packages\monofx_shelf.json` (hpath = `$HOUDINI_USER_PREF_DIR/monofx`).
- Thêm script build: `build/build.ps1`, `build/build.bat` — chạy từ thư mục gốc: `.\build\build.ps1` hoặc `build\build.bat`.
- Output installer: `build/output/MonoFXSuite_Setup.exe` (không version trong tên file).

### Shelf icons
- Icon shelf có nền bo tròn, màu nền khác nhau từng tool (info: xanh dương, layers: xanh lá, replace: cam, palette: tím).
- Icon màu trắng, scale 0.65, nền full 24×24 — nền to hơn icon.
- Cập nhật cả `config/Icons/` và `toolbar/icons/` (Lucide-based SVG).

### Docs
- `docs/setup/inno_build.md`: hướng dẫn build bằng script.
- `docs/setup/modeler_structure_reference.md`: tham khảo cấu trúc plugin modeler.
- `docs/setup/monofx_user_prefs_example.json`: mẫu package cài kiểu user prefs.
- `docs/setup/houdini_setup.md`: cập nhật mô tả folder monofx và monofx_shelf.json.