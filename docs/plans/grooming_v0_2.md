# MONO Grooming v0.2 (plan; decided 2026-11-13, not built yet)

v0.1 (released in MonoFX Suite v0.1.25, contract in `grooming_v0_1.md`) makes the whole groom
automatically from the hair mesh. v0.2 lets the artist change that result where it is wrong, on top of
it: the automatic groom stays the base layer and every v0.2 edit is a layer over it, never a second
system beside it (v0.1 plan, "Not in v0.1").

The v0.1 known issues (crown denser than v006, thin skin under floating mesh, a few strands outside
their lock) are answered here by edits the artist makes, not by more tuning of the automatic rules.

## Order: three parts, each released on its own

| Part | What the artist gets | Why this order |
|---|---|---|
| **v0.2a Density masks** | Paint more or less hair on the scalp, in layers with blend modes (Substance Painter style); the tool's own workspace and pie menu | Fixes most known issues (crown, thin skin) with the least new machinery; the layer system is reused by b and c |
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

## v0.2a Density masks

**What.** A stack of mask layers on the scalp, above the automatic density (density setting x region
share). Each layer: name, enabled, opacity, blend mode, scope (all locks, a group, or chosen locks) and,
per scalp point, a painted value and a coverage (0 = not painted there, the soft edge of a dab lies
between). Blend modes: Multiply (default), Add, Subtract, Replace, Min, Max. Final factor at a point =
1 through the layers from bottom to top, each as `m + (blend(m, value) - m) x coverage x opacity`, never
below 0 (decided by the spike: with a coverage, skin not painted is left alone in every mode; one value
per point would need a different "unpainted" number per mode). Final density = automatic density x that
factor. Roots are placed from the final density (v0.1 root spread unchanged: even at the density, so
painting 0.5 halves the roots there, evenly, not in patches).

**Where in the order.** settings applied -> region split -> **masks** -> cache key per lock -> hairgen.
The key of a lock includes a digest of the final factor on its region, so a stroke recooks only the
locks under it.

**Storage.** Per scalp point float attributes `mask_<id>_v` / `mask_<id>_a` in a hidden geometry parm
`mask_layers` (as `regions`), layer list (id, name, on, mode, opacity, scope, order) in `groom_data`.
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

**Build (proposed from the spike).**
- Data: `groom_data.masks` (list, bottom first: id, name, on, mode, opacity, scope), `schema` +1 with a
  migration; hidden geometry parm `mask_layers` (points of the fine scalp: `P`, `uv`,
  `mask_<id>_v`, `mask_<id>_a`). Both written in one undo group a stroke; neither goes into the shared
  part of the cache key (`_KEY_SKIP_PARMS`: a string parm in it recooked all 61 locks on the first stroke).
- Network: `mask_read` (Python SOP on `SCALP_FINE`, numpy blend -> point `mask`), point and prim `mask`
  on `SCALP_REGIONS`; `PREVIEW` counts `density x area x mask` and its `region_keys` take the mask;
  `region_frame` counts strands on the masked area (`lock_strands x masked area / area`, so a lock
  painted 0 everywhere grows nothing, floor included); `region_density` x the point's mask; `root_pick`
  keeps a start place by the chance of the mask there; the same in the `groom_` loop (`_copy_loop`).
- Paint: our viewer state in `apps/houdini/` (entered from the panel's Paint; `onGenerate`, since it is
  entered by name), a `SimpleDrawable` of the scalp recoloured from a copy a dab, a ring for the brush,
  write on release, the cook inside the controller's `_busy`. Selecting the node again makes Houdini
  enter the node's own state and drop ours (the spike lost its strokes to this): bind it as the HDA's
  state, or re-enter while Paint is on.
- While Paint is on the panel shows Hair preview (or Guides) and the scalp's X-ray toggle.

**Not sure yet (settle in the build, in this order).**
1. Skin under floating mesh: a root there moves to the lock's start by `far_w` whatever the mask, so
   painting that skin up mostly feeds the start. Proposed: the automatic share moves, what the mask adds
   above 1 stays (chance `far_w / mask`). Not tested; the done-when item "thin skin painted up" depends on it.
2. Scope: a layer for a group or chosen locks means a factor per lock, not per point. Proposed: one
   blended attribute per distinct scope set, each lock reading its own. Not prototyped.
3. The region digest: 9 sums a lock (the spike added the mask to two of them). A stroke that moves
   density inside a region without changing those sums would be missed; hash the lock's own mask values.
4. The brush measures straight distance (24.5 k points, 0.3 ms): a dab near the ear reaches skin behind
   it. Limit it to skin connected under the brush, facing the same way.
5. Whorl roots do not read the mask yet. UV transfer to a new scalp is untested. A hand-held brush
   (pen, hotkeys, radius drag) was not tried by a person.
6. v0.1, found here: with an anim wired, output 1's key differs from the display's (`do_capture`) and
   both use the lock's two cache slots, so once something reads output 1 an undo regrows the locks
   (0.65-1.5 s instead of 0.04 s). Give the capture its own slot, or keep 3.

**Panel.** A Layers section (list, eye, blend mode, opacity, scope), Paint / Erase with radius and
value, Fill and Clear for a layer. Mockups first.

**Done when.**
- Painting 0 removes every root under the stroke; 2 doubles them there; the roots stay even
  (`root_spacing_low` and `root_clumped` pass inside painted areas).
- On Helen: the crown painted down to v006's density (~5,100 / cm2) and the thin skin under floating mesh
  painted up, both in the GUI by scripted strokes, with the QC numbers before and after in the report
  (the user's own try with a mouse or pen is the User look gate).
- A stroke recooks only the locks under it, at most 0.2 s per lock plus 0.1 s; undo removes exactly
  that stroke, in under 0.1 s and with no lock recooked, also with an anim wired and output 1 read
  (the v0.1 fault of "Not sure yet" 6 is fixed in this part, as its own commit).
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

**Spike first (OPEN).**
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
