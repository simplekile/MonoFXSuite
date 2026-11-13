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
| **v0.2a Density masks** | Paint more or less hair on the scalp, in layers with blend modes (Substance Painter style) | Fixes most known issues (crown, thin skin) with the least new machinery; the layer system is reused by b and c |
| **v0.2b Lock redraw** | Move a lock's control points, redraw its curve, draw a new lock where the mesh has none | The plan's reserved slot (after spine and measure); changes shape, not density |
| **v0.2c Brush** | Comb, lift, cut and length brushes on the hair in the viewport | Most work and the most risk (edits must survive recooks); comes last, on what a and b settle |

Each part: spike first (a hython / GUI test in the sandbox that settles the open questions below,
like t02 did for shots), then the build, then `grooming-check` passes plus the part's own checks, then a
MonoFX Suite release. A part is done when its "done when" list holds; no tuning past it inside the part.
Panels go through the skill `dcc-panel-design` (mockups the user picks from, before building).

## Rules for every part

- An edit is stored in the node (JSON in `groom_data`, or a hidden geometry parm like `regions` for
  per-point data), saved with the hip, one undo step per stroke or drag, and dirties only what it touches.
- Edits are keyed by `lock_id` (and scalp UV for painted data), so they survive Detect, Update regions
  and a new hair mesh version; an orphaned lock keeps its edits in `orphans`.
- Partial cook stays: an edit is part of the cache key of the locks it touches only (v0.1 "Partial
  cook"), so a stroke on one area recooks the locks under it, not the groom. Target on Helen: under
  1 s for an edit on one lock, as v0.1's slider edits.
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
  painted up, both by hand in the GUI, with the QC numbers before and after in the report.
- A stroke on one lock's region recooks in under 1 s; undo removes exactly that stroke.
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
