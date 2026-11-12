# Review checklist, and how to measure it

Run it on a grab, not on the code. Numbers, not adjectives: a finding has the element, the number
(px, ratio, count, seconds) and the fix. Say which items were measured and which judged. A panel with
no Critical and few High findings gets a short review.

## Before reviewing: produce the evidence

1. **Grabs.** `python .claude/skills/dcc-panel-design/scripts/grab_offscreen.py --factory <mod>:make
   --widths 400,760,1100 --scales 1,1.5 --out <dir>` with a factory that builds the panel on fake data
   of a realistic size (61 locks, 3 groups; 16 materials). It writes a PNG and an inventory per width x
   scale and lists hit targets under 24 px x scale and widgets wider than the window. Grab each state
   that matters: nothing selected, one lock, a group, a hidden row, a warning showing, loading.
2. **Contrast.** `python .claude/skills/dcc-panel-design/scripts/contrast_check.py --pairs
   .claude/skills/dcc-panel-design/references/palette_pairs.json --suggest`; add the panel's new pairs
   to the file (a new colour, a new fill) before judging.
3. **Timings** from the numbers in `tools/fx/grooming/CLAUDE.md` or a fresh measurement: open, refresh, select, an edit, a poll
   (the review's `bench_panel.py` pattern: offscreen Qt, fake adapter, `time.perf_counter` around the
   controller call plus `processEvents`).
4. **In the host (only when a GUI check is possible):** the harness from `tools/fx/grooming/CLAUDE.md`: Houdini started with
   a startup script on the secondary monitor, the panel grabbed after the viewport has drawn; compare
   timings against an action whose code did not change (select) before calling a regression; kill the
   session after. Other sessions may need the secondary monitor: ask first.

Then look at every grab. Gates pass while a UI is still visibly broken.

## The checklist

Severity: **Critical** = accessibility failure or a convention broken in a way that confuses (dead `F`,
a modal that blocks the host, a key stolen); **High** = real friction (a control under 24 px, a
hover-only control, text under 4.5:1 that carries meaning, two primaries); **Medium** = suboptimal
pattern, inconsistency, missed host component; **Low** = polish.

### A. Hierarchy (judged on the 1100 and 400 grabs)

- [ ] One thing leads: the eye lands first on the thing the artist came for (the selection's name, the
  headline that says what the primary action will do). Display type is a clear step above body.
- [ ] One primary action, filled with `ACCENT_FILL`; every other button ghost or pill. Checked toggles
  do not compete with it.
- [ ] Viewing (display, colour, isolate, x-ray) is in a different bar from writing (detect, update,
  publish).
- [ ] Sections read in the order of the task: what am I looking at, what is selected, what it measures,
  what I can set, what I can do.
- [ ] The page ends on purpose at every width: no small block over a void; an empty state owns its
  space.

### B. Concept count (counted)

- [ ] Count the distinct things the artist must hold in mind to answer "why does the viewport look like
  this?" (display mode, per-row display, while-playing, deform, x-ray and its level, isolate, eyes,
  solo, focus, preview fraction). Over ~6 needs one status line that names the ones in effect, with a
  way to clear each.
- [ ] Count toggles, menus and modes on the first screen; each earns its place or moves to the
  right-click menu or Settings.
- [ ] One word per concept across HDA, panel, undo labels and docs (a shared label table in `config`).

### C. Feedback (judged per action)

- [ ] Every write ends in a sentence on the result line ("Updated 5 materials to v010", "Undid: …"); an
  action that cannot run says why where the button is.
- [ ] Status sits by the item (ring, chip, status word), not only in a summary.
- [ ] Loading shows after ~150 ms with the step named and Cancel; the host keeps drawing (no modal, no
  overlay). A frozen host for over a second is Critical.
- [ ] Feedback never outruns the truth: the list changes when the sentence says it did.
- [ ] A dangerous action (publish with hidden locks, overwrite) warns inline first and runs on the second
  click; data loss that is unexpected and irreversible is the only case for a confirm box.

### D. Discoverability (checked against the overview and menus)

- [ ] Every key, Alt / Shift / Ctrl click and drag the panel understands is in the overview list and
  beside its item in a right-click menu. A gesture that exists only in a tooltip is a Medium finding.
- [ ] Every icon-only control has a tooltip that names the action and the key.
- [ ] The host's habits still work with the panel focused: `F` frames the selection, `Esc` leaves the
  narrowest state, `Ctrl+Z` undoes the last edit (not the last look), `Tab` is not swallowed.
- [ ] The artist can switch the thing the panel looks at without relaunching it.

### E. Accessibility against the dark host (measured)

- [ ] Text that carries meaning 4.5:1 on its real background (a selected row, a chip fill, a checked
  pill), icons and borders that carry meaning 3:1; failures listed with ratio and the nearest passing
  colour. Dividers and dimmed "off" text are exempt, and are named as such.
- [ ] No meaning by colour alone: every status colour has its word or icon.
- [ ] Hit targets: every control at least 24 x 24 px at scale 1 (the inventory lists the ones under);
  sliders and eyes take their whole row height.
- [ ] Keyboard: Tab order follows reading order; focus is visible (accent border on inputs, the selected
  row in lists); focus never moves without the artist's action; no control reachable only by hover.
- [ ] Scale 1.5: same checks; nothing clipped, nothing under 36 px; every size went through `Sz`.
- [ ] Motion: none that is not feedback; nothing longer than ~200 ms; nothing that blocks input.

### F. Layout and host fit (measured on the 400 / 760 / 1100 grabs)

- [ ] No widget wider than the window, no horizontal scrollbar, at any width or scale.
- [ ] Below `NARROW_PX`: columns stack, bars wrap, rows compact, cells two a line; nothing hidden.
- [ ] Names are not elided while another column has slack; the status column shrinks first; an elided
  name keeps its distinguishing part (the number at the end) and has a tooltip.
- [ ] The parameter-row shape (label left, control right), the host's icons for its objects, sentence
  case, the host's own words. Nothing that reads as a web page (hero numbers, cards for everything, a
  gradient, a one-sided coloured border).

### G. State and threads (checked in the code)

- [ ] One undo step per action; drags write once; view state written with undo off and never saved or
  published.
- [ ] Reads off the main thread, writes on it, the poll from the host's idle loop.
- [ ] Style rules prefixed with the window's objectName; opaque colours in item views; widgets shown
  only once parented; fonts in px; wheel ignored by sliders and combos.

## Report shape

```
## Panel review: <name> (<commit>, grabs at 400/760/1100 x 1/1.5)
Summary: two sentences, the rating, and the one thing the panel does best.
Critical / High / Medium / Low: each with element, number, why (checklist item or host rule), fix.
Measured: contrast table (fails only), small targets, overflow, timings.
Not checked: what needed the host GUI or real data.
```
