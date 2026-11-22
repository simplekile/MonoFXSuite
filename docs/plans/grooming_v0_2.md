# MONO Grooming v0.2 (plan; decided 2026-11-13; v0.2a core rebuilt 2026-11-15 on the user's final model: density layers, each with its own number and its own mask; the t64 check's bugs fixed in t65; panel and gates open)

v0.1 (released in MonoFX Suite v0.1.25, contract in `grooming_v0_1.md`) makes the whole groom
automatically from the hair mesh. v0.2 lets the artist change that result where it is wrong, on top of
it: the automatic groom stays the base layer and every v0.2 edit is a layer over it, never a second
system beside it (v0.1 plan, "Not in v0.1").

The v0.1 known issues (crown denser than v006, thin skin under floating mesh, a few strands outside
their lock) are answered here by edits the artist makes, not by more tuning of the automatic rules.

## Order: three parts, each released on its own

| Part | What the artist gets | Why this order |
|---|---|---|
| **v0.2a Density layers** | Density layers over the automatic groom (Substance Painter style): each has its own density number and its own painted mask, so an area can be made thinner, denser or bare; the tool's own workspace and pie menu | Fixes most known issues (crown, thin skin) with the least new machinery; the layer system is reused by b and c |
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
| Manager (plan, briefs, diff review, gate decisions) | Opus 5.5 (the user picks it in the app); Fable 5.2 only while a design question is open | high | The decisions every other session builds on |
| Spike; design with no known answer (a new scatter, the cause of a miss nobody has traced) | Fable 5.2 | high | Design under open questions; a wrong choice costs the whole part |
| Build of a task the spike already settled (panel from the picked mockup, adapter functions, unit tests, the acceptance script); a fix round from a checker's list (bug, cause and script given) | Opus 5.5 | high | Careful work with a clear target |
| Checker of new work (no scripts yet; has to try to break each item) | Opus 5.5 when the executor ran on Fable 5.2, Sonnet 5.5 when it ran on Opus 5.5 | high | A different model from the executor, so it does not share its blind spots |
| Re-check of a fix round (the earlier checker's scripts run again unchanged, numbers compared, docs against numbers) | Sonnet 5.5 | high | The scripts and limits exist; the work is running and comparing |
| Mechanical runs (rebuild the HDA, run the acceptance script and QC again, flipbooks, changelog and release steps, moving notes) | Sonnet 5.5 | medium | Follows written steps; nothing to design |
| Read-only look-ups (find a function, list sessions, read a log) | Haiku 5.5, as a subagent | low | Cheap and fast; the result comes back in the same turn |

Changed 2026-11-15 on the user's decision (cost): Fable 5.2 was the executor of every core round and
the manager; most of that work was fixing from a checker's list and running scripts again.

A session never gets a model above the manager's (the app ignores it). When a cheaper model fails a
task twice, the manager restarts the task one row up, not a third try. The checker is never on the
executor's own model. The manager reports to the user when a session's final report is in, not at
each "still running" note.

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
   no global mask. A new density layer's mask is black, so adding a layer changes nothing until it is painted
   (confirmed by the user, 2026-11-15).
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
   cannot be deleted, moved or switched off. With no other layer the groom is the automatic groom, byte for
   byte whatever was painted and removed before. Against v0.1 ("Fit lookup per lock", decided 2026-11-15, see
   "Speed" below): with the toggle OFF, which is how a scene saved by a build without the parm opens (v0.1 and
   the test builds before 245f480), it is v0.1's groom within v0.1's own run-to-run difference (v0.1 against
   itself, t68's 10 runs each: up to 0.0024 cm on a groom it made and saved, 0.0123 cm on the Helen scene as it
   saved it); with it
   ON, a new node's default, every lock has v0.1's roots and strand count, and the strand points move: measured
   0.469 cm at most on a fresh v0.1 groom (44.6 % of points move) and 0.958 cm on the Helen scene as v0.1 saved
   it (57 %). No bound is claimed for that move.
6. **Black in a mask = "this layer does not apply here"**: the density below shows. It is NOT "no hair". No hair =
   a layer with D = 0 painted white. A layer may be denser than the automatic groom: D = 300 over locks at 150
   gives 300 (measured 299-303 / cm2 on four kinds of skin, t63).
7. **Folders are not in v0.2a (confirmed by the user, 2026-11-15; moved to a later part, see "Not in v0.2a"
   under "Done when").** A folder of density layers with a shared mask would need a second mask
   level in the stack, the tree and the brush's target: not free. A group or lock row of the tree already gathers
   its density layers, and a region shared by several layers is painted once and reused as a Multiply top layer.
   Older dev files with folders open: a folder's opacity and eye go into its layers.
8. Quick picks are densities: 0 / 75 / 150 / 300 (`config.MASK_DENSITY_PICKS`). The brush itself paints a grey into
   the mask (1 white by default; `config.MASK_VALUE_PICKS` 0 / 0.5 / 1).

**What "= D" means where locks share the skin (decided by measuring, t63 `o2_*`).** A layer's D is what the locks
it is owned for give on that skin TOGETHER:
- owned by **All locks**: every lock on that skin together gives D (each D / the number of owners of that prim);
  measured on eight kinds of skin, the most stacked included (7 locks): 0.96 / 0.98 / 1.00 of D at 40 / 120 /
  300 there, 0.92-1.06 over the eight kinds (t63); the t64 check, 174 cases on 12 places of its own: 0.85-1.09
  where 20 or more roots are asked.
- owned by **a group**: the group's locks on that skin together give D; locks of other groups there keep what the
  layers below give them.
- owned by **one lock**: that lock alone gives D on every prim it owns, whole (not divided by the other owners),
  and the other locks there keep what they had. Measured on the most stacked skin (a layer of 120, the four
  largest owners in turn): 0.998 / 1.051 / 1.022 / 1.027 of 120 (t63; the t64 check, 17 lock cases: 0.87-1.19);
  the other locks' roots there unchanged, only that lock recooked. So a
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
  0..1), `parent` (a mask layer's density layer) and `legacy` (a density layer read from an older test build's
  0..1 mask: below)), `mask_id_high` (a layer id is never reused). `schema` 6.
  Schemas 2 to 5 were never released; on reading (`model.migrate`, `_density_layers`) their layers come over:
  - **schema 4** ("= D strands / cm2" under a painted mask) and a schema 3 fill layer in strands / cm2 (Replace):
    a density layer of that D, opacity and owner whose mask is one paint layer holding the stored mask (the paint
    layer keeps the old id, so the paint on the node is found). The same result as before.
  - **schema 5** (one 0..1 mask x the lock's own Density) and the 0..1 layers of **schema 2 / 3** (paint layers,
    factor fills 0..1): the layers of one owner become the mask stack of ONE density layer of that owner, named
    "Older build N" and marked `legacy`, whose D is the owner's Density setting when the file is read. A legacy
    layer's mask blends by that build's own rule (`logic.legacy_mask`: the stack starts at the automatic groom
    and carries what is left of it and what the lock's Density adds), so the file gives what it gave: white =
    the owner's Density, black = no hair, a Multiply / Min layer or a grey fill = the automatic groom thinned (a
    factor m over unpainted skin is exactly a layer of D = 0 under the mask 1 - m: m x the density below).
    (At 65e782c these became a plain density layer of the owner's Density whose mask started black: every
    thinning was lost and black showed the automatic groom, t64 B2.) What still differs: the older build blended
    the layers of every owner reaching a lock as one stack in the list's order; here each owner's stack starts
    on its own and the owners apply all locks, group, lock. Normal, Multiply, Add and Subtract give the same
    either way; a Min or Max layer of a group or lock over skin an all-locks layer also painted compares with
    its own stack only. Measured (t65): t62's `layers.hiplc` gives 114,377 strands with the suite that wrote it
    and 114,377 here, every one of the 61 locks the same count.
  - a **folder** (schemas 3 to 5) is gone: its opacity is multiplied into its layers', its eye switches them off.
  - dropped, by name: a factor over 1, and a strands / cm2 layer in another blend mode than Replace (schema 3).
  `model.dropped_masks` / `converted_masks` name them, OnLoaded says so on the status bar (what was dropped;
  that a "= D" layer became a density layer of D under its mask; that 0..1 mask layers are kept in "Older build"
  layers that blend as before) and `mask_dropped(node)` gives the panel the sentence; never a dialog, never a
  traceback. The JSON on the node is rewritten only by the
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

**Shot deform on (t65, after the t64 check's B6).** The display with Shot deform on no longer captures its locks
inside the per-lock loop either (`capture_flag` is 0 for both outputs): a lock's hair is the rest strands
whatever deforms it, one cache entry shared by the display at rest, the display deformed, output 1 and publish.
The capture comes per lock from cached strands (`_capture_loop`, the display's own copy of output 1's loop; one
capture a lock per kind of hair, outside the limit's count), and the deformed hair is kept by its state
(`deform_keys`: the locks' keys, the animated mesh at this frame, the capture radius), so an undo back to a
state the cache holds reads it: no capture, no Point Deform. Captured in the loop (v0.1), every state of a lock
held 800 B a point: every undo regrew its locks, and the cache held 7.5 GB "live" after the deform was off.
Measured (Helen, hython, frame 12, the t64 check's `speed.py`): 10 strokes, 10 undos: 0 locks regrown by any
of them (65e782c: 0-5), each undo 0.026-0.032 s when its deformed state is held and 1.2-1.5 s when it is not
(the whole groom deformed again; 65e782c: 0.83-1.87 s); switching Shot deform on no longer regrows the groom
(first cook 4.2 s, was ~12 s); with the deform off again the live set is what it was (646 MB). A deformed state
is the whole deformed groom, 251-264 MB on Helen by `memoryusage`.
**Decided by the user (2026-11-15, t66 B6): the memory route**, not a packed display. The deformed states are
held APART from "Undo cache, GB" (`LockCache.APART`: not in its count, never pushed out by hair or pushing
hair out), in a limit of their own on the node, **"Deformed undo, GB"** (`undo_deform_gb`, default 4 GB;
`cook_deform_store` keeps them under it, the oldest going first, the newest always kept). Never more than the
user's limit (+ the state being stored). Why 4 GB (the t67 `u6`, Helen, frame 12, a deformed state 264.1 MB):
it holds 15 undos of a chain (the limit over one state, less the one shown), so a normal undo chain of 10-15
strokes with Shot deform on stays under 0.1 s; 2 GB would hold 7, 8 GB 31 at twice the memory. Measured at
4 GB, 20 strokes, 20 undos, 20 redos: the 15 undos and 15 redos inside the count 0.026-0.082 s, 0 locks grown
by any undo or redo; outside the count 1.71-1.87 s each (undos: the oldest states; redos: the NEWEST, which the
undo chain's recomputed oldest states pushed out, t68), the whole groom deformed again
(0 locks grown: the rest strands are cached; the cost is Point Deform of the whole groom). Peak memory: the
deformed states 4,227.8 MB (16 held, limit 4,295 MB), the hair cache 1,523.7 MB (limit 2,147.5 MB), the
captures 3,338.7 MB (one a lock, made once a deformed output is read, outside both limits as decided in
round 3): 9,090 MB together, the memory the tool ADDS; the process's working set peaks at 16.75 GB with the
default (t68: 8.3 GB held after the first deformed read, plus these); with the deform off again the tool's live
set is 646.5 MB and no deformed state is held. On a machine that cannot spare it the artist lowers "Deformed
undo, GB": fewer fast undos, the same hair. A lowered limit frees nothing until the next state is stored (an
undo or redo that finds its state stores none, t68). Not covered by this limit: a deformed read of output 1
(an anim wired and something reading output 1) deforms the whole groom again on every read, 1.2-3.1 s a read,
the newest state included (t68; `u6` reads the rest groom).

**Speed, and one change to the automatic groom that needs a decision (round 3).** A stroke missed the
limit (0.2 s a lock + 0.1 s) on three places in the second check. Most of a small lock's cook was a fixed
75 ms: the strand fit searched every lock's mesh for its own. Each lock now looks its strands up on its own
mesh piece ("Fit lookup per lock" on the node, on by default), its automatic roots are kept between
strokes, and two per-point passes were folded together: strokes on Helen 0.29-0.85 s for 3-6 locks (limits
0.7 / 1.3), the whorl 1.4-2.3 s for 24-35 locks, a full cook 7.6 s instead of 10.9.
**The per-lock lookup is not v0.1's hair bit for bit**: the same roots and strand counts, but 45 % of the
strand points move (half under 0.008 mm, 1 % over 1 mm, at most 4 mm; the t64 check: 5,309,021 of 12,554,097
coordinates, at most 4.10 mm, 21,801 over 1 mm), and 8 of the 27 grooming-check numbers of the no-layer groom
move by 5e-5 to 1 % (all 27 pass). With the toggle off the groom is v0.1's within v0.1's own run-to-run
difference: v0.1 is NOT byte-identical from run to run (the t68 check, 10 runs each, 45 pairs: on a groom
v0.1 made and saved up to 0.0024 cm, 5 of 10 runs identical, 3 off by one coordinate, 1 by 2 strands at 0.0016
cm, 1 by 2 strands at 0.0024 cm; on the Helen scene as v0.1 saved it no two runs identical, up to 212,116
coordinates and 0.0123 cm), and this build with the toggle off lies within that spread (on the made groom each
run byte-identical to some v0.1 run). The acceptance's tolerances, set from those runs: 0.003 cm and 0.015 cm,
strand counts per lock equal. The speed limit with the toggle off: below.
**Decided (the user, 2026-11-15, t64 B4):**
- A node created new: on. Strokes 0.27 s or more inside the limit (t62), the cold full cook 0.72 x v0.1's (t63).
- A scene saved before the toggle existed: OnLoaded writes it OFF on the node, once
  (`grooming_adapter.keep_old_lookup`; the node's user data `monofx_fit_lookup` records that the choice was
  made, so the artist may turn it on afterwards and it stays), and says so on the status bar. Such a scene
  holds no value for the parm, so it would otherwise take the default and a published v0.1 groom would reopen
  with its strand points moved. "Saved before the toggle" is read from the saved file itself: a hip holds each
  parm of a node as a record line of its own (`lookup_per_piece\t[ ...`), and `hip_holds` matches that record,
  not the word (t68: a sticky note holding the name opened an old scene with the toggle on; a node name, a
  comment, an expression or an embedded definition holding it does not count either). Known and contrived,
  not handled (t69): the record text itself after a REAL newline inside a sticky note, a node comment, node user
  data or a string parm, or a spare parm of that name on another node of the old scene, still reads as "holds the
  parm", and that scene opens with the toggle on. The artist setting the
  toggle by hand rewrites the note ("on: set by hand" / "off: set by hand", the toggle's callback). **A node
  copied out of an old scene and pasted into another is a new node** (decided by the manager, round 3): it
  keeps the toggle as it comes, on, with no note, as any node made now. The parm came in the middle of the schema 4 test builds (245f480 has it, on), so
  a schema number cannot tell (t66 N2). The file decides whenever it can be read, whatever the data's schema:
  a scene opened while another copy of the library without the parm was installed had its data rewritten in
  today's schema before this library took over, and OnUpdated then read schema 6 and kept the toggle on (t67);
  a node made in this session is marked by OnCreated and never judged. Only without a file to read does the
  schema decide (under 4: off). The choice is made before
  OnLoaded writes anything else (`mark_old_regions` rewrote the data of a scene whose regions carry no rule
  number, Helen as v0.1 saved it, in today's schema first, and the toggle stayed on: t66 N1, points moved up to
  0.958 cm). The acceptance grades the limit with the toggle on
  (`s1`, `r5`) and reports the same checks with it off as their own items (`s2`, `r5b`), on the same limits.
  **Decided by the user (2026-11-15): the thinning order is LAZY with the toggle off too**, made at a lock's
  first stroke and kept with its automatic roots, as with it on. **Known, stated cost, not a pass:** with the
  toggle off (scenes from before the toggle) the first stroke on a lock never painted may go over the stroke
  limit by up to 0.10 s, once per lock (t68 on 2865078: 3 of 8 first strokes over in each of 3 runs, the worst
  0.100 and 0.098 s); later strokes on those locks are inside it (0 of 48 over), and the cold cook stays inside
  1.10 x (display 1.016 x, rest 0.794 x v0.1's on Helen as v0.1 saved it, t68). The acceptance's `s2` keeps the limit's number: strokes on locks
  painted before in the run pass or fail; first strokes are reported with their margin as "known, decided
  2026-11-15" (`s2_first_strokes_with_the_lookup_off_known`, counted neither as a pass nor as a fail). Tried
  in t67 and reverted: the order made eagerly with the roots when the toggle is off (`thin_order_eager`): 0 of
  48 first strokes over, but 2.48 s of the cold cook (perfMon), and the display's cold cook of Helen as v0.1
  saved it (with Shot deform on) 1.16 x v0.1's (17.67 / 15.21 s; the per-lock capture outside the loop costs
  what v0.1's capture in the loop did, 3.07 / 2.98 s). Measured with the toggle on (t67, fd074e4): 24 of 24
  strokes inside the limit (worst margin 0.067 s) and the cold rest cook 0.47 x v0.1's (`r5`); the numbers
  with it off, lazy, are in the t67 report ("Lazy again").
- "No layers = the v0.1 groom" (decided by the user, 2026-11-15): with the toggle off, "v0.1's groom within
  v0.1's own run-to-run difference". The acceptance: a groom v0.1 made and saved opens with the toggle off,
  every lock's strand count equal and no point farther than 0.003 cm from v0.1's (`r6`; v0.1 against itself
  0.0024 cm over t68's 10 runs); the Helen scene as v0.1 saved it opens with the toggle off, the counts equal
  and no point farther than 0.015 cm (`r6c`, `r6d`; v0.1 against itself there 0.0123 cm). No rerun until it passes. With the
  toggle on (`r6b`): every lock's strand count and every root (within 1e-5 cm) are v0.1's; how far the strand
  points move is printed, not graded (0.469 cm at most on a fresh v0.1 groom, 0.958 cm on Helen as saved).

**Paint belongs to the painted node (round 3; t65).** Paint is on only while the painted node is the
selection. Esc ends Paint from anywhere in Houdini's window, also while the mouse is held: what was painted so
far is kept as one stroke, the rest of the drag paints nothing, and Paint is off at once, not at the release
(Esc reaches a pane with the keyboard as a shortcut, so the filter takes the ShortcutOverride as well as the
key press: posted to the network editor it used to leave Paint on until the button was up). Another node
selected, in the node's network or in any other (an object in /obj), ends Paint (the status bar says so), and
so does no node selected at all: the next drag in the viewport paints nothing. The grooming node selected again
while it is the only selection keeps Paint; after Paint ended it stays off (the panel turns it on again).
Entering Paint makes the node the selection. When the viewport cannot take the brush back (it looks at
another network) Paint is off, never half on.

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
and stays while thin_u < keep (`thin_order`, made the first time a layer covers the lock and kept with its
automatic roots: see "Cost" below):
- Start roots and scattered roots are each ordered by pairing: every root is paired with the nearest root not
  yet paired, one of the pair goes to the first half (the one farther from the roots already there), the
  other to the second, and each half is paired again, 10 times; the halves are the binary digits of thin_u. Of
  two neighbours one stays at a keep of 0.5, so the share is kept locally whatever the density and however
  near an edge. To stay cheap the roots are sorted along a Z-order curve and a partner is looked for among the
  next 10 (among all, once a half holds 64 or fewer).
- A small start grid (400 roots or fewer: a disc of a millimetre or two, several times denser than the rest of
  the lock) takes a farthest-point order instead: what is left of it must stand as evenly as it can.
- Whorl roots: their sunflower number with its bits reversed. (t65: ordering them by pairing on where they
  land was tried against the local evenness measure's misses at the whorl, below: it changed which locks
  miss, not how many, and was dropped. t67 traced why: the misses are pairs of roots of two KINDS, below.)
- Partial coverage puts the layers' own roots among automatic roots that stayed; a layer root nearer than
  0.45 of the root spacing asked there to an automatic one is moved off it, on the skin (`mask_apart`).
Tried and dropped: the root's number in hairgen's scatter (0.35 to 1.85 of the share from skin to skin); a
dither of the root's position (stripes; two places just over the limit); the same on whole cells (+0.06 to
+0.10 at x 0.25); a farthest-point order of everything (the rim of a set comes first: a patch inside a large
start grid kept 0.8 of the share, stacked skin 1.17, floating mesh 0.56); pairing every root against every
other (+13 s on Helen's cold cook).
Cost (t65): the order is made only for a lock a layer covers, the first time, and kept with the lock's
automatic roots (38 us a root: Helen's largest lock, 7,400 roots, 0.28 s once, on its first stroke; a stroke
on a lock already ordered pays nothing). Made for every lock on every cook, as at 65e782c, it was 4.5 s of
Helen's cold cook with or without layers, and the display's cold cook was 1.13 x v0.1's (t64 B5): with the
toggle on 0.91 x (t66, 3 pairs); made eagerly with the toggle off (t67, reverted by the user's decision) it
was 2.48 s and the display's cold cook of Helen as v0.1 saved it 1.16 x ("Speed" above). A per-element VEX pass over chunks of the order was tried to run it on all cores:
array code runs ~30 x slower outside a detail wrangle (6 s for one lock), dropped.
Traced in t63 (the two partial-coverage cases round 3 left open, and its one lock over a density limit):
- `hair_base_21` on ordinary skin (+0.122 in t62; +0.143 here at first): every root that read as bunched was a
  layer root beside a kept automatic root. `mask_apart` sized its distance from the lock's set Density x keep;
  that skin lies under floating mesh, where the automatic roots start the lock and 26 / cm2 of them are left
  where 150 are set, so layer roots were held 0.037 cm off them while roots asked there stand 0.14 cm apart.
  `mask_apart` now counts the automatic roots really kept round the place (the 8 nearest over the disc they
  span): rise 0.0. `hair_base_12` on the top of the head (+0.087 in t62): at most 0.008 now. All 31 grey-mask
  and opacity cases of t63 are inside +0.05; the report lists any case of the other checks that is not.
- One lock over its density limit on a sliver of skin (t62: `hair_bang_20`, 3 roots where 0.8 are asked on
  0.02 cm2; t63 also `hair_base_21` on the top of the head, 47 where 34 are asked on ONE prim of 0.22 cm2).
  The t64 check found the same excess at every D (1.337 x at 120 / 280 / 300 / 320) and asked whether the split
  is biased there. Traced in t65 (`b1_trace*.py`): it is not. Inside the network the lock's layer scatter is
  asked 33.7 roots on that prim (density x area, all four corners 150) and, over 40 scatter seeds, puts 33.6
  there on average (sd 4.6; with hairgen's relax off 33.9, sd 5.0; the t66 check's own 40 seeds: 35.1, sd 5.15,
  the shipped seed drawing 45, the highest of the 40), and the seven prims beside it whose corners
  hold other densities get 0.95-1.06 of what they are asked: no bias in `mask_split`, `mask_skin` or the count.
  The scatter's seed is the lock's id, so the one draw this lock gets (43 by the scatter's own `skinprim`, 45-47
  by the nearest prim) is the same at every D: fixed, not a new toss a D, and not a bias. hairgen's scatter
  hands a forced count to single prims with a spread of about 0.8 sqrt(N) (400 equal quads asked 34 each:
  variance 26-31), so a lock asked N roots on ONE prim misses max(0.15, 2 / sqrt(N)) in a few per cent of cases
  (t64: 1.5 % of (lock, prim) cases over the whole scalp at D 300, never a lock on its whole skin, not visible
  in a flipbook). Over a lock's whole skin in a patch the counts are tight ((roots - asked) / sqrt(asked): spread
  0.43). **Decided by the user (2026-11-15, t66 B1): no new scatter in v0.2a.** The known case, stated: on
  Helen's top of the head `hair_base_21` holds 45 roots where 33.7 are asked on its ONE prim of 0.22 cm2 (the
  shipped seed's draw; the t66 check's 40 seeds: mean 35.1, sd 5.15), and over the scalp 1.5 % of (lock, prim)
  cases miss the limit on one prim. The limit max(0.15, 2 / sqrt(N)) is not changed; it applies to all locks
  together and to each lock on its own skin inside the painted area (the prims covered in full by the paint (36-44 % of the painted area on the three test places, t68); the rim is not graded), not to a lock
  on one polygon: the acceptance (`d1`, `d2`, `b1`, `b3` on the top of the head) grades each lock over the
  patch and lists a lock whose skin there is one polygon with its numbers, unpassed and unfailed. The same
  for evenness (the manager, 2026-11-16, round 4, after t69 3b): the evenness checks skip the locks the density
  grading lists in `locks_on_one_polygon` and list them in the row (`not_judged_one_polygon`), neither passed
  nor failed: `hair_base_21` holds 35 roots there, so one root is 0.029 of its clumped share against a rise
  limit of 0.05, and the tie-break moving three border roots took it from 0.026 to 0.057. A scatter
  with a fixed count per prim (each prim floor or ceil of what it is asked, the total kept: our own scatter
  and relax in place of hairgen's for the layers' roots) is deferred.

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
| `undo_cache_usage(node) -> dict` | What the node's hair cache holds against "Undo cache, GB": `bytes`, `live_bytes`, `undo_bytes`, `undo_states`, `limit_bytes`, `dropped`, `gb`, `limit_gb`, `capture_bytes`; the deformed states apart, against "Deformed undo, GB": `deformed_bytes`, `deformed_states`, `deformed_limit_bytes` (the adapter's, not a mask function) |
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
- Still open: the result is not shown as hair while the button is down; a pen's pressure, mirror. (Radius by drag
  closes in v0.2a's last task: wheel and Ctrl+Shift+LMB drag, decided 2026-11-19.)

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

**Panel, built (t70, 2026-11-16; minimal: no folders, no workspace, no pie menu).** Mockups in the sandbox
(`tests/t70_density_panel/mockups/index.html`, three reworks of E2); **the user picked A, "E2 kept"**:
- The lock tree (heading "Locks") holds each row's density layers as its first children, top first (the upper
  wins), each with its mask layers under it, top first. Automatic is the last row of All locks' layers, a padlock
  where the eye is (no eye, cannot be selected for paint, moved, deleted or set; its Properties say so). The eye
  column sits at the left edge for every row (v0.1 had it at the right). Status column: a density layer's D and
  opacity under 100 %, a mask layer's blend and opacity, a fill's value, "painting" on the layer being painted.
- Tree tools in the tree's head: new density layer (owner = the selected row: All locks, a group, ONE lock;
  several locks selected are refused with a sentence; a selected layer gives its own owner), new paint layer (a
  fill layer: right click or Properties), up / down (among the layers of the same row, or inside one mask), delete
  (Del too; a density layer goes with its mask, the selection goes to what held it). Rename: double click or F2.
  Every command is ONE adapter call (`mask_add`, `mask_remove`, `mask_move`, `mask_set`, `mask_fill` /
  `mask_clear` / `mask_invert`: one undo step each), cooked in the loading line. Reorder is by the buttons, not by
  drag (drag stays for locks and groups).
- The row bar above the tree: a mask layer's blend and opacity, a density layer's D and opacity (mockup A).
  Properties: a density layer's D (slider, field, quick picks 0 / 75 / 150 / 300), owner (combo: All locks, each
  group, each lock) and the rule in one sentence; a fill layer's value (picks 0 / 0.5 / 1); a paint layer's Paint,
  Eraser, Grey (0 / 0.5 / 1), Radius, Softness and Fill white / Invert / Clear (Clear asks on the first click).
- Paint: the selected paint layer's Paint button (`paint_enter`, `HOOKS["stroke"]` cooks the stroke in the loading
  line and says "Stroke on <layer>", `HOOKS["exit"]` brings the panel back when Paint ends in the viewport).
  Selecting another paint layer moves the brush to it; selecting a density layer, a lock row, deleting the layer or
  Esc in the panel ends Paint. Hair display becomes Hair preview while painting and comes back after. While Paint
  is on a strip under the view bar shows what the scalp shows (Result / Layer / Roots, `set_brush(view=)`), the
  scalp's X-ray and the legend (`logic.DENSITY_STOPS` x the Density of All locks, `logic.DENSITY_RAMP`'s colours);
  Properties can be folded to one line (view state, ends with Paint). Brush values are session state (no undo).
- Settings: the ⚙ menu keeps Font size and X-ray (per user) and opens a "Node settings and undo cache" page in the
  Properties column: Fit lookup per lock, Undo cache, GB and Deformed undo, GB with what the cache holds
  (`undo_cache_usage`). Set through two adapter functions added for the panel, `node_settings(node)` and
  `set_node_setting(node, key, value)` (one undo step; the lookup toggle also writes the note its own callback
  writes). Opening a node puts `mask_dropped`, `mask_problem` and the lookup note on the message line.
- Code: `tools/fx/grooming/layers.py` (the controller's part, a mixin), `ui_layers.py` (the view's part); tests
  `tests/test_grooming_layers.py`. Not built: mask thumbnails on the rows (icons instead), the row tint of layer
  rows (Houdini's sheet paints item backgrounds), drag to reorder layers, a missing lock's layers shown under
  Missing locks are listed but their owner cannot be picked again from the combo.
- Checked (t70 `report.md`): pytest 812 passed; offscreen grabs 42 (7 states x 400 / 760 / 1100 x scale 1 / 1.5),
  0 overflow; contrast 34 of 36, 2 known; GUI Helen through the panel's widgets 30 of 30 (a stroke of D 75: 364
  automatic roots on the painted core -> 89, asked 91.8; undo 364, redo 89; eyes, D 0 -> 0, opacity 50 % -> 180,
  reorder, delete; panel and node agree at 13 of 13 points); `accept_v02a.py` 80 of 84 (the three failing by
  decision with main's rows, `s2` known, `s1` passing), `accept_v02a_gui.py` 19 of 19.
- Fix round after the t71 check (2026-11-19, t70 `report.md` "Fix round (t71)"): an empty rename shows the node's
  name again and says a layer needs a name; the settings page and `set_node_setting` clamp the two limits to
  0.01-16 GB, typed or dragged; a node deleted (or File > New) under an open panel puts it in its no-node state
  with one message instead of raising on every poll (v0.1's code); the status column elides inside its cell (it
  was drawn over Automatic's name at 760 px); the row bar puts its values on a second line when the name and
  values do not fit; a closed panel stops polling; Paint ended in the viewport says so. Left as decided:
  duplicate layer names, a short Properties at 400 px (Fold), the two X-ray toggles while painting.
- Look from the MonoFX Loader (t74, 2026-11-19, the user's pick "C"; sandbox `tests/t74_loader_look/`): icon
  buttons in the bars (only Publish keeps words), the view controls in the top bar when wide, Properties a
  full-height inspector (Details first, foldable sections), the tree painted by a delegate (one background, row
  and column separators covered by hover / selection, filled eye), no "·" joins. Behaviour unchanged. The row
  tint of layer rows (listed "not built" above) is decided against: one background for every row.

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
  when nothing lies below); every layer black, off, at opacity 0 or deleted = the automatic groom byte for byte.
  "Over a white area" means the black covers it (accepted by the user, 2026-11-15: black removes white at
  every point inside a black dab): every white point lies inside a black dab at full weight (a
  hard brush over the same area on any dab centres; a soft brush wider by its soft part; the same soft brush
  again on the same path, t65). A black stroke that leaves part of the white outside its dabs, or under the
  soft part of a brush of the same size, leaves that part white, as paint does: the t64 check's "same size,
  other dab centres" left 3-4 points that no black dab reached (0.36-0.39 cm from the nearest dab of 0.3 cm).
- The mask stack: each blend mode gives what the formula says, in the mask's numbers and in roots; Multiply 0 /
  0.5 / 1 as the top layer; fill layers; erase; a soft edge; a tiny mask moves no root.
- Evenness everywhere: each lock's local clumped share in a painted patch is not above the same lock's
  no-layer value there + 0.05 ("Evenness, the measure" below). NOT MET at the crown whorl under partial
  coverage for a few small fringe locks (t67 final run: `hair_bang_04` +0.065 at D 0 mask 0.5, +0.062 at D 40
  mask 0.5, +0.119 at D 120 opacity 0.75; `hair_base_09` +0.067; the t66 check's `hair_bang_05` +0.105 at the
  fringe start). **Decided by the user (2026-11-15): the limit stays +0.05 and these checks stay failing;**
  the cause was traced (t67 `evenness/analysis.md`): the roots that read as bunched are pairs of two kinds of
  automatic root of the same lock that stood as close before any layer (a whorl root of `root_place`'s
  sunflower on one of the lock's scattered roots, 9-14 of the 12-16 roots in pairs, two of them 0.0003 cm
  apart; start roots whose grid places are far apart in the farthest-point order but land 0.012 cm apart).
  Each kind is thinned by its own order, so a keep k keeps both roots of such a pair with a chance near k x k;
  at keep 1 they do not read as bunched, and a layer of high D shrinks the spacing asked so the same pairs
  pass again. `hair_bang_05` at the fringe start is one layer root 0.0648 cm from a kept automatic root where
  the measure's line is 0.0684 cm (`mask_apart`'s spacing estimate and the measure's differ ~2 x at a lock's
  start edge). The fix, not built: ONE thinning order for all of a lock's automatic roots by where each lands
  (about half a day, plus a day of re-checks; which roots a partial mask keeps changes once for every painted
  groom). Dropping the near-coincident pairs at the source would change the automatic groom itself: no.
- **Checks failing by decision** (the limits stay, the checks stay failing, listed in every report):
  `d3_partial_coverage_roots_even`, its 4 crown_whorl rows (= 40 and = 0 at mask 0.5, = 120 at opacity 0.5 and
  0.75), and `b1_blend_modes_roots_even_crown_whorl`, its 3 rows (add 0.25 over 0.5, max 0.5 over 0.75, multiply
  0.5 over 1.0 at opacity 0.5): the crown evenness above, decided by the user 2026-11-15; and
  `d4_soft_edge_follows_the_mask`, top_of_head = 0, ring 0.3-0.6 cm (17.7 % over against 15 %), a known open
  item decided by the manager 2026-11-16 (round 4), below.
- **Known open: the soft edge keeps too many roots in its inner part (d4, round 4).** One soft white dab of
  radius 1.5 cm on a layer of 0; every rest root's keep against the mask AT THE ROOT (a radial fit of the
  mask's point values, residual under 0.002), no prim assignment (the t69 checker's method, t67 `thin_r4/`).
  Kept / expected in the ring 0.3-0.6 cm: lock start (hair_base_12) 1392 / 1225.6 = **1.136** (5.5 sd of the
  binomial); crown 1888 / 1580.4 = **1.195** (9.0 sd); top of the head 132 / 108.8 = **1.214** (2.6 sd); the top
  moved by 0.705 cm 282 / 235.8 = **1.196** (3.5 sd). The ring 1.2-1.5 cm keeps too few at all four (0.958 to
  0.976, 7 to 13 sd), the 0.9-1.2 ring about right (0.971-0.998). So it is a bias of the thinning against the
  mask's falloff, not one draw: the inner, mostly white part keeps 14-21 % more than 1 - mask, the outer edge
  2-4 % fewer. The d4 prim reading passes at the lock start and the crown (their rings are dense, so the extra
  roots are inside 15 %) and fails only on the top of the head. Not fixed in v0.2a; the cause (how the keep
  share follows the mask between the points a prim holds) is not traced.
- On Helen: the crown painted down to v006's density (~5,100 / cm2) and the thin skin under floating mesh painted
  up, both in the GUI by scripted strokes, with the QC numbers before and after in the report (the user's own
  try with a mouse or pen is the User look gate); grooming-check is two-sided on a painted scene.
- A stroke recooks only the locks under it, at most 0.2 s per lock plus 0.1 s; undo removes exactly that stroke,
  in under 0.1 s and with no lock recooked, also with an anim wired and output 1 read, and for a whole chain of
  strokes (30 in a row, then 30 undos and 30 redos) while the undo cache ("Undo cache, GB") holds them.
- No layers = the v0.1 groom: strand count and QC numbers as t55; a scene from before "Fit lookup per lock"
  opens with it off and is v0.1's groom within v0.1's own run-to-run difference (0.003 cm on a groom v0.1
  made and saved, 0.015 cm on Helen as v0.1 saved it, counts per lock equal); with it on, the same roots and strand count per lock,
  the strand points' move stated as measured (0.469 cm / 0.958 cm at most), not bounded.
- Layers survive Detect, Update regions, save / reopen and Publish (read back from the publish JSON); a missing
  lock keeps its layers; files of schema 3, 4 and 5 open and give the strand counts they gave.

**v0.2a core closed 2026-11-16 by the user's decision.** Last acceptance (round 4, `df3c7ce`): 79 of 84 pass,
1 known (`s2_first_strokes_with_the_lookup_off_known`, decided 2026-11-15), and these fail by decision. The
limits stay and the checks stay failing:
- `d3_partial_coverage_roots_even`: 4 crown_whorl rows (the crown evenness, decided by the user 2026-11-15).
- `b1_blend_modes_roots_even_crown_whorl`: 3 rows (the same, 2026-11-15).
- `d4_soft_edge_follows_the_mask`: top_of_head, ring 0.3-0.6 cm 330.5 against 280.8 (17.7 % over, limit 15 %).
  This is the soft-edge bias (decided 2026-11-16). Kept / expected by root in the ring 0.3-0.6 cm:
  - lock start 1.136 (+5.5 sd);
  - crown 1.195 (+9.0 sd);
  - top of the head 1.214 (+2.6 sd);
  - top moved 0.705 cm 1.196 (+3.5 sd);
  - the 1.2-1.5 cm ring keeps too few at all four places (0.958-0.976).

  Not traced, not fixed.

`s1_stroke_speed_8_places_x3` failed in round 4 (first stroke at hair_base_12 1.684 s, limit 1.3 s). It was re-timed
2026-11-16 with the limits unchanged, `--only s1` three times in a row (t67 `accept_r5b_s1_1..3`, `queue_r5b.log`).
Before the runs, no other hython, no `gui.lock`, and no Blender, Resolve or Houdini were running. CPU load was
17-30 % of 32 threads, mostly the Claude app (~1 core), and one other session's pytest (under 1 core) was still
running during runs 2 and 3.

| Run | Pass | First stroke at hair_base_12 | Smallest margin |
|---|---|---|---|
| 1 | yes | 0.974 s | +0.256 s (hair_base_05, 0.444 / 0.7 s) |
| 2 | yes | 0.977 s | +0.222 s (hair_base_05, 0.478 / 0.7 s) |
| 3 | yes | 0.926 s | +0.250 s (hair_base_05, 0.450 / 0.7 s) |

So s1 passes on a quiet machine, and round 4's fail was the machine. An earlier set of three, run the same way
but with its process samples lost (`accept_r5_s1_1..3`), also passed: first stroke 0.981 / 1.218 / 1.112 s,
smallest margin +0.080 / +0.082 / +0.188 s.

**Not in v0.2a (moved to a later part).** Folders of density layers with a shared mask (confirmed by the
user, 2026-11-15): a group or lock row gathers its layers, and a shared region is a Multiply top layer.

**How the acceptance counts (t65, after the t64 check).** A root belongs to the skin prim nearest it ON THE
SURFACE (the exact distance to the prim's triangles, `accept_lib.Skin.assign`), not to the nearest prim centre,
and every root counts: none is left out for standing off the skin (by the surface no root of Helen's groom is
over 0.0025 cm off it, t69: 0.0023 cm; the "floating" roots of round 3 came from the nearest-centre count). A lock asked under
one root (N < 1) is graded by count (t67, after the t66 check): at most floor(N + 2 sqrt(N)) roots, the upper
side of the limit (`ceil` until round 3 passed three rows by one root); a lock over it fails and is listed as
the B1 kind (few polygons, `locks_outside_b1_kind`); its roots are also in the count of all locks together.
Each lock is graded on its own skin in the painted patch: prims covered in full by the paint (36-44 % of the painted area on the three test places, t68); the rim is not graded (partly painted rim prims read 1.77 x on the
crown whorl's rim at D 0, estimated root by root, which this count cannot tell from a measuring error), a lock
on one polygon there listed, not graded (B1 above). Lock borders (t68, corrected in round 3): the roots lie on
their own lock's skin (110 strays at three places, 2.4e-8 to 1.7e-5 cm from it); the HDA cuts a lock's region
by whole prims (`lock_owners`, `region_cut`), and on an edge shared with a prim of another lock the nearest-prim
count broke the tie to the neighbour, so such a lock read N = 0 with 1-2 roots and failed `d1` / `d2` / `b3`.
Now a root within 1e-4 cm of a prim its own lock owns is given to it. Two checks, apart (round 4, after t69 3a:
round 3's one check put 1e-4 cm on both and failed 31 % of the roots): ownership, `z_roots_stand_on_their_own_locks_skin`,
the distance to the root's own lock's skin minus the distance to the nearest skin of any lock <= 2e-5 cm (t69:
1.04e-5 cm at most on 20,000 roots: the nearest skin is their own lock's); and the surface gap, `z_roots_on_the_skin`,
the nearest skin <= 0.0025 cm (t69: 0.0023 cm at most; the scalp quads are not planar, up to 0.0038 cm off
their plane, and the roots lie on no triangulation of them to better than 0.0022 cm). Strands followed by id are where they were within 1e-5 cm
(measured: under 4e-7 cm).

**Evenness, the measure (the t64 checker's, `even_local.py`; `accept_lib.lock_even_local`).** For each lock
with 30 roots or more in the painted patch: a root is clumped when its nearest neighbour of the same lock is
nearer than 0.3 x the spacing asked WHERE THE ROOT STANDS, 1 / sqrt(density), and the density asked there is
(the lock's roots before any layer within 0.1 cm of the root, per cm2) x (the share of them kept: the lock's
automatic roots now / before, in the patch) + (the lock's layer roots within 0.3 cm, per cm2). The lock's
clumped share is the share of its roots that are clumped; the limit is that share under the layers <= the
share of the same lock's roots before any layer (their own local density, share kept 1) + 0.05. The area is
the root's own neighbourhood, not the lock's prims: a lock's automatic roots are several times denser at its
start and at a whorl than on the rest of its skin, so one spacing for the lock on a patch read the same start
grid as clumped or not as the lock's mean density moved (the lock's prims whole: rises of 0.06-0.38 where the
roots stand evenly; the prims shared by their owners: blind on stacked skin).

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

In the network `apply_settings` sits before `root_skin`, so the edit is the last step before `SPINES`
(settings applied -> Root to skin -> spine edits). The two do not act on the same thing: the settings scale
the widths and twist the frame, the edit moves the points and turns the frame with the tangent.

**Storage.** In `groom_data` per lock: control points relative to the root frame (so a hair mesh
version that moves the lock a little keeps the edit), or a drawn curve; `edited` shows in the panel and
the tree (status colour), with Reset. Decided in the spike (2 below): the stored points are HANDLES on the
measured spine, not the spine itself.

**Spike (run 2026-11-20, t76, `sandbox/.../tests/t76_redraw_spike/`, `report.md` there; Helen, hython and
the GUI on the second monitor with scripted mouse events). The prototype is the product's network built from
this repo's `build_hda.py` plus three nodes between `root_skin` and `SPINES`, built into the sandbox; nothing
of the product was changed. Numbers are Helen's, hython unless said.**

1. **Handles: our own Python viewer state, built as Paint is.** Decided.
   - Ours (`t76_state.py`): entered by name on the locked HDA in 0.013 s, it touches no inner node. It reads
     the measured spines (`root_skin`) and the stored points, keeps the drag in numpy while the button is
     down, and writes the node once on release. GUI, 7 scripted drags (`out/gui3/gui.json`):
     - cost: 0.9-1.6 ms of our code a mouse move for one lock (3.6 ms with five), nothing cooks while the
       button is down; on release the write is 0.3-0.5 ms and the cook 0.035-0.147 s for one lock (the
       heaviest, hair_base_20 with 8,661 strands: 0.142 s; the longest, hair_back_20 at 89.6 cm: 0.147 s;
       limit 0.3 s) and 0.188 s for five locks (limit 1.1 s). Only the dragged locks go through the loop.
     - one drag = one undo step: after every drag one undo puts the node's data back to what it was before
       the drag in 0.018-0.026 s with 0 locks regrown (the cache holds the hair), and redo the same.
     - several locks at once: with five fringe locks being edited, one drag of a tip handle moved the same
       handle of all five (1.27 cm each) in one write; one undo takes all five back.
     - the root: dragged, the first handle is where the mouse ray meets the scalp (0.0 cm off the skin at
       every event of the drag; a ray that misses the scalp leaves it where it was), and the cooked spine's
       root is 0.0 cm from the skin after.
     - beside Paint: Paint entered from our state takes the viewport, its stroke is stored, our state gets
       no event meanwhile; after `paint_exit` the viewer is on the node's own state, so control points are
       entered again (it works, the next drag is as before). With Paint ON, our state entered by name is
       taken back by Paint within 2 s (Paint's own "come back" rule). So: one tool at a time, and entering
       one ends the other first.
     - handles need X-ray: drawn as a `hou.GeometryDrawable` (no X-ray) the lock's own hair hid them; as a
       `hou.SimpleDrawable` with `setXray(True)` they show.
   - Houdini's Edit state on an editable node inside the locked HDA (`cp_edit`, an Edit SOP on control
     curves; `EditableNodes`): the state enters ("edit", the node editable, the asset still locked), with
     the viewer INSIDE the HDA, where Paint and our state need it outside on the node. It loses on:
     - what it stores: an Edit node keeps its edit by POINT NUMBER of the curves it is given. The same
       stored edit, with the two locks' curves in the other order, moved the other lock's tip 2.0 cm and
       left the edited one at 0.0 (`out/q1b/q1b.json`). Edits must be keyed by `lock_id` (rule above).
     - what a drag costs: every change of the node cooks it, the edit step and the locks it holds (driven
       through its parms: 1 + 1 + 2 lock cooks a tick, 0.056-0.061 s a tick for two locks of 240 strands;
       one heavy lock is 0.13-0.24 s a cook), where our state cooks once, on release.
     - the root: nothing in the Edit state holds a handle on the skin; the HDA could only move the spine
       back after the fact. And the HDA's display is its output: the control curves are not drawn.
     - NOT MEASURED: a drag of the Edit state's own handle by script (two ways tried, in three runs:
       `setCurrentGeometrySelection` answers "no active selector found"; with the group set on the node's
       parms, mouse events at the handle's place moved nothing and cooked nothing). So "one drag = one undo
       step" and the cooks during a real drag are not measured for this route. The decision does not rest
       on them.
   - Not covered: a hand on a mouse or pen (the drags were Qt mouse events sent to the viewport widget); the
     gestures for rotate / scale about the root and for redrawing a curve (their result is an edit of the
     same control points, measured in hython; the gestures are the build's); a HUD and keys.
   - A GUI test must click once on empty viewport before its first drag: the first press after entering the
     state went to the pane (focus), not to the state (two runs lost their first drag that way).
2. **The edit: control points are handles on the measured spine; each one's MOVE is what bends the lock.**
   Decided.
   - Rule (`VEX_SPINE_EDIT` in the prototype's `build_proto.py`): a lock stores K points in its root frame
     (origin = the measured spine's first point after Root to skin; axes = its tangent, width axis and
     thickness axis there), scene units. For each, the move = stored place minus where the measured spine is
     at the same share of its length; the moves are interpolated along the spine (Catmull-Rom, ends clamped)
     and added to the measured spine's own 49 points. The frame (`lock_axis`, `lock_minor`) turns with the
     tangent, so the offsets `fit_to_lock` reads carry the mesh surface along the bend. The first point is
     put on the skin once it has been moved; a root not moved (stored 0 0 0) stays the measured root.
   - No edit = the groom without the slot: byte-equal (118,705 strands, every lock the same count, max point
     difference 0.0 cm against the unpatched network, two processes). So the QC numbers of a scene with no
     edit cannot move; QC itself was not rerun.
   - Control points equal to the measured ones: hair moves 3.6e-5 cm at most (the lock recooks once, its key
     holds the points).
   - One fringe lock (hair_bang_11, 17.6 cm): tip pushed 2 cm, strand points move p95 1.90 cm and lie p50
     0.03 / p95 0.09 / max 0.36 cm from "the same bend carried"; turned 25 deg about its root, they move p95
     3.33 cm and lie p50 0.08 / p95 0.26 / max 0.54 cm from it. The cross-section keeps its spread across
     the width and the thickness within 5 % at four stations (0.475 -> 0.467, 0.597 -> 0.572 cm ...).
   - A root stored 1 cm off the skin cooks to a root 0.0 cm from it. A root slid 1 cm: the lock's start
     roots follow it (p50 0.38 cm), the others stay on its frozen region.
   - Cost, one lock, three new bends each (limit 0.3 s): 8,661 strands 0.236 / 0.171 / 0.165 s; the 89.6 cm
     lock 0.166 / 0.158 / 0.160 s; 241 strands 0.042 s. Five locks in one edit 0.231 s (limit 1.1 s). Only
     the edited locks recook; the other locks' points are identical. Undo 0.023 s, redo 0.026 s, 0 locks
     regrown.
   - Survives Detect (data unchanged, hair 0.0 cm from before), Update regions (every lock's count the same)
     and save / reopen (edited locks 0.0 cm; the others 0.0022 cm at most, v0.1's own run-to-run noise).
   - Storage: per lock in `groom_data`, `Lock.spine` = the K points (empty = the measured spine), the same on
     `Orphan` (a missing lock keeps its edit; `reassign_orphan` hands it on). `cook_assign` writes them to the
     spine prim as the float array `edit_cp`, which is in the lock's cache key like any prim attribute.
     **`schema` 6 -> 7**; `model.migrate()`: a schema 6 file has no edit and no drawn lock, so the step sets
     the number only; `from_json` must read the new fields (it drops what it does not name). (The prototype
     keeps the edits in a parm of their own, `spine_edits`, only so that `model.py` was not touched.)
   - What the build must add, found by its absence in the prototype: `split_regions` and `lock_infos` read
     `SPINES_LOCKS`, which lies before the edit (a slid root keeps its old footprint, the panel shows the
     unedited length); `root_place` / `region_join` look the lock's mesh up where it was modelled; the mesh
     display, the QC's mesh checks and the shot deform see the mesh where it was modelled too. The mesh
     carried by the same bend (each mesh point's `pu`, `ds`, `dt` put on the edited spine, as `fit_to_lock`
     places a strand) is the one geometry all of these should read. Not prototyped.
3. **How many control points.** Measured; the number a lock shows was the user's call (U1, decided below).
   - A curve through K points at equal lengths (Catmull-Rom) against each of the 61 measured spines
     (12.6-89.6 cm): fixed 5 misses by 1.17 cm at the median and 2.79 cm at worst (52 of 61 locks over
     0.25 cm); fixed 8: 0.33 / 0.97 cm; fixed 12: 0.09 / 0.40 cm. By length is no better: one point every
     6 cm is right for the long back locks (0.12 cm) and 1.28 cm off on the fringe, which curls. The fewest
     points that keep a lock within 0.25 cm are 4 to 15 a lock (543 on Helen), within 0.1 cm 6 to 22 (760).
   - So the points are not the spine (decision 2): as handles their number costs no accuracy (the measured
     spine is kept exactly at any K) and only sets how local a drag is: one handle's move reaches two
     handles to each side, the whole lock at K = 5.
   - Storage takes any count per lock (the array's length). A redrawn curve is stored with as many points
     as keep it within 0.25 cm of the stroke (4 to 15 on curves like Helen's).
4. **Shots.** Builds on the shot check t56 (2026-11-13; the plan's "session 019" check is not named in the
   plan or the notes: t56 has its scope, and that it is the same check is the spike's reading). Measured on
   copies of t56's sh020 / sh025 scenes, output 1 per frame, a fringe lock and the longest back lock, their
   spines bent 2 cm, 5 cm and turned 40 deg (`out/q3/q3_table.md`).
   - Point Deform leaves no point behind however far the hair is from the mesh (0 points, also 13 cm off
     it at a capture radius of 2 cm), and the roots stay on the animated scalp (0.001-0.059 cm, as unedited).
   - Where the lock's mesh piece moves rigidly in the shot, edited hair follows exactly as unedited hair:
     strand length x 1.000 at 2 cm and 5 cm, x 1.001-1.003 for the back lock turned 40 deg (tips 52 cm away).
   - Where the piece itself bends in the shot, hair moved off it changes length with the distance: sh020's
     fringe, unedited x 0.978-1.034 over the frames; 2 cm off x 0.958-1.029; 5 cm off x 1.066-1.142; sh025's
     back lock turned 40 deg x 1.095 against x 1.059 unedited.
   - Other captures tried on the same strands (a 10 cm radius; the lock's own mesh piece only; captured
     where the strand lay before the edit): none is better on both shots (before-the-edit gives the unedited
     numbers on sh025's back lock, x 1.063, and shrinks sh020's fringe 8-10 %; a 10 cm radius is the mildest
     on sh020's fringe, +2 to +6 %, and changes nothing on sh025). v0.1's deform stays as it is.
   - A drawn lock (no mesh, 3.0-4.6 cm from the nearest hair mesh) following the hair mesh as the node does
     now: its roots leave the animated skin by 3.0-4.5 cm on both shots and its strands stretch x 1.39-1.41
     on sh025. Following the scalp (Point Deform captured on the rest scalp at the node's 2 cm radius,
     deformed by the animated scalp): strand length x 0.996-1.007, roots 0.035-0.058 cm from the animated
     skin. The node has no animated scalp input: U2.
5. **A lock drawn on bare skin.** Prototype (`t76_drawn.py`): a stored curve from the skin, a width, a
   thickness and a tip taper become one more spine prim (49 points, the frame carried from "across the lock,
   on the skin" at the root, `piece` -1, its own lock id).
   - Stored only, it is a spine that grows nothing (it owns no skin; 0 strands, no error). After Update
     regions (run on the spines AFTER the edit and draw steps) its region is its footprint: 27 prims,
     0.82 cm2, all within 0.99 cm of the root (0.5 x the 2 cm width), taken from the two locks that owned
     that skin (-61 and -62 strands; they and the new lock recook, 0.34 s).
   - It grows 141 strands = density 150 x its cross-section (141.4; its skin alone asks 122.5), roots on the
     skin, strand points p50 0.28 / p95 0.64 cm from the curve, hair width 0.84-0.87 of the set width and
     thickness 0.95-1.03 of the set thickness at four stations; survives save / reopen.
   - The per-lock loop needed no change: `region_join`, `region_start`, `root_place`, `fit_to_lock` (its
     ellipse for "no mesh for this piece"), `surface_keys` and `lock_keys` have a no-piece path. One warning
     (`piece_cloud: Input has no packed primitives`) wants a switch.
   - The build must add: the node that makes the spine with the lock's own resolved settings (the prototype
     copies a neighbour's); `split_regions` reading the spines after it; Detect leaving `source` "drawn"
     alone (today a lock with no piece goes to Missing locks; not tested, the prototype kept drawn locks
     outside `groom_data`); mesh display, `lock_infos` and the QC's mesh checks without a mesh; a drawn
     lock's own points as its control points (in the prototype the draw step came after the edit step, so
     an edit on a drawn lock did nothing).

**Decided by the user 2026-11-20 (U1-U4; the options and the numbers that led to each are kept).**
- **U1. How many handles a lock shows.** (a) 5 for every lock: a drag reaches the whole lock, also on a 90 cm
  one. (b) By length, one every 8 cm, at least 4 and at most 12 (Helen: fringe 4-5, the longest 12).
  (c) The artist sets the number per lock. The spike recommended (b).
  **Decided: (c), the artist sets the number of handles per lock.** The manager's reading of that answer (not
  the user's words): a lock starts with rule (b)'s number; a number set for the lock in the panel overrides
  it and is kept in `groom_data` with the lock; changing the number on an edited lock keeps the edited shape
  (the stored moves are re-sampled onto the new handles).
- **U2. What a drawn lock follows in a shot.** (a) A new input "Animated scalp" on the node (contract: a
  fourth input; measured: length within 0.7 %, roots within 0.06 cm of the skin). (b) The nearest hair mesh,
  no contract change (measured: roots 3-5 cm off the skin, strands x 1.4 on sh025). (c) Drawn locks stay out
  of v0.2b's shots: at rest with a message.
  **Decided: (a), a fourth input "Animated scalp" (a contract change: the node's inputs are scalp, hair mesh,
  animated hair mesh, animated scalp).** Not wired: a drawn lock stays at rest in a shot, with a message on
  the panel's line and no error.
- **U3. A drawn lock and the frozen regions.** It has no hair until it owns skin, and owning skin takes it
  from its neighbours. (a) Draw gives the new lock its footprint in the same undo step and says which locks
  gave skin (only those recook; measured: two locks, 61 and 62 strands). (b) v0.1's rule as written: the
  lock shows as a guide and "Regions out of date" until the artist presses Update regions.
  **Decided: (a): Draw gives the new lock its footprint in the same undo step, and the message names the
  locks that gave skin.** A moved root keeps v0.1's rule (regions out of date, reason "a root moved").
- **U4. Edited locks where the mesh bends in the shot** (4 above): accept v0.1's deform with the measured
  limit, or ask for a capture choice per shot.
  **Decided: v0.1's deform is accepted for v0.2b, with the limit as measured: hair 2 cm off a mesh that bends
  stays within 2 points of the unedited lock's strand length, 5 cm off it is 7-14 % longer (sh020's fringe),
  the 90 cm back lock turned 40 deg 9.5 % against 5.9 % unedited (sh025).** It is judged on flipbooks at the
  User look gate, so the build's shot check makes flipbooks of the deformed frames of an edited lock.
- **U5. A root's first move snaps it onto the skin** (the measured root of a lock sits on the middle of its
  mesh's root edge, 0.08-0.5 cm over the skin on the six fringe locks tried): the alternative is to keep
  that height while it slides. Not asked; it stays as the plan says: on the skin.

**Still OPEN (why).**
- What an edit means under a new hair mesh version: the stored points are places in the lock's root frame,
  so the lock keeps its edited shape at the handles and takes the new mesh's shape only between them;
  storing the moves instead would take the new shape and push it the same way. Not measured: there is no
  second mesh version of Helen in the sandbox. The plan's wording (places) stands until one is tried.
- The Edit state's own drag by script (1 above): not measurable the two ways tried. Not to be chased (the
  manager, 2026-11-20): the choice of our own state does not rest on it.
- The carried mesh, QC on an edited groom, publish and read-back of edits and drawn locks, an edit under
  density layers, a control-point edit on a drawn lock, the redraw and rotate / scale gestures: not
  prototyped; each is a "Done when" item.

**Design gate (t78, 2026-11-20; mockups in `sandbox/.../tests/t78_redraw_mockups/`). Decided by the user.**
- **Mockup B**: a Tool bar at the panel's head (Select / Edit points / Draw lock / Paint) and under it a strip
  with the settings of the tool in hand (drag mode Move / Rotate / Scale / Redraw, Handles `auto (N)` with
  minus / plus, Reset, Done). One tool at a time shows in one place; Paint is entered from the same bar.
- **The word "edited"** on a row and as a filter word means the lock's SHAPE was edited. A lock with its own
  settings keeps its grey dot; its filter word becomes `own`. A drawn lock's row says `drawn`.
- **A drawn lock's group**: the group of the lock that gave it most skin (it resolves that group's settings);
  named `drawn_NN`.
- **Deleting a drawn lock** gives its skin back to the neighbours in the same undo step, and the message names
  the locks that took it (as Draw, U3).
- Left as mocked unless the user's try says otherwise (the manager's call, 2026-11-20): `edited` in the
  update blue and `drawn` in the "new" violet; keys Enter (Edit points), R / E / Shift + drag (rotate, scale,
  redraw), minus / plus (handles), the wheel for a new lock's width; Draw lock stays on for the next lock;
  Reset on a drawn lock returns the curve as drawn, and a drawn lock whose points were moved is also
  `edited`.
- **Paint's way in** (the user to the mockup session, 2026-11-20): the Tool bar's Paint cell REPLACES the Paint
  button in a paint layer's Properties (one way in). The cell is usable with one paint layer selected, else
  dimmed with the reason in its tooltip. B4 builds from `t78_redraw_mockups/b_toolbar.html` plus `review_b.md`
  there (status colours, Done, Reset, Edit points with no lock selected, a click on hair in the viewport
  selects that lock); where the two differ the review wins.

**After B1's independent check (t80) and B2's interim report (t79); the manager, 2026-11-21.**
- **The curve as drawn is kept** beside the moved one: `Lock.drawn_curve`, set by `add_drawn_lock`, saved
  with the lock (no schema step: absent = the curve). `Lock.edited` is true for a drawn lock whose `curve`
  differs from it; Reset puts `curve` back.
- **At most 12 handles everywhere** (U1): a redraw and a drawn stroke take the fewest handles within
  0.25 cm up to `HANDLES_MAX`; `STROKE_HANDLES_MAX` goes. A stroke 12 handles cannot hold is still taken
  and the message says how far the lock lies from it (t80: a straight redraw stroke needed up to 22).
- **One rule for a handle count out of range**: clamped to 4..12, on load too (t80 N2: a stored 13 became
  "by length").
- **Handing an orphan's state to a lock** replaces that lock's shape edit only when the orphan has one
  (t80 N5: an orphan without an edit wiped the target's).
- **A drawn lock's handle count** changes by a public function that refits its curve (t80 N6); same
  message rule as a mesh lock.
- **Garbage stays out of the cook** (t80 D3-D5): a zero or non-finite axis / factor leaves the handles as
  they are; a stroke with a non-finite point raises; a drawn lock with a non-finite or zero-length curve is
  refused; a loaded `source` outside `config.LOCK_SOURCES` reads as mesh.
- **A density layer naming only a deleted drawn lock** stays, with no lock (t80 N4); B4's row says so.
- **The shot deform of an edited lock** keeps its capture on the rest hair mesh (U4, v0.1's deform); the
  carried mesh is for display, regions and QC.
- **B4 as built (t82, 2026-11-22)**: the `edited` / `drawn` row words are neutral, not blue / violet (the
  mockup's review wins over "left as mocked"); the strip's handle count is the adapter's (`lock_handles`); in
  the radial menu Scalp X-ray moved into Display to free a slot for Draw lock; "Skin from" shows only for a
  lock drawn in this session (not stored).
- **Limits are not moved to pass** (s3 drawn lock stretch 2 %, s5 unedited groom in shots): a failing
  number is traced to its cause first, with the v0.1 locks beside it on the same shot as the baseline.

**Build, split by files** (U1-U4 are answered above; the panel waits for its mockup pick).
- **B1 Model and logic**: `tools/fx/grooming/model.py`, `logic.py`, `config.py`, their pytest files. Schema 7
  (`Lock.spine`, the lock's own handle count (empty = the default by length), a drawn lock's curve, width,
  thickness and taper, the same on `Orphan`), `migrate()`, `reassign_orphan` handing the edit on; pure
  functions: root frame to and from world, the interpolation rule (the same numbers as the VEX), the default
  handle count (one every 8 cm, 4 to 12), re-sampling stored moves onto another number of handles, rotate /
  scale about the root, a stroke to control points within a tolerance, reset.
- **B2 Network and adapter**: `tools/fx/grooming/build_hda.py`, `apps/houdini/grooming_adapter.py`,
  `otls/mono_grooming.hdalc`, `tests/houdini/grooming/accept_v02b.py`. `cook_assign` writes `edit_cp`; the
  nodes `spine_edit` and `drawn_locks` after `root_skin`; the carried mesh and its readers; `split_regions`
  and `lock_infos` after the edit; Detect and drawn locks; the `piece_cloud` switch; the adapter functions
  the state and the panel call (handles of a lock, set its handle count, set / reset / transform its points,
  draw and delete a lock, each one undo step named "MONO Grooming: ..."); Draw giving the lock its footprint
  in the same undo step and returning the locks that gave skin (U3); the publish record and its read-back.
  The fourth input "Animated scalp" (U2; `min_num_inputs` stays 2, `max_num_inputs` 4, its label, the same
  unpack of a packed USD input as the animated hair mesh): drawn locks are captured on the rest scalp at
  `deform_radius` and deformed by it; not wired, or with another point count than the rest scalp, they stay
  at rest and a `deform_problem`-style sentence says so for the panel. The contract's input list in
  `grooming_v0_1.md` changes in the same commit. The shot check's flipbooks of an edited lock (U4).
- **B3 Viewer state**: new `apps/houdini/grooming_points_state.py` and `tools/fx/grooming/points_keys.py`
  (its pure part, as `brush_keys.py`), a few lines in `grooming_paint_state.py` (one tool at a time),
  `tests/houdini/grooming/accept_v02b_gui.py`. From the prototype `t76_state.py`: handles with X-ray, drag
  on the view plane, the root on the skin, several locks, the redraw and rotate / scale gestures, Esc and
  "another node selected" as Paint has them.
- **B4 Panel**: new `tools/fx/grooming/spine.py` (controller mixin) and `ui_spine.py`, both LF; hooks only in
  `controller.py` / `ui.py` (CRLF); `workspace.py` and the radial menu file for the new entries; pytest.
  After the design gate (mockups, the user picks): the Edit points tool, the lock's number of handles (U1),
  "edited" on the row, Reset, Draw lock with width and thickness (its message names the locks that gave skin,
  U3), delete a drawn lock, the line that says a drawn lock stays at rest without an animated scalp (U2).
- **B5 QC**: `.claude/skills/grooming-check/scripts/qc_metrics.py`. Mesh checks against the carried mesh;
  drawn locks left out of the mesh checks and counted in density.
- Order: B1 first (it fixes the field names). Then B2 and B3 side by side (different files; B3 runs on the
  prototype's parm until B2's functions land) with the mockups. B4 after the pick and B2. B5 after B2.

**Done when** (Helen; each line is one check of `accept_v02b.py` or `accept_v02b_gui.py`).
- No edit and no drawn lock: every lock's strand count and every point equal the build before v0.2b in one
  session; the QC numbers are t55's.
- A schema 6 scene opens unchanged; the data is rewritten as schema 7 only by the next edit.
- Control points equal to the measured ones move no strand point more than 0.001 cm.
- One control point moved recooks only that lock, within 0.2 s a lock + 0.1 s, on hair_base_20 (most
  strands), hair_back_20 (longest) and five fringe locks at once.
- After a 2 cm tip move, strand points lie within 0.3 cm (p95) of the same bend carried; after a 25 deg
  turn about the root, within 0.5 cm (p95).
- After both, the strands' spread across the width and the thickness at 0.3 / 0.5 / 0.7 / 0.9 of the lock
  is within 10 % of the unedited lock's.
- The mesh display of an edited lock shows its mesh on the edited spine (each mesh point within 0.01 cm of
  the carry rule).
- grooming-check passes, with its limits unchanged, on a groom with a moved, a rotated and a redrawn lock.
- A dragged root is on the skin (within 0.001 cm) at every event of the drag and after the cook; a root
  never moved is the measured root.
- A moved root marks regions out of date with its reason; Update regions gives the lock its footprint at
  the new root.
- One drag is one undo step: one undo returns the node's data to before the drag in under 0.1 s with no
  lock regrown; redo returns the edit.
- Rotate about the root, scale about the root, redraw, reset, draw a lock, delete a drawn lock: one undo
  step each.
- With several locks being edited, one drag moves the same handle of each, in one undo step.
- A redrawn lock's spine lies within 0.25 cm of the stroke drawn.
- Reset returns the lock to its measured spine exactly, from the cache (no lock regrown).
- A lock shows the default number of handles for its length (one every 8 cm, at least 4, at most 12) until
  a number is set for it; the set number is kept with the lock through save / reopen and Detect.
- Changing the number of handles on an edited lock keeps its shape: the spine after the change lies within
  0.25 cm of the spine before it (`config.RESAMPLE_TOL_CM`; set by the manager 2026-11-20 from B1's t77:
  5 -> 8 -> 5 on Helen's spines 0.017-0.058 cm a step, 0.22 cm on the 89.6 cm lock turned 25 deg; the first
  0.1 cm was not measured). Fewer handles cannot hold every edit: past the limit the change is still made
  and the message line says how far the spine moved. Read with t80's numbers (61 spines): more handles
  holds a tip move (worst 0.12 cm) and most turns (0.51 cm worst, 2.3 % over); fewer handles often does
  not (12 -> 4 after a 2 cm tip move: 1.46 cm). The acceptance check names the edits it tries: 5 -> 8 -> 5
  after a tip move and after a 25 deg turn within the limit, and one 12 -> 4 case whose message must give
  the true distance.
- A lock drawn on bare skin grows density x max(its skin, its cross-section) strands within 15 %, roots on
  the skin, hair width within 20 % of the set width at four stations, no error or warning on the node.
- Draw is one undo step that also gives the lock its footprint (0.5 x its width round its root): it has hair
  at once, only the locks that gave skin recook, the message names them, and one undo takes the lock and
  the region change back.
- Detect leaves a drawn lock alone (not missing, not "new"); it can be deleted; its id is never reused.
- Edits and drawn locks survive undo / redo, save / reopen, Detect and Update regions.
- A missing lock keeps its edit; `reassign_orphan` gives it to the lock that takes its place.
- Publish writes edits and drawn locks into the publish JSON; read back into a fresh node they give the
  same hair (0.003 cm).
- Control points and Paint: entering one ends the other; Esc, another node selected, the node deleted and
  File > New leave the tool with no traceback.
- In the GUI by scripted events: a fringe lock moved, one rotated about its root, one redrawn, one new lock
  drawn on bare skin, with flipbooks before and after each.
- The panel shows "edited" on the row of an edited lock and offers Reset (the picked mockup; offscreen
  grabs and the contrast check as the panel rules ask).
- Shots (sh020, sh025): an edited lock leaves no point behind, its roots stay on the animated scalp as the
  unedited lock's do, and for a move of 2 cm its strand length stays within 3 points of the unedited lock's
  at every frame checked.
- Shots: flipbooks of the deformed frames of a lock moved 2 cm and 5 cm, beside the unedited lock, for the
  User look gate (U4: the look is the user's to judge, the check only makes the pictures).
- Shots, "Animated scalp" wired: a drawn lock's strand length stays within 2 % and its roots within 0.1 cm
  of the animated skin at every frame checked.
- Shots, "Animated scalp" not wired (or with another point count than the rest scalp): a drawn lock stays
  at rest, the panel's line says why, no error on the node; the mesh locks deform as before.
- A scene with three inputs wired (every scene before v0.2b) opens and cooks as before.
- The user's own try with a mouse or pen is the User look gate.

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

## v0.2a, last task: the tool's own workspace and pie menu (asked by the user 2026-11-13)

A place of its own for grooming, so the artist does not rebuild a layout or hunt for commands. Built
after the mask panel, since the pie menu's entries are that panel's commands. One session.

**What.**
- **Desktop "MONO Grooming"** (a `.desk` file in the suite's `desktop/`, listed next to Build): a large
  viewport, the Grooming panel docked on the right, a small network editor, the shelves that do not
  matter here hidden. The user's other desktops are not changed.
- **Radial menu "MONO Grooming"** (a file in the suite's `radialmenu/`, listed next to Main, key C in the
  viewport): Paint / Erase, Guides / Hair preview / Hair, Isolate the selected locks, Scalp X-ray, Update
  regions, Detect locks. Each entry calls the same controller function as the panel's button (no second
  code path). In the Paint state: brush hotkeys and a right-click menu (radius, value) belong to the
  viewer state.
- Installer: `MonoFXSuite.iss` ships `desktop/` and `radialmenu/` (in the same change).

**Paint state like Attribute Paint (decided 2026-11-19, built in this task).** The user looked at Houdini's
Attribute Paint and asked for the same in our Paint state:
- (a) a hint overlay (HUD) in the viewport, top left, listing the keys and the current brush values (radius,
  softness, grey, paint / erase); Houdini's own Shift+F1 hides it, like every state's hints;
- (b) a parameter bar above the viewport with Radius, Softness, Grey and Eraser, two-way with the panel's
  Properties: one source, `grooming_masks.BRUSH` through `set_brush`; a change on either side shows on the
  other, with no feedback loop; a brush change is view state (no undo step, no cook);
- (c) the mouse wheel and Ctrl+Shift+LMB drag change the radius;
- (d) F swaps paint / erase; Ctrl+LMB (erase while painting) and Esc (leave) stay.
- Not in this task: smooth (Shift), sample a value, pen pressure, mirror. They are new mask features, a later
  part.

**Spike (ANSWERED 2026-11-19, t72, Houdini 22.0.466 in GUI on its own `HOUDINI_USER_PREF_DIR`; sandbox
`tests/t72_workspace_paint/spike/`).**
1. Radial menu by script: YES, through `hou.ui._getActiveRadialMenu()` / `hou.ui._setActiveRadialMenu(name)`
   (underscore: not documented, present in H22's `hou.py`; set and read back `t72spike`, then `main` again; no
   pref file written). A `.radialmenu` in a HOUDINI_PATH folder's `radialmenu/` is listed by
   `hou.ui.radialMenus()`. A desk's `radial menu set <name>` line also switches it, but switching back to Build
   left ours on: a desk does not put the user's back. So the PANEL switches it: shown -> ours (the user's
   remembered), the last panel hidden (closed, or its desktop left) -> the user's, unless they picked another
   meanwhile. Fallback kept for a build without the calls: the panel says once to pick it by hand.
2. `.desk` with the Python panel: YES. A hand-written desk in a HOUDINI_PATH folder's `desktop/` is listed
   (`hou.ui.desktopNames()`), and its `pythonpanel -n mono_grooming` tab opens our interface on a fresh pref dir
   (the stand-in for another machine), provided `python_panels/mono_grooming.pypanel` is on HOUDINI_PATH: it
   moved from `tools/fx/grooming/` to the suite root's `python_panels/` (Houdini loads it at start; Dock still
   installs it by path). Build update: the desk is the same plain hscript SideFX's own desks use
   (`SolarisLookDev.desk` names four Python panels the same way), written by hand, not saved by a build, so
   nothing build-specific is in it; a missing interface leaves an empty Python Panel tab, not an error. No
   shelf-tool layout.
3. Viewer state API in H22 (docs `hom.zip`: state_parameters, hud_info, state_events, state_menus): the
   parameter bar (`bindParameter`, the "Operation Toolbox" above the viewport) and the HUD (`hudInfo(template=)`
   then `hudInfo(values=)`, "Press Shift+F1 to hide hints" drawn by Houdini) work; a flipbook does NOT include
   either (they are Houdini's UI over the GL view): pictures of them are offscreen grabs of the main window.
   Writing a state parm from code (`_setCurrentStateParm`, or the `state_parms` dict kept from `onEnter`) calls
   no `onParmChangeEvent` (no loop); a write from `onMouseEvent` does not reach the bar (read-only callback, as
   documented), so the state writes the bar deferred. `onMouseWheelEvent` gets +-1 a notch; consumed (True)
   the camera does not move (a synthetic wheel moved it in neither case, so the camera's own wheel is the
   user's to try). Ctrl+Shift+LMB reaches `onMouseEvent` with both modifiers, the camera does not move. F:
   `bindHotkeyDefinitions` + a menu item with that hotkey -> `onMenuAction("swap")`, and Houdini's own F
   (frame) is not run; `onKeyEvent` still sees "f" first and must not consume it. RMB opens the state's
   `bindMenu` menu (`onMenuPreOpen` called; it is Houdini's own menu, not a Qt one). A synthetic wheel reaches
   the state only when sent to the viewport's `RE_Window` widget (the GL widget's grandparent).

**Built (2026-11-19, t72).** `desktop/MONO_Grooming.desk` (viewport 70 % left; right: the MONO Grooming panel
with a Parameters tab, network editor under it; the shelves as Build has them: hiding shelves per desk was
not done, see the t72 report), `radialmenu/mono_grooming.radialmenu` (made from `tools/fx/grooming/workspace.py`
`ENTRIES`; a test holds the file to it: Paint top, Erase top right, Scalp X-ray right, Update regions bottom
right, Detect locks bottom, Isolate bottom left, Display submenu left with Guides / Hair preview / Hair; check
marks on the toggles), `python_panels/mono_grooming.pypanel`; the installer ships the three folders. Each entry
is `apps/houdini/grooming_workspace.radial(entry)` -> `workspace.run(controller, entry)` -> the controller
function the panel's button fires; without a panel a controller on the scene's node reports to the status
line; with no node the status line says so. Paint state: `tools/fx/grooming/brush_keys.py` (HUD rows and values,
bar, wheel x1.1 a notch, drag x2 every 120 px right, menu: Paint / Erase (F), Radius smaller / larger / 0.25-4
cm, Grey 0 / 0.5 / 1) bound by `grooming_paint_state.py`; every change goes through
`grooming_masks.set_brush(source="state")`, whose `HOOKS["brush"]` tells the panel (shown on its next poll,
400 ms), and a change made in the panel does not come back.

**Checked (t72, GUI by script, `tests/t72_workspace_paint/report.md`).** Desktop from the list on a fresh pref
dir (viewport, panel `mono_grooming` on the node, network editor), back to Build unchanged, radial menu ours while
the panel is shown and the user's after; the 9 radial entries leave the node as the panel's own widgets do; with
no node they say so; the Paint state's HUD, bar and the panel agree after a change from the panel, the bar, the
wheel, a Ctrl+Shift drag, F and the menu, each with no undo step and no cook, and a stroke after each moves the
right way; strokes 0.21-0.35 s (limits 0.9-1.5 s), undo 0.04-0.05 s with the HUD on; Esc, another node, the node
deleted, File > New while painting: no traceback, bar gone. The installer log holds the three folders;
`accept_v02a_gui.py` 19 / 19. Left for the User look gate: a real hand on the wheel, drag, F, bar and menu, the
pie menu with C, the layout; not built: hiding shelves per desk (needs a shelf set and the user's choice).

**Spike first (the questions as asked, 2026-11-13).**
1. Can the tool switch the viewport to its radial menu when the panel opens and put the user's back when
   it closes, by script, in Houdini 22? If not: the user picks it in the menu, and the panel says so once.
2. Does a `.desk` file keep the Python panel (by its interface name) on another machine and survive a
   Houdini build update? If fragile: build the layout by script from a shelf tool ("Grooming workspace")
   and ship no `.desk`.

**Done when.**
- From a fresh Houdini with the suite installed: the desktop is in the list, choosing it shows the
  viewport and the docked panel on the node in the scene (checked by script: pane types and the panel's
  interface); switching back restores the earlier desktop unchanged.
- Every radial entry does what its panel button does (same resulting node state, checked by script for
  each entry); none raises when no MONO Grooming node exists (a status line message instead).
- The installer build contains both folders (ISCC log).
- The user's own try of the pie menu and the layout is the User look gate.

## Not in v0.2 (later, when production needs it)

Several characters in one shot, batch over shots, shot mode reading a publish; colour layers and
melanin; Karma live preview; custom team effects; Unreal export; sim and body collision. The cut
lines decided for these in `grooming_v0_1.md` (cache paths per character and instance) stay.

## Before v0.2a starts

Session 019 checks v0.1's shot deform and whether caching per shot exists (v0.1 item 8). What it
finds is v0.1(.x) work and goes first; v0.2b's shot checks build on it.
