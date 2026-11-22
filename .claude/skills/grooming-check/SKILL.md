---
name: grooming-check
description: Check the hair MONO Grooming makes before calling it good, with numbers and XGen-style shaded images, against an approved groom. Use it after any change to tools/fx/grooming (build_hda.py, the adapter, region or fit logic), before sending the user hair screenshots, before a commit or PR of the grooming tool, and whenever the user says the hair looks messy, tangled, sparse, spiky or "rối". Median distances and per-lock averages hid zigzag strands and half-bare meshes before; this check is what "the hair is fine" means.
---

# MONO Grooming hair check

Two scripts, both in `scripts/`. Run both: the numbers find problems a picture misses (a 150 deg
corner inside a dense lock) and the picture finds problems no number was written for yet (the
user's eye found the zigzags, the brush roots and the bare crown before any metric did).

Never open the real project. Use a scene in the sandbox (`E:/01 Dev/sandbox/claude/grooming/tests/`)
and write output only under `tests/<folder>/`. Reference groom for Helen (approved):
`E:/01 Dev/sandbox/claude/grooming/project_helen/01_assets/_characters/char_Helen/04_grooming/publish/v006/char_Helen_groom_publish.usd`.

## 1. Numbers (`qc_metrics.py`, hython, ~1 min)

```bash
hython .claude/skills/grooming-check/scripts/qc_metrics.py <suite> <scene.hiplc> <out_dir> --ref <groom.usd> [--fresh] [--mesh carried|modelled]
```

**Edited and drawn locks (v0.2b, 2026-11-22).** A lock whose shape the artist edited (control points, rotate,
redraw) is measured against its mesh piece CARRIED onto the edited spine (the node's `MESH_CARRIED`), not the
modelled piece it was bent away from on purpose; the mesh views and close-ups of step 2 show that carried mesh too.
`--mesh modelled` measures against the modelled mesh, for comparison only (Helen with three edited locks: carried
passes, modelled fails `tip_center_off_worst` 1.67 and `lock_outside_worst` 1.0; t83). The reference is always
graded on the modelled mesh. A lock drawn on the skin has no mesh: its strands are left out of every mesh number
(distance to the mesh, on another lock, coverage, width / start share / shape) and the report says so; it counts in
the shape checks, in density and in the skin, and its own section measures roots on the skin, strands against
density x max(its skin, its cross-section), and hair width / thickness at 0.3 / 0.5 / 0.7 / 0.9 against the set ones,
with two checks added only on a groom that has a drawn lock (`drawn_root_skin_worst_cm` 0.0025, `drawn_width_off_worst`
0.20, the plan's "Done when"). The report lists the edited locks with their mesh numbers. With no edit and no drawn
lock every number is the one before v0.2b (t55's 27, checked in t83 and by `accept_v02b.py` r2); q1 there checks an
edited groom.

`--fresh` empties the groom data and runs Detect and Split regions first: use it after a change to
root detection, spines or regions, since a scene keeps what was detected with the old code.
A scene also keeps the parm values it was saved with, so after changing an HDA default the old
value still applies there: for Helen, rebuild the check scene with
`tests/t17_check/t17_make.py <suite>` (reverts every parm, fresh Detect and Split).
It measures the HDA's output 1 "Groom" at rest (`GROOM_REST`: every lock not excluded, full, whatever
the view; `HAIR` on a node built before it) against its own hair mesh and
writes `qc_report.md` / `.json`:

- **checks**: each with ours, the reference, the limit and what it catches. A limit is an absolute
  value or 1.5x the reference, whichever is larger. `passed` is the verdict; hython's exit code is not
  reliable (Houdini 22 segfaults on exit), read the report.
- **worst locks**: the 8 locks most over the limits, with their numbers; start there.
- **along the strand**: root-to-tip tenths with distance to the mesh and corner angles. It says
  where a problem sits: the root (regions, root pull), the middle (surface fit) or the tip (length,
  frizz).

- **roots and shape per lock**: strands against density x area, root spacing against the even
  spacing (bunched roots), hair width / mesh width by tenth of the lock (does the end narrow like the
  mesh), centre offset at the tip, and folds against the mesh's direction. Numbers, so a lock that
  looks fine but grows from a 2 cm spot of a 7 cm region still fails.

What each check means and what usually causes a failure is in `references/checks.md`. Read it
before changing code for a failure.

## 2. Look (`qc_capture.py`, Houdini GUI on the secondary monitor, ~3 min)

Images come from a viewport flipbook, never a screen grab (a grab took whatever window covered the
screen: a browser video once). "Ours" is the HDA's output 1 "Groom" (`GROOM`, the strands), not output 0 "Display", which
packs each lock with its colour inside, so the XGen look could not reach the strands and every "ours"
image before 2026-11-12 was flat colour per lock: they show lock shapes only, not strands.

```powershell
$env:QC_SUITE="<suite>"; $env:QC_HIP="<scene>"; $env:QC_OUT="<out dir>"
$env:QC_REPORT="<out_dir of step 1>/qc_report.json"; $env:QC_REF="<groom.usd>"
houdini.exe -foreground .claude/skills/grooming-check/scripts/qc_capture.py
```

Shots: front, back, left, right, top, three-quarter, crown (`QC_VIEWS=front,crown` for fewer); the
same of the hair mesh (`mesh_*`) and of the reference (`ref_*`);
the 4 worst locks of the report alone (`lock_<name>_a/b`). Shading is XGen-preview style, computed in
VEX per camera (Kajiya-Kay highlights, darker roots, value variation per strand), no shadows: a
strand that leaves its lock or turns the wrong way catches the highlight differently from its
neighbours. Shadows were tried and hid the inside of the groom in black.

**Per lock** (`QC_COMPARE=hair_base_01,hair_bang_10`, `group:hair_base` or `all`): one image per lock,
`cmp_<lock>.png`, with its mesh, our hair and the reference's strands of that lock (each reference
strand goes to the lock whose mesh is nearest most of it) side by side, front and side rows. About
40 s a lock; whole-groom shots are skipped. This is how a lock-shaped problem shows: Helen's crown
caps (wide, short) came out as narrow twisted ribbons while every other lock matched.

**Shot** (`QC_FRAMES=0,60,120`, a scene with the animated hair mesh wired): Shot deform on, one view a
frame (`QC_VIEWS` for more): `shot_<view>_f<frame>` (ours deformed) and `shot_mesh_<view>_f<frame>` (the
animated hair mesh, same camera). Nothing else is shot.

**One lock in a shot** (`QC_FRAMES` and `QC_LOCKS=hair_bang_11`): that lock alone of output 1 at each frame, deformed,
(`shot_lock_<name>_<view>_f<frame>`) and its animated mesh piece shaded alone (`shot_lock_mesh_...`), same camera: the
two overlay pixel for pixel (tint one over the other). The camera frames the animated piece grown by `QC_LOCK_MARGIN_CM` (3), shrunk to
`QC_LOCK_ZOOM` (0.55) about its centre (frameBoundingBox leaves a wide border), so the same lock
unedited, moved 2 cm and moved 5 cm (three scenes) gets the same camera at a frame: put them side by side. A drawn
lock is framed on its own hair. The whole-groom shot pictures are skipped. Before 2026-11-22 the only per-lock shot
was compare mode, which framed the rest mesh and the deformed lock together (~330 m apart in sh020 / sh025): empty
pictures. The rest-pose `lock_<name>` close-ups now blast output 1 by lock id too (they soloed by the eye, which
output 1 ignores, and showed the whole groom). Compare mode adds the modelled piece as a column for an edited lock
(`carried mesh | mesh as modelled | ours | reference`) and frames a drawn lock on its hair alone.

Wait for "done" in `capture_log.txt`, then kill the Houdini it started (it often hangs on exit):
only the process whose command line has `qc_capture`, never the fxhoudini MCP's.

Look at ours next to `mesh_*` and `ref_*` for the same view, then the worst-lock shots. Where ours
differs from the reference, the mesh tells whose it is: ours follows the mesh by design, so a
reference groomed past its mesh (Helen's v006 fringe) is a question for the user, not a bug. Say what you see in
words before judging: bare patches, strands crossing a lock, fans at the root, brush tips, zigzags.

## 3. Report

To the user, in Vietnamese: PASS/FAIL, the failing checks with ours vs reference, what the images
show, and what you changed or will change. Send the crown and three-quarter pairs (ours, ref) and the
worst-lock shots with SendUserFile. Do not call the hair good while a check fails or the images show
a problem the numbers missed; add a check for such a problem (see `references/checks.md`) so it is
caught next time.
