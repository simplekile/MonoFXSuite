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
4. Split the scalp into growth regions (`lock_owner`), frozen until the user presses "Chia vùng".
5. Hairgen per lock from its own region, then clump, length, frizz. One node network, not one per lock.
6. Settings: defaults → group → lock, edited in the panel or on the HDA. Each edit is one undo step.
7. Display: Mesh / Guide / Hair preview (10%, at most 20 000 strands) / Hair full; colour by lock or group.
8. Optional deform by the animated hair mesh (Point Deform, as today), then cache per shot.
9. Publish the asset groom to `04_grooming/publish/vNNN/char_<name>_grooming_publish.usd`.

Not in v0.1: drawing locks, control points dragged in the viewport, Guide Groom brush layer, masks,
colour layers and melanin, Karma live preview, shot mode reading a publish, batch over shots,
custom team effects, Unreal export, sim and body collision.

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
`clump`, `length_mult`, `frizz`. Resolution for a lock: built-in defaults → `data.defaults` → its
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
| output strand prims | `lock_id`, `name`, `group`, `clump_id` | | For shading, selection, solo |
| output strand points | `Cd` | vector | Display colour only |

`lock_width` is the lock's width. Houdini's `width` stays the strand thickness for render. Never mix them.

## Processing order (fixed)

source hair mesh → spine and measure → (v0.2: redraw, transform, brush) → settings applied → region split
(frozen) → hairgen per lock (For-Each by `lock_id`) → clump → length, frizz → display colour / preview cut
→ deform by animated hair mesh (optional) → output.

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

Lock colours come from `logic.lock_color`, so the panel and the viewport agree.

## Shots (decided by test t02, `tests/t02_karma_hair_procedural/NOTES.md` in the sandbox)

Karma's `houdinihairprocedural` in Generate mode does not reproduce clump, frizz and skin attributes
from guides, so shots do not generate hair at render time. The asset publish carries full strands
(clumped, frizzed, with per-strand attributes); a shot deforms them by the animated hair mesh (input 2,
Point Deform) and caches, as today. The procedural's Deform mode passed and is the lighter option to
try later (publish animated guides only, deform the rest strands at render time).

`LockInfo`, `DetectReport`, `PublishResult` are dataclasses in `tools/fx/grooming/logic.py` (no `hou`).

## Rules every part follows

- Region split is frozen: it is stored in the node (a stash) and changes only when the user presses
  "Chia vùng". Adding, moving or deleting a lock never silently changes another lock's region; the panel
  shows "regions out of date" instead.
- Region rule (`logic.region_owners`, decided after the Helen test where nearest-root left 19/61 locks
  without hair): the scalp is subdivided bilinearly (`region_subdiv`, default 2) and each scalp prim
  belongs to every lock whose footprint covers its centroid (radius = `REGION_FOOTPRINT` 0.5 x the
  lock's measured root width), else to the nearest lock of its group. Stacked locks (Helen's fringe
  layers, roots 1-4 mm apart) share the patch and divide its density, so the scalp's strand count does
  not change; every lock gets at least its nearest prim. The root width is the widest cross-section
  over the first 10% of the spine.
- A lock's root is one end of its ribbon (the end nearer the scalp, found by two sweeps of distance
  along the mesh), not every mesh point near the scalp: that made Helen's curved caps grow strands in
  a cone. Scenes detected before this rule re-match "unsure" and need Detect again.
- Strands follow the lock's own mesh surface (`fit_to_lock` looks the offset up in `SURFACE_CLOUD` by
  along/across position, the piece kept apart in z), not an ellipse around the spine; `root_blend`
  (default 0.05) eases each strand onto its scalp root.
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
  and makes the rest faster. Publish still cooks every lock, hidden or not.
- Fonts and icons follow Houdini's UI size (its scale setting), plus a UI size setting of the panel's
  own. The current panel is too small to read comfortably.
- Several characters in one shot: how each is groomed, deformed and cached (one MONO Grooming per
  character, names and cache paths that cannot collide, caching them together or one by one).
- Isolate: show one lock or group alone (and back).
- Drag and drop to reorder in the layer tree, like Cinema 4D or Substance Painter: move locks
  between groups, change order.
- A lock does not yet follow its group's display (hiding a group should hide its locks).
- A hidden group is drawn dimmed in the panel, its row and every lock inside it.
