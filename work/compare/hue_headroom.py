"""Headroom: our v11/v12 fits + LUTSmith-style hue sectors (12 continuous 3x3s on the linear signal after the look
matrix, before the curves; GR III has the same MultiAxial block in the CCA0 group but it never acted on stills, §18a).
Our matrix, curves and post matrix fixed; the 36 sector parameters fitted on the lab_fit dE2000 objective.
Usage (from re-tools): work/compare/hue_headroom.py ~/dev/GR4-LUTSmith"""
import sys, json, importlib.util; sys.path.insert(0, '.')
import numpy as np, colour
from scipy.optimize import least_squares
import cube_fit as cf
from cube_fit import BASE, K, samples, warm_samples, target_of, de2000
from lab_fit import lab
from film_cave import knots_of, expand
spec = importlib.util.spec_from_file_location('ls', sys.argv[1] + '/gr4_lutsmith.py')
ls = importlib.util.module_from_spec(spec); spec.loader.exec_module(ls)
src = open('work/compare/lutsmith.py').read()
exec(src[src.index('FITS = ['):src.index('def ls_render')])     # FITS, SETS
exec(src[src.index('def scores'):src.index('rows = []')])
KINK = ls.hue_kinks()
B = np.array([ls.hue_matrices(e.reshape(12, 3)).ravel() for e in np.eye(36)]) - ls.hue_matrices(np.zeros((12, 3))).ravel()
M0 = ls.hue_matrices(np.zeros((12, 3))).ravel()


def ours(f, cv, P, Hq=None):
    M = np.array(f['matrix'])
    def r(X):
        z = (K * X) @ M.T
        if Hq is not None:
            z = ls.hue_apply_q(z, Hq, ls.HUE_BOUNDS)
        b = np.interp(np.clip(z, 0, 255), np.arange(256), BASE)
        return np.clip(np.stack([np.interp(b[:, c] / 64, np.arange(256), cv[c]) for c in range(3)], 1) / 16384 @ P.T, 0, 1)
    return r


for name, fp, boost in FITS:
    f = json.load(open(fp)); T = target_of(f['presets'][0])
    cv = [np.array(c) for c in f['presets'][0]['curves']]
    if 'vision3' in fp or 'classicneg' in fp:
        cv = [expand(knots_of(c)) for c in cv]
    P = np.array(f['post_q512']) / 512
    cf.NEUTRAL = 3.0
    L, w, _ = samples(boost=boost); tl = lab(T(L)); sw = np.sqrt(w / w.mean())
    M = np.array(f['matrix'])
    n = np.sqrt(len(L))     # LUTSmith's penalties (weakest seam weight, ridge, +-1.85 range) on its mean-dE scale

    def res(d):
        e = sw * colour.delta_E(lab(ours(f, cv, P, 1024 * ls.hue_matrices(d.reshape(12, 3)))(L)), tl, method='CIE 2000')
        pen = np.r_[np.sqrt(ls.HUE_KINKS[0] / 12) * KINK @ d, np.sqrt(ls.HUE_RIDGE / 12) * d,
                    np.sqrt(ls.HUE_RANGE) * np.maximum(np.abs(M0 + d @ B) - ls.HUE_LIMIT, 0)]
        return np.r_[e, n * pen]
    d = least_squares(res, np.zeros(36), x_scale=0.05, max_nfev=40).x
    Hq = ls.hue_quantise(ls.hue_matrices(d.reshape(12, 3)))
    a, b = scores(ours(f, cv, P), T), scores(ours(f, cv, P, Hq), T)
    print(f'{name:13s} ours {" / ".join(f"{x:.2f}" for x in a)} -> + hue sectors {" / ".join(f"{x:.2f}" for x in b)}', flush=True)
