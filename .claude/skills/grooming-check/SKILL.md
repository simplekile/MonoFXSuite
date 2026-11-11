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
hython .claude/skills/grooming-check/scripts/qc_metrics.py <suite> <scene.hiplc> <out_dir> --ref <groom.usd> [--fresh]
```

`--fresh` empties the groom data and runs Detect and Split regions first: use it after a change to
root detection, spines or regions, since a scene keeps what was detected with the old code.
A scene also keeps the parm values it was saved with, so after changing an HDA default the old
value still applies there: for Helen, rebuild the check scene with
`tests/t17_check/t17_make.py <suite>` (reverts every parm, fresh Detect and Split).
It measures the HDA's `HAIR` node at rest (the shot deform is ignored) against its own hair mesh and
writes `qc_report.md` / `.json`:

- **checks**: each with ours, the reference, the limit and what it catches. A limit is an absolute
  value or 1.5x the reference, whichever is larger. `passed` is the verdict; hython's exit code is not
  reliable (Houdini 22 segfaults on exit), read the report.
- **worst locks**: the 8 locks most over the limits, with their numbers; start there.
- **along the strand**: root-to-tip tenths with distance to the mesh and corner angles. It says
  where a problem sits: the root (regions, root pull), the middle (surface fit) or the tip (length,
  frizz).

What each check means and what usually causes a failure is in `references/checks.md`. Read it
before changing code for a failure.

## 2. Look (`qc_capture.py`, Houdini GUI on the secondary monitor, ~3 min)

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
