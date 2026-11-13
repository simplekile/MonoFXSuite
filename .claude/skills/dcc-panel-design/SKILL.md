---
name: dcc-panel-design
description: Use when designing, building, changing or reviewing a Qt tool panel that lives inside a DCC (Houdini first; Maya, Nuke, Blender later) in MonoFXSuite - a new window or pane, a new section, a layout or colour change, a "the panel feels off / too busy / hard to read" complaint, or before a commit that touches tools/*/ui.py. Also when picking words, keys or states for a panel, or when the viewport and the panel disagree about what is shown.
---

# DCC panel design

A panel inside Houdini is not a web page and not a desktop app: it is a column next to a viewport that
an artist keeps open for hours, docked, often 400 px wide, on a dark theme the host owns, with a main
thread the host owns too. This skill is how this suite designs, builds and checks such panels. The
detail lives in `references/`; read the file the step names, not all of them.

| Need | File |
| --- | --- |
| Tokens, type roles, states, the recurring components, copy | `references/design-system.md` |
| Keys, undo, selection sync, view state vs data, threads, scale, narrow width | `references/interaction.md` |
| What artists already know (Houdini, XGen, Ornatrix, Yeti, Blender, C4D, Painter) | `references/host-patterns.md` |
| The review checklist and how to measure it | `references/review-checklist.md` |
| The checklist applied to the Grooming panel (what it finds) | `references/self-test-grooming.md` |
| Where every rule came from, licences | `references/sources.md` |
| Palette contrast, offscreen grabs with inventory | `scripts/contrast_check.py`, `scripts/grab_offscreen.py` |

## Workflow

1. **Artist tasks first.** Write the three to five things the artist comes to the panel to do, in their
   words and order ("find the lock that looks wrong, fix its clump, publish"). Every section of the
   panel later maps to one of them; a control that serves none goes to a menu or out.
2. **Reference the host and the tools they used before** (`host-patterns.md`): the host's words, keys,
   parameter-row shape and icons; the layer-panel conventions (eye, solo, drag, right-click); the
   operator-stack idea from XGen / Ornatrix / Blender when the tool has one. Note which patterns you
   keep and which you break, and why.
3. **Two or three mockups the user picks from**, before any Qt code: an HTML artifact at 400 and 1100
   px on `BG_APP`, or an offscreen Qt grab of a throwaway layout. Each mockup states what leads, the
   one primary action, and how it stacks when narrow. The user's pick is a design decision: write it in
   the panel's module docstring.
4. **Build** on the design system: import the palette from `tools/fx/auto_material/ui.py`, add roles
   through `_text` / `Sz`, follow the component table, and the interaction rules (one undo step per
   action, view state apart from saved data, reads off the main thread, no modals, fonts in px, style
   rules prefixed with the window's objectName). View and controller stay apart so the panel runs
   offscreen with a fake adapter: that is what every test and grab below relies on.
5. **Grab and critique.** `scripts/grab_offscreen.py` at 400 / 760 / 1100 px and scale 1 / 1.5, each
   state that matters; `scripts/contrast_check.py` with the panel's new colour pairs added to
   `references/palette_pairs.json`; then the checklist (`review-checklist.md`), written as a short report
   with numbers. Fix Critical and High, re-grab, and only then show the user screenshots. A GUI check
   in the host (secondary monitor, the harness in `tools/fx/grooming/CLAUDE.md`) comes last and only when the monitor is free.

## The rules that matter most (the rest is in the references)

- **One accent.** `ACCENT_FILL` on exactly one button per panel; `ACCENT` for selection, links, a
  toggle that is on. Status colours (`STATUS_COLORS`) mean status and nothing else; a destructive
  action is red, never the accent. Nothing is conveyed by colour alone.
- **Type in px, by role.** `display / title / body / name / meta / small / caps`, two weights, 13 px
  floor at scale 1, every size through `Sz` (host scale x the panel's own size pref). Point sizes
  overflow under Houdini's UI scale.
- **Viewing apart from writing.** A view bar (display, colour, deform, isolate, x-ray) and an action
  bar (detect, update, publish); what the viewport shows is view state: not saved, not undoable, never
  in the node's output.
- **One undo step per user action**; a slider drag writes once, on release; Ctrl+Z in the panel calls
  the host's undo.
- **Never block the host.** Reads on a worker thread, writes on the main thread with a thin progress
  line and Cancel, the poll from the host's idle loop, never a modal dialog.
- **Feedback in place.** Results on the result line, status beside the item, a dangerous action warns
  next to its button on the first click and runs on the second.
- **The host's habits keep working**: `F` frames the panel's selection, `Esc` leaves the narrowest
  state, `Tab` is not swallowed, standard shortcuts are not repurposed. Every key, modifier-click and
  drag the panel owns is listed in the overview and beside its menu item.
- **Docked and narrow first**: 400 px at scale 1 works with nothing hidden; below `NARROW_PX` columns
  stack and bars wrap themselves on resize; the eye always paints; names elide last.
- **Names as the host names them**, English, sentence case, one word per concept across HDA, panel,
  undo labels; a button says what happens and keeps its name through the flow.
- **Measure before you claim**: a contrast ratio, a px size, a count, a timing; "looks fine" is not a
  finding and not a pass.

## Review in short (full list in `review-checklist.md`)

Hierarchy (one thing leads, one primary), concept count (over ~6 view concepts needs a status line),
feedback (every write ends in a sentence; loading after 150 ms with Cancel), discoverability (keys and
gestures written down; host habits intact), accessibility against the dark host (4.5:1 text, 3:1 icons
on the real background, 24 px targets, keyboard order and visible focus, scale 1.5), layout and host fit
(no overflow at 400 / 760 / 1100, parameter-row shape, host icons), state and threads (undo, view state,
main thread). Severity: Critical for an accessibility failure or a broken host convention, High for real
friction, Medium for a missed pattern, Low for polish. Short review for a strong panel.

## Common mistakes

| Mistake | What happens | Do instead |
| --- | --- | --- |
| A web form in a 400 px column (label above input) | Half the rows fit; it reads as a web page inside Houdini | Label left, control right, like a parm |
| Two filled accent buttons, or checked toggles styled like the primary | The eye cannot find the action | One `ACCENT_FILL`; checked = tinted fill, accent text |
| A QMessageBox for a result or a confirm | Houdini and the MCP bridge hang until someone clicks | Result line; inline warning, second click runs |
| `font.setPointSize` | Text overflows painted areas at UI scale 1.5 | `setPixelSize` through `Sz` |
| Bare `QLabel { … }` or a transparent selection colour in a tree | Houdini's sheet wins; rows paint grey | Prefix `QWidget#Name`; opaque row colours |
| Showing a child before `addWidget` | A window of its own flashes and ends the drag | Parent first, then show |
| Polling `hou` from a QTimer | "Infinite recursion in evaluation" mid-cook | `hdefereval` / the host's idle loop |
| View state in `groom_data` or in the node's output | Undo undoes a look; a cache made while isolated misses hair | Hidden parms with undo off, never in the output |
| Taking `F`, `Esc`, `Tab` for something else, or leaving them dead | The host's first habits break | Frame the selection, leave the narrowest state, let Tab through |
| Judging a grab with the wrong font | Fallback glyphs are wider: false overflow at the boundary width | `grab_offscreen.py` substitutes a font and says so; confirm in the host |
| "Contrast looks ok" | `FAINT` at 2.04:1 looked ok to everyone | `contrast_check.py` on the real background, chips and checked pills included |
