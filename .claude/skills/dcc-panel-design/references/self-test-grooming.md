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
| 1 | High | D | `F` frames nothing while the panel has focus, and focus clears the viewport selection so the host's `F` cannot either (t48 P1-3). The shortcut list has no `F`. | Panel `F` and a right-click "Frame" that frame the bbox of the focused locks' spines; add to `SHORTCUTS`. |
| 2 | High | D | Discoverability: Alt+click solo, right-click (Flip root, Exclude, Display, colour, Confirm), drag-to-reorder exist only in tooltips; `SHORTCUTS` lists 6 lines and none of them (t48 P2-7). | Add them to the overview list; write the key beside each right-click item. |
| 3 | Medium | F | Names elided to `ha…01` at every width from 760 up while the settings column has 400+ px of slack: the tree pane is fixed at 260-300 px (`setMinimumWidth(300)`), the status column ("check match") takes the rest. At 400 px, where the tree is alone, names are whole. | Size the tree pane from the longest name (or let the splitter remember); elide the status word before the name; keep the number at the end visible. |
| 4 | Medium | A/B | The selection toggles mix a state ("Hidden") with verbs ("Flip root", "Exclude") (t48 P2-5). | One form: "Hide / Flip root / Exclude", or three checkboxes with state labels. |
| 5 | Medium | B | Concept count: Display, per-row Display, While playing, Deform, X-ray + level, Isolate, eye, Alt-solo, focus, preview fraction = 10 things decide what the viewport shows; nothing on screen says which are in effect (t48 P2-5). | One faint status line at the end of the view bar ("Editing hair_bang_05 · others x-ray · 3 hidden · rest pose"), each part clickable to clear it. |
| 6 | Medium | E | Hit targets: the 7 setting sliders are 20 px tall at scale 1 (30 at 1.5) inside a 34 px row; the inventory lists them under the 24 px floor. The row's rest is dead space. | Give `_Slider` the row's height (hit area), keep the 4 px groove. |
| 7 | Medium | E | Contrast (`contrast_check.py`): `FAINT` eye `#4a4a53` on `PANE` 2.04:1 (needs 3:1 as a meaningful icon); `DIM` hidden names 2.96:1 (meant to read as off; the row keeps its eye and status word, so acceptable as an inactive state); accent text on a checked pill 4.45:1 (a hair under 4.5). 26 of 29 pairs pass. | `FAINT` -> `#63636b` (3.0:1) keeps it quieter than `TEXT_LABEL` and readable; pill fill alpha 0.12, or text `#5e8eff`. |
| 8 | Medium | D | The panel is bound to one node; another character means re-running the shelf tool (t48 P2-9). | Node label as a menu of every MONO Grooming node (asset beside each) and a Follows selection pill, as in Auto Material. |
| 9 | Medium | B | Names differ between HDA and panel: "Hair full" / "Hair", "Colour by" / "Color by", "Detect" / "Detect locks", "Guide" / "Guides"; two undo prefixes (t48 P3-1). | One label table in `config.py` for both; one undo prefix. |
| 10 | Low | A | At 1100 x 820 the settings column ends at ~570 px with 250 px of nothing under it; the overview (counts, shortcuts) only appears with nothing selected. | Show the shortcut list, faint, under the settings when there is room; or let the measured cells and attribute names fill the space. |
| 11 | Low | Copy | The version field's placeholder is `vNNN?`: a pattern with a question mark, not the value that will be used. | Show the version Publish would pick ("v008") as the placeholder, from `publish_context`. |
| 12 | Low | C | Publish warns inline about hidden / isolated locks on the first click (good) but not about pieces never detected, locks still "check match", or regions out of date (t48 P1-1). | Extend the same first-click warning; block only on undetected pieces. |

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
