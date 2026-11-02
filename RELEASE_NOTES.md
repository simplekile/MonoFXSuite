## [0.1.22] - 2026-11-02

### Houdini
- **Auto Material**: read the colour space from Monos Painter texture names (`{set}_{name}_{colorspace}.{UDIM}.{ext}`: sRGB, Linear, ACEScg, Raw); `Linear` maps to `lin_rec709`, so float BaseColor maps in ACEScg or Linear no longer load as sRGB. `vNNN/publish.json` `cleaned.maps` fills the space for names without one.
- **Auto Material**: scan only the highest `vNNN/textures` folder of a Monos publish.
- **Auto Material**: Subsurface slots (weight, colour, radius) accept `SubsurfaceWeight`/`Subsurface`/`SSS` names and wire to `mtlxstandard_surface`; a colour or radius map without a weight is reported.
- **Auto Material**: Create on an existing material updates it and keeps edits made by hand (files and colour spaces changed by the user stay; new maps go only into free inputs; nothing is deleted, re-wired or moved). Auto assign adds to `assign_material_auto` instead of creating another node.

### Shared / tests
- Add Auto Material publish and update tests.