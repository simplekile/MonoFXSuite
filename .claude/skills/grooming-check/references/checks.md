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
| lock_width_ratio_worst | hair's spread / mesh's across the lock (2nd principal axis), at least 0.7 | | low-res lock meshes: ~5 mesh points a cross-section band measured the width wrong and the hair twisted into a narrow ribbon (fixed: bands fitted to `measure_samples` points spread over the faces). Coverage misses it: a thin lock is within 6 mm of a ribbon in its middle. First thought was "caps are wider than long": the numbers said 13.8 cm long, 3.4 cm wide; measure before explaining |
| lock_dmax / lock_kink worst | the worst lock | | look at its close-up |
| density_off_worst | a lock's strand count against density x its area (`logic.lock_strands`), \|ratio - 1\| | | Helen 2026-11-12: within 2 % on most locks, 16 % worst |
| root_clumped | share of roots closer than 0.3x the even spacing 1/sqrt(strands / region area) | | Helen 2026-11-12: 67 %: `root_pull` gathers every root under the mesh piece's root cross-section (hair_base_01: region 6.7 x 7.7 cm, roots in 1.1 x 1.9 cm), so the scalp between lock bases is bare at the root and the base is ~20-30x denser than the setting; small stacked locks get identical roots (hair_bang_15: 141 strands, 57 roots). OPEN: needs the user's call (spread roots on the region and converge into the lock, as XGen clumps do) |
| root_spacing_low | median nearest-root distance / that even spacing (random ~0.5, even ~0.9-1.1), at least | | 0.14 on Helen, same cause |
| width_mid_off_worst, tip_width_off_worst | hair width / mesh width across the lock (perpendicular to the spine, sqrt(12 var) of both point clouds, binned by the nearest spine point's curveu), middle tenths and last tenth | | Helen: ~0.77-0.80 along every lock (strands do not reach the mesh's edges), 1.0 at the tip median; worst tips 1.32 (flare) and 0.61 (too tight) |
| tip_center_off_worst | hair centre off the mesh centre in the last tenth, in mesh widths | | 0.23 worst on Helen |
| fold_share, lock_fold_worst | strand points whose direction turns over 60 deg from the spine's there (folds, hooks) | | 0.02 % on Helen |

Roots, width profile and folds are numpy over the full groom (output 1, `GROOM_REST`; 16 s on Helen). The per-lock table in
the report lists the locks that miss most, each with its width ratio by tenth, root -> tip: a lock
whose hair narrows before its mesh does reads as falling numbers at the end, a flare as a rise.


Diagnose by stage before changing code: measure the same numbers on the HDA's inner nodes
(`object_merge` of `<node>/SPINES`, `/foreach_end`, `/clump`, `/HAIR`) to find which node adds the
problem; `qc_metrics.measure`, `summary`, `profile` and `coverage` import and take any curves node.
On a copy, `node.allowEditingOfContents()` lets you try a parm on an inner node without a rebuild.

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
