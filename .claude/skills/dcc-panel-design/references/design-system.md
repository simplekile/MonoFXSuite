# The suite's DCC design system

Tokens are Python constants (Qt style sheets have no variables): a palette layer (`BG_*`, `TEXT_*`,
`ACCENT*`, `STATUS_COLORS`) in `tools/fx/auto_material/ui.py`, imported by every other panel, and a
role layer on top (`_text` / `TYPE`, `STYLE_*`, `Sz`). A new panel imports the palette and adds only
roles it needs; it never writes a hex value in a widget's style sheet. Measured contrast for every pair:
`palette_pairs.json` + `scripts/contrast_check.py`.

## Palette (dark host theme)

| Token | Value | Use |
| --- | --- | --- |
| `BG_APP` | `#111113` | the window, the main work surface |
| `BG_RAISED` | `#18181d` | tiles, pills, inputs, menus, tooltips |
| `BG_HOVER` | `#1f1f25` | hover on rows, ghost buttons, menu items |
| `BG_CURRENT` | `#1c2333` | the opened item in a sidebar |
| `PANE` (grooming) | `#17171b` | tree and bars, one step up from the window |
| `LINE` | `#26262d` | every border and divider (decorative: exempt from contrast) |
| `SELECTED` (grooming) | `#273352` | the selected row: the accent at 24 % over PANE, **opaque** |
| `TEXT_PRIMARY` | `#ededf0` | names, values, buttons, headlines (15-16:1) |
| `TEXT_LABEL` | `#a3a3ae` | every supporting text (7:1 on the window, 5:1 on a selected row) |
| `TEXT_META` | `#8e8e98` | icons, placeholders, disabled only, never a sentence (5.8:1, ui) |
| `TEXT_ERROR` | `#fca5a5` | error lines |
| `DIM` (grooming) | `#62626c` | names of hidden rows: meant to read as off (2.96:1, known) |
| `FAINT` (grooming) | `#4a4a53` | an eye decided by something else (2.04:1, known, see self-test 7) |
| `ACCENT` | `#5b8cff` | links, selection, timeline, a toggle that is on, the drop target |
| `ACCENT_FILL` | `#3d6cf0` | **the one primary button** (white on it: 4.56:1) |
| `ACCENT_LINE` | `#2f4a80` | border of a checked pill |

Status colours, the same on rings, tile edges, chips, status words and the legend (`STATUS_COLORS`):
ok `#3ecf8e` emerald, update `ACCENT` blue, new `#a78bfa` violet, pinned / warn `#f5b14c` amber,
missing / error `#f87171` red. A status colour never means anything but that status; a destructive
action is red, never the accent (token by intent). Group swatches (`SWATCHES`) are a fixed set of ten:
no colour dialog, it is modal.

Rules: one accent per panel; neutrals carry the weight; nothing is conveyed by colour alone (a status
colour always has its word or icon beside it: "check match", a crossed eye, a ring plus a count).
Qt paints item views grey under transparent colours and Houdini's own sheet wins over a bare `QLabel`
selector, so: every rule is prefixed `QWidget#<WindowName>`, and tree rows, branches and selection use
opaque colours.

## Type

Fonts in **px** (`font.setPixelSize`, `font-size: …px`): Houdini scales point sizes with its UI scale
and painted text overflows. Two weights, 400 and 600. The face is Inter where installed, else the
host's. Every label takes a role, never a size by hand (`_text(role)` / `Sz.font(role)`):

| Role | Auto Material | Grooming (an artist sits in it for hours) | Weight / colour | Use |
| --- | --- | --- | --- | --- |
| display | 26 | - | 600 primary | the headline: what the primary button will do |
| title | 19 | 22 | 600 primary | the selection's name, the empty state |
| body | 15 | 16 | 400 primary | buttons, rows, setting names, the result line |
| name | 14 | 16 | 600 primary | names of things, values set at this level |
| meta | 14 | 15 | 400 label | second lines, hints, where a value comes from |
| small | 13 | 14 | 400 label | units, measured labels, chip text (600) |
| caps | 13 | 13 | 600 label, +1 px spacing | section headers |

Floor: 13 px at scale 1 (Apple's desktop minimum is 10 pt; Houdini's parm labels are ~12-13 px). Line
length is not an issue in a 400 px column; wrapping beats truncation, and a name that must be elided is
elided in the middle with the full name in the tooltip.

## Space, radii, icons

- Spacing on a 4 px grid: 4 (label to its control), 6 / 8 (inside a row, between pills), 12 (between
  rows and cards), 16 (section padding), 24 (between sections). Everything through `Sz.px()`.
- Radii: 6 (menu items, small chips), 8 (inputs), 10 (buttons, menus, cards), 13 (pills: under half the
  height or Qt squares the corners), 3 (scrollbar handle).
- Icons: Lucide, verbatim paths, `currentColor`, stroke 2, one size token per place (14 chevrons, 15
  reset, 16 buttons, 18 bar buttons), `TEXT_LABEL` unless the control is on. The **host's own node
  icons** for what a row stands for (`_node_icon`: Material Library, MaterialX surface, image), Lucide
  outside the host. One icon per map kind, one per button; no emoji anywhere; the check icon never on a
  menu item (it reads as a ticked option).
- Hit targets: 24 x 24 px x scale is the floor, 28 (the host's buttons) the default; a slider's hit
  area is its row, not its 20 px groove (self-test issue 6).

## States (every interactive thing ships all that apply)

| State | Treatment |
| --- | --- |
| default | from the component table below |
| hover | `BG_HOVER` or a lighter border, text to primary; never a layout shift |
| pressed | one step darker than hover; feedback within ~100 ms |
| focus (keyboard) | 1 px `ACCENT` border on inputs and combos; a highlight, not a ring, in lists |
| checked / on | `_rgba(ACCENT, 0.16)` fill, `ACCENT_LINE` border, `ACCENT` text and icon |
| selected (rows, tiles) | `SELECTED` opaque row; a tile's edge in its status colour |
| disabled | `TEXT_META` text, `LINE` border, no fill; looks off and does nothing |
| loading | full strength, the label swapped for the step, Cancel beside it, a thin bar; never dimmed |
| warning | amber word or chip beside the thing; a banner line above the content when it concerns all |
| error | `TEXT_ERROR` line under the window, stays twice as long; never a modal |
| mixed (several differ) | "mixed" in the value field, a grey slider handle (`QSlider[mixed]`) |
| inherited | value in `TEXT_LABEL`, the source named ("All locks", "tool default"), Reset hidden |

## Components that recur

| Component | Anatomy | Rules |
| --- | --- | --- |
| **Top bar** | icon, what the panel is looking at (node path / asset), a pill with live context (latest publish), settings gear, Dock | The window title equals the thing looked at. Switching the thing happens here (menu or Follows selection), never by relaunching |
| **View bar** | Display, Color by, toggles that change the viewport (Deform, Isolate, X-ray) | Viewing never sits next to an action that writes. Checked toggles use the checked state, not the primary fill |
| **Tree with eye and status columns** | first column: swatch, expand chevron, name; status column: words in status colours ("check match", "new", "flipped"); last column: the eye | Hierarchy in the first column only. The eye always paints (never hover-only); its shape says what is drawn, its tone who decided (normal, `FAINT`, accent). Alt+click solo. Drag reorders; the controller plans every drop. Expansion state kept across refreshes. Names never shortened below recognisable; the status column shrinks first |
| **Setting row with inheritance** | name (+ unit), slider, value field, source, Reset (only when set here) | Label left, control right. A drag writes once on release. "mixed" when the selection differs. On a group, a last column says who below sets their own ("2 set own") |
| **Stat cells** | value (name role) over its label (small), 2-3 a line, wrapping to 2 a line when narrow | Measured, never editable; units in cm; "(preview)" when the number is from a reduced cook |
| **Tiles** | thumbnail, status colour on the edge, name, chip, a check to leave out | Share the row's width (`_fit_tiles`); right-click for version, pin, folder |
| **Action bar** | result line above; left: secondary actions (ghost); right: the one primary (`ACCENT_FILL`) with its input (version) beside it; Undo of the last run | One primary per panel. The headline above the content says what the primary will do ("5 materials behind v010") |
| **Banner** | one line above the content, `BG_RAISED`, an icon, the sentence, a link ("… just published · Open") | For a change of the world outside the panel; dismissed by acting on it |
| **Loading line** | thin bar + "Cooking: hair_back_04" + Cancel, in the action bar | Armed after 150 ms; hidden under that |
| **Inline warning** | amber icon and sentence next to the button that would be dangerous | First click warns, second click runs with the same state |
| **Chips** | 13 px 600 text in the status colour on its colour at 14 % with a 40 % border | Same colour on the tile edge and the ring |
| **Overview (nothing selected)** | what the whole shows, counts, the shortcut list | The one place every key and gesture is written down |
| **Empty state** | title role, one sentence of what will appear, the first action | Owns its space: never a small block over a void |

## Copy

English, sentence case, the host's words (Houdini: skin, guides, Hair / Hair preview, Color, Deform,
Detect locks, Update regions, Flip root, Exclude from hair; MaterialX names for slots). A button names
what happens ("Update 2 selected", "All to latest"), and keeps its name through the flow ("Publish" ->
"Published v008"). Toggles name a state in the same grammatical form as their neighbours (self-test
issue 4). An error says what happened and what to do; a placeholder shows the value that would be used,
not a pattern ("vNNN?"). Numbers with units and no more precision than measured.
