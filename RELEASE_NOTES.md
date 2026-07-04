## [0.1.14] - 2026-07-04

### Houdini
- Refactor **USD Batch Load** into `tools/fx/usd_batch_loader` (logic/ui/config) with shared `lop_usd_helpers`; independent horizontal LOP layout.
- Add **Node Preset Library** and **Restart Houdini** shelf tools (`library`, `restart` icons).
- Slim `anim_publish_loader` by moving shared LOP setup into `lop_usd_helpers`.

### Blender
- Fix material bake session `config` import; bump add-on to **0.9.84**.

### Tests
- Add logic tests for USD batch loader and node preset library.