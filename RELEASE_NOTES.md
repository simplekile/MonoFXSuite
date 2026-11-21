## [0.1.45] - 2026-11-22

### Houdini
- **MonoFX Loader**: a camera keeps the aperture of its publish, so a 16:9 camera stays 16:9. Before, the loader set only the width to 36 mm and left the height, and sh011's camera came out 3.05:1. A new **Aperture** menu on the Camera section can set a width in mm and take the height from the publish's own ratio, or set a width and an aspect ratio. Only the loader's own cameras are changed.