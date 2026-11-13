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
share). Each layer: name, enabled, opacity, blend mode, scope (all locks, a group, or chosen locks) and
a painted value per scalp point. Blend modes: Multiply (default, 1 = unchanged), Add, Subtract,
Replace, Min, Max. Final density at a root = automatic density through the layers from bottom to top,
never below 0. Roots are placed from the final density (v0.1 root spread unchanged: even at the
density, so painting 0.5 halves the roots there, evenly, not in patches).

**Where in the order.** settings applied -> region split -> **masks** -> cache key per lock -> hairgen.
The key of a lock includes a digest of the final density on its region, so a stroke recooks only the
locks under it.

**Storage.** Per scalp point float attributes `mask_<n>` in a hidden geometry parm (as `regions`),
layer list (name, mode, opacity, scope, order) in `groom_data`. A new scalp topology transfers the
layers by UV, with a warning.

**Spike (OPEN until it runs).**
1. Painting inside a locked HDA: Houdini's Attribute Paint state on an editable node inside the HDA,
   versus our own Python viewer state (brush radius, value, soft edge, stroke = one undo step). Pick the
   one that paints at the frame rate on Helen's scalp (24k prims) and keeps undo per stroke.
2. Showing the mask while painting: scalp coloured by the layer's value, hair in preview.
3. Hairgen with a density attribute versus scaling our own root scatter: the root spread is ours, so
   expected: our scatter reads the final density; check it stays even (`root_spacing_low`).

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
