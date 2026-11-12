# MONO Grooming (Houdini, `tools/fx/grooming/` + `apps/houdini/grooming_adapter.py`)

Notes for working on MONO Grooming, moved out of the suite's root `CLAUDE.md` (2026-11-13) so sessions on
the other tools do not load them. The contract is `docs/plans/grooming_v0_1.md`; read its scope before
proposing a feature. Claude Code loads this file when it works on files in `tools/fx/grooming/`; when
working only on `apps/houdini/grooming_adapter.py` or the `grooming-check` skill, read it first.

- Contract for v0.1: `docs/plans/grooming_v0_1.md` (scope, data model, geometry attributes, processing
  order, adapter API). One SOP HDA `mono::grooming::0.1` built from code by `tools/fx/grooming/build_hda.py`
  into `otls/` (the suite root is the package `hpath`).
- What the user set lives as JSON in the node's hidden `groom_data` parm (`model.GroomData`): a parm, so
  edits are undoable and saved with the hip. Measured lock shape lives on the geometry, never in the JSON.
  Settings resolve built-in → `defaults` → group → lock.
- A lock is spine + `lock_width` / `lock_thick` / `lock_twist` along `curveu`; the hair mesh is only an
  input. `lock_width` is the lock's width; Houdini's `width` stays the strand thickness.
- Growth regions are frozen in the node and change only on Update regions: editing one lock never changes
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
- Two outputs (labels in the DialogScript, `config.OUTPUT_LABELS`): 0 **Display**, what the viewport
  draws (hidden / isolated-out locks left out, packed, coloured, ghosts with Alpha, preview density,
  deformed with Shot deform on); 1 **Groom** (`GROOM`), the groom itself whatever the view: every lock
  not excluded, full density, only P + `config.GROOM_ATTRIBS` (width, lock_id, name, group, clump_id,
  id), at rest or deformed while Shot deform is on. Anything downstream (File Cache, SOP Import, a
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
  the node's); `lock_shown` turns it into `disp` (lighter while playing) and
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
  with its strands (`lock_capture`, per-lock `do_capture` in the key) **only while the deform runs**:
  capturing every full-hair lock whenever the anim was wired held ~800 B a point (Helen, anim wired:
  5.8 GB after a cook, 9.5 GB after an All-locks edit; now 2.1 / 2.7 GB, t49). The first Deform on
  regrows the groom once (~12 s, was 1.7 s); frames and the deformed hair are the same (max 0.5 mm off).
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
- Hair QC also measures roots against density, the width profile along each lock against its mesh,
  and folds (grooming-check, 2026-11-12). Helen: strand counts match density x area (worst 16 %), folds
  0.02 %, hair ~0.78 of the mesh's width along every lock, but `root_pull` gathers each lock's roots into
  its mesh piece's root cross-section (hair_base_01: region 6.7 x 7.7 cm, roots in 1.1 x 1.9 cm): the base
  is ~20-30x denser than set and the scalp between lock bases bare. OPEN, the user's call.
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
- Panel layout (2026-11-12 redesign): top bar (node, asset, Settings ⚙: Font size and X-ray, saved per user; Dock), then a view bar (Display,
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
  below follow ("all follow") or how many set their own ("2 set own", tooltip names them; narrow: "↓2"),
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
