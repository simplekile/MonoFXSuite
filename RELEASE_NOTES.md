## [0.1.33] - 2026-11-17

### Houdini
- **MonoFX Loaders** manager (layout A, picked from mockups): **+ Add** holds Load shot and **Assets...**, a drawer of the project's assets (type chips, search, thumbnails; pick several, Add N). A **view bar**: Solo selected (Houdini's Solo Geometry, not saved), Lookdev / Groom in the viewport for every loader, Filter. The status line says what the shot has that the scene lacks (**Add it**) and how many GB of textures the lookdevs pull. The selected loader shows **what is new** in a newer version (date, who saved its work file in Monos, outputs, frame range, meshes, size), Source Shot / Asset, and Open folder, Open in Monos, Frame. **Hand off...** writes a self-contained USD per loader with its textures, for people without MonoFX.
- **MonoFX Loader**: in a lighting scene laid out with merge_actors / merge_cameras / merge_environments, Load shot and Add put the new loaders there (characters with the actors, props and sets with the environments). Adding an asset already placed makes another instance (`prop_Cliff01_inst02`) for set dressing.
- **MonoFX Loader**, Source Asset: props and environments whose lookdev publish holds the whole asset load that alone; before, the UV mesh was loaded under it as well (double geometry).

### Houdini
- **MonoFX Loader** is its own node now (Tab > MonoFX > MonoFX Loader, named `monofx_loader`), no longer an "anim loader" in name, file or type. Scenes with the 2.2 node still open; the manager's **Upgrade** moves those nodes over, keeping every setting.
- **MonoFX Loader** manager (shelf **MonoFX Loaders**) finds loaders in every LOP network, also inside /obj (grooming scenes), not only /stage; opened from a node, Load shot builds next to it.
- **MonoFX Loader**, Source Asset: an **Asset Type** menu (Characters, Props...) shortens the Asset list, which shows only assets that have a UV publish; Advanced shows the **Model Path**; a part with nothing published says "none published".