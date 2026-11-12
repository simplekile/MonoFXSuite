# MONO Grooming v0.1 (spec for the build)

The shared contract for everyone building v0.1. Discussion and rationale: the plan page
(https://claude.ai/artifact/TWs7WFd7DrCmb3wtaq3CkP) and the walkthrough demo
(https://claude.ai/artifact/7TyxPqNTkxuBvkp8P96WwK). Where this file and the page differ, this file wins
for v0.1. Change it only through the lead session, so parallel work stays on one contract.

## What v0.1 is

One Houdini SOP HDA, **MONO Grooming** (`mono::grooming::0.1`), plus a Qt panel, that replaces the
copy-pasted hairgen/hairclump network of `char_Helen_grooming_v007` (about 60 hairgen, 70 hairclump):

1. Inputs: scalp mesh (with UV), hair mesh (one piece per lock, prim `name` when present), optional
   animated hair mesh (same topology as the rest hair mesh).
2. Detect locks: one lock per hair mesh piece, a stable `lock_id`, a name, a group from the region.
3. Measure each lock: spine curve, width, thickness and twist along `curveu`.
4. Split the scalp into growth regions (`lock_owner`), frozen until the user presses Update regions.
5. Hairgen per lock from its own region, then clump, length, frizz. One node network, not one per lock.
6. Settings: defaults → group → lock, edited in the panel or on the HDA. Each edit is one undo step.
7. Display: Mesh / Guides / Hair preview (10%, at most 20 000 strands) / Hair; Color by lock or group (names as
   Houdini uses them, listed in `tools/fx/grooming/CLAUDE.md`).
8. Optional deform by the animated hair mesh (Point Deform, as today), then cache per shot.
9. Publish the asset groom to `04_grooming/publish/vNNN/char_<name>_grooming_publish.usd`.

Not in v0.1: drawing locks, control points dragged in the viewport, Guide Groom brush layer, masks
(density layers painted over the automatic one, blend modes like Substance Painter), colour layers and
melanin, Karma live preview, shot mode reading a publish, batch over shots, several characters in one
shot (cache paths per character and instance, see Publish and caches), custom team effects, Unreal
export, sim and body collision. What v0.1 decides automatically (Root to skin, thin skin under floating
mesh, the root spread) is the default that v0.2's redraw, brush and masks edit over, never a second
system beside them.

## Code layout

| Path | Owner | What |
|---|---|---|
| `tools/fx/grooming/model.py` | lead | Data model, JSON (de)serialise, settings resolution. No `hou`. |
| `tools/fx/grooming/logic.py` | logic | Lock matching on re-import, region split, publish paths and version rule, lock naming. No `hou`. |
| `tools/fx/grooming/config.py` | logic | Constants (attribute names, defaults, limits). No `hou`. |
| `apps/houdini/grooming_adapter.py` | houdini | Everything that touches `hou`: build and read the node, run detect / split / publish, read cooked lock info. |
| `tools/fx/grooming/build_hda.py` | houdini | Builds `otls/mono_grooming.hdalc` from code (run with hython), so the HDA is reviewable and rebuildable. |
| `otls/mono_grooming.hdalc` | houdini | Built output. The suite root is the package `hpath`, so Houdini loads `otls/`. |
| `tools/fx/grooming/ui.py`, `controller.py`, `__init__.py` | panel | Qt panel and its controller. The controller talks to the adapter only. |
| `toolbar/MonoFX.shelf` (one new tool) | panel | Shelf tool "Grooming": finds the MONO Grooming node in the scene (selected first), else creates one, then opens the panel. |
| `tests/test_grooming_*.py` | each owner | pytest, no Houdini. Houdini checks are hython scripts under the owner's sandbox test folder. |

## Data model (single source of truth)

Stored as JSON in a hidden multi-line string parm `groom_data` on the MONO Grooming node. A parm (not user
data) so that every change is undoable, saved with the hip and dirties the cook. The panel never keeps its
own copy beyond the current edit. `model.GroomData.to_json()` / `from_json()` own the format;
`schema` is an int, bumped with a migration in `model.migrate()` whenever the shape changes.

Settings keys (`model.SETTING_KEYS`): `density` (strands/cm²), `width_mult`, `thick_mult`, `twist_add`,
`clump`, `length_mult`, `frizz`, `root_skin` (cm of the spine bent down to the skin, only on locks whose root
floats: see the root rules). Resolution for a lock: built-in defaults → `data.defaults` → its
group's `overrides` → its own `overrides`. Measured values (width, thickness, twist, length) come from the
geometry and are multiplied / added by the resolved settings; they are never written into the JSON.

## Geometry contract

| Where | Attribute | Type | Meaning |
|---|---|---|---|
| spine prims | `lock_id` | int | Stable id from the JSON |
| spine prims | `name`, `group` | string | Lock name, group id |
| spine points | `curveu` | float | 0 root → 1 tip |
| spine points | `lock_width`, `lock_thick` | float | Measured cross-section (scene units) |
| spine points | `lock_twist` | float | Measured twist (radians) |
| scalp prims | `lock_owners` | int array | Locks growing hair on this prim (stacked locks share it) |
| scalp prims | `lock_owner`, `share` | int | First owner (-1 none), number of owners |
| scalp prims | `density` | float | Mean strands/cm² of the owners (each grows its density / share here) |
| output strand prims | `lock_id`, `name`, `group`, `clump_id`, `id` | | For shading, selection, solo |
| output strand points | `width` | float | Strand thickness (render) |
| display output prims | `Cd`, `Alpha` | | Display only (output 0): colour, see-through out of focus; never on output 1 or the publish |

Outputs: 0 **Display** is what the viewport draws: hidden and isolated-out locks are missing, the hair is
packed per lock with its colour inside, locks out of focus are see-through ghosts, preview display lowers
the density, and with Shot deform on it is the deformed display. 1 **Groom** is the groom itself and never
depends on the view: every lock that is not excluded, full density, only P and the contract attributes
above (`config.GROOM_ATTRIBS`), at rest, or deformed by the animated hair mesh while Shot deform is on.
Downstream nodes (a File Cache for a shot, SOP Import, a ROP, Guide Process) and the publish read output 1.

`lock_width` is the lock's width. Houdini's `width` stays the strand thickness for render. Never mix them.

## Processing order (fixed)

source hair mesh → spine and measure → Root to skin (v0.1, automatic; v0.2: redraw, transform, brush here) →
settings applied → region split
(frozen) → cache key per lock → hairgen, clump, length, frizz per lock (For-Each by `lock_id`, only the
locks that grow and are not cached) → every growing lock from the cache → display colour → deform by
animated hair mesh (optional) → output.

## Adapter API (the panel uses only this)

`apps/houdini/grooming_adapter.py`, every function main-thread and `hou`-only. The panel's controller takes an
object with these functions, so its tests run with a fake adapter.

| Function | Returns / does |
|---|---|
| `find_nodes() -> list[hou.Node]` | MONO Grooming nodes in the scene, selected ones first |
| `create_node(parent: hou.Node \| None = None) -> hou.Node` | New node wired to a selected scalp + hair mesh when it can tell which is which, else unwired |
| `read_data(node) -> GroomData` / `write_data(node, data, label)` | Parse / store `groom_data`; the write is one undo step named `label` |
| `lock_infos(node) -> list[LockInfo]` | From the cooked spines: `id, name, group, root, length, width, thick, twist, strands, region_area_cm2` |
| `detect(node) -> DetectReport` | Detect locks from the hair mesh, match ids against the JSON (logic.match_locks), write the JSON. Counts of ok / unsure / new / orphaned |
| `split_regions(node) -> None` | Recompute and freeze `lock_owner`, clear `regions_stale` |
| `set_display(node, mode, color_by, preview)` | `mode` in mesh/guide/hair_preview/hair; `color_by` in lock/group |
| `selected_lock_ids(node) -> list[int]` | Locks whose spines or strands are selected in the viewport (empty when none) |
| `select_locks(node, ids)` | Select those locks in the viewport |
| `publish(node, version: str \| None) -> PublishResult` | Writes the USD and `_grooming/`, refuses to overwrite; result has path, version, message |
| `publish_context(node) -> (scene_name, existing_versions)` | For the panel's version field (`logic.publish_version`) |
| `display_state(node) -> (mode, color_by)` | The node's display parms, shown when the panel opens |
| `set_isolate(node, lock_ids: list[int] \| None)` / `isolate_ids(node) -> list[int]` | Show only those locks (None / [] = all shown ones). No undo step, not restored with the scene |
| `set_strands(node, lock_ids: list[int] \| None)` / `strand_ids(node) -> list[int]` | Draw those locks as strands, not packed (the viewport shows each strand's width ramp only unpacked); "all" = the whole groom. No cap (a cap of 20 drew hair_base's 21 locks as bands). No undo step, not restored with the scene |
| `set_focus(node, lock_ids: list[int] \| None)` / `focus_ids(node) -> list[int]` | The panel's selection: those locks in their colour, the others see-through grey; clears the node's viewport selection. No undo step, not restored with the scene |
| `set_drag_preview(node, lock_ids \| None, factor=1.0)` | While a slider drags: those locks at `factor` of their strands (1 = real count), coarser |
| `undo(node, redo=False) -> str` | Houdini's undo / redo from the panel (Ctrl+Z, Ctrl+Shift+Z); the step's label, "" when none |
| `set_root_flip(node, lock_ids, flip) -> int` | Root at the piece's other end, one undo step, regions stale; returns locks changed |
| `set_excluded(node, lock_ids, excluded) -> int` | No hair for those locks (guide, mesh stay), one undo step, regions stale |
| `unit_cm(node) -> float` (optional) | cm per scene unit for the panel's measured values; else the node's `unit_cm` parm |

Lock colours come from `logic.lock_color`, so the panel and the viewport agree.

## Shots (decided by test t02, `tests/t02_karma_hair_procedural/NOTES.md` in the sandbox)

Karma's `houdinihairprocedural` in Generate mode does not reproduce clump, frizz and skin attributes
from guides, so shots do not generate hair at render time. The asset publish carries full strands
(clumped, frizzed, with per-strand attributes); a shot deforms them by the animated hair mesh (input 2,
Point Deform) and caches, as today. The procedural's Deform mode passed and is the lighter option to
try later (publish animated guides only, deform the rest strands at render time).

`LockInfo`, `DetectReport`, `PublishResult` are dataclasses in `tools/fx/grooming/logic.py` (no `hou`).

## Rules every part follows

- Region split is frozen: it is stored on the node's hidden geometry parm `regions` (inner nodes of a locked
  HDA cannot be set, so not a stash) and changes only when the user presses
  Update regions. Adding, moving or deleting a lock never silently changes another lock's region; the panel
  shows "regions out of date" instead.
- Region rule (`logic.region_owners`, decided after the Helen test where nearest-root left 19/61 locks
  without hair): the scalp is subdivided bilinearly (`region_subdiv`, default 2) and each scalp prim
  belongs to every lock whose footprint covers its centroid (radius = `REGION_FOOTPRINT` 0.5 x the
  lock's measured root width), else to the nearest lock of its group. Stacked locks (Helen's fringe
  layers, roots 1-4 mm apart) share the patch and divide its density, so the scalp's strand count does
  not change; every lock gets at least its nearest prim. The root width is the widest cross-section
  over the first 10% of the spine. Past the footprints (rule 3, `config.REGION_RULE`, decided
  2026-11-13): a prim goes to the lock whose hair mesh lies nearest over it, and locks whose meshes are
  within `REGION_MESH_SHARE_CM` of the nearest share it (layers lying on each other). A split made with an
  older rule is marked out of date when the scene loads.
- A lock's root is one end of its ribbon (the end nearer the scalp, found by two sweeps of distance
  along the mesh), not every mesh point near the scalp: that made Helen's curved caps grow strands in
  a cone. Scenes detected before this rule re-match "unsure" and need Detect again.
- Strands follow the lock's own mesh surface (`fit_to_lock` looks the offset up in `SURFACE_CLOUD` by
  along/across position, the piece kept apart in z), not an ellipse around the spine; `root_blend`
  (default 0.05) eases each strand onto its scalp root.
- Root spread (decided 2026-11-13, session 012; answers the OPEN `root_pull` question): roots lie evenly on
  the lock's region at the set density, and each strand gathers into its lock's shape over
  `ROOT_CONVERGE` x its root's distance from the mesh root. Where the lock's mesh floats over the skin
  (no part of it within `ROOT_FAR_CM`), its roots move to the lock's start and that skin stays thin on
  purpose, with a soft falloff, not a hard cut: a strand crossing the 1-2.5 cm gap is the spike / fuzz
  seen on Helen. The hand groom v006 does the same (8 % of the density under floating caps, 2 % under
  the fringe arches). The panel says so ("thin under floating mesh"), so the artist does not read it as a
  fault; in v0.2 density masks paint over it.
- A lock whose mesh root edge lies over `ROOT_GAP_CM` (0.3 cm) off the skin floats at its root (a mesh
  fault): Detect lists those locks with the gap in cm, and Root to skin bends the start of their spine down
  to the skin. It never changes a lock whose root touches the skin.
- Crown whorls (`logic.whorls`): a lock starting where 3 or more roots meet within 1.5 cm gets extra
  roots inside 0.7 cm of the whorl's centre, so the crown is as dense as v006 (~5,100 / cm²).
- Start extras (strands added round a lock's root so its first 3/10 holds its share of the mesh): their
  target follows v006 (start share worst 0.47), not a hand-set floor; OPEN until measured, since they
  cost +24 % cook on Helen at 0.5.
- QC limits (skill `grooming-check`) take the approved hand groom as the reference wherever it can be
  measured; a limit stricter than v006 needs a reason written next to it.
- The scalp and rest hair mesh are read at `rest_frame`, so only the shot deform cooks per frame.
- Re-import keeps ids: match by name, then root position on the scalp, then shape. Unsure matches are
  marked and need a confirm; locks that disappear go to `orphans` with their settings kept.
- Publish never overwrites silently. Version default = the `_vNNN` of the scene name; when that version
  already exists, or is lower than the newest publish, the panel proposes the next free version.
  File name fixed: `char_<name>_grooming_publish.usd`; tool data goes to `vNNN/_grooming/`.
- Nothing writes outside the scene's project (paths come from `$HIP`), and tests never write into
  `D:/Dropbox/Job/...`. Houdini tests use the sandbox copy `E:/01 Dev/sandbox/claude/grooming/project_helen`
  read-only; each part writes only under its own `E:/01 Dev/sandbox/claude/grooming/tests/<folder>/`.
- No modal dialogs (they block Houdini and the MCP bridge): results go to the panel's status line.
- Fonts in pixels and the text roles of `tools/fx/auto_material/ui.py` (`_font`, `ui._text`).
- GUI checks only on the secondary monitor; prefer hython. One session drives a GUI Houdini at a time.

## Backlog (user notes, 2026-11-11)

Panel and network, after testing the Helen sandbox scene:

- Sliders never take the mouse wheel: the wheel over the panel always scrolls the panel.
- Hiding, or editing one lock or one group, recooks only that part, not the whole groom, in every
  display mode (Mesh, Guide, Hair preview, Hair full). A hidden lock or group is not cooked at all
  for display (today it still grows hair and is only blasted at the end), so hiding is near instant
  and makes the rest faster. Publish still cooks every lock, hidden or not, and says so first when
  some are hidden: the panel names them (count and names) and Publish needs a second click to go on.
  No modal dialog (rule above): the warning sits in the panel next to the button.
- Fonts and icons follow Houdini's UI size (its scale setting), plus a UI size setting of the panel's
  own. The current panel is too small to read comfortably.
- (v0.2) Several characters in one shot: how each is groomed, deformed and cached (one MONO Grooming per
  character, names and cache paths that cannot collide, caching them together or one by one).
- Isolate: show one lock or group alone (and back).
- Drag and drop to reorder in the layer tree, like Cinema 4D or Substance Painter: move locks
  between groups, change order.
- A lock does not yet follow its group's display (hiding a group should hide its locks).
- A hidden group is drawn dimmed in the panel, its row and every lock inside it.
- Fixed 2026-11-12: the per-row Display (right click › Display on a lock or group) was stored in
  `groom_data` but never read by the HDA. Each lock now shows in its own mode (lock, else group, else
  the node's), mesh, guide and hair side by side; publish is always full hair.
- Fixed 2026-11-11: the small window that flashed up on every edit and ended slider drags was the
  setting row's Reset button, shown before it had a parent (not Houdini's cook-interrupt button).
- Changed 2026-11-12 (user feedback): the selection is shown as focus (selected locks in colour, the
  others see-through) instead of Houdini's highlight, and its rows say "editing"; a slider drag shows
  the real strand count (coarser strands while dragging); Ctrl+Z / Ctrl+Shift+Z work with the panel
  focused; I on another lock while isolated isolates it at once. Strands for the whole groom all the
  time was measured and left out: edits ~1.7x and hides ~5x slower.
- Added 2026-11-11, replaced 2026-11-12 by the view model below (selecting shows strands; no Enter,
  double-click or Esc for strands): strands. With Anim off the hair is packed, and the viewport draws a packed lock as
  a flat band of one width. Enter or double-click on a lock or group (right-click › Show strands) draws
  those locks unpacked, each strand thinning to its tip; Esc packs them again. Selecting alone does not.
  Also fixed on the way: Ctrl+Z after an edit undid the panel's viewport selection instead of the edit;
  isolate on / off left the viewport selecting another lock; with Anim on and locks selected in the
  viewport, the panel's poll failed the cook ("Infinite recursion in evaluation").
- UI pass for long working days (artist in it for hours, every action quick). Clear separators,
  a clear main / secondary hierarchy, colour only where it means something. Seen on the current panel:
  - The tree and the settings run into each other; settings rows have no separation; "Measured" is
    a small afterthought at the bottom.
  - Source chips (group, built-in) look like buttons and carry colour, so they compete with the
    setting names; a big reset button on every row adds noise (show it only when a value is set here).
  - A slider spans the whole width with its value box at the far right: long mouse travel, and
    each setting takes ~90 px, so only 7 fit on screen. Name, slider and value on one compact row.
  - The tree row packs badges (edited, new) and a "Mesh / auto" column whose meaning is unclear.
  - The Display and Colour menus in the bottom bar show a square instead of an arrow.
  - Measured values are raw scene units (Width 0.0466): show cm.
  - Colours: one accent for the main action (Publish) and the selection; status colours only for
    status; the rest neutral.

- View model 2026-11-12 (thinking as the artist at work): selecting is editing, so the selection shows its
  real strands and the rest are x-ray bands; X shows the selection inside the real groom; nothing
  selected is the whole groom as strands. The per-lock strands set (icon, Enter, button) is gone.
  Settings ⚙ holds font size and X-ray strength.
- Redesign 2026-11-12 (UI/UX review + Houdini names): view bar apart from actions, narrow docked layout,
  quiet icon columns, filter, Confirm all, the selection's action row, groom overview with keys, fading
  result line, labels renamed as Houdini names things (`tools/fx/grooming/CLAUDE.md` lists them). Checked in GUI Houdini at
  1240 / 700 / 500 px and UI size Largest (sandbox t39), with t36 / t37 again.

## Panel pass (2026-11-11, branch claude/grooming-panel-v2-d1d5c0)

Done in the panel (the HDA side, partial recook and hidden-not-cooked, is session 009's):
- Zones: top bar / layer tree / settings / action bar on their own surfaces with a line between.
  Settings are the main zone (window colour); title 22 px, measured shape as stat cells in cm at the top,
  then one compact row per setting. The tree lost its badge chips and its "Mesh / auto" column: ● edited
  (neutral), "unsure" / "new" in status colour, a row's own display mode only when it has one (click it or
  right click › Display).
- Size: Houdini's UI scale x the panel's UI size (Small 0.9 … Largest 1.5, saved per user). Checked in a GUI
  Houdini at scale 1.0 and 1.5 (`HOUDINI_UISCALE=100/150`), sandbox `tests/t21_panel_v2`.
- Wheel, hidden group, isolate, drag and drop, mixed, one undo per drag, publish warning: as the edge cases
  below propose. A drop on a group row: top fifth = end of the group above, middle = end of this group,
  bottom fifth of an open group = first in it. Groups move between groups only.
- Display / Colour menus: the arrow is an image (Houdini drew Qt's border-triangle as a square); checked
  menu items show a check image, unchecked none.

## Edge cases for the backlog (proposed answer, or OPEN when it needs the user)

Hide, isolate, partial recook
- A hidden lock shares scalp prims with a visible one (stacked fringe locks): the visible lock keeps
  its share of the density; hiding never changes another lock's strand count.
- Every lock hidden: the node outputs empty geometry with a status note; deform and cache accept it.
- Group hidden, one of its locks switched on: the group wins, the lock's eye shows "hidden by group"
  (greyed), its own state is kept for when the group is shown (C4D-style).
- Isolate is a temporary view: not saved with the hip, not undoable, cleared by Esc or a second
  click; hidden states underneath stay as they were. Publish while isolated warns like hidden locks.
- Partial recook means a cache per lock, keyed by its inputs (mesh piece, region, resolved settings,
  display mode). Editing a group recooks that group's locks; a default edit recooks all; the clump
  (one hairclump for the whole groom) must work per lock too, or every edit still pays for it.
- Showing a lock that was never cooked costs one lock's cook, not the groom's.
- Slider drag: one undo step per drag, the lock recooks on release (or on idle), not on every tick.

Reorder and move (drag and drop)
- Order in the tree is stored in the groom data and changes nothing in the hair.
- Moving a lock to another group: its own overrides stay; values it took from the old group now come
  from the new one, and the panel says which changed. Regions may depend on the group (nearest lock
  of its group): mark regions out of date, never re-split silently.
- Dropping on Defaults, on itself, a group into a group (no nesting in v0.1), several locks at once,
  a drop while a cook runs: refused or queued with a status note, never half applied.

Detect and the hair mesh
- A lock split into two pieces, two merged into one, a piece renamed, duplicate or missing names:
  match rules give "unsure" and ask; settings follow the confirmed match.
- Piece with no thickness (single-sided card), closed tube, open ribbon, very low-res (fixed:
  measure_samples), very short, very long: all measured; the check covers each kind.
- Piece touching the scalp at both ends (a loop, hair tied back) or at none (an accessory, a floating
  strand): Detect takes the nearer end and flags the lock; the user decides per lock: flip which end
  is the root, exclude the piece from hair, or (later, with drawn locks) give it a guide of their own.
  A root that floats a little (a cap whose mesh starts in the air) is warned and bent by Root to skin.
  Done in the model and the HDA (`Lock.root_flip`, `Lock.excluded`, adapter `set_root_flip` /
  `set_excluded`), kept through re-Detect; the panel buttons are the panel's.
- Scalp without UV, scaled or moved objects, scenes not in metres (`unit_cm`): detect warns.
- Animated hair mesh with another point count or order than the rest mesh: refuse the deform with a
  message, never deform with the wrong points.

Publish and caches
- Publish always writes the full hair (not the preview, not the deformed shot pose, hidden and
  isolated locks included, with the warning), whatever the panel shows.
- Version already published, scene name without a version, path not writable, disk full: say so in
  the panel, nothing half written (write to a temp name, rename at the end). NOT DONE yet: v0.1 work.
- (v0.2) Several characters in a shot: one node per character; cache paths carry the character (and an
  instance number when the same asset appears twice), so two Helens never write one file. Caching
  one, several or all; one failing does not stop or corrupt the others; frame ranges per character.
- The same character several times in one shot (clones of one asset, same groom) is normal, and so
  are variants (one asset, different grooms). Each instance has its own animation, so its own deform
  and cache, named by instance; the groom publish they read is shared (variants read their own).
  Instances that share one animation (exact copies, offsets only) can share one cache and be
  instanced, instead of deforming and writing the same hair again.

Panel
- Long names, 200+ locks, a narrow docked panel, Houdini UI scale 0.75-2 plus the panel's own size.
- Node deleted, HDA missing, the hip opened read-only, two panels on one node: the panel shows the
  state and disables what cannot work; nothing raises into a Python error box.
- Several locks selected with different values: the field shows "mixed"; an edit sets all of them.
- Lock colours (colour by lock) must not reuse the status colours (new, edited, stale, error).

## Partial cook (decided 2026-11-11, session 011)

- Each lock's hair (hairgen, fit, clump, length, frizz) is cooked once per state of its inputs and kept
  per lock in the adapter's `LockCache` (memory only, per node and display mode, last 2 keys a lock so
  undo finds the previous hair). The key (`lock_keys`) digests the lock's spine with its resolved
  settings, its frozen region (sums per lock computed in PREVIEW), its mesh piece's lookup cloud, the
  loop's parms, the display mode and the preview factor. Colour, visibility and isolate are not in it.
- Only locks that grow (shown and not excluded) and miss the cache go through the For-Each; `hair_cache`
  merges every growing lock. Output 1 (Groom, and publish) has its own keys (every lock not excluded, full
  density, no drag) and its own copy of the loop through the same cache, so it shares the strands of locks
  the display shows as full hair and cooks only when read (decided 2026-11-12, t50). An edit of one lock recooks
  that lock; a group edit its locks; a default or an Advanced parm every lock.
- Hairclump runs per lock on the lock's own region. Clumps never crossed locks (`clumpid` = lock),
  so the look is the same; `clump_id` = lock_id x 100 000 + the lock's clump keeps ids unique.
- Preview: a capped factor snaps down to 0.8^k, so a density edit does not move it (it is in every key).
- Visibility: a lock is shown when its eye and its group's are on; the group wins, the lock keeps its
  own state. Hidden locks keep their region (also in the provisional split), so hiding never changes
  another lock. Isolated locks show even with the eye off; isolate is a hidden parm set with undo off,
  cleared on load (OnLoaded).
- Excluded locks keep guide and mesh, grow no hair, are not published; Update regions gives their scalp to
  the others. A root flip reverses the spine after the lock ids are known (Detect matches on the
  measured root, so the flag survives re-Detect); the lookup cloud stays on the measured spine.
- Measured on Helen (hython, t20): see the session report; hair full one-lock edit 9.5 s -> about 1 s,
  hide 9.5 s -> about 0.3 s, isolate 0.03 s.

## Anim input and playback (decided 2026-11-11, session 011)

- Input 2 takes the animated hair mesh unpacked (as before) or a USD Import left packed: the HDA unpacks
  only the gprims named like the rest hair mesh's prims (name, path or last path part), points only, no
  primvars. Point counts must match the rest hair mesh, else no deform and a warning (edge case above).
- Point Deform captures once at rest (`deform_capture`, time independent) and only deforms per frame.
  Hair full stays ~1 s a frame on Helen (the deform of 4 M points); fewer neighbours (`maxpt`) moved
  points up to 2.6 cm, so the quality setting stays.
- While playing (node parm, default Hair preview): playback draws min(Display, While playing), back on
  stop; Same as Display turns it off. Never applies to publish or to caching a shot by frames in hython.
