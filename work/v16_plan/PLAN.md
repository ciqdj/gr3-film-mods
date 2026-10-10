# Films v16 plan: hue sectors (MultiAxial) on top of v15

Written 2026-10-10. Details and raw numbers live in FINDINGS §27-31; this is the short version.

## What we learned today

1. **Sensor differences are small** (§27). After the best 3x3, two cameras differ by ~0.7 dE2000 on average
   (worst patch ~2, on cyan/skin/red). A daylight matrix reused under tungsten costs ~3 dE. The look itself
   (hue- and saturation-dependent moves) dominates, so porting another maker's look is limited by the hardware's
   levers, not by the sensor.
2. **Our fitter still beats GR4-LUTSmith 1.3.0 on GR III levers** (§28). With the same matrix + 3 curves + post matrix,
   ours wins 21 of 24 scores and every "general" score (by 0.1-0.8). LUTSmith's new "colour after the curves" closed most
   of the gap; its remaining edge comes from GR IV hue sectors.
3. **MultiAxial (hue sectors) works on the GR III** (§29, §30). Rounds 1-4 failed because we never set the per-zone
   strength fields: control[10..13] = 1024 (GR III ships 0, 0, 21, 62 = off). Probe 5 (photo-ma6) proved it on camera.
4. **Same geometry as the GR IV** (§30b). 12 sectors by the Cb/Cr angle of the post-look-matrix signal, edges
   359.8, 27.4, 62.2, 92.6, 112.0, 142.8, 179.2, 211.4, 238.6, 267.2, 306.0, 326.5 deg; 167/172 chart patches land in the
   predicted sector. LUTSmith's HueFitter model applies unchanged.

## What hue sectors would buy (work/v16_plan/hue15.py, hue15.log)

Mean dE2000 vs film target, general / warm / ColorChecker / camera chart. Matrix, curves and post matrix kept as in v15,
only the 12 sector matrices fitted:

| Film | v15 | + hue sectors |
|---|---|---|
| Portra 400 | 2.14 / 1.66 / 1.46 / 1.98 | 1.96 / 1.52 / 1.40 / 1.85 |
| Ektar 100 | 2.32 / 1.96 / 1.64 / 2.29 | 2.14 / 1.81 / 1.67 / 2.18 |
| Gold 200 | 2.10 / 1.58 / 1.39 / 1.87 | 1.99 / 1.53 / 1.47 / 1.89 |
| Pro 400H | 2.06 / 1.50 / 1.45 / 1.94 | 1.94 / 1.40 / 1.52 / 1.95 |
| Vision3 250D | 2.13 / 1.66 / 1.73 / 2.42 | 1.99 / 1.48 / 1.65 / 2.31 |
| Classic Neg | 1.51 / 1.16 / 1.14 / 1.33 | 1.23 / 1.09 / 1.18 / 1.13 |
| Vision3 500T | 2.27 / 1.72 / 1.55 / 2.27 | 2.03 / 1.49 / 1.47 / 2.02 |

A joint refit (matrix + curves + post + sectors together) should do better than this sectors-only estimate.

**Cinema is the big one.** The GR IV's Cinema (Yellow)/(Green) use their own MultiAxial sets (GR IV tones 18/19,
saved in work/ma_probe5/gr4_ma_sets.json). The v15 port leaves them out; adding them moves the render by
1.3-2.2 dE2000 on average (p95 2.8-4.8, max up to 11). That is the part of the GR IV Cinema look v15 is missing, and it
can be ported verbatim.

## How to fit it in the firmware (space)

v15 has ~1.1 KB of ROM free (no section growth). A full matrix table is 60 x 3x3 int32 = 2160 B per look, which does
not fit nine times. Plan:

- **One shared set** for all films: GR IV bounds, selectors and control (strengths 1024), ~140 B.
- **Compact per-film data**: 12 sectors x 6 off-diagonals (diagonal = 1024 - row sum), int8 at step 4/1024 = 72 B per
  film, ~650 B for nine. Check that rows sum to 1024 for every fitted and GR IV matrix (GR IV level 0 does).
- **A stub after MultiAxial's calc** (hook as probes 2/4 at the Make tail 0x536E4498) writes the 60 matrix registers
  (hw 272 + 64*(m//5) + 10*(m%5), 12-bit Q10) from the film's compact data. Levels: films get the same matrix at all 5
  levels (as LUTSmith, camera-validated on GR IV and in probe 5); Cinema gets GR IV's level scaling 1 - l/16
  (1024/960/896/832/768 row sums), to stay verbatim.
- Stock modes keep the stock (inactive) set; only film slots point at the shared set.

## Steps

1. Joint refit of the seven cube films with sectors (lab_fit + HueFitter alternating); compare to the table above.
2. Cinema: v15 port + GR IV sets verbatim; check against the GR IV emulated render (emux.py) on the chart samples.
3. make_slots16.py / verify_slots16.py: shared set, compact data, register stub; emulate every film's MultiAxial
   registers against the model.
4. Camera test: hue chart per film vs model (as check_v13.py), plus a real scene.

## Still open from earlier

- Movie recording path is not emulated (v15 test step 2).
- AWB, DR / highlight / shadow correction and clarity are untested with the films.
- Unknown: what selects the 5 levels within a sector (thresholds 293..3200 look like luma); probe 5 used equal levels.
- GR IV Standard also uses a MultiAxial set; a "GR IV Standard" look would need a slot (all slots are taken).

## White balance (FINDINGS §32, work/wb_sim)

Simulated (K-5 / NEX-5N spectral sensitivities, ColorChecker): the films track Standard under every light and AWB error
(within ~±0.5 dE2000, usually lower), so they need no WB-specific fix. Daylight variants cost 0.7-1.1 dE; tungsten,
fluorescent and white LED cost 2-3 dE mean (max 11-17 on saturated colours) **if** the camera keeps one daylight
sensor matrix, and only 0.5-0.9 with a matrix for that light. Whether the GR III switches/interpolates its sensor matrix
is not known yet (it is applied before the stage we emulate). One tungsten RAW+JPG ColorChecker shot settles it; if it
does not adapt, a WB-dependent correction of the film look matrices is a candidate after v16.
