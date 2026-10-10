"""Colour accuracy of other GR film mods vs ours (films v11), all against the same spektrafilm targets, mean dE2000.

  * ../gr3-v210-four-films-v9-2.persistence-fix.experimental.bin (third-party GR III 2.10 build): adds tones 25-28
    (Gold 200, Cine800T, Ektar 100, Metropolis). Its look is read by emulating ImageTuning Make (run_tuning.py):
    CCA0 -> look matrix (CCA0 = M STD_LOOK^-1 C_std), composite gamma tables, CSP (stock there).
  * Ricoh-GRMod (GR IV tool, core/src/color/camera.ts + fit.ts): slot = curve_c(S(M1 S^-1(standard))), M1 rows sum to 1,
    17-knot display-domain curves, CIE76 Lab residuals with soft_l1 (f_scale 3). Refitted here on our training set
    (cube_fit.samples, same weights) with that model and objective, started from our v11 look.
  * ours: films v11 build, also read by emulation.
Held-out sets: 8000 random colours (seed 99), Munsell (4950 in-gamut, -1/0/+1 EV), ColorChecker (-1/0/+1 EV,
was in the training set), photo-v10 camera chart inputs (252).
Usage (from re-tools): work/compare/compare.py"""
import sys, json; sys.path.insert(0, '.'); sys.path.insert(0, 'work/films_v8')
import numpy as np, colour, glob
from scipy.optimize import least_squares
import cube_fit as cf
from cube_fit import STD_LOOK, K, samples, load_target, M_from, de2000
from run_tuning import setup, make
from gr4_editor.codec.container import inspect_container
from gr4_editor.codec.frames import decode_payload
from chart import load

SRGB = colour.RGB_COLOURSPACES['sRGB']
lab = lambda x: colour.XYZ_to_Lab(colour.sRGB_to_XYZ(np.clip(x, 0, 1)))


def rtos(p):
    d = open(p, 'rb').read(); i = inspect_container(d)
    x, _ = decode_payload(d[128:i['payload_end']], i['decoded_size']); return bytes(x[0x10870:0x10c5e30])


def emulate(rt, tone):
    e, obj, info, si = setup(stage=1, rtos=rt); g = e.r32(obj + 0x17c)
    out = make(e, obj, info, si, tone, stage=1)
    comp = [np.frombuffer(bytes(e.u.mem_read(g + o, 512)), '<u2').astype(float) for o in (0x2a08, 0x2c08, 0x2e08)]
    s12 = lambda a, n, bits, sh: (lambda v: np.where(v >= 1 << (bits - 1), v - (1 << bits), v))(
        np.frombuffer(out[a:a + 2 * n], '<u2').astype(int) & ((1 << bits) - 1))
    return s12(0x140, 9, 12, 0).reshape(3, 3), comp, s12(0x120 + 0x1180, 9, 9, 0).reshape(3, 3)


def fw_look(rt, tone, C_std, H_std):
    C, comp, H = emulate(rt, tone)
    M = C @ np.linalg.inv(C_std) @ STD_LOOK
    P = np.linalg.inv(H_std) @ H
    def f(L):
        lin = np.clip(K * (L @ M.T), 0, 255)
        return np.clip(np.stack([np.interp(lin[:, c], np.arange(256), comp[c]) for c in range(3)], 1) / 16384 @ P.T, 0, 1)
    return f


# held-out sets
rng = np.random.default_rng(99)
rnd = rng.random((8000, 3)) ** 2.2 * 2.0 ** rng.uniform(-4, 2, (8000, 1)) * 0.6
mun = []
for _, xyY in colour.MUNSELL_COLOURS["all"]:
    xyz = colour.xyY_to_XYZ(np.array([xyY[0], xyY[1], xyY[2] / 100]))
    xyz = colour.chromatic_adaptation(xyz, colour.xy_to_XYZ(colour.CCS_ILLUMINANTS['CIE 1931 2 Degree Standard Observer']['C']),
                                      colour.xy_to_XYZ(SRGB.whitepoint))
    mun.append(colour.XYZ_to_RGB(xyz, SRGB, apply_cctf_encoding=False))
mun = np.array(mun); mun = mun[(mun.min(1) >= 0) & (mun.max(1) <= 1)]
mun = np.concatenate([mun * 2.0 ** ev for ev in (-1, 0, 1)])
_, _, cc = samples(seed=7); cc = np.concatenate([cc * 2.0 ** ev for ev in (-1, 0, 1)])
bg = lambda idx: np.interp(np.clip(idx, 0, 255), np.arange(256), cf.BASE) / 16384
Js, Ls = load('../photo-v10/R0011890')
lin0, std = Ls.reshape(-1, 3), Js.reshape(-1, 3)
ok = (std.max(1) < 0.95) & (std.min(1) > 0.03)
A = least_squares(lambda a: (bg(lin0[ok] @ a.reshape(3, 3).T) - std[ok]).ravel(), (STD_LOOK * 40).ravel()).x.reshape(3, 3)
chart = lin0 @ (np.linalg.inv(STD_LOOK) @ A).T * 0.18 / 7.8
SETS = [('random', rnd), ('Munsell', mun), ('ColorChecker', cc), ('camera chart', chart)]


def score(f, T):
    r = []
    for _, X in SETS:
        t = T(X); u = t.min(1) > 0.02
        r.append(de2000(f(X)[u], t[u]).mean())
    return np.array(r)


def grmod_fit(T, M0, cv0, boost):
    """GR Mod's slot model and objective (CIE76 Lab, soft_l1 f_scale 3) on our training set, started from v11."""
    cf.NEUTRAL = 3.0
    L, w, _ = samples(boost=boost)
    tl = lab(T(L)); sw = np.sqrt(w / w.mean())[:, None]
    KN = np.linspace(0, 1, 17)
    def f_of(p):
        M = M_from(p[:6]); kn = np.maximum.accumulate(np.clip(p[6:].reshape(3, 17), 0, 1), 1)
        def f(X):
            d = np.clip(K * (X @ M.T), 0, 255)
            d = np.stack([np.interp(d[:, c], np.arange(256), cf.BASE) for c in range(3)], 1) / 16384
            return np.stack([np.interp(d[:, c], KN, kn[c]) for c in range(3)], 1)
        return f
    off = lambda A: np.array([A[r, j] for r in range(3) for j in range(3) if j != r])
    k0 = np.array([np.interp(KN * 256, np.arange(256), np.array(c) / 16384) for c in cv0])   # curve index = base out / 64
    p0 = np.r_[off(M0), np.maximum.accumulate(k0, 1).ravel()]
    res = lambda p: (sw * (lab(f_of(p)(L)) - tl)).ravel()
    r = least_squares(res, p0, loss='soft_l1', f_scale=3.0, max_nfev=300, x_scale=0.05)
    print(f'    GR Mod refit: cost {least_squares(res, p0, max_nfev=1).cost if False else 0.5*np.sum(3**2*2*(np.sqrt(1+(res(p0)/3)**2)-1)):.0f} -> {r.cost:.0f}, nfev {r.nfev}')
    return f_of(r.x)


if __name__ == '__main__':
    stock, ours, exp = rtos('../fwdc239b.bin'), rtos('work/films_v11/fwdc239b.bin'), \
        rtos('../gr3-v210-four-films-v9-2.persistence-fix.experimental.bin')
    C_std, _, H_std = emulate(stock, 11)
    print('CSP stock', H_std.tolist())
    films = [('Ektar 100', 'ektar_b1n3', 12, 27, 1), ('Gold 200', 'gold_b4n3', 19, 25, 4)]
    print(f'{"":34s}' + ''.join(f'{n:>14s}' for n, _ in SETS))
    for name, stem, our_tone, exp_tone, boost in films:
        fit = json.load(open(f'work/films_v11/fits/{stem}_lab.json'))
        T = load_target(fit['presets'][0]['spec'], 'vlog', 0)
        rows = [('stock Standard', fw_look(stock, 11, C_std, H_std)),
                ('third-party GR III build', fw_look(exp, exp_tone, C_std, H_std)),
                ('GR Mod method (refit)', grmod_fit(T, np.array(fit['matrix']), fit['presets'][0]['curves'], boost)),
                ('ours v11', fw_look(ours, our_tone, C_std, H_std))]
        print(name)
        for rn, f in rows:
            print(f'  {rn:32s}' + ''.join(f'{v:14.2f}' for v in score(f, T)))
        # best spektrafilm target for the third-party look (any print, -1..+1 EV)
        f = rows[1][1]; best = None
        slug = 'ektar100' if 'Ektar' in name else 'gold200'
        cubes = glob.glob(f'scratch/luts*/*{slug}*/*.cube')
        for cube in cubes:
            for ev in (-1, -0.5, 0, 0.5, 1):
                s = score(f, load_target(cube, 'vlog', ev))
                if best is None or s[:2].mean() < best[0][:2].mean():
                    best = (s, cube.split('/')[-1], ev)
        print(f'  third-party vs its closest spektrafilm target ({best[1]}, {best[2]:+} EV):' +
              ''.join(f'{v:6.2f}' for v in best[0]))
