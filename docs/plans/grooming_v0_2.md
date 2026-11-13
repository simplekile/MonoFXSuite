# MONO Grooming v0.2 (plan; decided 2026-11-13; v0.2a core rebuilt in round 3 on one kind of layer, "= D"; panel and gates open)

v0.1 (released in MonoFX Suite v0.1.25, contract in `grooming_v0_1.md`) makes the whole groom
automatically from the hair mesh. v0.2 lets the artist change that result where it is wrong, on top of
it: the automatic groom stays the base layer and every v0.2 edit is a layer over it, never a second
system beside it (v0.1 plan, "Not in v0.1").

The v0.1 known issues (crown denser than v006, thin skin under floating mesh, a few strands outside
their lock) are answered here by edits the artist makes, not by more tuning of the automatic rules.

## Order: three parts, each released on its own

| Part | What the artist gets | Why this order |
|---|---|---|
| **v0.2a Density masks** | Paint the density on the scalp: layers "= D strands / cm2" with a mask, in folders (Substance Painter style) | Fixes most known issues (crown, thin skin) with the least new machinery; the layer system is reused by b and c |
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

## v0.2a Density masks

**What (round 3, decided by the user 2026-11-13 after two independent checks failed the blend modes).**
A stack of density layers on the scalp, above the automatic groom. ONE kind of layer: a fill layer
**"= D strands / cm2"** with a mask painted on the scalp (white: the layer applies; black: the skin returns to
the automatic groom; grey between), an opacity and an owner (all locks, a group, or chosen locks), plus
folders (one level) with a mask and opacity over their layers. Multiply, add, subtract, min and max, factor
values and layers with a value painted per point are removed: a grey mask or a lower opacity on a "= D"
layer, and the Density setting of a lock or a group, cover what they did.

**The rule.** Where layers cover the skin with coverage c (mask x opacity, through folders):

    density = automatic x (1 - c) + D x c            (`logic.mask_compose` -> keep = 1 - c, add = D x c)

"automatic" is what the groom has there without layers, relocated roots included (a whorl, a lock's start,
the thin skin under floating mesh), and "density" is every root on that skin, of all the locks that share it.
So painted D gives D whatever the lock is set to and whatever the tool did there before; painted black gives
the automatic groom back, root for root. Several layers run bottom to top, the upper one winning where it
covers: keep x (1 - e), add x (1 - e) + D x e with e its coverage. A folder blends what its layers make
through its own mask and opacity: x + (inside - x) x mask x opacity.

**Where in the order.** settings applied -> region split -> **layers** -> cache key per lock -> hairgen.
The key of a lock includes a digest of the layers' cover (keep, add) on its region, so a stroke recooks
only the locks under it.

**Storage.** Per scalp point one float attribute `mask_<id>_a` a layer (its mask) in a hidden geometry parm
`mask_layers` (as `regions`), layer list (id, name, on, density, opacity, owner, kind, parent, order) in
`groom_data`.
A new scalp topology transfers the layers by UV, with a warning.

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

**Build (core rebuilt in round 3, 2026-11-13, t62; the panel is a separate task). The spike above and the
numbered decisions further down are the first builds' history: where they speak of factors, blend modes or
paint layers they no longer hold.**
- Data: `groom_data.masks` (`model.MaskLayer`, bottom first: id, name, on, `value` (the density D), opacity,
  `scope` with its `group` or `locks` (the owner), `kind` "fill" or "folder", `parent`; the order is the place
  in the list), `mask_id_high` (a layer id is never reused). `schema` 4. Schemas 2 and 3 were never released:
  on reading (`model.migrate`) their layers of a removed kind (any blend mode but replace, factor units,
  paint layers) are dropped, "= D" layers and folders are kept; `model.dropped_masks` names them, OnLoaded
  says so on the status bar and `mask_dropped(node)` gives the panel the sentence; never a dialog, never a
  traceback. The JSON on the node is rewritten only by the next edit. A v0.1 scene opens with no layer.
  Hidden geometry parm `mask_layers`: the fine scalp's points with `P`, `uv`, `mask_<id>_a`; a layer never
  painted has no attribute. A stroke writes only `mask_layers` (the layer list did not change, and writing
  `groom_data` would recook the spines); a layer edit writes only `groom_data`; one undo group each. Neither
  is in the shared part of the cache key (`_KEY_SKIP_PARMS`).
- Network: `mask_read` (Python SOP in line after `region_prims`, `grooming_masks.cook_mask_read`) composes the
  layers per scope set in numpy into point attributes `mask_keep_<k>` / `mask_add_<k>` on `SCALP_REGIONS`,
  and writes the details `mask_sets`, `mask_set_of`, `mask_hash_of`, `mask_add_of` (by lock id) and the prim
  `mask_dens` (PREVIEW's expected strands). With no layer on it adds nothing, so the geometry and the groom
  are v0.1's. `lock_keys` gives each lock its `mask_set` and `mask_add_n` and puts the lock's digest in its key.
- Inside the loop the automatic groom is v0.1's own nodes, unchanged (`region_cut` ... `root_pick`,
  `root_place`): no layer reaches them. A lock a layer covers (`mask_set` >= 0, read by switches; the others
  never cook the new nodes) gets two more steps:
  1. `mask_thin`: each automatic root stays by the chance keep where it ENDS UP (`root_at`: a root the tool
     moved to the lock's start or a whorl is judged where it landed). The chance is drawn per root from its
     number in the automatic groom, so a small change of the mask removes or returns a few roots and moves
     no other.
  2. `hairgen_layers`: a second scatter on the lock's region by the layers' density there (`mask_skin`:
     add / share, on unshared points so a prim's corners carry its own share), as many roots as `mask_read`
     counted (`mask_add_n` = sum of add x area / share over the lock's prims). They join the automatic roots
     before `root_place` (`roots_with_layers`), are never relocated and never thinned.
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

**Why two sets of roots, and not one scatter by a density map (round 3).** The first builds multiplied
hairgen's density attribute by a factor and thinned the roots the tool relocates. Two checkers measured what
that gave: x2 was x1.08 on the whorl and x5.3 under floating mesh, "= D" ran 11-19 % short where relocated
roots dominate, a grey mask on the whorl reached D faster than its grey, and a leftover mask of 0.03 moved
every root of two locks by up to 20 mm (one scatter with a forced count re-places everything). Keeping the
automatic roots as they are and thinning them where they end up makes black paint the automatic groom
exactly, makes grey linear everywhere (measured, t62: 0.995-1.048 of the rule on ordinary skin, the crown
whorl and the top of the head), and leaves every other root in place when the mask changes a little.

**Adapter API added in v0.2a** (`apps/houdini/grooming_masks.py`, re-exported by `grooming_adapter`; each
function that changes something is one undo step named "MONO Grooming: ..."; the layer list itself is
`read_data(node).masks`).

| Function | Returns / does |
|---|---|
| `mask_add(node, name="", value=150.0, opacity=1.0, scope="all", group="", locks=(), kind="fill", parent=None) -> int` | New layer "= `value` strands / cm2" on top (or a folder), mask black; its id |
| `mask_remove(node, layer_id) -> bool` | Delete the layer and what is painted on it |
| `mask_move(node, layer_id, index, parent="keep")` | Put the layer at place `index` (0 = bottom), and into a folder (`parent` id, None = out) |
| `mask_set(node, layer_id, name=, on=, opacity=, scope=, group=, locks=, value=) -> bool` | Change the layer's row (`value`: its density); False (and no undo step) when nothing changed |
| `mask_fill(node, layer_id, value=1.0)` / `mask_clear(node, layer_id)` / `mask_invert(node, layer_id)` | The whole mask at `value` (1 = white mask) / no mask (black; a folder: none) / white <-> black |
| `mask_stroke(node, layer_id, points, radius_cm, soft, erase=False, normals=None, level=1.0) -> int` | One stroke through points on the skin, as the brush paints it: `level` on the mask (1 white, 0 black) |
| `mask_values(node, layer_id) -> mask` / `mask_cover(node, lock_id=None) -> (keep, add)` | Arrays per fine-scalp point: a layer's mask, or the cover (of one lock, or of the "all locks" layers): density = automatic x keep + add |
| `mask_dropped(node) -> str` | The sentence for the message line when the scene held layers of a removed kind ("" when none) |
| `paint_enter(node, layer_id) -> bool` / `paint_exit(node=None)` / `paint_layer(node) -> int \| None` | Paint on (the viewport's tool is the brush; False without a viewport) / off / the layer being painted |
| `set_brush(radius_cm=, soft=, erase=, xray=, view=, level=) -> dict` / `brush() -> dict` | Brush of the session (not saved, no undo): radius cm, soft share of the radius, `level` painted on the mask (1 white, 0 black; erase = black), scalp X-ray, `view` (density / layer / roots) |
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

**The layer model: Substance Painter's layer stack, with one kind of layer (the user, 2026-11-13).**
The first build painted a value per point, so the artist had to think "paint 0.5", could not tell what a
"mask" was, and could not see what the density really looked like; the second added fill layers with six
blend modes, of which only "= D" gave what it said (two checks, t60 and t61). The user then cut the model to:
- **Base**: the automatic density, shown as the bottom row, locked (not paintable, not movable).
- **Layer "= D strands / cm2"**: one number for the whole layer and an opacity. Changing the number is a
  panel edit, not paint. The panel's quick picks are densities (`config.MASK_DENSITY_PICKS`: 0, 40, 80,
  150, 300), never factors.
- **Mask**: each layer has one, per scalp point, 0..1. The brush paints it white (the layer applies) or black
  (it does not), with any grey between; a new layer's mask is black, so adding a layer changes nothing.
  White mask / black mask (`mask_fill` 1 / `mask_clear`), invert (`mask_invert`). Alt+click on a mask shows
  it alone (view "layer"), Shift+click switches it off for a moment (the panel's).
- **Folder**: holds layers (one level) and has a mask and opacity of its own over all of them
  (`logic.mask_compose`). A folder without a mask lets everything through; deleting a folder keeps its layers.
- **Owner** (`scope`: all locks / a group / chosen locks) stays per layer: it is Painter's Geometry mask. On
  skin several locks share, each owner a layer reaches grows D / share there, so a layer on All locks gives D
  in all. A layer owned by a lock follows the lock: when the lock goes missing and comes back as a new lock,
  giving the missing lock's settings to it (`controller.reassign_orphan`) moves the layer's ownership too.
- **Views** (`set_brush(view=)`): `density` the result, roots / cm2 counted from the cooked groom (so
  relocated roots are in it), moved while a stroke is down by what the layers ask now against what they
  asked when counted, and the density asked until the groom has been counted; `layer` (the mask alone, white
  on dark); `roots` (a dot a root on a plain scalp). No factor view: there is no factor. Choosing density or
  roots grows the locks the cache does not hold in full (Guides display: the whole groom once, ~12 s).
- Also from the user's try: Paint records no undo step of its own, and says so on the status bar when the
  layer being painted is undone; a stroke in Guides display grows no hair (the density view goes on from the
  last count); the painted colour is the final density map, no tint over it.
- Still open: the result is not shown as hair while the button is down (the density view moves, the hair
  cooks on release); a pen's pressure, radius by drag, mirror.

**Panel.** As Painter's layer stack: rows top to bottom with eye, name, the density ("= 80"), the mask
thumbnail (click to paint it, Alt+click to see it alone, Shift+click to switch
it off), folders with their own mask, the locked base row at the bottom; under it the selected layer's
density (quick picks: densities, not factors), opacity, owner, and the brush (white / black, radius, softness); over the viewport the view
choice (result / mask / roots) with the density ramp's legend. Mockups first (dcc-panel-design); the sketch
the user saw is described in the notes folder (`t58-mask-core.md`).

**Done when.**
- Painted D gives D: under a white mask of a layer "= D" the roots of all locks are D / cm2, measured
  on five or more kinds of skin (whorl, top of the head, lock starts, stacked skin, skin under floating mesh,
  fringe, ordinary) at D = 0, 40, 120, 300, within max(15 %, 2 / sqrt(D x area)); "= 0" removes every root;
  each lock's roots stay even there (clumped share on the lock's own skin). Black paint gives the automatic
  groom back by root positions. A grey mask or an opacity gives automatic + (D - automatic) x coverage.
- On Helen: the crown painted down to v006's density (~5,100 / cm2) and the thin skin under floating mesh
  painted up, both in the GUI by scripted strokes, with the QC numbers before and after in the report
  (the user's own try with a mouse or pen is the User look gate).
- A stroke recooks only the locks under it, at most 0.2 s per lock plus 0.1 s; undo removes exactly
  that stroke, in under 0.1 s and with no lock recooked, also with an anim wired and output 1 read, and for
  a whole chain of strokes (30 in a row, then 30 undos and 30 redos) while the undo cache holds them.
- No layers = the v0.1 groom: strand count and QC numbers as t55.
- Layers survive Detect, Update regions, save / reopen and Publish (read back from the publish JSON).

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
