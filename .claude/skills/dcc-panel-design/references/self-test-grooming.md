# Self-test: the checklist on the MONO Grooming panel (commit 0a32882, 2026-11-12)

The baseline for this skill is a panel built before it existed and reviewed without it (t48 review,
UI/UX findings P1-3, P1-4, P2-5, P2-7, P2-9, P3-1, P3-2): those are the failures the skill must catch
again on its own. This pass applies `review-checklist.md` to the same panel, offscreen, with fake data
of Helen's size (61 locks in 3 groups, one orphan, one lock selected). Evidence:
`E:/01 Dev/sandbox/claude/grooming/tests/t49_panel_grabs/` (PNG + inventory at 400 / 760 / 900 / 1100
px, scale 1 and 1.5; `grooming_factory.py` is the factory). Grabbed with Segoe UI: Inter is not
installed on this machine, so widths differ slightly from Houdini's. Not checked: anything that needs
the viewport (focus, x-ray, F), timings, keyboard focus order.

**Summary.** Good: one primary (Publish), the view bar apart from the action bar, the parameter-row
shape, Houdini's words, status by word and colour, the result line instead of dialogs, the layout
holds at 400 px and at scale 1.5 with no overflow. Rating: Needs work, on discoverability and a few
measured misses; no Critical finding in what could be checked offscreen.

## Findings

| # | Sev | Item | Finding (measured where there is a number) | Fix |
| --- | --- | --- | --- | --- |
| 4 | Medium | A/B | The selection toggles mix a state ("Hidden") with verbs ("Flip root", "Exclude") (t48 P2-5). | One form: "Hide / Flip root / Exclude", or three checkboxes with state labels. |
| 5 | Medium | B | Concept count: Display, per-row Display, While playing, Deform, X-ray + level, Isolate, eye, Alt-solo, focus, preview fraction = 10 things decide what the viewport shows; nothing on screen says which are in effect (t48 P2-5). | One faint status line at the end of the view bar ("Editing hair_bang_05 · others x-ray · 3 hidden · rest pose"), each part clickable to clear it. |
| 8 | Medium | D | The panel is bound to one node; another character means re-running the shelf tool (t48 P2-9). | Node label as a menu of every MONO Grooming node (asset beside each) and a Follows selection pill, as in Auto Material. |
| 10 | Low | A | At 1100 x 820 the settings column ends at ~570 px with 250 px of nothing under it; the overview (counts, shortcuts) only appears with nothing selected. | Show the shortcut list, faint, under the settings when there is room; or let the measured cells and attribute names fill the space. |
| 11 | Low | Copy | The version field's placeholder is `vNNN?`: a pattern with a question mark, not the value that will be used. | Show the version Publish would pick ("v008") as the placeholder, from `publish_context`. |

Fixed since (2026-11-12, re-grabbed in `tests/t51_panel_fix/`): 1 (`F` frames, `adapter.frame_locks`), 2 (every
key and gesture in `SHORTCUTS`), 3 (the tree pane widens to its longest name, up to half the window, while
the settings keep ~540 px: names whole from 900 px; at 760 the settings win), 6 (sliders and the Settings
button at least 24 px), 7 (`FAINT` #63636b 3.0:1, checked pill fill 0.12), 9 (one label set, one undo
prefix), 12 (Publish warns about undetected pieces, locks to check, stale regions). Left: Qt's own clear
button in the filter field (22 x 18).

What the checklist did not catch on its own and the t48 review did: P1-4 (finding wrong locks: a
quality column per lock) is a feature gap, not a panel rule; it stays a product decision.

## What this pass says about the skill

- Items A, F and E found three things the review had not written down (3, 6, 7), from the grabs and
  the contrast script alone: the measuring half of the checklist earns its place.
- Items B and D re-found P2-5, P2-7, P2-9, P3-1 from the grab and the `SHORTCUTS` list; P1-3 needed the
  code (`set_focus` clearing the selection), which item D's "host habits still work" line points at.
- The grab needs the real font to be trusted at the boundary width: with Segoe UI's fallback glyphs
  missing (first run, boxes) the 760 px grab showed 26 overflowing widgets that vanished with a real
  font. `grab_offscreen.py` now substitutes a font and says so.
- Next time the Grooming panel changes, re-run the two scripts and update this table; a fixed item is
  removed, a `known_fail` that now passes is unmarked in `palette_pairs.json` (the test insists).
