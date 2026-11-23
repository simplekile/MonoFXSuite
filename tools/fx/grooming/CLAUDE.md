# MONO Grooming (Houdini, `tools/fx/grooming/` + `apps/houdini/grooming_adapter.py`)

Notes for working on MONO Grooming, moved out of the suite's root `CLAUDE.md` (2026-11-13) so sessions on
the other tools do not load them. The contract is `docs/plans/grooming_v0_1.md`, the next version's
plan `docs/plans/grooming_v0_2.md` (masks, lock redraw, brush); read their scope before proposing a feature. v0.2 work
runs by the roles and gates in that plan ("How the work runs": manager, executor, checker, the test ladder,
the acceptance script per part, the GUI lock). Claude Code loads this file when it works on files in `tools/fx/grooming/`; when
working only on `apps/houdini/grooming_adapter.py` or the `grooming-check` skill, read it first.

- Contract for v0.1: `docs/plans/grooming_v0_1.md` (scope, data model, geometry attributes, processing
  order, adapter API). One SOP HDA `mono::grooming::0.1` built from code by `tools/fx/grooming/build_hda.py`
  into `otls/` (the suite root is the package `hpath`).
- What the user set lives as JSON in the node's hidden `groom_data` parm (`model.GroomData`): a parm, so
  edits are undoable and saved with the hip. Measured lock shape lives on the geometry, never in the JSON.
  Settings resolve built-in â†’ `defaults` â†’ group â†’ lock.
- A lock is spine + `lock_width` / `lock_thick` / `lock_twist` along `curveu`; the hair mesh is only an
  input. `lock_width` is the lock's width; Houdini's `width` stays the strand thickness.
- Growth regions are frozen in the node and change only on Update regions: editing one lock never changes
  another lock's look without telling. Rule (`logic.region_owners`): the scalp is subdivided bilinearly
  (`region_subdiv`), each prim belongs to every lock whose footprint (0.5 x widest head width, centred on
  the root moved onto the skin: `_roots_on_skin`, a cap whose root lies on another cap sits ~1 cm up and
  its footprint covered no skin) covers its centroid, else the lock of its group whose hair MESH lies nearest over it (HDA node `region_mesh`, layers
  within `REGION_MESH_SHARE_CM` share), else the nearest root; stacked locks share prims (`lock_owners`,
  `share`) and divide the density. Nearest-root alone left 19/61 Helen fringe locks bare (roots 1-4 mm
  apart), and past the footprints it gave scalp to locks lying elsewhere: 0.8 cm fringe locks owned 8 x 8
  cm, and with roots at the set density 59 % sat over 1 cm from their own mesh, under a neighbour's (by
  mesh: 25 %). Update regions also records whorls (`logic.whorls`: a lock with 2+ other roots within
  `WHORL_RADIUS_CM` 1.5 of its own starts at one; detail `whorl_locks` / `whorl_centres`, read per lock by
  `whorl_tag` into the cache key). The frozen split is read back by position (`nearpoint`), never by prim
  number; it records its rule (detail `region_rule`, `config.REGION_RULE` 3), and a scene split by an older
  rule opens with regions out of date and the reason (`mark_old_regions` in OnLoaded): existing scenes
  need Update regions.
- Strands per lock = density x max(its share of the scalp, its own cross-section) (`logic.lock_strands`,
  same rule in the HDA's `region_frame`): fringe locks whose roots converge on one spot still get hair
  matching their mesh. In VEX, type every `prim()` read used in arithmetic (`float a = prim(...)`):
  inside an int expression it returns int and areas of 0.03 cmÂ² became 0.
- Partial cook: each lock's hair is cooked once per state of what it reads and kept in a per-lock
  cache (`grooming_adapter.LockCache`, on `sys` so a module reload keeps it). `lock_keys` (Python SOP,
  hair modes only) digests per lock its spine and resolved settings, its region (`region_keys`, 9 sums
  per lock from PREVIEW), its mesh piece (`surface_keys`), the loop's parms, display mode and preview
  factor; colour and visibility are left out, so they recook nothing. Only locks that grow and miss go
  through the For-Each (`to_cook`); `cache_store` keeps each, `hair_cache` merges every growing lock
  (one copy: 4 M points in ~0.25 s, most of what a hide costs). Earlier states of a lock are kept while
  the node's "Undo cache, GB" lasts (round 3 below; it was the last 2 keys), so undo finds the previous hair. Hairclump, length, frizz run inside the loop on the lock's own
  region (`clump_id` = lock_id x `CLUMP_ID_STRIDE` + its clump): a whole-groom node after the cache
  made every edit pay for 116 k strands again. A capped preview factor snaps to 0.8^k steps (it is in
  every key; cap / total moved with any density edit). Helen hair full: one lock edit 9.5 -> ~1 s,
  hide 9.5 -> 0.3-0.4 s, isolate 0.03 s; a group edit still costs its locks (20 locks ~4.8 s).
- Two outputs (labels in the DialogScript, `config.OUTPUT_LABELS`): 0 **Display**, what the viewport
  draws (hidden / isolated-out locks left out, packed, coloured, ghosts with Alpha, preview density,
  deformed with Shot deform on); 1 **Groom** (`GROOM`), the groom itself whatever the view: every lock
  not excluded, full density, only P + `config.GROOM_ATTRIBS` (width, lock_id, name, group, clump_id,
  id), deformed whenever a matching anim is wired (Shot deform drives only output 0; `groom_use_deform`
  reads `anim_wired`, `capture_flag(groom=True)` captures its locks whenever wired), else at rest; it
  cooks only when read (since round 3 its locks are never captured in the loop: see "Undo cache" below; the
  sentence above about `capture_flag(groom=True)` is how v0.1 did it). Anything downstream (File Cache, SOP Import, a
  ROP, Guide Process) reads output 1; the review (t48 P0-1) found output 0 changing with every hide,
  isolate, focus and Display. Output 1 has its own keys (`groom_keys` = `cook_lock_keys(groom=True)`:
  factor 1, no drag, every lock not excluded) and its own copy of the per-lock loop (`groom_*`,
  `build_hda._copy_loop`: copies whatever the loop section holds and renames paths to its nodes, never
  a `ch("../x")` channel reference: `ch("../strand_smooth")` names the HDA parm, renamed it read 0 and
  the copy's strands came out unsmoothed, kink p95 26 -> 82 deg)
  through the same LockCache: a lock the display shows as full hair has the same key, so both share
  its strands. It cooks only when read: display cooks never touch it, no parm is set during a cook
  (the old publish toggled `cook_all`, now unused and kept hidden for old scenes). Rejected: one loop
  fed by the union of what both outputs miss (Houdini cooks a node once per state, so every display
  edit in preview, or of a hidden lock, would also grow the full hair: +0.3-0.5 s a lock, t50).
  `hair_cache` / `groom_cache` keep their last merge frozen by the locks and keys in it
  (`MERGED_LOCK`): merging that one geometry costs 0.006 s against 0.23 s for 61 locks, so an eye,
  isolate or Display change costs output 1 ~0.03 s. A node wired to output 1 cooks only output 1;
  `node.geometry(1)` from Python cooks output 0 too (tests read through a downstream null). t50 (hython
  Helen, `t50_groom.py`): hide, group eye, isolate, focus + strands, X-ray, all strands, colour by,
  preview, guide, drag preview change no byte of output 1; reading it after them 0-0.05 s, 0 locks
  cooked; after an edit in full display 0.25-0.3 s (the merge, 0 locks), in preview or of a hidden lock
  0.3-0.6 s (1 lock); cold, its own loop cooks all 61 locks in 11 s, equal to the display loop's (ids
  exact, P within 0.08 mm: the per-lock loop itself differs by up to 0.1 mm from one cook to the next,
  so compare copies with a tolerance, never bytes); deformed it equals the previous deform within
  0.5 mm; Deform on, a frame of output 1 costs ~1.1 s (hair full) and a view change ~0.9 s, only when
  something reads it. Display timings unchanged (hide 0.04-0.06 s, select 0.01-0.05 s).
- Hidden locks (the lock's eye, or its group's: `Lock.shown`, the group wins and the lock keeps its own
  state) and locks isolated out are not cooked for display at all; the Groom output (below) cooks
  every lock. Hidden locks keep their region (the provisional split ignores visibility), so hiding never
  changes another lock's strands. Isolate (`set_isolate` / `isolate_ids`) is the hidden `isolate_ids`
  parm, set with undo off and cleared by the HDA's OnLoaded: a temporary view, not restored with the
  scene; isolated locks draw even with their eye off.
- Per lock `root_flip` (root at the piece's other end) and `excluded` (no hair, not published, guide
  and mesh stay) are in the model, kept through re-Detect (matching uses the measured root, SPINES_RAW),
  set by `set_root_flip` / `set_excluded` (one undo step, marks regions stale; Update regions skips excluded
  locks). A flip reverses the spine after `assign_locks` (`spine_flip`); the surface cloud stays on the
  unflipped spine, so `fit_to_lock` reads it at 1 - u and the other thickness side. In the panel: the
  lock row's right-click menu ("Root at the other end", "Leave out of the hair", several locks at once);
  the row says "flipped" / "no hair" in its status column (neutral colour, the name is never shortened)
  and an excluded lock is dimmed.
- Interactive feel (judge it in GUI Houdini, until the viewport has drawn: `tests/t24_feel/t24_gui.py`
  in the sandbox; hython numbers missed all of the below):
  - Display without a shot deform is one packed prim per lock (`hair_packed`, embedding the cached
    frozen strands, coloured per packed prim). The merged 4 M points re-uploaded the whole groom to the
    viewport on every edit and hide. `HAIR` (merged) stays for the display's deform; tests and QC read
    strands from output 1 (`GROOM` / `GROOM_REST`), not from the display.
  - The viewport draws a packed lock as a flat band of one width: Houdini ignores curve width inside
    any packed prim (Pack SOP fragments, packed disk too). The view follows the work, nothing to switch
    or remember (the user: a strands set of its own, kept while the selection moved on, left grey solid
    locks over the one being edited): the selected, drawn locks are their real strands (unpacked, width
    ramp) and the others see-through bands (packed: only packed geometry can be see-through); **X**
    (view bar X-ray) turns the bands into real strands to judge the selection inside the groom, the
    selection still edits; nothing selected, All locks, or a selection that is all that is drawn shows
    the whole groom as strands (`set_strands(node, STRANDS_ALL)`, hidden parm `strand_ids` = "all").
    No cap on how many (a cap of 20 drew hair_base's 21 as bands while hair_bang showed strands). `controller.
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
    line ("Cooking: â€¦", a moving bar) is armed for `BUSY_DELAY_MS` (150), and the node is cooked there
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
  the node's); `lock_shown` turns it into `disp` (lighter while playing) and
  `grows` (only preview and hair grow). `lock_keys` gives each lock its `strand_factor` (preview or
  full; the node's mode is not in the key, so a lock keeps its cache when the node's Display changes).
  The display merges mesh, guide and packed hair (switches `mesh_in_use` / `guide_in_use` skip a branch
  no lock uses: colouring 196 k mesh polygons on every edit doubled the cost). The packed hair carries
  its colour inside (a copy per lock and colour, in the hair cache): the viewport ignores a packed
  prim's Cd and drew the groom white.
- Shot deform: toggle `shot_deform` (panel: the Anim button, shown when an animated hair mesh is wired;
  no undo step). Off is the main mode: the default, and OnLoaded turns it off in the UI only
  (`loaded_resets(hou.isUIAvailable())`: a hython / farm job caching output 1 kept getting the rest groom
  on every frame, t56) (the user groomed a scene
  saved with it on: every lock drawn as strands, focus only dimming, so select looked like strands /
  isolate). GUI tests open scenes as saved (t36), not with the deform forced off. Hidden `anim_wired` / `deform_active`. With it on, every edit deforms all 4 M points
  (~1.2 s), so grooming is done with it off (edits 0.1 s); with it on a drag applies on release. Each lock is captured to the rest hair mesh inside the per-lock loop and cached
  with its strands (`lock_capture`, per-lock `do_capture` in the key) **only while the deform runs**:
  capturing every full-hair lock whenever the anim was wired held ~800 B a point (Helen, anim wired:
  5.8 GB after a cook, 9.5 GB after an All-locks edit; now 2.1 / 2.7 GB, t49). The first Deform on
  regrows the groom once (~12 s, was 1.7 s); frames and the deformed hair are the same (max 0.5 mm off).
  (Since t65 the display captures outside the loop too, as output 1 does: no lock is captured in the loop,
  Deform on regrows nothing, and the deformed hair is kept by its state. See the t65 notes below.)
  The packed display's coloured / see-through copies never carry the capture (`_display_copy`);
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
- Hair QC also measures roots against density, the skin between locks, the width profile along each lock
  against its mesh, the hair's share at each lock's start, folds, hair turned off its lock and hair outside
  its lock (grooming-check). Decided (the user, 2026-11-13, plan "Root spread"; was the OPEN `root_pull`
  question): `root_pull` (v0.1, 0.85) gathered each lock's roots into its mesh's root cross-section (bases
  20-30x denser than set, scalp between them bare); roots now lie evenly at the set density where a lock's
  mesh lies within reach of the skin, and where it floats higher than `root_far_cm` (0.5, fading over +-50 %)
  they start the lock, so that skin is thin on purpose, as the hand groom v006 does (its density over what the
  regions ask, against the mesh's height over the skin: <0.3 cm 1.7, 0.3-0.5 0.50, 0.5-0.7 0.35, 0.7-0.9
  0.11, over 1.1 cm ~0; t52). Strands that crossed that 1-2.5 cm gap were the spike / fuzz / standing strands
  (hair_base_08 / 11 / 17) and the fringe's fin; even roots under floating caps (9593a15) left outside-the-lock
  0.53, Root to skin alone did not help past the root. The panel's measured cells say "Thin under floating
  mesh" (cm2, falloff-weighted, from `owner_dist` that Update regions records per owner), and the skin check
  leaves that skin out (Helen: 359 cm2, 304 thin, reported apart). Rejected on the way: a fixed share of each
  lock's roots moved to its start (7e33860: 60 % of roots, skin between thin), even roots everywhere (fringe fan
  2.3-3.9x, fin), rising at most 20-30 deg (worse), start extras at 0.63 (+23 % strands, +24 % cook).
  Helen (t53 k1; v006 / v0.1 / now, same skin and split for all): strands 86,338 / 118,380 / 118,705; start
  share worst 0.47 / 0.83 / 0.56 with no start extras (START_TARGET 0.47 = v006 asks none on Helen); outside
  worst 0.97* / 0.25 / 0.27 (back locks' tenth 8, as v0.1); turned 0.78* / 0.05 / 0.08; root clumped 0.32 / 0.75
  / 0.04, spacing 0.51 / 0.12 / 0.84; whorl densest 1 cm disc 18.6 % / 8.1 % / 18.7 % of roots (5,104 / 3,042 /
  7,059 per cm2). *v006 per lock is not measurable (a guide groom: its strands do not follow the cards).
  QC limits carry v006's value and a reason where they are stricter. Cook of the full groom (output 1),
  alternating with v0.1's HAIR (cook_all): median 9.17 vs 8.52 s, +7 % (pairs 0-23 %, a noisy machine).
  Root to skin (`root_skin`, cm, default 3) stays for locks whose mesh root edge floats over `ROOT_GAP_CM`
  (0.3; `root_gap`, the points in the first 3 % of `dist` from the root band nearest the skin): 25 Helen locks
  (hair_base_01/02/04/06-18, upper fringe layers), bent 0.43-1.36 cm, no lock touching the skin moved; Detect
  lists them with the gap in cm.
- Workflow GUI check (t46): drag ticks ~0.43 s (the first 2.5 s), release 0.7 s, undo 0.47 s, Deform
  frames ~1.5 s (first 4.4 s), publish 0.7 s with 118,380 strands and only contract primvars. GUI tests
  cannot play the timeline inside one step (Houdini's playback runs in its own loop): start it in one
  step, read it in the next (t47: frames timed by a playbar callback, cookCount of every inner node,
  perfMon per node; a step that reads the 118 k-prim output mid-play adds a ~0.9 s gap of its own).
- Playback (t47, GUI Helen, 30 fps realtime): with Deform off nothing is time dependent and nothing cooks
  per frame; the whole groom as strands, hair full, plays at the cap (28.5-28.8 fps, one lock selected
  the same). t46's "3.3 fps with Deform off" did not reproduce (the same harness again: 24 fps); it is
  the Deform-on number. Deform on, per frame (Hair preview, 422 k points): the scene's anim input 125 ms
  (`shot_anim_usd` unpacking the whole character 86 ms + a blast 37 ms), `deform` 101 ms, GPU draw
  ~21 ms: 3.7 fps; with the USD Import left packed (the node unpacks only the hair gprims) 6.1 fps;
  While playing Guide 5.4 fps; hair full 1.0 fps (the deform of 4 M points ~0.76 s).
- The first drag tick's 2.5 s did not come back (t47, same scene, lock hair_back_04, same commit; 5 GUI
  runs: t46's order with the hip saved first, a freshly built HDA, two drags a run): first tick 0.32-0.38 s
  (cook 0.19-0.24 s, the same as later ticks; hython 0.25 vs 0.21 s), later ticks 0.17-0.28 s, release
  0.5-0.6 s. What the first tick does add, every drag, is ~0.13 s of viewport draw (strands going from 46 to
  13 points). The 2.5 s was most likely the machine (t46's later ticks were 1.8x slower too): measure a tick
  against select before calling it a regression. A real mouse drag in a GUI test does not cook: the viewport
  cooks on Houdini's own idle loop, which a test's `processEvents` pump never reaches.
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
  Root spread (`root_spread`, a detail wrangle before `fit_root`): roots stay where hairgen scattered
  them (`root_pull` 0); each strand joins its lock at `fit_u0`, the `pu` of its own mesh's nearest point
  to the root (a lock lying over its region takes the strands rooted under it there: sent to the root
  end, Helen's fringe folded 11 %), the joins stretched so the earliest starts at u 0; (s, t) is the
  rank of the root's offset across the lock at u0, inside strips of sqrt(n) sorted by u0 (an even
  spread that keeps neighbours together: a random (s, t) crossed strands; ranking along the region's
  axes mixed along and across on caps). The strand runs u0 -> tip and leaves its root over
  `fit_blend` = max(`root_blend`, `root_converge` x offset / length), at most half.
  Root steps: `region_frame` (detail: frame, footprint, whorl_n, own_n), `region_join` (prim, parallel:
  where the strands of each region prim join, and `root_far`), `region_start` (detail: start_x),
  `root_pick` (detail: picks whorl roots and start extras at random among hairgen's, so the lock's own roots
  stay even; lays out the start roots), `root_place` (prim: `root_at`, raw join `fit_u0`, `rx` / `ry`),
  `root_spread` (detail: stretch and ranks). Start extras (`start_extra`) are strands ON TOP of the lock's
  count, as many as bring its first 3/10 to `start_target` (0.47, v006's worst) x the mesh's share there,
  estimated from the region's joins; on Helen none is needed any more. Own roots keep their
  place: a fixed share of them moved round the root (7e33860) left the skin between locks thin. Roots under
  floating mesh (`region_join` `far_w`: smoothstep of the lock's mesh height over the skin from 0.25 to 0.75 cm
  at `root_far_cm` 0.5, `ROOT_FAR_SOFT` 0.5; a root moves with that chance) start the lock, for every lock,
  and the start-share estimate counts them as full length.
  **Latest join** (setting `join_limit`, the user's decision 2026-11-23, a per-group override like the others): an own
  root whose join would fall past this share of the lock starts the lock too, laid out with the far roots. Default 1
  (off: every lock as v0.1, r1 byte-equal, grooming-check unchanged). It runs in `root_pick` with each root's own
  join, computed as `root_place` will (own piece's nearest `pu` on the mesh as modelled, input 3; inside the footprint
  the spine's nearest place), before the roots are laid out: not in `region_start` / `region_join` (a region prim's
  centre joins elsewhere than its roots: on hair_bang_02 / 03 it moved none of their late roots), not in `root_place`
  (a late root kept in place but joined at the start runs back up the lock, a hairpin). root_spread's stretch leaves
  the join as it is once the lock has a start root, which every root it moves becomes. Why a setting and not a rule:
  the fringe's tuft (hair_bang_19 / 20: 36 % of strands joining 0.4-0.9 along, 0.39 of the lock's length) and the caps
  lying along the scalp (42-46 % late, 0.75-0.86 of their lock) cannot be told apart by length or skin distance
  (t79 report 9.11). Helen's fringe at 0.3: no strand starts past 0.3 on bang_02 / 03 / 19 / 20, other groups
  byte-equal, counts unchanged; their own skin goes 22 % -> 81 % bare (no root within 5 mm) (v006: 97 %), so grooming-check's
  `skin_thin_share` 0.017 -> 0.128 and `lock_skin_thin_worst` 0.031 -> 0.414 fail their limits (0.05, 0.2; at 0.5:
  0.101, 0.341). The limits were not moved: that is the artist's trade on that group (t79 report 9.13).
  grooming-check (3a84bbe) leaves skin owned by a lock with Latest join under 1 out of skin_thin_* and judges it on
  `latest_skin_uncovered` (no hair point within 5 mm, bare at the skin's surface, not what a camera sees; at most
  0.05): fringe at 0.5 0.003 pass, at 0.3 0.077 fail (t79 9.14); hair over the skin further up is not counted (t84).
  Start roots are laid out as one sunflower on a disc round the lock's root at up to
  `START_DENSITY_MAX` (6) x its density, each point moved onto the region (a point off it is dropped, the
  disc grows to at most 3x: grown without bound it reached skin 4 cm away, hair_bang_03, and its strands ran
  back in a hairpin); extras with no place are dropped. Footprint roots join at the spine's nearest point,
  never behind it (sent to u 0, the half of the footprint ahead of the root made small hairpins: the crown
  caps' fuzz in their third tenth, turned 0.36). Joining strands rise over `root_converge` (3) x their
  offset (at 1 they rose straight up to the floating meshes: spike / fuzz, turned 0.2-0.27), starting ones
  over `root_converge_start` (1). A lock starting at a whorl gets `whorl_n` = `whorl_fill`
  (0.3) x density x the cross-section of its first `START_SPAN` (0.3) extra strands on top of its count,
  rooted on a sunflower within `WHORL_DISK_CM` (0.7) of the whorl's centre (`whorl_root`); whorl roots and
  start extras are left out of the root and skin checks, counted apart. With the crown's start extras the
  densest 1 cm disc is 18,111 roots, 5,765 / cm2 (v006 16,035 / 5,104). The crown shot keeps a light patch
  where the caps meet at the whorl; v006's crown shot has the same. Raising the density attribute in the
  footprint did nothing: hairgen's relax evens density out. `root_reach_cm` (0) can bring every far root
  closer. Strand count uses the lock's widest band anywhere (the first quarter gave
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
  detect 2.6 s, split 4 s, publish 5 s / 50 MB (47â€“56 s before regions were frozen). GUI checks run Houdini with a startup script on the secondary monitor and grab the panel.
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
- While playing (`play_display`, default Hair preview): during playback with Shot deform on the node
  draws min(Display, While playing) through the hidden `display_eff` expression (every inner reference to
  the mode reads it, the cache key too); the adapter's playbar callback (installed once by OnCreated /
  OnLoaded, UI only) sets the hidden `playing`, undo off, only on nodes whose deform is on
  (`playing_flag`; `set_shot_deform` mid-play follows). With the deform off it changes nothing: playback
  cooks nothing per frame, and switching to preview recooked 24 nodes on Start and on Stop (0.3-0.6 s
  each) and, the first time, regrew every lock's preview (Helen 2.8 s), for no gain. Publish and the
  Groom output never read it.
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
- Panel layout (2026-11-12 redesign): top bar (node, asset, Settings âš™: Font size and X-ray, saved per user; Dock), then a view bar (Display,
  Color by, Deform, Isolate: viewing never sits next to an action that writes), the tree (filter, a Confirm
  all line while locks are new / to check, banner, rows), the settings (title, subtitle with what the
  viewport does with the selection, toggles Strands / Isolate / Hidden / Flip root / Exclude in a `_WrapRow`
  that wraps to the width, measured cells, settings), the action bar (loading, result line that fades
  after `MESSAGE_MS`, Detect locks, Update regions, version, Publish). Nothing selected shows the whole
  groom and the keys. Below `NARROW_PX` (760 x scale) the tree sits above the settings, both bars stack,
  rows go compact and cells two a line; the floating window's minimum is 400 x scale. A width-dependent
  widget wraps itself on resize (`_WrapRow`): building to a measured width failed, the layout had not
  given the column its new width yet. The eye is painted by `_IconDelegate` (`ROLE_ICON`) and always shows:
  drawing it only on hover hid the control used most (the user asked why it vanished). The first Detect marks no lock "new" (every row would say it).
- Inheritance in the panel: the defaults level is the tree's root group **All locks** (`ALL_LOCKS`), the
  groups sit inside it (the data still keeps `defaults` apart; only the view nests). A setting's source
  column names the level an inherited value comes from: the group by its name, All locks, or "tool
  default" (`model.BUILTIN_DEFAULTS`). On All locks or a group a last column says whether the levels
  below follow ("all follow") or how many set their own ("2 set own", tooltip names them; narrow: "â†“2"),
  and an edit there says who keeps their own value (`controller._below`).
- Everything the artist reads is English (panel, status bar, node warnings, undo labels, publish notes); the
  user found Vietnamese mixed in. Regions out of date say why: `GroomData.mark_stale(why)` keeps the last
  `STALE_WHY_KEPT` reasons (Detect locks, a root flipped, excluded, locks moved to another group), shown in
  the Update regions tooltip and the overview; Update regions clears them. "new" shows only while there are
  missing locks whose settings could go to it; Detect with none missing marks nothing new.
- The measured cells add what the geometry holds (`adapter.geo_stats`, intrinsics of the per-lock cache,
  under 5 ms for the whole groom): real strand count (replacing the estimate; "(preview)" in preview
  display), points, points a strand, and the attribute names by class under the cells.
- The per-lock loop drops what only it needs (`config.LOOP_ONLY_ATTRIBS`: tightness, clumpblend, fit_*,
  length_mult, frizz, clumpid, skinprim / skinprimuv, which index the loop's region cut) in `lock_clean`
  before the cache: the cache, display and deform carry P, width, lock_id, name, group, clump_id, id (+ the
  deform capture); `tightness` alone was 4 M floats on Helen. Publish writes `GROOM_REST` (output 1 at
  rest: contract attributes only, every lock not excluded, whatever the view); `publish_clean` drops the capture.
- From the review (t48), done here: Detect checks the scalp's size in cm against a head
  (`config.SCALP_SIZE_CM`, catches a wrong `unit_cm`), its uv and the object's transform
  (`adapter.preflight`, warnings on the result line) and, while no split exists, splits regions in the same
  undo step (the first "regions out of date" only taught a click). Publish refuses pieces Detect has not
  matched (they grow nothing) and warns, with the second-click rule, about locks to check, new locks while
  some are missing, regions out of date, hidden / isolated locks (`_publish_risks`). **F** frames the
  locks being edited, or the whole groom (`adapter.frame_locks`; Houdini's own F frames its selection,
  which focus clears; an empty `hou.BoundingBox()` already holds the origin). One undo prefix,
  "MONO Grooming: ", for the HDA's buttons and the panel's edits; the HDA's labels match the panel's
  (Hair, Guides, Color by, Detect locks). The overview lists every key and gesture (`SHORTCUTS`).
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
  (`controller.solo_visible`, eye states, one undo step); again on the same rows puts every eye back as it
  was before (`_solo_before`, kept while the eyes are still what the solo set; locks hidden before stay
  hidden: the user found the first version showing them all). The isolate button turns its icon accent when on, not only its background; menu
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
- Publish writes nothing half done (`logic.StagedFiles`): the USD (the inner `PUBLISH_USD` exports to
  the temp name through `publish_path`), `grooming_data.json` and `publish.json` go to
  `<name>.<token>.tmp<ext>` next to their final names (same folder: the rename never crosses a disk; the
  extension kept: USD picks the format by it), then `commit` renames them with `os.replace`, the USD
  last, so a USD on disk always has its records; a final name that appeared meanwhile is refused, not
  overwritten. On any failure `abort` removes this publish's own temp files by name (never a glob:
  another publish may be writing beside it), what it had already renamed, and the folders it made while
  empty; earlier versions are not touched. JSON is fsynced so a full disk fails before the rename.
  `logic.publish_error` names what the artist can fix (disk full, folder not writable, already
  published, a file where a folder should be); the panel shows it on the message line and proposes the
  next free version again. hython t54 (`sandbox/.../t54_publish/`): ok, same version, disk full on the
  2nd rename, failure after the USD export, no permission, no `_vNNN` in the scene, file in the way: no
  temp file left, the renamed USD reads back with every strand (118,622 on Helen).
- Shot check t56 (sh020 / sh025, sandbox `tests/t56_shot/`): the deform follows the anim (strands p95
  0.54 cm off the animated mesh, as at rest, while it moves 76-195 cm); output 1 1.1 s a frame, output 0
  +0.9 s, first frame after Deform on 12 s. A warning inside the locked HDA (ANIM_HAIR's point-count
  check) never reaches `node.warnings()`, even on the cook chain: say it in the panel
  (`deform_problem`, shown by Deform on), not only in VEX. v0.1 has no shot cache: a stock File Cache on
  output 1, Deform on. `qc_capture.py` with `QC_FRAMES=0,60,120` keeps the anim and shoots
  `shot_<view>_f<frame>` and the animated mesh beside it.
- Output 1 deforms whenever a matching anim is wired (t56b): with the display at rest a lock edit cooks
  no deform node (output 1 is not read), and a File Cache on output 1 caches deformed with Shot deform off.
- v0.2a mask spike (t57, sandbox `tests/t57_mask_spike/`; decisions and numbers in the v0.2 plan):
  - Painting is our own Python viewer state: it reads `SCALP_FINE`, keeps the stroke in numpy, writes the
    HDA node's parms once on release (one undo step). Nothing cooks while the button is down, so the brush
    runs at the redraw rate (1.4-1.9 ms a dab on 24.5 k points) whatever the hair costs. Attribute Paint on
    an editable inner node works in a locked HDA, but cooks the groom below it on every dab (1.4 a second).
  - A state entered by name (`setCurrentState`) gets `onGenerate`, not `onEnter`, and no node in kwargs.
    Selecting the node afterwards (`setCurrent`) makes Houdini enter the node's own state on its next
    event loop and drops ours silently: `currentState()` still said ours right after the call.
  - `hou.SimpleDrawable.setGeometry` with the same `hou.Geometry` object does not re-read `Cd`: hand it a
    copy (`hou.Geometry(geo)`, 0.5 ms). `hou.GeometryDrawable` Face draws flat, no `Cd`. Drawables are in
    flipbook shots.
  - GUI tests can paint without the user's cursor: `QApplication.sendEvent` of QMouseEvents to the
    widget under the viewport (`RE_WindowDrawable`), one a timer tick (Houdini merges several moves sent
    in one tick; `postEvent`, QTest and Win32 messages did not reach the state). Real input
    (`SetCursorPos`) fights the user's own mouse.
  - hairgen's scatter follows the point `density` attribute, hard edges and soft ones (count x2.0 where
    painted 2, 0 where painted 0, spacing 0.86-1.04, clumped 0): masks need no scatter of our own. What
    does not follow it by itself: the start disc (`root_pick`) and whorl roots, which are placed by us.
  - Every parm of the node is in each lock's key unless listed in `_KEY_SKIP_PARMS`: a new storage parm
    must go there, or its first write regrows the groom.
  - `node.parm(data_parm).set(hou.Geometry)` undoes and redoes exactly and is saved with the hip; a spare
    parm can be added to a locked HDA node.
  - A scene keeps its saved parms: `t17_check/char_Helen_grooming_v007.hiplc` still has `root_pull` 0.85
    and Shot deform on (hython does not reset it), which bunches every root and deforms output 1; make a
    scene with the current defaults first (`t57_make.py`). Output 1 is deformed while an anim is wired:
    read roots from `GROOM_REST`.
- v0.2a density masks, the core (t58, sandbox `tests/t58_mask_core/`; what was decided is in the v0.2 plan,
  the acceptance scripts are `tests/houdini/grooming/accept_v02a.py` (hython) and `accept_v02a_gui.py`):
  - Code: `apps/houdini/grooming_masks.py` (storage, `cook_mask_read`, `ScalpBrush`, `PaintSession`, the layer
    functions; the adapter re-exports them) and `apps/houdini/grooming_paint_state.py` (the viewer state). The
    panel is not built yet: it calls `mask_*`, `paint_enter` / `paint_exit`, `set_brush` and sets `HOOKS`.
  - There is no `attribwrangle` SOP verb (it is an HDA): VEX cannot be run on a `hou.Geometry` without a node.
    `attribpromote`, `normal`, `attribtransfer` have verbs. Topology in bulk: a point and a prim number
    attribute promoted to vertices and read with `vertexIntAttribValuesAsString` (`_vertex_tables`); one hou
    call per vertex of the fine scalp is over a second.
  - A node outside a locked HDA cannot be wired to a node inside it (`setInput` fails): tests read
    `GROOM_REST` through an Object Merge.
  - `mask_read` is in line and cooks on every edit, so what depends only on the split is kept per node by a
    digest of it (`_region_tables`), and the mask's mean per prim is numpy's: looked up per owner and point
    in PREVIEW's VEX it cost 45 ms an edit and took the undo of a stroke to 0.09 s (now 0.04-0.08 s).
  - "No layer = v0.1" holds because `mask_read` adds nothing then and the automatic groom's nodes never read
    a layer; a lock whose skin no layer covers (keep all 1) gets no `mask_set` and no digest, so an empty
    layer regrows nothing, and the layer nodes of the loop sit behind switches on `mask_set`.
  - A scalp attribute named `mask_keep_<n>` of the user's cannot leak in: a lock without a set never reads
    it, and with one `mask_read` has just written it.
  - The state: entered by name it gets `onGenerate`; Houdini goes to the node's own state
    (`mono::grooming::0.1`) when the node is selected again, and the state comes back by itself while Paint
    is on (`_came_back`); a tool the artist picks (`USER_STATES`: select, view ...) ends Paint. Undo while
    painting: a `ParmTupleChanged` callback on the node reloads the brush's data. `ui_event.ray()` is in
    world space: the state moves it into the object's space.
  - GUI test of the brush: a stroke's release is handled after the tick that sent it (it stores and cooks),
    so wait for the state's stroke count, not a fixed time. Screen positions of points on the skin: fit
    global pixels to `viewport.mapToScreen` from a few test moves (no guess about toolbars or pixel ratio).
    Esc reaches the state as a QKeyEvent sent to the viewport widget after `setFocus()`.
  - Helen's scalp has a band of sliver polygons by the ears (half the fine scalp's prims on 1.7 cm2): pick
    test patches away from prims under 0.001 cm2, and never snap a path to the nearest scalp point.
  - Full-cook timing in one process: drop the node's LockCache and force `groom_keys` (forcing `GROOM_REST`
    alone cooks nothing: 0.0 s). Single cold cooks swing 9.5-13.4 s on this machine: compare medians of 5.
  - After the user's own try (2026-11-13): a factor colour does not show the density. `set_brush(view=)`
    (`density` / `layer`, Painter's "result or one mask alone"; the factor view went with the factors) and `set_brush(roots=True)` (a dot
    a root of the full groom, `grooming_masks.display_roots`; in Guides display on the bare skin) are in the
    state; the base row and Alt+click are the panel's. A `hou.GeometryDrawable` of type Point with
    `params={"radius", "style": hou.drawableGeometryPointStyle.LinearCircle}` draws 119 k dots fine.
    Tool changes made by our code run inside `hou.undos.disabler()`: Houdini records them as "Change
    selection", which sat between strokes in the undo stack. `set_display` still records its own step.
    A GUI test finds the viewport widget inside Houdini's own window (`mw.childAt`): `QApplication.widgetAt`
    is None when another window (the user's Houdini) lies over it.
  - Layer model, FINAL (the user, 2026-11-15; plan "What" and "The layer model"; built in t63 on round 3's
    network. It replaces t62's ONE 0..1 mask x the lock's own Density, commit 2b45a21, where no layer could be
    denser than the automatic groom and black meant "no hair"): DENSITY LAYERS over the automatic groom, each
    with its own number D (strands / cm2), opacity, eye, owner (`scope`: all locks / a group / a lock) and its
    own mask: paint and fill layers, values 0..1, six blend modes (`config.MASK_MODES`), blended from BLACK
    (`logic.mask_stack`). density = below + (D - below) x mask x opacity; density layers stack as Normal only,
    all-locks layers first, then the lock's group's, then the lock's, inside one owner in the list's order
    (`logic.density_order`). Black in a mask = the layer does not apply there (the density below shows); no hair
    = D 0 painted white; D may be over the lock's own Density. The automatic groom is the base layer, stored as
    the first row (`kind` "base", id `config.MASK_BASE_ID` -1, `model.base_layer()`): never deleted, moved or
    edited (`mask_remove` / `mask_move` / `mask_set` raise ValueError). No folders (plan, "What" 7). One list,
    `groom_data.masks`, in one order (`model._normalize`): the base, then each density layer followed by its
    mask layers (`MaskLayer.parent`); `GroomData.density_layers()`, `.mask_layers(id)`. A paint layer holds per
    point `mask_<id>_v` and `mask_<id>_a` as before (erase takes coverage away, never paints black); a fill
    layer one `value`. Quick picks are densities, `config.MASK_DENSITY_PICKS` 0 / 75 / 150 / 300.
    `groom_data` schema 6; schemas 2 to 5 open (`model._density_layers`: a "= D" layer under a mask becomes a
    density layer whose paint layer keeps the old id; the 0..1 layers of one owner become the mask of one
    density layer of the owner's Density; folders fold into their layers; a factor over 1 is dropped), named
    by `model.dropped_masks` / `converted_masks`, OnLoaded's status line and `mask_dropped`.
  - What "= D" means on skin several locks share (`grooming_masks.layer_divisor`, `logic.owners_sharing`;
    measured, t63 `o2`): D is what the locks the layer is owned for give there TOGETHER. All locks: every owner
    of the prim (D / owners each). A group: its locks on that prim. One lock: that lock alone, on every prim it
    owns, whole (0.998 / 1.051 / 1.022 / 1.027 of 120 on its own skin (it would read 4.215-4.667 x if the 120 were shared by the 4.223-4.441 owners of that skin) on the most stacked skin; the other locks' roots unchanged).
  - The rule in numbers (`logic.density_over`, `density_compose`, `layer_density`): the bottom is the automatic
    ROOTS, not a number, so the stack carries (keep, add) per point: keep = the product of (1 - mask x opacity)
    over the layers that reach the lock (the share of its automatic roots left), add = the layers' own density
    in strands / cm2 (add x (1 - e) + D x e), density = automatic x keep + add. `mask_read` writes per scope set
    (`logic.mask_scope_sets`: the ordered density layers reaching a lock) the POINT attribute `mask_keep_<k>` and
    the VERTEX attribute `mask_add_<k>`: add is one lock's part, each layer's D divided per PRIM by the owners
    it is shared by, and a point of the scalp belongs to prims with different owner lists. `mask_add_n` = the
    sum over the lock's prims of (mean of its corners' add) x area. `MaskData.weights` gives keep and each
    layer's weight (its e x the (1 - e) of the layers over it).
  - How the network does it (t62; why: the plan's "Why two sets of roots"): the automatic roots are grown
    by v0.1's own nodes and each stays while its threshold `thin_u` < keep where it ends up (`mask_thin`, by
    `root_at`); the layers' roots come from a second scatter (`hairgen_layers` on `mask_skin`: `mask_add_<k>`
    read per vertex on unshared points, strands / cm2, `mask_add_n` roots) merged in before `root_place`. Never
    multiply hairgen's density attribute by a mask again: it could not thin relocated roots (whorl, lock
    starts), and a forced count re-placed every root for a mask of 0.03.
  - Even thinning (`thin_order`, a detail wrangle after `root_pick`, cached with the automatic roots, so a
    stroke never pays it; plan "Even thinning"): `thin_u` per automatic root. Start roots and scattered roots
    are each ordered by PAIRING (nearest unpaired root; one of the pair to the first half, the one farther
    from the roots already there; each half paired again, `THIN_ORDER_BITS` 10 times; the halves are thin_u's
    binary digits), so a share is kept locally and per lock. Roots sorted along a Z-order curve, a partner
    looked for among the next `THIN_ORDER_WINDOW` 10 (all of them in a half of `THIN_ORDER_EXACT` 64 or
    fewer). A start grid of `THIN_ORDER_SMALL` 400 roots or fewer: farthest-point order. Whorl roots: the
    bit-reversed sunflower number. `mask_apart` (after `mask_thin`) moves a layer root off a kept automatic
    root (`MASK_APART` 0.45 of the spacing asked there, up to 6 moves, on the skin; it changes `root_at` only).
    Its nearest automatic root comes from a point lookup (`apart_cloud`, group `auto_at`): a VEX loop of every
    layer root against every automatic one took a 3-lock stroke from 0.4 to 0.72 s (limit 0.7).
    What failed on the way, do not retry: a random number (start grids left in bunches, clumped 0.014 ->
    0.616); the root's `id` in hairgen's scatter (it numbers patch by patch: a keep of 0.5 left 0.35 to 1.85 of
    the roots); a golden-ratio step of the sunflower index (that IS the angle); a dither of the position
    through R2 (stripes), and on whole cells (+0.06 to +0.10 at 0.25); a farthest-point order of everything
    (even in space, not a share: the rim first; inside a large start grid 0.8, stacked skin 1.17, floating
    mesh 0.56, also with distances in the roots' own spacing); pairing every root against every other (+13 s
    cold; VEX array loops run ~40-100 ns a step, keep n x n under a few million); pairs taken in turn instead
    of by distance to the first half (a 163-root start grid at a quarter: +0.15 to +0.19). VEX has no shift
    operators (`r = r * 2 + k % 2; k /= 2`). Cold cook 6.8 -> ~10 s.
  - A few v0.1 start roots float off the skin (hair_base_20: 1 of 7,172 strands starts 0.24 cm up); the mask
    judges a root where it lands on its lock's region, so such a strand can stay over skin painted black
    when that landing is the patch's rim. (By the distance to the SURFACE no root of the groom is over
    0.002 cm off the skin: the "0.24 cm up" was the distance to the nearest prim CENTRE on a large prim. The
    acceptance counts every root since t65.)
  - Measured (t62 `accept.json`, Helen, discs of 1.3 cm, 8 kinds of skin, all locks together and each lock on
    its own skin): see `report.md` there. Shared points (the lock's share averaged at a point) gave 1.08-1.10
    on the top of the head: hence `mask_split` (Facet, unique points).
  - Evenness under a layer is judged per lock on the lock's OWN skin in the patch (`accept_lib.lock_even`):
    a lock holding a strip of a painted patch has all its roots on that strip, which reads as "clumped"
    against the whole patch's area (t61's hair_base_21 0.756). All locks together on stacked skin are near a
    random pattern (0.15-0.29), as the automatic groom is there (0.17-0.43).
  - `lock_infos` under layers: `strands` = `auto_strands` x `keep_share` + `layer_strands` (whorl roots apart,
    as before). `layer_strands` is the network's own count (the layers' density over its skin, `mask_add_of`); `keep_share` follows the network's steps on the
    region's prims (`grooming_masks.lock_layer_counts`: scatter by area / share, `far_w` from `owner_dist`
    moved to root_pick's disc, kept by the keep where it lands). `mask_share` = strands / auto_strands.
  - The density view counts real roots: `display_roots` reads the per-lock cache (the display's full hair,
    else output 1's), `root_density` sums roots and skin area in the same 3 x 3 x 3 boxes of 0.5 cm cells
    (right on curved skin, edges and Helen's sliver band; it adds up to the strand count within 1 %).
    Entering Paint never cooks for it (`reroot(cook=False)`); choosing the view by hand does. While the
    button is down the view shows the counted density x factor now / factor then.
  - The acceptance (`accept_v02a.py`, rewritten in t63 for density layers): s* stroke speed, u* undo chains and the
    cache's memory, d* a layer of D painted white, black and the eraser, a tiny mask, grey masks and opacity, a soft
    edge; o* owner order and what D means for one lock; b* the mask's blend modes and Multiply as the top layer; m*
    compose and fill layers; r* no layer = v0.1; q* QC after painting (two-sided: `qc_tamper.py --drop 0.3` and
    `-0.3`); p* persistence, publish, a missing lock, schemas 3 / 4 / 5. Every density check grades all locks
    together AND each lock on its own skin in the patch (`_grade`, expectation from `_want`, written apart from the
    tool's code). Run timing checks with no other Houdini cooking: with two GUI
    sessions open and pytest running, stroke cooks were 1.5x slower and one missed its limit.
  - Timing checks are absolute limits: with Blender and Resolve running the whole machine was 1.45x slower
    (v0.1's own full cook 14.4 s instead of 9.7) and `dw3_stroke_speed` missed one stroke. Time v0.1 right
    before (`--time-only`) and read stroke limits only from a quiet run.
- Undo cache by memory, and output 1's capture apart from the hair (round 3, t62; the user's decision 2):
  - `LockCache` holds states while memory lasts, not a count of 2: per node a limit (parm `undo_cache_gb`,
    "Undo cache, GB", default 2, in `_KEY_SKIP_PARMS`, read by `lock_keys` every cook), each entry sized by its
    geometry's `memoryusage` intrinsic, the states used longest ago dropped when a store goes over. Never
    dropped: the key used last in each (node, lock, mode) slot and everything touched since the node's keys
    last cooked (`begin`; `has` counts as a touch, so what `lock_keys` saw is there when `hair_cache` merges).
    `undo_cache_usage(node)` gives the panel bytes / live / undo / limit / dropped / capture_bytes.
  - `put` is a cook of a lock's hair by the loop (`cache_store`) and nothing else; copies made from cached
    hair go through `put_derived` (the display's coloured copy, the whole merges, output 1's captures), so a
    test wrapping `put` counts hair grown. The display's coloured / ghost copies of earlier states are not
    kept (`keep_only`): by `memoryusage` they are as large as the hair and halved what the limit held, and
    making one again costs ~1 ms a lock (Houdini shares the attribute data of a copy: 6-11 MB real for a
    78 MB geometry, t62 `cow.py`, which the intrinsic does not show; the count stays the careful one).
  - Output 1 with an anim wired no longer captures inside the per-lock loop (`capture_flag(groom=True)` is
    0): `groom_keys` gives the same keys as the display's full hair, so GROOM_REST, publish and the density
    view read the display's strands (GROOM_REST after a display cook: 13.6 s in v0.1, 0.34 s now). The
    capture the deform needs is a second loop after `groom_cache` (`groom_capture_keys` -> `groom_capture_load`
    (the lock's cached strands, contract attributes) -> `groom_capture_lock` (Point Deform, capture) ->
    `groom_capture_store` -> `groom_capture_all`), cooked only when the deformed output is read. Why: captured
    strands are 800 B a point (Helen 3.3 GB for one state of the groom, 400 MB for one stroke over 6 locks),
    so no limit could hold undo states of them, and they pushed the hair's own states out. One capture a
    lock is kept, outside the limit's count (size 0, reported as `capture_bytes`); an undo with the deformed
    output read captures its locks again from cached strands (5 locks: counted apart, no hair regrown).
    The deformed output is point for point v0.1's (frames 0 / 24 / 48, max difference 0.0 cm); its first
    read after a display cook 4.5 s (v0.1 ~15 s), a frame 1.2 s as before.
  - Point Deform is an HDA of wrangles: it has no SOP verb (`nodeVerb("pointdeform")` is None), hence a
    loop of nodes for the capture, not a Python verb call. A node copied by `_copy_loop` takes the prefix
    `groom_`: a new node named `groom_captured` collided with the copy of the loop's `captured` switch.
  - Numbers (Helen, hython, anim wired, limit 2 GB, t62 `undo*/`): live 520 MB (hair 124, coloured copies
    126, the display's and output 1's merges 270); a stroke over 5 locks of ordinary skin holds 26 MB (a
    limit of 2 GB: ~58 such strokes), a whorl stroke over 26-35 locks 55 MB (~28 strokes). 30 strokes then
    30 undos and 30 redos on ordinary skin: 0 locks cooked for the display and for GROOM_REST, undo + display
    cook 0.025-0.071 s, redo 0.028-0.083 s, peak 1.27 GB. Whorl: the first 28 undos 0.04-0.07 s with 0 locks,
    the last 2 regrow (the cache was full: 190 states dropped), still the right hair. Limit 0.3 GB (under the
    live set): every undo regrows its locks (1.0-1.2 s for 5), every state still equal to the stroke's.
  - `PREVIEW` no longer sums `region_keys` on every stroke (new wrangle `region_keys` on the split before
    `mask_read`): 20 of its 26 ms, paid by every stroke and every undo.
- Stroke speed (round 3, t62 `speed*/`; limit 0.2 s a lock recooked + 0.1 s, unchanged). Profile a stroke
  with `hou.perfMon.startProfile(name, hou.PerfMonRecordOptions(cook_stats=True, ...all else False))` and
  read the CSV's self times and the per-node min / max over the loop's passes:
  - `fit_to_lock` cost ~75 ms a lock WHATEVER the lock's size (min 74, max 82 over locks 5x apart in
    strands): its two `xyzdist` lookups search SURFACE_CLOUD, every lock's mesh in one geometry, and VEX
    builds that search structure again in each pass of the for-each (naming the cloud by `op:` path changed
    nothing). Now each lock gets only its own piece: `surface_pack` (Pack by `piece_name`, one packed
    fragment a piece, once per mesh) -> in the loop `piece_pick` (Blast on 61 packed prims) -> `piece_cloud`
    (Unpack: costs the piece's faces). A Blast of the whole cloud per lock is the 73 ms the notes above
    warn about; 61 Blast verbs up front took the cold cook from 11 to 15 s. Strokes 30-40 % faster, the
    cold cook 10.9 -> 7.6 s.
  - CONTRACT NOTE: the per-piece lookup does not give v0.1's hair bit for bit. Same roots, same strand
    count per lock, but the nearest-face search answers within its own noise (flattened mesh with folds,
    z = piece x 100 in float): Helen without layers, 45 % of strand points differ, half of them under
    0.008 mm, 1 % over 1 mm, at most 4 mm. grooming-check: 27/27 pass, 19 numbers equal t55's to the last
    digit, 8 move by 5e-5 to 1 % (kink p95 32.9566 -> 32.9534, uncovered 0.0699 -> 0.0701, lock uncovered
    worst 0.1314 -> 0.1327, tip width off 0.4412 -> 0.44 ...; t62 `qc/nolayer_piece`). The node's toggle
    "Fit lookup per lock" (`lookup_per_piece`, on by default, in every lock's key) switches back to the whole
    cloud (`fit_cloud`): then the groom is v0.1's within v0.1's own run-to-run difference. v0.1 is NOT
    byte-identical from run to run (t68, 10 runs each: on a groom v0.1 made and saved up to 0.0024 cm, 5 of 10
    identical; on Helen as v0.1 saved it up to 0.0123 cm, no two runs identical), and this build with the toggle
    off lies within that spread; the acceptance's tolerances are 0.003 / 0.015 cm, counts per lock equal. The default (on for a new node,
    off for an old scene) is the user's decision: "B4" below and the plan.
  - The lock's automatic roots (hairgen's scatter + `root_pick`, 8-16 % of a lock's cook; `root_pick` is a
    single-threaded detail wrangle) are kept per lock under its key without layers (`auto_key`,
    `auto_store` / `auto_load` / `auto_roots`, LockCache slot "auto:" + mode, one state a lock): a stroke
    lays out no automatic root again. Stored on every cook of a lock, so a first stroke finds them.
  - `fit_mid` is folded into `strand_smooth`, which now leaves its result as one array (`smooth_p`) for a
    point wrangle (`strand_smooth_apply`): a trivial point wrangle costs ~10 ms a lock in the loop, and a
    `setpointattrib` per point from a prim wrangle is applied one by one. `length_frizz` returns at once
    when there is nothing to cut or frizz (it wrote every point back unchanged, 4 %).
  - Helen, 8 places x 3 strokes on "= 120" (radius 0.8 cm): 3 locks 0.29-0.43 s (limit 0.7), 6 locks
    0.66-0.85 s (1.3), 19-20 locks 1.07-1.13 s (3.9-4.1), the whorl 24-35 locks 1.43-2.33 s (4.9-7.1).
    Before (same build, whole-cloud lookup, no root cache): 0.56-0.73 / 1.03-1.52 / 2.06-2.21 / 2.81-4.70 s.
  - Timings on this machine swing 10-15 % from run to run even when idle: grade speed on the worst of
    several runs, never on one.
- t65, the t64 check's bugs (sandbox `tests/t65_density_fix/`, `report.md`; the plan has the decisions):
  - Older files (B2): the 0..1 layers of schema 2 / 3 / 5 become `legacy` density layers ("Older build N",
    `MaskLayer.legacy`): their mask layers blend by that build's rule (`logic.legacy_mask` -> (keep, add); the
    layer gives keep x keep' and add x keep' + D x add' over what is below, `MaskData.parts_of` / `weights`).
    A plain density layer is the same thing with (1 - mask, mask). Do not turn them into plain layers again:
    that lost every thinning (a mask starting black makes Multiply and Min do nothing) and black = no hair.
    Compare an older file against the suite that wrote it (t64 `old_suites/`): t62's `layers.hiplc` gives
    114,377 strands with both, lock for lock. The t64 report's "116,844" was a run that did not read the
    file's paint; rerun with the same script and suite it gives 114,377.
  - Black over white (B3): the points the t64 check found left white lie OUTSIDE every black dab (0.36-0.39 cm
    from the nearest dab centre, radius 0.3): an offset disc of the same size does not cover the first one;
    the brush's reach is not at fault. What was wrong: `logic.mask_dab` moved a painted value by the weight
    alone, so a soft stroke painted again in black with the same brush left (1 - w) x w of the white along its
    rim. It now moves by weight / coverage (at most 1). A soft black stroke over a HARD white disc of the same
    size still leaves the rim (the soft part never reaches full weight): that is what soft means.
  - `thin_order` is lazy (B5): made on the layer path only (`auto_thin` switch, `thin_store`), the result
    replacing the lock's "auto:" cache entry (`auto_cached` 2 = kept with `thin_u`). VEX outside a detail
    wrangle runs array code ~30 x slower (a "run over numbers" wrangle with one chunk a number took 6 s for a
    lock a detail wrangle orders in 0.18 s): no chunked parallel version.
  - Shot deform on (B6): no output captures in the per-lock loop any more (`capture_flag` 0; the loop's
    `lock_capture` / `captured` nodes stay, unused). The display's deform: `disp_capture_*` (`_capture_loop`,
    slot `capture_slot(mode)`: the full hair shares output 1's captures) -> `deform` -> `deform_no_capture` ->
    `deform_store`, or `deform_load` when `deform_keys` finds the state (`DEFORMED_MODE`, a whole deformed
    groom, ~251-264 MB on Helen; held APART from "Undo cache, GB" (`LockCache.APART`, not in its count) in a
    limit of their own, the node's "Deformed undo, GB" (`undo_deform_gb`, default 4: the user's decision on B6,
    memory and not a packed display), `LockCache.keep_bytes` dropping the oldest; states of another frame are
    dropped; with the deform off `lock_keys` drops them and the display's merge). The mesh and guide parts are deformed apart (`deform_mesh_guide`), the hair is coloured
    after the deform (`hair_color_deformed`). Toggling Shot deform no longer regrows the groom.
  - grooming-check under layers (B7): a painted lock's count is held to max(0.15, 2 / sqrt(expected)), written
    on the 0.15 scale (`density_limit`; an unpainted lock: 0.15 as before, so the no-layer numbers do not
    move); the start share weighs each automatic strand by 1 / keep where it is rooted and leaves the layers'
    own strands out (`layer_strand_weights`), so it still asks whether the TOOL left a start bare. A start
    the artist painted bare (D 0 white over it) reads 0: there is no automatic strand left to weigh.
  - Paint (B8): `_others_selected` looks at every network (the node's own ancestors apart), `_not_ours` also
    ends Paint when no node is selected, `_came_back` turns Paint off when the viewer cannot take the brush,
    and `_EscFilter` takes Esc as ShortcutOverride too (where Houdini has Esc as a shortcut the KeyPress never
    comes; a GUI test must POST the key, `app.postEvent`, to see it: a sent event skips the shortcuts). `esc()`
    turns Paint off FIRST and stores the held stroke after: storing it cooks the node, a cook runs Qt's event
    loop, and Paint stayed on for as long as that cook took (0.45-0.67 s; t66 B8(b), which looked like it
    depended on the steps run before: it depended on how many points the stroke had painted).
  - The per-lock "= D" miss (B1) is one fixed draw of hairgen's scatter, not a bias: over 40 seeds the prim
    holds 35.1 where 33.66 are asked (sd 5.15, the t66 check; the shipped seed draws 45, the highest of the
    40); the seed is the lock's id, so the draw is the same at every D. The user's decision (2026-11-15): no
    new scatter in v0.2a; the acceptance grades each lock over the prims covered in full by the paint (36-44 % of the painted area on the three test places, t68); the rim is not graded, and lists a lock on
    one polygon without passing or failing it, for evenness too (round 4: `not_judged_one_polygon`; at 35
    roots one root is 0.029 of a rise limit of 0.05). `hairgen_layers.geometry()` has `skinprim`: count per skin prim without any
    assignment (isolate the lock, read `mask_skin` and `hairgen_layers`).
  - "Fit lookup per lock" (B4, decided by the user): a new node has it on; a scene saved before it existed gets
    it written OFF by OnLoaded, once (`keep_old_lookup`, user data `monofx_fit_lookup`), so a v0.1 scene
    reopens as v0.1's groom within v0.1's own run-to-run difference. Two things learnt in t66 / t67:
    - It must run BEFORE anything writes `groom_data` again. `mark_old_regions` rewrote the data of a scene
      whose regions carry no rule number (Helen as v0.1 saved it, `helen_v01.hiplc`) in today's schema
      first, so the toggle stayed on (N1: points moved up to 0.958 cm, silently).
    - "Before the parm" is decided by the saved hip itself: it holds each parm of a node as a record line,
      `lookup_per_piece\t[ ...`, in plain text, a .hiplc too, and `hip_holds` matches the RECORD, not the word
      (t68: a sticky note holding the name opened an old scene with the toggle on; a hip naming the word does
      not hold the parm). Known and contrived, not handled (t69): the record text after a real newline inside a
      note / comment / user data / string parm, or a spare parm of that name on another node, still fools it
      (the old scene opens with the toggle on). The parm came in the middle of the schema 4 test builds (245f480 has it, on;
      two schema 4 commits before it do not), so no schema number tells (N2). The file decides whenever it
      can be read, whatever the schema (t67: a scene opened while another checkout's library, without the
      parm, was installed had its data rewritten as schema 6 by that load's `mark_old_regions`, and OnUpdated
      then kept the toggle on). A node made now is marked by OnCreated (`on_created`) and never judged.
      Without a file to read, schema under 4 decides. The toggle set by hand rewrites the note
      (`on_lookup_changed`, the parm's callback). A node copied out of an old scene and pasted into another
      is a new node (the manager's rule, round 3): toggle on, no note.
    - hython on this machine may bind a scene to ANOTHER worktree's `mono_grooming.hdalc` at load (the
      installed package) before a test's `installFile(force_use_assets=True)` switches to its own: the rule
      then runs from OnUpdated. A test that reads the toggle must read it after the switch. A hip lists the
      library paths installed when it was saved and Houdini installs them at load: bound first to a stale
      checkout's library without the layer parms (`mask_layers` ...), the node LOSES its painted masks at load,
      whatever this suite does after (t68 section 5). Test on copies whose saved library list names no stale
      checkout.
    Test scripts that open the Helen scene "as saved" run with it off; `accept_lib.fresh` reverts every parm
    to its default, so the acceptance's fresh groom has it on (checks `s2`, `r5b`, `r6`, `r6c` cover off).
  - The thinning order is lazy with the toggle on AND off (the user, 2026-11-15). With it off the whole-cloud
    lookup leaves a first stroke no margin, so the first stroke on a lock never painted may go over the stroke
    limit by up to 0.10 s, once per lock (t68: 0.100 / 0.098 s at worst): a known, stated cost; `s2` reports first strokes apart
    (`Checks.add(passed=None)`: KNOWN, neither pass nor fail). Do not make it eager again: tried in t67
    (`thin_order_eager`), 2.48 s of the cold cook, the display's cold cook of Helen as v0.1 saved it 1.16 x.
  - Lock borders in the acceptance (t67 `stray_roots.py`, cause corrected by t68): the roots lie on their OWN
    lock's skin (within 1.7e-5 cm); the HDA cuts a lock's region by whole prims (`lock_owners`, `region_cut`),
    and a root on an edge shared with another lock's prim went to the neighbour (`Skin.assign`, nearest prim),
    so a lock read N = 0 with 1-2 roots and failed `d1` / `d2` / `b3`. Round 3: a prim the root's own lock owns
    within 1e-4 cm wins (`Skin.TIE_CM`). Round 4 (t69 3a): ownership and the surface gap are two checks, never
    one number: `z_roots_stand_on_their_own_locks_skin`, own lock's skin minus the nearest skin of any lock
    <= 2e-5 cm (`OWN_EXTRA_CM`; measured 1.04e-5), and `z_roots_on_the_skin`, nearest skin <= 0.0025 cm
    (`GAP_CM`; measured 0.0023: the scalp quads are not planar, up to 0.0038 cm, so the roots stand up to
    that far off any triangulation of them).
  - Known open (round 4, t67 `thin_r4/`, the checker's attribution-free method): under one soft dab on a layer
    of 0 the thinning keeps 14-21 % more roots than 1 - mask in the ring 0.3-0.6 cm and 2-4 % fewer in
    1.2-1.5 cm, at all four places tried (lock start, crown, top of the head, the top moved 0.7 cm): a bias, not
    a draw. `d4` top_of_head fails on it (17.7 %, limit 15 %); the limit stays. Checks failing by decision:
    d3 (4 crown rows), b1 crown (3 rows), d4 top_of_head ring 0.3-0.6 (the plan lists them with dates).
  - Evenness by the local measure misses +0.05 at the crown whorl under partial coverage for a few small fringe
    locks (hair_bang_04 / 16 / 19, hair_base_09: +0.054 to +0.119). Traced in t67 (`evenness/` there): the roots
    that read as bunched are PAIRS OF TWO KINDS of automatic root of the same lock that already stood that close
    before any layer: a whorl root (root_place's sunflower) on top of one of the lock's scattered roots (9-14
    of the 12-16 roots in pairs; two 0.0003 cm apart), and start roots whose grid places are far apart in the
    farthest-point order but land 0.012 cm apart. Each kind is thinned by its own order, so a keep of k keeps
    both roots of a cross-kind pair with a chance near k x k; at keep 1 the pair does not read as bunched (the
    spacing asked is small). That is also why ordering the whorl roots by place on their own (t65) only moved
    the misses. The fix would be ONE order for all of a lock's automatic roots by where they land; the user
    decides (the plan has the cost). hair_bang_05's +0.105 at the fringe start (t66) is one other pair: a
    layer root 0.065 cm from a kept automatic root where the measure calls under 0.068 cm close.
  - The acceptance counts a root to the prim nearest it on the surface (`Skin.assign`), follows strands within
    1e-5 cm, holds a lock asked under one root to at most floor(N + 2 sqrt(N)) roots (round 3; ceil before;
    a lock over it is listed as the B1 kind, `locks_outside_b1_kind`, still failing),
    and judges evenness by `lock_even_local` (each root against the spacing asked where it stands; the plan
    has the definition). Per lock it grades over the painted patch (`_patch`: prims covered in full by the paint (36-44 % of the painted area on the three test places, t68); the rim is not graded) in d1 / d2 / b1 / b3, and lists a lock whose skin there is one polygon
    (`locks_on_one_polygon`) without passing or failing it. A grade that also took the partly painted rim
    (each automatic root's own mask value, `Skin.sample`, tried in t67) read the crown whorl's rim 1.77 x at
    D 0: not used, as it cannot tell a measuring error from a tool's. New checks: `u6` (Shot deform on: every
    undo and redo inside the count "Deformed undo, GB" holds < 0.1 s), `r6c` / `r6d` (Helen as v0.1 saved
    it), GUI `s4b` (Esc posted, another network, nothing selected).
  - A patch script for a CRLF file must turn its own LF into CRLF before matching (qc_metrics.py is CRLF in
    the repo), and `\n` / `\r` typed in a shell heredoc arrive as real characters: write the script with the
    editor.
- Do not write `\n` inside a Python heredoc passed through the shell tool: it arrives as a real newline
  (two build_hda.py edits broke that way). Use a patch file, or the editor.
- grooming-check under density layers (round 3, t62 `qc/`; `qc_metrics.py`):
  - `lock_infos`' expected count for a lock under layers is exact once the lock was cooked: the mean keep
    where each of its cached automatic roots ends up (`grooming_masks.root_landings` on the cache's "auto:"
    entry, `keep_at`: Attribute Transfer as a verb, nearest scalp point) x its automatic count + the layers'
    own count. The prim-based estimate (`lock_layer_counts` without roots) was 22-24 % off on crown locks
    (their start roots land in a painted whorl); it is only the answer before the first cook.
  - `density_off_worst` is |strands / expected - 1| for every lock, painted or not, both ways (the one-sided
    check for painted locks is gone). A groom painted "= 5104" on the crown and "= 150" on thin skin (round 3's
    model; the final model's numbers are in t62 `report.md`): 0.005.
    `tests/houdini/grooming/qc_tamper.py` cuts 30 % of a painted lock's strands while the groom cooks:
    QC fails with 0.298.
  - Skin: a prim asks automatic x keep + the layers' density of each owner (`grooming_masks.layer_cover`: one lock's
    part on the whole prim; `qc_metrics.layer_cover_of` turns it into the lock's density on its own share); skin whose 0.5 cm disc asks for less than one root (painted black) is not thin skin (`skin_none_asked_cm2` reports it); skin under
    floating mesh that a layer covers in full is judged like any skin.
  - Roots bunched / spacing of a lock under layers: each root's nearest-root distance is held against the
    spacing asked where the root is (1 / sqrt(automatic x keep + the layers' density)); one spacing for the
    lock called every root of a densely painted part bunched (fringe locks reaching into a crown painted
    5,104: 0.5-0.65). Unpainted locks: unchanged, and so are all 27 numbers of a groom without layers.
  - Known and left: on the rim of a hard-edged patch the mask is grey for one ring of prims, where the
    automatic roots are kept by chance: not even. A "= 0" patch on the top of the head took `root_clumped`
    from 0.0426 to 0.0500 (limit 0.05).
- Paint belongs to the painted node (round 3, checks t60 / t61; `grooming_paint_state.py`):
  - A viewer state gets NO key event while a mouse button is down, and none when another pane has the
    keyboard: Esc with the mouse held left the brush on. An application event filter (`_EscFilter`, installed
    while Paint is on, a fast path for everything that is not a key press) turns Esc into `esc()`: the stroke
    in progress is stored (one undo step), then `paint_exit`. Houdini keeps the state until the button is up,
    so `_mouse` paints nothing once `PAINT["node"]` is None and asks to leave again. Esc typed in a text field
    is left to the field.
  - Another node selected: Houdini enters that node's state, and `_came_back` used to bring the brush back
    over it, so a drag painted the grooming node while a null was selected. Now `_others_selected(node)`
    (other selected nodes of the same network) ends Paint in `_came_back` and refuses a stroke's first click;
    the node selected again still brings the brush back. `enter()` makes the painted node the selection.
- Density layers and missing locks: a layer owned by a lock keeps the lock's id while the lock is missing;
  `GroomData.reassign_orphan` (the panel's reassign) gives the missing lock's settings AND its layers to the
  lock that takes its place (Detect gives a piece that comes back a new id; it does not re-match a missing lock).
- An edit of the groom's data (a layer's number, any setting) used to cost 0.10-0.12 s to undo: `region_keys`
  39 ms (a detail wrangle downstream of the spines, dirty on every data edit), `hair_packed` 31 ms (a tuple of
  3 floats a strand through Python for each coloured copy), `lock_keys` 27 ms. Now the region fingerprints are
  numpy, kept per split (`grooming_masks.region_keys`, input 3 of `lock_keys`), the display copies carry their
  colour as the attribute's DEFAULT (`addAttrib(Prim, "Cd", cd)`: no value written per strand), and `lock_keys`
  reads each prim attribute in one call: 0.057-0.069 s.
- Density layers, what t63 found (sandbox `tests/t63_density_layers/`, `report.md`):
  - hairgen's scatter gives a forced count to prims almost as a coin toss per root: on 400 equal quads asked 34
    roots each the count per quad has variance 26-31 (a coin toss: 34; `scripts/scatter_stats.py`). So a lock
    asked N roots on a small piece of skin holds N +- sqrt(~0.8 N), and the acceptance's per-lock limit
    max(0.15, 2 / sqrt(N)) is a 2.2-sigma limit: a few per cent of small lock cases miss it by chance (t62's
    hair_bang_20, 3 roots where 0.8 were asked; t63's hair_base_21 on the top of the head, 47 where 34). All
    locks together are far inside. A scatter with a fixed count per prim would remove it; not built.
  - The top of Helen's head has large skin prims (the core of a 1.3 cm disc is 11 prims of ~0.23 cm2): a root on
    a prim's edge is counted to either prim. `accept_lib.Skin.roots_in` gives a root to the nearest prim centre.
  - "Clumped share" (`accept_lib.lock_even`) compares each root's nearest neighbour with ONE spacing for the lock
    on the patch. Under partial coverage a lock keeps part of a start grid several times denser than the rest
    of it while its mean density changes, so the same grid reads as more or less "clumped": `hair_base_21` on ordinary skin read +0.14 because `mask_apart` took the lock's set Density (150) for the automatic density there, where under floating mesh 26 / cm2 are left; it now counts the 8 nearest kept automatic roots (rise 0.0; do not go back to the set density).
  - Black painted over white with other dabs left a few white points (r1's first version, the groom not
    byte-equal). Traced in t65: those points lie outside every black dab (the two discs do not cover the same
    skin), not at seams; the eraser, a black stroke with the same dabs, or a wider one leave none.
  - VEX: `setdetailattrib(0, "x", prim(...))` is ambiguous (the build cooks, the lock's loop fails at cook time):
    read into a typed variable first. The same family as "type every prim() read".
  - Patch scripts with triple quotes inside a shell heredoc break the shell tool's quoting: write the script
    with the editor into the scratchpad and run the file.
- Density-layer panel (t70, 2026-11-16, the user's pick "A" of three E2 reworks; the plan's "Panel, built" has the
  whole list): the lock tree holds each row's density layers and their mask layers (`ui_layers.add_layers`), the eye
  column moved to the left edge (`header.moveSection`), Automatic last in All locks with a padlock. The controller's
  part is the mixin `layers.LayersMixin` (selection kind `SEL_LAYER`), the view's part `ui_layers.py`; both are LF
  files, so `controller.py` / `ui.py` (CRLF) only got hooks. Every layer command is one adapter call (its own undo
  step) inside `_run`. `GroomingUI._fire` passes keyword arguments (`set_layer(lid, density=...)`,
  `set_brush(view=...)`): it did not, and the first offscreen test caught it.
  - Qt ignores `QTreeWidgetItem.setExpanded` before the item is in a view: layer rows are opened after the tree is
    built (`ui_layers.expand_layers`). An item's BackgroundRole is painted over by the window's sheet
    (`QTreeWidget::item { background }`), so layer rows are told apart by indentation and icons, not a tint.
  - "painting" in the status column is TEXT_PRIMARY: ACCENT on SELECTED is 3.95:1 (contrast_check).
  - Node values from the panel go through `grooming_adapter.node_settings` / `set_node_setting` (added outside the
    panel with the manager's yes, t70): only the three keys of `NODE_SETTING_PARMS` (else KeyError), one undo step
    each; a parm set from Python runs no callback, so the lookup toggle calls `on_lookup_changed(recorded=True)`,
    which writes the "on/off: set by hand" note INSIDE the step (the callback itself keeps undo off), and one undo
    puts back value and note.
  - Fix round t71 (the checker's defects): the poll checks the node is alive first (`controller.node_alive`;
    a deleted node raises on ANY call, `node.path()` included, so the old except handler raised too) and goes to
    `node_gone` once; the panel's `is_alive` (closed, or its C++ object deleted) stops a poll queued through
    hdefereval; the status delegate clips and elides to its own cell (a wider text was drawn over the name
    column); `ui_layers._RowBar` switches to two lines by the width its content needs.
- Workspace and Paint keys (v0.2a last task, t72, 2026-11-19; plan section "v0.2a, last task"; sandbox
  `tests/t72_workspace_paint/`, `report.md`):
  - Shipped at the suite root (the package `hpath`), each in the installer: `desktop/MONO_Grooming.desk`,
    `radialmenu/mono_grooming.radialmenu`, `python_panels/mono_grooming.pypanel` (moved from this folder:
    Houdini loads `python_panels/` at start, which the desk needs; `_dock` installs it from there). The radial
    file is MADE from `workspace.ENTRIES` (`workspace.radial_menu_text()`); a test fails when they differ:
    change the entries, then write the file again. Its scripts call `apps/houdini/grooming_workspace.radial`,
    and a check script is a body with `return` (as SideFX's own `.radialmenu` files write it).
  - A radial entry calls the controller function the panel's button fires (`workspace.run`): the open panel's
    controller (`controller.live_panels()`, every panel made, docked or floating), else one on the scene's
    node with a `StatusView` (messages to the status line), else the status line says there is no node.
  - The radial menu is switched by the PANEL (`controller.panel_shown` / `panel_hidden`, through the adapter's
    `radial_on` / `radial_off`): `hou.ui._setActiveRadialMenu` (private in H22; the panel asks once to pick it
    by hand when missing). A desk's `radial menu set` line was tried and not used: going back to the user's
    desktop left ours on. What was the user's is kept on `hou.session`, so a module reload keeps it.
  - Paint state like Attribute Paint: `brush_keys.py` is the pure part (HUD rows / values, bar, wheel x1.1 a
    notch, Ctrl+Shift drag x2 per 120 px, menu items), `grooming_paint_state.py` binds it. One source:
    `grooming_masks.set_brush(..., source=)`; "panel" (the default) tells only the state, anything else also
    calls `HOOKS["brush"]`, which marks the panel dirty and its poll (`flush_brush`) shows it: a drag changes the
    radius at the mouse's rate and rebuilding the Properties per move would slow it. The state writes HUD and
    bar deferred and coalesced (`_queue_show`): Houdini ignores a bar write made from `onMouseEvent`, and a
    write from code fires no `onParmChangeEvent` (so no loop; `field_change` also drops a value the brush
    has). The bar is written BOTH ways (t72 gui2 / gui3): the kept `state_parms` dict alone reached the bar on
    the next callback only (the bar one change late), `viewer._setCurrentStateParm` alone was put back by that
    dict on the next callback (the bar stuck at its first value). A radius / grey / softness / mode change recounts and recolours nothing (`view_shown`): only a view
    change does. F is a hotkey of the state's menu (`bindHotkeyDefinitions`), so Houdini's frame-on-F does not
    run; `onKeyEvent` must return False for it. The wheel is consumed while painting (no dolly).
  - What GUI tests can and cannot do here: the bar and HUD are Houdini's own UI, not Qt and not in a flipbook
    (grab the main window); `_evalCurrentStateParm` reads the bar, nothing reads the HUD back (the state keeps
    what it sent in `STATS["hud"]`); a change typed in the bar is simulated as `_setCurrentStateParm` + the
    state's `onParmChangeEvent` (Houdini's own call is not triggered by a script); a menu item is chosen by
    calling `onMenuAction` (RMB opening the menu is seen through `onMenuPreOpen`); a synthetic wheel reaches
    the state only when sent to the `RE_Window` widget (the GL widget's grandparent).
  - GUI tests of the workspace run Houdini on their own `HOUDINI_USER_PREF_DIR` with the suite on
    HOUDINI_PATH (`run_gui.sh` in t72), so the user's desktops and radial menus are never touched.
  - Paint ended by a deleted node or File > New: the state's exit hook (`_on_paint_exit`) reads nothing from
    the node (`node_alive` first); it raised `hou.ObjectWasDeleted` inside `_came_back` (t72 gui1).
  - Fix round t73 (the checker's findings): Paint and the radial Erase need ONE paint layer selected
    (`layers.paint_needs`, text `PAINT_NEEDS` + what is selected); without it they say so and change nothing
    (no state, no write, brush as it was). The panel never holds several layer rows (the one clicked last is
    the selection). A radial entry's message also goes to the status line (`grooming_workspace._said`). The
    HUD shows the wheel on the Radius row and the drag on its own row (a key spec "mousewheel / Ctrl + Shift +
    LMB" drew only the drag). `brush_keys` takes NaN / inf / huge / non-numbers: always a finite radius in the
    limits (steps capped at `STEPS_MAX`). Known, not changed: F reaches the state only while the viewport has
    the keyboard focus (Houdini's hotkeys), and a pane the user closed in the desktop stays closed when they
    switch back (Houdini keeps a desktop's changes for the session).
- Panel look from the MonoFX Loader (t74, 2026-11-19, the user's pick "C" of three; sandbox `tests/t74_loader_look/`:
  `lessons.md` = what was taken, adapted or left and why, `mockups/`, `report.md`; `ui.py`'s docstring has the layout):
  - The look helpers are the suite's shared ones, `tools/fx/look.py` (also the Loader's); `ui_look.py` keeps the
    panel's names and its differences as parameters or thin subclasses: `_crisp_icon` = Selected mode + a
    `DISABLED_ICON` pixmap + cached, `scale_css` without the border step (`round_borders` does it), `_Props` /
    `_Section` on `Sz` and role labels, `SELECTED_HOVER` #2c395b (the Loader keeps #2e3c5f). Panel-only colours
    (BUTTON..., DISABLED_ICON) stay in `ui_look.py`. Before 2026-11-19 these were copies (`anim_loader` was not on
    the branch).
  - The tree is painted by `_RowDelegate` for every column and by `_LayerTree.drawRow / drawBranches`; the sheet
    has no `QTreeWidget::item` / `::branch` rule any more. Measured before the change in the live t72 grab: the old
    `::item` rules did paint PANE / SELECTED in Houdini 22 (the Loader's grey came from palette colours), but they
    beat an item's own colour, so per-row lines, separators and a hover over the branch area needed the delegate.
    Check tree colours in the live window (`QWidget.grab` of the tree inside Houdini, t74 `t74_gui.py`
    `live_tree_*`), not only offscreen.
  - One background for every row (the user's rule on the Loader): layer rows are not tinted; t70's "row tint: not
    built" is closed as decided. Separators (the user, 2026-11-19): a `LINE` hairline under each row, vertical lines
    eye | name | status, all covered by a hovered or selected row; so the status column takes ONE width for the whole
    tree (`_fit_status`: widest words, at most 40 %).
  - No "·" joins anywhere the artist reads (the user, 2026-11-19): Properties show `details` (label / value rows,
    from `controller.properties` / `layers.layer_properties`; `subtitle` is kept, comma-joined, for other readers),
    counts and lists by commas, clauses and message parts by "; ". The HDA's own status line still has dots (no HDA
    change in t74).
  - The eye: drawn = filled (pupil cut out), not drawn = outline with slash; who decided is the tone: TEXT_LABEL
    the row's own, `FAINT` (#6b6b73 since t74, 3.1:1 on a hovered row; #63636b was 2.75:1) a group / layer /
    isolate, `FAINT_ON_SELECTED` on a selected row (`ROLE_EYE`); the accent eye of isolate went.
  - The Loader's 40 % dim eye measures 2.2:1 on PANE and its selected + hover colour `#2e3c5f` 4.36:1 under
    TEXT_LABEL: here `FAINT` and `SELECTED_HOVER` #2c395b (4.56:1). Settings rows and stat cells go compact when
    Properties are narrower than `COMPACT_PX` (540 x scale), so the tree can have ~300 px at 760 px wide.
  - Live Houdini (t74 `gui_panel*`): the painter Houdini hands a delegate draws antialiased, so a 1 px `drawLine`
    landed on two pixels at half strength (#1f1f24 for LINE): separators are `fillRect`s of 1 px. A `QWidget.grab()`
    of the tree's VIEWPORT came back without the state just set (selection, hover); grab the panel (`ui.grab()`) and
    map the viewport's coordinates (`viewport().mapTo(ui, ...)`), with the panel's poll stopped while sampling (a
    rebuild deletes the items being sampled). Measured: row #17171b, selected #273352, hover #1f1f25, selected +
    hover #2c395b, branch area the same as its row, separators #26262d, covered on hover / selection.
  - Tests: `tests/test_grooming_look.py` (delegate states by pixels, separators, icon buttons' tooltips and
    accessible names, the eye, the status width, the two-line result line, the sections, no "·").
  - The user on the docked panel (t74, 2026-11-19): the row bar (a layer's D / opacity or blend / opacity) is UNDER
    the tree: above it, showing it on a click pushed every row down and picking a density layer jumped; the tree
    gets shorter at its bottom and the current row is scrolled into view. A layer's status cell shows the value
    alone ("75", "75, 50%"), the unit in the cell's tooltip ("75 /c…" was cut). Bordered buttons are FILLED
    (`ui_look.BUTTON` #25252c, hover / pressed / disabled), fields stay inset (BG_RAISED): quick picks read as
    fields. Icons carry their own Disabled pixmap (`DISABLED_ICON` #45454e, `_crisp_icon`): Houdini drew the
    Normal one, so disabled + / up / down / delete looked usable. The desk `MONO_Grooming` gives the panel its own
    pane on the left (30 %), alone: viewport, then parameter editor over network editor.
    Wide, the tree takes `TREE_SHARE` (40 %) of the window at least and follows it on resize, until the user drags
    the divider (`_tree_user`): after that it only widens when a name no longer fits. Docked at ~1150 px it had
    ~350 px and cut the head's count. The status column has slack over its words (`status_width`): in Houdini
    "per lock" was cut to "per lo…" at the exact width.
    The head's count is a `_FitLabel` (t75): it shows "61 locks, 3 groups", else "61 locks", else that elided
    with "…", and a shorter form carries the full count in its tooltip; it asks for its full width + 2 px and can
    shrink to an ellipsis, so the tree tools beside it never cut it (at 760 px it read "61 locks, 3 group").
    The head is a `_TreeHead` (t75 recheck): LOCKS, the count and the tools on one row while the whole count fits
    beside the tools, else the tools on a row of their own under it, decided by its width alone. A window opened
    at 700-800 px had read "6…" (the tree's room beat the head's need); the head no longer widens the tree.
  - The tree's width (`_tree_width`) is a function of the window's width and the rows only, so a window opened at
    a width and one resized to it match: Properties count as fixed numbers (the 40 % share yields to
    `COMPACT_PX`, whole rows; the names may push them down to 430 px, compact rows), not their minimum as laid
    out (it changed with the compact state); the status column counts its widest words (`_status_words`), not
    its section as left by the last layout; `_after_resize` fits the tree again once the body is laid out (a
    stacked -> side by side switch spread the splitter from its old size). Offscreen checks need
    `QT_QPA_FONTDIR` (Windows fonts): without it Qt falls back to a font about twice as wide.
  - In Houdini a `ui.grab()` right after a scroll can show the tree's rows below the first two from the older
    scroll position (seen in t74 `gui_panel8` and later; not on screen): sample the top rows only.
- v0.2b lock redraw, B1 model and logic (2026-11-20; plan `docs/plans/grooming_v0_2.md` "v0.2b", spike t76;
  tests `tests/test_grooming_spine.py` on three Helen spines in `tests/fixtures/grooming/t76_spines.json`). The field
  names are the contract for B2-B4:
  - `groom_data` schema 7. `Lock.spine`: K control points (handles) in the lock's ROOT FRAME (origin the measured
    spine's first point after Root to skin, rows tangent / width axis / thickness axis there, scene units), [] = the
    measured spine. `Lock.handles`: the artist's handle count (U1), None = by length. A drawn lock is a `Lock` with
    `source` "drawn" (`config.SOURCE_DRAWN`): `curve` its handles in REST SCENE SPACE (no measured spine, no root
    frame, no mesh: U2's animated scalp moves it in a shot), `width_cm`, `thick_cm` at the root, `taper` (share left
    at the tip); its `spine` stays []. `Orphan.spine` / `.handles` keep a missing lock's edit; `Orphan.from_lock`
    is what Detect should build orphans with (the adapter's `apply_detect` still lists fields by hand: B2), and
    `reassign_orphan` hands the edit on (not onto a drawn lock). `migrate()` 6 -> 7 sets the number only.
    `GroomData.add_drawn_lock` (new id via `next_lock_id`, marks regions out of date "<name> drawn") /
    `remove_drawn_lock` (drawn only; the id stays used) / `edited_locks`; `Lock.edited`, `.drawn`, `.reset_spine()`.
  - The rule (`logic.edited_spine`, the spike's VEX line for line; the test carries a scalar port of the VEX and
    matches it to 1e-13 cm): each handle's MOVE against the measured spine at k / (K - 1) of its length,
    Catmull-Rom (uniform, ends clamped) along the spine, added to its points; the frame turns with the tangent by
    the shortest turn; a root stored at the origin (`config.ROOT_MOVED_EPS`) is the measured root, a moved one goes
    through `snap_root` (the network's scalp lookup, U5). Also: `root_frame`, `frame_to_world` / `world_to_frame`,
    `direction_to_frame` / `_world`, `measured_handles` (the no-edit handles), `handle_count` (ceil(cm / 8) + 1 in
    4..12, or the override), `lock_handle_count`, `resample_spine` (another count: least-squares fit of the moves,
    root and tip kept; returns the gap in cm), `rotate_about_root` / `scale_about_root` (about the first point, any
    space), `stroke_handles` (drawn stroke -> fewest handles within `STROKE_TOL_CM`), `redraw_handles` (a lock
    redrawn: handles on the stroke so its EDITED spine lies within the tolerance), `curve_points` / `drawn_spine`
    (a drawn lock's curve and its n-point spine), `drawn_footprint_cm` (`REGION_FOOTPRINT` x width), `drawn_profile`,
    `flat_handles` / `unflat_handles` (the `edit_cp` prim array), `reset_locks`, `curve_gap`.
  - Constants in `config.py` "v0.2b": `HANDLE_SPACING_CM` 8, `HANDLES_MIN` 4, `HANDLES_MAX` 12, `STROKE_TOL_CM` 0.25,
    (`STROKE_HANDLES_MAX` 24 until 2026-11-21: now HANDLES_MAX), `RESAMPLE_TOL_CM` 0.25, `ATTR_EDIT_CP` / `ATTR_EDITED`, `POINTS_STATE`, `UNDO_SPINE`
    (the undo step names), `DRAWN_*` first values.
  - Measured on the fixture (sandbox `tests/t77_redraw_model/numbers.json`): re-sampling 5 -> 8 -> 5 moves the
    edited spine 0.017-0.058 cm, but 0.22 cm for the 89.6 cm lock turned 25 deg (its tip 34 cm away): near the
    0.25 cm tolerance; fewer handles than the edit was made with can miss a local bend (the caller says so).
- v0.2b lock redraw, B2 network and adapter (2026-11-20; sandbox `tests/t79_redraw_network/`, `report.md` there;
  acceptance `tests/houdini/grooming/accept_v02b.py` + `_sub.py` / `_shot.py` / `_lib.py`, pytest
  `tests/test_grooming_adapter_spines.py`):
  - Nodes after `root_skin`: `SPINES_MEASURED` (the spine as Root to skin left it: a mesh lock's handles are in its
    root frame) -> `spine_edit` (prim wrangle `VEX_SPINE_EDIT`, the spike's rule = `logic.edited_spine` within
    0.001 cm; input 1 the rest scalp for a moved root) -> `drawn_locks` (Python SOP `cook_drawn_locks`: one spine a
    drawn lock, `drawn_spine_arrays`, resolved settings via `lock_display_attribs`, `piece` -1, `drawn` 1; detail
    `edited_count`, `drawn_count`, `drawn_group`) -> `SPINES`. `cook_assign` writes `edit_cp` (flat handles,
    `edit_cp_values`) and `drawn` 0 on every mesh spine, and matches pieces to the MESH locks only (`mesh_locks`).
  - `spine_edit` moves the prim `root` only when the root handle moved: the measured `root` is spine_build's, not
    the spine's first point after Root to skin, and rewriting it on an unmoved-root edit moved the footprint (an
    identity edit of hair_back_20 moved hair 0.04 cm). `length` is scaled by the spine's length change; `curveu`
    stays the measured one. Handles all within `SPINE_STILL` (1e-6 scene units) of the measured spine leave the
    spine untouched and `edited` 0: the per-lock loop is chaotic in the last bit (float noise of 1e-7 in P and
    2e-6 in the frame moved hair_back_20's strands 0.04 cm; a recook with no change is exact, 0.0).
  - The carried mesh: `mesh_carry` (point wrangle `VEX_MESH_CARRY` on `mesh_pu`, inputs SPINES_MEASURED and
    SPINES) puts each point of an EDITED lock's piece at its `pu` on the edited spine with the same offset in the
    square frame (tangent, width axis, thickness axis) -> switch `mesh_carry_any` (the mesh itself while no lock
    is edited: no edit = the network before v0.2b) -> `MESH_CARRIED`. Read by `region_join`, `root_place`,
    `region_mesh` and the mesh display (`mesh_show` / `mesh_show_any` before `mesh_color`). Not by the shot
    deform: U4 keeps v0.1's capture on the rest hair mesh for edited locks (the spike measured that one; a
    capture on the carried mesh would need the animated mesh carried too). `mesh_su` stays on the mesh.
  - `split_regions` takes roots from SPINES (a moved root's footprint) and widths from SPINES_LOCKS (measured, as
    before), a drawn lock's radius from `logic.drawn_footprint_cm`; `region_mesh` reads MESH_CARRIED and SPINES.
    `lock_infos` reads root and length after the edit, and the drawn locks from SPINES.
  - The per-lock loop for a drawn lock (piece -1): `piece_or_none` (an empty `no_piece` instead of the Unpack of
    nothing that warned "Input has no packed primitives") feeds `fit_cloud`; fit_to_lock's ellipse does the rest.
  - Input 4 "Animated scalp" (U2, `build_hda.INPUT_LABELS`, max inputs 4, hidden `scalp_wired`, in
    `_KEY_SKIP_PARMS`): unpacked as input 2 (`rest_scalp_names`, `anim_scalp_*`), `ANIM_SCALP` (detail
    `deform_ok`, `anim_points`, `rest_points`; never a warning). The capture loops (`_capture_loop`) pass a drawn
    lock's strands without a capture (switch `*_on_scalp` by its `drawn`); `_deform_drawn` (display
    `deform_drawn_*`, output 1 `groom_drawn_*`) deforms the mesh locks as v0.1 and the drawn ones by the animated
    scalp, each strand rigidly with the skin frame at its root (`VEX_FOLLICLE`: the hit polygon's normal and first
    edge, rest scalp -> animated scalp), or leaves them at rest when it is not wired or has another point count;
    while no lock is drawn the v0.1 Point Deform is used as it is. Point Deform captured on the scalp (the first
    build, and the spike's choice) stretched a fringe drawn lock 1.9-3.5 % on sh025 (limit 2 %): mesh-lock hair on
    the same skin captured that way stretched up to 46 %, the scalp's local stretch read far from the skin; a
    larger radius helped the fringe and made the back of the head worse (1.37 at 0.1 m); Point Deform's piece
    attribute moved nothing. The follicle frame: length 1.0000, roots 0.003 cm off the animated skin (t79 s3). `deform_keys` takes ANIM_SCALP as input 2 (its points in the key only
    with drawn locks).
  - Adapter (every change one undo step named from `config.UNDO_SPINE`, several locks at once; places in the
    node's space): `lock_handles(node, ids)` -> per lock `points`, `frame`, `origin`, `axes`, `count`, `edited`,
    `drawn`, `root_moved`, `spine`, `measured`, `length_cm`, `default_count`, `count_set`; `set_points(node,
    {id: points}, space="points"|"frame", step="move")` -> {locks, roots_moved, message} (a root given where it is
    keeps the stored root, `ROOT_SAME_CM`; a moved root marks regions out of date "<name>: a root moved");
    `reset_points`, `rotate_points(node, ids, axis, degrees)`, `scale_points(node, ids, factor)`;
    `set_handle_count(node, ids, count|None)` -> also `gap_cm` per lock, the message says how far past
    `RESAMPLE_TOL_CM`; `redraw_lock(node, id, stroke)` -> also `gap_cm`, `count`; `draw_lock(node, stroke, width_cm,
    thick_cm, taper, group, name)` -> {id, name, gave, gave_ids, gap_cm, count, message}, the footprint
    (`footprint_owners`) in the same undo step (U3); the group of the lock that gave it most skin
    (`most_skin_group`), named `drawn_NN` (the user, 2026-11-20); a stroke 12 handles cannot hold is taken and
    the message gives the gap (`_gap_text`, also for redraw); `set_drawn(node, ids, width_cm, thick_cm, taper)` (step
    "drawn"); `delete_drawn_locks(node, ids)` -> {locks, took, took_ids, message}: the skin it owned alone goes
    to its neighbours in the same undo step by the rule of Update regions on those prims only (`_split(only=)`,
    `logic.region_owners(every_lock=False)`: with every_lock the last rule gave EVERY lock one of the freed prims,
    all 61 recooked), shared skin keeps its other owners (`give_back`); `edited_ids`, `drawn_ids`, `scalp_wired`, `animated_scalp(node)` -> {wired, ok,
    anim_points, rest_points, drawn, message} (`scalp_text`, the panel's line); `import_spines(node, tool_dir)`
    (`spines_from_publish`: edits by lock name, drawn locks with their id when unused here, regions out of date).
  - Model after t80 (2026-11-21, B2 now owns model / logic / config): `Lock.drawn_curve` (the curve as drawn;
    absent on load = the curve), a drawn lock whose `curve` differs is `edited`, `reset_spine` puts it back; one
    clamp for a handle count (4..12, on load too); at most 12 handles for a stroke (`STROKE_HANDLES_MAX` gone);
    `logic.drawn_handle_count`; `reassign_orphan` hands an edit on only when the orphan has one; rotate / scale with
    a zero or non-finite axis / factor change nothing; a stroke with a non-finite point raises; `add_drawn_lock`
    refuses a curve without length; a stored `source` outside `LOCK_SOURCES` is mesh; `UNDO_SPINE["drawn"]`.
  - Shots as saved are not byte-reproducible on the build before v0.2b either (t79 s5): 7 runs of it on sh025
    differ up to 0.084 cm at frame 30 in 10 locks (hair_back_03 / 06 / 11 / 18, hair_bang_09 / 10 / 19,
    hair_base_02 / 04 / 13), the same locks and per-lock maxima as this build; at rest the same runs already differ
    up to 0.0065 cm (the per-lock loop with "Fit lookup per lock" off, an old scene), the deform amplifies it.
  - Detect: `match_locks` and `apply_detect` leave drawn locks alone (never missing, never new) and build orphans
    with `Orphan.from_lock` (a missing lock keeps its edit). Publish: grooming_data.json holds the edits (schema
    7), publish.json `spines` names the edited and drawn locks (`spine_record`).
- v0.2b lock redraw, B4 panel (2026-11-22; mockup B of t78 + `review_b.md`, the pick and the review's fixes in
  `ui_spine.py`'s docstring; sandbox `tests/t82_spine_panel/`, `report.md` there; pytest `tests/test_grooming_spine_panel.py`):
  - Files: `spine.py` (Qt-free: texts, the handle count over several locks, the `SpineMixin` of the controller, mixed in
    BEFORE `LayersMixin` so its `paint_on` / `paint_off` / `select_layer` / `_on_paint_exit` wrap v0.2a's) and
    `ui_spine.py` (the Tool bar, the tinted strip, the drawn lock's section, row icon and words, the trash / Del /
    right-click delete). Hooks only in `controller.py` / `ui.py` (CRLF, patched by script keeping CRLF); `ui_layers.py`
    lost the paint layer's Paint button (the Tool bar's Paint cell replaced it, the user 2026-11-20) and shows a
    density layer whose drawn lock was deleted under All locks with "no lock" (`spine.no_lock_layers`;
    `layers.owner_name` says "no lock").
  - The tool in hand: `controller.tool` (Edit points / Draw lock) or `paint_layer_id` (Paint): `tool_now()`. One tool at
    a time: entering one ends the other (`set_tool`); Esc ends the shape tool first (`escape` -> `tool_off`); another
    node / node gone / panel hidden end it (`tool_reset`, which also unhooks). Enter toggles Edit points, `-` / `+`
    step handles while it is on (panel shortcuts, a text field keeps its keys); the radial menu got Edit points
    (top_left) and Draw lock (right), Scalp X-ray moved into the Display submenu (`workspace.ENTRIES`).
  - B3's modules are imported lazily: `adapter.points_state` (tests), else `apps.houdini.grooming_points_state` only
    when the adapter is Houdini's own module; `tools.fx.grooming.points_keys.HOOKS["tool"]` is a LIST of callables
    (B3's interface; the panel appends `_on_tool_record`, shown on the next poll) and `HOOKS["write"](node, result)`
    cooks the state's write in the loading line and keeps a draw's `gave` for Properties' "Skin from". Without the
    state the tool is the panel's own view state and the strip's Reset / Handles / drawn values still work (the
    message says the state is not installed).
  - Edit points never refuses: no lock -> the strip says "Select a lock"; a group = its locks; locks not drawn
    (hidden, isolated out) get no handles and the line says why (`edit_targets`). Minus / plus act on each lock
    (`stepped_counts`: one `set_handle_count` per target count, all in one undo step through `adapter.undo_group`
    or `adapter.hou.undos.group`); "auto" puts the number by length back. Reset shape is in the strip while Edit
    points is on, beside Hidden / Flip root / Exclude otherwise, never both (review 2).
  - Rows: `shape_edited`, `drawn`, `at_rest`, `editing` (attached by `attach_spine`); `edited` / `drawn` are neutral
    TEXT_LABEL words (review 13), an amber triangle (`ui_spine.WARN_ICON` part, drawn by the delegate) while a drawn
    lock stays at rest in a shot (`adapter.animated_scalp`, cached per data shown); the own-settings dot is unchanged
    (badge "edited") and its filter word is `own`; filter words `edited` (shape) and `drawn`.
  - Strip layout (`ui_spine._Flow`): groups on one line, on two when they do not fit (a larger font size), never
    clipped; narrow (< NARROW_PX) the cells are icons, Reset a 28 px flat icon, spacing 6: one line at 400 px (39 px
    strip at scale 1, 50 px at 1.5); at 760 px Reset shape goes to a second line, as in the mockup. Minus / plus are
    `step_size` (28 px, 24 at least): at the default Medium font size 24 x 28 gave 22 px, under the floor.
  - Joined with B3's state (2026-11-22, t82 `gui4`): the panel registers on `points_keys.HOOKS` itself (the state
    module has no HOOKS of its own; a fake with one passed while the real joint did nothing). The record's `tool`
    "paint" (`yield_to_paint`) ends the panel's shape tool; its `lock_ids` (a click on hair) become the panel's
    selection (an empty list, a click on empty space, changes nothing); `held` lights the strip's cell; `message`
    goes to the message line. `spine_follow` never rebuilds the tree: it runs inside Qt's selection signal of a
    row click, and `show_tree` there deleted the item being selected, Houdini crashed in
    `QTreeWidgetItem::setSelected`; the rows' "editing" marks come on the next poll (`_rows_dirty`). Offscreen
    tests never caught it: only a tree rebuilt while Qt was still inside its own call does.
  - grooming-check on an edited groom (B5, t83, 2026-11-22): `qc_metrics.py` measures every lock against
    `MESH_CARRIED` (`--mesh modelled` for comparison only), the reference against `pieces`. A drawn lock (`drawn` on
    SPINES) is left out of every mesh number (VEX writes -1, `summary` masks it, its row's mesh fields are None) and
    gets a "Drawn locks" section (roots off the rest scalp, strands against `lock_infos`, hair width / thickness at
    0.3-0.9 against `logic.drawn_profile`) and two checks only when one exists (`drawn_root_skin_worst_cm` 0.0025,
    `drawn_width_off_worst` 0.20), so a groom without one keeps t55's 27 checks and numbers. Helen with hair_bang_11
    moved 2 cm, hair_bang_05 turned 25 deg, hair_bang_15 redrawn, drawn_01: carried passes (hair_bang_11 far p95
    0.46 cm, tip off centre 0.01); modelled fails tip_center_off 1.67 and lock_outside 1.0 (far p95 1.74 cm). drawn_01:
    274 / 274 strands, roots 1.5e-5 cm off the skin, width 0.83-0.84 of the set. `accept_v02b.py` q1 runs it.
    `qc_metrics.py` imports `hou` lazily so `tests/test_grooming_check_metrics.py` tests its pure parts.
  - `qc_capture.py` shot close-up (`QC_FRAMES` + `QC_LOCKS`): output 1 blasted by lock id at each frame, and its
    animated piece alone in a second picture (ANIM_HAIR + the rest `piece` by point number; drawn with the hair it
    lies under it, Alpha draws only inside packed geometry, a template's wire vanished on white), camera on the animated piece's box
    + 3 cm, framed shrunk to 0.55 about its centre, so one lock in several scenes gets the same camera at a frame. The
    `lock_*` close-ups blast output 1 by lock id (the eye never reached it). Compare shows the carried mesh, adds the
    modelled piece for an edited lock, frames a drawn lock on its hair.
- v0.2b, an EDITED lock in a shot (U4 changed by the user, 2026-11-22; sandbox `tests/t79_redraw_network/u4/`):
  - What v0.1's deform did (t79 u4 diag, sh020): hair_bang_11 moved 5 cm turns its tip 22 deg from the unedited lock at
    rest but 59-92 deg in the frames (the hook the user saw), its offset in the lock's moving frame changes by p95
    2.8-3.9 cm: the deform captures the moved points on the hair mesh far from where they now lie.
  - (REPLACED 2026-11-23 by the piece deform below: the `edit_ride_*` path is gone.) Built: `edit_ride_spines` (`VEX_SPINE_PACK`: per edited lock its unedited spine, two copies 1 cm out along the
    width / thickness axes, and its edited spine, prim `skey` = lock_id x 4 + kind) -> `edit_ride_capture` /
    `edit_ride_deform` (v0.1's Point Deform) -> `edit_ride_fk` (`VEX_EDIT_FK`: per spine point the unedited spine's
    rotation rest -> frame, `rot`; the edited spine rebuilt from its root, each rest segment turned by the rotation
    there and keeping its length) -> in `_deform_drawn`, `*_edited_ride` (`VEX_EDIT_RIDE`: each strand point around the
    rebuilt spine with its rest offset turned, blending into v0.1's own deform over the first 0.2 of the strand, so
    the roots move as the unedited lock's). Unedited locks keep v0.1's points; with no edited lock nothing changes.
  - Tried first and dropped: the same offset in the unedited spine's moving frame (offset change p95 0.28-1.6 cm on
    sh020 but strands 13 % longer: an offset curve changes length where its centreline bends); its frame from both
    offset copies took the hair mesh's local shear. Where the piece moves rigidly (sh025) every method is near exact.
  - Measured (t79 run7): length 0.998-1.004, roots as the unedited lock's, nothing left behind, tip turn within 3.7
    deg of rest (sh020) and 0.2 deg (sh025), for 2 cm, 5 cm and 25 deg. A shot frame with one edited lock ~1.4-1.6 s
    against ~1.0 s (the split of the 4 M points). Decided (the manager, 2026-11-22): no stretch wins over the same
    offset; `s1b` grades the offset change in the moving frame on sh025 only (p95 <= 0.25 cm; measured 0.02-0.10), and
    reports it on sh020 where the piece bends (p95 0.66-2.07 cm against the unedited lock's own 0.36-0.56).
  - An EMPTY Blast group deletes everything: `drawn_group([])` is `@lock_id==-1` (with an edited lock and no drawn
    one every strand had gone to the drawn branch and stayed at rest).
  - Deleting a drawn lock: 3.8 s -> 0.49 s (`_prim_centres`: the fine scalp's prim centres and groups read in bulk,
    summed in vertex order, bit-identical to the per-prim loop; mesh distances by `primFloatListAttribValues`).
    Update regions gains the same (2.2 s on Helen).
- v0.2b B2 after the independent check t84 (2026-11-22; FAIL on B-1 / B-2 / B-3; `t79_redraw_network/report.md`
  section 8 answers each item):
  - Every adapter write that takes numbers goes through ONE guard, `_finite` (with `_places` for handles and strokes,
    `_in_range` for a factor / width / thickness, `_reach`): a NaN / inf, a wrong shape, a count outside
    HANDLES_MIN..HANDLES_MAX (set_points took 2, 3 and 100) or a value past a limit raises ValueError naming it,
    BEFORE anything is written. A NaN handle had been stored, written as `NaN` into groom_data (not JSON) and lost on
    reload. `set_handle_count` takes a whole number only (7.5 and "7" went through int()); `draw_lock` refuses an
    unknown group.
  - Limits in config (B-2; scale 1e9 segfaulted the cook, width 1e6 cm and a stroke 1e6 cm off the skin ran for
    minutes): LOCK_REACH_MAX_CM 300 (every handle / stroke point from the lock's root; floor-length hair on a 2 m
    character is under 2 m; measured on Helen a 30 m stroke and an 8 x scale still cook in ~1 s, so the cost is far
    off: the hang was 1e6 cm), STROKE_SKIN_MAX_CM 5 (a stroke starts on the skin; a few cm allows one started over
    the hair; t84 minor 4's 80 cm redraw is refused), SCALE_RANGE 0.1-10 a call, DRAWN_WIDTH_RANGE_CM 0.05-10 (the
    footprint is 0.5 x the width round the root: 10 cm took skin from 5 locks, 20 cm from 42 of 61, 40 cm from all),
    DRAWN_THICK_RANGE_CM 0.02-5. Costs in `t79/limits.out`, `reach*.log`.
  - A result within `config.SPINE_STILL` of what is stored or measured writes nothing (no undo step, "nothing
    changed"): rotate with a zero axis or 0 deg, scale 1, the measured handles given back (minor 1). SPINE_STILL,
    ROOT_SAME_CM and DRAWN_ROOT_FADE (the drawn root's fade, 0.25 of the length) live in config (minor 6).
  - `lock_spines(node, ids)` (public, for the viewer state): per lock `spine` (SPINES) and `measured`
    (SPINES_MEASURED, None for a drawn lock), each P / tangent / axis as numpy, and `drawn`. The viewer state
    still reads `_spine_rows(_cooked(...))` (B3's to switch).
  - accept_v02b: e1's identity passes by construction now (nothing written), so e1 adds the case that can fail:
    every handle but the root 5 x SPINE_STILL off, the spine = logic.edited_spine within 0.001 cm (9e-6 / 1.3e-5 cm).
    Found there: that 0.0005 cm spine move regrows hair_back_20 with 2.4 % of its strand points moved past 0.01 cm,
    0.5 cm at most (hair_bang_11: 0.0005 cm everywhere): reported, not graded. v1 replays t84's bad inputs on the
    node. s1 adds hair_bang_05 moved 2 cm (B-3) on sh020 frames 10 / 25 / 75 / 105 / 135 (and the earlier ones).
    r1 and s5 grade against the old build's own spread over 7 of its runs, kept in `<base>_samples/<base key>/
    <scene>_<sha1>/` and reused (`against_base`): NO BUILD IS BYTE-STABLE FROM RUN TO RUN (old build: Helen 0.0022 cm,
    sh020 0.05 cm, sh025 0.084 cm); byte-equal pairs are reported, not required.
  - B-3, hair_bang_05 moved 2 cm in sh020 under U4's deform: length 1.005 at frame 10, then 1.02-1.05 (median; p95 to
    1.17) from frame 25 on, past s1's 2 %. Cause: v0.1's capture folds this lock's unedited spine BACK on itself there
    (its turn total 466-493 deg against 228 at rest, 86-90 deg at one point), so the rest -> frame rotation the
    edited lock rides spins ~180 deg over two spine points and strands 1 cm out are thrown (a 0.76 cm segment became
    2.1 cm). Tried and dropped: the rotations smoothed along the spine (quaternion Gaussian, 2 cm: frame 10 1.005 ->
    1.000, the fold-back frames 1.042, but the tip turn rose to 8.65 deg on hair_bang_11 and 14 deg on hair_bang_05
    against 5; 5 cm: 1.040); the place along the spine kept monotone along a strand and the previous axis carried
    where the width copy is weak (no effect). The deform is run11's. The unedited lock under v0.1 stretches there too
    (p95 1.08). Left to the manager: the line holds on hair_bang_11 and on sh025, not where the hair mesh folds a
    piece back.
- After t84's second round (2026-11-22; the plan's "After 037b's recheck"; accept_v02b v1 / v2, pytest
  `test_grooming_adapter_spines.py`):
  - `groom_data` is read RAW (`data_text(node)` = `parm.unexpandedString()`; also `grooming_masks`): `evalParm`
    expands a backslash, a backtick and `$`, so a lock or layer name `c\` broke the JSON (the node could not cook
    until Undo), `cost $5` read back `cost ` and ``a`b`c`` `abc`. `parm.set(text)` already stored the text as given.
  - Lock ids go through `_lock_id` / `_lock_ids` before anything is read: whole numbers (text of one is left), a bool
    or a fraction refused, a duplicate counted once (rotate [L, L] turned L twice); `set_points` refuses a lock
    given twice. A rotate axis is divided by its largest component first ((1e200, 1e200, 0) overflowed the norm).
  - `tol_cm` in `config.STROKE_TOL_RANGE_CM` (0.01-10); a stroke over `config.STROKE_POINTS_MAX` (2000, cost in
    config) is thinned evenly by index before the fit (`thin_stroke`: 100,000 points drew in 0.1 s; 400,000 took
    159 s); a zero-length stroke is refused by draw as by redraw. A drawn lock's name is text, not only spaces, and
    no other lock's (or missing lock's); `set_drawn` refuses a taper outside 0-1 as `draw_lock` does.
  - Roots under an edit (the manager's decision on part 2): an edit that leaves the root handle in place moves no
    strand root; per strand id the root is the unedited lock's (accept e6, within 2e-7 cm). The edited lock is
    regrown, and `region_join` / `root_place` (and their `groom_` copies) read the mesh as modelled (`mesh_pu`), not
    `MESH_CARRIED`: reading the carried mesh, a turned or bent lock's mesh lay elsewhere over the skin, other skin read
    as under floating mesh (`far_w`: roots sent to the start disc), the joins moved and `root_spread` dealt the ids out
    again (hair_base_07 turned 25 deg: 78 % of roots moved by id, p95 9.3 cm, 16 % off its own root set). Where roots
    sit is the regions' call; a moved root handle marks them out of date (U3 / U5). MESH_CARRIED is still read by
    the mesh display and `region_mesh`.
  - Known, left: the regrowth itself is chaotic in the last bit on a wide cap: hair_base_07's handles moved 1e-4 cm
    move its strands up to 0.272 cm (43 % of points over 0.01 cm) with every root exact (hair_back_05 0.021 cm,
    fringe 0.0002 cm). Carrying the unedited lock's cached strands onto the edited spine instead (the carry rule
    `mesh_carry` uses, per strand point) would make a tiny edit a tiny move; see t79 report 9.3 for the cost.
  - r1 / s5: 20 samples of the old build made from the COMMITTED ed7d0de (`t79/base7_suite` = git archive; t79's
    base6_suite had a rebuilt HDA), graded against the largest difference between any two + 2 float32 steps.
- The shot deform replaces v0.1's (B-3 decided by the user, 2026-11-22; plan "The cause, and the deform that replaces
  v0.1's in shots"; t79 report 9.4-9.6, acceptance s6 = `tests/houdini/grooming/accept_v02b_deform.py`):
  - Why: v0.1's Point Deform (radius `deform_radius` 2 cm, maxpt 100) gave a strand point the motion of every rest mesh
    point within 2 cm, whatever lock it belonged to (47 % of the weight on average from other locks' pieces), and inside
    a hooked fringe piece also the hook's other arm: 19 lock-frames folded on sh020, 10 on sh025, where the piece does
    not fold. Capturing on the own piece alone left the hooks; any deform that follows each lock's own piece moves
    every lock 0.15-1.5 cm p95 against v0.1, so "within 0.1 cm of v0.1" was dropped for shots (the manager).
  - What: each strand point stores `dfu`, its place along its OWN piece (`pu` of the nearest face of that piece, on
    MESH_CARRIED so an edited lock's strands find their place on its carried piece), and each strand its root's
    neighbours on the rest hair mesh (`rnb` / `rnw`, any piece, within `config.ROOT_ANCHOR_CM`), in the capture loop
    (`VEX_PIECE_U`; 4 bytes a point + 48 neighbours a strand where v0.1's capture was 800 B a point). `piece_samples`
    (rest only) puts `config.PIECE_SAMPLES` places along every piece, from 2 sigma to 1 - 2 sigma of `pu` (whole windows:
    a one-sided window at a piece's end sat inward by an amount that follows the point spacing, which a stretching piece
    changes, and kinked strands 80 deg), each listing its Gaussian window's points; `piece_fit` (per frame, parallel
    over the ~2,900 places) gives the window's mean in the frame and its best rotation (Kabsch by `svddecomp`; a local
    linear fit of the centre was tried and dropped: it extrapolated the animated mesh's local jitter at the ends);
    `piece_fk` rebuilds an EDITED lock's centreline from its root with those rotations (U4's rule, no stretch). A
    strand point: e1(u) + (P - e0(u)) * rot(u), past the first / last place carried rigidly by it; its root zone takes
    the translation of its root's neighbours with ONE rotation, the piece's at the strand's root (the root-zone rule,
    2026-11-23; each point's own bent the root half up to 58 deg, v0.1 76), and blends into that over
    `config.ROOT_BLEND` of the strand. One deform for edited and unedited locks; drawn locks pass it and keep the follicle (VEX_FOLLICLE);
    an animated mesh of another point count keeps v0.1's answer (rest pose, `deform_ok`), and so does one with a point
    that is not finite at that frame (`bad_points`, checked each frame in `ANIM_HAIR` / `ANIM_SCALP`; `deform_problem`
    and the drawn locks' line say how many): one inf point of hair_bang_11's piece gave 5,302 NaN strands across 20
    locks with no error (t84 round 3). Mesh / guide display parts are
    still Point Deformed (their own mesh), so `deform_radius` now only drives those.
  - A bad frame's message is of that frame: the panel keeps the scalp's line per data and frame (`adapter.current_frame`;
    kept per data only, a bad frame's line stayed on good frames), and the point-count sentence is not added to it. What
    is NOT covered: the panel does not re-read on a frame change (poll looks at the data), so scrubbing onto a bad frame
    shows the hair at rest with no line until something refreshes it, `deform_problem` is read when Shot deform is
    turned on and at publish, at the frame of that moment only, and the warnings inside the locked HDA reach no artist.
  - Known coupling (t84 round 3): the root zone takes the translation of its root's mesh neighbours from ANY piece
    within ROOT_ANCHOR_CM, so a piece moving on its own moves the root zones of the locks rooted near it: one piece
    moved 5 cm moved 20 neighbouring locks' roots up to 1.25 cm (22-25 %; 50 cm gave 12.5 cm), median 0. Roots off
    the animated scalp follow the lift of those neighbours (t79 9.15: root off vs the neighbours' centre's lift,
    correlation 0.92-0.95; hair_bang_20 at sh020 10 its worst tenth's neighbours lift 0.69 cm, hair_back_03 at sh025
    30 1.47 cm, own piece); turning the stand-off by the scalp's rotation instead of the piece's changes it by 0.25 cm
    at most.
  - An edited lock's root zone turns by the piece's rotation at its root's place on the piece AS MODELLED
    (`VEX_PIECE_U` `rdfu_shift` = that place minus the place on the carried piece, 0 for a lock not edited): read on the
    carried piece the place slid with the edit (hair_bang_19 turned 25 deg: up to 0.11 along a piece whose rotation
    changes fast at the crumple), and its roots sat up to 0.20 cm from the unedited lock's in sh020 frame 10 (t84 round
    3, by strand id). Now 0 by id. Unedited locks (control, 3 runs a build, every strand, sh020 10 / 25 and
    sh025 5 / 25): `rdfu_shift` 0 on all; before against after identical but hair_bang_20 on sh025 (0.0059 cm), which
    two runs of one build also differ by.
  - Frame to frame, every pair (t79 9.18): s6 grades all consecutive pairs of the playbars (sh020 0-120, sh025 0-45; a
    5-frame window had shown a worst of 1.09). As built 41 sh020 pairs are over 1.4 (worst 3.50, hair_base_20 52 -> 53),
    sh025 none. 40 are the root zone's neighbours from other pieces (own-piece neighbours or no anchor: 1 left, the tip of
    hair_bang_03 32 -> 33, not traced); own-piece neighbours move every lock and put more roots off the scalp, so not
    built. Roots carried by the animated scalp (trial, not built): 0 roots over 0.1 cm, but 150 sh020 pairs over 1.4
    (worst 18) and root-zone stretch to 2.3 x on hair_bang_20. A short window hid both: grade every pair.
  - On sh025 13 back locks gain ~52 deg (max 58.6) of joint turn over rest on most strands near the root, under the fold
    rule's 90 (t79 9.20). v0.1's deform (a3b2d08) has it, worse: 20 locks over 30, worst 76. Cause, by experiment: the
    root zone turns each point's offset from its root (up to 13 cm) by that point's OWN rotation along the piece; one
    rotation per strand (the root's) alone makes it 0 locks, 27 deg, and changes no other line: built (t79 9.21; s6
    grades the joint turn on sh025, 30 deg). It moves the hair's distance to its own piece on sh025 by up to 0.18 cm
    both ways (p95 0.230 -> 0.240, worst 0.36 -> 0.26) and costs 4-7 % a frame.
  - Root zone by experiment (t79 9.20; nothing built): the scalp trial's jump is the polygon frame's float32 noise (a 0.09 cm
    polygon turns 2.2 deg while the skin turns 0.03) times the 13 cm lever; the scalp's translation with the piece's rotation
    does not jump (1 pair over 1.4 against 150). A zone over 0.7 of the strand takes the hair off its own piece (0.9 cm):
    always read the hair-to-piece distance beside the joint and stretch lines. `scalp_patch` as first written fell back
    silently where the scalp is coarse (forehead): an experiment that can fall back must count how often it did.
  - A test that reads `groom_data` with `evalParm` makes Houdini evaluate a backtick in a lock name as an expression;
    the failed expression stays in the process's error state and the next SOP verb reports it (t84 round 3:
    ``a%(x)s${HIP}`b``, `grooming_masks._vertex_tables`' attribpromote raised). The tool reads it raw and is not
    affected; tests must read it with `unexpandedString()`.
  - VEX traps met: `vector(prim(...))` / `vector(point(...))` picks the float overload and copies one number into all
    three (roots landed at (x, x, x)): read into typed variables. A rotation fitted to a root's neighbours alone is
    ill-posed where they lie near one line (a ribbon's edge: 0.9 cm with no animation); fitted per root where they
    spread enough it fixed sh025's roots but stretched the root zone (p95 1.10 against v0.1's 1.07): not kept. A
    detail wrangle over every piece's points per frame cost 0.7-0.8 s; the rest-only sample lists + a parallel fit
    0.1 s. Prototype nodes outside the HDA must be force-cooked per frame (an Object Merge of an inner node did not
    pass time dependency on).
  - An edited lock's rebuilt centreline takes its piece's own length change segment by segment (`piece_fk`; the plan
    2026-11-23: the edit adds no stretch of its own): kept at rest length it was 2-4 % off the unedited lock where the
    pieces stretch. A strand's place never goes back along it (`VEX_PIECE_U`).
  - Lines (the plan, 2026-11-23, after the cause was traced: the animation stretches the pieces): unedited strand
    length within 5 % (p95) of its piece's length ratio over the strand's span; edited median within 2 % of the
    unedited lock's at that frame; roots within 0.1 cm (p95) of the animated scalp. s6 run19s6 (all 61 locks, sh020
    frames 10 / 25 / 45 / 60 / 75 / 105 / 135, sh025 5 / 20 / 25 / 40 / 50): 0 folds (v0.1 19 / 10); nothing left behind;
    every edited case (sh020's 20 fringe locks, sh025's 9) within 2 % of the unedited lock and 5 deg; output 1 0.29-0.43 s
    a frame (v0.1 0.94-1.13). Not met, causes in t79 report 9.7: length against the piece on 36 / 5 lock-frames (v0.1 64 /
    25; fringe bang_02/03/04/07/12/14/19/20, back_15); roots over 0.1 cm on 76 / 58 lock-frames (v0.1 78 / 30): the
    animated hair mesh by the roots lifts off the head in the shot (hair_back_03 on sh025: p95 0.45 cm at rest, 1.40 at
    frame 40), and roots that follow the mesh leave the scalp with it; with the animated scalp wired they could follow
    the skin as drawn locks do (not built). Frame to frame (no jump asked): a strand's tip past its piece's last sample
    rides that sample's rotation, which jitters with the end of the animated piece: hair_back_07 sh025 20 -> 21, tip
    0.99 cm against the piece's 0.56.
  - (b), the jump at a piece's end (the manager, 2026-11-23): the cause was 32-bit sums, not the end rotations. The
    shots sit ~330 m from the origin and VEX sums positions in 32-bit floats: a window of ~2,600 points' centre was
    0.34 cm off, by a different amount every frame, so an end place moved 0.95 cm where its points moved 0.53
    (hair_back_07, sh025 20 -> 21: the tip 1.75 x its piece). Every sum of positions (`piece_samples`, `piece_fit`,
    `VEX_PIECE_ROOT`) is now taken as offsets from the window's first point: the tip moves 0.57 cm, the frame-to-frame
    worst 1.09 x. Tried and dropped: replacing a loosely fitting place's rotation by its neighbours', a limit on the turn
    between places (45 deg), and freezing the rotation past the last well fitting place (fit residual over 0.25 of the
    window's size): each folded fringe locks that did not fold (sh020 14 lock-frames, edited tip turn to 66 deg) or sh025
    back locks. Left: hair_bang_20's tip crumples in sh020 frame 10 (fit residual 0.5-0.9 of the window), its places
    flip 45-133 deg and the last strands draw a flat block (look4 `sh020_hair_bang_20_*_f0010_b.png`). Traced
    (t79 9.13): the piece's last tenth folds back on itself and the hair follows it (on the piece within 0.2 cm, places
    right to 0.011); points past the last sample are not the cause. Tried and dropped (t79 9.14): where residual / size
    passed 0.5, points carried by their 8 nearest own-piece mesh points blended by the residual. The line is crossed
    all shot long by sh025's 20 back locks (2.14 on hair_back_15, mid-lock): in 2.6-6 % of their point pairs the
    distance changes over 20 % (p50 1.000), and back hair moved up to 16.4 cm. Why is NOT established (a part of the piece
    moving apart, its points the nearest ones, was assumed, never tested). A residual line does not tell a tip folding back from a piece made of
    parts; nearest points would have to be limited to the strand's own part and place.
  - accept_v02b after the change: s1 grades the edited lock against the unedited one at that frame (the plan's line);
    s5 (three-input scenes) grades the same strands and points a strand and no error, and reports the move from v0.1
    (3.1 / 7.6 cm at most on sh020 / sh025), since the deform that replaced v0.1's moves every lock; r1 (rest) still
    holds this build to the old build's own spread.
- v0.2b lock redraw, B3 viewer state (2026-11-22; sandbox `tests/t81_points_state/`, `report.md` there; GUI acceptance
  `tests/houdini/grooming/accept_v02b_gui.py`, pytest `tests/test_grooming_points_keys.py`):
  - `apps/houdini/grooming_points_state.py`: ONE Python state `config.POINTS_STATE` for Edit points and Draw lock,
    entered by name on the node as Paint is (selects the node, `_came_back` when Houdini drops it, ends on another
    node selected, the node deleted (BeingDeleted), File > New / Open (`hipFile` BeforeClear / BeforeLoad), Esc from
    anywhere (application filter)). It never writes the data: one adapter call a gesture on release (`set_points`,
    `rotate_points`, `scale_points`, `redraw_lock`, `set_handle_count`, `draw_lock`), then the node cooks, or
    `points_keys.HOOKS["write"](node, result)` does it for the panel. A move of handles of mesh locks goes as
    `space="frame"` with the handles that did not move kept exactly (a moved root's cooked place on the skin is not its
    stored place: given back in node space it read as moved again); drawn locks in node space; both in one
    `hou.undos.group` when mixed.
  - The panel's interface: `enter_points(node, ids)`, `enter_draw(node)`, `exit_tool()`, `set_mode(mode)`,
    `set_locks(ids)`, `set_new_lock(width_cm, thick_cm, taper)`, `current_tool()`; `points_keys.STATE` (`tool`, `mode`,
    `lock_ids`, `width_cm`, `thick_cm`, `taper`, plus `held`, `message`, `node`), `points_keys.HOOKS["tool"]` (a list
    of callables, or one) on every change. Paint: `grooming_paint_state.enter` calls `yield_to_paint` (the record says
    `paint`), its leave / end calls `paint_ended`; entering this tool calls `paint_exit` first.
  - Gestures: drag a handle on the view plane through it; the root handle on the ray's hit on the frozen IN_SCALP
    (`intersect`; a miss keeps it), other locks' roots `nearestPrim` onto it: 6e-6 cm off the skin at every event.
    R / E PRESSED arm the next drag (rotate / scale about each lock's root; held through the drag or tapped before
    it, the release is ignored, a second press disarms): Houdini's own R / E would take the viewport to its Edit /
    scale tool, so they are hotkeys of the state's menu (`HOTKEY_CONTEXT`), and the press is seen by the application
    filter. Rotate: the angle on the view plane through the root about the view direction; scale: x2 per 200 px
    right. Shift + drag redraws the lock nearest the press (from the root handle the root stays; from the skin the
    root moves there). minus / plus: one handle less / more on EACH lock (grouped by target count, one undo step).
    Several locks: the same handle of each (`points_keys.map_handle`: root to root, tip to tip, the rest by share).
  - Houdini sends a press and release without motion as ONE mouse event (`ui_event.reason()` Picked, the button
    down, no release after it): handled as a whole click; read as a press it left a gesture open and the next move
    closed it as a click elsewhere (t81 r11). A click on a handle keeps the selection; on hair (the spine nearest on
    screen within 30 px, points behind the camera or outside the view left out) it selects that lock, Shift adds,
    Ctrl toggles; on empty space it keeps the selection. A gesture whose button is no longer down when a key comes is
    closed (`_drop_stale`).
  - GUI tests of a state: map viewport pixels to the GL widget directly (x = widget x, y = height - widget y, read
    live), not by moves read back from the state: after a flipbook the state's events lag and the read-back
    calibration was garbage (r5); redraw the viewport after a flipbook before reading where a handle is (r4 / r7:
    presses 30 px off); find the GL widget once before any state (the HUD's widget sits at the viewport's centre);
    each step frames its own lock (run alone, a step used the default view: handles off screen, r15).
