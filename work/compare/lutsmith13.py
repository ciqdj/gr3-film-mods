"""GR4-LUTSmith (lemonadesaltbagel, v1.3.0: + colour after the curves, turns) fitting method vs ours, on the same GR III model and targets.
LUTSmith model: out_c = C_c[ T( H_g(M v) )_c ]: look matrix M, 12 hue-sector 3x3s H_g (before the curves), up to 3
curves; Adam on a CIE94/CIEDE2000-style Lab distance. Its Fitter/HueFitter are used unchanged, with T = the GR III
Standard base gamma; samples/weights are ours (cube_fit.samples). Hue sectors at its weakest seam penalty, no seam
budget check (most freedom). Ours: v11/v12 lab fits (matrix -> curves -> post matrix via the CSP).
Usage (from re-tools): work/compare/lutsmith13.py ~/dev/GR4-LUTSmith"""
import sys, json, importlib.util; sys.path.insert(0, '.')
import numpy as np
import cube_fit as cf
from cube_fit import BASE, K, samples, warm_samples, target_of, model, de2000
from film_cave import knots_of, expand

spec = importlib.util.spec_from_file_location('ls', sys.argv[1] + '/gr4_lutsmith.py')
ls = importlib.util.module_from_spec(spec); spec.loader.exec_module(ls)
ls.base_curve = lambda name: BASE / 16384

FITS = [('Ektar 100', 'work/films_v11/fits/ektar_b1n3_lab.json', 1), ('Gold 200', 'work/films_v11/fits/gold_b4n3_lab.json', 4),
        ('Pro 400H', 'work/films_v11/fits/pro400h_own_b4n3_lab.json', 4), ('Portra 400', 'work/films_v11/fits/portra_b4n3_lab.json', 4),
        ('Vision3 250D', 'work/films_v11/fits/vision3250d_2383_b4n3_lab.json', 4),
        ('Classic Neg', 'work/films_v12/fits/classicneg_b4n3_lab.json', 4)]
chart = np.load('work/films_v10/camera_chart_L.npy')
warm = warm_samples(n=1200, seed=11); Lg, _, cc = samples(seed=7)
SETS = [('general', Lg[600:]), ('warm', warm), ('ColorChecker', cc), ('camera chart', chart)]


def ls_render(look, L):
    z = (K * L) @ (np.array(look['matrix_q13']) / 8192).T
    if look.get('hue_sectors'):
        z = ls.hue_apply_q(z, np.array(look['hue_sectors']['matrices_q10']), ls.HUE_BOUNDS)
    b = np.interp(np.clip(z, 0, 255), np.arange(256), BASE)
    out = np.stack([np.interp(b[:, c] / 64, np.arange(256), np.array(look['curves'][c])) for c in range(3)], 1) / 16384
    if look.get('post_matrix_q9'):
        out = out @ ls.post_effective(look['post_matrix_q9']).T
    return out


def scores(f, T):
    out = []
    for nm, X in SETS:
        t = T(X); u = t.min(1) > 0.02 if nm == 'camera chart' else np.ones(len(X), bool)
        out.append(float(de2000(np.clip(f(X), 0, 1)[u], t[u]).mean()))
    return out


rows = []
TURNS = 3
print('mean dE2000 vs film target: general / warm / ColorChecker / camera chart', flush=True)
for name, fp, boost in FITS:
    f = json.load(open(fp)); T = target_of(f['presets'][0])
    cv = [np.array(c) for c in f['presets'][0]['curves']]
    if 'vision3' in fp or 'classicneg' in fp:
        cv = [expand(knots_of(c)) for c in cv]
    P = np.array(f['post_q512']) / 512
    ours = scores(lambda X: model(np.array(f['matrix']), cv, X) @ P.T, T)
    ours_nopost = None
    cf.NEUTRAL = 3.0
    L, w, _ = samples(boost=boost)
    v, t = K * L, T(L)
    res = {}
    res = {}
    look = ls.Fitter(v, t, 'rgb', weight=w).run(t, iters=1500)
    res['rgb'] = (look, scores(lambda X: ls_render(look, X), T))
    cands = [ls.Fitter(v, t, 'rgb', weight=w, post=True).run(t, iters=1500, init=look, lr=ls.POST_WARM_LR)]
    for s in range(TURNS):                                     # turn 1 classic start, then random starts
        cands.append(ls.Fitter(v, t, 'rgb', weight=w, post=True).run(t, iters=1500, rng=None if s == 0 else np.random.default_rng(1000 + s)))
    fs = [(look_, scores(lambda X: ls_render(look_, X), T)) for look_ in cands]
    res['rgb+after'] = min(fs, key=lambda r: r[1][0])          # best of the turns on 'general'
    pl = res['rgb+after'][0]
    hf = ls.HueFitter(v, t, w / w.sum(), pl); hf.kink = ls.HUE_KINKS[0]
    hlook = dict(pl, hue_sectors=dict(matrices_q10=ls.hue_quantise(ls.hue_matrices(hf.run(800))).tolist()))
    res['rgb+after+hue'] = (hlook, scores(lambda X: ls_render(hlook, X), T))
    rows.append((name, ours, {k: s for k, (_, s) in res.items()}))
    fmt = lambda s: ' / '.join(f'{x:.2f}' for x in s)
    print(f'{name:13s} ours {fmt(ours)} | LS 3 curves {fmt(res["rgb"][1])} | + after curves (best of {TURNS} turns) '
          f'{fmt(res["rgb+after"][1])} | + hue sectors (GR IV only) {fmt(res["rgb+after+hue"][1])}', flush=True)
