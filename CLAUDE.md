# MonoFXSuite

## Auto Material (Houdini, `tools/fx/auto_material/` + `apps/houdini/solaris_adapter.py`)

- Texture names follow Monos Painter publishes: `{set}_{name}_{colorspace}.{UDIM}.{ext}`. The colour
  space word (sRGB, Linear, ACEScg, Raw) is what Painter really wrote, so it sets the image's
  filecolorspace; the slot default is only for names without one. `vNNN/publish.json`
  `cleaned.maps` fills the space when a name has none.
- A Monos publish folder (children `v001`, `v002`...) is scanned only at its highest version's `textures/`.
- Subsurface slots accept Painter's OpenPBR names and SSS forms (`SubsurfaceWeight`/`Subsurface`/`SSS`,
  `SubsurfaceColor`/`SSSColor`, `SubsurfaceRadius`/`SSSRadius`). Map names in Monos Settings ›
  Texturing must use one of the names in `config.SLOT_DEFS`, or the tool does not load the map.
- Coat slots use Painter's OpenPBR channel names: `CoatWeight` (also `CoatOpacity`, `Clearcoat`),
  `CoatColor`, `CoatRoughness`, `CoatRoughnessAnisotropy`, `CoatNormal`, wired to mtlxstandard_surface
  `coat*` inputs. Coat IOR and darkening are Painter shader settings, not channels: no map, no slot.
  `config.NORMAL_MAP_SLOTS` (Normal, CoatNormal) go through their own mtlxnormalmap node.
- Create on a material that already exists updates it instead of making a second one. Image nodes
  carry user data (`monofx_slot`, `monofx_file`, `monofx_colorspace`) recording what the tool set; an
  update changes a file or colour space only while it still equals that record, so edits by hand stay.
  A new map gets an image node wired only into a free surface input; nothing is deleted or re-wired,
  and existing builders and LOP nodes are not moved. Auto assign adds to `assign_material_auto`
  instead of making another node, keeping the entries already there.
- Create runs inside `solaris_adapter.manual_update()` (Houdini updates set to Manual, then put
  back): while the Material Library cooks on changes, every node created in it re-translates all its
  materials, so 16 materials took ~110 s instead of ~1 s.
- The path box takes a texture folder or a USD file (Scan picks by what it is). **From USD** picks a
  USD file; **Publish** loads the publish's Painter export when its latest `vNNN` holds one
  (`find_painter_usd`: highest `_vNNN` in the file name, `*.material.usda` skipped), else fills the
  folder as before. A Painter USD export is read with pxr (in the adapter; `logic.py` gets plain
  `SubstanceMaterial` data and stays testable without pxr). The export only sublayers
  `*.material.usda` (Material prims under `/Geo/material` + `over`s carrying `material:binding`) and
  the geometry it was painted on (e.g. the UV publish, which may hold its own materials, e.g.
  `/_materials`). Painter materials = Material prims with an input in `config.SUBSTANCE_INPUT_TO_SLOT`;
  the geometry = the sublayers that author none of them.
  Create then makes `{base}_geo` (Sublayer of the geometry) -> `{base}_materials` (Material Library,
  materials at `/materials/<Painter name>`, not over Painter's `/Geo/material`) -> `{base}_assign`
  (one entry per material, prims from Painter's bindings). `{base}` is the export name without `_vNNN`,
  so a newer export updates the same three nodes the usual way.
- Painter writes `<UDIM>` for a texture set on several tiles and the first tile (`.1001`) for a set on
  one; both become `.%(UDIM)d`. Its `colorSpace` metadata is always `raw`, so the colour space comes
  from the name's last token (ACEScg, Raw, sRGB, Linear), like the folder scan.
