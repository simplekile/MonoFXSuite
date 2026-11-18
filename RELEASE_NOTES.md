## [0.1.37] - 2026-11-19

### Houdini
- **MonoFX Loader**: a groom whose lookdev publish holds its own values on the groom (Helen's) keeps moving after a Merge or a Graft Stages downstream; before, from the shot layout's merge_actors on, the groom stood still at the lookdev's values, with the lookdev's point count over the cache's topology (sh025_lighting_v004).
- **MonoFX Loader**: the **Reload** button works; in v0.1.36 every click raised "module object has no attribute 'cb_reload'" (the manager's Reload from disk was fine).
- **MonoFX Loader**: **Hide Prims** is gone from the node's parameters: show and hide prims with the eye in the manager's inspector. The hair driver mesh stays hidden by default, as before; its eye shows it.

### Blender
- **MonoFX tab by department**: the tab shows the tools of the department the .blend is saved in (`01_modelling` Model, `02_rigging` Rig, `NN_anim` Anim); Scene has an Auto / Model / Rig / Anim switch to pick another. A file outside a project shows Model and Anim as before.
- **Rig publish** (new Rig panel): Publish Rig writes `02_rigging/<task>/publish/vNNN/<asset>_rig_publish.blend` holding only the rig's publish collection (other collections and scenes left out, orphans purged); the open file is not changed. Anim > Link finds it as before.
- **UV maps and normals in publish**: Publish Asset and Publish Anim ask in their confirm dialog (Include: UV Maps, Normals). Model publish keeps both on by default, anim publish leaves both off (points only, as before); with them on, anim UVs are written once (the render UV as `st`) and normals on every frame.
- **Anim > Link** also takes a publish collection named with a dash (`CHAR_HELEN_RIG-PUBLISH`), which it refused before.