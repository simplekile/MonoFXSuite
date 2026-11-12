# Interaction rules for DCC panels

Every rule here was paid for in this suite (CLAUDE.md, Auto Material and MONO Grooming sections) or comes
from the host's own conventions. A panel is a tool the artist keeps open for hours next to a viewport:
it must never make the viewport wait, lie about what the viewport shows, or take a key the host owns.

## 1. The host's main thread is sacred

- `hou`, `maya.cmds`, `bpy` are main-thread only, and so is every Qt widget. The panel may **read**
  files and parse exports on a worker thread (`controller.background`: one at a time, a newer request
  drops the older result) and must **write** to the scene on the main thread.
- A scene write disables the panel and shows a thin progress line with what is being done and Cancel,
  never a dark overlay, never a modal box (a modal blocks Houdini and the MCP bridge until someone
  closes it). A read's result waits while a write runs.
- Polling the host (selection, cook state) runs from the host's idle loop (`hdefereval`,
  `executeDeferred`), never from a Qt timer that can fire mid-cook: that produced "Infinite recursion in
  evaluation" on a node being cooked.
- Budget: an interaction that costs more than ~150 ms shows the loading line (`BUSY_DELAY_MS`); under
  that, nothing flashes. Read attributes in bulk (`primIntAttribValues`), never one object per strand.

## 2. Undo: one step per user action

- Every write the artist perceives as one action is one undo step (`undo_group`): a Create of 16
  materials, a drag's release, a Confirm all, a cancelled Create too.
- A slider **drag** writes live ticks with no undo step and puts the pre-drag data back before writing
  the final value once, so Ctrl+Z undoes the whole drag.
- View state (focus, isolate, x-ray strength, selection sync) is written with undo **off**: Ctrl+Z must
  undo the artist's last edit, not their last look.
- Ctrl+Z / Ctrl+Shift+Z / Ctrl+Y are panel shortcuts that call the host's undo: the host never sees keys
  sent to a focused Qt panel. When the top undo step is not the tool's, say what was undone ("Undid: Move
  node") rather than undoing silently (grooming review P3-2). Undo labels carry one prefix per tool.

## 3. View state apart from saved data

- What the artist **set** (settings, groups, pins, left-out flags) is saved with the scene, on the node,
  as data the tool can read back and migrate. What the artist is **looking at** (selection, focus,
  isolate, x-ray, preview fraction, drag preview) is view state: not saved, cleared on load, never in
  undo, and never in the node's output that downstream nodes or a cache read (grooming review P0-1).
- The panel reads the host's truth on every refresh (the record on the node, the selection in the
  viewport) rather than trusting its own last write.
- A hidden parm is a pragmatic place for view state (it dirties the cook), at the cost of marking the
  hip changed; gather several into one when you can (P2-2).

## 4. Selection sync with the viewport

- Clicking a row selects in the viewport; picking in the viewport selects the row. The panel's selection
  is what the settings column edits, and what the viewport draws as "the thing being edited" (real
  strands, the rest x-ray).
- Focus (our highlight) replaces the host's selection highlight only when the host's would hide the
  work; then provide what the host's selection gave for free: a Frame action on `F`, and the selection
  still available to the host's own tools.
- Only drawn things take focus: a selection that is hidden or isolated out ghosts nothing, and the
  message says why.
- Keep "what the viewport does with the selection" in words next to the selection (the settings
  subtitle), and one view-state line that answers "why does the viewport look like this?" (P2-5).

## 5. Keyboard

| Key | Convention | Rule for the panel |
| --- | --- | --- |
| `F` / `G` / `H` | Houdini frame selected / frame all / home; Maya `F` / `A` | If the panel takes `F`, it frames the panel's selection. Never leave `F` dead |
| `Esc` | leave the tool / mode | Leave the narrowest state first (isolate, then selection), never close the panel |
| `H`, `Alt+H`, `Shift+H` | Blender / Maya hide, unhide, hide others | Only when the panel is the visibility owner; say so in the shortcut list |
| `I` | isolate (ours) | Toggle; on another selection while isolated, re-isolate at once |
| `X` | x-ray (ours; Houdini's `X`-ray is a viewport display option too) | Toggle, view state |
| `Ctrl+Z` / `Ctrl+Shift+Z` / `Ctrl+Y` | host undo / redo | Forward to the host (§2) |
| `Shift` / `Ctrl` + click | extend / toggle selection | Host convention, keep |
| `Alt` + click on an eye | solo (Photoshop family) | Again on the same rows restores the eyes |
| `Enter` in a value field | commit | The field loses nothing on Tab away; Esc restores |
| `Tab` | next field, or the host's node menu | Do not block Tab inside the panel |

Every shortcut the panel owns appears in one list the artist can read (the overview shown when nothing
is selected), and in each right-click menu next to its item ("Isolate    I"). Alt+click, right-click
and drag are not discoverable from a tooltip alone (P2-7).

## 6. Host UI scale, docking, narrow width

- One `Sz` (host scale x the panel's own size pref) converts every px: fonts, paddings, icon sizes,
  minimum widths. Fonts in px, never pt. A pill's radius stays under half its height or Qt draws square
  corners.
- Design the **docked** column first: 400 px wide at scale 1 is the floor. Below `NARROW_PX` (760) the
  two-column layout stacks, bars wrap (`_WrapRow` wraps itself on resize; building to a measured width
  failed since the layout had not given the column its width yet), rows go compact, cells go two a line.
- Check at 400 / 760 / 1100 px and at scale 1 and 1.5 (`scripts/grab_offscreen.py`): no widget wider
  than the window, no horizontal scrollbar, every control at least 24 x 24 px x scale (the host's own
  are ~28).
- Sliders and combos ignore the wheel (it scrolls the panel); a slider follows its own drag with a
  timer, so a window popping up mid-drag no longer ends it.

## 7. Feedback without dialogs

- Results, notes, warnings and errors go to the result line under the window (fades after
  `MESSAGE_MS`, errors stay twice as long) or to an inline banner above the content; never a modal.
- A dangerous action warns **next to its button** on the first click (names, count) and runs on a
  second click with the same state; a modal confirm is the last resort, for data loss that is
  unexpected and irreversible (HIG `feedback`).
- Status feedback sits by the item it describes: a ring on the library row, a chip on the tile, a
  status word in the row's status column, never only in a summary elsewhere.
- Progress: a thin bar, the current step in words, Cancel; cancelling keeps what was made.

## 8. Mouse

- Press feedback within ~100 ms (hover and pressed colours on every button, a cursor on everything
  clickable); a disabled control looks disabled and does nothing; loading is not disabled (full strength,
  the label swapped for the step).
- Drag and drop: the controller decides on every move (`plan_drop`) and refusals say why in the cursor
  and the message; Qt never moves items itself; the drop is one write. Every drag has a non-drag
  alternative (a menu item, a key), WCAG 2.5.7.
- Double-click on a toggle is two clicks: make the second click undo the first, not open an editor.
- Show a widget only once it has a parent: a child shown before `addWidget` is a window of its own for
  a moment and steals the mouse from a drag.
