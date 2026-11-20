## [0.1.42] - 2026-11-20

### Houdini
- **Test in Houdini** (anim): a lookdev that gives the anim no material or brings meshes of its own (made on another geometry than the UV publish) is now reported, instead of "reads clean".
- **MonoFX Loaders**: right-click a Geo / Lookdev / Groom / Cloth cell to open that part's publish folder; Open folder is a submenu with every part.
- **MonoFX Loader**: an Open Folder strip on the node (Geo, Lookdev, Groom, Cloth).
- **MonoFX Loaders**: in an asset's scene (a lookdev file) the shot crumb asks for a shot instead of showing the project's first one.
- **MonoFX Loaders**: a Refresh button (also F5); the window reads the scene again when you come back to it.
- **MonoFX Loaders**: the headline counts loaders with a missing file instead of saying "All up to date".
- **MonoFX Loaders**: Upgrade no longer turns a texturing (or other non-UV) Sublayer into a loader that cannot find its file.
- **MonoFX Loader**: Prim Name has a checkbox. Off keeps the publish's own prims (/Geo); new Source Asset loaders start off, shot loaders on.