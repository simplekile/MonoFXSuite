## [0.1.26] - 2026-11-17

### Houdini
- **Auto Material**: Fix colorspace button. Select a Material Library LOP and click it: every MaterialX image with an empty colour space gets the one in its file name (`_ACEScg`, `_Raw`, `_sRGB`, `_Linear`). Materials Houdini converts from a USD leave it empty, which made base colours look washed out; images that already have a value are not changed. One undo step.
- **MONO Grooming** (v0.2a): density layers. Paint a density mask on the scalp in the viewport; each layer sets its own strands per cm² under its own mask stack, stacked over the base density. Scenes saved by v0.1 open with their groom unchanged.

### Blender
- **Model publish**: materials go under the asset root (`/<defaultPrim>/material`) instead of `/_materials` at the top of the file, with every binding moved with them, so a reference to the asset brings its materials.
- **Model publish**: file names by collection. One collection publishes `char_Helen_uv_publish.usd`; several collections add the collection name after `publish`, words joined with a capital (`char_Helen_uv_publish_GeoHelen.usd`).
- **Model publish**: the Publish dialog no longer fails with "Writing to ID classes in this context is not allowed" (Blender 5.2).
- **Publish version**: new mode File (the default for new scenes): the publish version is the `_vNNN` of the open work file. Geo and anim USD.
- **Anim USD**: the file declares a `defaultPrim`, so Solaris Reference / Sublayer attach it without a prim path.
- **Anim USD**: faster export: meshes that do not move keep only their first and last sample, points are read in one call (shot sh025 ~57 s).
- **Anim USD**: object transforms are written every frame (rigs animated only by transforms), and translated / rotated rig roots come out at the right place (the matrix was written transposed).
- **Anim USD**: a warning when a mesh exports with all points at the origin, empty or NaN, naming its active modifiers (e.g. a wrap modifier with no source object).
- The add-on version shows in the Scene, Model and Anim panel headers.

### Shared / tests
- Tests for the material scope move (needs pxr, run with hython), collection file names, point sampling, degenerate points and the colour space fix.