## [0.1.28] - 2026-11-17

### Blender
- **Model publish**: materials stay where Blender writes them (`/_materials`, beside the asset root), as before v0.1.26: the move into `/<root>/material` is taken out.
- **Model publish**: the asset root is marked `kind = component` (USD asset structure). A kind already there, or a component / group / assembly below the root, is left alone.
- **USD fps**: every publish (model, UV, camera) carries the scene fps. A static export used to keep 24, and a Houdini Sublayer copied that over the hip's fps (30 fps scenes rendered at 24). Anim USD also writes `framesPerSecond`.