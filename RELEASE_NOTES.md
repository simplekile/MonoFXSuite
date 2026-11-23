## [0.1.47] - 2026-11-23

### Blender
- **Publish Anim**: prims of a linked rig carry the names in the rig file. Blender adds `.001` to an override whose name is taken in the shot, and the anim USD came out as `/Geo_Whale_001` (sh014, sh015, sh017), which the lookdev does not bind to. A copy of a rig mesh keeps its own name.
- **Link Rig**: a second link of the same rig in another collection gets its own namespace (`helenwhalerig2::`); it took the first one's and every object got `.001`.
- **Remove Rig Link**: removes the rig's objects and child collections too. They stayed in the file, and the next link of the rig got `.001`. Other instances and the artist's own objects stay, and the library stays while they use its data.