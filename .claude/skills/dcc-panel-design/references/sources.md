# Sources

What this skill distilled, from where, under which licence, and what it left out. Every file in this
skill is our own text: nothing is copied beyond a short quote, and the community repositories were read
as data in a sandbox (`E:/01 Dev/sandbox/claude/skills_study/`, cloned 2026-11-12), never run.

## Community skills (read 2026-11-12)

| Source | Licence | Taken | Left out, and why |
| --- | --- | --- | --- |
| [nextlevelbuilder/ui-ux-pro-max-skill](https://github.com/nextlevelbuilder/ui-ux-pro-max-skill) `6ae86f6` | MIT | The priority order of concerns (accessibility, interaction feedback, then layout, type, colour, motion, forms, navigation); the pre-delivery checklist's shape (process steps, then per-area boxes); the "no emoji as icons, one icon family, one stroke width, icon sizes as tokens" rules; "loading is not disabled"; "pressed feedback within ~100 ms"; dark-mode contrast checked on its own, not inferred from light; "primary action: one per screen". | The CSV search engine, design-system generator, style/palette/font catalogues, GSAP and stack guides: web and marketing material. Touch targets in pt/dp (we use Houdini's ~28 px controls and the 24 px floor). Its token files (Tailwind, CSS variables). |
| [plugin87/ux-ui-agent-skills](https://github.com/plugin87/ux-ui-agent-skills) (XIAS) `f823ace` | MIT | The three-tier token idea reduced to two (palette constants, then roles) since Qt style sheets have no variables; the eight component states as a checklist, with "selected" never optional when a thing can be selected; "token by intent" (a destructive action never wears the accent); "one thing leads" on every screen; "verify every state, not just resting"; "never state a number you did not measure"; "render and look: gates pass while a UI is still visibly broken"; the critic that reviews in a fresh context without the maker's reasoning; the review table (severity, finding, recommendation) and Nielsen's heuristics as a lens; "feedback may not outrun the truth"; the WCAG 2.2 criteria that apply to desktop (focus not obscured, target size 24 px, dragging has a non-drag alternative). | Its 52 browser gates, DTCG token JSON, 2,144 design systems, framework adapters, Thai typography, foldables, mobile-first: all HTML/CSS. Its no-em-dash and no-native-select rules (a Qt panel uses QComboBox; Houdini's own menus are the convention). |
| [dickwu/apple-design-skill](https://github.com/dickwu/apple-design-skill) `ff4ebdd` | MIT (the HIG pages it mirrors are Apple's text; we quote none of them at length) | The reviewer's stance (two people: platform reviewer and studio lead); the five lenses in order (accessibility, platform conventions, visual craft, interaction, writing) with severity tied to the lens; the report format (Summary, Critical, Improvements, What works) and "a strong design gets a short review"; "numbers, not adjectives"; "cite it or label it as judgment"; desktop numbers (default control 28 x 28 pt, minimum 20 x 20; desktop type default 13 pt, minimum 10 pt); the HIG patterns we reuse: status feedback near the item it describes, alerts rare and never for common undoable actions, a modal has one short task and an obvious way out, show something at once while loading and let people keep working, never move focus without the person's action, outline views expose hierarchy in the first column only, keep expansion state, a panel is an inspector of the selection with simple adjustment controls, respect standard shortcuts and do not repurpose them, every toolbar command also in a menu, "keep actions with text labels separate from symbol-only actions". | iOS, iPhone Duo, Liquid Glass, Apple Pay, app icons, widgets, App Review: not a DCC panel. Apple's title-case rule: Houdini and this suite use sentence case. |
| [borghei/Claude-Skills](https://github.com/borghei/Claude-Skills) `25bf86b` (UI/UX parts: `product-team/apple-hig-expert`, `engineering/design-auditor`, `engineering/a11y-audit`) | MIT + Commons Clause (no selling the software; reading and learning from it is fine, and we ship no part of it) | "Say which parts were measured and which were judged"; include focus rings, borders, icons and disabled states in the contrast pass at 3:1, not only body text; "a clean automated scan is not 'the design is good'"; the baseline idea (grade against the previous audit); a contrast checker that suggests the nearest passing colour (ours is written from scratch, stdlib, with alpha compositing added). | Its scorer, slop detector, HTML scanner and grades A-F: tuned to marketing pages, regex on HTML. The Commons Clause also means none of its code is vendored here. |

## This repository

- `CLAUDE.md` sections *Auto Material* and *MONO Grooming*: fonts in px against Houdini's UI scale, one
  accent, status colours only for status, no modal dialogs, style rules prefixed with the window's
  objectName, opaque tree colours under Houdini's style sheet, show a widget only once it has a parent,
  the wheel never on sliders and combos, the narrow docked layout and width-dependent wrapping, names as
  Houdini names them, panel (view) state apart from saved data, the GUI test harness on the secondary
  monitor, and every timing in the two sections.
- `tools/fx/auto_material/ui.py`: the palette constants, `_text` roles, `STATUS_COLORS`, `LUCIDE`
  paths, `_node_icon`, the style sheets (`STYLE_*`).
- `tools/fx/grooming/ui.py`: `PANE` / `SELECTED` / `DIM` / `FAINT`, the `TYPE` roles sized for a panel
  an artist sits in for hours, `Sz`, `NARROW_PX`, `_WrapRow`, `_IconDelegate`, `UI_SIZES`.
- The review `E:/01 Dev/sandbox/claude/grooming/tests/t48_review/review.md` (2026-11-12) and its
  offscreen bench `bench_panel.py`: the UI/UX findings in `self-test-grooming.md` start from its P1-3,
  P1-4, P2-5, P2-7, P2-9, P3-1, P3-2.

## DCC documentation (public pages, for the patterns artists already know)

Read on 2026-11-12 unless marked; the rest is from memory of the public manuals and should be checked
against the live page before a quote.

- SideFX Houdini: [Guide Groom SOP](https://www.sidefx.com/docs/houdini/nodes/sop/guidegroom.html)
  (read: tools live in the viewport radial menu, C; every tool has its own options; paint group and
  paint mask tools), [Hair Generate SOP](https://www.sidefx.com/docs/houdini/nodes/sop/hairgen.html),
  [Python panels](https://www.sidefx.com/docs/houdini/hom/python_panes.html),
  [viewport keys](https://www.sidefx.com/docs/houdini/basics/view.html).
- Blender: [Curves Sculpt mode](https://docs.blender.org/manual/en/latest/sculpt_paint/curves_sculpting/introduction.html)
  (read: brushes, selection modes 1 / 2, cage opacity overlay), the Outliner's restriction toggles
  (eye, render, select; `H`, `Alt+H`, `Shift+H`, `/` local view) from memory of
  [editors/outliner](https://docs.blender.org/manual/en/latest/editors/outliner/interface.html).
- Adobe Substance 3D Painter: [Layer stack](https://experienceleague.adobe.com/en/docs/substance-3d-painter/using/interface/layer-stack/layer-stack)
  (read: layers, folders, masks, per-channel opacity and blend mode, actions in a top-right icon row,
  bottom layer drawn first).
- Autodesk Maya XGen (memory): Descriptions inside Collections, a Modifiers tab holding a stack
  (Clumping, Noise, Cut, Coil), Preview/Output tab with a density preview percentage, per-description
  visibility; Maya's `F` frame, `A` frame all, `Ctrl+H` hide, `Shift+H` show, `Ctrl+Shift+H` unhide last.
- Ephere Ornatrix (memory): an operator stack per hair object (Edit Guides, Hair from Guides, Clump,
  Frizz, Length), strand groups as the way to limit an operator.
- Peregrine Labs Yeti (memory): a node graph editor, grooms as painted attributes on the mesh.
- Maxon Cinema 4D Layer Manager (memory; the public URL moved and returned 404 on 2026-11-12): a
  layer row with a colour swatch and one-letter toggles (S solo, V view, R render, M manager, L lock,
  A animation, G generators, D deformers, E expressions), drag to reorder.
- Lucide icons: [ISC licence](https://lucide.dev/license); the paths in `ui.py` are copied verbatim.
