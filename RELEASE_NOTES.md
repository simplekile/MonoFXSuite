## [0.1.36] - 2026-11-19

### Houdini
- **MonoFX Loader**: a groom cache keeps moving after a Graft Stages downstream (the shot layout's graft_anim); before, the groom stood still at its first frame there, in any shot.
- **MonoFX Loader**: **Reload** (on the node beside Refresh, and Reload from disk on the manager's right-click menu) reads every file the loader uses again from disk, for a publish written again into the same version; Houdini kept showing the old content. Versions do not change.