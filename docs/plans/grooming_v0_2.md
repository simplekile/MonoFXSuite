# MONO Grooming v0.2 (plan; decided 2026-11-13; v0.2a core rebuilt 2026-11-15 on the user's final model: density layers, each with its own number and its own mask; panel and gates open)

v0.1 (released in MonoFX Suite v0.1.25, contract in `grooming_v0_1.md`) makes the whole groom
automatically from the hair mesh. v0.2 lets the artist change that result where it is wrong, on top of
it: the automatic groom stays the base layer and every v0.2 edit is a layer over it, never a second
system beside it (v0.1 plan, "Not in v0.1").

The v0.1 known issues (crown denser than v006, thin skin under floating mesh, a few strands outside
their lock) are answered here by edits the artist makes, not by more tuning of the automatic rules.

## Order: three parts, each released on its own

| Part | What the artist gets | Why this order |
|---|---|---|
| **v0.2a Density layers** | Density layers over the automatic groom (Substance Painter style): each has its own density number and its own painted mask, so an area can be made thinner, denser or bare | Fixes most known issues (crown, thin skin) with the least new machinery; the layer system is reused by b and c |
| **v0.2b Lock redraw** | Move a lock's control points, redraw its curve, draw a new lock where the mesh has none | The plan's reserved slot (after spine and measure); changes shape, not density |
| **v0.2c Brush** | Comb, lift, cut and length brushes on the hair in the viewport | Most work and the most risk (edits must survive recooks); comes last, on what a and b settle |

Each part runs through the gates in "How the work runs" below. A part is done when its "done when"
list holds; no tuning past it inside the part.

## How the work runs (manager, executors, checker; decided 2026-11-13)

Goal: agents test and check every step themselves; the user is asked only where a person must decide.

### Roles

| Role | Who | Does | Never |
|---|---|---|---|
| **Manager** | the lead session (004) | Owns this plan and the "done when" lists, writes briefs, starts sessions, reads every diff, runs the gate checks itself, merges, keeps the plan current, reports to the user | Writes feature code; passes on an executor's claim it has not checked |
| **Executor** | one session per task, own worktree and branch | Spike or build of one task; tests its own work up the ladder below; writes the evidence report | Changes the contract or scope on its own; pushes, opens PRs, merges |
| **Checker** | a fresh session per gate, started by the manager with the branch and the "done when" list only (not the executor's report) | Runs the acceptance script and the ladder again from a clean checkout, tries to break each "done when" item, answers pass / fail per item with evidence | Fixes code (it reports; the executor fixes) |

The executor never grades its own work for the gate: a "done when" item counts only when the checker
passed it and the manager saw the evidence.

### Models (the manager sets `model` and `effort` when it starts a session)

| Work | Model | Effort | Why |
|---|---|---|---|
| Manager (plan, briefs, diff review, gate decisions) | Fable 5.2 | high | The decisions every other session builds on |
| Spike; build of the hard core (viewport state, HDA network, root and density logic, storage and cache keys) | Fable 5.2 | high | Design under open questions; a wrong choice costs the whole part |
| Build of a task the spike already settled (panel from the picked mockup, adapter functions, unit tests, the acceptance script) | Opus 5.5 | high | Careful work with a clear target |
| Checker | Opus 5.5 | high | A different model from the hard-core executor, so it does not share its blind spots; strong enough to try to break each item |
| Mechanical runs (rebuild the HDA, run the acceptance script and QC again, flipbooks, changelog and release steps, moving notes) | Sonnet 5.5 | medium | Follows written steps; nothing to design |
| Read-only look-ups (find a function, list sessions, read a log) | Haiku 5.5, as a subagent | low | Cheap and fast; the result comes back in the same turn |

A session never gets a model above the manager's (the app ignores it). When a cheaper model fails a
task twice, the manager restarts the task one row up, not a third try. The checker of a task built on
Opus 5.5 runs on Fable 5.2 for the same reason as above: never the executor's own model.

### Gates of one part (a, b, c)

1. **Spike** (executor): answers the part's OPEN questions with measurements, writes the decisions into
   this plan. Manager checks the numbers; a decision that changes the contract or what the artist sees
   goes to the user.
2. **Design** (executor, panels only): `dcc-panel-design` mockups; the user picks one.
3. **Build** (executor, split into tasks that touch different files when they can run side by side):
   feature, unit tests, the part's acceptance script, notes in `tools/fx/grooming/CLAUDE.md`.
4. **Self-check** (executor): the whole ladder green, evidence report written. Not green = not handed over.
5. **Independent check** (checker): pass / fail per "done when" item. A fail goes back to the executor
   with the evidence; at most 2 rounds, then the manager decides (cut the item, change the approach,
   or ask the user).
6. **Merge** (manager): reads the diff, runs pytest and the acceptance script itself on the merged
   branch, opens the PR. Push, PR merge and release stay the user's yes.
7. **User look**: the flipbooks and a short GUI try of the feature; then the release.

The user is asked only for: a contract or scope change, the mockup choice, how the hair looks (taste),
push / merge / release, archiving sessions.

### Test ladder (every build task climbs all of it; each rung leaves a file)

| Rung | What | How | Evidence |
|---|---|---|---|
| 1 Unit | Logic, model, controller without Houdini | `python -m pytest -q` | pass count in the report |
| 2 Node | The feature on Helen in hython: results, errors, warnings on the node | the part's acceptance script | `accept.json` |
| 3 Regression | No edits = the v0.1 groom: strand count and QC numbers unchanged | `qc_metrics.py` against the numbers of t55 | `qc_report.json` |
| 4 Quality | Hair with the edits passes `grooming-check`, plus the part's own checks | `qc_metrics.py` | `qc_report.json` |
| 5 Speed | An edit costs at most 0.2 s per lock it recooks, plus 0.1 s (Helen, hython; decided 2026-11-13 after t57: skin is stacked, a stroke touches 4-9 locks); full cook within +10 % of v0.1 | timed in the acceptance script | `accept.json` |
| 6 Persistence | Edits survive undo / redo, save and reopen, Detect, Update regions, Publish (read back) | acceptance script | `accept.json` |
| 7 Interaction | The viewport tool and the panel really work: strokes, drags, undo per stroke | Houdini GUI on the secondary monitor, events sent by script (viewer state events, Qt test clicks), never by hand | flipbook frames before / after, panel grabs (`grab_offscreen.py`), `contrast_check.py` |
| 8 Look | Whole groom and the edited area | `qc_capture.py` flipbooks | `shots/*.png`, described in words in the report |

**Acceptance script**: one per part in the repo, `tests/houdini/grooming/accept_v02<part>.py`, run with
hython: `hython accept_v02a.py <suite> <scene> <out_dir>`. It turns the part's "done when" list into
checks (one id per item) and writes `accept.json`: `{item, pass, value, limit, evidence}` per check and
`passed`. The executor writes it during the build, the checker and the manager run the same file, so
"done" means the same thing for all three. The Helen scene stays in the sandbox (path by argument),
never in the repo. Hython's exit code is not reliable (segfault on exit): read the JSON.

**Evidence report** (executor, at hand-over): `tests/<tNN>/report.md` in the sandbox with the branch
and commit, each "done when" item with pass / fail and the file that shows it, each rung's result,
what was not tested and why, open questions. A claim without a file is not in the report.

### Rules between agents

- One task = one session = one worktree = one branch; two sessions never edit the same files at once.
  Tests write only under `sandbox/claude/grooming/tests/<tNN>/`, a new number per task.
- Houdini GUI: one at a time across all sessions. Take `sandbox/claude/grooming/tests/gui.lock`
  (a file with the session name and the PID) before starting it, delete it after; a lock whose PID is
  gone may be taken. Secondary monitor only; kill only your own PID.
- An executor stops and asks the manager when: the brief needs a contract change, the same fix failed
  twice, the work grows past the brief, or a rung cannot be automated (it says which, never skips it
  silently).
- The manager answers from this plan; what the plan does not decide goes to the user, and the answer is
  written into the plan in the same step.
- Session names `NNN · Tag · việc`; a checker is `NNNb · DCC · Kiểm ...` of the task it checks.

## Rules for every part

- An edit is stored in the node (JSON in `groom_data`, or a hidden geometry parm like `regions` for
  per-point data), saved with the hip, one undo step per stroke or drag, and dirties only what it touches.
- Edits are keyed by `lock_id` (and scalp UV for painted data), so they survive Detect, Update regions
  and a new hair mesh version; an orphaned lock keeps its edits in `orphans`.
- Partial cook stays: an edit is part of the cache key of the locks it touches only (v0.1 "Partial
  cook"), so a stroke on one area recooks the locks under it, not the groom. Target on Helen: at
  most 0.2 s per lock recooked, plus 0.1 s (decided 2026-11-13 after t57; "under 1 s for one lock" could
  not be told apart from a stroke over stacked locks, which touches 4-9 of them).
- Output 1 Groom and Publish include every edit; the publish JSON records them so a later version can
  read them back. `groom_data` `schema` bumps with a migration in `model.migrate()`; a v0.1 scene opens
  unchanged (no edits = v0.1 result, checked by the v0.1 QC numbers staying the same).
- No modal dialogs; results and warnings on the panel's message line.

## v0.2a Density layers

**What (the user's final model, 2026-11-15: "the automatic density is a density layer of its own; the user makes
a new density layer with another density number and a mask, to override the density"). It replaces the one 0..1
mask x the lock's own Density of 2026-11-14 (t62), in which a layer could never be denser than the automatic groom
and black meant "no hair"; that one had replaced "= D strands / cm2" layers (2026-11-13) and the first builds'
factor layers.**

1. **Density layer**: its own number **D** (strands / cm2, absolute), an opacity, an eye, an owner row in the lock
   tree (All locks, a group, a lock) and a mask.
2. **The mask of a density layer**: a stack of paint and fill layers, values 0..1, blended bottom to top as the
   layer stack of a mask in Substance Painter, starting from black. It belongs to that one density layer; there is
   no global mask. A new density layer's mask is black, so adding a layer changes nothing until it is painted.
   - **Paint layer**: the brush paints a value AND coverage; skin of the layer never painted is transparent. Erase
     removes the layer's own paint (coverage back to 0); it does not paint black.
   - **Fill layer**: one value over all the skin, full coverage.
   - Each mask layer has a blend mode (Normal, the default; Multiply, Add, Subtract, Min, Max) and an opacity:
     m = below + (blend(below, value) - below) x coverage x opacity, clamped to 0..1 per layer. Multiply as the
     top layer bounds the region.
3. **Result at a skin point**, a density layer over what lies below it:

       density = below + (D - below) x mask x opacity

   Density layers stack as Normal only: there is no blend mode between density layers.
4. **Order**: layers owned by All locks first, then the lock's group, then the lock (the more specific wins);
   within one owner row the upper layer wins.
5. **The bottom of the stack is the automatic groom**, stored and shown as the base density layer ("Automatic",
   `kind` "base", always the first row of `groom_data.masks`): D = each lock's own Density setting, mask full; it
   cannot be deleted, moved or switched off. With no other layer the groom is v0.1's, byte for byte.
6. **Black in a mask = "this layer does not apply here"**: the density below shows. It is NOT "no hair". No hair =
   a layer with D = 0 painted white. A layer may be denser than the automatic groom: D = 300 over locks at 150
   gives 300 (measured 299-303 / cm2 on four kinds of skin, t63).
7. **Folders are dropped from v0.2a.** A folder of density layers with a shared mask would need a second mask
   level in the stack, the tree and the brush's target: not free. A group or lock row of the tree already gathers
   its density layers, and a region shared by several layers is painted once and reused as a Multiply top layer.
   Older dev files with folders open: a folder's opacity and eye go into its layers.
8. Quick picks are densities: 0 / 75 / 150 / 300 (`config.MASK_DENSITY_PICKS`). The brush itself paints a grey into
   the mask (1 white by default; `config.MASK_VALUE_PICKS` 0 / 0.5 / 1).

**What "= D" means where locks share the skin (decided by measuring, t63 `o2_*`).** A layer's D is what the locks
it is owned for give on that skin TOGETHER:
- owned by **All locks**: every lock on that skin together gives D (each D / the number of owners of that prim);
  measured on eight kinds of skin, the most stacked included (7 locks): %(all_stacked)s of D.
- owned by **a group**: the group's locks on that skin together give D; locks of other groups there keep what the
  layers below give them.
- owned by **one lock**: that lock alone gives D on every prim it owns, whole (not divided by the other owners),
  and the other locks there keep what they had. Measured on the most stacked skin (a layer of 120, the four
  largest owners in turn): %(lock_alone)s; the other locks' roots there unchanged, only that lock recooked. So a
  lock layer of 120 on skin 7 locks share makes that skin 120 denser than the other six leave it: the artist
  thins a stacked area with an All locks layer, and one lock with its own layer.

**The rule in the tool's numbers.** The automatic groom at the bottom is not a number but the automatic ROOTS
(gathered at lock starts and whorls, thin under floating mesh), so the stack carries two numbers per skin point
(`logic.density_over`, `density_compose`): **keep**, the share of the automatic roots still there (the product of
1 - mask x opacity over the layers that reach the lock), and **add**, the density the layers themselves ask in
strands / cm2 (add x (1 - e) + D x e, layer by layer), and

    density of a lock = its automatic density x keep + add              (`logic.layer_density`)

which is "below + (D - below) x e" written apart. Fully covered (keep 0) no automatic root is left and the lock
grows the layer's D; partial coverage (a grey mask, a soft brush edge, an opacity under 1) blends the two.

**Where in the order.** settings applied -> region split -> **layers** -> cache key per lock -> hairgen.
The key of a lock includes a digest of the layers' cover (keep, add) on its region, so a stroke recooks
only the locks under it.

**Storage.** Per scalp point two float attributes a paint layer, `mask_<id>_v` (its value) and `mask_<id>_a`
(its coverage), in a hidden geometry parm `mask_layers` (as `regions`); a fill layer and a density layer store
nothing there. The layer list (id, name, on, kind, density, blend mode, value, opacity, owner, parent, order) is in
`groom_data`. A new scalp topology transfers the layers by UV, with a warning.

**Spike (run 2026-11-13, t57, `sandbox/.../tests/t57_mask_spike/`; Helen, fine scalp 24,320 prims /
24,501 points, GUI on the second monitor, flipbook shots in `shots/`).**

1. **Painting inside the locked HDA: our own Python viewer state.** Decided.
   - Ours (`t57_state.py`): it touches no inner node. It reads `SCALP_FINE` (readable on a locked HDA),
     keeps the layer as numpy arrays while the button is down, and on release writes the two parms of the
     HDA node in one undo group. On the locked node: 40-45 mouse events a stroke, every one drawn (41-52
     redraws a second, the test's own input rate; 1.4-1.9 ms of our code a dab: ray hit, 24.5 k distances,
     recolour, drawable), entering the state 0.05 s. Undo removes exactly the last stroke (the parm equals
     the stroke before, bit for bit; redo puts it back), 0.04 s and no lock recooked. Saved with the hip
     and equal after reopen (+1.0 MB a layer: P, value, coverage on 24.5 k points).
   - Houdini's Attribute Paint on an editable node in a locked HDA works too (small test HDA on the same
     scalp: 32-34 cooks a second, undo per stroke, the asset stays locked, strokes saved with the hip).
     It loses on what it forces: its state needs the viewer inside the HDA, and the node cooks on every
     dab with the groom below it. Feeding the groom's mask, the same 45-move drag took 7.6 s instead of
     1.1 s: 11 cooks, 1.4 a second, each one regrowing the locks under the brush. It also paints one
     attribute with its own UI, so layers, blend modes and scope would sit beside it, not in it.
   - Not covered: a hand on a mouse or pen. The strokes were Qt mouse events sent to the viewport widget
     (the real cursor belongs to the user while tests run), so the feel, pressure and hotkeys need the
     user's own try in the build.
2. **Showing the mask while painting: a drawable of the scalp coloured by the final factor** (grey 1,
   blue towards 0, red towards 2+), the hair in Hair preview. `hou.SimpleDrawable` given a fresh copy of
   the geometry on every dab (1.9 ms): handed the same `hou.Geometry` again it keeps the old colours, and
   `hou.GeometryDrawable` (Face) drew flat grey without `Cd`. Shots: `q2_drawable_simple_copy` (scalp
   alone), `q2_4_close_hair_preview` (the painted patch reads through the preview hair),
   `q2_3_close_hair_full_xray` (full hair: only with the drawable's X-ray on, as a wash),
   `q2_5_head_hair_preview` (whole head: the hair hides the scalp even in preview, so painting is done
   close, or with the hair out of the way: Guides, isolate, or the ghost look).
3. **Roots read the final density through hairgen's own scatter** (its `density` point attribute x the
   factor, the forced count from the masked area). No scatter of our own is needed. hython, one lock
   whose roots sit on the skin (hair_back_06) and one cap with floating mesh (hair_base_01), half of each
   region painted:
   | | hair_back_06 | hair_base_01 |
   |---|---|---|
   | roots in the half painted 0 (before -> after) | 216 -> 0 | 1,130 -> 0 |
   | roots in the half painted 2 | 248 -> 499 (2.01x) | 1,046 -> 2,004 (1.92x) |
   | the other half meanwhile | 248 -> 249, 216 -> 213 | 1,046 -> 1,000, 1,130 -> 1,282 |
   | spacing / clumped inside the half painted 2 | 1.04 / 0 % | 0.86 / 0 % (0.85 before) |
   A soft dab (radius 1.5 cm, value 0, falloff over the whole radius): roots per ring / before follow the
   factor's mean on the ring (0.12 vs 0.09, 0.34 vs 0.37, 0.79 vs 0.75, 0.88 vs 0.97, 1.04 vs 1.0), so
   hairgen's relax does not flatten a brush edge.
   Found on the way: the lock's start roots (its roots under floating mesh, and the start extras) are laid
   out on a disc round its root whatever the mask: hair_base_01 kept 115 bunched roots in the half
   painted 0. With the disc's places kept by the chance of the factor there: 0. Whorl roots need the same.
   Cook after a stroke (display, hair full, anim wired, Shot deform off; GUI): 0.68-0.71 s for a small
   stroke (4 locks under it), 1.08-1.13 s for a 3.4 x 2 cm one (7 locks: this skin is stacked); hython
   0.38 s (2 locks) to 1.3 s (7 locks), about 0.15-0.2 s a lock. The mask itself costs 2 ms (blend and
   transfer) plus the 0.04 s every edit pays (keys, merge). "One lock under 1 s" holds; a stroke over
   stacked locks pays for each of them.

**Build (core rebuilt 2026-11-15, t63, on round 3's network; the panel is a separate task). The spike above and
the numbered decisions further down are the first builds' history: where they speak of factors, of a 0..1 mask x
the lock's density, of folders or of blend modes between layers they no longer hold.**
- Data: `groom_data.masks` (`model.MaskLayer`, bottom first: the base, then each density layer followed by its
  mask layers; fields id, name, on, `kind` "base" / "density" / "paint" / "fill", `density` (D), opacity, `scope`
  with its `group` or `locks` (a density layer's owner), `mode` (`config.MASK_MODES`), `value` (a fill layer's,
  0..1) and `parent` (a mask layer's density layer)), `mask_id_high` (a layer id is never reused). `schema` 6.
  Schemas 2 to 5 were never released; on reading (`model.migrate`, `_density_layers`) their layers come over:
  - **schema 4** ("= D strands / cm2" under a painted mask) and a schema 3 fill layer in strands / cm2 (Replace):
    a density layer of that D, opacity and owner whose mask is one paint layer holding the stored mask (the paint
    layer keeps the old id, so the paint on the node is found). The same result as before.
  - **schema 5** (one 0..1 mask x the lock's own Density) and the 0..1 layers of **schema 2 / 3** (paint layers,
    factor fills 0..1): the layers of one owner become the mask stack of ONE density layer of that owner, whose D
    is the owner's Density setting when the file is read. White gives what it gave; black gave "no hair" and now
    shows the density below; a soft edge mixes a little differently; a Multiply layer with nothing under it in
    its mask now does nothing (it thinned the automatic groom).
  - a **folder** (schemas 3 to 5) is gone: its opacity is multiplied into its layers', its eye switches them off.
  - dropped, by name: a factor over 1, and a strands / cm2 layer in another blend mode than Replace (schema 3).
  `model.dropped_masks` / `converted_masks` name them, OnLoaded says so on the status bar and `mask_dropped(node)`
  gives the panel the sentence; never a dialog, never a traceback. The JSON on the node is rewritten only by the
  next edit. A v0.1 scene opens with the base layer alone.
  Hidden geometry parm `mask_layers`: the fine scalp's points with `P`, `uv`, `mask_<id>_v`, `mask_<id>_a`; a
  layer never painted has no attribute. A stroke writes only `mask_layers` (the layer list did not change, and
  writing `groom_data` would recook the spines); a layer edit writes only `groom_data`; one undo group each.
  Neither is in the shared part of the cache key (`_KEY_SKIP_PARMS`).
- Network: `mask_read` (Python SOP in line after `region_prims`, `grooming_masks.cook_mask_read`) composes the
  density layers per scope set (`logic.mask_scope_sets`: the ordered layers that reach a lock) in numpy into the
  point attribute `mask_keep_<k>` and the VERTEX attribute `mask_add_<k>` (strands / cm2 one lock of the set is
  asked on that prim: each layer's D divided by `layer_divisor`, which is per prim, hence a vertex attribute) on
  `SCALP_REGIONS`, and writes the details `mask_sets`, `mask_set_of`, `mask_hash_of`, `mask_add_of` (by lock id)
  and the prim `mask_dens` (PREVIEW's expected strands). With no density layer on it adds nothing, so the geometry
  and the groom are v0.1's. `lock_keys` gives each lock its `mask_set` and `mask_add_n` and puts the lock's digest
  in its key.
- Inside the loop the automatic groom is v0.1's own nodes, unchanged (`region_cut` ... `root_pick`,
  `root_place`): no layer reaches them. A lock a layer covers (`mask_set` >= 0, read by switches; the others
  never cook the new nodes) gets two more steps:
  1. `mask_thin`: each automatic root stays where keep says so at the place it ENDS UP (`root_at`: a root the
     tool moved to the lock's start or a whorl is judged where it landed). Each root has a threshold of its
     own that never changes with the mask (`thin_order`, kept with the automatic roots), so a small change of
     the mask removes or returns a few roots and moves no other. See "Even thinning".
  2. `hairgen_layers`: a second scatter on the lock's region by the layers' density there (`mask_skin`:
     `mask_add` on unshared points, so a prim's corners carry its own value), as many roots as `mask_read`
     counted (`mask_add_n` = the sum of add x area over its prims; no cap at the lock's own Density). They join
     the automatic roots before `root_place` (`roots_with_layers`), are never relocated and never thinned.
  The `groom_` loop is the same code (`_copy_loop`).
- Paint: `apps/houdini/grooming_paint_state.py`, state `mono_grooming_mask_paint`, registered on first use
  (no `viewer_states/` folder to install), entered by `paint_enter`. A `SimpleDrawable` of the scalp recoloured
  from a copy a dab, a ring on the skin, the write on release, then the panel's `HOOKS["stroke"]` (the cook
  inside `_busy`) or the node's own cook. Ctrl paints the other way round, Esc leaves Paint.
- While Paint is on the panel shows Hair preview (or Guides) and the scalp's X-ray toggle (`set_brush(xray=)`).
- Publish: `vNNN/_grooming/mask_layers.bgeo` next to `grooming_data.json` (staged like the other files),
  named in `publish.json` (`masks`: file, layer ids, points, painted points a layer); `masks_from_publish` /
  `import_masks` read them back. The published USD is the groom with its layers.

**Undo cache (round 3, the user's decision 2026-11-13).** The per-lock hair cache keeps earlier states by
memory, not by a count (it kept 2, so the second undo of a row of strokes regrew its locks): parm "Undo
cache, GB" on the node (`undo_cache_gb`, default 2, saved with the hip, in no lock's key), the states used
longest ago dropped when full, what the node shows now never dropped. An undo past what the cache holds
gives the same hair, grown again. `undo_cache_usage(node)` reads what is in use (bytes, live, undo states,
limit, dropped) for the panel. Output 1's Point Deform captures are held apart from that count, one a lock,
and its locks are no longer captured inside the per-lock loop (800 B a point: one state of Helen's groom is
3.3 GB): the rest groom and publish share the display's strands, and the capture is made per lock from
cached strands only when the deformed output is read. The deformed groom is point for point v0.1's.
Helen, 2 GB: ~58 strokes on ordinary skin (26 MB each, 5 locks), ~28 on the whorl (55 MB, 26-35 locks).

**Speed, and one change to the automatic groom that needs a decision (round 3).** A stroke missed the
limit (0.2 s a lock + 0.1 s) on three places in the second check. Most of a small lock's cook was a fixed
75 ms: the strand fit searched every lock's mesh for its own. Each lock now looks its strands up on its own
mesh piece ("Fit lookup per lock" on the node, on by default), its automatic roots are kept between
strokes, and two per-point passes were folded together: strokes on Helen 0.29-0.85 s for 3-6 locks (limits
0.7 / 1.3), the whorl 1.4-2.3 s for 24-35 locks, a full cook 7.6 s instead of 10.9.
**The per-lock lookup is not v0.1's hair bit for bit**: the same roots and strand counts, but 45 % of the
strand points move (half under 0.008 mm, 1 % over 1 mm, at most 4 mm), and 8 of the 27 grooming-check numbers
of the no-layer groom move by 5e-5 to 1 % (all 27 pass). With the toggle off the groom is v0.1's within its
own run-to-run noise and the speed limit holds with 3-9 % to spare. OPEN for the manager / user: which
default ships (the executor built it on, for the margin; "No layers = the v0.1 groom" below is graded by
root positions and strand counts, and by the QC numbers with the toggle off).

**Paint belongs to the painted node (round 3).** Esc ends Paint from anywhere in Houdini's window, also while
the mouse is held: what was painted so far is kept as one stroke, the rest of the drag paints nothing.
Selecting another node ends Paint (the status bar says so) and a drag in the viewport never paints the
grooming node while another node is selected; selecting the grooming node again keeps Paint. Entering Paint
makes the node the selection.

**Why two sets of roots, and not one scatter by a density map (round 3).** The first builds multiplied
hairgen's density attribute by a factor and thinned the roots the tool relocates. Two checkers measured what
that gave: x2 was x1.08 on the whorl and x5.3 under floating mesh, "= D" ran 11-19 % short where relocated
roots dominate, a grey mask on the whorl reached D faster than its grey, and a leftover mask of 0.03 moved
every root of two locks by up to 20 mm (one scatter with a forced count re-places everything). Keeping the
automatic roots as they are and thinning them where they end up makes unpainted (or erased) skin the automatic
groom exactly, makes partial coverage linear everywhere, and leaves every other root in place when the mask
changes a little. The same two sets carry the density layers: keep thins the automatic roots, the layers' own
density (add, strands / cm2) is the second scatter.

**Even thinning (round 3; it does not depend on the layer model).** A keep between 0 and 1 (a grey mask, a soft
brush edge, an opacity under 1) must leave an even share of the automatic roots, and the share must hold on every
part of the skin and for every lock: thinned at random, the start grids were left in bunches (rounds 1 and 2:
clumped share 0.014 -> 0.616 at x 0.5 on the top of the head). Each automatic root gets a threshold `thin_u`
and stays while thin_u < keep (`thin_order`, cached with the automatic roots: a stroke pays nothing for it):
- Start roots and scattered roots are each ordered by pairing: every root is paired with the nearest root not
  yet paired, one of the pair goes to the first half (the one farther from the roots already there), the
  other to the second, and each half is paired again, 10 times; the halves are the binary digits of thin_u. Of
  two neighbours one stays at a keep of 0.5, so the share is kept locally whatever the density and however
  near an edge. To stay cheap the roots are sorted along a Z-order curve and a partner is looked for among the
  next 10 (among all, once a half holds 64 or fewer).
- A small start grid (400 roots or fewer: a disc of a millimetre or two, several times denser than the rest of
  the lock) takes a farthest-point order instead: what is left of it must stand as evenly as it can.
- Whorl roots: their sunflower number with its bits reversed.
- Partial coverage puts the layers' own roots among automatic roots that stayed; a layer root nearer than
  0.45 of the root spacing asked there to an automatic one is moved off it, on the skin (`mask_apart`).
Tried and dropped: the root's number in hairgen's scatter (0.35 to 1.85 of the share from skin to skin); a
dither of the root's position (stripes; two places just over the limit); the same on whole cells (+0.06 to
+0.10 at x 0.25); a farthest-point order of everything (the rim of a set comes first: a patch inside a large
start grid kept 0.8 of the share, stacked skin 1.17, floating mesh 0.56); pairing every root against every
other (+13 s on Helen's cold cook).
Cost: Helen's cold cook 6.8 -> ~10 s (v0.1: 12.7 s); nothing on a stroke.
Traced in t63 (the two partial-coverage cases round 3 left open, and its one lock over a density limit):
- `hair_base_21` on ordinary skin (+0.122 in t62; +0.143 here at first): every root that read as bunched was a
  layer root beside a kept automatic root. `mask_apart` sized its distance from the lock's set Density x keep;
  that skin lies under floating mesh, where the automatic roots start the lock and 26 / cm2 of them are left
  where 150 are set, so layer roots were held 0.037 cm off them while roots asked there stand 0.14 cm apart.
  `mask_apart` now counts the automatic roots really kept round the place (the 8 nearest over the disc they
  span): rise 0.0. `hair_base_12` on the top of the head (+0.087 in t62): at most 0.008 now. All 31 grey-mask
  and opacity cases of t63 are inside +0.05; the report lists any case of the other checks that is not.
- One lock over its density limit on a sliver of skin (t62: `hair_bang_20`, 3 roots where 0.8 are asked on
  0.02 cm2; t63 also `hair_base_21` on the top of the head, 47 where 34 are asked on ONE prim of 0.22 cm2):
  hairgen's scatter gives a forced count to single prims almost as a coin toss per root (400 equal quads asked
  34 each: variance 26-31), and its relax pushes roots against the border of each prim island `mask_split`
  makes, where the count gives them to either prim (of the 47, 38 lie inside the prim and 12 on its edge).
  Over a lock's whole skin in a patch the counts are tight: 614 lock cases, (roots - asked) / sqrt(asked) has
  a spread of 0.43 where a coin toss would give 1. Not fixed: it needs a scatter with a fixed count per prim.

**Adapter API added in v0.2a** (`apps/houdini/grooming_masks.py`, re-exported by `grooming_adapter`; each
function that changes something is one undo step named "MONO Grooming: ..."; the layer list itself is
`read_data(node).masks`, with `GroomData.density_layers()` and `.mask_layers(density_id)`).

| Function | Returns / does |
|---|---|
| `mask_add(node, name="", mode="normal", opacity=1.0, scope="all", group="", locks=(), kind=None, value=1.0, parent=None, density=150.0) -> int` | New layer, its id. `kind` "density" (the default without `parent`): a density layer on top, `density` D, `opacity`, owner (`scope` / `group` / `locks`); its mask is black until painted. "paint" (the default with `parent`) / "fill": a layer on top of density layer `parent`'s mask, `mode`, `opacity`, a fill layer's `value` 0..1 |
| `mask_remove(node, layer_id) -> bool` | Delete the layer and what is painted on it; a density layer goes with its mask layers. The automatic layer: ValueError |
| `mask_move(node, layer_id, index, parent="keep")` | Put the layer at place `index` among its like (0 = bottom): a density layer among the density layers, a mask layer in its mask or (`parent`) into another density layer's. The automatic layer: ValueError |
| `mask_set(node, layer_id, name=, on=, mode=, opacity=, scope=, group=, locks=, value=, density=) -> bool` | Change the layer's row (`density`, owner: a density layer; `mode`, `value`: a mask layer); False (and no undo step) when nothing changed. The automatic layer: ValueError |
| `mask_fill(node, layer_id, value=1.0)` / `mask_clear(node, layer_id)` / `mask_invert(node, layer_id)` | A paint layer painted `value` everywhere / nothing painted (transparent) / its values inverted where painted |
| `mask_stroke(node, layer_id, points, radius_cm, value=1.0, soft, erase=False, normals=None) -> int` | One stroke through points on the skin on a paint layer, as the brush paints it: `value` (1 white, 0 black) with coverage, or `erase` (the layer's paint taken away) |
| `mask_values(node, layer_id) -> (a, b)` | Arrays per fine-scalp point. A mask layer: (value, coverage). A density layer: (its mask, its mask x its opacity) |
| `mask_cover(node, lock_id=None) -> (keep, add)` | The stack's result per fine-scalp point for one lock (the layers that reach it, in the order they apply), or of the All locks layers: density = automatic x keep + add, add in strands / cm2 with each D as it is set |
| `mask_dropped(node) -> str` | The sentence for the message line when the scene came from an older test build: layers dropped, layers now read as density layers ("" when none) |
| `paint_enter(node, layer_id) -> bool` / `paint_exit(node=None)` / `paint_layer(node) -> int \| None` | Paint on a paint layer (the viewport's tool is the brush; False without a viewport; a fill, density or automatic layer: ValueError) / off / the layer being painted |
| `set_brush(radius_cm=, value=, soft=, erase=, xray=, view=) -> dict` / `brush() -> dict` | Brush of the session (not saved, no undo): radius cm, `value` painted into the mask (0..1), soft share of the radius, erase, scalp X-ray, `view` (density / layer / roots) |
| `undo_cache_usage(node) -> dict` | What the node's hair cache holds against "Undo cache, GB": `bytes`, `live_bytes`, `undo_bytes`, `undo_states`, `limit_bytes`, `dropped`, `gb`, `limit_gb`, `capture_bytes` (the adapter's, not a mask function) |
| `mask_problem(node) -> str` / `mask_rebake(node) -> bool` | "moved over by UV" while the layers sit on another scalp / store them on the current one |
| `import_masks(node, tool_dir) -> int` / `masks_from_publish(tool_dir)` | Layers of a publish's `_grooming/` folder into the node / read only |
| `grooming_masks.HOOKS["stroke"](node)`, `HOOKS["exit"]()` | Set by the panel: after a stroke is stored (it cooks in its loading line); Paint ended without the panel |

**Decided in the build (the "Not sure yet" list of the spike; numbers: Helen, hython, t58 `accept.json`).**
1. Skin under floating mesh: the plan's proposal, built. A root there starts the lock with the chance
   `far_w / max(mask, 1)` (`logic.far_chance`): painted down, the same share of fewer roots moves; painted
   above 1, the automatic share still moves and what the mask adds stays. Skin with `far_w` 1 painted 2 went
   from 0 to 1.02 x the set density (132 roots where 129 are asked), evenly. The lock grew by more than the
   patch holds when its strand count is floored by its cross-section (hair_base_20: +304 strands, 132 on the
   patch): the surplus starts the lock, +2 % of its strands. No contract change.
2. Scope: one blended factor per distinct set of layers (`logic.mask_scope_sets`), each lock reads its own
   (`mask_set`). A groom with only "all locks" layers has one set. Two locks sharing skin, the layer on one:
   only that lock is recooked and loses its roots there, the other keeps its count. No contract change.
3. The digest: `mask_read` hashes each lock's own factor values (blake2b of the float32 values on its region's
   points), "" when all are exactly 1, so an empty layer or paint elsewhere regrows nothing. The same paint on
   another part of a lock's own skin gives another key.
4. The brush (`grooming_masks.ScalpBrush`) reaches the points inside its radius that face the way the skin
   under the cursor does (under 75 deg, `config.BRUSH_FACING_DEG`) and are joined to it through such points
   (neighbours = points sharing a prim). On Helen: 6 points facing away within 0.8 cm of a dab, none reached.
5. Whorl roots and start roots are kept by the chance of the mask where they land (painted 0: none; the
   layout does not move, so nothing piles up beside the paint): the crown painted 0 went from 35,790 roots to
   0. They are only ever thinned: painting a whorl or a start disc above 1 adds hair through hairgen's scatter
   there, not through the relocated roots. UV transfer: a scalp with other points (tested: Region subdivisions
   2 -> 1) takes each point's value from the stored point nearest in uv (in space without uv), `mask_problem`
   says so, the next write (or `mask_rebake`) stores it. A hand-held brush is still the user's own try.
6. Fixed as its own commit (559c1da): captured strands have a cache slot of their own (`cache_mode`).

Found on the way: Helen's scalp has a band of sliver polygons by the ears (12,418 of the fine scalp's 24,320
prims on 1.7 cm2). A 1 cm dab there holds ~7,000 points (2.9 ms a mouse move instead of ~1.5), and the first
prototype of the GUI test painted it by mistake. The brush works on it; nothing to fix in v0.2a.

**The layer model: density layers with a mask each (the user, final, 2026-11-15).**
History: the first build painted a factor per point (the artist had to think "paint 0.5 of what?"); the second
added fill layers with six blend modes on factors up to 8, of which only "= D" gave what it said (two checks, t60
and t61); the third cut it to one kind of layer, "= D strands / cm2"; the fourth (t62) made the thing blended ONE
mask in 0..1 x the lock's own Density, where no layer could be denser than the automatic groom and black removed
the hair. The final model gives every layer its own number and keeps the 0..1 mask for where it applies.
- **Base**: the automatic density, the bottom row "Automatic", locked (not paintable, not movable, no eye).
- **Density layer**: D, opacity, eye, owner. Quick picks 0 / 75 / 150 / 300.
- **Its mask layers**: paint (value and coverage per scalp point; the eraser takes paint away; fill / clear /
  invert) and fill (one value; changing it is a panel edit, the brush refuses it), each with a blend mode, an
  opacity and an eye.
- **Owner** (`scope`: all locks / a group / a lock) is the density layer's: it is the row of the lock tree the
  layer sits under. A layer owned by a lock follows the lock: when the lock goes missing it keeps its layers
  (and their masks), and giving the missing lock's settings to the lock that comes back
  (`controller.reassign_orphan`) moves the layers' ownership too.
- **Views** (`set_brush(view=)`): `density` the result, roots / cm2 counted from the cooked groom (so relocated
  roots are in it), moved while a stroke is down by what the layers ask now against what they asked when
  counted, and the density asked until the groom has been counted; `layer` (the painted mask layer alone, its
  value as a grey where painted); `roots` (a dot a root on a plain scalp). Choosing density or roots grows the
  locks the cache does not hold in full (Guides display: the whole groom once, ~12 s).
- Also from the user's try: Paint records no undo step of its own, and says so on the status bar when the layer
  being painted is undone; a stroke in Guides display grows no hair; the painted colour is the final density map.
- Still open: the result is not shown as hair while the button is down; a pen's pressure, radius by drag, mirror.

**Panel (for the panel task; not built here).** The lock tree has three levels, as Substance Painter's layer
stack with masks: **lock row (All locks / a group / a lock) > its density layers > each layer's mask layers**,
every row with an eye. The base "Automatic" row sits at the bottom of All locks, locked. The selected mask row is
what the brush paints into (`paint_enter(node, that id)`); selecting a density layer row paints nothing.
Properties shows only the selected row's parms: a density layer's D (quick picks 0 / 75 / 150 / 300), opacity
and owner; a mask layer's blend mode, opacity and, for a fill layer, its value; with a paint layer selected, the
brush (grey 0 / 0.5 / 1, eraser, radius, softness). Over the viewport the view choice (result / layer / roots)
with the density ramp's legend. "Undo cache, GB" (node parm `undo_cache_gb`, default 2) with the readout of
`undo_cache_usage(node)` belongs in the panel's settings. Mockups first (dcc-panel-design); the E2 mockup of t59
predates this model.

**Done when.**
- A layer of D painted white gives D: on the eight kinds of skin (whorl, top of the head, a lock start, stacked
  skin, skin under floating mesh, fringe, ordinary, the sliver band by the ear) D = 0 / 40 / 120 / 300 gives roots
  = D x skin within max(15 %, 2 / sqrt(N)), for all locks together and for each lock on its own skin, also where D
  is above the locks' own Density; 0 removes every root. A mask of 0.5 / 0.25, or an opacity, gives
  below + (D - below) x mask x opacity.
- Owner order: an All locks layer, a group layer and a lock layer over the same skin; the lock's wins on its skin,
  whatever their order in the list; inside one owner the upper layer wins. A layer owned by one lock gives D for
  that lock alone.
- Black over a white area returns the density below within the same limit (the automatic groom root for root
  when nothing lies below); every layer black, off, at opacity 0 or deleted = the v0.1 groom byte for byte.
- The mask stack: each blend mode gives what the formula says, in the mask's numbers and in roots; Multiply 0 /
  0.5 / 1 as the top layer; fill layers; erase; a soft edge; a tiny mask moves no root.
- Evenness everywhere: each lock's clumped share on its own skin in a painted patch is not above its no-layer
  value there + 0.05.
- On Helen: the crown painted down to v006's density (~5,100 / cm2) and the thin skin under floating mesh painted
  up, both in the GUI by scripted strokes, with the QC numbers before and after in the report (the user's own
  try with a mouse or pen is the User look gate); grooming-check is two-sided on a painted scene.
- A stroke recooks only the locks under it, at most 0.2 s per lock plus 0.1 s; undo removes exactly that stroke,
  in under 0.1 s and with no lock recooked, also with an anim wired and output 1 read, and for a whole chain of
  strokes (30 in a row, then 30 undos and 30 redos) while the undo cache ("Undo cache, GB") holds them.
- No layers = the v0.1 groom: strand count and QC numbers as t55.
- Layers survive Detect, Update regions, save / reopen and Publish (read back from the publish JSON); a missing
  lock keeps its layers; files of schema 3, 4 and 5 open.

## v0.2b Lock redraw and control points

**What.** Per lock: show its spine as a curve with a few control points; drag them (and rotate /
scale the lock about its root) in the viewport; redraw the whole curve; reset to the measured spine.
Draw a new lock where the hair mesh has none: a curve from the scalp, width and thickness as settings,
its region from the root and its width. The strands follow the edited spine; the lock's mesh surface
is carried along by the same bend (the offsets `fit_to_lock` reads are relative to the spine), so the
cross-section shape stays.

**Where in the order.** source hair mesh -> spine and measure -> Root to skin -> **spine edits** ->
settings applied (the slot v0.1 reserved). The root stays on the skin: the first control point slides on
the scalp, never off it.

**Storage.** In `groom_data` per lock: control points relative to the root frame (so a hair mesh
version that moves the lock a little keeps the edit), or a drawn curve; `edited` shows in the panel and
the tree (status colour), with Reset.

**Spike (OPEN).**
1. Handles: our Python viewer state on the spines versus Houdini's Edit / Curve state on an editable
   node; one drag = one undo step; several locks at once.
2. Shots: an edited lock is deformed by its animated mesh piece (Point Deform at rest, v0.1); check the
   hair moved off its mesh still follows well; a drawn lock (no mesh) follows the nearest piece or the
   scalp. Measure on sh020 / sh025 after session 019 has checked v0.1's deform.
3. How many control points per lock (fixed 5? by length?).

**Done when.** On Helen: a fringe lock moved, one rotated about its root, one redrawn and one new lock
drawn on bare skin, all in the GUI; QC passes; the edits survive Detect, save / reopen, publish; the
edited locks deform in a shot.

## v0.2c Brush

**What.** Brushes in the viewport on the hair: comb (direction), lift / flatten (angle from the skin),
cut / extend (length), clump more / less, smooth. Strokes act on the groom as a layer, with a layer
stack like v0.2a (opacity, enable, per lock or group scope).

**The hard part.** Strands are regenerated on every recook (density, region, mask, spine edits change
them), so a brush cannot store per-strand deltas. Proposal: brushes paint fields, not strands: a comb
direction, a lift angle, a length factor, stored per scalp point (like the masks) and applied to every
strand growing there, so they survive any recook. Houdini's Guide Groom stores deltas per guide id and
loses them when guides change, so it is not the model to follow.

**Spike (OPEN).** Field brushes on Helen: comb and length on one lock, then change its density and
redraw its spine; the brushed look must stay. If fields cannot give the look, the user decides between
guide-level edits (lost on some changes, with a warning) and stopping at a and b.

**Done when.** Decided after the spike; written here before the build starts.

## Not in v0.2 (later, when production needs it)

Several characters in one shot, batch over shots, shot mode reading a publish; colour layers and
melanin; Karma live preview; custom team effects; Unreal export; sim and body collision. The cut
lines decided for these in `grooming_v0_1.md` (cache paths per character and instance) stay.

## Before v0.2a starts

Session 019 checks v0.1's shot deform and whether caching per shot exists (v0.1 item 8). What it
finds is v0.1(.x) work and goes first; v0.2b's shot checks build on it.
