"""A/B test: Portra 400 and Classic Neg fitted with GR4-LUTSmith 1.3.0's method (as work/compare/lutsmith13.py: its
Fitter unchanged, GR III base gamma, our samples/weights; 3 curves + colour after the curves, best of a warm start and
3 turns on 'general'; no hue sectors, GR IV only). Writes each look in our fit format (matrix / curves / post_q512)
next to this script, for make_slots.py.
Usage (from re-tools): work/lsab/fit_ls.py ~/dev/GR4-LUTSmith"""
import sys, json, importlib.util; sys.path.insert(0, '.')
import numpy as np
import cube_fit as cf
from cube_fit import BASE, K, samples, warm_samples, target_of, model, de2000
from film_cave import knots_of, expand

spec = importlib.util.spec_from_file_location('ls', sys.argv[1] + '/gr4_lutsmith.py')
ls = importlib.util.module_from_spec(spec); spec.loader.exec_module(ls)
ls.base_curve = lambda name: BASE / 16384
OUT = 'work/lsab/'
FITS = [('portra_ls', 'work/films_v12/fits/portra_b4n3_lab.json', 4),
        ('classicneg_ls', 'work/films_v12/fits/classicneg_b4n3_lab.json', 4)]
chart = np.load('work/films_v10/camera_chart_L.npy')
warm = warm_samples(n=1200, seed=11); Lg, _, cc = samples(seed=7)
SETS = [('general', Lg[600:]), ('warm', warm), ('ColorChecker', cc), ('camera chart', chart)]


def scores(f, T):
    out = []
    for nm, X in SETS:
        t = T(X); u = t.min(1) > 0.02 if nm == 'camera chart' else np.ones(len(X), bool)
        out.append(float(de2000(np.clip(f(X), 0, 1)[u], t[u]).mean()))
    return out


def as_fit(look, preset):
    """LUTSmith look -> our fit format: z = (K L) M^T = K (L M^T), same curves (256 x 0..16384), P = q9 / 512."""
    return dict(matrix=(np.array(look['matrix_q13']) / 8192).tolist(),
                presets=[dict(spec=preset['spec'], in_cs=preset.get('in_cs', 'vlog'), ev=preset.get('ev', 0.0),
                              curves=[list(map(float, c)) for c in look['curves']])],
                post_q512=np.array(look['post_matrix_q9']).tolist(), source='GR4-LUTSmith 1.3.0 Fitter (rgb, after curves)')


fmt = lambda s: ' / '.join(f'{x:.2f}' for x in s)
print('mean dE2000 vs film target: general / warm / ColorChecker / camera chart', flush=True)
for key, fp, boost in FITS:
    f = json.load(open(fp)); pre = f['presets'][0]; T = target_of(pre)
    cv = [expand(knots_of(c)) for c in pre['curves']]                  # as the firmware stores them (33 knots)
    ours = scores(lambda X: model(np.array(f['matrix']), cv, X) @ (np.array(f['post_q512']) / 512).T, T)
    cf.NEUTRAL = 3.0
    L, w, _ = samples(boost=boost)
    v, t = K * L, T(L)
    look = ls.Fitter(v, t, 'rgb', weight=w).run(t, iters=1500)
    cands = [ls.Fitter(v, t, 'rgb', weight=w, post=True).run(t, iters=1500, init=look, lr=ls.POST_WARM_LR)]
    for s in range(3):
        cands.append(ls.Fitter(v, t, 'rgb', weight=w, post=True).run(t, iters=1500, rng=None if s == 0 else np.random.default_rng(1000 + s)))
    best = None
    for c in cands:
        fit = as_fit(c, pre)
        kcv = [expand(knots_of(x)) for x in fit['presets'][0]['curves']]
        sc = scores(lambda X: model(np.array(fit['matrix']), kcv, X) @ (np.array(fit['post_q512']) / 512).T, T)
        if best is None or sc[0] < best[1][0]:
            best = (fit, sc)
    fit, sc = best
    fit['scores_knots'] = dict(zip([n for n, _ in SETS], sc)); fit['ours_scores_knots'] = dict(zip([n for n, _ in SETS], ours))
    json.dump(fit, open(OUT + key + '.json', 'w'))
    print(f'{key:14s} ours {fmt(ours)} | LutSmith {fmt(sc)}   knot err {max(int(abs(expand(knots_of(c)) - np.array(c)).max()) for c in fit["presets"][0]["curves"])}/16384', flush=True)
