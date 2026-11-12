# What the checks catch, and what caused them on Helen

Per strand, over its polyline. `p95` = 95th percentile over strands. Reference = v006 (approved).

| check | meaning | v006 | causes found so far |
|---|---|---|---|
| kink_p95_deg | sharpest corner of a strand | 43 | lookup jumping between a lock's top side and underside (fixed: two sheets, `SHEET_GAP`); band centroids jumping (fixed: `spine_smooth`); single bad lookups on folded meshes (fixed: `strand_smooth`, median of 3); the spine frame swinging on round bands and a stale `tangentu` (fixed: angle-smoothed frame); a hard stop of the root relaxation (fixed: fading weight); too few segments on short curled locks (fixed: at least 32) |
| zigzag_p95 | bends that turn back the other way, per segment | 0.06 | same as kink |
| sharp_mean | share of joints bent over 30 deg | 0.012 | same as kink |
| maxseg_p95_cm | longest segment | 2.4 | 24 segments on a 90 cm lock (fixed: segments from `strand_segment_cm`) |
| dmax_p95_cm | farthest point from the strand's OWN lock mesh | 0.8 | roots scattered over a wide scalp region fanning in (fixed: `root_pull`) |
| dtip_p95_cm | tip distance from the mesh | 0.4 | length / frizz settings |
| other_mean | share of points sitting on another lock's mesh | 0 | fans at the root; stacked locks |
| uncovered | hair mesh with no strand curve within 6 mm | 0.035 | strands bunched mid-lock (fixed: `cross_spread`); hairclump's blend (fixed: the lock's clump drives `blend`, tightness alone never switches it off); `ps` narrower than the mesh (fixed: stretched to its edges); strand count from the root only (fixed: widest band); too coarse spines in curls (fixed: 48 points) |
| lock_uncovered_worst | the barest lock | | as above |
| lock_width_ratio_worst | hair's spread (points weighted by the strand length they stand for) / mesh's (points weighted by face area) across the lock (2nd principal axis), at least 0.7 | | low-res lock meshes: ~5 mesh points a cross-section band measured the width wrong and the hair twisted into a narrow ribbon (fixed: bands fitted to `measure_samples` points spread over the faces). Coverage misses it: a thin lock is within 6 mm of a ribbon in its middle. First thought was "caps are wider than long": the numbers said 13.8 cm long, 3.4 cm wide; measure before explaining |
| lock_start_share_worst | hair in the first 3/10 of a lock (by nearest spine point) / the mesh's share there by face area, at least 0.5 | | root spread: strands joining a lock where its mesh lies over them left caps and fringe 11-20 % of their mesh's share at the start (fixed: start extras on top of the lock's count, `start_target`); v0.1 (root_pull) 0.83 |
| width_start_off_worst | \|hair width / mesh width - 1\| in tenths 2-3, worst lock | | the fringe's start climbing from its skin to an arc 1.5-2.4 cm up (fixed: far roots become start roots) |
| width_bulge_worst | widest of tenths 2-9 over the mesh, worst lock, at most 1.4 | | fringe fin mid-arc: strands rooted under the arc climbing to it (hair_bang_09 2.0, 4-5x the lock's thickness); same fix |
| lock_dmax / lock_kink worst | the worst lock | | look at its close-up; a cap lying ~1 cm up on another whose roots all climbed to it from the skin (hair_base_08 61 deg: the far-root height is per lock) |
| density_off_worst | a lock's strand count against density x its area (`logic.lock_strands`), \|ratio - 1\| | | Helen 2026-11-12: within 2 % on most locks, 16 % worst |
| root_clumped | share of roots closer than 0.3x the even spacing 1/sqrt(strands / region area) | | Helen 2026-11-12: 67 %: `root_pull` gathers every root under the mesh piece's root cross-section (hair_base_01: region 6.7 x 7.7 cm, roots in 1.1 x 1.9 cm), so the scalp between lock bases is bare at the root and the base is ~20-30x denser than the setting; small stacked locks get identical roots (hair_bang_15: 141 strands, 57 roots). Fixed 2026-11-12 (t47): roots stay where hairgen scatters them on regions that follow the meshes (`logic.region_owners`: footprint, else the mesh lying over the scalp), strands join their lock where its mesh is nearest the root and converge over `root_converge` x the offset: 3 % bunched (fringe roots pulled toward the lock's root) |
| root_spacing_low | median nearest-root distance / that even spacing (random ~0.5, even ~0.9-1.1), at least | | 0.14 on Helen, same cause; 1.0 after the fix (t47) |
| width_mid_off_worst, tip_width_off_worst | hair width / mesh width across the lock (perpendicular to the spine, sqrt(12 var) of both point clouds, binned by the nearest spine point's curveu), middle tenths and last tenth | | Helen: ~0.77-0.80 along every lock (strands do not reach the mesh's edges), 1.0 at the tip median; worst tips 1.32 (flare) and 0.61 (too tight) |
| tip_center_off_worst | hair centre off the mesh centre in the last tenth, in mesh widths | | 0.23 worst on Helen |
| fold_share, lock_fold_worst | strand points whose direction turns over 60 deg from the spine's there (folds, hooks) | | 0.02 % on Helen |
| lock_turned_worst | share of hair length turned over 30 deg from the spine, worst tenth 3-9 of any lock, at most 0.10 | | strands crossing their lock to join it, and the crown's footprint hairpins; 7e33860 0.36 (hair_base_01 / 03 / 08 / 11 / 17), v0.1 0.05. Tenths 1-2 left out: there hair leaves the skin and the crown caps' spine starts steeper than the hair (v0.1 0.6-0.9) |
| lock_outside_worst | share of hair beyond its lock's cross-section (mesh 1-99 % extent on its two axes across the spine) by 2 mm, worst tenth 3-9, at most 0.10 | | hair crossing the gap between the skin and a lock floating over it, in bundles: the spike on hair_base_11, fuzz on _17, standing strands on _08 (7e33860 0.30, even roots 0.53, v0.1 0.25 at the back locks' tips). The turned check missed these once they rose gently |
| skin_thin_share / lock_skin_thin_worst | scalp (and worst region) with under half the roots its regions ask for within 5 mm, whorl roots and start extras left out; at most 0.05 / 0.20 | | roots moved round lock roots leave the skin between thin: v0.1 0.84, 7e33860 0.23. Skin under an arch (every owner's root edge on the skin, its mesh over 1 cm above) is left out and reported apart: the tool moves those roots to the lock start on purpose |

Roots, width profile and folds are numpy over the full HAIR (16 s on Helen). The per-lock table in
the report lists the locks that miss most, each with its width ratio by tenth, root -> tip: a lock
whose hair narrows before its mesh does reads as falling numbers at the end, a flare as a rise.


Diagnose by stage before changing code: measure the same numbers on the HDA's inner nodes
(`object_merge` of `<node>/SPINES`, `/foreach_end`, `/clump`, `/HAIR`) to find which node adds the
problem; `qc_metrics.measure`, `summary`, `profile` and `coverage` import and take any curves node.
On a copy, `node.allowEditingOfContents()` lets you try a parm on an inner node without a rebuild.

Whorls (t47): roots the tool packs at a whorl on purpose carry `whorl_root` and are left out of
density_off, root_clumped and root_spacing; the report's "Whorl" section gives their count and share and the
densest 1 cm disc of ours and of the reference (v006: 16,035 roots, 18.6 % of its roots, 5,104 / cm2 at
Helen's crown). Start roots (`start_root` without `whorl_root`) are the lock's own and are measured like
any root. The mesh is weighted by face area in the width ratio and the start share (`mesh_point_area`):
by point count a cap's densely tessellated end weighed 0.44 of it, by area 0.28. Never re-weight the hair
to pass a check: an earlier version matched the hair's mass along the lock to the mesh's and passed a
groom whose caps had 2 % of their hair at the start (review t48); that matched value is printed for
information only.
Check where the reference puts its roots (`t47_root_spread/probe_ref_roots.py`) before calling a dense
whorl a bug. Measure the hair share per tenth of a lock against its mesh's (`probe_mass.py`) and root to
own mesh vs any mesh (`probe_roots.py`) before blaming the fit: 59 % of roots over 1 cm from their own
mesh was the region rule, not the fit.

Lessons that cost time:
- An average or a median over all strands passes a groom where every strand has one bad corner.
  Use the worst strand's value per strand, then a p95 over strands, and per lock.
- Distance to a strand's nearest POINT misreads coverage (points are 2 cm apart): use the curve
  (`xyzdist`).
- Attribute Blur pins every point of an open polyline with `pinborder` on: it did nothing.
- In VEX, a `prim()` / `point()` passed straight into another function or a comparison picks the
  wrong overload; read it into a typed variable first.
- A scene keeps the parm values it saved: after changing a default, check the scene's values
  (`--fresh` does not revert parms; the check scene is rebuilt with every parm reverted).
- A `%` in a VEX string that goes through Python `%` formatting breaks the build: write `%%`.
