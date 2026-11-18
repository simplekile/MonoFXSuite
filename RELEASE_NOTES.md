## [0.1.35] - 2026-11-19

### Blender
- **Anim USD export**: a rig whose meshes are named with a digit first (veh_Spaceship v003: `01_Pipe_Rubber`) exports again; its prims are named `_01_Pipe_Rubber`, as in the asset's lookdev and UV publish. Before, the export stopped with "Path must be an absolute path" and a headless export hung. An export that cannot start now ends with its error instead of waiting forever.