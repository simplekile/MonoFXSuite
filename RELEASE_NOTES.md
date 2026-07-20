## [0.1.21] - 2026-07-21

### Installer / Houdini
- Copy shelf/icons only into **selected** Houdini versions that received a full install (avoid orphan shelf buttons).
- Point `monofx.json` `hpath` / `MONOFX_SUITE` at `$HOUDINI_USER_PREF_DIR/monofx`.
- Shelf `_find_suite_root` resolves installer `Documents/houdini*/monofx` layouts more reliably.

### Blender
- Multi-axis **sine chain** drivers (per-axis slots, wave modes, chain phase).
- Anim USD Cache: custom mesh export list (add/remove selected), richer asset list UI.
- Resolve anim publish under any `NN_anim` task folder (shot or asset). Bump add-on to **0.9.132**.

### Shared / tests
- Extend `anim_sine_chain` multi-axis helpers and USD cache path tests.