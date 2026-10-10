"""v16 planning: what MultiAxial hue sectors (FINDINGS §30a/b) would add to the v15 films.
1) The seven cube films as built in v15 (33-knot curves, post matrix) + 12 hue-sector matrices fitted on the lab_fit
   dE2000 objective (matrix/curves/post fixed; LUTSmith's seam/size penalties) -> mean dE2000 before -> after.
2) Cinema (Yellow)/(Green): how far the GR IV's own MultiAxial sets (tones 18/19, work/ma_probe5/gr4_ma_sets.json,
   level-0 matrices) move the v15 port's render, i.e. what the port is missing today.
Usage (from re-tools): work/v16_plan/hue15.py ~/dev/GR4-LUTSmith"""
import sys, json, importlib.util; sys.path.insert(0, '.')
import numpy as np, colour
from scipy.optimize import least_squares
import cube_fit as cf
from cube_fit import BASE, K, samples, warm_samples, target_of, de2000
from lab_fit import lab
from film_cave import knots_of, expand
spec = importlib.util.spec_from_file_location('ls', sys.argv[1] + '/gr4_lutsmith.py')
ls = importlib.util.module_from_spec(spec); spec.loader.exec_module(ls)
F12, F11, F14 = 'work/films_v12/fits/', 'work/films_v11/fits/', 'work/films_v14/fits/'
FILMS = [('Portra 400', F12 + 'portra_b4n3_lab.json', 4), ('Ektar 100', F12 + 'ektar_b1n3_lab.json', 1),
         ('Gold 200', F12 + 'gold_b4n3_lab.json', 4), ('Pro 400H', F12 + 'pro400h_own_b4n3_lab.json', 4),
         ('Vision3 250D', F11 + 'vision3250d_2383_b4n3_lab.json', 4), ('Classic Neg', F12 + 'classicneg_b4n3_lab.json', 4),
         ('Vision3 500T', F14 + 'vision3500t_2383_b4n3_lab.json', 4)]
chart = np.load('work/films_v10/camera_chart_L.npy')
warm = warm_samples(n=1200, seed=11); Lg, _, cc = samples(seed=7)
SETS = [('general', Lg[600:]), ('warm', warm), ('ColorChecker', cc), ('camera chart', chart)]
KINK = ls.hue_kinks()
B = np.array([ls.hue_matrices(e.reshape(12, 3)).ravel() for e in np.eye(36)]) - ls.hue_matrices(np.zeros((12, 3))).ravel()
M0 = ls.hue_matrices(np.zeros((12, 3))).ravel()


def render(M, cv, P, Hq=None):
    def r(X):
        z = (K * X) @ M.T
        if Hq is not None:
            z = ls.hue_apply_q(z, Hq, ls.HUE_BOUNDS)
        b = np.interp(np.clip(z, 0, 255), np.arange(256), BASE)
        return np.clip(np.stack([np.interp(b[:, c] / 64, np.arange(256), cv[c]) for c in range(3)], 1) / 16384 @ P.T, 0, 1)
    return r


def scores(f, T):
    out = []
    for nm, X in SETS:
        t = T(X); u = t.min(1) > 0.02 if nm == 'camera chart' else np.ones(len(X), bool)
        out.append(float(de2000(np.clip(f(X), 0, 1)[u], t[u]).mean()))
    return out


fmt = lambda s: ' / '.join(f'{x:.2f}' for x in s)
print('1) mean dE2000 vs film target, general / warm / ColorChecker / camera chart', flush=True)
fitted = {}
for name, fp, boost in FILMS:
    f = json.load(open(fp)); T = target_of(f['presets'][0])
    cv = [expand(knots_of(c)) for c in f['presets'][0]['curves']]        # as v15 stores them
    P = np.array(f['post_q512']) / 512; M = np.array(f['matrix'])
    cf.NEUTRAL = 3.0
    L, w, _ = samples(boost=boost); tl = lab(T(L)); sw = np.sqrt(w / w.mean()); n = np.sqrt(len(L))

    def res(d):
        e = sw * colour.delta_E(lab(render(M, cv, P, 1024 * ls.hue_matrices(d.reshape(12, 3)))(L)), tl, method='CIE 2000')
        pen = np.r_[np.sqrt(ls.HUE_KINKS[0] / 12) * KINK @ d, np.sqrt(ls.HUE_RIDGE / 12) * d,
                    np.sqrt(ls.HUE_RANGE) * np.maximum(np.abs(M0 + d @ B) - ls.HUE_LIMIT, 0)]
        return np.r_[e, n * pen]
    d = least_squares(res, np.zeros(36), x_scale=0.05, max_nfev=40).x
    Hq = ls.hue_quantise(ls.hue_matrices(d.reshape(12, 3)))
    a, b = scores(render(M, cv, P), T), scores(render(M, cv, P, Hq), T)
    fitted[name] = Hq.tolist()
    print(f'  {name:13s} v15 {fmt(a)} -> + hue sectors {fmt(b)}', flush=True)
json.dump(fitted, open('work/v16_plan/hue_sectors.json', 'w'))

print('2) Cinema: v15 port with vs without the GR IV MultiAxial set (dE2000 mean / p95 / max)')
G4 = json.load(open('work/ma_probe5/gr4_ma_sets.json'))
for name, fp, tone in (('Cinema (Yellow)', F14 + 'cinema_yellow.json', '18'), ('Cinema (Green)', F14 + 'cinema_green.json', '19')):
    f = json.load(open(fp)); cv = [np.array(c) for c in f['presets'][0]['curves']]
    P = np.array(f['post_q512']) / 512; M = np.array(f['matrix'])
    Hq = np.array(G4[tone]['matrices']).reshape(12, 5, 3, 3)[:, 0]
    for nm, X in SETS:
        e = de2000(render(M, cv, P)(X), render(M, cv, P, Hq)(X))
        print(f'  {name:15s} {nm:12s} {e.mean():.2f} / {np.percentile(e, 95):.2f} / {e.max():.2f}')
