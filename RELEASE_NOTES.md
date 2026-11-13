## [0.1.25] - 2026-11-13

### Houdini
- **MONO Grooming** (new, v0.1): a SOP node that turns a hair card mesh into strands. Detect finds the locks and their roots on the scalp, Split regions gives each lock its patch of skin; each lock grows strands evenly at the set density that gather into the lock's shape (Helen: 61 locks, ~119,000 strands, full cook ~11 s).
- **MONO Grooming**: a panel (MonoFX shelf) with the locks in a tree (groups, hide, isolate, exclude), per-lock and global settings with sliders, Guides / Hair views, Color by lock or group; hidden locks do not cook, so working on a few locks stays fast.
- **MONO Grooming**: skin under hair mesh that floats over the scalp is left thin on purpose, as in a hand groom, and the panel says so; a lock whose mesh root floats off the skin is listed by Detect and Root to skin bends its start down.
- **MONO Grooming**: output 1 "Groom" is the full groom whatever the view; Publish writes it as USD with the groom data in `vNNN/_grooming/`, never overwrites a version, and never leaves a half-written file (a failure says why in the panel).

### Installer
- Ships `otls/` (the MONO Grooming HDA).

### Shared / tests
- Grooming logic, controller and publish tests; `grooming-check` skill (hair QC numbers and shaded shots against an approved groom).