# Host patterns: what artists already know

A panel inside a DCC is judged against the host and against the tools artists used before it. Reuse
their patterns where they fit, name them the way the host does, and only invent where the task has no
precedent. Sources and dates: `sources.md`.

## Houdini (first host)

- **Parameter pane conventions.** Label left, control right, one row per parameter; folders (tabs) for
  groups; a slider with a typed field; a `(`..`)` ladder on middle drag; the wheel does not change a
  slider unless it has focus. Our setting row (name, slider, value, source, Reset) extends this: keep the
  name on the left and the field on the right so it still reads as a Houdini parm.
- **Viewport keys an artist expects to keep working while the panel has focus**: `F` frame selected,
  `G` frame all, `H` home, `Space` + drag view, `Esc` leave the current tool, `Enter` show handles,
  `Tab` node menu (in a network editor), `Ctrl+Z` / `Ctrl+Y` undo / redo. A panel that eats `F` or
  clears the selection `F` would frame breaks the first habit of every Houdini artist (grooming review
  P1-3). A Qt panel sees keys only while focused, so give it its own `F` that frames the panel's
  selection, and forward nothing you did not mean to take.
- **Grooming tools** ([Guide Groom](https://www.sidefx.com/docs/houdini/nodes/sop/guidegroom.html)):
  the tools are viewport brushes chosen from a radial menu (`C`), each with its own options; groups and
  masks are painted. Hair Generate / Hair Clump name the parameters (Thickness is one strand's width,
  Clump has Blend, the scalp is the skin). Our panel is the layer side those tools lack: use their words.
- **Node-centric state.** Everything the artist saved lives on a node (parms, user data); the panel is a
  view of a node and should say which node, and let the artist switch nodes without relaunching
  (grooming review P2-9: Auto Material's Follows selection is the pattern).
- **Dark theme.** Houdini's panes are mid-grey (~`#3c3c3c`); our panels are darker surfaces inside
  them, so the border between panel and host is the pane edge itself. Fonts must be set in px: Houdini
  scales point sizes with its UI scale and painted text overflows (CLAUDE.md).
- **Python panels** are docked by default and can be very narrow; a floating window is the exception.
  Design the 400 px column first.

## Maya / XGen (next host; from the public manual, not re-read this session)

- XGen keeps **Descriptions inside Collections**; each description has a modifier stack (Clumping,
  Noise, Cut, Coil) and a Preview/Output tab with a density preview percentage. Artists expect per
  description: density, a preview fraction, visibility, and a stack of named modifiers with their own
  parameters. "Clump › Size", "Cut", "Noise frequency", "Width ramp" are the words they search for
  (grooming review P1-5).
- Keys: `F` frame selected, `A` frame all, `Ctrl+H` hide, `Shift+H` show, `Ctrl+Shift+H` unhide last,
  `Alt+H` hide unselected (isolate by hiding). Maya's isolate select is a viewport toggle.
- Maya dockable Qt panels run inside Maya's own Qt; the same rules on fonts, style-sheet scope and the
  main thread apply (`maya.utils.executeDeferred` is the idle hook).

## Blender (later)

- Hair is **Curves objects in Curves Sculpt mode**: brushes in the toolbar, selection modes `1` points /
  `2` curves, a cage overlay with its own opacity (the same idea as our x-ray: the thing being edited
  seen inside the thing it belongs to). Procedural hair is a modifier stack of node groups (Clump,
  Frizz, Interpolate), so "a stack of named operators per object" is again what the artist knows.
- Outliner toggles: eye (viewport), camera (render), arrow (select); `H` hide, `Alt+H` unhide all,
  `Shift+H` hide others, `/` local view (isolate). Blender panels are not Qt: this skill's layout rules
  carry over, its Qt mechanics do not.

## Ornatrix, Yeti (for reference)

- Ornatrix: one **operator stack** per hair object; an operator is limited to strand groups. Clump,
  Frizz, Length, Edit Guides are the names.
- Yeti: a node graph; grooms painted on the mesh. Its vocabulary (graph, scatter, grow, clumping) is
  the one FX artists from Maya know.

## Layer panels (Cinema 4D, Substance Painter, Photoshop family)

- **A row is: colour swatch, name, status, toggles at the right edge.** Cinema 4D's Layer Manager
  shows one-letter toggles per layer (S solo, V view, R render, L lock, ...); Painter's layer stack an
  eye, a thumbnail, opacity and blend mode per channel; both drag to reorder and use folders. Artists
  expect: eye always visible (never hover-only), drag between rows and onto a folder, right-click for the
  rest, the bottom layer drawn first (Painter) or the top (C4D): say which.
- **Alt+click on an eye = solo** (Photoshop, carried into Painter and ours), and the same click again
  puts the eyes back. **Shift+click / Ctrl+click** extend the selection.
- Painter keeps the stack's **actions in one icon row at the top right** (add layer, folder, mask,
  effect, delete). An action row has a fixed order; do not move an action because it is disabled.

## What to copy, what not to

| Copy | Do not copy |
| --- | --- |
| The host's words for what a thing is (skin, guides, clump, description, layer) | A rival's product name for it |
| Its keys for view and visibility | Its keys for actions the host already binds to something else |
| Eye / solo / isolate behaviour from layer tools | Hover-only controls, modal colour pickers (Houdini's colour dialog is modal: use swatches) |
| Stack order shown as the artist reads it | A stack the panel reorders on its own |
| The parameter-pane row (label left, control right) | A web form (label above, full-width input) in a 400 px column: it halves the rows that fit |
